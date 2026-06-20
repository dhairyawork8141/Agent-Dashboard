"""Reads/writes the dashboard's Supabase database over its REST API. Uses the service-role
key, so this must only ever run server-side (GitHub Actions / your VPS) - never in the
browser dashboard."""
import logging
from datetime import datetime, timezone
import requests
import config

log = logging.getLogger("supabase")
TIMEOUT = 20


def configured() -> bool:
    return bool(config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY and config.AGENT_ID)


def _base() -> str:
    return config.SUPABASE_URL.rstrip("/") + "/rest/v1"


def _headers(extra: dict | None = None) -> dict:
    h = {
        "apikey": config.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def load_settings():
    """Returns the agent's settings (merged over defaults), or None if paused/missing."""
    try:
        r = requests.get(f"{_base()}/agents", headers=_headers(),
                         params={"id": f"eq.{config.AGENT_ID}", "select": "*"}, timeout=TIMEOUT)
        r.raise_for_status()
        rows = r.json()
        if not rows:
            log.warning("Agent row not found - using local defaults.")
            return dict(config.DEFAULT_SETTINGS)
        row = rows[0]
        if not row.get("enabled", True):
            log.info("Agent is paused in the dashboard - skipping this run.")
            return None
        merged = {**config.DEFAULT_SETTINGS, **(row.get("settings") or {})}
        log.info("Loaded settings from the dashboard (agent %s).", config.AGENT_ID)
        return merged
    except Exception as e:
        log.warning("load_settings failed (%s) - using local defaults.", e)
        return dict(config.DEFAULT_SETTINGS)


def leads_needing_contact(limit: int) -> list[dict]:
    """Highest-scoring leads not yet enriched (no contact email AND never attempted).
    Selects '*' so drafting has category/location/registered_at for the right template;
    `enriched_at is null` stops us re-trying (and re-spending Apollo on) the same lead
    every run when no email can be found. Tier/recruiter filtering is done in Python."""
    try:
        r = requests.get(f"{_base()}/leads", headers=_headers(), params={
            "select": "*",
            "contact_email": "is.null",
            "enriched_at": "is.null",
            "order": "score.desc.nullslast",
            "limit": str(max(limit * 4, limit)),
        }, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning("leads_needing_contact failed: %s", e)
        return []


def leads_requested_draft(limit: int = 25) -> list[dict]:
    """Leads you flagged in the dashboard with the 'Draft email' button (any tier).
    They get enriched if needed and drafted, regardless of the normal tier gate."""
    try:
        r = requests.get(f"{_base()}/leads", headers=_headers(), params={
            "select": "*", "draft_status": "eq.requested",
            "order": "score.desc.nullslast", "limit": str(limit),
        }, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning("leads_requested_draft failed: %s", e)
        return []


def sent_today_count() -> int:
    """How many emails have already been sent today (UTC) - for the daily cap."""
    start = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
    try:
        r = requests.get(f"{_base()}/leads", headers=_headers({"Prefer": "count=exact"}),
                         params={"select": "id", "sent_at": f"gte.{start}", "limit": "1"},
                         timeout=TIMEOUT)
        r.raise_for_status()
        return int((r.headers.get("content-range") or "*/0").split("/")[-1])
    except Exception as e:
        log.warning("sent_today_count failed: %s", e)
        return 0


def leads_to_send(limit: int = 25) -> list[dict]:
    """Leads you've approved in the dashboard that haven't been sent yet."""
    try:
        r = requests.get(f"{_base()}/leads", headers=_headers(), params={
            "select": "id,contact_name,contact_email,draft_subject,draft_body,draft_status",
            "draft_status": "eq.approved",
            "contact_email": "not.is.null",
            "limit": str(limit),
        }, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning("leads_to_send failed: %s", e)
        return []


def update_lead(lead_id: str, fields: dict) -> bool:
    try:
        r = requests.patch(f"{_base()}/leads",
                           headers=_headers({"Prefer": "return=minimal"}),
                           params={"id": f"eq.{lead_id}"}, json=fields, timeout=TIMEOUT)
        r.raise_for_status()
        return True
    except Exception as e:
        log.warning("update_lead %s failed: %s", lead_id, e)
        return False


def record_candidate_outcome(lead: dict, contact: dict | None,
                             stage: str = "enriched", outcome: str | None = None) -> None:
    """Datacenter (v8): record this lead's enrichment/outreach OUTCOME so the source
    scoreboard shows real conversion. Upserts on (source, external_key) — a partial patch
    that only touches outcome columns, preserving the finder's category/score/raw."""
    key, src = lead.get("external_key"), lead.get("source")
    if not key or not src:
        return
    row = {"source": src, "external_key": key, "stage": stage,
           "contact_found": bool((contact or {}).get("contact_email")),
           "lead_id": lead.get("id")}
    if outcome:
        row["outcome"] = outcome
    try:
        r = requests.post(f"{_base()}/lead_candidates",
                          headers=_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
                          params={"on_conflict": "source,external_key"},
                          json=row, timeout=TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        log.warning("record_candidate_outcome failed: %s", e)


def finish_run(status: str, count: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    try:
        requests.patch(f"{_base()}/agents", headers=_headers(),
                       params={"id": f"eq.{config.AGENT_ID}"},
                       json={"last_run_at": now, "last_run_status": status}, timeout=TIMEOUT)
        requests.post(f"{_base()}/agent_runs",
                      headers=_headers({"Prefer": "return=minimal"}),
                      json={"agent_id": config.AGENT_ID, "status": status,
                            "found_count": count}, timeout=TIMEOUT)
    except Exception as e:
        log.warning("finish_run failed: %s", e)
