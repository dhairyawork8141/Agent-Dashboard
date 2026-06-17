import logging
import time
from datetime import datetime, timezone

import requests
import config
import web_search_enrich
import supabase_io

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(name)-9s %(levelname)s  %(message)s")
log = logging.getLogger("backfill")

_LEGAL_SUFFIXES = (" limited", " ltd", " ltd.", " llp", " plc", " (uk)", " uk ltd")

def _clean_company(name: str) -> str:
    out = name.strip()
    low = out.lower()
    for suf in _LEGAL_SUFFIXES:
        if low.endswith(suf):
            out = out[: len(out) - len(suf)].strip()
            break
    return out

def _company_name(lead: dict) -> str | None:
    name = (lead.get("showroom_name") or "").strip()
    if not name or "unknown" in name.lower():
        name = (lead.get("company") or "").strip()
    return _clean_company(name) if name else None

def get_leads_without_website():
    """Fetch all leads that don't have a website yet."""
    base_url = config.SUPABASE_URL.rstrip("/") + "/rest/v1"
    headers = {
        "apikey": config.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }
    try:
        r = requests.get(f"{base_url}/leads", headers=headers, params={
            "select": "id,company,showroom_name,location,contact_email",
            "website": "is.null",
        }, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.error("Failed to fetch leads: %s", e)
        return []

def run():
    if not supabase_io.configured():
        log.error("Supabase is not configured.")
        return

    leads = get_leads_without_website()
    log.info("Found %d leads missing website/socials.", len(leads))

    done = 0
    for lead in leads:
        name = _company_name(lead)
        if not name:
            continue
        
        log.info("Backfilling '%s'...", name)
        web_result = web_search_enrich.enrich_from_web(name, lead.get("location"))
        
        if web_result and (web_result.get("website") or any(k.startswith("social_") for k in web_result)):
            patch = {}
            # Only update fields that are present in web_result
            if web_result.get("website"):
                patch["website"] = web_result["website"]
            for k in web_result:
                if k.startswith("social_") and web_result.get(k):
                    patch[k] = web_result[k]
                    
            # If they don't have an email, and we found one, add it too!
            if not lead.get("contact_email") and web_result.get("contact_email"):
                patch["contact_email"] = web_result["contact_email"]
                if web_result.get("contact_name"):
                    patch["contact_name"] = web_result["contact_name"]
                if web_result.get("contact_title"):
                    patch["contact_title"] = web_result["contact_title"]
                patch["status"] = "Contact found"
                patch["enriched_at"] = datetime.now(timezone.utc).isoformat()
            
            if patch:
                if supabase_io.update_lead(lead["id"], patch):
                    done += 1
                    log.info("Successfully updated '%s' with %d fields.", name, len(patch))
        else:
            log.info("No website/socials found for '%s'.", name)

        time.sleep(1) # Be nice to the network and web scraping

    log.info("Backfill complete. Updated %d leads.", done)

if __name__ == "__main__":
    run()
