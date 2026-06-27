# matcher.py
# -----------------------------------------------------------------------------
# Two responsibilities:
#   1. Fuzzy-match a job TITLE against the list of target-role keywords.
#   2. Normalize a job LOCATION string and decide whether it is US-based.
#
# Both are deliberately kept out of the scraper and the agents so the matching
# rules can be tuned in one place (and unit-tested without hitting the web).
# -----------------------------------------------------------------------------

from rapidfuzz import fuzz

import config

# -----------------------------------------------------------------------------
# FUZZY ROLE MATCHING
# -----------------------------------------------------------------------------
# We use rapidfuzz's partial_ratio: it scores how well the SHORTER string fits
# as a substring of the LONGER one (0-100). That suits our problem because a
# real title like "Senior Applied AI Engineer, Platform" should still match the
# keyword "Applied AI Engineer" even with extra words around it.
#
# The catch: very short keywords (e.g. "FDE") can spuriously hit unrelated
# titles because almost any 3 letters fit "partially" somewhere. We guard
# against that below by requiring short keywords to appear as a whole word.


# Words that carry no role signal — ignored when comparing token sets so a
# keyword like "Senior Data Scientist" isn't blocked by a missing filler word.
# (We deliberately KEEP "senior", "staff", etc. only when they're part of the
# keyword itself — see _significant_tokens.)
STOPWORDS = {
    "the", "of", "and", "a", "an", "for", "to", "in", "on", "at",
    "i", "ii", "iii", "iv", "jr", "sr",
}

import re  # noqa: E402  (kept next to the tokenizer that uses it)


def _significant_tokens(text):
    """Lowercase, split on non-alphanumerics, drop pure filler words.

    "Senior Applied AI Engineer, Platform" ->
        ['senior', 'applied', 'ai', 'engineer', 'platform']
    """
    toks = re.findall(r"[a-z0-9]+", text.lower())
    return [t for t in toks if t not in STOPWORDS]


def _token_present(kw_token, title_tokens, fuzz_floor):
    """Is a single keyword token present among the title's tokens?

    Short tokens / abbreviations ('ai', 'ml', 'fde') must match EXACTLY — fuzzy
    matching 2-3 char tokens is too noisy. Longer tokens may match a title token
    fuzzily (>= fuzz_floor) so plurals/typos like 'scientist'/'scientists' count.
    """
    if len(kw_token) <= 3:
        return kw_token in title_tokens
    return any(fuzz.ratio(kw_token, tt) >= fuzz_floor for tt in title_tokens)


def score_title(title, keyword, fuzz_floor=None):
    """Return a 0-100 confidence that `title` matches `keyword`.

    THE GATE (precision): every significant token of the keyword must appear in
    the title (exact for short tokens, fuzzy for longer ones). This is what
    rejects "Electrical Engineer" -> "AI Engineer": the title lacks the token
    'ai'. The head-noun alone ('engineer') is NOT enough, because both titles
    share it — the distinguishing token is what matters.

    THE SCORE (ranking): if the gate passes, we return token_sort_ratio as a
    0-100 confidence for sorting/display. If the gate fails, we return 0.0 so
    the title can never count as a match for this keyword.
    """
    if fuzz_floor is None:
        fuzz_floor = config.FUZZY_MATCH_THRESHOLD

    kw_tokens = _significant_tokens(keyword)
    title_tokens = _significant_tokens(title)
    if not kw_tokens or not title_tokens:
        return 0.0

    # Gate: ALL keyword tokens must be present in the title.
    if not all(_token_present(kt, title_tokens, fuzz_floor) for kt in kw_tokens):
        return 0.0

    # Passed -> confidence score for ranking among competing keywords.
    return float(fuzz.token_sort_ratio(keyword.lower(), title.lower()))


