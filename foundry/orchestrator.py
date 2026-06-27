# foundry/orchestrator.py
# -----------------------------------------------------------------------------
# The conductor. Builds the three AutoGen agents + a UserProxyAgent into a
# GroupChat (registered conceptually in Azure AI Foundry), and exposes the
# high-level pipeline the FastAPI app calls.
#
# Pipeline (per spec):
#   1. UserProxy (Orchestrator) triggers a scrape for a company.
#   2. JobScraperAgent fetches jobs.
#   3. FuzzyMatchAgent filters for target roles + normalizes locations.
#   4. Results stored to SQLite.
#   5. On demand: ResumeAnalysisAgent analyzes a specific JD.
#
# Live vs stub:
#   * LIVE (Azure OpenAI creds present): real GroupChat with LLM turn-taking is
#     available; we still execute the deterministic tools directly for speed and
#     reliability, but the agents are real and registered.
#   * STUB: agents print "[STUB] ..."; the deterministic tools still run, so the
#     whole scrape->match->store flow works offline for the demo.
# -----------------------------------------------------------------------------

import time

import config
import database
from agents import matcher_agent, resume_agent, scraper_agent
from foundry.client import (
    OPENAI_STUB_MODE,
    deploy_to_foundry,
    get_azure_openai_config,
    get_foundry_client,
)


class RoleRadarOrchestrator:
    """Holds the agent fleet and runs the scrape/match/store pipeline."""

    def __init__(self):
        # Touch the Foundry client so its stub/live banner prints at startup.
        get_foundry_client()
        # Build (or stub) the three AutoGen agents.
        self.scraper = scraper_agent.build_agent()
        self.matcher = matcher_agent.build_agent()
        self.resume = resume_agent.build_agent()
        self.user_proxy = self._build_user_proxy()
        self.groupchat = self._build_groupchat()
        # Announce the (stubbed) Foundry deployment of the agent workflow.
        deploy_to_foundry()

    # -- AutoGen wiring -------------------------------------------------------
    def _build_user_proxy(self):
        """The Orchestrator/UserProxyAgent that drives the conversation."""
        if OPENAI_STUB_MODE:
            print("[STUB] Orchestrator UserProxyAgent would be created here")
            return None
        import autogen
        return autogen.UserProxyAgent(
            name="Orchestrator",
            human_input_mode="NEVER",
            max_consecutive_auto_reply=3,
            code_execution_config={"work_dir": "workspace", "use_docker": False},
        )

    def _build_groupchat(self):
        """Assemble the GroupChat of all agents (live only)."""
        if OPENAI_STUB_MODE:
            print("[STUB] AutoGen GroupChat would register: "
                  "JobScraperAgent, FuzzyMatchAgent, ResumeAnalysisAgent, Orchestrator")
            return None
        import autogen
        agents = [self.user_proxy, self.scraper, self.matcher, self.resume]
        groupchat = autogen.GroupChat(agents=agents, messages=[], max_round=12)
        manager = autogen.GroupChatManager(
            groupchat=groupchat,
            llm_config={"config_list": [get_azure_openai_config()], "timeout": 60},
        )
        return manager

    # -- The pipeline ---------------------------------------------------------
    def scrape_one(self, company_row):
        """Run scrape -> match -> store for a single company row (dict).

        Returns a summary dict: {company, jobs_found, new_jobs, matches, error}.
        Never raises — any failure is captured in the 'error' field and the
        company's last_error column, so a full run never crashes here.
        """
        name = company_row["name"]
        url = company_row["careers_url"]
        cid = company_row["id"]
        summary = {"company": name, "jobs_found": 0, "new_jobs": 0,
                   "matches": 0, "error": None}

        try:
            # Step 2: ScraperAgent fetches jobs (tool call).
            import json
            jobs = json.loads(scraper_agent.run_scrape_tool(name, url))

            # Step 3: MatcherAgent annotates match + location fields.
            keywords = database.get_role_keywords()
            jobs = matcher_agent.run_match_tool(jobs, keywords=keywords)

            # Warn if the generic scraper barely found anything (spec rule).
            if len(jobs) < 3:
                print(f"[WARN] {name}: only {len(jobs)} jobs found — "
                      "may need playwright or a URL update")

            # Step 4: store each job (dedup by URL).
            new_count, match_count = 0, 0
            for job in jobs:
                job["company_id"] = cid
                is_new = database.upsert_job(job)
                if is_new:
                    new_count += 1
                if job.get("is_match"):
                    match_count += 1
                    # Fetch the full JD for matched jobs so resume analysis works.
                    self._maybe_fetch_description(job)

            summary.update(jobs_found=len(jobs), new_jobs=new_count, matches=match_count)
            database.mark_company_scraped(cid, error=None)

        except Exception as e:
            # Capture, log, continue. One company never breaks the run.
            err = f"{type(e).__name__}: {e}"
            print(f"[ERROR] {name}: {err}")
            summary["error"] = err
            database.mark_company_scraped(cid, error=err)

        return summary

    def _maybe_fetch_description(self, job):
        """Fetch + store the JD text for a matched job (best-effort)."""
        import scraper
        # Find the stored job by URL to attach the description (direct lookup).
        stored = database.get_job_by_url(job["url"])
        if not stored or stored.get("description"):
            return
        desc = scraper.fetch_job_description(job["url"])
        if desc:
            database.set_job_description(stored["id"], desc)

    def run_full_scrape(self, only_company_id=None, note=None):
        """Scrape all active companies (or just one). Returns a run summary.

        only_company_id: if set, scrape just that company (used by the
        single-company and 'Test Anthropic Only' endpoints).
        """
        run_id = database.start_run(note=note)

        if only_company_id is not None:
            companies = [database.get_company(only_company_id)]
        else:
            companies = database.list_companies(active_only=True)

        results = []
        total_jobs, total_matches = 0, 0
        for comp in companies:
            if not comp:
                continue
            res = self.scrape_one(comp)
            results.append(res)
            total_jobs += res["jobs_found"]
            total_matches += res["matches"]
            # Politeness delay between companies (skip after the last one).
            if comp is not companies[-1]:
                time.sleep(config.SCRAPE_DELAY_SECONDS)

        database.finish_run(run_id, len(companies), total_jobs, total_matches)
        return {
            "run_id": run_id,
            "companies_scraped": len(companies),
            "jobs_found": total_jobs,
            "matches": total_matches,
            "results": results,
        }

    def analyze_resume(self, jd_text, resume_text):
        """On-demand ResumeAnalysisAgent call."""
        return resume_agent.analyze(jd_text, resume_text)


# Singleton used across the FastAPI app.
_orchestrator = None


def get_orchestrator():
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = RoleRadarOrchestrator()
    return _orchestrator
