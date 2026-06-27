# agents/matcher_agent.py
# -----------------------------------------------------------------------------
# AutoGen FuzzyMatchAgent.
#
# Receives a scraped job list + the target role keywords, runs rapidfuzz over
# each title, and returns the jobs annotated with match score and the keyword
# that triggered the match.
#
# Like the scraper agent, the real matching is deterministic Python (matcher.py)
# so it runs the same in live and stub mode; the AutoGen object exists for the
# orchestration architecture.
# -----------------------------------------------------------------------------

import matcher
from foundry.client import OPENAI_STUB_MODE, get_azure_openai_config

AGENT_NAME = "FuzzyMatchAgent"

SYSTEM_MESSAGE = (
    "You are FuzzyMatchAgent. Given a list of scraped jobs and a list of target "
    "role keywords, you use fuzzy string matching to decide which jobs match. "
    "For each job you report match_score (0-100) and matched_keyword. You call "
    "the fuzzy_match tool to compute scores."
)


def run_match_tool(jobs, keywords=None, threshold=None):
    """Annotate each job with match fields. Returns the enriched list.

    Delegates to matcher.enrich_jobs, which also normalizes locations so the
    downstream storage step has everything it needs in one pass.
    """
    print(f"[{AGENT_NAME}] matching {len(jobs)} jobs against target roles")
    return matcher.enrich_jobs(jobs, keywords=keywords, threshold=threshold)


def build_agent():
    if OPENAI_STUB_MODE:
        print(f"[STUB] {AGENT_NAME} would be created as an AutoGen AssistantAgent "
              "with fuzzy_match registered as a callable tool")
        return None

    import autogen

    llm_config = {"config_list": [get_azure_openai_config()], "timeout": 60}
    return autogen.AssistantAgent(
        name=AGENT_NAME,
        system_message=SYSTEM_MESSAGE,
        llm_config=llm_config,
    )
