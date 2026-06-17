import os
import sys
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.dirname(__file__))

import config
import supabase_io
import draft

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("backfill")

def run():
    sb = supabase_io._base()
    import requests
    
    # Get leads that have an email but NO draft_status = pending or approved
    r = requests.get(f"{sb}/leads", headers=supabase_io._headers(), params={
        "contact_email": "not.is.null",
        "draft_status": "in.(none,)",
        "select": "*"
    })
    r.raise_for_status()
    leads = r.json()
    
    log.info(f"Found {len(leads)} leads needing email drafts.")
    settings = supabase_io.load_settings() or config.DEFAULT_SETTINGS
    
    done = 0
    for lead in leads:
        contact = lead.copy()
        if draft.available():
            d = draft.draft_email(lead, contact, settings)
            if d:
                patch = {
                    "draft_subject": d["subject"],
                    "draft_body": d["body"],
                    "draft_status": "pending",
                    "drafted_at": datetime.now(timezone.utc).isoformat(),
                }
                supabase_io.update_lead(lead["id"], patch)
                done += 1
                log.info(f"Drafted email for {lead.get('company')} to {contact.get('contact_email')}")
            else:
                log.error(f"Draft failed for {lead.get('company')}")
        else:
            log.error("Drafting not available! Check GROQ_API_KEY")
            break

    log.info(f"Done drafting {done} emails.")

if __name__ == "__main__":
    run()
