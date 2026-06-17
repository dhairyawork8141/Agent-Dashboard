"""Job-board clients (official APIs, not scraping). Each returns normalised job dicts.
fetch_all() drives them from the runtime `settings` (searches/countries/recency)."""
import logging
import requests
import config

log = logging.getLogger("sources")
TIMEOUT = 25


def _key(source: str, job_id: str) -> str:
    return f"{source}:{job_id}"


def _fmt_salary(lo, hi):
    if not lo:
        return None
    lo = int(lo)
    hi = int(hi) if hi else lo
    return f"\u00a3{lo:,} - \u00a3{hi:,}" if hi != lo else f"\u00a3{lo:,}"


def fetch_adzuna(search: dict, country: str, max_days_old: int) -> list:
    if not (config.ADZUNA_APP_ID and config.ADZUNA_APP_KEY):
        return []
    url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
    params = {
        "app_id": config.ADZUNA_APP_ID,
        "app_key": config.ADZUNA_APP_KEY,
        "what_phrase": search["phrase"],
        "results_per_page": 50,
        "max_days_old": max_days_old,
        "content-type": "application/json",
    }
    if search.get("extra"):
        params["what"] = search["extra"]
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.warning("Adzuna %s/%s failed: %s", country, search.get("label"), e)
        return []

    out = []
    for j in data.get("results", []):
        jid = str(j.get("id", "")).strip()
        if not jid:
            continue
        out.append({
            "key": _key("adzuna", jid),
            "source": f"Adzuna ({country.upper()})",
            "title": (j.get("title") or "").strip(),
            "company": ((j.get("company") or {}).get("display_name") or "").strip(),
            "location": ((j.get("location") or {}).get("display_name") or "").strip(),
            "salary": _fmt_salary(j.get("salary_min"), j.get("salary_max")),
            "url": j.get("redirect_url", ""),
            "posted": (j.get("created") or "")[:10],
            "description": j.get("description", ""),
            "matched_on": search.get("label", ""),
        })
    return out


def fetch_reed(search: dict) -> list:
    if not config.REED_API_KEY:
        return []
    url = "https://www.reed.co.uk/api/1.0/search"
    keywords = f'"{search["phrase"]}"'
    if search.get("extra"):
        keywords += f' {search["extra"]}'
    try:
        r = requests.get(url, params={"keywords": keywords, "resultsToTake": 100},
                         auth=(config.REED_API_KEY, ""), timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.warning("Reed %s failed: %s", search.get("label"), e)
        return []

    out = []
    for j in data.get("results", []):
        jid = str(j.get("jobId", "")).strip()
        if not jid:
            continue
        out.append({
            "key": _key("reed", jid),
            "source": "Reed",
            "title": (j.get("jobTitle") or "").strip(),
            "company": (j.get("employerName") or "").strip(),
            "location": (j.get("locationName") or "").strip(),
            "salary": _fmt_salary(j.get("minimumSalary"), j.get("maximumSalary")),
            "url": j.get("jobUrl", ""),
            "posted": j.get("date", ""),
            "description": j.get("jobDescription", ""),
            "matched_on": search.get("label", ""),
        })
    return out


def fetch_all(settings: dict) -> list:
    searches = settings.get("searches") or config.DEFAULT_SETTINGS["searches"]
    countries = settings.get("countries") or config.DEFAULT_SETTINGS["countries"]
    max_days_old = settings.get("max_days_old", config.DEFAULT_SETTINGS["max_days_old"])

    jobs, seen = [], set()

    def _add(items):
        for j in items:
            if j["key"] not in seen:
                seen.add(j["key"])
                jobs.append(j)

    for search in searches:
        for country in countries:
            _add(fetch_adzuna(search, country, max_days_old))
        _add(fetch_reed(search))

    log.info("Fetched %d unique postings across all sources", len(jobs))
    return jobs
