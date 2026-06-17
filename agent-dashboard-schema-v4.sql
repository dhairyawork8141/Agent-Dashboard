-- ============================================================
--  CAD Illustrators — Agent Control Desk : MIGRATION v4
--  Adds website + social media columns to LEADS.
--  Safe to run more than once (idempotent).
--  Run in Supabase → SQL Editor → New query (after v1, v2, v3).
-- ============================================================

-- Company website and social media profiles discovered by the contact agent.
alter table public.leads add column if not exists website          text;
alter table public.leads add column if not exists social_facebook  text;
alter table public.leads add column if not exists social_instagram text;
alter table public.leads add column if not exists social_linkedin  text;
alter table public.leads add column if not exists social_twitter   text;
alter table public.leads add column if not exists social_youtube   text;
alter table public.leads add column if not exists social_tiktok    text;
alter table public.leads add column if not exists social_pinterest text;
alter table public.leads add column if not exists social_houzz     text;

-- RLS is already "authenticated full access" (see schema v1).
