"""Closes the outreach loop (Project Hermes):
  1) Reads the M365 inbox via Microsoft Graph (app-only, same Entra app as the sender) and
     marks leads that REPLIED — stops chasing them; a reply saying "unsubscribe"/"stop"
     opts them out (sets unsubscribed so the sender suppresses them).
  2) For sent leads with no reply after `followup_days`, drafts a polite follow-up for your
     approval (up to `max_followups`), so cold leads get a second/third touch automatically.

SETUP: the Entra app needs the Microsoft Graph **Mail.Read** APPLICATION permission + admin
consent (it already has SMTP send). Without it, reply-reading 403s (fail-soft -> just skips).
Requires v9 columns (replied_at, unsubscribed, follow_up_count, last_followup_at)."""
import logging
from datetime import datetime, timezone, timedelta

import requests
import config
import draft
import supabase_io

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(name)-9s %(levelname)s  %(message)s")
log = logging.getLogger("replies")
GRAPH = "https://graph.microsoft.com/v1.0"
_STOP = ("unsubscribe", "unsubscrib", "opt out", "opt-out", "stop emailing", "remove me", "do not contact")


def _oauth_ready() -> bool:
    return bool(config.OAUTH_TENANT_ID and config.OAUTH_CLIENT_ID
               and config.OAUTH_CLIENT_SECRET and config.SMTP_USER)


def _graph_token() -> str | None:
    try:
        url = f"https://login.microsoftonline.com/{config.OAUTH_TENANT_ID}/oauth2/v2.0/token"
        r = requests.post(url, timeout=30, data={
            "client_id": config.OAUTH_CLIENT_ID, "client_secret": config.OAUTH_CLIENT_SECRET,
            "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials"})
        r.raise_for_status()
        return r.json()["access_token"]
    except Exception as e:
        log.error("Graph token failed: %s", e)
        return None


def _parse(iso: str):
    try:
        return datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    except Exception:
        return None


def _inbox_since(token: str, since_iso: str) -> list[dict]:
    """Recent inbox messages since a timestamp: [{from, received, preview}]."""
    out = []
    url = (f"{GRAPH}/users/{config.SMTP_USER}/mailFolders/inbox/messages"
           f"?$select=from,receivedDateTime,bodyPreview&$top=500"
           f"&$filter=receivedDateTime ge {since_iso}&$orderby=receivedDateTime desc")
    try:
        while url:
            r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
            if r.status_code == 403:
                log.error("Graph Mail.Read denied (403) - add the Mail.Read app permission + admin consent.")
                return []
            r.raise_for_status()
            data = r.json()
            for m in data.get("value", []):
                addr = ((m.get("from") or {}).get("emailAddress") or {}).get("address", "").lower()
                out.append({"from": addr, "received": _parse(m.get("receivedDateTime")),
                            "preview": (m.get("bodyPreview") or "").lower()})
            url = data.get("@odata.nextLink")
    except Exception as e:
        log.warning("Inbox read failed: %s", e)
    return out


def run() -> None:
    if not supabase_io.configured():
        log.error("Supabase not configured - nothing to do.")
        return
    settings = supabase_io.load_settings() or dict(config.DEFAULT_SETTINGS)

    # --- 1) Reply detection ---
    replied = unsubbed = 0
    if _oauth_ready():
        token = _graph_token()
        if token:
            since = (datetime.now(timezone.utc) - timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
            msgs = _inbox_since(token, since)
            log.info("Read %d recent inbox message(s).", len(msgs))
            awaiting = supabase_io.leads_awaiting_reply()
            for lead in awaiting:
                addr = (lead.get("contact_email") or "").lower()
                sent = _parse(lead.get("sent_at"))
                if not addr or not sent:
                    continue
                hits = [m for m in msgs if m["from"] == addr and m["received"] and m["received"] > sent]
                if hits:
                    optout = any(any(w in m["preview"] for w in _STOP) for m in hits)
                    supabase_io.mark_replied(lead["id"], unsubscribed=optout)
                    replied += 1
                    unsubbed += 1 if optout else 0
            log.info("Replies detected: %d (of which opted out: %d).", replied, unsubbed)
    else:
        log.warning("M365 OAuth not set - skipping reply detection.")

    # --- 2) Auto follow-ups for no-reply leads ---
    drafted = 0
    if settings.get("followups_enabled", True) and draft.available():
        days = int(settings.get("followup_days", 4))
        cap = int(settings.get("max_followups", 2))
        for lead in supabase_io.leads_needing_followup(days, cap):
            d = draft.follow_up(lead, settings)
            if not d:
                continue
            supabase_io.update_lead(lead["id"], {
                "draft_subject": d["subject"], "draft_body": d["body"],
                "draft_status": "pending", "drafted_at": datetime.now(timezone.utc).isoformat(),
                "follow_up_count": int(lead.get("follow_up_count") or 0) + 1,
                "last_followup_at": datetime.now(timezone.utc).isoformat(),
                "status": "Follow-up drafted"})
            drafted += 1
        log.info("Follow-ups drafted for approval: %d.", drafted)

    supabase_io.finish_run("ok", replied + drafted)
    log.info("Done - %d reply(ies), %d follow-up(s).", replied, drafted)


if __name__ == "__main__":
    run()
