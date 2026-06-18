"""Drafts an outreach email by filling the right FIXED template for the lead's type:
  - showroom leads -> by category (fitter / interior / bathroom) or, for
    kitchen/kbb/bedroom, by recency (new <=6mo vs established).
  - job leads      -> by the role advertised (kitchen / bathroom / both).
Templates live in templates/*.txt. No AI/Groq - on-brand, free, deterministic.
The email is parked as 'pending' for human approval; it is never sent from here."""
import logging
import os
import config

log = logging.getLogger("draft")
_DIR = os.path.join(os.path.dirname(__file__), "templates")
_CACHE = {}


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
        # kitchen / kbb / bedroom / other -> by recency tier
        return ("showroom_new_6mo" if (lead.get("tier") or "").startswith("HOT")
                else "showroom_established_12mo")
    # job lead -> by the role(s) advertised in the title
    t = (lead.get("title") or "").lower()
    k, b = "kitchen" in t, "bathroom" in t
    if k and b: return "job_kitchen_bathroom"
    if b:       return "job_bathroom"
    return "job_kitchen"


def _first_name(merged: dict) -> str:
    n = (merged.get("contact_name") or "").strip()
    return n.split()[0] if n else "there"


def draft_email(lead: dict, contact: dict | None = None, settings: dict | None = None) -> dict | None:
    merged = {**(lead or {}), **{k: v for k, v in (contact or {}).items() if v}}
    key = _template_key(merged)
    try:
        text = _load(key)
    except Exception as e:
        log.warning("Template '%s' load failed: %s", key, e)
        return None

    name = merged.get("showroom_name") or merged.get("company") or "your showroom"
    for a, b in {"[First Name]": _first_name(merged), "[Showroom Name]": name,
                 "[Company Name]": name, "[Your Name]": config.SENDER_NAME}.items():
        text = text.replace(a, b)

    lines = text.splitlines()
    subject, start = "", 0
    if lines and lines[0].lower().startswith("subject:"):
        subject = lines[0].split(":", 1)[1].strip()
        start = 1
    body = "\n".join(lines[start:]).strip()
    if not subject or not body:
        return None
    return {"subject": subject, "body": body, "template": key}
