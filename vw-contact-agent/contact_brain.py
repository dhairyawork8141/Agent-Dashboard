"""Groq 'contact brain' (Phase 2) — reads a verified company website and picks the BEST
decision-maker contact, instead of regex-grabbing the first email on the page.

Runs on the cheap 8B model (DRAFT_MODEL) which has a generous free daily budget, so every
enriched lead can afford one call. Fail-soft: no key / 429 / bad JSON -> returns None and
the caller falls back to the existing regex extraction. It NEVER invents an address — it
may only return an email that literally appears in the page text (caller re-checks)."""
import json
import logging

import config
import groq_pool

log = logging.getLogger("contact_brain")
_MAX_CHARS = 6000          # keep the prompt small (token budget) — contact info is up top

_SYSTEM = """You read the scraped text of a UK company's website and extract the single
best person to approach for a B2B sales pitch (the owner / director / decision-maker).

Rules:
- ONLY use an email address that literally appears in the provided text. Never guess,
  pattern-build, or invent one. If no real email is in the text, return email: null.
- Prefer a PERSONAL named address (e.g. sarah@firm.co.uk) over a generic one
  (info@, sales@, enquiries@) — but a generic company address is fine if that's all there is.
- Prefer an email on the company's OWN domain. Ignore third-party emails (web designers,
  suppliers, social networks, analytics).
- Only give a contact name/title if the text clearly attributes them to THIS company.
- confidence = how sure you are this is the right company's real decision-maker email (0-100).

Reply with ONLY JSON:
{"is_company": true|false, "email": "<addr or null>", "name": "<full name or null>",
 "title": "<role or null>", "confidence": 0-100}"""


def available() -> bool:
    return groq_pool.available()


def extract_contact(company: str, page_text: str, domain: str | None = None,
                    settings: dict | None = None) -> dict | None:
    """Return {email, name, title, confidence, is_company} judged from the page text,
    or None on any failure (caller keeps its regex result)."""
    if not available() or not (page_text or "").strip():
        return None
    model = (settings or {}).get("draft_model") or config.DRAFT_MODEL
    user = (f"Company: {company}\n"
            f"Their website domain: {domain or 'unknown'}\n\n"
            f"WEBSITE TEXT:\n{page_text[:_MAX_CHARS]}")
    content = groq_pool.chat(
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
        model=model, role="extract", temperature=0)
    if not content:
        return None
    try:
        out = json.loads(content)
    except Exception as e:
        log.warning("Contact-brain bad JSON for %r (%s)", company, e)
        return None
    email = (out.get("email") or "").strip().lower() or None
    return {
        "is_company": bool(out.get("is_company")),
        "email": email,
        "name": (out.get("name") or "").strip() or None,
        "title": (out.get("title") or "").strip() or None,
        "confidence": int(out.get("confidence") or 0),
    }


_CONFIRM_SYSTEM = """You verify whether a web domain is the OFFICIAL site of a specific UK
KBB/interior business (kitchen/bedroom/bathroom showroom, fitter, or interior designer).
Say no if the domain belongs to a DIFFERENT organisation that merely shares a word — e.g. a
magazine, newspaper, a town/council/community site, a directory, or an unrelated company in
another trade or country. Reply ONLY JSON: {"belongs": true|false}"""


def confirm_match(company: str, domain: str, settings: dict | None = None):
    """True/False whether `domain` is plausibly THIS company's official site; None if the
    brain is unavailable (caller then falls back to the heuristic only)."""
    if not available() or not domain:
        return None
    model = (settings or {}).get("draft_model") or config.DRAFT_MODEL
    user = f"Business name: {company}\nDomain: {domain}\nDoes this domain belong to that exact business?"
    content = groq_pool.chat(
        [{"role": "system", "content": _CONFIRM_SYSTEM}, {"role": "user", "content": user}],
        model=model, role="extract", temperature=0)
    if not content:
        return None
    try:
        return bool(json.loads(content).get("belongs"))
    except Exception:
        return None
