"""Central config for the VW Contact Finder. Credentials come from environment
variables (so the same code runs locally via .env and in GitHub Actions via secrets).
The actual behaviour lives in DEFAULT_SETTINGS, overridden by the agent's row in the
dashboard when Supabase is connected."""
import os
from dotenv import load_dotenv

load_dotenv()


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _list(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


# --- Apollo ---
APOLLO_API_KEY = os.getenv("APOLLO_API_KEY", "")

# --- Supabase (the dashboard's database) ---
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")   # service_role key (server only)
AGENT_ID = os.getenv("AGENT_ID", "")                          # the contact-finder agent row id

# --- Fallback settings, used when the dashboard row carries none. The dashboard edits a
#     copy of this shape stored in the agents table. ---
DEFAULT_SETTINGS = {
    "max_per_run": int(os.getenv("MAX_PER_RUN", "10")),
    "tiers": _list("TIERS", "HOT - Virtual Worlds,WARM - Winner/Cyncly"),
    "skip_recruiters": _flag("SKIP_RECRUITERS", "true"),
    "reveal_phone": _flag("REVEAL_PHONE", "false"),
    "locations": _list("LOCATIONS", "United Kingdom"),
    "titles": [
        "Owner", "Founder", "Co-Founder", "Managing Director", "Director",
        "Proprietor", "Partner", "Showroom Manager", "General Manager", "Sales Director",
    ],
}
