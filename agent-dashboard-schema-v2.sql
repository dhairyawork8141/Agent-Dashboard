-- ============================================================
--  CAD Illustrators — Agent Control Desk : MIGRATION v2
--  Adds contact columns to LEADS and seeds the VW Contact Finder agent.
--  Safe to run more than once (idempotent).
--  Run in Supabase → SQL Editor → New query.
-- ============================================================

-- 1. Contact columns the Apollo contact-finder writes back onto each lead.
alter table public.leads add column if not exists contact_name     text;
alter table public.leads add column if not exists contact_title    text;
alter table public.leads add column if not exists contact_email    text;
alter table public.leads add column if not exists contact_phone    text;
alter table public.leads add column if not exists contact_linkedin text;
alter table public.leads add column if not exists enriched_at      timestamptz;

-- Handy for the contact-finder's "leads still needing a contact" query.
create index if not exists leads_needs_contact_idx
  on public.leads (score desc) where contact_email is null;

-- 2. Seed agent #2 with a FIXED id so the worker can reference it directly.
--    (Agent ids are not secret — the worker still needs the SERVICE ROLE key to write.)
insert into public.agents (id, name, type, enabled, schedule_cron, settings)
values (
  'b7e6d5c4-3a2b-4c1d-9e8f-0a1b2c3d4e5f',
  'VW Contact Finder',
  'contact_finder',
  true,
  '0 8,14,19 * * 1-6',                 -- runs ~1h after the job watcher, Mon–Sat
  jsonb_build_object(
    'max_per_run', 10,                 -- credit guardrail: at most N reveals per run
    'tiers', jsonb_build_array('HOT - Virtual Worlds','WARM - Winner/Cyncly'),
    'skip_recruiters', true,
    'reveal_phone', false,             -- leave off to save direct-dial credits
    'locations', jsonb_build_array('United Kingdom'),
    'titles', jsonb_build_array(
      'Owner','Founder','Co-Founder','Managing Director','Director',
      'Proprietor','Partner','Showroom Manager','General Manager','Sales Director'
    )
  )
)
on conflict (id) do nothing;
