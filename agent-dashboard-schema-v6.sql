-- ============================================================
--  CAD Illustrators — Agent Control Desk : MIGRATION v6
--  Adds a business-type CATEGORY to leads (for the Showroom Lists tabs).
--  Safe to run more than once (idempotent).
--  Run in Supabase → SQL Editor → New query (after v1–v5).
-- ============================================================

-- Category = business TYPE, set by the showroom brain. One of:
--   kitchen | bathroom | kbb | bedroom | fitter | interior | other
-- (Independent of tier, which is HOT/WARM/WATCH by recency.)
alter table public.leads add column if not exists category text;
create index if not exists leads_category_idx on public.leads (category);
