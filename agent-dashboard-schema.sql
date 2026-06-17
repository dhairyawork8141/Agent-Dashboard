-- ============================================================
--  CAD Illustrators — Agent Control Desk
--  Supabase schema. Run this in Supabase → SQL Editor → New query.
-- ============================================================

-- 1. AGENTS — one row per agent. The dashboard edits these; the Python
--    worker reads its row to know what to do.
create table if not exists public.agents (
  id              uuid primary key default gen_random_uuid(),
  name            text not null,
  type            text not null default 'job_watcher',
  enabled         boolean not null default true,
  schedule_cron   text default '0 7,13,18 * * 1-6',
  settings        jsonb not null default '{}'::jsonb,
  last_run_at     timestamptz,
  last_run_status text,
  created_at      timestamptz not null default now()
);

-- 2. LEADS — everything an agent finds. The worker upserts on external_key
--    so the same posting is never inserted twice.
create table if not exists public.leads (
  id                  uuid primary key default gen_random_uuid(),
  agent_id            uuid references public.agents(id) on delete cascade,
  external_key        text unique,
  found_at            timestamptz not null default now(),
  tier                text,
  score               int,
  title               text,
  company             text,
  showroom_name       text,
  location            text,
  salary              text,
  is_recruiter        boolean,
  decision_maker_hint text,
  opening_line        text,
  url                 text,
  source              text,
  matched_on          text,
  status              text not null default 'New'
);

create index if not exists leads_agent_idx on public.leads (agent_id);
create index if not exists leads_found_idx on public.leads (found_at desc);

-- 3. RUNS — a short log of each execution (optional but handy).
create table if not exists public.agent_runs (
  id          uuid primary key default gen_random_uuid(),
  agent_id    uuid references public.agents(id) on delete cascade,
  ran_at      timestamptz not null default now(),
  status      text,
  found_count int default 0,
  note        text
);

-- ------------------------------------------------------------
--  Row Level Security
--  Dashboard uses the ANON key + your login (subject to RLS).
--  The Python worker uses the SERVICE ROLE key (bypasses RLS).
--  Policy below = any logged-in user has full access. Since this is
--  your personal tool that's fine; tighten to owner-based later if needed.
-- ------------------------------------------------------------
alter table public.agents     enable row level security;
alter table public.leads      enable row level security;
alter table public.agent_runs enable row level security;

create policy "authenticated full access - agents"
  on public.agents     for all to authenticated using (true) with check (true);
create policy "authenticated full access - leads"
  on public.leads      for all to authenticated using (true) with check (true);
create policy "authenticated full access - runs"
  on public.agent_runs for all to authenticated using (true) with check (true);

-- ------------------------------------------------------------
--  Seed your first agent: the Virtual Worlds job watcher.
--  These settings mirror config.py in the Python agent.
-- ------------------------------------------------------------
insert into public.agents (name, type, enabled, schedule_cron, settings)
values (
  'Virtual Worlds Job Watch',
  'job_watcher',
  true,
  '0 7,13,18 * * 1-6',
  jsonb_build_object(
    'countries', jsonb_build_array('gb','ie'),
    'max_days_old', 3,
    'enrich_with_claude', false,
    'send_email', false,
    'searches', jsonb_build_array(
      jsonb_build_object('label','Virtual Worlds (exact)','phrase','virtual worlds'),
      jsonb_build_object('label','Cyncly','phrase','cyncly'),
      jsonb_build_object('label','Winner Design','phrase','winner design'),
      jsonb_build_object('label','Compusoft','phrase','compusoft'),
      jsonb_build_object('label','Bathroom CAD designer','phrase','bathroom designer','extra','CAD'),
      jsonb_build_object('label','Kitchen CAD designer','phrase','kitchen designer','extra','CAD')
    ),
    'hot_terms',  jsonb_build_array('virtual worlds','virtual world','vw 4d','4d theatre'),
    'warm_terms', jsonb_build_array('winner design','winner flex','cyncly','compusoft'),
    'watch_terms',jsonb_build_array('cad','kbb','bathroom design','kitchen design','autocad','sketchup')
  )
)
on conflict do nothing;

-- Create your login: Supabase → Authentication → Users → Add user
-- (enter your email + a password). That's the password the dashboard asks for.
