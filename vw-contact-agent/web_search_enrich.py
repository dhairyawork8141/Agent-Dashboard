"""Fallback contact enrichment via direct website scraping + optional Google search.

Two-stage approach (both free and unlimited):
  Stage A — Domain guessing: construct likely domains from the company name,
            hit the website, scrape /contact and /about pages for emails,
            phones, social-media links, and decision-maker names.
  Stage B — Google search via Serper.dev (optional, if SERPER_API_KEY is set):
            search Google for extra contact details and social profiles.

No mandatory API key.  Uses only requests (already a project dependency).
Fail-soft: any error returns an empty result dict.
"""
import logging
import os
import re
import time
from urllib.parse import urljoin, urlparse

import requests

try:                                    # optional: MX (mail-server) validation
    import dns.resolver as _dnsresolver
    _DNS_OK = True
except Exception:                       # dnspython not installed -> skip MX checks, fail-soft
    _dnsresolver = None
    _DNS_OK = False

try:                                    # optional: AI decision-maker extraction (Phase 2)
    import contact_brain
except Exception:
    contact_brain = None

log = logging.getLogger("web_enrich")
TIMEOUT = 10
_SERPER_URL = "https://google.serper.dev/search"
_SERPER_KEY = os.getenv("SERPER_API_KEY", "")
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# ---------------------------------------------------------------------------
#  Regex patterns
# ---------------------------------------------------------------------------
_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
_PHONE_RE = re.compile(
    r'\b(0\d{3,4}[\s-]?\d{3}[\s-]?\d{3,4}|'
    r'\+44[\s-]?\d{3,4}[\s-]?\d{3}[\s-]?\d{3,4})\b'
)

# Social media URL patterns (compiled for speed).
_SOCIAL_PATTERNS = {
    "facebook":  re.compile(r'https?://(?:www\.)?facebook\.com/[A-Za-z0-9._-]+/?', re.I),
    "instagram": re.compile(r'https?://(?:www\.)?instagram\.com/[A-Za-z0-9._-]+/?', re.I),
    "linkedin":  re.compile(r'https?://(?:\w+\.)?linkedin\.com/(?:company|in)/[A-Za-z0-9._-]+/?', re.I),
    "twitter":   re.compile(r'https?://(?:www\.)?(?:twitter|x)\.com/[A-Za-z0-9_]+/?', re.I),
    "youtube":   re.compile(r'https?://(?:www\.)?youtube\.com/(?:@|channel/|c/|user/)[A-Za-z0-9._-]+/?', re.I),
    "tiktok":    re.compile(r'https?://(?:www\.)?tiktok\.com/@[A-Za-z0-9._-]+/?', re.I),
    "pinterest": re.compile(r'https?://(?:\w+\.)?pinterest\.(?:com|co\.uk)/[A-Za-z0-9._-]+/?', re.I),
    "houzz":     re.compile(r'https?://(?:www\.)?houzz\.(?:com|co\.uk)/[A-Za-z0-9._/-]+/?', re.I),
}

_GENERIC_EMAIL_PREFIXES = frozenset([
    "info", "enquiries", "enquiry", "contact", "hello", "admin", "sales",
    "support", "office", "mail", "team", "help", "reception", "general",
    "accounts", "noreply", "no-reply", "privacy", "webmaster",
])

_TITLE_RE = re.compile(
    r'\b(owner|founder|co-?founder|managing\s+director|director|'
    r'proprietor|partner|showroom\s+manager|general\s+manager|'
    r'sales\s+director|md)\b', re.I,
)

_LEGAL_SUFFIXES = (
    " inc.", " inc", " corp.", " corp", " llc", " llp", " plc",
    " limited", " ltd.", " ltd", " (uk)", " uk ltd",
    " gmbh", " pty", " dba",
)

# Common TLD suffixes to try when guessing domains.
_TLDS = (".co.uk", ".com", ".com.au", ".ie", ".org", ".net")

# Pages likely to contain contact info.
_CONTACT_PATHS = ("/contact", "/contact-us", "/about", "/about-us", "/team",
                  "/our-team", "/people")

