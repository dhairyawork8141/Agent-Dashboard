# CAD Illustrators — Virtual Worlds Growth System

Everything for the Virtual Worlds outreach campaign and the agent system, in one place.

## What's in this bundle

### 1. The campaign
- **CAD_Illustrators_VW_Campaign_Tracker.xlsx**
  Your lead tracker. 5 tabs: Dashboard, Leads (with 9 verified owner-level contacts already
  enriched via Apollo), Lead Sources, Email Templates, Deliverability Checklist.

### 2. The sending domain (already done — kept for reference)
- **cadillustrator.com.zone.txt**
  The Cloudflare DNS zone file for the cold-email domain. SPF, DKIM, DMARC all verified
  passing. You won't need this again unless you rebuild the DNS.

### 3. The agent (finds & prepares leads automatically)
- **vw-job-agent/** (also zipped as vw-job-agent.zip)
  Python agent that watches Adzuna + Reed for showrooms hiring Virtual Worlds designers,
  scores them HOT/WARM/WATCH, optionally has Claude draft an opener, and writes finds to
  your dashboard. Runs free on GitHub Actions, 3×/day. Full setup in its own README.

### 4. The dashboard (your control panel)
- **agent-dashboard.html**
  Single-file dashboard to see and control your agents. Opens in demo mode now; add your
  Supabase keys to the CONFIG block and deploy to go live with login + real data.
- **agent-dashboard-schema.sql**
  Run this once in Supabase → SQL Editor to create the database the dashboard and agent
  share (tables, security, and your seeded Virtual Worlds agent).

## Setup order (full walkthrough)
1. **Supabase** — create project, run `agent-dashboard-schema.sql`, add your login user,
   copy your URL + anon key + service_role key + the agent's id.
2. **Dashboard** — paste URL + anon key into `agent-dashboard.html`, rename to index.html,
   deploy to Cloudflare Pages.
3. **API keys** — get free Adzuna + Reed keys.
4. **Agent** — push `vw-job-agent/` to a private GitHub repo, add the keys + Supabase
   service_role key + AGENT_ID as Actions secrets, run the workflow.
5. **Verify** — refresh the dashboard; the agent's finds appear there.

## How the campaign and the system fit together
The **agent + dashboard** FIND and PREPARE leads (with drafted openers).
**Apollo + your warmed cadillustrator.com mailbox** SEND to them.
Handoff: agent surfaces a hot lead → enrich the decision-maker's email in Apollo →
add to the "VW Showrooms — First Project Free" sequence → send from the warmed domain.

Reminder: the sending domain is still in its 2–3 week warm-up before the cold campaign
launches. Use that window to let the agent build your pipeline.
