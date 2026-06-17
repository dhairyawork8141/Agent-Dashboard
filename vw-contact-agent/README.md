# VW Contact Finder (agent #2)

Turns the **companies** agent #1 finds into **people you can email**. For each HOT/WARM
showroom lead in the dashboard that has no contact yet, it asks Apollo for the senior
decision-maker (Owner / MD / Director / Showroom Manager…), reveals their work email,
and writes it back onto the lead — closing the gap between "found a showroom" and
"can pitch the owner".

## What it does, each run
1. **Reads** the dashboard's `leads` table for the highest-scoring leads where
   `contact_email is null` (recruiters skipped, target tiers only).
2. **Finds** the company in Apollo, then the best-matching decision-maker in the UK.
3. **Reveals** that person's work email (and optionally phone).
4. **Writes** `contact_name / title / email / phone / linkedin` back onto the lead.

## Credit safety
- `max_per_run` (default **10**) caps how many reveals can happen in one run.
- Only the **single best** person per showroom is revealed (1 lead credit each).
- Company + people **searches don't spend** lead credits; only the reveal does.
- A lead that already has `contact_email` is never re-enriched.

## Setup
### 1. Migrate the database (once)
Run [`../agent-dashboard-schema-v2.sql`](../agent-dashboard-schema-v2.sql) in
Supabase → SQL Editor. It adds the contact columns and seeds this agent's row
(fixed id `b7e6d5c4-3a2b-4c1d-9e8f-0a1b2c3d4e5f`).

### 2. Get your Apollo API key
Apollo → **Settings → Integrations → API** → create / copy the key.

### 3. Run locally first
```bash
pip install -r requirements.txt
cp .env.example .env
# paste APOLLO_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY (AGENT_ID is pre-filled)
python main.py
```
Watch the log: it prints each `Enriched 'Showroom' -> Name, Title <email>` line, then
open the dashboard — the contact columns are now populated.

### 4. Put it on autopilot
Add `APOLLO_API_KEY` to the repo's Actions secrets (you already have `SUPABASE_URL`
and `SUPABASE_SERVICE_KEY`). The workflow
[`../.github/workflows/contact-agent.yml`](../.github/workflows/contact-agent.yml)
runs it 8am / 2pm / 7pm UTC, Mon–Sat — about an hour after the job watcher, so fresh
leads get a contact the same day.

## Tuning (in the dashboard `agents` row → settings)
- `max_per_run` — raise once you trust it and your credit balance allows.
- `tiers` — which lead tiers to enrich (default HOT + WARM).
- `titles` — which seniorities to target.
- `reveal_phone` — set `true` to also spend a direct-dial credit per contact.

## Files
```
vw-contact-agent/
├── main.py          # orchestrates a run
├── config.py        # credentials + default settings
├── apollo.py        # Apollo company -> person -> reveal
├── supabase_io.py   # reads leads, writes contacts back
├── requirements.txt
├── .env.example
└── README.md
```
