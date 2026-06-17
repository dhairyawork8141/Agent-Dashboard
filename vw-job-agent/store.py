"""Remembers which postings we've already alerted on, in a human-readable JSON file so
you can open it and see exactly what the agent has found over time. At this scale a flat
file is plenty - no database needed."""
import json
import os
from datetime import datetime, timezone

STATE_FILE = os.getenv("STATE_FILE", "state/seen_jobs.json")


def _load() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"seen_keys": [], "archive": []}


def _save(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def filter_new(jobs: list[dict]) -> list[dict]:
    seen = set(_load()["seen_keys"])
    return [j for j in jobs if j["key"] not in seen]


def commit(new_jobs: list[dict]) -> None:
    state = _load()
    seen = set(state["seen_keys"])
    stamp = datetime.now(timezone.utc).isoformat()
    for j in new_jobs:
        seen.add(j["key"])
        state["archive"].append({
            "found_at": stamp,
            "key": j["key"],
            "title": j.get("title"),
            "company": j.get("company"),
            "tier": j.get("tier"),
            "url": j.get("url"),
        })
    state["seen_keys"] = sorted(seen)
    _save(state)