def match_job_title(title, keywords=None, threshold=None):
    """Find the best-matching target keyword for a single job title.

    Returns a dict:
        {"is_match": bool, "match_score": float, "matched_keyword": str|None}

    The match DECISION is the all-tokens-present gate inside score_title (any
    keyword that clears the gate makes this a match). The numeric score is only
    used to pick which keyword to credit when several gates pass — e.g. a
    "Senior Data Scientist" title clears both "Data Scientist" and "Senior Data
    Scientist", and we credit the more specific (higher-scoring) one.
    """
    if keywords is None:
        # Imported lazily to avoid a circular import at module load time.
        import database
        keywords = database.get_role_keywords()
    if threshold is None:
        threshold = config.FUZZY_MATCH_THRESHOLD

    best_score = 0.0
    best_keyword = None
    for kw in keywords:
        s = score_title(title, kw, fuzz_floor=threshold)
        if s > best_score:
            best_score = s
            best_keyword = kw

    # A score > 0 means the gate passed for at least one keyword -> it's a match.
    is_match = best_score > 0.0
    return {
        "is_match": is_match,
        "match_score": round(best_score, 1),
        "matched_keyword": best_keyword if is_match else None,
    }


# -----------------------------------------------------------------------------
# LOCATION NORMALIZATION + US DETECTION
# -----------------------------------------------------------------------------
# Job sites write locations a dozen different ways. We collapse the variants we
# care about into a single canonical city name (used by the dashboard's city
# filter) and flag anything clearly outside the US so it can be hidden by
# default.

# Canonical city -> the raw variants that should map to it (all lowercase).
CITY_ALIASES = {
    "San Francisco": [
        "san francisco", "sf", "san francisco bay area", "bay area",
        "south san francisco", "sfo",
    ],
    "New York": ["new york", "nyc", "new york city", "ny, ny", "manhattan"],
    "Seattle": ["seattle", "bellevue", "redmond"],
    "Austin": ["austin"],
    "Chicago": ["chicago"],
    "Los Angeles": ["los angeles", "la", "santa monica", "culver city"],
    "Remote": ["remote", "remote - us", "us remote", "remote (us)", "anywhere"],
}

# Countries / regions that mark a posting as NOT US-based. Lowercased substrings.
NON_US_MARKERS = [
    "united kingdom", "london", "uk", "england", "ireland", "dublin",
    "canada", "toronto", "vancouver", "ontario",
    "germany", "berlin", "munich", "france", "paris", "spain", "madrid",
    "netherlands", "amsterdam", "switzerland", "zurich",
    "india", "bangalore", "bengaluru", "hyderabad", "mumbai",
    "singapore", "japan", "tokyo", "australia", "sydney",
    "israel", "tel aviv", "poland", "warsaw", "brazil", "mexico city",
    "emea", "apac", "europe",
]


def normalize_location(raw_location):
    """Return (normalized_city, is_us_based) for a raw location string.

    Rules:
      * Empty/unknown -> (None, True) — we don't hide jobs just for missing data.
      * Matches a non-US marker -> (raw-ish label, False).
      * Matches a known city alias -> (canonical city, True).
      * Otherwise -> (the cleaned raw string, True) so it still shows up.
    """
    if not raw_location:
        return None, True

    loc = raw_location.strip().lower()

    # "Remote" is special — always US-visible unless an explicit foreign tag.
    for canonical, aliases in CITY_ALIASES.items():
        if any(alias == loc or alias in loc for alias in aliases):
            # But if the string also names a foreign country, respect that.
            if canonical != "Remote" and any(m in loc for m in NON_US_MARKERS):
                break
            return canonical, True

    # Non-US detection.
    if any(marker in loc for marker in NON_US_MARKERS):
        return raw_location.strip(), False

    # Unknown US-ish location: keep the original text, assume US.
    return raw_location.strip(), True


def enrich_jobs(jobs, keywords=None, threshold=None):
    """Apply fuzzy matching + location normalization to a list of scraped jobs.

    Mutates and returns each job dict with the extra fields the database needs:
    is_match, match_score, matched_keyword, location_normalized, is_us_based.
    This is the function the matcher agent / orchestrator calls.
    """
    enriched = []
    for job in jobs:
        match = match_job_title(job.get("title", ""), keywords, threshold)
        norm_city, is_us = normalize_location(job.get("location", ""))
        job.update(match)
        job["location_normalized"] = norm_city
        job["is_us_based"] = is_us
        enriched.append(job)
    return enriched
