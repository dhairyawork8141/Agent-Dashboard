// Cloudflare Pages Function — on-demand worker trigger (Project Hermes).
// POST /api/dispatch  { workflow: "draft"|"contact"|"showroom"|"job"|"replies", access_token }
// Lets the dashboard run an agent NOW (e.g. draft a clicked lead immediately) instead of
// waiting for the cron. Verifies the user's Supabase login; GitHub token stays server-side.

const SUPABASE_URL = "https://qwblxytpznslidwjoxvt.supabase.co";
const SUPABASE_ANON = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InF3Ymx4eXRwem5zbGlkd2pveHZ0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODE2NjE0ODksImV4cCI6MjA5NzIzNzQ4OX0.e0_rcgEY8xY8_AEX3xaKeR1Zxu7TbV2RmXODkl9Wxtc";
const GITHUB_REPO = "dhairyawork8141/Agent-Dashboard";
const WORKFLOWS = {
  draft: "draft-requested.yml", contact: "contact-agent.yml",
  showroom: "showroom-agent.yml", job: "job-agent.yml", replies: "watch-replies.yml",
};
const cors = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type" };

export async function onRequestOptions() { return new Response(null, { headers: cors }); }

export async function onRequestPost({ request, env }) {
  const json = (o, s = 200) => new Response(JSON.stringify(o), { status: s, headers: { ...cors, "Content-Type": "application/json" } });
  try {
    const body = await request.json();
    const who = await fetch(`${SUPABASE_URL}/auth/v1/user`, {
      headers: { apikey: SUPABASE_ANON, Authorization: `Bearer ${body.access_token || ""}` } });
    if (!who.ok) return json({ error: "not authenticated" }, 401);
    const wf = WORKFLOWS[body.workflow];
    if (!wf) return json({ error: "unknown workflow" }, 400);
    if (!env.GITHUB_TOKEN) return json({ error: "GITHUB_TOKEN not set in Cloudflare" }, 500);
    const r = await fetch(`https://api.github.com/repos/${GITHUB_REPO}/actions/workflows/${wf}/dispatches`, {
      method: "POST",
      headers: { Authorization: `Bearer ${env.GITHUB_TOKEN}`, Accept: "application/vnd.github+json",
                 "User-Agent": "hermes-dashboard", "Content-Type": "application/json" },
      body: JSON.stringify({ ref: "main" }) });
    return r.status === 204 ? json({ ok: true }) : json({ ok: false, status: r.status, detail: (await r.text()).slice(0, 160) }, 502);
  } catch (e) {
    return json({ error: String(e && e.message || e) }, 500);
  }
}
