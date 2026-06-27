# main.py
# -----------------------------------------------------------------------------
# FastAPI application: REST API + static frontend + APScheduler background job.
#
# Run with:  python main.py    (or: uvicorn main:app --reload)
# Then open: http://localhost:8000
# -----------------------------------------------------------------------------

import threading
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import database
from foundry.orchestrator import get_orchestrator

app = FastAPI(title="RoleRadar", version="1.0")

# A simple in-memory status object so the UI can poll scrape progress.
SCRAPE_STATUS = {"running": False, "last_run": None, "message": "idle"}

# A lock so two scrape triggers can't run the pipeline concurrently.
_scrape_lock = threading.Lock()


# -----------------------------------------------------------------------------
# Pydantic request bodies
# -----------------------------------------------------------------------------
class CompanyIn(BaseModel):
    name: str
    careers_url: str
    tier: int = 1


class RoleIn(BaseModel):
    keyword: str


class LocationIn(BaseModel):
    city: str
    state: str = "US"


class ResumeIn(BaseModel):
    resume_text: str


# -----------------------------------------------------------------------------
# Startup: init DB, build orchestrator, start scheduler
# -----------------------------------------------------------------------------
scheduler = BackgroundScheduler()


@app.on_event("startup")
def startup():
    database.init_db()
    # Build the orchestrator once (prints the stub/live banners).
    get_orchestrator()
    # Schedule a recurring full scrape every N hours.
    scheduler.add_job(
        _run_full_scrape_job,
        "interval",
        hours=config.SCRAPE_INTERVAL_HOURS,
        id="full_scrape",
        replace_existing=True,
    )
    scheduler.start()
    print(f"[RoleRadar] started. Scheduled full scrape every "
          f"{config.SCRAPE_INTERVAL_HOURS}h. Open http://localhost:8000")


@app.on_event("shutdown")
def shutdown():
    scheduler.shutdown(wait=False)


# -----------------------------------------------------------------------------
# Scrape runners (threaded so the HTTP request returns immediately)
# -----------------------------------------------------------------------------
def _run_full_scrape_job(only_company_id=None, note="scheduled"):
    """Run a scrape, guarding against overlapping runs and updating status."""
    if not _scrape_lock.acquire(blocking=False):
        print("[RoleRadar] scrape already running; skipping new trigger")
        return
    SCRAPE_STATUS.update(running=True, message=f"scraping ({note})...")
    try:
        result = get_orchestrator().run_full_scrape(
            only_company_id=only_company_id, note=note
        )
        SCRAPE_STATUS.update(
            running=False,
            last_run=database.latest_run(),
            message=f"done: {result['matches']} matches across "
                    f"{result['companies_scraped']} companies",
        )
    except Exception as e:
        SCRAPE_STATUS.update(running=False, message=f"error: {e}")
        print(f"[ERROR] scrape job failed: {e}")
    finally:
        _scrape_lock.release()


def _trigger_async(only_company_id=None, note="manual"):
    """Kick off a scrape in a background thread and return immediately."""
    t = threading.Thread(
        target=_run_full_scrape_job,
        kwargs={"only_company_id": only_company_id, "note": note},
        daemon=True,
    )
    t.start()


# -----------------------------------------------------------------------------
# Company endpoints
# -----------------------------------------------------------------------------
@app.get("/api/companies")
def get_companies():
    return database.list_companies()


@app.post("/api/companies")
def post_company(body: CompanyIn):
    new_id = database.add_company(body.name, body.careers_url, body.tier)
    return {"id": new_id}


@app.delete("/api/companies/{company_id}")
def remove_company(company_id: int):
    database.delete_company(company_id)
    return {"ok": True}


@app.patch("/api/companies/{company_id}/toggle")
def toggle_company(company_id: int):
    database.toggle_company(company_id)
    return {"ok": True}


# -----------------------------------------------------------------------------
# Role endpoints
# -----------------------------------------------------------------------------
@app.get("/api/roles")
def get_roles():
    return database.list_roles()


@app.post("/api/roles")
def post_role(body: RoleIn):
    database.add_role(body.keyword)
    return {"ok": True}


@app.delete("/api/roles/{role_id}")
def remove_role(role_id: int):
    database.delete_role(role_id)
    return {"ok": True}


# -----------------------------------------------------------------------------
# Location endpoints
# -----------------------------------------------------------------------------
@app.get("/api/locations")
def get_locations():
    return database.list_locations()


@app.post("/api/locations")
def post_location(body: LocationIn):
    database.add_location(body.city, body.state)
    return {"ok": True}


@app.delete("/api/locations/{location_id}")
def remove_location(location_id: int):
    database.delete_location(location_id)
    return {"ok": True}


# -----------------------------------------------------------------------------
# Scraping endpoints
# -----------------------------------------------------------------------------
@app.post("/api/scrape")
def scrape_all():
    """Trigger a full scrape of all active companies (async)."""
    _trigger_async(note="full")
    return {"status": "started", "scope": "all active companies"}


@app.post("/api/scrape/test")
def scrape_test():
    """Validation endpoint: scrape Anthropic only, synchronously.

    Runs inline (not threaded) so the caller gets the result directly — this is
    the 'test one before scaling' checkpoint from the build plan.
    """
    anthropic = database.get_company_by_name("Anthropic")
    if not anthropic:
        raise HTTPException(404, "Anthropic not found in companies table")
    result = get_orchestrator().run_full_scrape(
        only_company_id=anthropic["id"], note="test-anthropic"
    )
    return result


@app.post("/api/scrape/{company_id}")
def scrape_one(company_id: int):
    """Scrape a single company (async)."""
    comp = database.get_company(company_id)
    if not comp:
        raise HTTPException(404, "company not found")
    _trigger_async(only_company_id=company_id, note=f"single:{comp['name']}")
    return {"status": "started", "company": comp["name"]}


@app.get("/api/scrape/status")
def scrape_status():
    return SCRAPE_STATUS


# -----------------------------------------------------------------------------
# Job endpoints
# -----------------------------------------------------------------------------
@app.get("/api/jobs")
def get_jobs(match_only: bool = False, new_only: bool = False,
             tier: Optional[int] = None, city: Optional[str] = None, us_only: bool = True):
    return database.query_jobs(
        match_only=match_only, new_only=new_only, tier=tier,
        city=city, us_only=us_only,
    )


@app.get("/api/jobs/matches")
def get_matches():
    """Shortcut: matched + US-based only."""
    return database.query_jobs(match_only=True, us_only=True)


@app.get("/api/jobs/{job_id}/description")
def get_job_description(job_id: int):
    job = database.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return {"id": job_id, "title": job["title"], "description": job.get("description") or ""}


@app.post("/api/jobs/{job_id}/analyze")
def analyze_job(job_id: int, body: ResumeIn):
    """Run ResumeAnalysisAgent on a stored job's JD vs the supplied resume."""
    job = database.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    jd_text = job.get("description") or job.get("title", "")
    analysis = get_orchestrator().analyze_resume(jd_text, body.resume_text)
    return analysis


# -----------------------------------------------------------------------------
# Run history
# -----------------------------------------------------------------------------
@app.get("/api/runs")
def get_runs():
    return database.list_runs()


# -----------------------------------------------------------------------------
# Frontend (served from /static, index at root)
# -----------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse("static/index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
