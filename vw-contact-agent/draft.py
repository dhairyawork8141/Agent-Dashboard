"""Drafts a personalised cold-outreach email for an enriched lead, using the free Groq
brain. Returns {subject, body} or None on any error (fail-soft: no draft, no crash).

The email is NEVER sent from here - it's parked as 'pending' for human approval in the
dashboard. The sender mails it only after you approve."""
import json
import logging
import requests
import config

log = logging.getLogger("draft")
TIMEOUT = 30
_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

_SYSTEM = """You write short, warm, non-salesy B2B cold emails for {studio}, an outsourced
CAD/CGI studio that produces kitchen, bedroom & bathroom (KBB) and interior-design visuals
for showrooms and design retailers.

Context: the recipient's business just advertised a DESIGNER vacancy. The angle is that
{studio} can take CAD/CGI design work off their plate (faster renders, no extra hire,
overflow capacity) - a helpful alternative or supplement to hiring.

Rules:
- Address the named contact by first name if given.
- Reference their specific business and the role they advertised - make it clearly personal.
- 90-130 words. Plain, friendly, British English. No jargon, no hype, no "I hope this finds you well".
- One soft call to action (a quick reply or a 15-min call). Sign off as {sender}, {studio}.
- Do NOT invent facts, prices, or fake mutual connections.

Reply with ONLY a JSON object, no prose:
{{"subject": "<short, specific subject line>", "body": "<the full email body with line breaks>"}}"""


def available() -> bool:
    return bool(config.GROQ_API_KEY)


def _user_prompt(lead: dict, contact: dict) -> str:
    return (
        f"Recipient first name: {(contact.get('contact_name') or '').split(' ')[0] or 'there'}\n"
        f"Recipient title: {contact.get('contact_title') or 'decision-maker'}\n"
        f"Business: {lead.get('showroom_name') or lead.get('company') or 'their showroom'}\n"
        f"Location: {lead.get('location') or 'the UK'}\n"
        f"Role they advertised: {lead.get('title') or 'a designer'}\n"
        f"Tier/why this is a fit: {lead.get('tier') or ''}\n"
        f"(If an opener was suggested, you may build on it: {lead.get('opening_line') or 'n/a'})"
    )


def draft_email(lead: dict, contact: dict, settings: dict | None = None) -> dict | None:
    if not available():
        return None
    model = (settings or {}).get("brain_model") or config.GROQ_MODEL
    system = _SYSTEM.format(studio=config.STUDIO_NAME, sender=config.SENDER_NAME)
    try:
        r = requests.post(_ENDPOINT, timeout=TIMEOUT,
            headers={"Authorization": f"Bearer {config.GROQ_API_KEY}",
                     "Content-Type": "application/json"},
            json={
                "model": model,
                "temperature": 0.6,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": _user_prompt(lead, contact)},
                ],
            })
        r.raise_for_status()
        out = json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception as e:
        log.warning("Draft failed for lead %s (%s)", lead.get("id"), e)
        return None

    subject = (out.get("subject") or "").strip()
    body = (out.get("body") or "").strip()
    if not subject or not body:
        return None
    return {"subject": subject, "body": body}
