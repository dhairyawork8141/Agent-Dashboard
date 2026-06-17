"""Reads/writes the dashboard's Supabase database over its REST API, with the service-role
key (server-side only). Mirrors the job agent's supabase_io so showroom finds appear as
ordinary leads and flow into the contact-finder + drafting pipeline."""
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


def get_agent(agent_id: str):
    try:
        r = requests.get(f"{_base()}/agents", headers=_headers(),
                         params={"id": f"eq.{agent_id}", "select": "*"}, timeout=TIMEOUT)
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else None
    except Exception as e:
        log.warning("get_agent failed: %s", e)
        return None


def load_settings():
    """Merged settings, or None if the agent is paused in the dashboard."""
    row = get_agent(config.AGENT_ID)
    if row is None:
        log.warning("Agent row not found - using local defaults.")
        return dict(config.DEFAULT_SETTINGS)
    if not row.get("enabled", True):
        log.info("Agent is paused in the dashboard - skipping this run.")
        return None
    return {**config.DEFAULT_SETTINGS, **(row.get("settings") or {})}


def upsert_leads(agent_id: str, leads: list[dict]) -> None:
    if not leads:
        return
    payload = [{
        "agent_id": agent_id,
        "external_key": l.get("key"),
        "tier": l.get("tier"),
        "score": l.get("score"),
        "title": l.get("title"),
        "company": l.get("company"),
        "showroom_name": l.get("showroom_name"),
        "location": l.get("location"),
        "url": l.get("url"),
        "source": l.get("source"),
        "matched_on": l.get("matched_on"),
        "is_recruiter": False,
        "opening_line": l.get("reason"),
    } for l in leads]
    try:
        r = requests.post(f"{_base()}/leads",
                          headers=_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
                          params={"on_conflict": "external_key"},
                          json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        log.info("Upserted %d showroom leads to the dashboard", len(payload))
    except Exception as e:
        log.warning("upsert_leads failed: %s", e)


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
