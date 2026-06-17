-- ============================================================
--  CAD Illustrators — Agent Control Desk : MIGRATION v3
--  Adds the email draft + human-approval workflow to LEADS.
--  Safe to run more than once (idempotent).
--  Run in Supabase → SQL Editor → New query (after v1 and v2).
-- ============================================================

-- The contact-finder drafts an email (Groq brain) and parks it as 'pending'.
-- You review/edit/approve it in the dashboard; the sender then mails 'approved'
-- ones via Microsoft 365 and marks them 'sent'.
--
--   draft_status lifecycle:  none → pending → approved → sent
--                                              ↘ rejected   (you declined)
--                                              ↘ failed     (send error)
alter table public.leads add column if not exists draft_subject text;
alter table public.leads add column if not exists draft_body    text;
alter table public.leads add column if not exists draft_status  text not null default 'none';
alter table public.leads add column if not exists drafted_at    timestamptz;
alter table public.leads add column if not exists sent_at       timestamptz;

-- Fast lookups for the dashboard ("needs approval") and the sender ("ready to send").
create index if not exists leads_draft_status_idx on public.leads (draft_status);

-- RLS is already "authenticated full access" (see schema v1), so the logged-in
-- dashboard can update draft_status / draft_subject / draft_body for approval.
