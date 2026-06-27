# RoleRadar — Stack, Patterns & Lessons Learned

A reusable knowledge file: *what* we used, **why** we picked it, and the patterns
worth carrying into other projects (CSI Bid Intelligence, Parsek/Gravl, PB IQ).
Written to be mined later — skim the tables, steal the patterns.

---

## 1. The stack — and why each piece

| Layer | Tool | Why this one (for this problem) | Where I'd reuse it |
|---|---|---|---|
| **Agent orchestration** | **AutoGen** (`pyautogen` 0.2) | Multi-agent `GroupChat` with a dead-simple `AssistantAgent` API; runs locally; course required an agent framework | Any multi-step LLM workflow (research → analyze → write) |
| **LLM runtime** | **Azure AI Foundry** + **Azure OpenAI** (GPT-4o) | Enterprise hosting; structured JSON output mode; course requirement | Regulated / enterprise LLM apps where data residency matters |
| **Backend API** | **FastAPI** | Async, automatic `/docs`, Pydantic request validation, almost no boilerplate | Every Python API or service I build |
| **Scraping (light)** | **httpx** + **BeautifulSoup4** | Fast static download + HTML parsing; covers JSON APIs | Hitting APIs, parsing static/server-rendered pages |
| **Scraping (heavy)** | **Playwright** (headless Chromium) | Runs JavaScript so SPA pages actually render before scraping | Dynamic sites, browser automation, end-to-end UI testing |
| **Fuzzy matching** | **rapidfuzz** | Fast (C++) fuzzy string scoring; many scorers (`partial_ratio`, `token_*`) | Dedup, entity resolution, search ranking, record linkage |
| **Storage** | **SQLite** (`sqlite3`) | Zero-config embedded DB; the whole DB is one file you can ship | Prototypes, single-node apps, shippable datasets/fixtures |
| **Scheduler** | **APScheduler** | In-process cron; decouples expensive jobs from web requests | Periodic ETL, data refresh, cache warming |
| **Frontend** | **vanilla JS + Tailwind CDN** | No build step, single `index.html`, instant to ship | Quick dashboards, internal tools, demos |
| **Packaging / deploy** | **Docker** | Reproducible environment *including* system libraries + a browser | Anything with native deps; team distribution; cloud deploy |
| **Config / secrets** | **python-dotenv** + env vars | Same code runs local (`.env`) and cloud (host settings); secrets stay out of git | Every project, always |

---

## 2. The big lesson: httpx vs Playwright (web scraping mental model)

**Two kinds of web pages:**

- **Server-rendered:** you request the page, the server returns **complete HTML
  with the content already in it**. `httpx` — a plain HTTP client that just
  downloads bytes, like `curl` — gets everything. One network call, milliseconds.
- **Client-rendered (SPA):** the server returns a **near-empty shell + a pile of
  JavaScript**. The content doesn't exist yet; your **browser runs the JS**,
  which fetches data and *builds* the page. `httpx` can't run JS, so it sees only
  the empty shell. **Playwright runs a real (headless) browser** that executes
  the JS, so it sees the finished page.

> **httpx reads what the server *mails* you. Playwright actually *visits* the
> site and waits for it to assemble itself.**

**Cost asymmetry → the strategy:** httpx is ~milliseconds; Playwright launches a
~150 MB browser and renders (seconds). So: **try httpx first; fall back to
Playwright only when the page comes back suspiciously empty.** RoleRadar's
`fetch_smart()` does exactly this — if visible text < 500 chars, it's probably
JS-rendered → use Playwright.

**The pro move:** Many SPA sites have a **hidden API** — the JSON endpoint the
JavaScript itself calls. Find it (e.g. Greenhouse/Lever/Ashby job boards) and
`httpx` hits that JSON directly, skipping the browser entirely. Faster *and* more
robust than parsing rendered HTML. **Always look for the API before reaching for
a browser.**

*Rough split in this project:* ~65–75% of companies were reachable with
httpx/ATS APIs; only ~25–35% needed (or benefited from) Playwright. Job boards
skew toward a few ATS platforms, so you dodge rendering more than typical scraping.

---

## 3. Why Docker (and what it bought us)

**The problem:** Playwright needs a real Chromium browser + dozens of Linux
system libraries. A standard cloud Python runtime (Azure App Service) is a locked
sandbox — you can `pip install` Python packages but **can't install OS-level
system libraries**, so Chromium can't even launch.

**Docker fixes it by inverting the model:** instead of depending on what the host
provides, **you define the whole environment yourself** in a `Dockerfile`,
starting from a base image that already has Chromium + libs
(`mcr.microsoft.com/playwright/python`). The result is one self-contained image
that runs **identically** on your laptop, a teammate's machine, and the cloud.

> Standard runtime = renting a furnished apartment you can't modify.
> Docker = building your own food truck — full kitchen included — and parking it anywhere.

