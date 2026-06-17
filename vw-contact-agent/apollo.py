"""Apollo.io REST client: company name -> senior decision-maker -> revealed email/phone.

Uses the official v1 API with an API key (header X-Api-Key). Every call fails soft:
a single error returns an empty result and is logged, so one bad lead never stops a run.

Credit model (so we never surprise-spend):
  * company search + people search   -> search calls, do NOT spend lead credits
  * people/match (the reveal)        -> spends ~1 lead credit, and only this is called
                                        once per lead, for the single best person.
"""
import logging
import requests
import config

log = logging.getLogger("apollo")
BASE = "https://api.apollo.io/api/v1"
TIMEOUT = 30


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": config.APOLLO_API_KEY,
    }


def find_org(name: str) -> tuple[str | None, str | None]:
    """Return (organization_id, domain) for the best company match.

    Apollo splits results across `organizations` (often domain-less stubs like
    "<Name> IT") and `accounts` (usually the real record with a domain), so prefer
    whichever candidate actually carries a domain."""
    try:
        r = requests.post(f"{BASE}/mixed_companies/search", headers=_headers(),
                          json={"q_organization_name": name, "page": 1, "per_page": 5},
                          timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        candidates = (data.get("organizations") or []) + (data.get("accounts") or [])
        if not candidates:
            return None, None
        with_domain = [c for c in candidates if (c.get("primary_domain") or c.get("domain"))]
        chosen = with_domain[0] if with_domain else candidates[0]
        return chosen.get("id"), (chosen.get("primary_domain") or chosen.get("domain"))
    except Exception as e:
        log.warning("find_org failed for '%s': %s", name, e)
        return None, None


def find_person(org_id: str | None, domain: str | None,
                titles: list[str], locations: list[str]) -> dict | None:
    """Most relevant person for the target titles. Searching by company DOMAIN is far
    more reliable than by org id (Apollo's domain-less org stubs match poorly)."""
    try:
        payload = {"person_titles": titles, "person_locations": locations,
                   "page": 1, "per_page": 5}
        if domain:
            payload["q_organization_domains_list"] = [domain]
        elif org_id:
            payload["organization_ids"] = [org_id]
        else:
            return None
        r = requests.post(f"{BASE}/mixed_people/api_search", headers=_headers(),
                          json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        people = r.json().get("people") or []
        return people[0] if people else None
    except Exception as e:
        log.warning("find_person failed (org=%s domain=%s): %s", org_id, domain, e)
        return None


def reveal(person: dict, domain: str | None, reveal_phone: bool = False) -> dict:
    """Reveal a person's work email (and optionally phone). Spends ~1 lead credit."""
    try:
        payload = {
            "id": person.get("id"),
            "first_name": person.get("first_name"),
            "last_name": person.get("last_name"),
            "organization_name": (person.get("organization") or {}).get("name"),
            "domain": domain,
            "reveal_personal_emails": False,
        }
        if reveal_phone:
            payload["reveal_phone_number"] = True
        r = requests.post(f"{BASE}/people/match", headers=_headers(),
                          json={k: v for k, v in payload.items() if v is not None},
                          timeout=TIMEOUT)
        r.raise_for_status()
        return r.json().get("person") or {}
    except Exception as e:
        log.warning("reveal failed for %s %s: %s",
                    person.get("first_name"), person.get("last_name"), e)
        return {}


def best_email(person: dict) -> str | None:
    """Apollo returns a placeholder until a reveal succeeds — filter those out."""
    e = person.get("email")
    if e and "email_not_unlocked" not in e and "domain.com" not in e:
        return e
    for c in person.get("contact_emails") or []:
        addr = c.get("email")
        if addr and "email_not_unlocked" not in addr:
            return addr
    return None


def best_phone(person: dict) -> str | None:
    for p in person.get("phone_numbers") or []:
        num = p.get("sanitized_number") or p.get("raw_number")
        if num:
            return num
    return None
