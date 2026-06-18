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

# Tier strings keep the "- New showroom" suffix so they match the contact agent's
# apollo_tiers setting (only HOT leads spend Apollo credits).
TIER_HOT = "HOT - New showroom"
TIER_WARM = "WARM - New showroom"
TIER_WATCH = "WATCH - New showroom"
_TIER = {"HOT": TIER_HOT, "WARM": TIER_WARM, "WATCH": TIER_WATCH}
# Valid business-type categories the brain may return.
CATEGORIES = {"kitchen", "bathroom", "kbb", "bedroom", "fitter", "interior", "other"}

_SYSTEM = """You qualify UK companies as sales leads for CAD Illustrators, an outsourced
CAD/CGI studio that makes kitchen, bedroom & bathroom (KBB) and interior-design visuals
for showrooms, retailers and fitters.

fit=false (drop it) = anything that is NOT a KBB/interior-design business:
plumbing-only, scaffolding, cleaning, property/lettings, cafes, consultancies, holding
companies, or a coincidental name match.

For fit=true businesses, return TWO things:

1) category - the business TYPE (pick exactly one):
   "kitchen"  = kitchen showroom / kitchen retailer
   "bathroom" = bathroom showroom / bathroom retailer
   "kbb"      = clearly does BOTH kitchens AND bathrooms
   "bedroom"  = fitted-bedroom / fitted-furniture specialist
   "fitter"   = installer / fitter / joiner who fits kitchens or bathrooms (NOT a retail showroom)
   "interior" = interior-design studio / firm
   "other"    = KBB-related but none of the above, or unclear

2) tier - the PRIORITY, judged purely on how new it is (use the "Registered" line):
   "HOT"   = NEW (recently registered) - the best targets, just starting out, no CGI supplier yet
   "WARM"  = ESTABLISHED (older)
   "WATCH" = ambiguous / low confidence

Reply with ONLY JSON:
{"fit": true|false, "category": "kitchen|bathroom|kbb|bedroom|fitter|interior|other",
 "tier": "HOT|WARM|WATCH", "score": 0-100, "reason": "<one short line>"}"""


def _months_old(date_str: str):
    try:
        d = datetime.date.fromisoformat((date_str or "")[:10])
        t = datetime.date.today()
        return (t.year - d.year) * 12 + (t.month - d.month) - (1 if t.day < d.day else 0)
    except Exception:
        return None


def tier_from_registration(date_str: str, settings: dict | None = None) -> str:
    """Deterministic tier purely by how recently the company was registered:
    <= hot_max_months -> HOT, <= warm_max_months -> WARM, else WATCH."""
    s = settings or {}
    hot = int(s.get("hot_max_months", 6))
    warm = int(s.get("warm_max_months", 12))
    age = _months_old(date_str)
    if age is None:
        return TIER_WATCH
    if age <= hot:
        return TIER_HOT
    if age <= warm:
        return TIER_WARM
    return TIER_WATCH


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
    cat = str(out.get("category", "")).lower().strip()
    return {
        "fit": bool(out.get("fit")),
        "category": cat if cat in CATEGORIES else "other",
        "tier": _TIER.get(str(out.get("tier", "")).upper(), TIER_WATCH),
        "score": int(out.get("score") or 0),
        "reason": (out.get("reason") or "").strip(),
    }
