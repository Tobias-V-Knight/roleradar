# database.py
# -----------------------------------------------------------------------------
# All SQLite setup and queries live here. Keeping every SQL statement in one
# module means the rest of the app never writes raw SQL — it just calls these
# helper functions. That makes the data layer easy to reason about and test.
# -----------------------------------------------------------------------------

import os
import shutil
import sqlite3
from datetime import datetime, timezone

import config

# A pre-scraped snapshot shipped in the repo so the whole team sees the SAME
# dataset on first run without re-scraping. On startup, if there's no working
# database yet but this snapshot exists, we copy it to DB_PATH. The working
# copy (roleradar.db) is gitignored, so anyone's later scrapes stay local and
# never touch the shared snapshot.
SEED_DB_PATH = "seed.db"

# -----------------------------------------------------------------------------
# Connection helper
# -----------------------------------------------------------------------------
def get_conn():
    """Open a SQLite connection.

    We set row_factory to sqlite3.Row so query results behave like dicts
    (row["title"]) instead of plain tuples — much easier to serialize to JSON
    for the API later.
    """
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    # Enforce foreign keys (off by default in SQLite).
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _now():
    """Return an ISO-8601 UTC timestamp string for consistent storage."""
    return datetime.now(timezone.utc).isoformat()


# -----------------------------------------------------------------------------
# Schema creation
# -----------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    careers_url TEXT NOT NULL,
    tier INTEGER DEFAULT 1,
    active BOOLEAN DEFAULT 1,
    last_scraped TIMESTAMP,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS target_roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS target_locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city TEXT,
    state TEXT DEFAULT 'US',
    active BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER REFERENCES companies(id),
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    location TEXT,
    location_normalized TEXT,
    is_us_based BOOLEAN DEFAULT 1,
    is_match BOOLEAN DEFAULT 0,
    match_score REAL,
    matched_keyword TEXT,
    description TEXT,
    is_new BOOLEAN DEFAULT 1,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- A simple run log so the "Run History" tab has something to show.
CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    companies_scraped INTEGER DEFAULT 0,
    jobs_found INTEGER DEFAULT 0,
    new_matches INTEGER DEFAULT 0,
    note TEXT
);
"""


def init_db():
    """Create tables (if missing) and seed the reference data once.

    First, if there's no working DB yet but the shipped snapshot (seed.db)
    exists, copy it so teammates open the app to the same pre-scraped jobs.
    """
    if not os.path.exists(config.DB_PATH) and os.path.exists(SEED_DB_PATH):
        shutil.copy(SEED_DB_PATH, config.DB_PATH)
        print(f"[RoleRadar] seeded {config.DB_PATH} from {SEED_DB_PATH} "
              "(shared dataset snapshot)")

    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    _seed_if_empty(conn)
    conn.close()


def _seed_if_empty(conn):
    """Load the seed companies/roles/locations only if those tables are empty.

    This is idempotent: running it on every startup is safe because we check
    the row count first and skip if the data is already there.
    """
    # Companies
    if conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 0:
        for c in config.SEED_COMPANIES:
            conn.execute(
                "INSERT INTO companies (name, careers_url, tier, active) VALUES (?, ?, ?, 1)",
                (c["name"], c["url"], c.get("tier", 1)),
            )
    # Roles
    if conn.execute("SELECT COUNT(*) FROM target_roles").fetchone()[0] == 0:
        for kw in config.SEED_ROLES:
            conn.execute(
                "INSERT OR IGNORE INTO target_roles (keyword) VALUES (?)", (kw,)
            )
    # Locations
    if conn.execute("SELECT COUNT(*) FROM target_locations").fetchone()[0] == 0:
        for loc in config.SEED_LOCATIONS:
            conn.execute(
                "INSERT INTO target_locations (city, state, active) VALUES (?, ?, 1)",
                (loc["city"], loc.get("state", "US")),
            )
    conn.commit()


# -----------------------------------------------------------------------------
# Company queries
# -----------------------------------------------------------------------------
def list_companies(active_only=False):
    conn = get_conn()
    sql = "SELECT * FROM companies"
    if active_only:
        sql += " WHERE active = 1"
    sql += " ORDER BY tier, name"
    rows = conn.execute(sql).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_company(company_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_company_by_name(name):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM companies WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def add_company(name, careers_url, tier=1):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO companies (name, careers_url, tier, active) VALUES (?, ?, ?, 1)",
        (name, careers_url, tier),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def delete_company(company_id):
    conn = get_conn()
    conn.execute("DELETE FROM companies WHERE id = ?", (company_id,))
    conn.commit()
    conn.close()


def toggle_company(company_id):
    conn = get_conn()
    conn.execute("UPDATE companies SET active = NOT active WHERE id = ?", (company_id,))
    conn.commit()
    conn.close()


def mark_company_scraped(company_id, error=None):
    """Record the scrape timestamp and any error message for a company."""
    conn = get_conn()
    conn.execute(
        "UPDATE companies SET last_scraped = ?, last_error = ? WHERE id = ?",
        (_now(), error, company_id),
    )
    conn.commit()
    conn.close()


# -----------------------------------------------------------------------------
# Role queries
# -----------------------------------------------------------------------------
def list_roles():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM target_roles ORDER BY keyword").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_role(keyword):
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO target_roles (keyword) VALUES (?)", (keyword,))
    conn.commit()
    conn.close()


def delete_role(role_id):
    conn = get_conn()
    conn.execute("DELETE FROM target_roles WHERE id = ?", (role_id,))
    conn.commit()
    conn.close()


def get_role_keywords():
    """Return just the list of keyword strings — what the matcher needs."""
    return [r["keyword"] for r in list_roles()]


# -----------------------------------------------------------------------------
# Location queries
# -----------------------------------------------------------------------------
def list_locations():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM target_locations ORDER BY city").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_location(city, state="US"):
    conn = get_conn()
    conn.execute(
        "INSERT INTO target_locations (city, state, active) VALUES (?, ?, 1)",
        (city, state),
    )
    conn.commit()
    conn.close()


def delete_location(location_id):
    conn = get_conn()
    conn.execute("DELETE FROM target_locations WHERE id = ?", (location_id,))
    conn.commit()
    conn.close()


# -----------------------------------------------------------------------------
# Job queries
# -----------------------------------------------------------------------------
def upsert_job(job):
    """Insert a job, or update last_seen if its URL is already stored.

    We rely on the UNIQUE constraint on jobs.url for deduplication. The first
    time we see a URL it is inserted with is_new = 1. On subsequent scrapes we
    bump last_seen and refresh the match fields (a title's match status could
    change if the user edits their target roles).

    `job` is a dict with keys: company_id, title, url, location,
    location_normalized, is_us_based, is_match, match_score, matched_keyword.
    Returns True if this was a brand-new row.
    """
    conn = get_conn()
    existing = conn.execute(
        "SELECT id FROM jobs WHERE url = ?", (job["url"],)
    ).fetchone()

    if existing:
        conn.execute(
            """UPDATE jobs SET last_seen = ?, location = ?, location_normalized = ?,
                   is_us_based = ?, is_match = ?, match_score = ?, matched_keyword = ?,
                   is_new = 0
               WHERE url = ?""",
            (
                _now(),
                job.get("location"),
                job.get("location_normalized"),
                int(job.get("is_us_based", 1)),
                int(job.get("is_match", 0)),
                job.get("match_score"),
                job.get("matched_keyword"),
                job["url"],
            ),
        )
        conn.commit()
        conn.close()
        return False

    conn.execute(
        """INSERT INTO jobs
               (company_id, title, url, location, location_normalized, is_us_based,
                is_match, match_score, matched_keyword, is_new, first_seen, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
        (
            job["company_id"],
            job["title"],
            job["url"],
            job.get("location"),
            job.get("location_normalized"),
            int(job.get("is_us_based", 1)),
            int(job.get("is_match", 0)),
            job.get("match_score"),
            job.get("matched_keyword"),
            _now(),
            _now(),
        ),
    )
    conn.commit()
    conn.close()
    return True


