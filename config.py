# config.py
# -----------------------------------------------------------------------------
# Central configuration for RoleRadar: the seed data (companies, target roles,
# target locations), the fuzzy-match threshold, and the scrape schedule.
#
# Everything a non-programmer teammate might want to tweak lives here so they
# never have to dig through the scraping or matching logic.
# -----------------------------------------------------------------------------

# How often APScheduler re-runs a full scrape of every active company.
# Default is weekly (168h): the heavy Playwright scrape runs on a loop in the
# background, while the dashboard always serves instantly from the stored data.
# Override with the SCRAPE_INTERVAL_HOURS env var (e.g. 6 for every 6 hours).
# NOTE: on App Service Free tier the app sleeps when idle, so this in-app timer
# may not fire — use Basic tier + "Always On", or an external cron that calls
# POST /api/scrape. See README "Deploy to Azure (Docker)".
import os  # noqa: E402

SCRAPE_INTERVAL_HOURS = int(os.getenv("SCRAPE_INTERVAL_HOURS", "168"))

# Politeness delay between company scrapes so we don't hammer career sites.
SCRAPE_DELAY_SECONDS = 2

# rapidfuzz partial_ratio minimum score (0-100). A job title must score at
# least this high against one of the target-role keywords to count as a match.
FUZZY_MATCH_THRESHOLD = 75

# A job whose title is shorter than this many characters is treated with care
# in the matcher (short titles inflate partial_ratio scores — see matcher.py).
MIN_TITLE_LEN_FOR_FUZZY = 6

# Path to the SQLite database file (created on first run).
DB_PATH = "roleradar.db"

