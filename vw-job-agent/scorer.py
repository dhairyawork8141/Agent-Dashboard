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
    exclude = s.get("exclude_terms") or config.DEFAULT_SETTINGS.get("exclude_terms", [])
    role_terms = s.get("role_terms") or config.DEFAULT_SETTINGS.get("role_terms", [])
    excl_companies = s.get("exclude_companies") or config.DEFAULT_SETTINGS.get("exclude_companies", [])

    title = (job.get("title") or "").lower()
    company = (job.get("company") or "").lower()
    text = f"{title} {company} {job.get('description','')}".lower()

    def _disqualify(reason: str) -> dict:
        job["tier"] = TIER_WATCH
        job["score"] = 0
        job["is_recruiter"] = False
        job["disqualified"] = True
        job["score_reasons"] = [reason]
        return job

    # 1. Off-target roles (graphic/web/fashion/etc.) anywhere in the advert.
    hit = next((t for t in exclude if t in text), None)
    if hit:
        return _disqualify(f"excluded: off-target term '{hit}'")

    # 2. Employer IS the software vendor (Cyncly/Compusoft/...) hiring internally,
    #    not a showroom. Adverts that only mention the software still pass.
    vhit = next((c for c in excl_companies if c and c in company), None)
    if vhit:
        return _disqualify(f"excluded: employer is the software vendor '{vhit}', not a showroom")

    # 3. Must be a designer vacancy: a role term has to appear in the title
    #    (drops Account/Sales/Project Managers, developers, support, admin...).
    role_field = title or text
    if role_terms and not any(t in role_field for t in role_terms):
        return _disqualify("excluded: title is not a designer/CAD role")

    if any(t in text for t in hot):
        tier, base = TIER_HOT, 100
    elif any(t in text for t in warm):
        tier, base = TIER_WARM, 70
    elif any(t in text for t in watch):
        tier, base = TIER_WATCH, 40
    else:
        # Matched a search phrase but none of our relevance keywords -> noise.
        tier, base = TIER_WATCH, 0

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
