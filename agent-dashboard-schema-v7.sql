-- ============================================================
--  CAD Illustrators — Agent Control Desk : MIGRATION v7
--  Stores a showroom's registration (incorporation) date so the dashboard can
--  show it and tier by recency (<=6mo HOT, 6-12mo WARM, >12mo WATCH).
--  Safe to run more than once (idempotent).
--  Run in Supabase → SQL Editor → New query (after v1–v6).
-- ============================================================

alter table public.leads add column if not exists registered_at date;
