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
import osm_source
import store
import brain
import hotness
import hermes
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

    # Hermes plans this run from shared memory (datacenter): pushes work caps up when behind
    # the daily HOT goal, baseline when on track.
    settings, plan_note = hermes.plan("showroom", settings)
    log.info("Hermes: %s", plan_note)
    # Learning loop: feed the user's recent rejections to the brain so it avoids similar leads.
    settings["rejection_feedback"] = supabase_io.recent_rejections()
    if settings["rejection_feedback"]:
        log.info("Learning from %d recent user rejection(s).", len(settings["rejection_feedback"]))

    # Capture the FULL KBB directory (all dates) — established (WATCH) ones are kept as
    # data but don't count as "leads" (the dashboard's Total leads = HOT+WARM only).
    # Shuffled + capped per run so the daily agent finishes the backlog and catches new ones.
    # Multi-source UK lead finding: Companies House (new registrations) + OpenStreetMap
    # (existing mapped KBB/interior shops). Both feed the same brain → tier → upsert pipeline.
    found = companies_house.fetch_all_backfill(settings) + osm_source.fetch_all(settings)
    new = store.filter_new(found)
    random.shuffle(new)
    log.info("%d unjudged companies (processing up to the per-run cap)", len(new))
    if not new:
        supabase_io.finish_run("ok", 0)
        return

    cap = int(settings.get("max_per_run", 25))
    min_score = int(settings.get("min_score", 50))
    use_brain = bool(settings.get("use_brain", True)) and brain.available()

    candidates = new[:cap]                      # bound brain calls / writes per run
    kept = []
    for lead in candidates:
        lead["_stage"] = "judged"
        # Tier suffix reflects the source; the HOT/WARM/WATCH prefix is decided by Smart HOT.
        lead["_tier_suffix"] = "New showroom" if lead.get("registered_at") else "Showroom"
        if use_brain:
            v = brain.classify(lead, settings)  # brain decides fit + business category
            time.sleep(1.5)                     # pace under Groq per-minute limits
            if v is None:                       # API failed -> keep, category unknown
                lead["category"] = "other"
                lead["score"] = min_score
                lead["_fit"] = None
                lead["tier"] = hotness.smart_tier(lead, None, settings)
            elif v["fit"] and v["score"] >= min_score:
                lead["category"] = v["category"]
                lead["score"] = v["score"]
                lead["reason"] = v["reason"]
                lead["_fit"] = True
                lead["tier"] = hotness.smart_tier(lead, v, settings)
            else:                               # brain rejected -> record tier + why, then skip
                lead["category"] = v.get("category", "other")
                lead["score"] = v.get("score", 0)
                lead["_fit"] = bool(v.get("fit"))
                lead["tier"] = hotness.smart_tier(lead, v, settings)
                lead["_decision"] = "rejected"
                lead["_reject_reason"] = (v.get("reason")
                                          or ("below min_score" if v.get("fit") else "not a KBB fit"))
                continue
        else:
            lead["category"] = "other"
            lead["score"] = min_score
            lead["tier"] = hotness.smart_tier(lead, None, settings)
        lead["_decision"] = "kept"
        kept.append(lead)

    log.info("Brain kept %d of %d judged (cap %d)", len(kept), len(candidates), cap)

    # Datacenter: record ALL judged candidates (kept AND rejected) before anything else.
    supabase_io.record_candidates(candidates)

    if kept:
        supabase_io.upsert_leads(config.AGENT_ID, kept)
    supabase_io.finish_run("ok", len(kept))

    # Remember ALL fetched-new companies (even rejects) so we don't re-judge them.
    store.commit(new)
    log.info("Done - %d showroom lead(s) delivered.", len(kept))


if __name__ == "__main__":
    run()
