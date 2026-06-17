# VW New-Showroom Finder (agent #3)

Finds **newly-registered UK KBB / interior-design businesses** via the free
[Companies House API](https://developer.company-information.service.gov.uk/) and writes
them to the dashboard as leads — a new lead **source** beyond job ads (reaches showrooms
that aren't hiring). Found companies flow into the existing contact-finder (agent #2),
which enriches them and drafts outreach.

## How it works
`companies_house.fetch_all()` (advanced-search: company name contains a KBB keyword +
incorporated in the last N days) → `store.filter_new()` (dedup vs `state/seen_companies.json`)
→ `brain.classify()` (Groq judges genuine KBB/interior fit, sets tier + score) →
`supabase_io.upsert_leads()` → `store.commit()`.

## Run locally
```bash
cd vw-showroom-agent
cp .env.example .env      # fill in keys
python -m pip install -r requirements.txt
python main.py
```

## Config lives in the dashboard
Like the other agents, behaviour is read from the `agents` row's `settings` jsonb
(`name_keywords`, `incorporated_within_days`, `max_per_run`, `min_score`, `use_brain`,
optional `sic_codes`), falling back to `config.DEFAULT_SETTINGS`.

## Notes
- New leads are tagged `HOT/WARM/WATCH - New showroom`. To have agent #2 enrich them,
  add those tiers to the contact-finder's `tiers` setting in the dashboard.
- `max_per_run` caps brain calls + writes per run (free-tier friendly).
