// Cloudflare Pages Function — Hermes chat backend (Project Hermes, Phase 5).
//
// POST /api/hermes  body: { messages: [{role,content}...], access_token }
// - Verifies the caller is a logged-in dashboard user (Supabase JWT).
// - Calls Groq with function-calling so Hermes can READ the datacenter/leads and
//   TRIGGER agent runs — all server-side, so the Groq key + GitHub token never reach
//   the browser.
//
// Secrets to set in Cloudflare Pages → Settings → Environment variables (Production):
//   GROQ_API_KEY          (your Groq key)
//   SUPABASE_SERVICE_KEY  (service_role key — server-side only)
//   GITHUB_TOKEN          (fine-grained PAT with Actions: read/write on the repo)
// Public defaults below can be overridden by env vars of the same name.

const SUPABASE_URL = "https://qwblxytpznslidwjoxvt.supabase.co";
const SUPABASE_ANON = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InF3Ymx4eXRwem5zbGlkd2pveHZ0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODE2NjE0ODksImV4cCI6MjA5NzIzNzQ4OX0.e0_rcgEY8xY8_AEX3xaKeR1Zxu7TbV2RmXODkl9Wxtc";
const GITHUB_REPO = "dhairyawork8141/Agent-Dashboard";
const GROQ_URL = "https://api.groq.com/openai/v1/chat/completions";
const MODEL = "llama-3.3-70b-versatile";

const WORKFLOWS = {
  showroom: "showroom-agent.yml",
  job: "job-agent.yml",
  contact: "contact-agent.yml",
};

const SYSTEM = `You are Hermes, the assistant inside the CAD Illustrators lead-gen dashboard.
CAD Illustrators is an outsourced CAD/CGI studio selling to UK KBB (kitchen/bedroom/bathroom)
showrooms, fitters and interior designers. You help the owner run the system: report on leads
and which sources are working, and trigger the agents when asked.
Use the tools to get real data before answering numeric questions — never make figures up.
Be concise and practical. When you trigger an agent, say so plainly and that results take a
few minutes. The goal is 10 genuine HOT leads a day.`;

const TOOLS = [
  {
    type: "function",
    function: {
      name: "get_datacenter",
      description: "Per-source performance (discovered/kept/HOT/contacted/sent/replied) and today's HOT count.",
      parameters: { type: "object", properties: {} },
    },
  },
  {
    type: "function",
    function: {
      name: "search_leads",
      description: "Search leads. Filter by tier (HOT/WARM/WATCH), whether a contact email exists, or draft status; optional name search.",
      parameters: {
        type: "object",
        properties: {
          tier: { type: "string", description: "HOT, WARM or WATCH" },
          has_contact: { type: "boolean" },
          draft_status: { type: "string", description: "pending, approved, sent, none" },
          query: { type: "string", description: "company name contains" },
          limit: { type: "integer" },
        },
      },
    },
  },
  {
    type: "function",
    function: {
      name: "trigger_agent",
      description: "Start an agent run now. agent must be one of: showroom, job, contact.",
      parameters: {
        type: "object",
        properties: { agent: { type: "string", enum: ["showroom", "job", "contact"] } },
        required: ["agent"],
      },
    },
  },
];

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

export async function onRequestOptions() {
  return new Response(null, { headers: cors });
}

export async function onRequestPost({ request, env }) {
  const json = (obj, status = 200) =>
    new Response(JSON.stringify(obj), { status, headers: { ...cors, "Content-Type": "application/json" } });
  try {
    const body = await request.json();
    const token = body.access_token || "";
    // --- auth: must be a logged-in dashboard user ---
    const who = await fetch(`${SUPABASE_URL}/auth/v1/user`, {
      headers: { apikey: SUPABASE_ANON, Authorization: `Bearer ${token}` },
    });
    if (!who.ok) return json({ error: "Please sign in to use Hermes." }, 401);

    const msgs = [{ role: "system", content: SYSTEM }, ...(body.messages || [])].slice(-21);
    const reply = await runWithTools(msgs, env);
    return json({ reply });
  } catch (e) {
    return json({ error: String(e && e.message || e) }, 500);
  }
}

