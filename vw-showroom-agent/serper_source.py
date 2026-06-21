"""Search-based UK lead discovery (Project Hermes). Uses Serper.dev (Google search, free
tier) to find KBB/interior businesses by querying "<term> <town>" across UK towns — a robust,
ToS-friendly alternative to scraping anti-bot directories (Yell/Houzz/Checkatrade).

Optional: needs SERPER_API_KEY; without it this returns [] (no-op). Credit-friendly: capped at
`serper_max_queries` per run (Serper free tier is limited), with a shuffled town×term subset so
coverage rotates over days. Results flow through the same brain → Smart HOT → datacenter pipeline."""
import logging
import os
import random
import re
import time
from urllib.parse import urlparse

import requests

log = logging.getLogger("serper")
_URL = "https://google.serper.dev/search"
_KEY = os.getenv("SERPER_API_KEY", "")

_DEFAULT_TOWNS = ["London", "Manchester", "Birmingham", "Leeds", "Glasgow", "Bristol",
                  "Liverpool", "Sheffield", "Edinburgh", "Cardiff", "Nottingham", "Leicester",
                  "Newcastle", "Southampton", "Brighton", "Reading", "Milton Keynes", "Hull"]
_DEFAULT_TERMS = ["kitchen showroom", "bathroom showroom", "fitted bedrooms", "kbb showroom"]
# Domains that are directories / marketplaces / media / socials — not a showroom's own site.
_SKIP = ("yell.", "houzz.", "checkatrade.", "trustatrader.", "ratedpeople.", "mybuilder.",
         "bark.com", "trustpilot.", "facebook.", "instagram.", "linkedin.", "youtube.",
         "pinterest.", "twitter.", "x.com", "wikipedia.", "indeed.", "gumtree.", "amazon.",
         "ebay.", "reddit.", "which.co.uk", "gov.uk", ".gov", "tripadvisor.", "google.")
_LEGAL = (" ltd", " limited", " | ", " - ", " – ")


def _domain(link: str) -> str:
    return urlparse(link or "").netloc.lower().replace("www.", "")


def _clean_title(t: str) -> str:
    t = (t or "").strip()
    for sep in (" | ", " - ", " – ", " — "):
        if sep in t:
            t = t.split(sep)[0].strip()
    return t[:80]


def _search(query: str) -> list[dict]:
    try:
        r = requests.post(_URL, headers={"X-API-KEY": _KEY, "Content-Type": "application/json"},
                          json={"q": query, "gl": "gb", "num": 10}, timeout=20)
        r.raise_for_status()
        return r.json().get("organic", [])
    except Exception as e:
        log.debug("Serper query '%s' failed: %s", query, e)
        return []


def fetch_all(settings: dict) -> list[dict]:
    """Discover UK KBB businesses via Google search. [] if no Serper key / disabled."""
    if not _KEY or not bool(settings.get("use_serper", True)):
        return []
    towns = settings.get("serper_towns") or _DEFAULT_TOWNS
    terms = settings.get("serper_terms") or _DEFAULT_TERMS
    cap = int(settings.get("serper_max_queries", 8))     # bound Serper credit use per run
    combos = [(t, tn) for t in terms for tn in towns]
    random.shuffle(combos)
    out, seen = [], set()
    for term, town in combos[:cap]:
        for item in _search(f"{term} {town}"):
            dom = _domain(item.get("link", ""))
            if not dom or dom in seen or any(s in dom for s in _SKIP):
                continue
            seen.add(dom)
            name = _clean_title(item.get("title", "")) or dom
            out.append({
                "key": f"serper:{dom}",
                "source": "Serper",
                "title": name, "company": name, "showroom_name": name,
                "location": town, "registered_at": None, "salary": None,
                "url": item.get("link"), "website": f"https://{dom}",
                "posted": "",
                "description": f"Found via search '{term} {town}'. {item.get('snippet','')[:200]}",
                "matched_on": f"Serper: {term}",
            })
        time.sleep(0.3)
    log.info("Serper discovered %d UK businesses (%d queries).", len(out), min(cap, len(combos)))
    return out
