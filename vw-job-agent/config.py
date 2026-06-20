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
JOOBLE_API_KEY = os.getenv("JOOBLE_API_KEY", "")        # free key: https://jooble.org/api/about
CAREERJET_AFFID = os.getenv("CAREERJET_AFFID", "")      # free affid: careerjet.com/partners
# Paid (RapidAPI). Unlocks Google-for-Jobs: LinkedIn, Indeed, Glassdoor, ZipRecruiter, Monster.
JSEARCH_API_KEY = os.getenv("JSEARCH_API_KEY", "")      # https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch

# --- Supabase (optional - the dashboard's database). With these set, the agent reads
#     its settings from the dashboard and writes finds back so they appear there. ---
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")   # service_role key (server only)
AGENT_ID = os.getenv("AGENT_ID", "")

# --- Gemini enrichment credentials (the on/off toggle lives in settings) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ENRICH_MODEL = os.getenv("ENRICH_MODEL", "gemini-2.0-flash")

# --- Groq "brain": free LLM that judges each candidate lead for KBB/interior-design fit ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# --- Email credentials (the on/off toggle lives in settings) ---
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.office365.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")        # the sending mailbox (e.g. dhairya@cadillustrator.com)
SMTP_PASS = os.getenv("SMTP_PASS", "")        # only used for basic-password auth (fallback)
ALERT_FROM = os.getenv("ALERT_FROM", SMTP_USER)
ALERT_TO = os.getenv("ALERT_TO", "")

# --- Microsoft 365 OAuth2 (app-only / client-credentials) SMTP ---
# When these three are set, notify.py authenticates to Office 365 SMTP with an OAuth
# token (XOAUTH2) instead of a password. This works with Security Defaults / MFA left ON.
# Register an app in Entra, grant it the SMTP.SendAsApp application permission, and
# register its service principal in Exchange Online (see notify.py header for steps).
OAUTH_TENANT_ID = os.getenv("OAUTH_TENANT_ID", "")
OAUTH_CLIENT_ID = os.getenv("OAUTH_CLIENT_ID", "")
OAUTH_CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET", "")

# --- Fallback settings, used when Supabase isn't connected. The dashboard edits a copy
#     of this shape stored in the agents table. ---
DEFAULT_SETTINGS = {
    "countries": [c.strip() for c in os.getenv("COUNTRIES", "gb,us,ca,au,nz,de,fr,nl").split(",") if c.strip()],
    "careerjet_locales": [c.strip() for c in os.getenv("CAREERJET_LOCALES", "en_GB,en_US").split(",") if c.strip()],
    "jsearch_countries": [c.strip() for c in os.getenv("JSEARCH_COUNTRIES", "gb,us").split(",") if c.strip()],
    "jsearch_max_per_run": int(os.getenv("JSEARCH_MAX_PER_RUN", "2")),  # free BASIC safe: 2/run x3/day ~= 180/mo
    "max_days_old": int(os.getenv("MAX_DAYS_OLD", "3")),
    "enrich_with_claude": _flag("ENRICH_WITH_CLAUDE"),
    "send_email": _flag("SEND_EMAIL"),
    # --- AI brain (Groq): final human-like judge of KBB/interior-design fit. Runs only on
    #     candidates that clear the keyword pre-filter, capped per run to respect free quota. ---
    "use_brain": _flag("USE_BRAIN", "true"),
    "brain_max_per_run": int(os.getenv("BRAIN_MAX_PER_RUN", "30")),
    # Hermes goal: how many HOT leads/day the planner steers toward.
    "daily_hot_goal": int(os.getenv("DAILY_HOT_GOAL", "10")),
    # --- Quality gate: only leads scoring >= min_score are saved/emailed. Postings
    #     containing any exclude_term are disqualified outright. Tune from the dashboard.
    #     ~70 = HOT/WARM only, ~50 = + strong WATCH (balanced), ~30 = keep most CAD/KBB.
    "min_score": int(os.getenv("MIN_SCORE", "50")),
    "exclude_terms": [t.strip() for t in os.getenv("EXCLUDE_TERMS",
        "graphic designer,web designer,ux designer,ui designer,ux/ui,ui/ux,"
        "fashion,jewellery,jewelry,game designer,vfx artist,motion graphic,"
        "hairdresser,nail technician,florist").split(",") if t.strip()],
    # The advert TITLE must contain one of these, or it's not a designer vacancy
    # (drops Account/Sales/Project Managers, developers, support, admin, etc.).
    "role_terms": [t.strip() for t in os.getenv("ROLE_TERMS",
        "designer,design consultant,cad,draught,draft,kbb,kitchen design,"
        "bathroom design,3d visual,cgi,render").split(",") if t.strip()],
    # If the EMPLOYER is one of these, it's the software vendor hiring internally,
    # not a showroom -> drop (adverts that merely mention the software still pass).
    "exclude_companies": [t.strip() for t in os.getenv("EXCLUDE_COMPANIES",
        "cyncly,compusoft,winner design,2020,fusion software,virtual worlds software").split(",") if t.strip()],
    "searches": [
        {"label": "Virtual Worlds (exact)", "phrase": "virtual worlds"},
        {"label": "Cyncly",                 "phrase": "cyncly"},
        {"label": "Winner Design",          "phrase": "winner design"},
        {"label": "Compusoft",              "phrase": "compusoft"},
        {"label": "Bathroom designer",      "phrase": "bathroom designer"},
        {"label": "Kitchen designer",       "phrase": "kitchen designer"},
        {"label": "Bedroom designer",       "phrase": "bedroom designer"},
        {"label": "KBB designer",           "phrase": "kbb designer"},
        {"label": "Showroom designer",      "phrase": "showroom designer"},
        {"label": "Interior design (CAD)",  "phrase": "interior designer", "extra": "CAD"},
    ],
    "hot_terms":  ["virtual worlds", "virtual world", "vw 4d", "4d theatre", "4d theater"],
    "warm_terms": ["winner design", "winner cad", "winner flex", "cyncly", "compusoft"],
    "watch_terms": ["cad", "kbb", "bathroom design", "kitchen design", "bedroom design",
                    "fitted furniture", "showroom", "interior design", "autocad", "sketchup"],
}
