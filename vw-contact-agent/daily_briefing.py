"""Daily briefing (Project Hermes): emails you a short morning summary of the pipeline —
new HOT today, leads awaiting your approval, replies, sends, and the best source — so you
know where to spend your time without opening the dashboard. Uses the same M365 OAuth SMTP
as the sender. Fail-soft: if email isn't configured it just logs the summary."""
import logging
from datetime import datetime, timezone
from email.mime.text import MIMEText

import requests
import config
import supabase_io
from send_approved import _fetch_token, _connect, _oauth_ready

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(name)-9s %(levelname)s  %(message)s")
log = logging.getLogger("briefing")


def _count(table: str, params: dict) -> int:
    try:
        r = requests.get(f"{supabase_io._base()}/{table}",
                         headers=supabase_io._headers({"Prefer": "count=exact"}),
                         params={**params, "select": "id", "limit": "1"}, timeout=20)
        return int((r.headers.get("content-range") or "*/0").split("/")[-1])
    except Exception:
        return 0


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")


def build_summary() -> str:
    base, h = supabase_io._base(), supabase_io._headers()
    # KPIs
    try:
        hot_today = requests.get(f"{base}/hot_today", headers=h, params={"select": "*"}, timeout=20).json()
        hot_today = (hot_today or [{}])[0].get("hot_today", 0)
    except Exception:
        hot_today = 0
    pending = _count("leads", {"draft_status": "eq.pending"})
    approved = _count("leads", {"draft_status": "eq.approved"})
    sent_today = supabase_io.sent_today_count()
    replies_today = _count("leads", {"replied_at": f"gte.{_today()}"})
    hot_open = _count("leads", {"tier": "like.HOT*", "draft_status": "not.eq.sent"})
    # best source
    try:
        perf = requests.get(f"{base}/source_performance", headers=h, params={"select": "*"}, timeout=20).json()
        perf = sorted(perf or [], key=lambda x: -(x.get("hot") or 0))
        top = perf[0] if perf else None
    except Exception:
        top = None
    goal = 10
    lines = [
        f"Good morning — here's your CAD Illustrators pipeline:",
        "",
        f"  HOT today:           {hot_today} / {goal} goal",
        f"  Open HOT leads:      {hot_open}",
        f"  Awaiting approval:   {pending}   (approve them in the dashboard)",
        f"  Approved, queued:    {approved}",
        f"  Sent today:          {sent_today}",
        f"  Replies today:       {replies_today}",
    ]
    if top:
        lines.append(f"  Best source:         {top.get('source')} ({top.get('hot')} HOT, {top.get('hot_rate_pct')}%)")
    lines += ["", "Dashboard: https://agent-dashboard-55d.pages.dev", "", "— Hermes"]
    return "\n".join(lines)


def run() -> None:
    if not supabase_io.configured():
        log.error("Supabase not configured - nothing to do.")
        return
    summary = build_summary()
    log.info("Briefing:\n%s", summary)
    to = config.ALERT_TO or config.SMTP_USER
    if not (_oauth_ready() and to):
        log.warning("Email not configured - briefing logged only.")
        return
    try:
        s = _connect(_fetch_token())
        msg = MIMEText(summary, "plain", "utf-8")
        msg["Subject"] = f"Hermes briefing — {datetime.now().strftime('%a %d %b')}"
        msg["From"] = config.ALERT_FROM
        msg["To"] = to
        s.send_message(msg)
        s.quit()
        log.info("Briefing emailed to %s", to)
    except Exception as e:
        log.warning("Briefing email failed: %s", e)


if __name__ == "__main__":
    run()
