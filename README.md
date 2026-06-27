# RoleRadar 📡

A job-posting tracker that scrapes 35+ target companies, fuzzy-matches openings
against your target roles, and gives you live **resume-vs-JD gap analysis** —
built on **AutoGen** agents orchestrated through **Azure AI Foundry**.

*MSBA 6511 — Gen AI for Business, final project.*

---

## Architecture

```
                 ┌─────────────────────────────────────────────┐
                 │      Azure AI Foundry (host / runtime)        │
                 │   ┌───────────── AutoGen GroupChat ────────┐  │
   FastAPI  ───► │   │  Orchestrator (UserProxyAgent)         │  │
   + APScheduler │   │    ├─ JobScraperAgent  → scraper.py    │  │
                 │   │    ├─ FuzzyMatchAgent  → matcher.py    │  │
                 │   │    └─ ResumeAnalysisAgent → GPT-4o      │  │
                 │   └────────────────────────────────────────┘  │
                 └─────────────────────────────────────────────┘
                                     │
                            SQLite (roleradar.db)
                                     │
                       static/index.html (dashboard)
```

**Stub-safe:** with no Azure credentials the app runs in **stub mode** — the
AutoGen agent objects are still built and the full scrape → match → store → UI
flow works locally; only the live LLM calls return mock `[STUB]` data. Add Azure
OpenAI credentials and resume analysis goes live with **no code change**.

---

## Setup

> **⚠️ Python version:** use **Python 3.9–3.12**, NOT 3.13. The pinned
> `pyautogen==0.2.35` (classic AutoGen API) is incompatible with 3.13 — on 3.13
> pip silently installs the wrong AutoGen and the agents break.

### Quick start (macOS / Linux) — one command

```bash
git clone https://github.com/Tobias-V-Knight/roleradar.git
cd roleradar
./setup.sh                # creates .venv, installs deps + Chromium, makes .env
./.venv/bin/python main.py
# open http://localhost:8000
```

`setup.sh` auto-picks a compatible Python (3.9–3.12). The app opens to the
**shared dataset** (`seed.db`, ~9,800 pre-scraped jobs) — no scraping needed.

### Quick start (Windows)

```powershell
git clone https://github.com/Tobias-V-Knight/roleradar.git
cd roleradar
py -3.12 -m venv .venv          # any Python 3.9-3.12
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\playwright install chromium
copy .env.example .env          # then paste the shared key (see below)
.venv\Scripts\python main.py
```

### `.env` (paste the shared team key here)

Tobias shares the Azure key/endpoint **privately** (not in this repo). Paste the
shared values so everyone uses the same live GPT-4o for resume analysis:

```
AZURE_AI_PROJECT_CONNECTION_STRING=   # leave blank — full Foundry deploy is stubbed
AZURE_OPENAI_API_KEY=                 # Foundry → Overview → API Key
AZURE_OPENAI_ENDPOINT=                # e.g. https://<resource>.openai.azure.com/  (the
                                      #  eastus2.api.cognitive.microsoft.com/ endpoint also works)
AZURE_OPENAI_DEPLOYMENT=gpt-4o        # optional; set if your deployment isn't named "gpt-4o"
```

---

## First run (validate before scaling)

This project was built **one company at a time**. Validate the pipeline on
Anthropic before trusting the full run:

1. Open <http://localhost:8000>
2. Go to the **Run History** tab.
3. Click **Test Anthropic Only** — scrapes Anthropic synchronously and reports
   `jobs found / matches`. Expect ≥ 1 job, with AI/Eng roles matched.
4. If that works, click **Run Full Scrape** to hit all active companies.
5. The **Dashboard** populates with matched, US-based roles.

If a scraper fails for a company, the error is logged to that company's row
(Companies tab → ⚠) and the run continues — one bad site never crashes the run.

---

## Adding companies

