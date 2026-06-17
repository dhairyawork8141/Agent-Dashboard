"""Sends the outreach emails you APPROVED in the dashboard, via Microsoft 365 OAuth2
(app-only XOAUTH2 - same Entra app/secrets as the job agent). Nothing is ever sent
without prior human approval: this only touches leads with draft_status='approved'.

Run it after approving drafts:  python send_approved.py
On success a lead becomes draft_status='sent' (+ sent_at); on failure 'failed'."""
import base64
import logging
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
import requests
import config
import supabase_io

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(name)-9s %(levelname)s  %(message)s")
log = logging.getLogger("sender")


def _oauth_ready() -> bool:
    return bool(config.OAUTH_TENANT_ID and config.OAUTH_CLIENT_ID
                and config.OAUTH_CLIENT_SECRET and config.SMTP_USER)


def _fetch_token() -> str:
    url = f"https://login.microsoftonline.com/{config.OAUTH_TENANT_ID}/oauth2/v2.0/token"
    r = requests.post(url, timeout=30, data={
        "client_id": config.OAUTH_CLIENT_ID,
        "client_secret": config.OAUTH_CLIENT_SECRET,
        "scope": "https://outlook.office365.com/.default",
        "grant_type": "client_credentials",
    })
    r.raise_for_status()
    return r.json()["access_token"]


def _connect(token: str) -> smtplib.SMTP:
    s = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT)
    s.starttls()
    s.ehlo()
    auth = base64.b64encode(
        f"user={config.SMTP_USER}\x01auth=Bearer {token}\x01\x01".encode()).decode()
    code, msg = s.docmd("AUTH", "XOAUTH2 " + auth)
    if code != 235:
        raise smtplib.SMTPAuthenticationError(code, msg)
    return s


def run() -> None:
    if not supabase_io.configured():
        log.error("Supabase not configured - nothing to do.")
        return
    if not _oauth_ready():
        log.error("M365 OAuth/SMTP not configured - cannot send. Set OAUTH_* and SMTP_USER.")
        return

    queue = supabase_io.leads_to_send()
    log.info("%d approved draft(s) to send.", len(queue))
    if not queue:
        return

    try:
        token = _fetch_token()
        s = _connect(token)
    except Exception as e:
        log.error("Could not authenticate to Microsoft 365 SMTP: %s", e)
        return

    sent = 0
    try:
        for lead in queue:
            to = lead.get("contact_email")
            subject = lead.get("draft_subject") or "Hello"
            body = lead.get("draft_body") or ""
            try:
                msg = MIMEText(body, "plain", "utf-8")
                msg["Subject"] = subject
                msg["From"] = config.ALERT_FROM
                msg["To"] = to
                s.send_message(msg)
                supabase_io.update_lead(lead["id"], {
                    "draft_status": "sent",
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                    "status": "Contacted",
                })
                sent += 1
                log.info("Sent to %s (%s)", to, lead.get("contact_name") or "")
            except Exception as e:
                log.warning("Send failed for %s: %s", to, e)
                supabase_io.update_lead(lead["id"], {"draft_status": "failed"})
    finally:
        try:
            s.quit()
        except Exception:
            pass
    log.info("Done - %d email(s) sent.", sent)


if __name__ == "__main__":
    run()
