"""CAD Illustrators - VW Contact Finder (agent #2).

Each run:
  load settings  ->  pull HOT/WARM leads with no contact yet
  ->  Apollo: company -> senior decision-maker -> reveal email/phone
  ->  if Apollo fails, fall back to web search (DuckDuckGo Lite)
  ->  write the contact back onto the lead in the dashboard

Credit-safe by design: at most `max_per_run` reveals, recruiters skipped, never
re-enriches a lead that already has a contact_email.
"""
import logging
from datetime import datetime, timezone

import config
import apollo
import draft
import supabase_io
import web_search_enrich

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
    has_apollo = bool(config.APOLLO_API_KEY)
    if not has_apollo:
        log.warning("APOLLO_API_KEY is not set - will use web search fallback only.")
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

        # --- Stage 1: FREE web-scrape enrichment first (website, socials, maybe email) ---
        # Every lead gets this — it costs nothing.
        contact = web_search_enrich.enrich_from_web(name, lead.get("location")) or {}
        source_label = "Web search" if contact.get("contact_email") else None

        # --- Stage 2: Apollo ONLY for high-value leads (conserves paid credits) ---
        # Apollo runs just for tiers listed in `apollo_tiers` (default: HOT only); its
        # verified decision-maker takes priority over any generic web-scraped email.
        apollo_tiers = set(settings.get("apollo_tiers") or [])
        if has_apollo and lead.get("tier") in apollo_tiers:
            org_id, domain = apollo.find_org(name)
            person = apollo.find_person(org_id, domain, settings["titles"],
                                        settings["locations"]) if org_id else None
            if person:
                enriched = apollo.reveal(person, domain,
                                         bool(settings.get("reveal_phone"))) or person
                a_contact = {
                    "contact_name": " ".join(filter(None, [enriched.get("first_name"),
                                                           enriched.get("last_name")])) or None,
                    "contact_title": enriched.get("title"),
                    "contact_email": apollo.best_email(enriched),
                    "contact_phone": (apollo.best_phone(enriched)
                                      if settings.get("reveal_phone") else None),
                    "contact_linkedin": enriched.get("linkedin_url"),
                }
                for key, val in a_contact.items():     # Apollo wins where it has a value
                    if val:
                        contact[key] = val
                source_label = "Apollo"
            else:
                log.info("Apollo found no decision-maker for '%s'.", name)

        if not contact.get("contact_email") and not contact.get("website"):
            log.info("No contact or website found for '%s'.", name)
            continue

        # --- Finalise contact record ---
        email = contact.get("contact_email")
        contact["enriched_at"] = datetime.now(timezone.utc).isoformat()
        contact["status"] = ("Contact found" if email
                             else "Contact (no email)")

        # Draft an outreach email for review (only if we have an address to send to).
        if email and settings.get("draft_emails") and draft.available():
            d = draft.draft_email(lead, contact, settings)
            if d:
                contact.update({
                    "draft_subject": d["subject"],
                    "draft_body": d["body"],
                    "draft_status": "pending",
                    "drafted_at": datetime.now(timezone.utc).isoformat(),
                })

        if supabase_io.update_lead(lead["id"], contact):
            done += 1
            log.info("Enriched '%s' via %s -> %s, %s <%s>%s", name,
                     source_label, contact.get("contact_name"),
                     contact.get("contact_title") or "",
                     email or "no email",
                     " +draft" if contact.get("draft_status") == "pending"
                     else "")

    supabase_io.finish_run("ok", done)
    log.info("Done - %d contact(s) written to the dashboard.", done)


if __name__ == "__main__":
    run()