# Domains to ignore when extracting emails (not real showroom emails).
_JUNK_EMAIL_DOMAINS = frozenset([
    "example.com", "domain.com", "wixpress.com", "sentry.io",
    "googleapis.com", "w3.org", "schema.org", "googletagmanager.com",
    "facebook.com", "twitter.com", "instagram.com", "youtube.com",
    "linkedin.com", "pinterest.com", "tiktok.com", "google.com",
    "apple.com", "microsoft.com", "mozilla.org", "wordpress.org",
    "gravatar.com", "wp.com", "cloudflare.com", "jquery.com",
    "bootstrapcdn.com", "fontawesome.com", "gstatic.com",
])

# Government / institutional domains are never a real showroom contact - reject outright
# (these slip in from licensing/regulator pages, e.g. onlinehelp@dcwp.nyc.gov).
_JUNK_DOMAIN_SUFFIXES = (".gov", ".gov.uk", ".gov.au", ".gov.ie", ".gc.ca",
                         ".nhs.uk", ".police.uk", ".mil", ".ac.uk", ".edu", ".sch.uk")
_JUNK_DOMAIN_SUBSTR = ("council", "nhs", "police", "hmrc", "parliament", ".gov.",
                       "wixpress", "sentry", "godaddy", "wordpress", "squarespace")


def _is_junk_domain(domain: str) -> bool:
    d = (domain or "").lower()
    if d in _JUNK_EMAIL_DOMAINS:
        return True
    if any(d.endswith(s) for s in _JUNK_DOMAIN_SUFFIXES):
        return True
    return any(s in d for s in _JUNK_DOMAIN_SUBSTR)


# Words too generic to identify a company (so a domain sharing only these isn't a match).
_GENERIC_NAME_WORDS = frozenset([
    "the", "and", "ltd", "limited", "llp", "plc", "uk", "co", "group", "company",
    "studio", "studios", "services", "service", "solutions", "design", "designs",
    "designer", "interior", "interiors", "kitchen", "kitchens", "bathroom", "bathrooms",
    "bedroom", "bedrooms", "fitted", "furniture", "tiles", "tile", "home", "homes",
])
# Free email providers never prove company ownership -> can't be domain-matched.
_FREE_EMAIL_DOMAINS = frozenset([
    "gmail.com", "outlook.com", "hotmail.com", "hotmail.co.uk", "yahoo.com",
    "yahoo.co.uk", "icloud.com", "aol.com", "live.com", "btinternet.com", "me.com",
])
_TLD_STRIP = (".co.uk", ".org.uk", ".com", ".org", ".net", ".uk", ".ie", ".io",
              ".biz", ".shop", ".store", ".design", ".co")


