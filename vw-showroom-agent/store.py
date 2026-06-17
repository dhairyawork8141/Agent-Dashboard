"""Dedup memory: remembers which companies we've already processed so they aren't
re-judged/re-written on every run. The GitHub Actions workflow commits this file back
to the repo after each run (like the job agent's seen_jobs.json)."""
import json
import os

STATE_FILE = os.getenv("SEEN_FILE", "state/seen_companies.json")


def _load() -> set:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return set(json.load(f).get("seen_keys", []))
    except Exception:
        return set()


def filter_new(leads: list[dict]) -> list[dict]:
    seen = _load()
    return [l for l in leads if l.get("key") not in seen]


def commit(leads: list[dict]) -> None:
    seen = _load()
    seen.update(l["key"] for l in leads if l.get("key"))
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"seen_keys": sorted(seen)}, f, indent=2)
