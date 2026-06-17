"""Assigns each posting a tier and fit score from the keyword lists in `settings`
(which come from the dashboard, or fall back to config defaults)."""
import config

TIER_HOT = "HOT - Virtual Worlds"
TIER_WARM = "WARM - Winner/Cyncly"
TIER_WATCH = "WATCH - generic CAD"

RECRUITER_HINTS = ["recruitment", "recruiter", "talent", "resourcing", "consultancy",
                   "we are working with", "our client", "on behalf of", "agency"]


def score_job(job: dict, settings: dict | None = None) -> dict:
    s = settings or config.DEFAULT_SETTINGS
    hot = s.get("hot_terms") or config.DEFAULT_SETTINGS["hot_terms"]
    warm = s.get("warm_terms") or config.DEFAULT_SETTINGS["warm_terms"]
    watch = s.get("watch_terms") or config.DEFAULT_SETTINGS["watch_terms"]

    text = f"{job.get('title','')} {job.get('company','')} {job.get('description','')}".lower()

    if any(t in text for t in hot):
        tier, base = TIER_HOT, 100
    elif any(t in text for t in warm):
        tier, base = TIER_WARM, 70
    elif any(t in text for t in watch):
        tier, base = TIER_WATCH, 40
    else:
        tier, base = TIER_WATCH, 20

    reasons = []
    if job.get("salary"):
        base += 10
        reasons.append("salary listed (real budget)")

    is_recruiter = any(h in text for h in RECRUITER_HINTS)
    if is_recruiter:
        reasons.append("via recruiter - identify the showroom before contacting")
    else:
        base += 10
        reasons.append("looks like a direct employer")

    job["tier"] = tier
    job["score"] = base
    job["is_recruiter"] = is_recruiter
    job["score_reasons"] = reasons
    return job