# -----------------------------------------------------------------------------
# COMPANY SEED DATA
# tier 1-4 = priority bands; tier 0 = aggregator (handled specially).
# URLs marked "# VERIFY" are flagged on first run if they return 0 jobs.
# -----------------------------------------------------------------------------
SEED_COMPANIES = [
    # TIER 1 — FDE / Applied AI / Solutions
    {"name": "Anthropic",   "tier": 1, "url": "https://www.anthropic.com/careers/jobs"},
    {"name": "OpenAI",      "tier": 1, "url": "https://openai.com/careers/search/"},
    {"name": "Databricks",  "tier": 1, "url": "https://www.databricks.com/company/careers/open-positions"},
    {"name": "Scale AI",    "tier": 1, "url": "https://scale.com/careers"},
    {"name": "Cursor",      "tier": 1, "url": "https://www.cursor.com/careers"},  # VERIFY
    {"name": "Notion",      "tier": 1, "url": "https://www.notion.com/careers"},
    {"name": "Figma",       "tier": 1, "url": "https://www.figma.com/careers/"},  # VERIFY
    {"name": "Gamma",       "tier": 1, "url": "https://careers.gamma.app/"},
    {"name": "Wispr Flow",  "tier": 1, "url": "https://www.wispr.ai/careers"},    # VERIFY
    {"name": "Speechify",   "tier": 1, "url": "https://speechify.com/careers/"},
    {"name": "Mistral",     "tier": 1, "url": "https://mistral.ai/careers/"},

    # TIER 2 — Product / Growth DS
    {"name": "Superhuman",  "tier": 2, "url": "https://superhuman.com/company/careers/jobs"},
    {"name": "Grammarly",   "tier": 2, "url": "https://www.grammarly.com/jobs"},  # VERIFY
    {"name": "Uber",        "tier": 2, "url": "https://www.uber.com/us/en/careers/list/"},
    {"name": "Plaud",       "tier": 2, "url": "https://jobs.ashbyhq.com/Plaud"},
    {"name": "Otter.ai",    "tier": 2, "url": "https://otter.ai/jobs"},           # VERIFY
    {"name": "Meta",        "tier": 2, "url": "https://www.metacareers.com/jobs"},
    {"name": "Rippling",    "tier": 2, "url": "https://www.rippling.com/careers/open-roles"},
    {"name": "Block",       "tier": 2, "url": "https://www.block.xyz/careers"},   # VERIFY
    {"name": "Instacart",   "tier": 2, "url": "https://instacart.careers/current-openings/"},
    {"name": "Duolingo",    "tier": 2, "url": "https://careers.duolingo.com/"},
    {"name": "Quizlet",     "tier": 2, "url": "https://quizlet.com/careers"},     # VERIFY
    {"name": "Bumble",      "tier": 2, "url": "https://bumble.com/en/jobs"},      # VERIFY
    {"name": "Turo",        "tier": 2, "url": "https://turo.com/us/en/careers"},  # VERIFY

    # TIER 3 — Marketplace / Mobility / Senior DS
    {"name": "Waymo",       "tier": 3, "url": "https://careers.withwaymo.com/jobs/search"},
    {"name": "Airbnb",      "tier": 3, "url": "https://careers.airbnb.com/positions/"},
    {"name": "DoorDash",    "tier": 3, "url": "https://careers.doordash.com/jobs"},
    {"name": "Lyft",        "tier": 3, "url": "https://www.lyft.com/careers"},    # VERIFY
    {"name": "Lime",        "tier": 3, "url": "https://www.li.me/careers"},       # VERIFY
    {"name": "Shipt",       "tier": 3, "url": "https://www.shipt.com/careers/"},  # VERIFY
    {"name": "Faire",       "tier": 3, "url": "https://www.faire.com/careers"},   # VERIFY
    {"name": "Samsara",     "tier": 3, "url": "https://www.samsara.com/company/careers/roles"},  # VERIFY
    {"name": "Tesla",       "tier": 3, "url": "https://www.tesla.com/careers/search"},

    # TIER 4 — Specialty / Hardware / Robotics
    {"name": "Nuro",        "tier": 4, "url": "https://www.nuro.ai/careers"},     # VERIFY
    {"name": "Zoox",        "tier": 4, "url": "https://zoox.com/careers/"},
    {"name": "Verkada",     "tier": 4, "url": "https://www.verkada.com/careers/"},  # VERIFY
    {"name": "Oura",        "tier": 4, "url": "https://ouraring.com/careers"},    # VERIFY
    {"name": "Eight Sleep", "tier": 4, "url": "https://www.eightsleep.com/careers/"},  # VERIFY
    {"name": "Toast",       "tier": 4, "url": "https://careers.toasttab.com/"},   # VERIFY
    {"name": "Crunchyroll", "tier": 4, "url": "https://www.crunchyroll.com/about/careers"},  # VERIFY
    {"name": "Rivian",      "tier": 4, "url": "https://rivian.com/careers"},
    {"name": "Peloton",     "tier": 4, "url": "https://www.onepeloton.com/careers"},
    {"name": "SpaceX",      "tier": 4, "url": "https://www.spacex.com/careers/jobs"},
    {"name": "Redis",       "tier": 4, "url": "https://redis.io/company/careers/current-job-openings/"},

    # AGGREGATOR — scraped separately, matched against the company list by name.
    {"name": "YC Jobs",     "tier": 0, "url": "https://www.ycombinator.com/jobs",
     "is_aggregator": True},
]

# -----------------------------------------------------------------------------
# TARGET ROLE SEED DATA — the keywords the fuzzy matcher compares titles against.
# -----------------------------------------------------------------------------
SEED_ROLES = [
    "AI Engineer",
    "Applied AI Engineer",
    "Forward Deployed Engineer",
    "FDE",
    "Solutions Architect",
    "Solutions Engineer",
    "Field Engineer",
    "Machine Learning Engineer",
    "ML Engineer",
    "Data Scientist",
    "Senior Data Scientist",
    "Product Manager",
    "Technical Account Manager",
]

# -----------------------------------------------------------------------------
# TARGET LOCATION SEED DATA — used for the dashboard city filter and the
# "is this US-based?" check. "Remote" is always shown unless filtered out.
# -----------------------------------------------------------------------------
SEED_LOCATIONS = [
    {"city": "Remote", "state": "US"},
    {"city": "San Francisco", "state": "CA"},
    {"city": "New York", "state": "NY"},
    {"city": "Seattle", "state": "WA"},
    {"city": "Austin", "state": "TX"},
    {"city": "Chicago", "state": "IL"},
    {"city": "Los Angeles", "state": "CA"},
]