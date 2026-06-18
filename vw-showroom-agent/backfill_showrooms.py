"""One-off: backfill ALL existing KBB showrooms from Companies House (not just newly
incorporated). Judges each with the 8B Groq model (high free daily budget), writes the
fits to the dashboard in batches, and records them as seen so the daily agent won't redo
them. Run locally with env vars set (COMPANIES_HOUSE_API_KEY, SUPABASE_*, GROQ_API_KEY, AGENT_ID)."""
import logging
import time

import config
import companies_house
import store
import brain
import supabase_io

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("backfill")

BRAIN_MODEL = "llama-3.1-8b-instant"   # big daily token budget, fine for KBB fit judging


def run():
    if not (config.COMPANIES_HOUSE_API_KEY and supabase_io.configured() and brain.available()):
        log.error("Missing config (Companies House / Supabase / Groq) - aborting.")
        return
    settings = supabase_io.load_settings() or dict(config.DEFAULT_SETTINGS)
    settings = {**settings, "brain_model": BRAIN_MODEL}
    min_score = int(settings.get("min_score", 50))

    companies = companies_house.fetch_all_backfill(settings)
    new = store.filter_new(companies)
    log.info("%d companies to judge (after dedup) with %s", len(new), BRAIN_MODEL)

    batch, kept, judged = [], 0, 0
    for i, lead in enumerate(new, 1):
        v = brain.classify(lead, settings)
        judged += 1
        if v is None:                       # rate-limited / error -> keep neutral, don't lose it
            time.sleep(6); continue
        if v["fit"] and v["score"] >= min_score:
            lead["tier"] = brain.tier_from_registration(lead.get("registered_at"), settings)
            lead["score"], lead["reason"] = v["score"], v["reason"]
            lead["category"] = v["category"]
            batch.append(lead); kept += 1
        if i % 25 == 0:
            log.info("  ...judged %d/%d, kept %d so far", i, len(new), kept)
        if len(batch) >= 50:
            supabase_io.upsert_leads(config.AGENT_ID, batch); batch = []
        time.sleep(4.5)                     # pace under Groq 8B free TPM (~6k) to avoid 429s

    if batch:
        supabase_io.upsert_leads(config.AGENT_ID, batch)
    store.commit(new)                       # remember ALL judged (incl. rejects)
    supabase_io.finish_run("ok", kept)
    log.info("DONE. judged %d, kept %d KBB showrooms.", judged, kept)


if __name__ == "__main__":
    run()
