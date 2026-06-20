"""Smart HOT tiering: a lead is HOT when it's a strong KBB/interior fit AND shows buying
signals — recently registered, reachable (has a website/contact), and a clear category —
*regardless of source*. This lets OpenStreetMap and any future platform earn HOT, not just
new Companies House registrations, so Hermes can hit its 10-HOT/day goal from anywhere.

Recency still counts heavily (a brand-new company is the classic HOT signal), so genuine new
incorporations keep going HOT exactly as before. Falls back gracefully when the brain is off."""
import brain


def _recency_bonus(lead: dict, settings: dict) -> int:
    age = brain._months_old(lead.get("registered_at") or "")
    if age is None:
        return 0
    if age <= int(settings.get("hot_max_months", 6)):
        return 30
    if age <= int(settings.get("warm_max_months", 12)):
        return 12
    return 0


def score_hotness(lead: dict, verdict: dict | None, settings: dict) -> int:
    """0-100 'how hot is this lead' from fit quality + recency + category + reachability."""
    v = verdict or {}
    if v.get("fit") is False:
        return 0
    fit_score = int(v.get("score") or lead.get("score") or 0)
    weight = float(settings.get("hot_fit_weight", 0.7))
    h = int(fit_score * weight)                              # up to ~70 from fit quality
    h += _recency_bonus(lead, settings)                      # up to 30 for newness
    cat = (v.get("category") or lead.get("category") or "other")
    if cat not in ("other", ""):
        h += 10                                              # a clear KBB/interior category
    if lead.get("website") or lead.get("contact_email"):
        h += 10                                              # already reachable
    return min(h, 100)


def smart_tier(lead: dict, verdict: dict | None, settings: dict) -> str:
    """Return 'HOT|WARM|WATCH - <suffix>'. Gates elsewhere match by the HOT/WARM prefix."""
    suffix = lead.get("_tier_suffix") or "Showroom"
    if (verdict or {}).get("fit") is False:
        return f"WATCH - {suffix}"
    h = score_hotness(lead, verdict, settings)
    hot_t = int(settings.get("hot_threshold", 70))
    warm_t = int(settings.get("warm_threshold", 45))
    prefix = "HOT" if h >= hot_t else "WARM" if h >= warm_t else "WATCH"
    return f"{prefix} - {suffix}"
