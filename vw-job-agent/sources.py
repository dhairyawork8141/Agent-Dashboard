"""Job-board clients (official APIs, not scraping). Each returns normalised job dicts.
fetch_all() drives them from the runtime `settings` (searches/countries/recency)."""
import hashlib
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


def fetch_jooble(search: dict) -> list:
    """Jooble aggregator (POST to a key-in-URL endpoint). Free key on request.
    One global endpoint returns international results, so we don't loop countries."""
    if not config.JOOBLE_API_KEY:
        return []
    keywords = search["phrase"]
    if search.get("extra"):
        keywords = f'{search["extra"]} {keywords}'
    try:
        r = requests.post(f"https://jooble.org/api/{config.JOOBLE_API_KEY}",
                          json={"keywords": keywords}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.warning("Jooble %s failed: %s", search.get("label"), e)
        return []

    out = []
    for j in data.get("jobs", []):
        jid = str(j.get("id", "")).strip()
        if not jid:
            continue
        out.append({
            "key": _key("jooble", jid),
            "source": "Jooble",
            "title": (j.get("title") or "").strip(),
            "company": (j.get("company") or "").strip(),
            "location": (j.get("location") or "").strip(),
            "salary": (j.get("salary") or "").strip() or None,
            "url": j.get("link", ""),
            "posted": (j.get("updated") or "")[:10],
            "description": j.get("snippet", ""),
            "matched_on": search.get("label", ""),
        })
    return out


def fetch_careerjet(search: dict, locale: str) -> list:
    """Careerjet global aggregator. Free affiliate id (affid). `locale_code` (en_GB,
    en_US, ...) selects the regional index, so we loop a small set of locales."""
    if not config.CAREERJET_AFFID:
        return []
    keywords = search["phrase"]
    if search.get("extra"):
        keywords = f'{search["extra"]} {keywords}'
    params = {
        "keywords": keywords,
        "locale_code": locale,
        "affid": config.CAREERJET_AFFID,
        "user_ip": "11.22.33.44",
        "user_agent": "Mozilla/5.0 (compatible; CADIllustratorsBot/1.0)",
        "pagesize": 50,
        "page": 1,
        "sort": "date",
    }
    try:
        r = requests.get("http://public.api.careerjet.net/search",
                         params=params, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.warning("Careerjet %s/%s failed: %s", locale, search.get("label"), e)
        return []

    out = []
    for j in data.get("jobs", []):
        link = j.get("url", "")
        if not link:
            continue
        jid = hashlib.md5(link.encode("utf-8")).hexdigest()[:16]
        out.append({
            "key": _key("careerjet", jid),
            "source": f"Careerjet ({locale[-2:].upper()})",
            "title": (j.get("title") or "").strip(),
            "company": (j.get("company") or "").strip(),
            "location": (j.get("locations") or "").strip(),
            "salary": (j.get("salary") or "").strip() or None,
            "url": link,
            "posted": (j.get("date") or ""),
            "description": j.get("description", ""),
            "matched_on": search.get("label", ""),
        })
    return out


def fetch_jsearch(search: dict, country: str, max_days_old: int) -> list:
    """JSearch (RapidAPI) reads Google for Jobs, which indexes LinkedIn, Indeed,
    Glassdoor, ZipRecruiter, Monster and more. Dormant until JSEARCH_API_KEY is set.
    Each result is tagged with the board it actually came from (job_publisher)."""
    if not config.JSEARCH_API_KEY:
        return []
    date_posted = "month" if max_days_old > 7 else ("week" if max_days_old > 3 else "3days")
    query = search["phrase"]
    if search.get("extra"):
        query = f'{search["extra"]} {query}'
    headers = {
        "X-RapidAPI-Key": config.JSEARCH_API_KEY,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }
    params = {"query": query, "page": 1, "num_pages": 1,
              "date_posted": date_posted, "country": country}
    try:
        r = requests.get("https://jsearch.p.rapidapi.com/search",
                         headers=headers, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.warning("JSearch %s/%s failed: %s", country, search.get("label"), e)
        return []

    out = []
    for j in data.get("data", []):
        jid = str(j.get("job_id", "")).strip()
        if not jid:
            continue
        out.append({
            "key": _key("jsearch", jid),
            "source": f"{j.get('job_publisher') or 'Google Jobs'} (via JSearch)",
            "title": (j.get("job_title") or "").strip(),
            "company": (j.get("employer_name") or "").strip(),
            "location": ", ".join(p for p in [j.get("job_city"), j.get("job_country")] if p),
            "salary": None,
            "url": j.get("job_apply_link", ""),
            "posted": (j.get("job_posted_at_datetime_utc") or "")[:10],
            "description": j.get("job_description", ""),
            "matched_on": search.get("label", ""),
        })
    return out


def fetch_all(settings: dict) -> list:
    searches = settings.get("searches") or config.DEFAULT_SETTINGS["searches"]
    countries = settings.get("countries") or config.DEFAULT_SETTINGS["countries"]
    max_days_old = settings.get("max_days_old", config.DEFAULT_SETTINGS["max_days_old"])
    cj_locales = settings.get("careerjet_locales") or config.DEFAULT_SETTINGS["careerjet_locales"]
    jsearch_countries = settings.get("jsearch_countries") or config.DEFAULT_SETTINGS["jsearch_countries"]
    js_cap = settings.get("jsearch_max_per_run", config.DEFAULT_SETTINGS["jsearch_max_per_run"])
    js_used = 0

    jobs, seen = [], set()

    def _add(items):
        for j in items:
            if j["key"] not in seen:
                seen.add(j["key"])
                jobs.append(j)

    for search in searches:
        for country in countries:                       # Adzuna: per-country
            _add(fetch_adzuna(search, country, max_days_old))
        _add(fetch_reed(search))                         # Reed: UK
        _add(fetch_jooble(search))                       # Jooble: global aggregator
        for locale in cj_locales:                        # Careerjet: per-locale
            _add(fetch_careerjet(search, locale))
        for country in jsearch_countries:                # JSearch: Google Jobs (LinkedIn/Indeed/...)
            if js_used >= js_cap:                        # free-tier quota guard
                break
            _add(fetch_jsearch(search, country, max_days_old))
            js_used += 1

    log.info("Fetched %d unique postings across all sources", len(jobs))
    return jobs
