"""One-off: free web-scrape enrichment for HOT leads that don't have a website yet.
Fills website + socials (+ a contact email/name if found on the site). NO Apollo,
NO email drafting - just gets the HOT showrooms enriched into the dashboard now."""
import logging
import time
from datetime import datetime, timezone

import requests
import config
import web_search_enrich
import supabase_io

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("enrich-hot")

_SUFFIXES = (" limited", " ltd", " ltd.", " llp", " plc", " (uk)", " uk ltd")


def _name(l: dict) -> str:
    n = (l.get("showroom_name") or l.get("company") or "").strip()
    low = n.lower()
    for s in _SUFFIXES:
        if low.endswith(s):
            return n[: len(n) - len(s)].strip()
    return n


def _hot_needing_web() -> list[dict]:
    base = config.SUPABASE_URL.rstrip("/") + "/rest/v1"
    h = {"apikey": config.SUPABASE_SERVICE_KEY,
         "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}"}
    r = requests.get(f"{base}/leads", headers=h, params={
        "select": "id,company,showroom_name,location,contact_email,website",
        "tier": "like.HOT*", "website": "is.null", "limit": "1000"}, timeout=20)
    r.raise_for_status()
    return r.json()


def run():
    if not supabase_io.configured():
        log.error("Supabase not configured."); return
    leads = _hot_needing_web()
    log.info("%d HOT leads need web enrichment.", len(leads))
    done = 0
    for l in leads:
        name = _name(l)
        if not name:
            continue
        web = web_search_enrich.enrich_from_web(name, l.get("location"))
        if web and (web.get("website") or any(k.startswith("social_") for k in web)):
            patch = {}
            if web.get("website"):
                patch["website"] = web["website"]
            for k in web:
                if k.startswith("social_") and web.get(k):
                    patch[k] = web[k]
            if not l.get("contact_email") and web.get("contact_email"):
                patch["contact_email"] = web["contact_email"]
                if web.get("contact_name"):
                    patch["contact_name"] = web["contact_name"]
                if web.get("contact_title"):
                    patch["contact_title"] = web["contact_title"]
                patch["status"] = "Contact found"
                patch["enriched_at"] = datetime.now(timezone.utc).isoformat()
            if patch and supabase_io.update_lead(l["id"], patch):
                done += 1
                log.info("enriched '%s' (+%d fields)", name, len(patch))
        time.sleep(1)
    log.info("DONE. enriched %d HOT lead(s).", done)


if __name__ == "__main__":
    run()
