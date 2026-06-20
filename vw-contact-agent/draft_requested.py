"""Fast, frequent worker for the dashboard "Draft email" button. Processes only leads
flagged draft_status='requested': enrich the contact if needed (free web-scrape), then
draft from the right per-sector template (+ light AI personalisation) -> 'pending'.
Runs on a short cron so a clicked draft shows in Needs approval within ~20 minutes.
Clears the request if no verified email can be found. No Apollo, low cost."""
import logging
from datetime import datetime, timezone

import config
import web_search_enrich
import draft
import supabase_io

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(name)-9s %(levelname)s  %(message)s")
log = logging.getLogger("draft-req")

_SUFFIXES = (" limited", " ltd", " ltd.", " llp", " plc", " (uk)", " uk ltd")


def _name(lead: dict) -> str:
    n = (lead.get("showroom_name") or lead.get("company") or "").strip()
    low = n.lower()
    for s in _SUFFIXES:
        if low.endswith(s):
            return n[: len(n) - len(s)].strip()
    return n


def run():
    if not supabase_io.configured():
        log.error("Supabase not configured."); return
    settings = supabase_io.load_settings() or dict(config.DEFAULT_SETTINGS)
    requested = supabase_io.leads_requested_draft()
    if not requested:
        log.info("No requested drafts."); return
    log.info("%d requested draft(s) to handle.", len(requested))

    done = 0
    for lead in requested:
        name = _name(lead)
        contact = {k: lead.get(k) for k in ("contact_name", "contact_title",
                   "contact_email", "contact_phone", "contact_linkedin") if lead.get(k)}
        if not contact.get("contact_email") and name:
            web = web_search_enrich.enrich_from_web(name, lead.get("location"))
            for k, v in (web or {}).items():
                if v and not contact.get(k):
                    contact[k] = v
        email = contact.get("contact_email")
        patch = dict(contact)
        patch["enriched_at"] = datetime.now(timezone.utc).isoformat()
        d = draft.draft_email(lead, contact, settings) if (email and draft.available()) else None
        if d:
            patch.update({"draft_subject": d["subject"], "draft_body": d["body"],
                          "draft_status": "pending",
                          "drafted_at": datetime.now(timezone.utc).isoformat(),
                          "status": "Contact found"})
            done += 1
        else:
            patch["draft_status"] = "none"          # no verified email -> clear the request
        supabase_io.update_lead(lead["id"], patch)
        log.info("Requested '%s' -> %s", name, "drafted" if d else "no email, cleared")
    supabase_io.finish_run("ok", done)
    log.info("Done - %d requested draft(s) created.", done)


if __name__ == "__main__":
    run()
