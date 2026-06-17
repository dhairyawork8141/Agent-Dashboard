# Virtual Worlds Job-Watch Agent

An always-on agent that watches UK & Ireland job boards for showrooms hiring **Virtual
Worlds** (and Winner / Cyncly) designers, scores each one by how good a CAD Illustrators
lead it is, optionally has Claude name the showroom and draft your opening line, and emails
you a digest. A showroom advertising for a VW designer is broadcasting *pain + budget +
urgency* at the same time — this catches every one of those, the day it's posted.

## What it does, each run
1. **Fetches** new postings from Adzuna (UK + Ireland) and Reed using their official APIs.
2. **De-duplicates** against everything it has seen before (stored in `state/seen_jobs.json`).
3. **Scores & tiers** each posting:
   - 🔥 **HOT** — advert names Virtual Worlds
   - 🟡 **WARM** — names Winner / Cyncly / Compusoft
   - 👀 **WATCH** — generic CAD bathroom/kitchen designer
   - bonus points for a listed salary (real budget) and for direct employers over recruiters
4. **Enriches** (optional) — Claude reads the advert, identifies the actual hiring showroom
   (handy when a recruiter hides it), and writes a one-line personalised email opener.
5. **Notifies** — appends every find to `state/new_jobs.csv` and emails you an HTML digest.

> **Sourcing note:** this uses official **APIs** (Adzuna, Reed), not scraping, so it's
> reliable and within each site's terms. LinkedIn's "a designer just left this showroom"
> signal is gold but LinkedIn prohibits automated scraping — get that from Sales Navigator
> alerts and review by hand. Don't point a scraper at LinkedIn.

---

## Setup (about 15 minutes)

### 1. Get the two free API keys
- **Adzuna:** https://developer.adzuna.com → register → you get an **App ID** and **App Key**.
- **Reed:** https://www.reed.co.uk/developers → register → you get one **API key**.

### 2. Run it locally first (to see it work)
```bash
pip install -r requirements.txt
cp .env.example .env
# open .env, paste your Adzuna + Reed keys, save
python main.py
```
Check `state/new_jobs.csv` — your first batch of leads should be in it.

### 3. Put it on autopilot with GitHub Actions (free, no server)
1. Create a new **private** GitHub repo and push these files to it.
2. In the repo: **Settings → Secrets and variables → Actions**.
   - Add **Secrets** (sensitive): `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `REED_API_KEY`,
     and (if using email) `SMTP_USER`, `SMTP_PASS`, `ALERT_TO`,
     and (if using enrichment) `ANTHROPIC_API_KEY`.
   - Add **Variables** (non-sensitive toggles): `COUNTRIES` = `gb,ie`,
     `MAX_DAYS_OLD` = `3`, `ENRICH_WITH_CLAUDE` = `false`, `SEND_EMAIL` = `false`,
     `SMTP_HOST` = `smtp.office365.com`, `SMTP_PORT` = `587`.
3. Go to the **Actions** tab → **VW Job Watch** → **Run workflow** to test it now.
4. After that it runs automatically on the schedule in `.github/workflows/job-agent.yml`
   (default: 7am / 1pm / 6pm UTC, Mon–Sat). Edit the `cron` line to change times.

The agent commits its updated memory (`state/`) back to the repo after each run, so it
never alerts you about the same job twice.

> **Prefer your Hetzner VPS instead of Actions?** Same code. Just add a crontab line:
> `0 7,13,18 * * 1-6 cd /path/to/vw-job-agent && /usr/bin/python3 main.py` and put your
> values in a `.env` file in the folder. GitHub Actions is recommended only because it's
> zero-maintenance.

---

## Turning on the extras

### Claude enrichment (showroom name + drafted opener)
Set `ENRICH_WITH_CLAUDE=true` and add `ANTHROPIC_API_KEY`. Uses Haiku by default (cheap —
fractions of a penny per advert). Each digest entry then comes with the likely showroom and
a ready-to-send first line.

### Email digests
Set `SEND_EMAIL=true` and fill the SMTP values. **Microsoft 365 note:** you must enable
**Authenticated SMTP** for the sending mailbox — Admin centre → Active users → (the user) →
Mail → *Manage email apps* → tick **Authenticated SMTP**. If the mailbox has MFA, generate
an **app password** and use that as `SMTP_PASS`.
*Tip:* you can send the digest from any mailbox. Sending a couple of internal emails a day
from `dhairya@cadillustrator.com` is harmless and even helps warm the domain, but the digest
is just for you — it has nothing to do with the cold campaign volume.

---

## Tuning
- **What it searches:** edit `SEARCHES` in `config.py`.
- **How it scores/tiers:** edit the keyword lists in `scorer.py` — this is the dial you'll
  touch most as you learn what converts.
- **How often it runs:** edit the `cron` schedule in the workflow file.

## How this plugs into the rest of the campaign
`new_jobs.csv` is your renewable top-of-funnel. Workflow: agent surfaces a HOT lead →
(optional) Claude has already drafted the opener → drop it into the campaign tracker → run
it through Apollo (search → enrich the decision-maker's email → add to the *VW Showrooms —
First Project Free* sequence) → send from your warmed `cadillustrator.com` mailbox.

## Files
```
vw-job-agent/
├── main.py            # orchestrates a run
├── config.py          # all settings + the search list
├── sources.py         # Adzuna + Reed API clients
├── scorer.py          # tier + fit scoring  (tune me)
├── enrich.py          # optional Claude enrichment
├── notify.py          # CSV log + HTML email digest
├── store.py           # remembers what it's already seen
├── requirements.txt
├── .env.example       # copy to .env for local runs
├── .gitignore
└── .github/workflows/job-agent.yml   # the scheduler
```

## A couple of honest caveats
- I couldn't run this live in the environment it was written in (no network there), so do
  the **manual "Run workflow"** first and glance at the log. If a field ever comes back
  empty, check the current Adzuna/Reed API docs — these clients are written to fail soft
  (one source erroring won't stop the others).
- Free API tiers have rate limits. Three runs a day across a handful of searches sits well
  inside them; if you add many more searches, space the runs out.