**Three things Docker bought us:**
1. **Playwright works in the cloud** (the original blocker).
2. **Reproducibility** — froze Python 3.10 + every dep, killing "works on my
   machine" bugs (incl. the `pyautogen`/Python-3.13 trap below).
3. **Dead-simple distribution** — teammates run `docker run` with no Python, no
   venv, no `pip install`, no `playwright install`. Push to a registry (ghcr.io)
   and it's pull-and-run for anyone.

---

## 4. Reusable patterns (steal these)

| Pattern | What it is | Why it matters | Reuse in |
|---|---|---|---|
| **Stub-safe / graceful degradation** | App runs without cloud creds, returning labeled `[STUB]` data | Demo anywhere; no hard dependency on a flaky/expensive service | CSI (run without the client's live data), PB IQ (run without YouTube API) |
| **Decouple compute from serving** | Heavy work (scrape) runs on a schedule → writes to DB; the UI only *reads* the DB | Instant UX; expensive work off the request hot path | Any dashboard over slow/expensive data |
| **Lazy fetch + cache** | Fetch the costly detail (job description) on first click, then cache it | Don't pay to fetch data nobody looks at (45-min run → 3-min run) | Parsek/Gravl detail views, any per-item enrichment |
| **Seed / working data split** | Ship a tracked `seed.db` snapshot; the live working DB is gitignored | Team shares one baseline dataset; nobody's runs cause git conflicts | Any project that ships demo data |
| **Find the hidden API** | Call the JSON the page's JS calls, instead of rendering HTML | Faster + far more robust than scraping markup | All scraping work |
| **Precision-first matching** | Gate on required tokens *before* trusting a fuzzy score | Fuzzy scores alone over-match ("AI Engineer" ≈ "Electrical Engineer") | CSI bid/entity matching, dedup, search |
| **Pin + document the runtime** | Pin the fragile dep; document the required language version | Reproducibility; teammates don't hit silent breakage | Every project |
| **Secrets via env, never in repo** | `.env` local, host settings in cloud; both gitignored + `.dockerignore`d | One codebase, two secret sources; nothing leaks | Every project |

---

## 5. Gotchas that actually bit us (so future-me doesn't repeat them)

- **`pip install pyautogen` on Python 3.13 installs the *wrong* AutoGen.** v0.10 is
  the new restructured API with no `import autogen`. The classic
  `autogen.AssistantAgent` API needs **`pyautogen==0.2.35` on Python 3.9–3.12.**
  Pin it; document the Python version.
- **Azure tenant policy blocked the *Global Standard* model deployment.** Fix:
  deploy as **Standard** (regional). Education/enterprise tenants restrict model +
  deployment *type* — read the policy error, change the type, retry.
- **The Cognitive Services endpoint** (`*.api.cognitive.microsoft.com`) works with
  the standard `AzureOpenAI` SDK at its `/openai/deployments/...` route — you don't
  need the `*.openai.azure.com` form.
- **`docker --env-file` is stricter than `python-dotenv`** — no spaces around `=`,
  no spaces in names. dotenv tolerates `KEY = value`; Docker doesn't.
- **Never put a venv inside an iCloud-synced folder** — iCloud thrashes trying to
  sync thousands of small files. Keep venvs outside (`~/venvs/...`) or use Docker.
- **Don't eagerly fetch detail data during a bulk job.** It turned a 3-minute run
  into 45 minutes. Fetch lazily, on demand.

---

## 6. How this transfers to my other projects

- **CSI Bid Intelligence:** the *precision-first matching* pattern (token gate
  before fuzzy score) maps directly to matching bid line-items / contractors.
  *Stub-safe* mode lets the tool run in demos without the client's live data.
  *Decouple compute from serving* fits a "refresh nightly, dashboard reads cache"
  design.
- **Parsek/Gravl:** *lazy fetch + cache* and *find the hidden API* are the core of
  any data-aggregation feature; *Docker* gives a clean reproducible deploy.
- **PB IQ:** the YouTube pipeline is the same shape — *decouple* the heavy
  ingest/analysis (scheduled) from the app that serves it; *stub-safe* keeps the
  app demoable without the full pipeline running; *Docker* standardizes the env.

---

## 7. Portfolio framing (accurate, no overclaiming)

> **RoleRadar** — a multi-agent job-intelligence platform. AutoGen agents on Azure
> AI Foundry scrape 40+ companies, fuzzy-match roles, and run live GPT-4o
> resume-vs-JD gap analysis. FastAPI + SQLite backend, containerized with Docker.
> Built for an MSBA Gen AI course; deployed live on Azure.

Pair with: an **architecture diagram**, a **30-second demo GIF** (dashboard →
Analyze → live GPT-4o output), and a **metrics line** (45 companies, ~9,800 jobs,
~3-minute full scrape, ~1,100 matched roles).

**Stack badges:** Python · FastAPI · SQLite · AutoGen · Azure AI Foundry · GPT-4o
· Docker · Playwright · rapidfuzz.
