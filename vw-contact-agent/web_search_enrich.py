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
        if email_domain in _JUNK_EMAIL_DOMAINS:
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
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    parts = slug.split("-")
    name_parts = []
    for p in parts:
        if p.isalpha() and len(p) > 1:
            name_parts.append(p.capitalize())
        else:
            break
    return " ".join(name_parts) if name_parts else None


def _guess_name_from_email(addr: str) -> str | None:
    local = addr.split("@")[0]
    if local in _GENERIC_EMAIL_PREFIXES:
        return None
    if "." in local:
        parts = local.split(".")
        return " ".join(p.capitalize() for p in parts if p.isalpha())
    return None


# ---------------------------------------------------------------------------
#  Public API
# ---------------------------------------------------------------------------
def enrich_from_web(company_name: str, location: str | None) -> dict | None:
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
    result: dict = {}

    # --- Stage A: guess domain + scrape website ---
    candidates = _guess_domains(name)
    domain = _find_working_domain(candidates) if candidates else None

    if domain:
        log.info("Found website for '%s': %s", name, domain)
        result["website"] = _extract_website(domain)
        result["_domain"] = domain  # internal, stripped before return

        scraped = _scrape_site(domain)
        text = scraped["text"]
        html = scraped["html"]

        # Extract emails (only from own domain preferred).
        emails = _extract_emails_from_text(text, domain)
        if emails:
            result["contact_email"] = emails[0]

        # Extract phones.
        phones = _extract_phones(text)
        if phones:
            result["contact_phone"] = phones[0]

        # Extract social media links.
        socials = _extract_socials(html)
        result.update(socials)

        # Try to find a title in the text.
        title_match = _TITLE_RE.search(text)
        if title_match:
            result["contact_title"] = title_match.group(0).strip().title()
    else:
        log.debug("Could not guess a working domain for '%s'.", name)

    # --- Stage B: Google search (optional, if Serper key is set) ---
    result = _enrich_from_serper(name, location, result)

    # --- Post-processing: guess names ---
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
