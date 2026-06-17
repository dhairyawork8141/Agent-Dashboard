"""Central configuration. Credentials come from environment variables (so the same code
runs locally via .env and in GitHub Actions via secrets). The actual search behaviour
lives in DEFAULT_SETTINGS, which is overridden by the dashboard's settings when Supabase
is connected."""
import os
from dotenv import load_dotenv

load_dotenv()


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


# --- Job board APIs (free tiers) ---
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")
REED_API_KEY = os.getenv("REED_API_KEY", "")

# --- Supabase (optional - the dashboard's database). With these set, the agent reads
#     its settings from the dashboard and writes finds back so they appear there. ---
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")   # service_role key (server only)
AGENT_ID = os.getenv("AGENT_ID", "")

# --- Gemini enrichment credentials (the on/off toggle lives in settings) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ENRICH_MODEL = os.getenv("ENRICH_MODEL", "gemini-2.0-flash")

# --- Email credentials (the on/off toggle lives in settings) ---
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.office365.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
ALERT_FROM = os.getenv("ALERT_FROM", SMTP_USER)
ALERT_TO = os.getenv("ALERT_TO", "")

# --- Fallback settings, used when Supabase isn't connected. The dashboard edits a copy
#     of this shape stored in the agents table. ---
DEFAULT_SETTINGS = {
    "countries": [c.strip() for c in os.getenv("COUNTRIES", "gb,ie").split(",") if c.strip()],
    "max_days_old": int(os.getenv("MAX_DAYS_OLD", "3")),
    "enrich_with_claude": _flag("ENRICH_WITH_CLAUDE"),
    "send_email": _flag("SEND_EMAIL"),
    "searches": [
        {"label": "Virtual Worlds (exact)", "phrase": "virtual worlds"},
        {"label": "Cyncly",                 "phrase": "cyncly"},
        {"label": "Winner Design",          "phrase": "winner design"},
        {"label": "Compusoft",              "phrase": "compusoft"},
        {"label": "Bathroom CAD designer",  "phrase": "bathroom designer", "extra": "CAD"},
        {"label": "Kitchen CAD designer",   "phrase": "kitchen designer",  "extra": "CAD"},
    ],
    "hot_terms":  ["virtual worlds", "virtual world", "vw 4d", "4d theatre", "4d theater"],
    "warm_terms": ["winner design", "winner cad", "winner flex", "cyncly", "compusoft"],
    "watch_terms": ["cad", "kbb", "bathroom design", "kitchen design", "autocad", "sketchup"],
}
