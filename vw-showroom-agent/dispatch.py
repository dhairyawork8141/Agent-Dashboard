"""Tiny helper so one agent can trigger the next one immediately (Project Hermes chaining):
showroom/job -> contact (enrich new HOT now) -> draft-requested (draft them now). Uses the
Actions-provided GITHUB_TOKEN (workflow needs `permissions: actions: write`). Fail-soft."""
import logging
import os

import requests

log = logging.getLogger("dispatch")
_REPO = os.getenv("GITHUB_REPOSITORY", "dhairyawork8141/Agent-Dashboard")
_TOKEN = os.getenv("GH_DISPATCH_TOKEN") or os.getenv("GITHUB_TOKEN", "")


def fire(workflow_file: str) -> None:
    """Trigger a workflow_dispatch run of another agent now. No-op if no token."""
    if not _TOKEN:
        return
    try:
        r = requests.post(
            f"https://api.github.com/repos/{_REPO}/actions/workflows/{workflow_file}/dispatches",
            headers={"Authorization": f"Bearer {_TOKEN}", "Accept": "application/vnd.github+json",
                     "User-Agent": "hermes-agent"},
            json={"ref": "main"}, timeout=20)
        if r.status_code == 204:
            log.info("Dispatched %s", workflow_file)
        else:
            log.warning("Dispatch %s failed: %s %s", workflow_file, r.status_code, r.text[:120])
    except Exception as e:
        log.warning("Dispatch error: %s", e)
