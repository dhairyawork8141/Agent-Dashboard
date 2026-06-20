"""Central config for the New-Showroom Finder (agent #3). Credentials come from env vars
(local .env or GitHub Actions secrets). Live behaviour is read from the agent's row in the
dashboard (agents.settings), falling back to DEFAULT_SETTINGS below."""
import os
from dotenv import load_dotenv

load_dotenv()


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _list(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


# --- Companies House (free): https://developer.company-information.service.gov.uk ---
COMPANIES_HOUSE_API_KEY = os.getenv("COMPANIES_HOUSE_API_KEY", "")

# --- Supabase (the dashboard's database) ---
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")   # service_role key (server only)
AGENT_ID = os.getenv("AGENT_ID", "")                          # the showroom-finder agent row id

# --- Groq "brain": free LLM that judges KBB/interior-design business fit ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# --- Fallback settings; the dashboard edits a copy of this shape in the agents table. ---
DEFAULT_SETTINGS = {
    # Newly-incorporated companies whose NAME contains one of these are strong KBB signals.
    "name_keywords": _list("NAME_KEYWORDS",
        "kitchen,kitchens,bathroom,bathrooms,bedroom,bedrooms,interiors,kbb,"
        "tiles,worktops,fitted furniture"),
    # Only companies incorporated within this many days (catch them while they're new).
    "incorporated_within_days": int(os.getenv("INCORPORATED_WITHIN_DAYS", "45")),
    "company_status": os.getenv("COMPANY_STATUS", "active"),
    "max_per_run": int(os.getenv("MAX_PER_RUN", "25")),       # cap brain calls / writes per run
    # Bulk judging uses the 8B model (huge daily budget); 70B is reserved for the lower-volume
    # job agent. Avoids the per-minute rate-limiting seen judging 150 shops/run on 70B.
    "brain_model": os.getenv("SHOWROOM_BRAIN_MODEL", "llama-3.1-8b-instant"),
    "use_brain": _flag("USE_BRAIN", "true"),
    # Hermes goal: how many HOT leads/day the planner steers toward.
    "daily_hot_goal": int(os.getenv("DAILY_HOT_GOAL", "10")),
    "min_score": int(os.getenv("MIN_SCORE", "50")),
    # Recency feeds the Smart HOT score (newness is a strong signal but no longer the ONLY one).
    "hot_max_months": int(os.getenv("HOT_MAX_MONTHS", "6")),
    "warm_max_months": int(os.getenv("WARM_MAX_MONTHS", "12")),
    # Smart HOT thresholds: a lead's 0-100 hotness (fit + recency + category + reachability)
    # >= hot_threshold => HOT, >= warm_threshold => WARM, else WATCH. Lets any source go HOT.
    "hot_threshold": int(os.getenv("HOT_THRESHOLD", "70")),
    "warm_threshold": int(os.getenv("WARM_THRESHOLD", "45")),
    # Optional SIC-code filter (KBB-relevant). Empty = name-keyword search only.
    "sic_codes": _list("SIC_CODES", ""),
    # --- OpenStreetMap source (free, no key, UK-only existing KBB/interior shops) ---
    "use_osm": _flag("USE_OSM", "true"),
    "osm_shop_tags": _list("OSM_SHOP_TAGS",
        "kitchen,bathroom_furnishing,interior_decoration,bed,tiles"),
    "osm_max": int(os.getenv("OSM_MAX", "2000")),    # safety bound on the country-wide query
}
