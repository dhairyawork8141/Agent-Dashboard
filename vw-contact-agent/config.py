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

# --- Groq "brain": free LLM that drafts the personalised outreach email ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
# Smaller/faster model for the light email personalisation (high free-tier limits).
DRAFT_MODEL = os.getenv("DRAFT_MODEL", "llama-3.1-8b-instant")

# --- Sending: Microsoft 365 OAuth2 (app-only) SMTP. Same app/secrets as the job agent.
#     The sender mails APPROVED drafts; it stays inert until these are set. ---
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.office365.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")                        # the sending mailbox
ALERT_FROM = os.getenv("ALERT_FROM", SMTP_USER)
OAUTH_TENANT_ID = os.getenv("OAUTH_TENANT_ID", "")
OAUTH_CLIENT_ID = os.getenv("OAUTH_CLIENT_ID", "")
OAUTH_CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET", "")
# Studio details the brain weaves into the draft.
STUDIO_NAME = os.getenv("STUDIO_NAME", "CAD Illustrators")
SENDER_NAME = os.getenv("SENDER_NAME", "Dhairya")

# --- Send throttling (cold-email warm-up / deliverability) ---
SEND_DAILY_CAP = int(os.getenv("SEND_DAILY_CAP", "30"))        # max approved emails sent per day
SEND_PER_RUN = int(os.getenv("SEND_PER_RUN", "6"))            # max per workflow run (hourly)
SEND_MIN_GAP_SECONDS = int(os.getenv("SEND_MIN_GAP_SECONDS", "45"))   # min gap between sends (jittered up to 2x)

# --- Fallback settings, used when the dashboard row carries none. The dashboard edits a
#     copy of this shape stored in the agents table. ---
DEFAULT_SETTINGS = {
    "max_per_run": int(os.getenv("MAX_PER_RUN", "10")),
    # Minimum confidence (0-100) to keep a web-scraped email. Below this we save no email
    # rather than risk a wrong one (cold outreach: a bad address burns the lead + domain).
    "min_contact_confidence": int(os.getenv("MIN_CONTACT_CONFIDENCE", "50")),
    # Hermes goal: how many HOT leads/day the planner steers toward.
    "daily_hot_goal": int(os.getenv("DAILY_HOT_GOAL", "10")),
    "tiers": _list("TIERS", "HOT - Virtual Worlds,WARM - Winner/Cyncly"),
    "skip_recruiters": _flag("SKIP_RECRUITERS", "true"),
    "reveal_phone": _flag("REVEAL_PHONE", "false"),
    # Only these (high-value) tiers spend Apollo credits; everything else is web-scrape only.
    "apollo_tiers": _list("APOLLO_TIERS", "HOT - Virtual Worlds,HOT - New showroom"),
    # When true, after finding a contact the agent drafts an outreach email (from the
    # per-sector templates) and parks it as 'pending' for you to approve in the dashboard.
    "draft_emails": _flag("DRAFT_EMAILS", "true"),
    # Only these tiers get a draft (default HOT only) — keeps drafting focused on hot leads.
    "draft_tiers": _list("DRAFT_TIERS", "HOT - Virtual Worlds,HOT - New showroom"),
    # Let the AI lightly personalise each template draft (falls back to plain template).
    "personalise_drafts": _flag("PERSONALISE_DRAFTS", "true"),
    "locations": _list("LOCATIONS", "United Kingdom"),
    "titles": [
        "Owner", "Founder", "Co-Founder", "Managing Director", "Director",
        "Proprietor", "Partner", "Showroom Manager", "General Manager", "Sales Director",
    ],
}
