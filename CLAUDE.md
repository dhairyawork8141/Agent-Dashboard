# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A lead-generation system for **CAD Illustrators** (an outsourced CAD/CGI studio serving kitchen & bathroom showrooms). Two independent Python agents plus a single-file web dashboard, all sharing one Supabase Postgres database:

- **`vw-job-agent/`** — watches job boards for showrooms hiring CAD/"Virtual Worlds" designers, scores each as a lead, writes them to the dashboard, optionally emails a digest.
- **`vw-contact-agent/`** — reads HOT/WARM leads the job agent found and enriches them with a decision-maker's contact (email/phone/LinkedIn) via the Apollo API.
- **`agent-dashboard.html`** — single-file React (CDN + Babel) control panel + leads view, deployed to Cloudflare Pages.

The job agent finds *companies*; the contact agent attaches *people*; the dashboard is where you review both. Cold outreach itself is done manually (Apollo sequences) — there is no auto-sender in this repo yet.

## The one pattern that explains everything: settings live in the database

Each agent's behaviour is **not** driven primarily by its `config.py`. It reads a row from the Supabase `agents` table whose `settings` (jsonb) column holds the live config — search terms, countries, scoring keywords, feature toggles, credit caps. `config.py.DEFAULT_SETTINGS` (populated from env vars) is only the **fallback** when a key is absent from the DB row.

- Job agent: `settings_loader.load_settings()` → `{**config.DEFAULT_SETTINGS, **db_row.settings}`.
- Contact agent: `supabase_io.load_settings()` does the same.
- A `settings.enabled == false` row pauses that agent.

**Consequence:** to change production behaviour, edit the DB row's `settings` (via the dashboard or a PATCH to Supabase) — editing `config.py` alone only affects local runs and fresh fallbacks. **When PATCHing `settings` over the REST API, send the COMPLETE jsonb object** — PostgREST replaces the whole column, so a partial `{"settings": {"send_email": true}}` silently wipes `searches`, `countries`, etc. (This has bitten the project before.)

## Architecture

**Shared database** (`agent-dashboard-schema.sql`, then `agent-dashboard-schema-v2.sql` migration): tables `agents` (one row per agent), `leads` (upserted on `external_key`; v2 adds `contact_*` columns), `agent_runs` (run log). Browser dashboard uses the **anon** key under RLS; agents use the **service_role** key server-side.

**Job agent run** (`vw-job-agent/main.py`):
`sources.fetch_all(settings)` → `store.filter_new()` (dedup against `state/seen_jobs.json`) → `scorer.score_job()` (tier HOT/WARM/WATCH + numeric score + recruiter detection) → `enrich.enrich()` (optional, Gemini) → `notify.notify()` (appends `state/new_jobs.csv` + optional HTML email) → `supabase_io.upsert_leads()` → `store.commit()`. If there are **no new postings it returns before `notify`**, so digests only fire on genuinely-new finds.

**Sources are plug-in and fail-soft** (`vw-job-agent/sources.py`): each `fetch_*` returns `[]` on any error or missing key, so one dead source never stops a run. `fetch_all` fans out per search × country. Active: Adzuna (multi-country), Reed (UK), Jooble (global), JSearch (Google-Jobs aggregator → LinkedIn/Indeed/Glassdoor, hard-capped by `jsearch_max_per_run`). Careerjet is coded but dormant (its API needs server-IP whitelisting, incompatible with GitHub Actions' rotating IPs). Add a new board by writing a `fetch_x` and wiring it into `fetch_all`.

**Contact agent run** (`vw-contact-agent/main.py`): pull leads where `contact_email is null` (tier-filtered, recruiters skipped, score-ordered) → `apollo.find_org()` → `apollo.find_person()` → `apollo.reveal()` → write contact back via `supabase_io.update_lead()`. Credit-safe: `max_per_run` cap, one reveal per lead, never re-enriches.

**State / dedup:** `vw-job-agent/state/seen_jobs.json` is the job agent's memory; the GitHub Actions workflow commits it back to the repo after each run so jobs aren't re-alerted. **Emptying it forces every current posting to be treated as new** (useful to force a digest for testing).

## Common commands

Run an agent locally (Windows; `python` may need to be `py` or `python3`):
```bash
cd vw-job-agent          # or vw-contact-agent
cp .env.example .env     # then fill in keys
python -m pip install -r requirements.txt
python main.py
```
There is no build step and no test suite.

Deploy the dashboard (source is `agent-dashboard.html`; the deployed copy is `dashboard/index.html`):
```bash
cp agent-dashboard.html dashboard/index.html      # after editing the CONFIG block (Supabase url + anon key)
wrangler pages deploy dashboard --project-name cad-dashboard --branch main
```

Trigger / inspect the cloud agents (GitHub Actions):
```bash
gh workflow run job-agent.yml --repo dhairyawork8141/Agent-Dashboard
gh workflow run contact-agent.yml --repo dhairyawork8141/Agent-Dashboard
gh run watch <run-id> --repo dhairyawork8141/Agent-Dashboard
```

Apply DB schema: run `agent-dashboard-schema.sql` then `agent-dashboard-schema-v2.sql` in Supabase → SQL Editor.

## Deployment

- **Agents:** GitHub Actions (`.github/workflows/job-agent.yml`, `contact-agent.yml`) on cron, Mon–Sat. All credentials are GitHub Actions **Secrets** (not committed). Agent ids: job watcher passes `AGENT_ID` from a secret; contact finder uses the fixed seeded id `b7e6d5c4-3a2b-4c1d-9e8f-0a1b2c3d4e5f` as a literal in its workflow.
- **Dashboard:** Cloudflare Pages project `cad-dashboard`.
- Each agent folder has its own `.gitignore` excluding `.env` — keep new secret-bearing files out of git the same way.

## Conventions & gotchas

- **Apollo people search** must call `POST /api/v1/mixed_people/api_search` (not `/mixed_people/search`, which 403s with API keys). Good company records often sit under `accounts` (have a domain) while `organizations` are domain-less stubs — prefer the one with a domain, and search people by domain over org id.
- **Credit/quota caps are deliberate** (`max_per_run`, `jsearch_max_per_run`): the user runs on free tiers — keep hard caps and flag any spend.
- **Enrichment is currently off** — Gemini's free tier returns `limit: 0` for this project. The `enrich.py` toggle lives in `settings`, not `config`.
- **Email digest** sends only when `settings.send_email` is true AND there are new leads AND SMTP creds are present; failures are caught and logged (`notify.send_email`). Sender mailbox needs Office 365 "Authenticated SMTP" enabled and must not be blocked by tenant security-defaults policy.