def set_job_description(job_id, description):
    conn = get_conn()
    conn.execute("UPDATE jobs SET description = ? WHERE id = ?", (description, job_id))
    conn.commit()
    conn.close()


def get_job(job_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_job_by_url(url):
    """Direct lookup by the unique URL — used to attach JD text after upsert."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM jobs WHERE url = ?", (url,)).fetchone()
    conn.close()
    return dict(row) if row else None


def query_jobs(match_only=False, new_only=False, tier=None, city=None, us_only=True):
    """Flexible job listing used by the dashboard filters.

    We JOIN companies so each row carries company name + tier for display.
    Filters are applied with parameterized WHERE clauses (never string
    formatting) to stay safe from SQL injection.
    """
    conn = get_conn()
    sql = """
        SELECT jobs.*, companies.name AS company_name, companies.tier AS company_tier
        FROM jobs
        LEFT JOIN companies ON jobs.company_id = companies.id
        WHERE 1 = 1
    """
    params = []
    if match_only:
        sql += " AND jobs.is_match = 1"
    if new_only:
        sql += " AND jobs.is_new = 1"
    if us_only:
        sql += " AND jobs.is_us_based = 1"
    if tier is not None:
        sql += " AND companies.tier = ?"
        params.append(tier)
    if city:
        sql += " AND jobs.location_normalized = ?"
        params.append(city)
    sql += " ORDER BY jobs.is_match DESC, companies.tier ASC, jobs.first_seen DESC"

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# -----------------------------------------------------------------------------
# Run-log queries (Run History tab)
# -----------------------------------------------------------------------------
def start_run(note=None):
    conn = get_conn()
    cur = conn.execute("INSERT INTO scrape_runs (note) VALUES (?)", (note,))
    conn.commit()
    run_id = cur.lastrowid
    conn.close()
    return run_id


def finish_run(run_id, companies_scraped, jobs_found, new_matches):
    conn = get_conn()
    conn.execute(
        """UPDATE scrape_runs
           SET finished_at = ?, companies_scraped = ?, jobs_found = ?, new_matches = ?
           WHERE id = ?""",
        (_now(), companies_scraped, jobs_found, new_matches, run_id),
    )
    conn.commit()
    conn.close()


def list_runs(limit=50):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM scrape_runs ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def latest_run():
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM scrape_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None
