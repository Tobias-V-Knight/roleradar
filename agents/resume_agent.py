# agents/resume_agent.py
# -----------------------------------------------------------------------------
# AutoGen ResumeAnalysisAgent.
#
# Given a job description + a resume, asks GPT-4o (via Azure OpenAI) for a
# structured fit analysis: fit score, gaps, strengths, three bullet rewrites,
# and an apply recommendation.
#
# This is the one agent that genuinely needs the LLM, so it has a real STUB
# fallback: if no Azure OpenAI creds are configured it returns mock data with
# every field prefixed "[STUB]" so the UI flow still demos end-to-end.
# -----------------------------------------------------------------------------

import json

from foundry.client import (
    OPENAI_STUB_MODE,
    get_azure_openai_config,
)

AGENT_NAME = "ResumeAnalysisAgent"

SYSTEM_MESSAGE = (
    "You are an expert technical recruiter and career coach. Analyze the fit "
    "between a job description and a resume. Return ONLY valid JSON."
)

USER_TEMPLATE = """JOB DESCRIPTION:
{jd_text}

RESUME:
{resume_text}

Return JSON with exactly these fields:
{{
  "fit_score": <0-100 integer>,
  "fit_summary": "<2 sentence overall assessment>",
  "gaps": ["<gap 1>", "<gap 2>", "<gap 3>"],
  "strengths": ["<strength 1>", "<strength 2>"],
  "bullet_rewrites": [
    {{"original": "<existing bullet or null>", "rewritten": "<improved bullet targeting this JD>"}},
    {{"original": "...", "rewritten": "..."}},
    {{"original": "...", "rewritten": "..."}}
  ],
  "apply_recommendation": "Strong Apply | Apply | Stretch | Skip"
}}"""


def _stub_analysis():
    """Mock response used when no Azure OpenAI credentials are available."""
    return {
        "fit_score": 72,
        "fit_summary": "[STUB] Mock analysis — set AZURE_OPENAI_API_KEY and "
                       "AZURE_OPENAI_ENDPOINT for a real GPT-4o assessment.",
        "gaps": [
            "[STUB] Production ML deployment experience",
            "[STUB] Customer-facing solutions delivery",
            "[STUB] Specific cloud platform certification",
        ],
        "strengths": [
            "[STUB] Strong applied analytics + Gen AI project portfolio",
            "[STUB] Demonstrated end-to-end build ownership",
        ],
        "bullet_rewrites": [
            {"original": None,
             "rewritten": "[STUB] Built an agentic job-intelligence pipeline "
                          "(AutoGen + Azure AI Foundry) scraping 35+ companies."},
            {"original": "[STUB] Did data analysis",
             "rewritten": "[STUB] Delivered fuzzy-matched role recommendations "
                          "with rapidfuzz, cutting manual job search ~2 hrs/day."},
            {"original": "[STUB] Worked on a school project",
             "rewritten": "[STUB] Shipped a FastAPI + SQLite dashboard with "
                          "live resume-vs-JD gap analysis via GPT-4o."},
        ],
        "apply_recommendation": "Apply",
        "_stub": True,
    }


def analyze(jd_text: str, resume_text: str) -> dict:
    """Run the resume-vs-JD analysis. Returns the parsed JSON dict.

    Live path uses the Azure OpenAI SDK against the configured endpoint.
    Any failure (no creds, network, bad JSON) degrades to the labeled stub so
    the endpoint never 500s during a demo.
    """
    if OPENAI_STUB_MODE:
        print(f"[STUB] {AGENT_NAME}: returning mock analysis (no Azure OpenAI creds)")
        return _stub_analysis()

    cfg = get_azure_openai_config()
    try:
        from openai import AzureOpenAI

        client = AzureOpenAI(
            api_key=cfg["api_key"],
            api_version=cfg["api_version"],
            azure_endpoint=cfg["base_url"],
        )
        resp = client.chat.completions.create(
            model=cfg["model"],  # Azure deployment name
            messages=[
                {"role": "system", "content": SYSTEM_MESSAGE},
                {"role": "user", "content": USER_TEMPLATE.format(
                    jd_text=jd_text[:12000], resume_text=resume_text[:12000])},
            ],
            temperature=0.4,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
        data = json.loads(content)
        data["_stub"] = False
        return data
    except Exception as e:
        print(f"[WARN] {AGENT_NAME} live call failed ({e}); returning stub")
        stub = _stub_analysis()
        stub["fit_summary"] = f"[STUB] Live call failed: {e}"
        return stub


def build_agent():
    """Build the AutoGen AssistantAgent for resume analysis (or stub marker)."""
    if OPENAI_STUB_MODE:
        print(f"[STUB] {AGENT_NAME} would be created as an AutoGen AssistantAgent "
              "wired to Azure OpenAI GPT-4o")
        return None

    import autogen

    llm_config = {"config_list": [get_azure_openai_config()], "timeout": 60}
    return autogen.AssistantAgent(
        name=AGENT_NAME,
        system_message=SYSTEM_MESSAGE,
        llm_config=llm_config,
    )
