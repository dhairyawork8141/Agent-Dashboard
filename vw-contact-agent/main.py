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
import hermes
import supabase_io
import web_search_enrich

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(name)-9s %(levelname)s  %(message)s")
log = logging.getLogger("main")


_LEGAL_SUFFIXES = (" limited", " ltd", " ltd.", " llp", " plc", " (uk)", " uk ltd")


def _pfx(tier: str) -> str:
    """The HOT/WARM/WATCH prefix of a tier label, e.g. 'HOT - New showroom' -> 'HOT'.
    Gates compare by prefix so a HOT lead from ANY source (Companies House, OSM, ...)
    is treated the same — the source-specific suffix no longer matters."""
    return (tier or "").split(" ")[0].strip().upper()


def _tier_match(tier: str, configured: set) -> bool:
    """True if the lead's tier prefix matches any configured tier (also by prefix)."""
    return _pfx(tier) in {_pfx(t) for t in configured}


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

    # Hermes plans this run from shared memory (datacenter): tunes how many leads to work
    # toward the daily HOT goal.
    settings, plan_note = hermes.plan("contact", settings)
    log.info("Hermes: %s", plan_note)

    tiers = set(settings.get("tiers") or [])
    cap = int(settings.get("max_per_run", 10))
    skip_recruiters = bool(settings.get("skip_recruiters", True))

    candidates = supabase_io.leads_needing_contact(cap)
    # Filter in Python: only target tiers, drop recruiters, then cap.
    queue = []
    for lead in candidates:
        if tiers and not _tier_match(lead.get("tier"), tiers):
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
        contact = web_search_enrich.enrich_from_web(name, lead.get("location"), settings) or {}
        source_label = "Web search" if contact.get("contact_email") else None

        # --- Stage 2: Apollo ONLY for high-value leads (conserves paid credits) ---
        # Apollo runs just for tiers listed in `apollo_tiers` (default: HOT only); its
        # verified decision-maker takes priority over any generic web-scraped email.
        apollo_tiers = set(settings.get("apollo_tiers") or [])
        if has_apollo and _tier_match(lead.get("tier"), apollo_tiers):
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

        # Software-usage skill: a showroom running KBB design software is a strong buyer -> HOT.
        if contact.get("tech_software") and _pfx(lead.get("tier")) != "HOT":
            base = (lead.get("tier") or "lead").split(" - ", 1)
            contact["tier"] = "HOT - " + (base[1] if len(base) > 1 else "lead")
            log.info("'%s' uses %s -> boosting to HOT", name, contact.get("tech_software"))

        # --- Finalise contact record ---
        email = contact.get("contact_email")
        contact["enriched_at"] = datetime.now(timezone.utc).isoformat()
        contact["status"] = ("Contact found" if email
                             else "Contact (no email)")

        # Draft an outreach email for review — only for high-value tiers (draft_tiers,
        # default HOT) and only if we have an address to send to.
        draft_tiers = set(settings.get("draft_tiers") or [])
        if (email and settings.get("draft_emails") and draft.available()
                and (not draft_tiers or _tier_match(lead.get("tier"), draft_tiers))):
            d = draft.draft_email(lead, contact, settings)
            if d:
                contact.update({
                    "draft_subject": d["subject"],
                    "draft_body": d["body"],
                    "draft_status": "pending",
                    "drafted_at": datetime.now(timezone.utc).isoformat(),
                    "template": d.get("template"),
                })

        if supabase_io.update_lead(lead["id"], contact):
            done += 1
            drafted = contact.get("draft_status") == "pending"
            supabase_io.record_candidate_outcome(
                lead, contact, stage="drafted" if drafted else "enriched",
                outcome="pending" if drafted else None)
            log.info("Enriched '%s' via %s -> %s, %s <%s>%s", name,
                     source_label, contact.get("contact_name"),
                     contact.get("contact_title") or "",
                     email or "no email",
                     " +draft" if drafted else "")

    # Manually-requested drafts (dashboard "Draft email" button) — enrich if needed,
    # then draft regardless of tier. Clears the request if no email can be found.
    requested = supabase_io.leads_requested_draft()
    if requested:
        log.info("%d manually-requested draft(s) to handle.", len(requested))
    for lead in requested:
        name = _company_name(lead)
        contact = {k: lead.get(k) for k in ("contact_name", "contact_title",
                   "contact_email", "contact_phone", "contact_linkedin") if lead.get(k)}
        if not contact.get("contact_email") and name:
            web = web_search_enrich.enrich_from_web(name, lead.get("location"), settings)
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
                          "template": d.get("template"), "status": "Contact found"})
        else:
            patch["draft_status"] = "none"     # couldn't draft (no email) - clear the request
        supabase_io.update_lead(lead["id"], patch)
        supabase_io.record_candidate_outcome(
            lead, contact, stage="drafted" if d else "enriched",
            outcome="pending" if d else None)
        log.info("Requested draft for '%s' -> %s", name,
                 "drafted" if d else "no email, cleared")

    # Auto-draft: queue a draft for EVERY HOT lead that has an email but no draft yet, so
    # hot leads get an outreach email immediately (the draft-requested worker drafts them).
    if settings.get("draft_emails", True):
        hot_undrafted = supabase_io.leads_hot_needing_draft()
        for lead in hot_undrafted:
            supabase_io.update_lead(lead["id"], {"draft_status": "requested"})
        if hot_undrafted:
            log.info("Auto-queued %d hot lead(s) for immediate drafting.", len(hot_undrafted))

    supabase_io.finish_run("ok", done)
    log.info("Done - %d contact(s) written to the dashboard.", done)


if __name__ == "__main__":
    run()