Companies tab → **Add Company** → paste any careers URL. The dispatcher
auto-detects Greenhouse / Lever / Ashby ATS JSON APIs; otherwise it uses a
generic link-scanner (flagged if it finds < 3 jobs — likely needs a real parser).

---

## File map

| File | Role |
|---|---|
| `main.py` | FastAPI app + APScheduler + endpoints |
| `config.py` | seed companies / roles / locations, thresholds |
| `database.py` | SQLite schema + all queries |
| `scraper.py` | httpx → Playwright fetch + site-specific parsers |
| `matcher.py` | rapidfuzz role matching + location normalization |
| `agents/` | AutoGen JobScraper / FuzzyMatch / ResumeAnalysis agents |
| `foundry/client.py` | stub-safe Azure AI Foundry / OpenAI client |
| `foundry/orchestrator.py` | AutoGen GroupChat + the scrape→match→store pipeline |
| `static/index.html` | single-file dark-mode dashboard (4 tabs) |

---

## Run with Docker (easiest for teammates)

No Python version worries, no `pip install`, no `playwright install` — the image
has everything (incl. Chromium) and the `seed.db` dataset baked in.

```bash
git clone https://github.com/Tobias-V-Knight/roleradar.git
cd roleradar
docker build -t roleradar .
docker run -p 8000:8000 --env-file .env roleradar      # .env: KEY=value, no spaces!
# open http://localhost:8000
```

> **Note:** `docker --env-file` is stricter than `python-dotenv` — use
> `AZURE_OPENAI_API_KEY=value` with **no spaces** around `=`.

---

## Deploy to Azure App Service (Docker container)

The container includes Chromium, so **Playwright works in the cloud** (live
re-scraping of JS-heavy sites), unlike the standard Python runtime.

1. **Build & push the image** to a registry (Azure Container Registry or GitHub
   Container Registry):
   ```bash
   docker build -t roleradar .
   docker tag roleradar ghcr.io/tobias-v-knight/roleradar:latest
   docker push ghcr.io/tobias-v-knight/roleradar:latest
   ```
2. **Create the Web App** (Portal → Web App → *Docker Container*, Linux), or CLI:
   ```bash
   az webapp create -g <rg> -p <plan> -n roleradar \
     --deployment-container-image-name ghcr.io/tobias-v-knight/roleradar:latest
   ```
3. **Set Application Settings** (this is where the key lives — never in the repo):
   `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT=gpt-4o`,
   and `WEBSITES_PORT=8000`.
4. **Keep the weekly scrape alive:** set the plan to **Basic (B1)+** with
   **"Always On"** enabled (the Free tier sleeps and the in-app scheduler won't
   fire), *or* trigger `POST /api/scrape` from an external weekly cron
   (GitHub Action). Schedule is `SCRAPE_INTERVAL_HOURS` (default 168 = weekly).
5. Browse `https://roleradar.azurewebsites.net`.

> If your course Azure tenant blocks App Service or registry creation (same kind
> of policy that restricts model deployments), **Railway** runs the same Dockerfile
> with zero changes as a fallback.

### Hosted Foundry workflow (stubbed)

> **[STUB]** To run the agents as a *hosted* Foundry workflow (vs. local
> APScheduler): provision an Azure AI Foundry project, register the three AutoGen
> agents as a hosted GroupChat via `azure-ai-projects`, attach a compute session,
> and schedule the scrape through Foundry's job runner. Integration point:
> `foundry/client.deploy_to_foundry()`.

---


## Grading rubric (MSBA 6511) alignment

- **Gen-AI superpowers:** Analyze (fuzzy match/classify) + Summarize (JD parsing)
  + Generate (resume bullet rewrites).
- **Operating zone:** Optimize (personal workflow) → Accelerate (job-search outcomes).
- **Deployment level:** Inference + light RAG (resume = knowledge base, JD = query).
- **Agent quality:** 3 AutoGen agents in a GroupChat, registered in Azure AI Foundry.
- **KPI:** job-board checking 120 min/day → ~0; resume-JD fit score before/after rewrites.
