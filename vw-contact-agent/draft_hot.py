"""One-off: template-draft every HOT lead that has a contact email but no approved/sent
draft yet, and park it as 'pending' for review. Uses the per-sector templates (no AI).
Leaves approved/sent/rejected drafts untouched."""
import logging
from datetime import datetime, timezone

import requests
import config
import draft
import supabase_io

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("draft-hot")
BASE = config.SUPABASE_URL.rstrip("/") + "/rest/v1/leads"
H = {"apikey": config.SUPABASE_SERVICE_KEY, "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}"}


def run():
    if not supabase_io.configured() or not draft.available():
        log.error("Supabase/templates not available."); return
    r = requests.get(BASE, headers=H, params={
        "select": "*", "tier": "like.HOT*", "contact_email": "not.is.null", "limit": "2000"})
    r.raise_for_status()
    leads = [l for l in r.json() if (l.get("draft_status") or "none") in ("none", "pending")]
    log.info("%d HOT lead(s) with an email to draft.", len(leads))

    done = 0
    for l in leads:
        d = draft.draft_email(l, l)            # lead row carries contact_name etc.
        if not d:
            continue
        patch = {"draft_subject": d["subject"], "draft_body": d["body"],
                 "draft_status": "pending",
                 "drafted_at": datetime.now(timezone.utc).isoformat()}
        if supabase_io.update_lead(l["id"], patch):
            done += 1
            log.info("drafted [%s] %s", d["template"], (l.get("company") or "")[:34])
    log.info("DONE. drafted %d HOT lead(s) into Needs approval.", done)


if __name__ == "__main__":
    run()
