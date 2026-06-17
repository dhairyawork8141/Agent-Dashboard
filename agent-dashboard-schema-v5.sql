-- ============================================================
--  CAD Illustrators — Agent Control Desk : MIGRATION v5
--  Seeds agent #3: the New-Showroom Finder (Companies House).
--  Safe to run more than once (idempotent).
--  Run in Supabase → SQL Editor → New query (after v1–v4).
-- ============================================================

insert into public.agents (id, name, type, enabled, schedule_cron, settings)
values (
  'c8f7e6d5-4b3a-2c1d-0e9f-1a2b3c4d5e6f',
  'VW New-Showroom Finder',
  'showroom_watcher',
  true,
  '0 6 * * 1-6',                         -- 6am UTC, Mon–Sat
  jsonb_build_object(
    'name_keywords', jsonb_build_array(
      'kitchen','kitchens','bathroom','bathrooms','bedroom','bedrooms',
      'interiors','kbb','tiles','worktops','fitted furniture'),
    'incorporated_within_days', 45,
    'company_status', 'active',
    'max_per_run', 25,
    'use_brain', true,
    'min_score', 50,
    'sic_codes', jsonb_build_array()       -- empty = name-keyword search only
  )
)
on conflict (id) do nothing;
