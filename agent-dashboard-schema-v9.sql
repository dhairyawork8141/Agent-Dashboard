-- ============================================================
--  CAD Illustrators — Agent Control Desk : MIGRATION v9
--  Columns for the outreach "close the loop" upgrade: reply detection, autonomous
--  follow-ups, and unsubscribe/suppression compliance.
--  Safe to run more than once (idempotent). Run in Supabase → SQL Editor (after v1–v8).
-- ============================================================

alter table public.leads add column if not exists replied_at      timestamptz;  -- set when a reply is detected
alter table public.leads add column if not exists unsubscribed    boolean default false;  -- opt-out / suppression
alter table public.leads add column if not exists follow_up_count int default 0;  -- how many follow-ups sent
alter table public.leads add column if not exists last_followup_at timestamptz;  -- when the last follow-up went out
alter table public.leads add column if not exists reply_likelihood int;          -- 0-100, for ranking the queue

create index if not exists leads_unsubscribed_idx on public.leads (unsubscribed);
create index if not exists leads_replied_idx      on public.leads (replied_at);
