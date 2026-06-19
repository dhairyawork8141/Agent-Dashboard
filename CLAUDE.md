# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A lead-gen + cold-outreach system for **CAD Illustrators** (an outsourced CAD/CGI studio serving **KBB** — kitchen, bedroom & bathroom — showrooms, fitters and interior designers). **Three independent Python agents + a sender + a single-file React dashboard**, all sharing one Supabase Postgres database:

- **`vw-job-agent/`** — watches job boards for showrooms hiring CAD/designers; an AI brain scores each as a lead.
- **`vw-showroom-agent/`** — finds UK KBB/interior businesses via the free **Companies House** API (a lead *source* beyond job ads); an AI brain tags each with a **category** + recency tier.
- **`vw-contact-agent/`** — enriches leads with a decision-maker contact (free web-scrape first, **Apollo only for HOT**), then **drafts a per-sector outreach email** for approval. Also runs the **sender** (`send_approved.py`).
- **`agent-dashboard.html`** — single-file React (CDN + Babel) control desk; sidebar sections **Overview · Job Leads · Showroom Lists · Connected · Reports · Account**.

**Pipeline:** find → judge (Groq brain) → enrich → draft (templates, AI-personalised) → **human approves in dashboard** → send via Microsoft 365 → lead moves to **Connected**. Nothing sends without approval.

## The one pattern that explains everything: settings live in the database

