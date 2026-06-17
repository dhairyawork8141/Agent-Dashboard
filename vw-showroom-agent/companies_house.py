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


def _advanced_search(name_includes: str, incorporated_from: str,
                     status: str, sic_codes: list[str]) -> list[dict]:
    params = {
        "company_name_includes": name_includes,
        "incorporated_from": incorporated_from,
        "company_status": status,
        "size": 100,
    }
    if sic_codes:
        params["sic_codes"] = ",".join(sic_codes)
    try:
        r = requests.get(f"{_BASE}/advanced-search/companies",
                         params=params, auth=_auth(), timeout=TIMEOUT)
        r.raise_for_status()
        return r.json().get("items", [])
    except Exception as e:
        log.warning("Companies House search '%s' failed: %s", name_includes, e)
        return []


def _to_lead(item: dict) -> dict | None:
    number = (item.get("company_number") or "").strip()
    name = (item.get("company_name") or "").strip()
    if not number or not name:
        return None
    sics = item.get("sic_codes") or []
    return {
        "key": f"companieshouse:{number}",
        "source": "Companies House",
        "title": "Newly registered KBB/interior business",
        "company": name,
        "showroom_name": name,
        "location": _fmt_address(item.get("registered_office_address") or {}),
        "salary": None,
        "url": f"{_PROFILE_URL}{number}",
        "posted": item.get("date_of_creation", ""),
        "description": f"Incorporated {item.get('date_of_creation','?')}. "
                       f"SIC: {', '.join(sics) if sics else 'n/a'}. "
                       f"Status: {item.get('company_status','')}.",
        "matched_on": "Companies House (new incorporation)",
    }


def fetch_all(settings: dict) -> list[dict]:
    if not config.COMPANIES_HOUSE_API_KEY:
        log.error("COMPANIES_HOUSE_API_KEY not set - nothing to fetch.")
        return []
    keywords = settings.get("name_keywords") or config.DEFAULT_SETTINGS["name_keywords"]
    days = int(settings.get("incorporated_within_days", 45))
    status = settings.get("company_status", "active")
    sic_codes = settings.get("sic_codes") or []
    since = (date.today() - timedelta(days=days)).isoformat()

    out, seen = [], set()
    for kw in keywords:
        for item in _advanced_search(kw, since, status, sic_codes):
            lead = _to_lead(item)
            if lead and lead["key"] not in seen:
                seen.add(lead["key"])
                out.append(lead)
    log.info("Fetched %d unique new companies (since %s)", len(out), since)
    return out
