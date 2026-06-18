"""CAD Illustrators - New-Showroom Finder (agent #3).

Each run:
  load settings  ->  Companies House: newly-incorporated KBB/interior companies
  ->  drop ones already seen  ->  Groq brain judges each for genuine KBB fit
  ->  keep fits >= min_score  ->  write to the dashboard as leads  ->  remember them

The leads it writes are ordinary leads, so agent #2 then enriches them (contact, website,
socials) and drafts outreach - same pipeline as job-ad leads, just a new source.
"""
import logging

import config
import companies_house
import store
import brain
import supabase_io

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(name)-12s %(levelname)s  %(message)s")
log = logging.getLogger("main")


def run() -> None:
    if not config.COMPANIES_HOUSE_API_KEY:
        log.error("COMPANIES_HOUSE_API_KEY is not set - nothing to do.")
        return
    if not supabase_io.configured():
        log.error("Supabase is not configured - nothing to do.")
        return

    settings = supabase_io.load_settings()
    if settings is None:                       # paused in the dashboard
        return

    found = companies_house.fetch_all(settings)
    new = store.filter_new(found)
    log.info("%d new companies after de-duplication", len(new))
    if not new:
        supabase_io.finish_run("ok", 0)
        return

    cap = int(settings.get("max_per_run", 25))
    min_score = int(settings.get("min_score", 50))
    use_brain = bool(settings.get("use_brain", True)) and brain.available()

    candidates = new[:cap]                      # bound brain calls / writes per run
    kept = []
    for lead in candidates:
        if use_brain:
            v = brain.classify(lead, settings)
            if v is None:                       # API failed -> keep with a neutral tier
                lead["tier"] = brain.TIER_WATCH
                lead["category"] = "other"
                lead["score"] = min_score
            elif v["fit"] and v["score"] >= min_score:
                lead["tier"] = v["tier"]
                lead["category"] = v["category"]
                lead["score"] = v["score"]
                lead["reason"] = v["reason"]
            else:
                continue                        # brain rejected -> skip
        else:
            lead["tier"] = brain.TIER_WARM
            lead["category"] = "other"
            lead["score"] = min_score
        kept.append(lead)

    log.info("Brain kept %d of %d judged (cap %d)", len(kept), len(candidates), cap)

    if kept:
        supabase_io.upsert_leads(config.AGENT_ID, kept)
    supabase_io.finish_run("ok", len(kept))

    # Remember ALL fetched-new companies (even rejects) so we don't re-judge them.
    store.commit(new)
    log.info("Done - %d showroom lead(s) delivered.", len(kept))


if __name__ == "__main__":
    run()
