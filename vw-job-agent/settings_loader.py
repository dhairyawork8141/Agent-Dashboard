"""Decides what settings this run uses: the dashboard's (if Supabase is connected and the
agent is enabled there) or the local defaults from config.py."""
import logging
import config
import supabase_io

log = logging.getLogger("settings")


def load_settings():
    """Returns a settings dict, or None if the agent is paused in the dashboard."""
    if supabase_io.configured():
        row = supabase_io.get_agent(config.AGENT_ID)
        if row is not None:
            if not row.get("enabled", True):
                log.info("Agent is paused in the dashboard - skipping this run.")
                return None
            merged = {**config.DEFAULT_SETTINGS, **(row.get("settings") or {})}
            log.info("Loaded settings from the dashboard (agent %s).", config.AGENT_ID)
            return merged
        log.warning("Supabase configured but agent row not found - using local defaults.")
    else:
        log.info("Supabase not configured - using local default settings.")
    return dict(config.DEFAULT_SETTINGS)
