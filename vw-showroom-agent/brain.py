"""Groq 'brain' that judges whether a newly-registered company is a genuine KBB /
interior-design business CAD Illustrators could sell outsourced CAD/CGI design to.
Returns {fit, tier, score, reason} or None on error (fail-soft -> keyword fallback)."""
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

_SYSTEM = """You qualify newly-registered UK companies as sales leads for CAD Illustrators,
an outsourced CAD/CGI studio that produces kitchen, bedroom & bathroom (KBB) and
interior-design visuals for showrooms, retailers and fitters.

A GOOD lead is a business that designs/sells/fits kitchens, bedrooms, bathrooms, fitted
furniture, tiles/worktops, or does interior design - i.e. someone who needs design
renders. A BAD lead is anything unrelated (plumbing-only, scaffolding, cleaning,
property/lettings, cafes, consultancies, holding companies, etc.) even if the name
coincidentally contains a keyword.

Tier by how clearly they're a design-led KBB/interior business:
  HOT  = clearly a kitchen/bathroom/bedroom showroom or interior-design studio
  WARM = plausibly KBB/interior (fitter, furniture, tiles) but less certain
  WATCH= weak/ambiguous
Reply with ONLY JSON:
{"fit": true|false, "tier": "HOT|WARM|WATCH", "score": 0-100, "reason": "<one short line>"}"""


def available() -> bool:
    return bool(config.GROQ_API_KEY)


def classify(lead: dict, settings: dict | None = None) -> dict | None:
    if not available():
        return None
    model = (settings or {}).get("brain_model") or config.GROQ_MODEL
    user = (f"Company: {lead.get('company','')}\n"
            f"Location: {lead.get('location','')}\n"
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
