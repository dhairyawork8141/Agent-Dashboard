-- ============================================================
--  CAD Illustrators — Agent Control Desk : MIGRATION v8
--  THE DATACENTER. One row for EVERY candidate Hermes ever evaluates — kept OR
--  rejected, right OR wrong — across every source. This is the raw firehose that
--  lets Hermes (and the Reports tab) measure which source/strategy actually
--  produces HOT leads, and drive the "10 proper HOT leads/day" goal.
--
--  `leads` stays the curated working set (what you act on); `lead_candidates` is
--  the full memory of everything seen, so nothing is ever silently dropped.
--
--  Safe to run more than once (idempotent). Run in Supabase → SQL Editor (after v1–v7).
-- ============================================================

create table if not exists public.lead_candidates (
  id                 uuid primary key default gen_random_uuid(),
  source             text not null,                 -- 'companies_house','adzuna','reed','jooble','jsearch','osm','serper','yell','houzz',...
  external_key       text not null,                 -- stable dedup id (company number / job id / osm id)
  company            text,
  location           text,
  country            text default 'United Kingdom', -- UK-only by policy
  discovered_at      timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  -- Funnel stage this candidate has reached (lets us compute conversion per source):
  -- discovered → prefiltered → judged → enriched → drafted → sent → replied
  stage              text default 'discovered',
  decision           text,                          -- 'kept' | 'rejected'
  reject_reason      text,                          -- why it was dropped (keyword / brain reason)
  fit                boolean,                        -- brain verdict
  category           text,                          -- kitchen|bathroom|kbb|bedroom|fitter|interior|other
  tier               text,                          -- HOT / WARM / WATCH (full label)
  score              int,
  -- Enrichment outcome (so we can see which sources give findable contacts):
  contact_found      boolean,
  contact_confidence int,                           -- 0-100 from web_search_enrich
  email_valid        boolean,                        -- MX check result
  -- Outreach outcome (so we can see which sources actually convert):
  outcome            text,                          -- pending|approved|sent|bounced|replied|user_rejected
  lead_id            uuid references public.leads(id) on delete set null,
  raw                jsonb,                          -- the full original payload — store everything
  unique (source, external_key)
);

create index if not exists lead_candidates_source_idx     on public.lead_candidates (source);
create index if not exists lead_candidates_discovered_idx  on public.lead_candidates (discovered_at);
create index if not exists lead_candidates_tier_idx        on public.lead_candidates (tier);
create index if not exists lead_candidates_stage_idx       on public.lead_candidates (stage);
create index if not exists lead_candidates_outcome_idx     on public.lead_candidates (outcome);

-- Keep updated_at fresh on every change.
create or replace function public.touch_lead_candidates() returns trigger as $$
begin new.updated_at = now(); return new; end; $$ language plpgsql;
drop trigger if exists trg_touch_lead_candidates on public.lead_candidates;
create trigger trg_touch_lead_candidates before update on public.lead_candidates
  for each row execute function public.touch_lead_candidates();

-- Strategy scoreboard: per-source funnel, newest activity first. The Reports tab and
-- Hermes read this to see "what's working and what's not".
create or replace view public.source_performance as
select
  source,
  count(*)                                                   as discovered,
  count(*) filter (where decision = 'kept')                  as kept,
  count(*) filter (where tier like 'HOT%')                   as hot,
  count(*) filter (where contact_found)                      as contacted,
  count(*) filter (where outcome = 'sent')                   as sent,
  count(*) filter (where outcome = 'replied')                as replied,
  round(100.0 * count(*) filter (where tier like 'HOT%')
        / nullif(count(*), 0), 1)                            as hot_rate_pct,
  max(discovered_at)                                         as last_seen
from public.lead_candidates
group by source
order by hot desc;

-- Today's HOT count (UTC) — the KPI Hermes drives toward (target: 10/day).
create or replace view public.hot_today as
select count(*) as hot_today
from public.lead_candidates
where tier like 'HOT%' and discovered_at >= date_trunc('day', now() at time zone 'utc');

-- ------------------------------------------------------------
--  Row Level Security — same convention as the other tables
--  (any logged-in user has full access; agents use the service key, bypassing RLS).
-- ------------------------------------------------------------
alter table public.lead_candidates enable row level security;
create policy "authenticated full access - lead_candidates"
  on public.lead_candidates for all to authenticated using (true) with check (true);
