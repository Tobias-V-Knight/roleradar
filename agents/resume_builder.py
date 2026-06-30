# agents/resume_builder.py
# -----------------------------------------------------------------------------
# Two responsibilities:
#   1. generate_content() — ask GPT-4o to produce ATS-optimized projects and
#      skills as structured JSON, sourced strictly from the master CV.
#   2. build_docx() — open the base resume DOCX as a template and replace only
#      the projects and skills sections in-place, then return the modified file
#      as bytes for download. Experience bullets are left untouched — edits to
#      those are surfaced as suggestions in the analysis step instead.
# -----------------------------------------------------------------------------

import json

from foundry.client import OPENAI_STUB_MODE, get_azure_openai_config

SYSTEM_MSG = (
    "You are an expert ATS optimizer and resume writer. Given a master CV, a job "
    "description, and the candidate's base resume, select and describe the best "
    "projects and curate the skills list to maximize ATS keyword coverage for this "
    "specific job. Use ONLY content that appears in the master CV — never fabricate. "
    "Return ONLY valid JSON."
)

USER_TEMPLATE = """JOB DESCRIPTION:
{jd_text}

MASTER CV (all available experience — the only content you may draw from):
{cv_text}

BASE RESUME (projects and skills sections will be replaced; experience section is kept as-is):
{base_resume_text}

Return JSON with exactly these fields:
{{
  "projects": [
    {{"name": "<project name>", "description": "<1-2 sentence description from CV>"}}
  ],
  "skills_tools": "<comma-separated tools, keep under 120 characters total>",
  "skills_methods": "<comma-separated methods, keep under 210 characters total>",
  "ats_keywords": ["<every ATS-critical keyword/phrase extracted from the JD>"],
  "ats_matched": ["<keywords from ats_keywords that now appear in the generated skills/projects>"],
  "ats_missing_from_cv": ["<JD keywords that cannot be supported by anything in the master CV>"]
}}

Rules:
- SKILLS ARE THE TOP PRIORITY: scan the JD for every tool, technology, method,
  framework, and domain term a recruiter would boolean-search for. Include ALL of
  them in skills_tools or skills_methods if they appear anywhere in the master CV
  or are demonstrably used in the listed experience. Use EXACT JD phrasing where
  possible (e.g. "Product-Led Growth" not just "growth", "A/B Testing" not just
  "testing").
- Single-page constraint: keep skills_tools under 120 characters and
  skills_methods under 210 characters. Prioritize ATS-critical JD keywords over
  generic terms if you must trim.
- Projects: pick 2-3 from the master CV's actual projects section that best
  demonstrate the skills this JD requires. You may adjust project titles to echo
  JD language, but keep them true to the actual project content — no large
  stretches. Do NOT repackage or duplicate content that already appears in the
  experience/work history section — projects must be distinct entries from the CV,
  not reworded job duties.
- ats_missing_from_cv: be honest about gaps — list JD keywords that cannot be
  justified by anything in the CV. This is the user's gap signal.
- Skills must only include items present in the master CV or demonstrably used
  in the listed experience.
"""


def generate_content(jd_text: str, cv_text: str, base_resume_text: str) -> dict:
    """Call GPT-4o to produce ATS-optimized projects + skills. Stubs if no creds."""
    if OPENAI_STUB_MODE:
        print("[STUB] resume_builder: returning mock content (no Azure OpenAI creds)")
        return _stub_content()

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
                {"role": "system", "content": SYSTEM_MSG},
                {"role": "user", "content": USER_TEMPLATE.format(
                    jd_text=jd_text[:5000],
                    cv_text=cv_text[:8000],
                    base_resume_text=base_resume_text[:4000],
                )},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
        data["_stub"] = False
        return data
    except Exception as e:
        print(f"[WARN] resume_builder live call failed ({e}); returning stub")
        s = _stub_content()
        s["_error"] = str(e)
        return s


