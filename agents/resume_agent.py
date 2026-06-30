# agents/resume_agent.py
# -----------------------------------------------------------------------------
# AutoGen ResumeAnalysisAgent.
#
# Given a job description + a resume, returns a structured ATS-aware fit
# analysis: fit score, keyword coverage (present/missing), deal breakers,
# role-anchored experience edits, and an apply recommendation with reasoning.
# -----------------------------------------------------------------------------

import json

from foundry.client import (
    OPENAI_STUB_MODE,
    get_azure_openai_config,
)

AGENT_NAME = "ResumeAnalysisAgent"

SYSTEM_MESSAGE = (
    "You are an expert ATS analyst and technical recruiter. Your job is to identify "
    "whether a resume will pass ATS keyword filters for a specific job description, "
    "flag hard-requirement gaps honestly, and provide specific role-anchored edits "
    "that would improve keyword coverage without fabricating experience. "
    "Return ONLY valid JSON."
)

USER_TEMPLATE = """JOB DESCRIPTION:
{jd_text}

RESUME:
{resume_text}

Return JSON with exactly these fields:
{{
  "fit_score": <0-100 integer>,
  "fit_summary": "<2 sentence overall assessment anchored to THIS specific JD>",
  "apply_recommendation": "Strong Apply | Apply | Stretch | Skip",
  "recommendation_reason": "<1-2 sentences explaining why — be direct>",
  "ats_keywords": ["<every ATS-critical keyword/phrase a recruiter would boolean-search for>"],
  "ats_present": ["<subset of ats_keywords that appear in or are clearly demonstrated by the resume>"],
  "ats_missing": ["<subset of ats_keywords absent from the resume>"],
  "deal_breakers": ["<hard requirements in the JD the candidate clearly cannot demonstrate — be honest; empty array if none>"],
  "strengths": ["<strength 1 tied to a specific JD requirement>", "<strength 2>"],
  "experience_edits": [
    {{
      "role": "<COMPANY NAME – Job Title, exactly as it appears in the resume>",
      "action": "<specific instruction: which bullet to target and what keyword/phrase to add>",
      "suggested_rewrite": "<the full rewritten bullet incorporating the missing keyword naturally>"
    }}
  ]
}}

Rules:
- ats_keywords: extract every tool, technology, method, framework, domain term, and exact phrase a recruiter would search for (e.g. "Product-Led Growth", "GTM", "SQL", "experimentation").
- ats_present: only include keywords clearly evidenced in the resume — do not give credit for vague proximity.
- deal_breakers: be honest. If the JD requires 3+ years of dedicated PLG ownership and the resume shows none, say so. This helps the user decide whether to apply at all.
- experience_edits: provide 2-4 specific, role-anchored edits ONLY where the keyword is a genuinely accurate description of the work already described. If a bullet is about real operational GPS data, do not suggest adding "simulation" — that would be a lie. If a bullet is about HR records, do not add "time series forecasting" unless forecasting actually happened. Only suggest adding a keyword when it is an honest, alternative framing of work that was already done. If no honest edit exists for a missing keyword, omit it from experience_edits entirely — it belongs in ats_missing, not forced into the resume.
- strengths: tie each strength to a concrete JD requirement, not a generic statement.
"""


def _stub_analysis():
    return {
        "fit_score": 72,
        "fit_summary": "[STUB] Mock analysis — set AZURE_OPENAI_API_KEY and "
                       "AZURE_OPENAI_ENDPOINT for a real GPT-4o assessment.",
        "apply_recommendation": "Apply",
        "recommendation_reason": "[STUB] Strong analytical background but missing explicit PLG/GTM language.",
        "ats_keywords": ["SQL", "growth analytics", "PLG", "GTM", "experimentation", "dashboard", "data analysis"],
        "ats_present": ["SQL", "growth analytics", "experimentation", "dashboard", "data analysis"],
        "ats_missing": ["PLG", "GTM"],
        "deal_breakers": [],
        "strengths": [
            "[STUB] Strong causal inference and experimentation background matches JD requirement for A/B testing.",
            "[STUB] SQL + Python + Tableau stack aligns with the core tool requirements.",
        ],
        "experience_edits": [
            {
                "role": "CARLSON ANALYTICS LAB – Student Data Scientist",
                "action": "Add 'Product-Led Growth' language to the first bullet about growth performance",
                "suggested_rewrite": "[STUB] Built Python, SQL, and Tableau dashboards to monitor PLG metrics and regional growth performance, identifying $32M in revenue opportunities and enabling stakeholders to compare performance by region, seasonality, and competitor benchmarks.",
            }
        ],
        "_stub": True,
    }


def analyze(jd_text: str, resume_text: str) -> dict:
    """Run the resume-vs-JD analysis. Returns the parsed JSON dict."""
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
            model=cfg["model"],
            messages=[
                {"role": "system", "content": SYSTEM_MESSAGE},
                {"role": "user", "content": USER_TEMPLATE.format(
                    jd_text=jd_text[:12000], resume_text=resume_text[:12000])},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
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
