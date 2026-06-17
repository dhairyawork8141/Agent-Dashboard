"""CAD Illustrators - VW Contact Finder (agent #2).

Each run:
  load settings  ->  pull HOT/WARM leads with no contact yet
  ->  Apollo: company -> senior decision-maker -> reveal email/phone
  ->  write the contact back onto the lead in the dashboard

Credit-safe by design: at most `max_per_run` reveals, recruiters skipped, never
re-enriches a lead that already has a contact_email.
"""
import logging
from datetime import datetime, timezone

import config
import apollo
import supabase_io

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(name)-9s %(levelname)s  %(message)s")
log = logging.getLogger("main")


_LEGAL_SUFFIXES = (" limited", " ltd", " ltd.", " llp", " plc", " (uk)", " uk ltd")


def _clean_company(name: str) -> str:
    """Apollo matches plain trading names better than legal names — drop the suffix."""
    out = name.strip()
    low = out.lower()
    for suf in _LEGAL_SUFFIXES:
        if low.endswith(suf):
            out = out[: len(out) - len(suf)].strip()
            break
    return out


def _company_name(lead: dict) -> str | None:
    """Prefer the resolved showroom name; fall back to the raw company field."""
    name = (lead.get("showroom_name") or "").strip()
    if not name or "unknown" in name.lower():
        name = (lead.get("company") or "").strip()
    return _clean_company(name) if name else None


def run() -> None:
    if not config.APOLLO_API_KEY:
        log.error("APOLLO_API_KEY is not set - nothing to do.")
        return
    if not supabase_io.configured():
        log.error("Supabase is not configured - nothing to do.")
        return

    settings = supabase_io.load_settings()
    if settings is None:                       # paused in the dashboard
        return

    tiers = set(settings.get("tiers") or [])
    cap = int(settings.get("max_per_run", 10))
    skip_recruiters = bool(settings.get("skip_recruiters", True))

    candidates = supabase_io.leads_needing_contact(cap)
    # Filter in Python: only target tiers, drop recruiters, then cap.
    queue = []
    for lead in candidates:
        if tiers and lead.get("tier") not in tiers:
            continue
        if skip_recruiters and lead.get("is_recruiter"):
            continue
        queue.append(lead)
        if len(queue) >= cap:
            break

    log.info("%d lead(s) to enrich this run (cap %d)", len(queue), cap)

    done = 0
    for lead in queue:
        name = _company_name(lead)
        if not name:
            log.info("Lead %s has no company name - skipping.", lead.get("id"))
            continue

        org_id, domain = apollo.find_org(name)
        if not org_id:
            log.info("No Apollo company match for '%s'.", name)
            continue

        person = apollo.find_person(org_id, domain, settings["titles"], settings["locations"])
        if not person:
            log.info("No decision-maker found at '%s'.", name)
            continue

        enriched = apollo.reveal(person, domain, bool(settings.get("reveal_phone"))) or person
        email = apollo.best_email(enriched)
        contact = {
            "contact_name": " ".join(filter(None, [enriched.get("first_name"),
                                                    enriched.get("last_name")])) or None,
            "contact_title": enriched.get("title"),
            "contact_email": email,
            "contact_phone": apollo.best_phone(enriched) if settings.get("reveal_phone") else None,
            "contact_linkedin": enriched.get("linkedin_url"),
            "enriched_at": datetime.now(timezone.utc).isoformat(),
            "status": "Contact found" if email else "Contact (no email)",
        }
        if supabase_io.update_lead(lead["id"], contact):
            done += 1
            log.info("Enriched '%s' -> %s, %s <%s>", name, contact["contact_name"],
                     contact["contact_title"] or "", email or "no email")

    supabase_io.finish_run("ok", done)
    log.info("Done - %d contact(s) written to the dashboard.", done)


if __name__ == "__main__":
    run()
