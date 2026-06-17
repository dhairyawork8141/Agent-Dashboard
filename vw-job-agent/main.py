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
import enrich
import notify
import supabase_io
from settings_loader import load_settings

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(name)-9s %(levelname)s  %(message)s")
log = logging.getLogger("main")


def run() -> None:
    settings = load_settings()
    if settings is None:                     # paused in the dashboard
        return

    found = sources.fetch_all(settings)
    new = store.filter_new(found)
    log.info("%d new postings after de-duplication", len(new))

    if not new:
        if supabase_io.configured():
            supabase_io.finish_run(config.AGENT_ID, "ok", 0)
        return

    new = [scorer.score_job(j, settings) for j in new]
    if settings.get("enrich_with_claude"):
        new = [enrich.enrich(j) for j in new]
    new.sort(key=lambda j: -j.get("score", 0))

    notify.notify(new, bool(settings.get("send_email")))

    if supabase_io.configured():
        supabase_io.upsert_leads(config.AGENT_ID, new)
        supabase_io.finish_run(config.AGENT_ID, "ok", len(new))

    store.commit(new)
    log.info("Done - %d lead(s) delivered.", len(new))


if __name__ == "__main__":
    run()
