"""Groq key pool + role-based router with automatic failover (Project Hermes).

Lets Hermes use SEVERAL Groq API keys (ideally from separate accounts = separate free
daily budgets) so different jobs don't starve each other, and a 429 / daily-cap on one key
rotates to the next instead of failing. Reads GROQ_API_KEY, GROQ_API_KEY_2, GROQ_API_KEY_3
(or a comma-separated GROQ_API_KEYS) from the environment. Degrades gracefully to one key,
or none (returns None -> caller falls back to its plain-template / keyword behaviour).

Usage:
    content = groq_pool.chat(messages, model="llama-3.1-8b-instant", role="draft")
    # content is the assistant message string (parse JSON yourself), or None on total failure.
"""
import logging
import os

import requests

log = logging.getLogger("groq_pool")
_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

# Each role prefers its own key index so a heavy workload can't drain another's daily budget;
# if that key is rate-limited the pool rotates through the rest before giving up.
_ROLE_INDEX = {
    "judge":   0,   # 70B lead judging — your tightest daily limit, gets a dedicated key
    "draft":   1,   # 8B email drafting
    "extract": 1,   # 8B decision-maker extraction
    "plan":    2,   # 8B/70B agentic planner
    "verify":  2,   # ensemble double-check pass
}


def keys() -> list[str]:
    """All configured Groq keys, de-duplicated, in priority order."""
    raw = [os.getenv("GROQ_API_KEY", ""),
           os.getenv("GROQ_API_KEY_2", ""),
           os.getenv("GROQ_API_KEY_3", "")]
    raw += os.getenv("GROQ_API_KEYS", "").split(",")
    out: list[str] = []
    for k in raw:
        k = k.strip()
        if k and k not in out:
            out.append(k)
    return out


def available() -> bool:
    return bool(keys())


def _rotation(role: str, pool: list[str]) -> list[str]:
    """Keys to try, starting at this role's preferred index, then wrapping around."""
    start = _ROLE_INDEX.get(role, 0) % len(pool)
    return [pool[(start + i) % len(pool)] for i in range(len(pool))]


def chat(messages: list[dict], model: str, role: str = "judge",
         temperature: float = 0, json_mode: bool = True,
         timeout: int = 30, max_tokens: int | None = None) -> str | None:
    """Call Groq chat-completions with failover across the key pool. Returns the assistant
    message content (string), or None if every key failed/was exhausted."""
    pool = keys()
    if not pool:
        return None
    payload: dict = {"model": model, "temperature": temperature, "messages": messages}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if max_tokens:
        payload["max_tokens"] = max_tokens

    for key in _rotation(role, pool):
        try:
            r = requests.post(_ENDPOINT, timeout=timeout,
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                json=payload)
            if r.status_code == 429:
                log.info("Groq key ...%s rate-limited (role=%s) - rotating.", key[-4:], role)
                continue
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            log.warning("Groq call failed (role=%s, key ...%s): %s - rotating.",
                        role, key[-4:], e)
            continue
    log.warning("All %d Groq key(s) exhausted for role=%s.", len(pool), role)
    return None
