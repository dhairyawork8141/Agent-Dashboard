"""Companies House client (free official API). Finds newly-incorporated UK companies
whose name signals a kitchen/bedroom/bathroom or interior business, via the
advanced-search endpoint. Auth is HTTP Basic with the API key as the username."""
import logging
from datetime import date, timedelta
import requests
import config

log = logging.getLogger("companieshouse")
TIMEOUT = 25
_BASE = "https://api.company-information.service.gov.uk"
_PROFILE_URL = "https://find-and-update.company-information.service.gov.uk/company/"


def _auth():
    return (config.COMPANIES_HOUSE_API_KEY, "")


def _fmt_address(addr: dict) -> str:
    if not addr:
        return ""
    parts = [addr.get("locality"), addr.get("region"), addr.get("postal_code")]
    return ", ".join(p for p in parts if p)


def _advanced_search(name_includes: str, incorporated_from: str | None,
                     status: str, sic_codes: list[str],
                     max_pages: int = 25) -> list[dict]:
    """Paginated advanced search. `incorporated_from=None` searches ALL dates (backfill)."""
    items, start, size = [], 0, 500
    for _ in range(max_pages):
        params = {
            "company_name_includes": name_includes,
            "company_status": status,
            "size": size,
            "start_index": start,
        }
        if incorporated_from:
            params["incorporated_from"] = incorporated_from
        if sic_codes:
            params["sic_codes"] = ",".join(sic_codes)
        try:
            r = requests.get(f"{_BASE}/advanced-search/companies",
                             params=params, auth=_auth(), timeout=TIMEOUT)
            r.raise_for_status()
            page = r.json().get("items", [])
        except Exception as e:
            log.warning("Companies House search '%s' (start %d) failed: %s",
                        name_includes, start, e)
            break
        items.extend(page)
        if len(page) < size:
            break
        start += size
    return items


def _to_lead(item: dict) -> dict | None:
    number = (item.get("company_number") or "").strip()
    name = (item.get("company_name") or "").strip()
    if not number or not name:
        return None
    sics = item.get("sic_codes") or []
    created = item.get("date_of_creation", "")
    return {
        "key": f"companieshouse:{number}",
        "source": "Companies House",
        "title": name,                          # the showroom's name is the headline
        "company": name,
        "showroom_name": name,
        "location": _fmt_address(item.get("registered_office_address") or {}),
        "registered_at": created or None,       # official registration date
        "salary": None,
        "url": f"{_PROFILE_URL}{number}",
        "posted": created,
        "description": f"Incorporated {created or '?'}. "
                       f"SIC: {', '.join(sics) if sics else 'n/a'}. "
                       f"Status: {item.get('company_status','')}.",
        "matched_on": "Companies House",
    }


def _search_keywords(settings: dict, incorporated_from: str | None) -> list[dict]:
    keywords = settings.get("name_keywords") or config.DEFAULT_SETTINGS["name_keywords"]
    status = settings.get("company_status", "active")
    sic_codes = settings.get("sic_codes") or []
    out, seen = [], set()
    for kw in keywords:
        for item in _advanced_search(kw, incorporated_from, status, sic_codes):
            lead = _to_lead(item)
            if lead and lead["key"] not in seen:
                seen.add(lead["key"])
                out.append(lead)
    return out


def fetch_all(settings: dict) -> list[dict]:
    """Daily mode: only companies incorporated within the last N days (new-showroom alert)."""
    if not config.COMPANIES_HOUSE_API_KEY:
        log.error("COMPANIES_HOUSE_API_KEY not set - nothing to fetch.")
        return []
    days = int(settings.get("incorporated_within_days", 45))
    since = (date.today() - timedelta(days=days)).isoformat()
    out = _search_keywords(settings, since)
    log.info("Fetched %d unique new companies (since %s)", len(out), since)
    return out


def fetch_all_backfill(settings: dict) -> list[dict]:
    """Backfill mode: ALL matching companies regardless of incorporation date."""
    if not config.COMPANIES_HOUSE_API_KEY:
        log.error("COMPANIES_HOUSE_API_KEY not set - nothing to fetch.")
        return []
    out = _search_keywords(settings, None)
    log.info("Backfill fetched %d unique companies (all dates)", len(out))
    return out