def _company_tokens(name: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    return [w for w in words if len(w) >= 4 and w not in _GENERIC_NAME_WORDS]


def _domain_core(domain: str) -> str:
    d = (domain or "").lower().split("@")[-1].strip()
    for tld in _TLD_STRIP:
        if d.endswith(tld):
            d = d[: -len(tld)]
            break
    return re.sub(r"[^a-z0-9]", "", d)


def _domain_matches_company(domain: str, name: str) -> bool:
    """True only if the domain plausibly belongs to THIS company (shares a distinctive
    token). Prevents grabbing a different company's domain (e.g. suttonbuild for INODESIGN)."""
    dl = (domain or "").lower().split("@")[-1]
    if dl in _FREE_EMAIL_DOMAINS:
        return False
    core = _domain_core(domain)
    if not core:
        return False
    toks = _company_tokens(name)
    if not toks:                                   # no distinctive words -> need full-slug match
        slug = re.sub(r"[^a-z0-9]", "", (name or "").lower())
        return bool(slug) and (slug in core or core in slug)
    return any(t in core or core in t for t in toks)


# ---------------------------------------------------------------------------
#  Company name cleaning
# ---------------------------------------------------------------------------
def _clean_name(name: str) -> str:
    """Strip legal suffixes and 'DBA' clauses for better search results."""
    out = name.strip()
    if " dba " in out.lower():
        out = out.lower().split(" dba ")[-1].strip().title()
    low = out.lower()
    for suf in _LEGAL_SUFFIXES:
        if low.endswith(suf):
            out = out[: len(out) - len(suf)].strip()
            break
    # Also strip trailing commas and whitespace.
    return out.rstrip(", ").strip()


def _slugify(name: str) -> str:
    """Turn 'Coastal Bathrooms' into 'coastalbathrooms'."""
    return re.sub(r'[^a-z0-9]', '', name.lower())


# ---------------------------------------------------------------------------
#  HTTP helpers
# ---------------------------------------------------------------------------
def _get(url: str, timeout: int = TIMEOUT) -> str | None:
    """Fetch a page; return its text or None on any error."""
    try:
        r = requests.get(url, headers={"User-Agent": _UA}, timeout=timeout,
                         allow_redirects=True)
        if r.status_code == 200 and "text/html" in r.headers.get("content-type", ""):
            return r.text
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
#  Stage A — Domain guessing + website scraping
# ---------------------------------------------------------------------------
def _guess_domains(company_name: str) -> list[str]:
    """Generate candidate domains from a company name."""
    slug = _slugify(company_name)
    if not slug or len(slug) < 3:
        return []
    # Also try with hyphens: "Coastal Bathrooms" -> "coastal-bathrooms"
    hyphenated = re.sub(r'[^a-z0-9]+', '-', company_name.lower()).strip('-')
    candidates = []
    for tld in _TLDS:
        candidates.append(f"{slug}{tld}")
        if hyphenated != slug:
            candidates.append(f"{hyphenated}{tld}")
    return candidates


def _find_working_domain(candidates: list[str]) -> str | None:
    """Return the first domain that responds with a real website."""
    for domain in candidates:
        try:
            r = requests.head(f"https://www.{domain}",
                              headers={"User-Agent": _UA},
                              timeout=5, allow_redirects=True)
            if r.status_code < 400:
                return domain
        except Exception:
            pass
        try:
            r = requests.head(f"https://{domain}",
                              headers={"User-Agent": _UA},
                              timeout=5, allow_redirects=True)
            if r.status_code < 400:
                return domain
        except Exception:
            pass
    return None


def _scrape_site(domain: str) -> dict:
    """Scrape a website's homepage + contact/about pages for useful data."""
    all_text = ""
    all_html = ""

    urls_to_try = [f"https://www.{domain}", f"https://{domain}"]
    for path in _CONTACT_PATHS:
        urls_to_try.append(f"https://www.{domain}{path}")
        urls_to_try.append(f"https://{domain}{path}")

    pages_fetched = 0
    for url in urls_to_try:
        if pages_fetched >= 4:  # cap to avoid being slow
            break
        html = _get(url, timeout=8)
        if html:
            all_html += " " + html
            # Strip HTML tags for text extraction.
            text = re.sub(r'<[^>]+>', ' ', html)
            text = re.sub(r'\s+', ' ', text)
            all_text += " " + text
            pages_fetched += 1
        time.sleep(0.2)

    return {"text": all_text, "html": all_html, "domain": domain}


def _extract_emails_from_text(text: str, own_domain: str | None) -> list[str]:
    """Extract and rank emails. Own-domain personal emails first."""
    raw = _EMAIL_RE.findall(text)
    seen: set[str] = set()
    result: list[str] = []
    for addr in raw:
        addr = addr.lower()
        email_domain = addr.split("@")[1] if "@" in addr else ""
        if _is_junk_domain(email_domain):
            continue
        if addr not in seen:
            seen.add(addr)
            result.append(addr)
    # Sort: own-domain personal > own-domain generic > other
    def _rank(a: str) -> int:
        local = a.split("@")[0]
        domain = a.split("@")[1]
        score = 50
        if own_domain and own_domain in domain:
            score -= 20
        if local in _GENERIC_EMAIL_PREFIXES:
            score += 30
        else:
            score -= 15
        return score
    result.sort(key=_rank)
    return result


def _extract_phones(text: str) -> list[str]:
    return list(dict.fromkeys(m.strip() for m in _PHONE_RE.findall(text)))


def _extract_socials(html: str) -> dict:
    """Extract social media URLs from raw HTML."""
    socials: dict[str, str] = {}
    for platform, pattern in _SOCIAL_PATTERNS.items():
        matches = pattern.findall(html)
        if matches:
            # Pick the first unique, clean match.
            url = matches[0].rstrip("/")
            # Filter out generic/share links.
            if "/sharer" in url or "/share" in url or "/intent" in url:
                continue
            socials[f"social_{platform}"] = url
    return socials


def _extract_website(domain: str) -> str:
    return f"https://www.{domain}"


# ---------------------------------------------------------------------------
#  Stage B — Google search via Serper.dev (optional)
# ---------------------------------------------------------------------------
def _serper_search(query: str) -> list[dict]:
    """Return [{title, link, snippet}, ...] from Google via Serper."""
    if not _SERPER_KEY:
        return []
    try:
        r = requests.post(
            _SERPER_URL,
            headers={"X-API-KEY": _SERPER_KEY,
                     "Content-Type": "application/json"},
            json={"q": query, "num": 10},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        results = []
        for item in data.get("organic", []):
            results.append({
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            })
        kg = data.get("knowledgeGraph", {})
        if kg:
            attrs = kg.get("attributes", {})
            extra = " ".join(f"{k}: {v}" for k, v in attrs.items())
            results.append({
                "title": kg.get("title", ""),
                "link": kg.get("website", ""),
                "snippet": kg.get("description", "") + " " + extra,
            })
        return results
    except Exception as exc:
        log.debug("Serper search failed for '%s': %s", query, exc)
        return []


def _enrich_from_serper(company_name: str, location: str | None,
                        existing: dict) -> dict:
    """Supplement existing data with Google search results (if Serper key set)."""
    if not _SERPER_KEY:
        return existing

    loc = location or ""
    search_results = _serper_search(f"{company_name} {loc} contact email")
    time.sleep(0.3)
    search_results += _serper_search(f"{company_name} {loc} owner director")

    if not search_results:
        return existing

    full_text = " ".join(r["title"] + " " + r["snippet"] for r in search_results)
    all_links = " ".join(r["link"] for r in search_results)

    # Fill in missing emails.
    if not existing.get("contact_email"):
        emails = _extract_emails_from_text(full_text, existing.get("_domain"))
        if emails:
            existing["contact_email"] = emails[0]

    # Fill in missing socials from search result URLs.
    serper_socials = _extract_socials(all_links + " " + full_text)
    for key, val in serper_socials.items():
        if not existing.get(key):
            existing[key] = val

    # Fill in missing phone.
    if not existing.get("contact_phone"):
        phones = _extract_phones(full_text)
        if phones:
            existing["contact_phone"] = phones[0]

    # Try to find a LinkedIn person profile.
    if not existing.get("contact_linkedin"):
        person_re = re.compile(r'https?://(?:\w+\.)?linkedin\.com/in/[\w-]+')
        person_matches = person_re.findall(all_links + " " + full_text)
        if person_matches:
            existing["contact_linkedin"] = person_matches[0]

    # Try to extract a title if missing.
    if not existing.get("contact_title"):
        title_match = _TITLE_RE.search(full_text)
        if title_match:
            existing["contact_title"] = title_match.group(0).strip().title()

    return existing


# ---------------------------------------------------------------------------
#  Name guessing helpers
# ---------------------------------------------------------------------------
def _guess_name_from_linkedin(url: str) -> str | None:
    """Only accept a real-looking 'First Last' from a /in/first-last slug.
    Single-token handles (e.g. 'thekitchenguynyc') are rejected -> no fake name."""
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    parts = [p for p in slug.split("-") if p.isalpha() and len(p) > 1]
    if len(parts) >= 2:                       # need at least first + last
        return " ".join(p.capitalize() for p in parts[:3])
    return None


def _guess_name_from_email(addr: str) -> str | None:
    """Only accept a 'first.last@' style local part as a name; never a handle/word."""
    local = addr.split("@")[0]
    if local in _GENERIC_EMAIL_PREFIXES:
        return None
    if "." in local:
        parts = [p for p in local.split(".") if p.isalpha() and len(p) > 1]
        if len(parts) >= 2:
            return " ".join(p.capitalize() for p in parts)
    return None


# ---------------------------------------------------------------------------
#  Accuracy: site verification, MX validation, confidence
# ---------------------------------------------------------------------------
_TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def _site_is_company(text: str, html: str, name: str) -> bool:
    """Confirm a fetched site actually belongs to THIS company before we trust any
    email off it. Domain-guessing happily returns a *different* business that owns the
    slug; this checks the company-name tokens really appear in the page <title>/body.
    Lenient enough for brand vs legal-name drift, strict enough to reject wrong sites."""
    toks = _company_tokens(name)
    body = (text or "").lower()
    m = _TITLE_TAG_RE.search(html or "")
    title = m.group(1).lower() if m else ""
    if toks:
        if any(t in title for t in toks):                 # name in the title = strong signal
            return True
        return sum(1 for t in toks if t in body) >= max(1, len(toks) // 2)
    slug = re.sub(r"[^a-z0-9]", "", (name or "").lower())  # no distinctive words -> full slug
    return bool(slug) and slug in re.sub(r"[^a-z0-9]", "", title + " " + body)


def _has_mx(domain_or_email: str):
    """True/False if the domain has/lacks a mail server; None if unknown (no dnspython
    or a transient lookup error - we don't punish a good lead for flaky DNS)."""
    d = (domain_or_email or "").split("@")[-1].strip().lower().rstrip(".")
    if not d or not _DNS_OK:
        return None
    try:
        return len(_dnsresolver.resolve(d, "MX", lifetime=6)) > 0
    except (_dnsresolver.NXDOMAIN, _dnsresolver.NoAnswer):
        return False
    except Exception:
        return None


def _discover_domain(name: str, location: str | None) -> str | None:
    """Find the company's real website. Search-first via Serper (returns the *actual*
    site, not a name-slug guess), falling back to slug-guessing only if no Serper key."""
    if _SERPER_KEY:
        loc = location or ""
        for r in _serper_search(f"{name} {loc} kitchen bathroom showroom"):
            host = urlparse(r.get("link") or "").netloc.lower().replace("www.", "")
            if host and not _is_junk_domain(host) and _domain_matches_company(host, name):
                return host
    candidates = _guess_domains(name)
    return _find_working_domain(candidates) if candidates else None


def _confidence(result: dict, name: str, verified: bool, mx) -> int:
    """0-100 score for how much we trust the found email. Used to gate weak contacts."""
    email = result.get("contact_email")
    if not email:
        return 0
    score = 20
    if verified:
        score += 40                                       # site confirmed to be this company
    if _domain_matches_company(email, name):
        score += 25
    if email.split("@")[0] not in _GENERIC_EMAIL_PREFIXES:
        score += 15                                       # a personal address, not info@
    if mx is True:
        score += 15
    elif mx is False:
        score = 0                                         # dead mailbox domain
    return min(score, 100)


# ---------------------------------------------------------------------------
#  Public API
# ---------------------------------------------------------------------------
def enrich_from_web(company_name: str, location: str | None,
                    settings: dict | None = None) -> dict | None:
    """Find contact details, website, and social media for a company.

    Returns a dict with keys matching the Supabase ``leads`` columns::

        {contact_name, contact_email, contact_phone, contact_linkedin,
         contact_title, website,
         social_facebook, social_instagram, social_linkedin,
         social_twitter, social_youtube, social_tiktok,
         social_pinterest, social_houzz}

    or ``None`` if nothing useful was found.
    """
    name = _clean_name(company_name)
    min_conf = int((settings or {}).get("min_contact_confidence", 50))
    result: dict = {}
    verified = False

    # --- Stage A: discover the REAL website (search-first), verify it's this company,
    #     then scrape it. Unverified sites are dropped - this is the wrong-email fix. ---
    domain = _discover_domain(name, location)
    if domain:
        scraped = _scrape_site(domain)
        text, html = scraped["text"], scraped["html"]
        if _site_is_company(text, html, name):
            verified = True
            log.info("Verified website for '%s': %s", name, domain)
            result["website"] = _extract_website(domain)
            result["_domain"] = domain  # internal, stripped before return

            emails = _extract_emails_from_text(text, domain)
            if emails:
                result["contact_email"] = emails[0]
            phones = _extract_phones(text)
            if phones:
                result["contact_phone"] = phones[0]
            result.update(_extract_socials(html))
            title_match = _TITLE_RE.search(text)
            if title_match:
                result["contact_title"] = title_match.group(0).strip().title()

            # Phase 2: let the 8B brain pick the best decision-maker from the page,
            # overriding the regex first-match. Anti-hallucination: only accept an email
            # that literally appears in the scraped text and isn't a junk domain.
            if contact_brain and contact_brain.available():
                ai = contact_brain.extract_contact(name, text, domain, settings)
                if ai and ai.get("is_company") and ai.get("email"):
                    ae = ai["email"]
                    if ae in text.lower() and not _is_junk_domain(ae.split("@")[-1]):
                        result["contact_email"] = ae
                        if ai.get("name"):
                            result["contact_name"] = ai["name"]
                        if ai.get("title"):
                            result["contact_title"] = ai["title"]
        else:
            log.info("Site %s does not look like '%s' - rejecting (wrong company).",
                     domain, name)
    else:
        log.debug("Could not find a working domain for '%s'.", name)

    # --- Stage B: Google search (optional, if Serper key is set) ---
    result = _enrich_from_serper(name, location, result)

    # --- Accuracy gate: drop anything that doesn't belong to THIS company ---
    # (the scraper/Serper can surface a different company's site/email).
    _SOCIAL_KEYS = ("social_facebook", "social_instagram", "social_linkedin",
                    "social_twitter", "social_youtube", "social_tiktok",
                    "social_pinterest", "social_houzz")
    if result.get("website") and not _domain_matches_company(result["website"], name):
        for key in ("website", "contact_phone") + _SOCIAL_KEYS:
            result.pop(key, None)
    if result.get("contact_email") and not _domain_matches_company(result["contact_email"], name):
        for key in ("contact_email", "contact_name", "contact_title"):
            result.pop(key, None)

    # --- MX validation: drop an email whose domain has no mail server (dead/typo'd) ---
    mx = None
    if result.get("contact_email"):
        mx = _has_mx(result["contact_email"])
        if mx is False:
            log.info("Dropping %s for '%s' - domain has no mail server.",
                     result["contact_email"], name)
            for key in ("contact_email", "contact_name", "contact_title"):
                result.pop(key, None)

    # --- Confidence gate: better no email than a wrong one (cold outreach) ---
    if result.get("contact_email"):
        conf = _confidence(result, name, verified, mx)
        if conf < min_conf:
            log.info("Dropping low-confidence email %s for '%s' (%d < %d).",
                     result["contact_email"], name, conf, min_conf)
            for key in ("contact_email", "contact_name", "contact_title"):
                result.pop(key, None)

    # --- Post-processing: guess names (only from a kept, matching email/profile) ---
    if not result.get("contact_name"):
        if result.get("contact_linkedin"):
            result["contact_name"] = _guess_name_from_linkedin(
                result["contact_linkedin"])
        elif result.get("contact_email"):
            result["contact_name"] = _guess_name_from_email(
                result["contact_email"])

    # Clean up internal keys.
    result.pop("_domain", None)

    # Only return if we found something useful.
    if not result.get("contact_email") and not result.get("website"):
        log.info("Web enrichment found nothing useful for '%s'.", name)
        return None

    log.info("Web enrichment for '%s': email=%s, website=%s, socials=%d",
             name,
             result.get("contact_email", "none"),
             result.get("website", "none"),
             sum(1 for k in result if k.startswith("social_") and result[k]))
    return result
