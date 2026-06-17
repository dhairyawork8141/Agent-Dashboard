"""Optional: Claude reads each posting, names the hiring showroom and drafts an opener.
The on/off decision is made by the caller (from settings); this just needs the API key."""
import json
import logging
import config

log = logging.getLogger("enrich")

PROMPT = """You are a B2B sales researcher for CAD Illustrators, an outsourced CAD and CGI \
design studio that serves kitchen & bathroom showrooms (showrooms WhatsApp a brief; \
specialist designers return finished plans, elevations and photoreal renders in 24-48 hours; \
the first project is free).

You are given a job advert where a showroom is hiring a designer. Return ONLY a JSON object \
(no prose, no code fences) with exactly these keys:
- "showroom_name": the actual hiring showroom if identifiable, else "unknown (recruiter-listed)"
- "decision_maker_hint": any named person or specific role to address, else ""
- "fit_note": one short sentence on why they are a good CAD Illustrators lead
- "opening_line": one personalised first line for a cold email referencing their specific \
advert. Warm, human, under 30 words, no greeting, no sign-off.

Advert:
Title: {title}
Company field: {company}
Location: {location}
Description: {description}"""


def enrich(job: dict) -> dict:
    if not config.ANTHROPIC_API_KEY:
        return job
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=config.ENRICH_MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": PROMPT.format(
                title=job.get("title", ""),
                company=job.get("company", ""),
                location=job.get("location", ""),
                description=(job.get("description", "") or "")[:2000],
            )}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        text = text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        job["showroom_name"] = data.get("showroom_name", "")
        job["decision_maker_hint"] = data.get("decision_maker_hint", "")
        job["fit_note"] = data.get("fit_note", "")
        job["opening_line"] = data.get("opening_line", "")
    except Exception as e:
        log.warning("Enrichment failed for '%s': %s", job.get("title"), e)
    return job