def _stub_content() -> dict:
    return {
        "projects": [
            {
                "name": "[STUB] Growth Experimentation & Causal Analytics",
                "description": "Add Azure OpenAI credentials for real GPT-4o content.",
            }
        ],
        "skills_tools": "[STUB] Python, SQL, Tableau",
        "skills_methods": "[STUB] Growth/Product Analytics, A/B Testing, Causal Inference",
        "ats_keywords": ["SQL", "growth", "experimentation", "dashboard"],
        "ats_matched": ["SQL", "growth", "experimentation", "dashboard"],
        "ats_missing_from_cv": [],
        "_stub": True,
    }


# -----------------------------------------------------------------------------
# DOCX builder — replaces projects and skills only; experience is untouched
# -----------------------------------------------------------------------------

def _set_para_text(para, new_text: str):
    """Replace a paragraph's visible text while preserving its run formatting."""
    if not para.runs:
        para.add_run(new_text)
        return
    para.runs[0].text = new_text
    for run in para.runs[1:]:
        run.text = ""


def _all_paragraphs_in_order(doc):
    """
    Yield every paragraph in document body order, including those inside tables.
    python-docx's doc.paragraphs skips table cells, which many resume templates
    use to align company names (left) against dates (right).
    """
    from docx.text.paragraph import Paragraph
    from docx.table import Table

    def _from_element(el):
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if tag == "p":
            yield Paragraph(el, doc)
        elif tag == "tbl":
            tbl = Table(el, doc)
            for row in tbl.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        yield para
        for child in el:
            child_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if child_tag not in ("p", "tbl"):
                yield from _from_element(child)

    for child in doc.element.body:
        yield from _from_element(child)


def build_docx(base_docx_bytes: bytes, content_json: dict) -> bytes:
    """
    Open the base resume DOCX as a template, replace only the projects and
    skills sections in-place, return modified bytes.
    Experience bullets are intentionally left unchanged — targeted edits for
    those are surfaced in the analysis step as suggestions for the user.
    """
    from io import BytesIO
    from docx import Document

    projects: list = content_json.get("projects", [])
    skills_tools: str = content_json.get("skills_tools", "")
    skills_methods: str = content_json.get("skills_methods", "")

    doc = Document(BytesIO(base_docx_bytes))

    section = None
    project_paras: list = []
    skill_paras: list = []

    SECTION_HEADERS = {"EDUCATION", "EXPERIENCE", "DATA SCIENCE PROJECTS", "TECHNICAL SKILLS"}

    for para in _all_paragraphs_in_order(doc):
        text = para.text.strip()
        text = text.lstrip("`'''""").strip()
        upper = text.upper()

        if upper in SECTION_HEADERS:
            section = upper
            continue

        if not text:
            continue

        if section == "DATA SCIENCE PROJECTS":
            project_paras.append(para)
        elif section == "TECHNICAL SKILLS":
            skill_paras.append(para)

    # --- Replace project paragraphs ---
    for i, para in enumerate(project_paras):
        if i < len(projects):
            proj = projects[i]
            if len(para.runs) >= 2:
                para.runs[0].text = proj["name"] + ": "
                para.runs[1].text = proj["description"]
                for run in para.runs[2:]:
                    run.text = ""
            else:
                _set_para_text(para, proj["name"] + ": " + proj["description"])
        else:
            _set_para_text(para, "")

    # --- Replace skills lines ---
    for para in skill_paras:
        text = para.text.strip().lower()
        if text.startswith("tools:"):
            if len(para.runs) >= 2:
                para.runs[0].text = "Tools: "
                para.runs[1].text = skills_tools
                for run in para.runs[2:]:
                    run.text = ""
            else:
                _set_para_text(para, "Tools: " + skills_tools)
        elif text.startswith("methods:"):
            if len(para.runs) >= 2:
                para.runs[0].text = "Methods: "
                para.runs[1].text = skills_methods
                for run in para.runs[2:]:
                    run.text = ""
            else:
                _set_para_text(para, "Methods: " + skills_methods)

    out = BytesIO()
    doc.save(out)
    out.seek(0)
    return out.read()
