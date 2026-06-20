"""Hermes planner — the agentic layer shared by all agents (copied into each agent folder).

Before each run, an agent calls hermes.plan(name, settings). Hermes reads the DATACENTER
(shared memory: source_performance + hot_today), reasons about progress toward the
daily-HOT goal, and returns this run's settings with the work caps tuned UP when behind and
left at baseline when on track. Safe by design: caps only ever scale within [base, 2x base],
so it can push harder (using the multi-key budget) but never blow free-tier limits.

Deterministic at its core (goal pressure); an optional Groq 'advisor' (role="plan") adds a
one-line rationale and may nudge the multiplier within the same clamp. Fail-soft: if the
datacenter or Groq is unavailable, returns the settings unchanged."""
import json
import logging

import requests
import config
import groq_pool

log = logging.getLogger("hermes")
TIMEOUT = 15
_CAP_KEYS = ("max_per_run", "brain_max_per_run")   # the work-volume knobs Hermes may tune


def _base() -> str:
    return config.SUPABASE_URL.rstrip("/") + "/rest/v1"


def _headers() -> dict:
    return {"apikey": config.SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}"}


def read_state() -> dict | None:
    """Read shared memory: today's HOT count + per-source performance. None if unavailable."""
    if not (config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY):
        return None
    try:
        h = _headers()
        hot = requests.get(f"{_base()}/hot_today", headers=h,
                           params={"select": "*"}, timeout=TIMEOUT).json()
        perf = requests.get(f"{_base()}/source_performance", headers=h,
                            params={"select": "*"}, timeout=TIMEOUT).json()
        return {"hot_today": int((hot or [{}])[0].get("hot_today", 0)),
                "sources": perf or []}
    except Exception as e:
        log.warning("Hermes could not read the datacenter (%s) - running defaults.", e)
        return None


def _advise(agent: str, state: dict, goal: int) -> dict | None:
    """Optional Groq nudge: returns {cap_multiplier, rationale} or None (fail-soft)."""
    if not groq_pool.available():
        return None
    sys = ("You are Hermes, the planner for a UK lead-gen system. Given today's progress "
           f"toward the goal of {goal} HOT leads/day and per-source performance, decide how "
           "hard the '" + agent + "' agent should work THIS run. Reply ONLY JSON: "
           '{"cap_multiplier": <0.5-2.0>, "rationale": "<one short line>"}. '
           "Use ~2.0 when far behind goal, ~1.0 when on track.")
    user = (f"HOT today: {state['hot_today']} / {goal}\n"
            f"Source performance: {json.dumps(state['sources'])[:1500]}")
    content = groq_pool.chat(
        [{"role": "system", "content": sys}, {"role": "user", "content": user}],
        model="llama-3.1-8b-instant", role="plan", temperature=0)
    if not content:
        return None
    try:
        return json.loads(content)
    except Exception:
        return None


def _apply_caps(settings: dict, mult: float) -> dict:
    """Scale the work-volume knobs by mult, clamped to [base, 2x base]."""
    out = dict(settings)
    for k in _CAP_KEYS:
        if isinstance(out.get(k), int):
            base = out[k]
            out[k] = max(base, min(int(round(base * mult)), base * 2))
    return out


def plan(agent: str, settings: dict, goal: int | None = None) -> tuple[dict, str]:
    """Return (tuned_settings, rationale). Tunes work caps toward the daily HOT goal."""
    settings = dict(settings or {})
    goal = int(goal or settings.get("daily_hot_goal", 10))
    state = read_state()
    if not state:
        return settings, "no datacenter state - running baseline"

    hot = state["hot_today"]
    pressure = max(0.0, (goal - hot) / goal) if goal else 0.0      # 0 (at goal) .. 1 (none yet)
    mult = round(1.0 + pressure, 2)                                # 1x .. 2x
    rationale = f"{hot}/{goal} HOT today -> push x{mult}"

    advice = _advise(agent, state, goal)
    if advice:
        try:
            mult = max(0.5, min(float(advice.get("cap_multiplier", mult)), 2.0))
        except (TypeError, ValueError):
            pass
        rationale = (advice.get("rationale") or rationale)[:160] + f" (x{mult})"

    return _apply_caps(settings, mult), rationale
