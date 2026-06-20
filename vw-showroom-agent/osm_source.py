"""OpenStreetMap (Overpass API) lead source — FREE, no key, UK-only.

Pulls KBB / interior shops that the public OSM map already has tagged (shop=kitchen,
bathroom_furnishing, interior_decoration, bed, tiles) across Great Britain, with their
name, address, website and phone where mapped. Returns leads in the SAME shape as
companies_house._to_lead so they flow through the identical brain → tier → upsert pipeline.

Note: OSM shops are EXISTING businesses, so they have no incorporation date — they tier
as WATCH/WARM by recency, not HOT. They add coverage + datacenter signal; HOT volume
still comes from Companies House new registrations. Fail-soft: any error returns []."""
import logging
import requests

log = logging.getLogger("osm")
TIMEOUT = 90
# A couple of public Overpass endpoints; we try them in order (they rate-limit).
_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
_DEFAULT_TAGS = ["kitchen", "bathroom_furnishing", "interior_decoration", "bed", "tiles"]
_PROFILE = "https://www.openstreetmap.org/"


def _build_query(tags: list[str]) -> str:
    """Overpass QL: all matching shops within Great Britain."""
    blocks = "".join(f'  nwr["shop"="{t}"](area.uk);\n' for t in tags)
    return (
        "[out:json][timeout:80];\n"
        'area["ISO3166-1"="GB"][admin_level=2]->.uk;\n'
        f"(\n{blocks});\n"
        "out center tags;\n"
    )


def _fmt_location(tags: dict) -> str:
    parts = [tags.get("addr:city") or tags.get("addr:town") or tags.get("addr:suburb"),
             tags.get("addr:postcode")]
    loc = ", ".join(p for p in parts if p)
    return loc or "United Kingdom"


def _to_lead(el: dict) -> dict | None:
    tags = el.get("tags") or {}
    name = (tags.get("name") or "").strip()
    if not name:
        return None                                   # unnamed shop is useless for outreach
    shop = tags.get("shop", "shop")
    osm_id = f"{el.get('type')}/{el.get('id')}"
    website = tags.get("website") or tags.get("contact:website") or ""
    phone = tags.get("phone") or tags.get("contact:phone") or ""
    return {
        "key": f"osm:{osm_id}",
        "source": "OpenStreetMap",
        "title": name,
        "company": name,
        "showroom_name": name,
        "location": _fmt_location(tags),
        "registered_at": None,                        # OSM has no incorporation date
        "salary": None,
        "url": website or f"{_PROFILE}{osm_id}",
        "website": website or None,
        "contact_phone": phone or None,
        "posted": "",
        "description": f"OSM-mapped {shop.replace('_', ' ')} shop. "
                       f"{_fmt_location(tags)}.",
        "matched_on": f"OSM shop={shop}",
    }


def fetch_all(settings: dict) -> list[dict]:
    """Return UK KBB/interior shops from OpenStreetMap, deduped by OSM id."""
    if not bool(settings.get("use_osm", True)):
        return []
    tags = settings.get("osm_shop_tags") or _DEFAULT_TAGS
    cap = int(settings.get("osm_max", 2000))          # safety bound on a big country-wide query
    query = _build_query(tags)
    elements = []
    for endpoint in _ENDPOINTS:
        try:
            r = requests.post(endpoint, data={"data": query}, timeout=TIMEOUT,
                              headers={"User-Agent": "cad-illustrators-hermes/1.0"})
            r.raise_for_status()
            elements = r.json().get("elements", [])
            break
        except Exception as e:
            log.warning("Overpass endpoint %s failed: %s", endpoint, e)
    out, seen = [], set()
    for el in elements:
        lead = _to_lead(el)
        if lead and lead["key"] not in seen:
            seen.add(lead["key"])
            out.append(lead)
        if len(out) >= cap:
            break
    log.info("OpenStreetMap fetched %d UK KBB/interior shops (tags: %s)",
             len(out), ", ".join(tags))
    return out
