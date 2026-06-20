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


def upsert_leads(agent_id: str, jobs: list) -> None:
    if not jobs:
        return
    payload = [{
        "agent_id": agent_id,
        "external_key": j.get("key"),
        "tier": j.get("tier"),
        "score": j.get("score"),
        "title": j.get("title"),
        "company": j.get("company"),
        "showroom_name": j.get("showroom_name"),
        "location": j.get("location"),
        "salary": j.get("salary"),
        "is_recruiter": j.get("is_recruiter"),
        "decision_maker_hint": j.get("decision_maker_hint"),
        "opening_line": j.get("opening_line"),
        "url": j.get("url"),
        "source": j.get("source"),
        "matched_on": j.get("matched_on"),
    } for j in jobs]
    try:
        r = requests.post(
            f"{_base()}/leads",
            headers=_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
            params={"on_conflict": "external_key"},
            json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        log.info("Upserted %d leads to the dashboard", len(payload))
    except Exception as e:
        log.warning("upsert_leads failed: %s", e)


def record_candidates(rows: list[dict]) -> None:
    """Datacenter (v8): record EVERY judged candidate — kept or rejected — so the source
    scoreboard shows which job boards actually produce HOT leads. Upserts on (source, external_key)."""
    payload = []
    for r in rows:
        if not r.get("key"):
            continue
        payload.append({
            "source": r.get("source"),
            "external_key": r.get("key"),
            "company": r.get("company"),
            "location": r.get("location"),
            "stage": r.get("_stage", "judged"),
            "decision": r.get("_decision"),
            "reject_reason": r.get("_reject_reason"),
            "tier": r.get("tier"),
            "score": r.get("score"),
            "raw": {k: v for k, v in r.items() if not k.startswith("_")},
        })
    if not payload:
        return
    try:
        resp = requests.post(f"{_base()}/lead_candidates",
                             headers=_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
                             params={"on_conflict": "source,external_key"},
                             json=payload, timeout=TIMEOUT)
        resp.raise_for_status()
        log.info("Datacenter: recorded %d candidate(s)", len(payload))
    except Exception as e:
        log.warning("record_candidates failed: %s", e)


def finish_run(agent_id: str, status: str, found_count: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    try:
        requests.patch(f"{_base()}/agents", headers=_headers(),
                       params={"id": f"eq.{agent_id}"},
                       json={"last_run_at": now, "last_run_status": status}, timeout=TIMEOUT)
        requests.post(f"{_base()}/agent_runs",
                      headers=_headers({"Prefer": "return=minimal"}),
                      json={"agent_id": agent_id, "status": status, "found_count": found_count},
                      timeout=TIMEOUT)
    except Exception as e:
        log.warning("finish_run failed: %s", e)
