"""One-off, NO-GROQ fix: for every existing Companies House lead, set the registration
date, use the company name as the title, and recompute the tier from recency
(<=6mo HOT, <=12mo WARM, else WATCH). Pulls dates from the Companies House search
(free) - does NOT call the AI brain, so it spends no Groq quota. Categories already set
by the backfill are left untouched."""
import logging
import requests
import config
import brain
import companies_house
import supabase_io

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("fix")
BASE = config.SUPABASE_URL.rstrip("/") + "/rest/v1/leads"
H = {"apikey": config.SUPABASE_SERVICE_KEY, "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}"}


def run():
    if not (config.COMPANIES_HOUSE_API_KEY and supabase_io.configured()):
        log.error("Missing Companies House / Supabase config."); return
    settings = supabase_io.load_settings() or dict(config.DEFAULT_SETTINGS)

    # Build external_key -> {registered_at, title} from a fresh Companies House sweep.
    by_key = {c["key"]: c for c in companies_house.fetch_all_backfill(settings)}
    log.info("Have registration data for %d companies.", len(by_key))

    r = requests.get(BASE, headers=H, params={
        "select": "id,external_key", "source": "eq.Companies House", "limit": "5000"})
    r.raise_for_status()
    leads = r.json()
    log.info("Fixing %d existing showroom leads.", len(leads))

    fixed = nomatch = 0
    for lead in leads:
        c = by_key.get(lead["external_key"])
        if not c:
            nomatch += 1; continue
        patch = {
            "registered_at": c.get("registered_at"),
            "title": c.get("title"),
            "tier": brain.tier_from_registration(c.get("registered_at"), settings),
        }
        rr = requests.patch(BASE, headers={**H, "Prefer": "return=minimal"},
                            params={"id": f"eq.{lead['id']}"}, json=patch)
        if rr.status_code < 300:
            fixed += 1
    log.info("DONE. fixed %d, no-match %d.", fixed, nomatch)


if __name__ == "__main__":
    run()
