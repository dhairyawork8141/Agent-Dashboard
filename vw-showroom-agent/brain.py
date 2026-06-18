"""Groq 'brain' that judges whether a newly-registered company is a genuine KBB /
interior-design business CAD Illustrators could sell outsourced CAD/CGI design to.
Returns {fit, tier, score, reason} or None on error (fail-soft -> keyword fallback)."""
import datetime
import json
import logging
import requests
import config

log = logging.getLogger("brain")
TIMEOUT = 30
_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

TIER_HOT = "HOT - New showroom"
TIER_WARM = "WARM - New showroom"
TIER_WATCH = "WATCH - New showroom"
_TIER = {"HOT": TIER_HOT, "WARM": TIER_WARM, "WATCH": TIER_WATCH}

_SYSTEM = """You qualify UK companies as sales leads for CAD Illustrators, an outsourced
CAD/CGI studio that makes kitchen, bedroom & bathroom (KBB) and interior-design visuals
for showrooms and retailers.

fit=false (drop it) = anything that is NOT a real KBB/interior-design business:
plumbing-only, scaffolding, cleaning, property/lettings, cafes, consultancies, holding
companies, or a coincidental name match.

For fit=true businesses, choose the tier from BOTH what they are AND how new they are
(use the "Registered" line):
  HOT  = a clear kitchen/bathroom/bedroom SHOWROOM or interior-design studio that is NEW
         (recently registered). Brand-new showrooms are the best targets - just opening,
         no existing CGI supplier yet.
  WARM = a clear KBB/interior business that is ESTABLISHED (older), OR any less-certain
         KBB type (fitter, furniture maker, joinery, tiles) at any age.
  WATCH= weak / ambiguous.
Reply with ONLY JSON:
{"fit": true|false, "tier": "HOT|WARM|WATCH", "score": 0-100, "reason": "<one short line>"}"""


def _months_old(date_str: str):
    try:
        d = datetime.date.fromisoformat((date_str or "")[:10])
        t = datetime.date.today()
        return (t.year - d.year) * 12 + (t.month - d.month)
    except Exception:
        return None


def available() -> bool:
    return bool(config.GROQ_API_KEY)


def classify(lead: dict, settings: dict | None = None) -> dict | None:
    if not available():
        return None
    model = (settings or {}).get("brain_model") or config.GROQ_MODEL
    hot_max = int((settings or {}).get("hot_max_age_months", 18))
    age = _months_old(lead.get("posted", ""))
    if age is None:
        recency = "Registered: date unknown"
    else:
        tag = "NEW" if age <= hot_max else "ESTABLISHED"
        recency = f"Registered: {lead.get('posted')} ({age} months ago - {tag})"
    user = (f"Company: {lead.get('company','')}\n"
            f"Location: {lead.get('location','')}\n"
            f"{recency}\n"
            f"Details: {lead.get('description','')}")
    try:
        r = requests.post(_ENDPOINT, timeout=TIMEOUT,
            headers={"Authorization": f"Bearer {config.GROQ_API_KEY}",
                     "Content-Type": "application/json"},
            json={"model": model, "temperature": 0,
                  "response_format": {"type": "json_object"},
                  "messages": [{"role": "system", "content": _SYSTEM},
                               {"role": "user", "content": user}]})
        r.raise_for_status()
        out = json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception as e:
        log.warning("Brain call failed for %r (%s)", lead.get("company"), e)
        return None
    return {
        "fit": bool(out.get("fit")),
        "tier": _TIER.get(str(out.get("tier", "")).upper(), TIER_WATCH),
        "score": int(out.get("score") or 0),
        "reason": (out.get("reason") or "").strip(),
    }