async function runWithTools(messages, env) {
  if (!env.GROQ_API_KEY) {
    return "I'm not configured yet — GROQ_API_KEY is missing in Cloudflare → Pages → Settings → Environment variables (Production). Add it and redeploy.";
  }
  for (let step = 0; step < 4; step++) {
    const r = await fetch(GROQ_URL, {
      method: "POST",
      headers: { Authorization: `Bearer ${env.GROQ_API_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify({ model: MODEL, temperature: 0.2, messages, tools: TOOLS, tool_choice: "auto" }),
    });
    if (!r.ok) {
      const detail = (await r.text()).slice(0, 180);
      if (r.status === 401) return "Groq rejected the key (401). Check GROQ_API_KEY in Cloudflare is a valid key (starts with 'gsk_') and redeploy the dashboard.";
      return `Model error (${r.status}): ${detail}`;
    }
    const data = await r.json();
    const msg = data.choices && data.choices[0] && data.choices[0].message;
    if (!msg) return "Sorry, I couldn't get a response.";
    messages.push(msg);
    if (msg.tool_calls && msg.tool_calls.length) {
      for (const tc of msg.tool_calls) {
        let args = {};
        try { args = JSON.parse(tc.function.arguments || "{}"); } catch (_) {}
        const result = await execTool(tc.function.name, args, env);
        messages.push({ role: "tool", tool_call_id: tc.id, content: JSON.stringify(result).slice(0, 4000) });
      }
      continue;
    }
    return msg.content || "(no reply)";
  }
  return "I took a few steps but couldn't finish — try rephrasing.";
}

function sbHeaders(env) {
  return { apikey: env.SUPABASE_SERVICE_KEY, Authorization: `Bearer ${env.SUPABASE_SERVICE_KEY}` };
}

async function execTool(name, args, env) {
  try {
    if (name === "get_datacenter") {
      const base = `${SUPABASE_URL}/rest/v1`;
      const [perf, hot] = await Promise.all([
        fetch(`${base}/source_performance?select=*`, { headers: sbHeaders(env) }).then((r) => r.json()),
        fetch(`${base}/hot_today?select=*`, { headers: sbHeaders(env) }).then((r) => r.json()),
      ]);
      return { source_performance: perf, hot_today: (hot && hot[0] && hot[0].hot_today) || 0 };
    }
    if (name === "search_leads") {
      const p = new URLSearchParams();
      p.set("select", "company,showroom_name,tier,category,location,contact_email,draft_status,score");
      if (args.tier) p.set("tier", `like.${args.tier.toUpperCase()}*`);
      if (args.has_contact === true) p.set("contact_email", "not.is.null");
      if (args.has_contact === false) p.set("contact_email", "is.null");
      if (args.draft_status) p.set("draft_status", `eq.${args.draft_status}`);
      if (args.query) p.set("or", `(company.ilike.*${args.query}*,showroom_name.ilike.*${args.query}*)`);
      p.set("order", "score.desc.nullslast");
      p.set("limit", String(Math.min(args.limit || 15, 40)));
      const rows = await fetch(`${SUPABASE_URL}/rest/v1/leads?${p}`, { headers: sbHeaders(env) }).then((r) => r.json());
      return { count: Array.isArray(rows) ? rows.length : 0, leads: rows };
    }
    if (name === "trigger_agent") {
      const wf = WORKFLOWS[args.agent];
      if (!wf) return { error: "Unknown agent. Use showroom, job or contact." };
      const resp = await fetch(`https://api.github.com/repos/${GITHUB_REPO}/actions/workflows/${wf}/dispatches`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GITHUB_TOKEN}`,
          Accept: "application/vnd.github+json",
          "User-Agent": "hermes-dashboard",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ref: "main" }),
      });
      return resp.status === 204
        ? { ok: true, message: `${args.agent} agent run started — results in a few minutes.` }
        : { ok: false, status: resp.status, detail: (await resp.text()).slice(0, 200) };
    }
    return { error: `Unknown tool ${name}` };
  } catch (e) {
    return { error: String(e && e.message || e) };
  }
}