Each agent reads a row from the Supabase `agents` table whose `settings` (jsonb) column holds the live config. `config.py.DEFAULT_SETTINGS` (from env vars) is only the **fallback** for keys absent from the DB row (`load_settings()` returns `{**DEFAULT_SETTINGS, **db_row.settings}`). `settings.enabled == false` (the row's `enabled` column) pauses that agent.

**To change production behaviour, edit the DB row's `settings`** (dashboard or PATCH) — editing `config.py` only affects local runs/fresh fallbacks. **When PATCHing `settings` over REST, send the COMPLETE jsonb object** — PostgREST replaces the whole column, so a partial patch silently wipes the other keys (this has bitten the project; always GET-merge-PATCH the full object).

## Architecture

**Shared DB** — schema applied as migrations **v1→v7** (`agent-dashboard-schema.sql`, `-v2`…`-v7.sql`) in Supabase SQL Editor. Tables: `agents` (one row/agent), `leads` (upserted on `external_key`), `agent_runs` (log). Key `leads` columns added over time: `contact_*`/`enriched_at` (v2), `draft_subject/body/status/drafted_at/sent_at` (v3), `website`/`social_*` (v4), `category` (v6), `registered_at` (v7). Browser uses the **anon** key under RLS (policy = any authenticated user has full access); agents use the **service_role** key server-side.

**Job agent** (`vw-job-agent/main.py`): `sources.fetch_all` (Adzuna multi-country + Reed + Jooble + JSearch, all fail-soft, JSearch hard-capped) → `store.filter_new` (dedup vs `state/seen_jobs.json`) → `scorer.score_job` (cheap keyword pre-filter: `exclude_terms`, `role_terms`, `exclude_companies`, `min_score`) → **`brain.score`/`classify`** (Groq judges genuine KBB-designer fit) → `notify` (CSV + optional digest) → `supabase_io.upsert_leads` → `store.commit`.

**Showroom agent** (`vw-showroom-agent/main.py`): `companies_house.fetch_all_backfill` (advanced-search by name keyword + KBB SIC codes, paginated, **all dates**) → `store.filter_new` (dedup vs `state/seen_companies.json`) → **shuffle** → process up to `max_per_run` → **`brain.classify`** (Groq, fit + `category` ∈ kitchen|bathroom|kbb|bedroom|fitter|interior|other) → tier is **deterministic by `registered_at`** (`brain.tier_from_registration`: ≤6mo HOT, ≤12mo WARM, else WATCH) → upsert. It's a **self-completing rolling backfill**: each daily run judges a fresh shuffled batch of unseen companies, so the historical backlog finishes over days AND new registrations are caught.

**Contact agent** (`vw-contact-agent/main.py`): `leads_needing_contact` (contact_email **AND** enriched_at both null, tier-filtered, recruiters skipped) → **web-scrape first** (`web_search_enrich`, free: domain-guess + scrape for email/phone/socials, junk domains like `.gov` rejected) → **Apollo only if tier ∈ `apollo_tiers`** (HOT) → write contact. Then if `draft_emails` and tier ∈ `draft_tiers` (HOT), **`draft.draft_email`** picks the per-sector template + lightly AI-personalises it → `draft_status='pending'`. It also processes **`draft_status='requested'`** leads (the dashboard "Draft email" button) regardless of tier.

**Drafting** (`vw-contact-agent/draft.py` + `templates/*.txt`): selects a fixed template — showroom by `category` (fitter/interior/bathroom) or recency for kitchen/kbb/bedroom; job by advertised role — fills `[First Name]`/`[Showroom Name]`/`[Your Name]`, then Groq (`DRAFT_MODEL`, 8B) lightly personalises the opening while **preserving offer/£100/URL/sign-off** (safety-checked; falls back to plain template if Groq is off or drops key content). **Edit the `.txt` files to change wording.**

**Sender** (`vw-contact-agent/send_approved.py`): sends `draft_status='approved'` leads via **M365 OAuth2 app-only XOAUTH2** SMTP → marks them `sent` (+ `sent_at`, status Contacted). Throttled: `SEND_DAILY_CAP` (30/day), `SEND_PER_RUN` (6), jittered `SEND_MIN_GAP_SECONDS` (45–90s) — cold-email warm-up.

**Dashboard** (`agent-dashboard.html`): sidebar nav; leads split by `leadSection` (showroom = showroom-agent or Companies House source). **Sent leads (`draft_status='sent'`) are excluded from the working lists and shown only under Connected.** The DraftPanel renders only under the "Needs approval" filter. Edits write through Supabase (anon key, logged-in user). **Three byte-identical copies must stay in sync: `agent-dashboard.html` (source), `dashboard/index.html`, root `index.html`** — Cloudflare serves root `index.html`.

**State/dedup:** `state/seen_jobs.json` (job) and `state/seen_companies.json` (showroom) are each agent's memory; the GitHub Actions workflow commits them back after each run. Rebuilding `seen_companies.json` to only the leads actually in the DB forces re-processing of skipped companies.

## AI brain (Groq) — free, no card

Both lead-judging and email personalisation use **Groq** (`GROQ_API_KEY`, repo secret). Two models, different free limits:
- `llama-3.3-70b-versatile` (`GROQ_MODEL`): better, but ~**100K tokens/DAY** — the daily cap bites on big batches. Used for job-agent judging.
- `llama-3.1-8b-instant` (`DRAFT_MODEL`, and showroom `brain_model` in settings): ~**500K tokens/DAY**, generous — use for bulk/backfill judging and drafting.
A call returning a 429 / `None` is **fail-soft** (lead kept, category "other" / plain template). **Do NOT add Gemini/Google billing** (Gemini free tier returns `limit:0` here; user is firmly free-tier).

## Common commands

Run an agent locally (Windows; `python` may be `py`):
```bash
cd vw-job-agent          # or vw-contact-agent / vw-showroom-agent
cp .env.example .env     # fill in keys
python -m pip install -r requirements.txt
python main.py
```
No build step, no test suite. Quick validate: `python -m py_compile *.py`; dashboard sanity = bracket-balance the `<script type="text/babel">` block.

One-off maintenance scripts (run with env vars set; no Groq unless noted):
- `vw-showroom-agent/backfill_showrooms.py` — full Companies House backfill (Groq 8B).
- `vw-showroom-agent/fix_showroom_dates.py` — set name/`registered_at`/tier on existing showroom leads from Companies House (no Groq).
- `vw-contact-agent/enrich_hot_showrooms.py` — free web-scrape enrich HOT leads.
- `vw-contact-agent/draft_hot.py` — template-draft existing HOT leads into approval.

Deploy: **just `git push`** — Cloudflare Pages project `agent-dashboard` is git-connected and auto-deploys root `index.html` on push to `main`. (Keep the 3 dashboard copies in sync first.) The old `wrangler pages deploy` flow is superseded.

Trigger / inspect cloud agents:
```bash
gh workflow run showroom-agent.yml --repo dhairyawork8141/Agent-Dashboard
gh run list --repo dhairyawork8141/Agent-Dashboard --limit 8
```
Apply schema: run `agent-dashboard-schema.sql` then each `-v2`…`-v7.sql` in Supabase → SQL Editor (DDL can't go through the service key/PostgREST — must be the SQL Editor).

## Deployment

- **Agents:** GitHub Actions on cron, all **active**: `job-agent.yml` (7/13/18 UTC Mon–Sat), `contact-agent.yml` (8/14/19 Mon–Sat), `showroom-agent.yml` (6am Mon–Sat), `send-approved.yml` (hourly 8–16 UTC Mon–Fri). Credentials are GitHub **Secrets**. Agent ids are literals in the workflows: job `b3024c3a-…`, contact `b7e6d5c4-3a2b-4c1d-9e8f-0a1b2c3d4e5f`, showroom `c8f7e6d5-4b3a-2c1d-0e9f-1a2b3c4d5e6f`.
- **Dashboard:** Cloudflare Pages `agent-dashboard` (git-connected) → agent-dashboard-55d.pages.dev.
- Each agent folder `.gitignore` excludes `.env` + `*.log` — keep secrets/logs out of git.

## Conventions & gotchas

- **Settings PATCH = full jsonb object** (see above). Same trap applies to all three agents' rows.
- **Dashboard = 3 copies in sync** (source + `dashboard/index.html` + root `index.html`); Cloudflare serves root.
- **Schema changes need the Supabase SQL Editor** (service key/PostgREST do data, not DDL). Data inserts/updates (seeding an agent row, fixing leads) CAN go via the service key.
- **Apollo people search**: `POST /api/v1/mixed_people/api_search` (not `/mixed_people/search`, which 403s). Prefer company records with a domain (`accounts` over domain-less `organizations`). Apollo is **paid/credit-capped** — only HOT tiers (`apollo_tiers`) use it; web-scrape is the free default.
- **`enriched_at IS NULL` gates re-enrichment** — without it the contact agent re-tries (and re-spends Apollo on) leads where no email was found, every run.
- **Web-scraped contacts must domain-match the company** (`web_search_enrich._domain_matches_company`): the scraper/Serper otherwise grabs a *different* company's site/email (e.g. `suttonbuild.co.uk` for "INODESIGN"). Only emails/websites whose domain shares a distinctive company-name token are kept; free providers (gmail/outlook) and wixpress/sentry/gov are rejected. Better no contact than a wrong one (it's cold email). Clearing a lead's `contact_email`+`enriched_at` makes the (fixed) scraper re-attempt it next run.
- **M365 SMTP uses OAuth2 app-only** (XOAUTH2), NOT basic auth (tenant Security Defaults block basic). Needs the Entra app `SMTP.SendAsApp` + admin consent + an Exchange `New-ServicePrincipal`/`Add-MailboxPermission` granting send-as the mailbox (run by an Exchange/Global admin in interactive PowerShell — EXO v3 has no device-code flow). Client secret rotates (24mo) → update the `OAUTH_CLIENT_SECRET` secret.
- **Showroom tier is recency, not AI** (`tier_from_registration`); the brain only sets `fit` + `category`.
- **Free-tier discipline:** keep hard caps (`max_per_run`, `jsearch_max_per_run`, `SEND_DAILY_CAP`), flag any spend, prefer the 8B model for volume.
