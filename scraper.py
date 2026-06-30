# scraper.py
# -----------------------------------------------------------------------------
# All web-scraping logic. The public entry point is scrape_company(name, url),
# which dispatches to a site-specific parser based on the URL, and falls back to
# a generic link-scanner for unknown sites.
#
# Strategy (per project spec):
#   1. Try a fast static fetch with httpx.
#   2. If the response body looks empty/too small (< 500 chars of useful HTML),
#      the page is probably JS-rendered -> fall back to Playwright (headless
#      Chromium) which executes the JavaScript first.
#   3. ATS platforms (Greenhouse, Lever, Ashby) expose clean JSON APIs — we use
#      those directly when we can detect them, which is far more reliable than
#      parsing HTML.
#
# Every parser returns a list of dicts: {title, url, company, location}.
# Errors are raised to the caller (the orchestrator), which logs them per
# company and keeps going — one bad site never crashes the whole run.
# -----------------------------------------------------------------------------

import re
import time
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

# A realistic User-Agent so career sites don't immediately block us as a bot.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

# If a static fetch returns less than this many characters we assume the real
# content is rendered by JavaScript and switch to Playwright.
MIN_STATIC_BODY_CHARS = 500

REQUEST_TIMEOUT = 25  # seconds


# -----------------------------------------------------------------------------
# Low-level fetchers
# -----------------------------------------------------------------------------
def fetch_static(url):
    """Fetch a URL with httpx. Returns the response text (may be empty-ish)."""
    resp = httpx.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def fetch_rendered(url, wait_selector=None, wait_ms=4000):
    """Fetch a URL with Playwright (headless Chromium) so JS runs first.

    If Playwright isn't installed we raise ImportError — the caller catches it,
    logs "[WARN] playwright not available", and the company is skipped rather
    than crashing the run.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise ImportError("playwright not available") from e

    html = ""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=HEADERS["User-Agent"])
        page.goto(url, timeout=REQUEST_TIMEOUT * 1000, wait_until="domcontentloaded")
        # Give the SPA a moment (or wait for a specific element) to render jobs.
        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=wait_ms)
            except Exception:
                pass  # fall through — we'll parse whatever rendered
        else:
            page.wait_for_timeout(wait_ms)
        html = page.content()
        browser.close()
    return html


def fetch_smart(url, wait_selector=None):
    """httpx first; if the body looks too small, fall back to Playwright.

    Returns a tuple (html, method_used) so the caller can log which path ran.
    """
    try:
        html = fetch_static(url)
        if html and len(html) >= MIN_STATIC_BODY_CHARS:
            # Heuristic: a near-empty <body> also signals a JS app even when the
            # raw HTML (with <head>/scripts) is large. Check visible text length.
            text_len = len(BeautifulSoup(html, "html.parser").get_text(strip=True))
            if text_len >= MIN_STATIC_BODY_CHARS:
                return html, "httpx"
    except Exception as e:
        print(f"[INFO] static fetch failed ({e}); trying playwright")

    # Fall back to a rendered fetch.
    html = fetch_rendered(url, wait_selector=wait_selector)
    return html, "playwright"


# -----------------------------------------------------------------------------
# ATS detection + JSON-API parsers
# -----------------------------------------------------------------------------
def _slugify(company_name):
    """Turn 'Scale AI' -> 'scaleai' style guesses for ATS board slugs."""
    return re.sub(r"[^a-z0-9]", "", company_name.lower())


def _slug_hyphen(company_name):
    """Turn 'Scale AI' -> 'scale-ai'."""
    return re.sub(r"[^a-z0-9]+", "-", company_name.lower()).strip("-")


def scrape_greenhouse(company_name, url=None):
    """Greenhouse boards expose a clean JSON API. Try common slug guesses."""
    slugs = [_slugify(company_name), _slug_hyphen(company_name),
             company_name.lower().replace(" ", "")]
    # If a Greenhouse URL was provided, extract its slug and try it first.
    if url:
        path = urlparse(url).path.strip("/").split("/")[0]
        if path and path not in slugs:
            slugs.insert(0, path)
    for slug in slugs:
        api = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
        try:
            resp = httpx.get(api, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                continue
            data = resp.json()
            jobs = []
            for j in data.get("jobs", []):
                jobs.append({
                    "title": j.get("title", "").strip(),
                    "url": j.get("absolute_url", ""),
                    "company": company_name,
                    "location": (j.get("location") or {}).get("name", ""),
                })
            if jobs:
                return jobs
        except Exception:
            continue
    return []


def scrape_lever(company_name, url=None):
    """Lever postings JSON API."""
    slugs = [_slugify(company_name), _slug_hyphen(company_name)]
    if url:
        path = urlparse(url).path.strip("/").split("/")[0]
        if path and path not in slugs:
            slugs.insert(0, path)
    for slug in slugs:
        api = f"https://api.lever.co/v0/postings/{slug}?mode=json"
        try:
            resp = httpx.get(api, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                continue
            data = resp.json()
            jobs = []
            for j in data:
                jobs.append({
                    "title": j.get("text", "").strip(),
                    "url": j.get("hostedUrl", ""),
                    "company": company_name,
                    "location": (j.get("categories") or {}).get("location", ""),
                })
            if jobs:
                return jobs
        except Exception:
            continue
    return []


def scrape_ashby(company_name, url):
    """Ashby ATS (jobs.ashbyhq.com/<Org>). Uses their public GraphQL-ish API."""
    # Extract the org slug from the URL: jobs.ashbyhq.com/Plaud -> Plaud
    org = url.rstrip("/").split("/")[-1]
    api = "https://api.ashbyhq.com/posting-api/job-board/" + org
    try:
        resp = httpx.get(api, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            jobs = []
            for j in data.get("jobs", []):
                jobs.append({
                    "title": j.get("title", "").strip(),
                    "url": j.get("jobUrl") or j.get("applyUrl", ""),
                    "company": company_name,
                    "location": j.get("location", ""),
                })
            if jobs:
                return jobs
    except Exception:
        pass
    return []


# -----------------------------------------------------------------------------
# Custom site parsers
# -----------------------------------------------------------------------------
def scrape_anthropic(company_name, url):
    """Anthropic's careers page is React-rendered -> Playwright required.

    Anthropic actually hosts its listings on Greenhouse under the hood, so we
    try the Greenhouse JSON API first (fast + reliable). If that yields nothing
    we fall back to rendering the page and scraping job-card links.
    """
    # Fast path: Anthropic's Greenhouse board slug is "anthropic".
    gh = scrape_greenhouse("anthropic")
    if gh:
        # Stamp the display company name (Greenhouse returns generic titles).
        for j in gh:
            j["company"] = company_name
        return gh

    # Fallback: render the SPA and scrape anchor tags that look like jobs.
    html = fetch_rendered(url, wait_selector="a")
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        title = a.get_text(strip=True)
        # Anthropic job links contain "/careers/" and a role slug.
        if "/careers/" in href and title and len(title) > 4:
            full = urljoin(url, href)
            if full in seen:
                continue
            seen.add(full)
            jobs.append({
                "title": title,
                "url": full,
                "company": company_name,
                "location": "",  # location lives on the detail page for Anthropic
            })
    return jobs


def scrape_openai(company_name, url):
    """OpenAI careers — also Greenhouse-backed; try API then render."""
    gh = scrape_greenhouse("openai")
    if gh:
        for j in gh:
            j["company"] = company_name
        return gh
    return scrape_generic(company_name, url, force_render=True)


# -----------------------------------------------------------------------------
# Generic fallback
# -----------------------------------------------------------------------------
JOB_HREF_HINTS = ("job", "position", "career", "opening", "role", "apply", "posting")


def scrape_generic(company_name, url, force_render=False):
    """Last-resort parser: find anchor tags whose href looks like a job link.

    Used for any company without a dedicated parser. Noisy by nature, so the
    caller warns if fewer than 3 jobs come back (likely needs a real parser).
    """
    if force_render:
        html = fetch_rendered(url, wait_selector="a")
    else:
        html, _ = fetch_smart(url)

    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        if not any(hint in href for hint in JOB_HREF_HINTS):
            continue
        title = a.get_text(strip=True)
        if not title or len(title) < 4:
            continue
        full = urljoin(url, a["href"])
        # Skip the careers landing page itself and obvious non-job links.
        if full.rstrip("/") == url.rstrip("/") or full in seen:
            continue
        seen.add(full)
        jobs.append({
            "title": title,
            "url": full,
            "company": company_name,
            "location": "",
        })
    return jobs


# -----------------------------------------------------------------------------
# YC aggregator
# -----------------------------------------------------------------------------
def scrape_yc(url):
    """Scrape the YC jobs board. Returns raw jobs with a 'company' field that
    the orchestrator cross-references against the seed company list."""
    html, _ = fetch_smart(url, wait_selector="a")
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/companies/" not in href and "/jobs/" not in href:
            continue
        title = a.get_text(strip=True)
        if not title or len(title) < 4:
            continue
        full = urljoin(url, href)
        if full in seen:
            continue
        seen.add(full)
        jobs.append({
            "title": title,
            "url": full,
            "company": "",       # filled in by cross-reference, if possible
            "location": "",
        })
    return jobs


# -----------------------------------------------------------------------------
# Dispatcher
# -----------------------------------------------------------------------------
def scrape_google(company_name, url):
    """Scrape Google Careers (JS-rendered). Uses Playwright + parses sMn82b cards."""
    BASE = "https://www.google.com/about/careers/applications/"
    html = fetch_rendered(url, wait_ms=5000)
    soup = BeautifulSoup(html, "html.parser")

    jobs = []
    # Each job card lives in a div.sMn82b; the link to the posting is a sibling <a>
    for card in soup.find_all("div", class_="sMn82b"):
        parts = [p.strip() for p in card.get_text(separator="|").split("|") if p.strip()]
        if not parts:
            continue
        title = parts[0]
        # Location follows the "place" icon text
        location = ""
        for i, p in enumerate(parts):
            if p == "place" and i + 1 < len(parts):
                location = parts[i + 1]
                break
        # Find the nearest <a> with a job URL in the ancestor chain
        link_el = card.find_parent("a", href=True)
        if not link_el:
            # Try sibling/nearby <a> within the card's parent
            parent = card.parent
            link_el = parent.find("a", href=lambda h: h and "jobs/results/" in h)
        href = link_el["href"] if link_el else ""
        if href and not href.startswith("http"):
            href = urljoin(BASE, href)
        if not title or not href:
            continue
        jobs.append({"title": title, "url": href, "company": company_name, "location": location})

    print(f"[scrape_google] found {len(jobs)} jobs")
    return jobs


def scrape_company(company_name, url):
    """Route a company to the right parser based on its careers URL.

    This is the single function the scraper agent / orchestrator calls.
    Returns a list of job dicts (possibly empty). Raises on hard failures so
    the caller can record the error per-company.
    """
    host = urlparse(url).netloc.lower()
    name_lower = company_name.lower()

    # --- ATS platforms (detected by hostname) ---
    if "ashbyhq.com" in host:
        return scrape_ashby(company_name, url)
    if "greenhouse.io" in host or "boards.greenhouse" in host:
        return scrape_greenhouse(company_name, url)
    if "lever.co" in host:
        return scrape_lever(company_name, url)

    # --- Custom, well-known sites ---
    if "anthropic" in name_lower:
        return scrape_anthropic(company_name, url)
    if "openai" in name_lower:
        return scrape_openai(company_name, url)
    if "google.com/about/careers" in url:
        return scrape_google(company_name, url)

    # --- ATS guesses for known-tricky companies (try API before HTML) ---
    # Many of the seed companies use Greenhouse/Lever under a custom URL.
    for ats in (scrape_greenhouse, scrape_lever):
        try:
            jobs = ats(company_name)
            if jobs:
                return jobs
        except Exception:
            pass

    # --- Generic fallback ---
    return scrape_generic(company_name, url)


# -----------------------------------------------------------------------------
# Job description fetch (for matched jobs)
# -----------------------------------------------------------------------------
def fetch_job_description(job_url):
    """Fetch a single job posting and return its visible text (HTML stripped).

    Returns "" on failure — the caller logs the error but keeps the job record.
    """
    try:
        html, _ = fetch_smart(job_url)
        soup = BeautifulSoup(html, "html.parser")
        # Drop script/style noise before extracting text.
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        # Collapse excessive blank lines.
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text[:20000]  # cap to keep the DB + LLM prompt reasonable
    except Exception as e:
        print(f"[WARN] failed to fetch JD for {job_url}: {e}")
        return ""
