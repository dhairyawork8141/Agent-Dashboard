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
    """Highest-scoring leads that don't yet have a contact email. Filtering by tier /
    recruiter is done in Python so odd characters in tier names can't break the query."""
    try:
        r = requests.get(f"{_base()}/leads", headers=_headers(), params={
            "select": "id,company,showroom_name,tier,score,url,is_recruiter,contact_email",
            "contact_email": "is.null",
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
