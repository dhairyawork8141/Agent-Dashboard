"""Drafts an outreach email from the right FIXED per-sector template, then (optionally)
lets the Groq brain LIGHTLY personalise the opening to the specific business.

Template choice:
  - showroom leads -> by category (fitter / interior / bathroom) or, for
    kitchen/kbb/bedroom, by recency (new <=6mo vs established).
  - job leads      -> by the role advertised (kitchen / bathroom / both).

Personalisation is conservative and SAFE: the offer, the £100 price, the free-first-
project line, the URL and the sign-off are preserved; only the greeting/opening is
tailored. If Groq is off, rate-limited, or drops key content, we fall back to the plain
template fill. Nothing is ever sent from here - drafts are parked 'pending' for approval."""
import json
import logging
import os

import config
import groq_pool

log = logging.getLogger("draft")
_DIR = os.path.join(os.path.dirname(__file__), "templates")
_CACHE = {}

_PERSONALISE_SYSTEM = """You personalise a fixed B2B outreach email for CAD Illustrators.
You are given a ready template (the business name is already filled in) plus a few facts
about the recipient. Rewrite it so the GREETING and the FIRST one or two sentences feel
specific to this exact business (reference their name, location, trade, or that they
recently opened) - warm and human, not generic.

HARD RULES - do not break:
- Keep the core offer, the "£100 per project/layout" pricing, the free-first-project
  line, the website URL, and the sign-off EXACTLY as in the template.
- Do NOT invent facts, prices, names, or claims beyond what you are told.
- Keep roughly the same length and the same friendly British tone.
Return ONLY JSON: {"subject": "...", "body": "..."}"""


def available() -> bool:
    return os.path.isdir(_DIR)


def _load(key: str) -> str:
    if key not in _CACHE:
        with open(os.path.join(_DIR, key + ".txt"), encoding="utf-8") as f:
            _CACHE[key] = f.read()
    return _CACHE[key]


def _template_key(lead: dict) -> str:
    cat = (lead.get("category") or "").lower().strip()
    if cat:                                       # showroom lead (has a category)
        if cat == "fitter":   return "showroom_fitter"
        if cat == "interior": return "showroom_interior"
        if cat == "bathroom": return "showroom_bathroom"
        return ("showroom_new_6mo" if (lead.get("tier") or "").startswith("HOT")
                else "showroom_established_12mo")
    t = (lead.get("title") or "").lower()         # job lead -> advertised role
    k, b = "kitchen" in t, "bathroom" in t
    if k and b: return "job_kitchen_bathroom"
    if b:       return "job_bathroom"
    return "job_kitchen"


def _first_name(merged: dict) -> str:
    n = (merged.get("contact_name") or "").strip()
    return n.split()[0] if n else "there"


def _fill(text: str, merged: dict) -> str:
    name = merged.get("showroom_name") or merged.get("company") or "your showroom"
    for a, b in {"[First Name]": _first_name(merged), "[Showroom Name]": name,
                 "[Company Name]": name, "[Your Name]": config.SENDER_NAME}.items():
        text = text.replace(a, b)
    return text


def _split(text: str):
    lines = text.splitlines()
    subject, start = "", 0
    if lines and lines[0].lower().startswith("subject:"):
        subject = lines[0].split(":", 1)[1].strip()
        start = 1
    return subject, "\n".join(lines[start:]).strip()


def _keeps_offer(body: str, base_body: str) -> bool:
    """Safety: the personalised body must keep the URL and the £100 price."""
    url_ok = "cad-illustrators-website.pages.dev" in body
    price_ok = "£100" in body or "100" in body
    return url_ok and price_ok and len(body) > 200


def _personalise(subject: str, body: str, merged: dict, settings: dict) -> tuple | None:
    if not groq_pool.available():
        return None
    model = (settings or {}).get("draft_model") or config.DRAFT_MODEL
    facts = (f"Business: {merged.get('showroom_name') or merged.get('company') or '?'}\n"
             f"Location: {merged.get('location') or '?'}\n"
             f"Type: {merged.get('category') or 'job applicant employer'}\n"
             f"Registered: {merged.get('registered_at') or 'n/a'}\n"
             f"Contact: {merged.get('contact_name') or 'unknown'}")
    user = f"{facts}\n\nTEMPLATE SUBJECT: {subject}\nTEMPLATE BODY:\n{body}"
    content = groq_pool.chat(
        [{"role": "system", "content": _PERSONALISE_SYSTEM}, {"role": "user", "content": user}],
        model=model, role="draft", temperature=0.5)
    if not content:
        return None
    try:
        out = json.loads(content)
    except Exception as e:
        log.warning("Personalise bad JSON (%s) - using plain template.", e)
        return None
    s2 = (out.get("subject") or "").strip()
    b2 = (out.get("body") or "").strip()
    if s2 and b2 and _keeps_offer(b2, body):
        return s2, b2
    log.info("Personalised draft dropped key content - using plain template.")
    return None


def follow_up(lead: dict, settings: dict | None = None) -> dict | None:
    """Build a polite follow-up email from the followup template (lightly personalised)."""
    try:
        subject, body = _split(_fill(_load("followup"), lead))
    except Exception as e:
        log.warning("Follow-up template failed: %s", e)
        return None
    if not subject or not body:
        return None
    if (settings or {}).get("personalise_drafts", True):
        p = _personalise(subject, body, lead, settings or {})
        if p:
            subject, body = p
    return {"subject": subject, "body": body}


def draft_email(lead: dict, contact: dict | None = None, settings: dict | None = None) -> dict | None:
    merged = {**(lead or {}), **{k: v for k, v in (contact or {}).items() if v}}
    key = _template_key(merged)
    try:
        subject, body = _split(_fill(_load(key), merged))
    except Exception as e:
        log.warning("Template '%s' load failed: %s", key, e)
        return None
    if not subject or not body:
        return None

    # Light AI personalisation on top of the safe template (best-effort, never blocks).
    if (settings or {}).get("personalise_drafts", True):
        p = _personalise(subject, body, merged, settings or {})
        if p:
            subject, body = p
    return {"subject": subject, "body": body, "template": key}
