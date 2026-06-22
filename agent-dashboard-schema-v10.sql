-- ============================================================
--  CAD Illustrators — Agent Control Desk : MIGRATION v10
--  New agent "skills": detect KBB design software a showroom uses (buying signal), and
--  track which email template was used (for A/B reply-rate learning).
--  Safe to run more than once (idempotent). Run in Supabase → SQL Editor (after v1–v9).
-- ============================================================

alter table public.leads add column if not exists tech_software text;  -- detected KBB software (Winner/Virtual Worlds/2020/...)
alter table public.leads add column if not exists template      text;  -- email template used (A/B reply-rate tracking)

create index if not exists leads_tech_software_idx on public.leads (tech_software);
create index if not exists leads_template_idx      on public.leads (template);
