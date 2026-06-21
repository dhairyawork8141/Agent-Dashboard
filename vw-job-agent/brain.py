"""The 'brain': a free Groq LLM that reads each candidate posting and decides, like a
human SDR would, whether it's a genuine KBB / interior-design business hiring a designer
who'd use CAD/CGI. Returns a verdict (fit, tier, score, reason, opener) or None on any
error so the run falls back to the keyword score (fail-soft, like the job sources)."""
import json
import logging
import config
import groq_pool

log = logging.getLogger("brain")

# CAD Illustrators' ideal customer, in plain language for the model.
_SYSTEM = """You are a lead-qualification analyst for CAD Illustrators, an outsourced
CAD/CGI studio that produces kitchen, bedroom & bathroom (KBB) and interior-design
visuals for SHOWROOMS and design retailers.

A GOOD lead is a posting where a KBB or interior-design BUSINESS (a kitchen/bedroom/
bathroom showroom, fitted-furniture retailer, or interior-design/fit-out firm) is hiring
a DESIGNER role (kitchen/bathroom/bedroom designer, design consultant, CAD designer,
showroom designer, interior designer, 3D/CGI visualiser). These businesses need CAD/CGI
work and are real prospects.

A BAD lead (fit=false) is anything else, e.g.: software vendors hiring their own staff
(Cyncly, Compusoft, 2020); non-design roles (sales/account/project managers, developers,
admin, support, installers, fitters); unrelated industries (graphic/web/UX/fashion/games);
or design roles with no KBB/interior connection.

Tiers:
- HOT: explicitly mentions Virtual Worlds, or is a clear KBB-showroom designer role using
  CGI/3D visualisation.
- WARM: KBB/interior business hiring a designer, mentions Winner/Cyncly/Compusoft or strong
  CAD/showroom signals.
- WATCH: plausibly a KBB/interior design role but weak or ambiguous signals.

Reply with ONLY a JSON object, no prose:
{"fit": true|false, "tier": "HOT"|"WARM"|"WATCH", "score": 0-100,
 "reason": "<one short sentence why>", "opener": "<one warm sentence to open outreach, or empty>"}"""

_TIER_LABEL = {"HOT": "HOT - Virtual Worlds", "WARM": "WARM - Winner/Cyncly", "WATCH": "WATCH - generic CAD"}


def available() -> bool:
    return groq_pool.available()


def _feedback_text(settings: dict | None) -> str:
    """Turn the user's recent rejections into a learning instruction for the brain."""
    fb = (settings or {}).get("rejection_feedback") or []
    if not fb:
        return ""
    lines = "\n".join(f"- {r.get('company', '?')}: {r.get('reject_reason', '')}" for r in fb[:25])
    return ("\n\nLEARN FROM THE USER: they recently REJECTED these leads. Treat similar "
            "postings as a WORSE fit (lower score; fit=false if clearly the same kind):\n" + lines)


def _user_prompt(job: dict) -> str:
    desc = (job.get("description") or "")[:1500]
    return (f"Title: {job.get('title','')}\n"
            f"Company: {job.get('company','')}\n"
            f"Location: {job.get('location','')}\n"
            f"Salary: {job.get('salary') or 'n/a'}\n"
            f"Description: {desc}")


def classify(job: dict, settings: dict | None = None) -> dict | None:
    if not available():
        return None
    model = (settings or {}).get("brain_model") or config.GROQ_MODEL
    content = groq_pool.chat(
        [{"role": "system", "content": _SYSTEM + _feedback_text(settings)},
         {"role": "user", "content": _user_prompt(job)}],
        model=model, role="judge", temperature=0)
    if not content:
        log.warning("Brain unavailable/exhausted for %r - falling back to keyword score",
                    job.get("title"))
        return None
    try:
        verdict = json.loads(content)
    except Exception as e:
        log.warning("Brain bad JSON for %r (%s) - falling back to keyword score",
                    job.get("title"), e)
        return None

    tier = str(verdict.get("tier", "WATCH")).upper()
    verdict["tier_label"] = _TIER_LABEL.get(tier, _TIER_LABEL["WATCH"])
    verdict["fit"] = bool(verdict.get("fit"))
    try:
        verdict["score"] = max(0, min(100, int(verdict.get("score", 0))))
    except (TypeError, ValueError):
        verdict["score"] = 0
    return verdict


def judge(job: dict, settings: dict | None = None) -> dict | None:
    """Apply the brain's verdict onto the job in place. Returns the job if it's a fit,
    None if the brain rejects it. Returns the job unchanged if the brain is unavailable
    or errors (fail-soft -> keyword score stands)."""
    verdict = classify(job, settings)
    if verdict is None:
        return job
    if not verdict["fit"]:
        return None
    job["tier"] = verdict["tier_label"]
    job["score"] = verdict["score"]
    job["score_reasons"] = [f"AI: {verdict.get('reason','')}"]
    if verdict.get("opener"):
        job["opening_line"] = verdict["opener"]
    job["ai_judged"] = True
    return job
