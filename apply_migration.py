"""Apply a .sql migration to Supabase WITHOUT the SQL Editor (Project Hermes helper).

DDL (create table / add column) can't go through the service key / PostgREST, so migrations
normally have to be pasted into the Supabase SQL Editor by hand. This runs them via the
Supabase **Management API** instead, so applying v8/v9/... is one command.

One-time setup:
  1. Create a personal access token: https://supabase.com/dashboard/account/tokens
  2. Set it in your environment (or .env):  SUPABASE_ACCESS_TOKEN=sbp_xxx
     (project ref is auto-read from SUPABASE_URL, or set SUPABASE_PROJECT_REF)

Usage:
  python apply_migration.py agent-dashboard-schema-v8.sql
  python apply_migration.py agent-dashboard-schema-v8.sql agent-dashboard-schema-v9.sql
"""
import os
import re
import sys

import requests

try:
    from dotenv import load_dotenv
    # Load whichever agent .env carries the Supabase vars (any is fine — same project).
    for env_path in ("vw-contact-agent/.env", "vw-job-agent/.env", "vw-showroom-agent/.env", ".env"):
        if os.path.isfile(env_path):
            load_dotenv(env_path, override=False)
except Exception:
    pass

_API = "https://api.supabase.com/v1/projects/{ref}/database/query"


def _project_ref() -> str | None:
    ref = os.getenv("SUPABASE_PROJECT_REF", "").strip()
    if ref:
        return ref
    url = os.getenv("SUPABASE_URL", "")
    m = re.match(r"https://([a-z0-9]+)\.supabase\.co", url.strip())
    return m.group(1) if m else None


def apply(path: str, ref: str, token: str) -> bool:
    with open(path, encoding="utf-8") as f:
        sql = f.read()
    r = requests.post(
        _API.format(ref=ref),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"query": sql}, timeout=60)
    if r.status_code < 300:
        print(f"  OK  {path}")
        return True
    print(f"  FAILED  {path}  [{r.status_code}] {r.text[:300]}")
    return False


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python apply_migration.py <file.sql> [more.sql ...]")
        return 2
    token = os.getenv("SUPABASE_ACCESS_TOKEN", "").strip()
    ref = _project_ref()
    if not token:
        print("ERROR: set SUPABASE_ACCESS_TOKEN (create one at "
              "https://supabase.com/dashboard/account/tokens)")
        return 1
    if not ref:
        print("ERROR: could not determine project ref (set SUPABASE_PROJECT_REF "
              "or SUPABASE_URL).")
        return 1
    print(f"Applying {len(argv)} migration(s) to project {ref} ...")
    ok = all(apply(p, ref, token) for p in argv)
    print("Done." if ok else "Finished with errors.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
