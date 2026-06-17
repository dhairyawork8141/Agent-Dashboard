"""Delivers new finds two ways:
1. Always appends them to state/new_jobs.csv (your running lead log - import into the tracker).
2. Optionally emails you an HTML digest, grouped by tier (SEND_EMAIL=true).

Email auth: prefers Microsoft 365 OAuth2 (app-only / client-credentials, XOAUTH2) when
OAUTH_TENANT_ID/CLIENT_ID/CLIENT_SECRET are set - this works with Security Defaults / MFA
left ON. Falls back to basic SMTP password auth (SMTP_PASS) otherwise.

One-time Microsoft setup for the OAuth path:
  1. Entra admin -> App registrations -> New registration. Note Application (client) ID
     + Directory (tenant) ID.
  2. Certificates & secrets -> New client secret. Copy the secret VALUE.
  3. API permissions -> Add -> APIs my organization uses -> "Office 365 Exchange Online"
     -> Application permissions -> SMTP.SendAsApp -> add, then "Grant admin consent".
  4. In Exchange Online PowerShell, register the app's service principal and let it send
     as the mailbox:
       New-ServicePrincipal -AppId <client-id> -ServiceId <enterprise-app-object-id>
       Add-MailboxPermission -Identity "dhairya@cadillustrator.com" `
         -User <enterprise-app-object-id> -AccessRights FullAccess
"""
import base64
import csv
import logging
import os
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import requests
import config

log = logging.getLogger("notify")
CSV_FILE = os.getenv("NEW_JOBS_CSV", "state/new_jobs.csv")

COLUMNS = ["found_date", "tier", "score", "title", "company", "showroom_name",
           "location", "salary", "is_recruiter", "decision_maker_hint",
           "opening_line", "url", "source", "matched_on"]

_TIER_ORDER = {"HOT - Virtual Worlds": 0, "WARM - Winner/Cyncly": 1, "WATCH - generic CAD": 2}


def _sorted(jobs: list[dict]) -> list[dict]:
    return sorted(jobs, key=lambda j: (_TIER_ORDER.get(j.get("tier"), 9), -j.get("score", 0)))


def write_csv(jobs: list[dict]) -> None:
    os.makedirs(os.path.dirname(CSV_FILE), exist_ok=True)
    new_file = not os.path.exists(CSV_FILE)
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        if new_file:
            w.writeheader()
        for j in _sorted(jobs):
            row = dict(j)
            row["found_date"] = date.today().isoformat()
            w.writerow(row)


def _html(jobs: list[dict]) -> str:
    cards = []
    for j in _sorted(jobs):
        opener = ""
        if j.get("opening_line"):
            opener = (f"<div style='margin-top:6px;color:#3a3a3a;font-size:13px'>"
                      f"<em>Suggested opener:</em> {j['opening_line']}</div>")
        showroom = ""
        if j.get("showroom_name") and "unknown" not in j["showroom_name"].lower():
            showroom = f" &middot; <b>{j['showroom_name']}</b>"
        cards.append(f"""
        <div style="border-left:4px solid #A98A4E;padding:10px 14px;margin:12px 0;background:#FAF8F3">
          <div style="font-size:15px;color:#211D19"><b>{j.get('title','')}</b>
            &mdash; {j.get('company') or 'company named in advert'}{showroom}</div>
          <div style="color:#6b6b6b;font-size:12px;margin-top:3px">
            {j.get('tier','')} &middot; score {j.get('score','')} &middot;
            {j.get('location') or 'UK'} &middot; {j.get('salary') or 'salary n/a'} &middot;
            {j.get('source','')}</div>
          {opener}
          <div style="margin-top:8px"><a href="{j.get('url','')}"
            style="color:#A98A4E">View the advert &rarr;</a></div>
        </div>""")
    return f"""<div style="font-family:Arial,Helvetica,sans-serif;max-width:680px;margin:auto">
      <h2 style="color:#211D19">New Virtual Worlds leads &mdash; {len(jobs)} found</h2>
      <p style="color:#6b6b6b;font-size:13px">Sorted hottest first. HOT = the advert names
      Virtual Worlds.</p>
      {''.join(cards)}
      <p style="color:#9b9b9b;font-size:11px;margin-top:18px">CAD Illustrators job-watch agent</p>
    </div>"""


def _oauth_enabled() -> bool:
    return bool(config.OAUTH_TENANT_ID and config.OAUTH_CLIENT_ID and config.OAUTH_CLIENT_SECRET)


def _fetch_oauth_token() -> str:
    """App-only (client-credentials) token for Office 365 SMTP."""
    url = f"https://login.microsoftonline.com/{config.OAUTH_TENANT_ID}/oauth2/v2.0/token"
    resp = requests.post(url, data={
        "client_id": config.OAUTH_CLIENT_ID,
        "client_secret": config.OAUTH_CLIENT_SECRET,
        "scope": "https://outlook.office365.com/.default",
        "grant_type": "client_credentials",
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]


def _smtp_oauth_login(s: smtplib.SMTP, mailbox: str, token: str) -> None:
    """Authenticate an open SMTP session with XOAUTH2."""
    auth = base64.b64encode(
        f"user={mailbox}\x01auth=Bearer {token}\x01\x01".encode()
    ).decode()
    code, msg = s.docmd("AUTH", "XOAUTH2 " + auth)
    if code != 235:
        raise smtplib.SMTPAuthenticationError(code, msg)


def send_email(jobs: list[dict]) -> None:
    use_oauth = _oauth_enabled()
    if not (config.SMTP_USER and config.ALERT_TO and (use_oauth or config.SMTP_PASS)):
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[VW Job Watch] {len(jobs)} new lead(s)"
    msg["From"] = config.ALERT_FROM
    msg["To"] = config.ALERT_TO
    msg.attach(MIMEText(_html(jobs), "html"))
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as s:
            s.starttls()
            s.ehlo()
            if use_oauth:
                _smtp_oauth_login(s, config.SMTP_USER, _fetch_oauth_token())
            else:
                s.login(config.SMTP_USER, config.SMTP_PASS)
            s.send_message(msg)
        log.info("Digest emailed to %s (%s auth)", config.ALERT_TO,
                 "OAuth2" if use_oauth else "password")
    except Exception as e:
        log.warning("Email send failed (auth=%s): %s",
                    "OAuth2" if use_oauth else "password", e)


def notify(jobs: list[dict], do_email: bool = False) -> None:
    if not jobs:
        log.info("No new jobs this run.")
        return
    write_csv(jobs)
    if do_email:
        send_email(jobs)
