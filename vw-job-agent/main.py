"""CAD Illustrators - Virtual Worlds job-watch agent.

Each run:
  load settings (from the dashboard if connected)  ->  fetch postings
  ->  drop ones already seen  ->  score & tier  ->  (optional) enrich with Claude
  ->  notify (CSV + email)  ->  write finds to the dashboard  ->  remember them
"""
import logging

import config
import sources
import store
import scorer
import brain
import notify
import hermes
import dispatch
import supabase_io
from settings_loader import load_settings

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(name)-9s %(levelname)s  %(message)s")
log = logging.getLogger("main")


def run() -> None:
    settings = load_settings()
    if settings is None:                     # paused in the dashboard
        return

    # Hermes plans this run from shared memory (datacenter): tunes work caps toward the HOT goal.
    settings, plan_note = hermes.plan("job", settings)
    log.info("Hermes: %s", plan_note)
    # Learning loop: feed the user's recent rejections to the brain so it avoids similar leads.
    settings["rejection_feedback"] = supabase_io.recent_rejections()
    if settings["rejection_feedback"]:
        log.info("Learning from %d recent user rejection(s).", len(settings["rejection_feedback"]))

    found = sources.fetch_all(settings)
    new = store.filter_new(found)
    log.info("%d new postings after de-duplication", len(new))

    if not new:
        if supabase_io.configured():
            supabase_io.finish_run(config.AGENT_ID, "ok", 0)
        return

    new = [scorer.score_job(j, settings) for j in new]

    # Stage 1 - cheap keyword pre-filter: drop disqualified + below-threshold noise.
    min_score = settings.get("min_score", config.DEFAULT_SETTINGS["min_score"])
    scored = new
    candidates = [j for j in scored if not j.get("disqualified") and j.get("score", 0) >= min_score]
    log.info("Keyword pre-filter: %d of %d postings are candidates (min_score=%d)",
             len(candidates), len(scored), min_score)

    # Stage 2 - AI brain judges each candidate for genuine KBB/interior-design fit.
    if candidates and settings.get("use_brain") and brain.available():
        cap = settings.get("brain_max_per_run", config.DEFAULT_SETTINGS["brain_max_per_run"])
        batch = candidates[:cap]
        judged = [brain.judge(j, settings) for j in batch]
        kept = [j for j in judged if j is not None]
        rejected = len(batch) - len(kept)
        # Datacenter: record EVERY judged candidate (kept AND rejected) before filtering.
        kept_ids = {id(j) for j in kept}
        for j in batch:
            j["_stage"] = "judged"
            j["_decision"] = "kept" if id(j) in kept_ids else "rejected"
            if id(j) not in kept_ids:
                j["_reject_reason"] = "not a KBB-designer fit"
        if supabase_io.configured():
            supabase_io.record_candidates(batch)
        leftover = candidates[cap:]     # beyond the per-run cap: keep keyword verdict
        new = kept + leftover
        log.info("AI brain: kept %d, rejected %d (of %d judged; %d beyond cap kept on keyword score)",
                 len(kept), rejected, len(batch), len(leftover))
    else:
        new = candidates

    if not new:
        log.info("No leads cleared the filters this run.")
        if supabase_io.configured():
            supabase_io.finish_run(config.AGENT_ID, "ok", 0)
        store.commit(scored)            # still remember them so they aren't re-checked
        return

    new.sort(key=lambda j: -j.get("score", 0))

    notify.notify(new, bool(settings.get("send_email")))

    if supabase_io.configured():
        supabase_io.upsert_leads(config.AGENT_ID, new)
        supabase_io.finish_run(config.AGENT_ID, "ok", len(new))
        # Chain: new HOT leads -> enrich them immediately (don't wait for the contact cron).
        if any((j.get("tier") or "").upper().startswith("HOT") for j in new):
            dispatch.fire("contact-agent.yml")

    store.commit(new)
    log.info("Done - %d lead(s) delivered.", len(new))


if __name__ == "__main__":
    run()
