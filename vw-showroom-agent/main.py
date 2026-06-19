"""CAD Illustrators - New-Showroom Finder (agent #3).

Each run:
  load settings  ->  Companies House: newly-incorporated KBB/interior companies
  ->  drop ones already seen  ->  Groq brain judges each for genuine KBB fit
  ->  keep fits >= min_score  ->  write to the dashboard as leads  ->  remember them

The leads it writes are ordinary leads, so agent #2 then enriches them (contact, website,
socials) and drafts outreach - same pipeline as job-ad leads, just a new source.
"""
import logging
import random
import time

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

    # Only the ≤12-month lead window (HOT/WARM); established showrooms aren't leads for us.
    # Process unjudged ones shuffled, up to the per-run cap, so coverage stays balanced and
    # the daily agent gradually finishes the window AND catches new registrations.
    found = companies_house.fetch_lead_window(settings)
    new = store.filter_new(found)
    random.shuffle(new)
    log.info("%d unjudged companies in the lead window", len(new))
    if not new:
        supabase_io.finish_run("ok", 0)
        return

    cap = int(settings.get("max_per_run", 25))
    min_score = int(settings.get("min_score", 50))
    use_brain = bool(settings.get("use_brain", True)) and brain.available()

    candidates = new[:cap]                      # bound brain calls / writes per run
    kept = []
    for lead in candidates:
        # Tier is deterministic from the registration date (<=6mo HOT, <=12mo WARM, else WATCH).
        lead["tier"] = brain.tier_from_registration(lead.get("registered_at"), settings)
        if (lead["tier"] or "").startswith("WATCH"):
            continue                            # established (>12mo) -> not a lead, skip
        if use_brain:
            v = brain.classify(lead, settings)  # brain decides fit + business category
            time.sleep(1.5)                     # pace under Groq per-minute limits
            if v is None:                       # API failed -> keep, category unknown
                lead["category"] = "other"
                lead["score"] = min_score
            elif v["fit"] and v["score"] >= min_score:
                lead["category"] = v["category"]
                lead["score"] = v["score"]
                lead["reason"] = v["reason"]
            else:
                continue                        # brain rejected -> skip
        else:
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
