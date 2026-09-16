"""
DealerOn website scraper (the platform Lighthouse Buick GMC runs on).

PLAIN ENGLISH: A lot of dealership websites are built by a company called DealerOn.
Every one of those sites publishes a "sitemap" -- a plain text list of every page on
the site, including one page per vehicle. This file:

  1. Downloads that sitemap (one request) and picks out the vehicle pages.
     A DealerOn vehicle page URL looks like:
         https://www.lighthousegmc.com/new-Springfield-2025-GMC-Sierra-1500-AT4-1GTUUEE1XXXXXXXXX
     ...so the last chunk after the final dash is the 17-character VIN. That means we
     know every VIN on the lot before we open a single vehicle page.
  2. Opens each vehicle page and reads the price, color, engine, photos, etc.
  3. Hands back a plain list of vehicles in the shared shape every scraper uses,
     so the rest of the program does not care which website platform it came from.

WHY FOUR PLACES TO LOOK FOR THE SAME NUMBER: dealership sites are built by marketing
teams, not by us. The same fact (say, MSRP) shows up in a hidden JavaScript blob on one
store, in Google's "structured data" block on the next, and only in the visible HTML on a
third. Even on ONE store it moves: on Lighthouse right now a brand-new truck has its
price in the JavaScript blob, while a used truck has no such blob at all. So for each
field we try, in order:

    1. the hidden JavaScript price blob
    2. Google structured data (the block that puts cars in search results)
    3. the site's own "data-" attributes on the listing (stock number, odometer, body style)
    4. a plain text search of the page

First one that answers wins, and a field nobody answers comes back blank rather than
wrong. This is why the scraper keeps working when a store redesigns half its page.

You should not need to edit this file. If a site changes its layout, the thing to fix is
usually one of the regular expressions ("regex") below -- ask your AI agent to help.
"""

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape as html_unescape

from ..http import polite_get
from ..normalize import (
    decode_drivetrain_from_vin,
    normalize_vehicle,
    safe_float,
    safe_int,
)

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

# How many vehicle pages to download at the same time.
# WHY this is safe to raise a little but not a lot: http.polite_get already waits the
# crawl delay that the site's own robots.txt asks for, per host. So the workers throttle
# themselves -- more workers mostly means "less idle waiting", not "hammer the site".
# Override with SCRAPER_WORKERS=10 in your .env if a run feels slow.
DEFAULT_WORKERS = 5

# Print a progress line every this many pages. The workshop room is watching the terminal.
PROGRESS_EVERY = 25

# Only print the first few error messages so one broken site cannot spam the screen.
MAX_ERRORS_PRINTED = 5

# A DealerOn sitemap can be a "sitemap index" -- a list of other sitemaps instead of a
# list of pages. If that happens we open the child sitemaps, but never more than this
# many, so a misconfigured site cannot send us on a long crawl.
MAX_CHILD_SITEMAPS = 25


# ---------------------------------------------------------------------------
# Step 1: find every vehicle page from the sitemap
# ---------------------------------------------------------------------------


def _url_slugs(sitemap_xml):
    """Pull every <loc>...</loc> address out of a sitemap.

    We use a regular expression instead of a real XML parser on purpose: dealership
    sitemaps are frequently slightly malformed, and a strict XML parser refuses to read
    the whole file when one tag is wrong. The regex just takes what it can get.
    """
    urls = []
    for raw_url in re.findall(r"<loc>(.*?)</loc>", sitemap_xml, re.DOTALL):
        url = raw_url.strip()
        # Sitemaps escape a few characters; undo the two we actually see in the wild.
        url = url.replace("&#x2B;", "+").replace("&amp;", "&")
        if url:
            urls.append(url)
    return urls


def _condition_markers(condition):
    """Which URL fragments identify the vehicles we were asked to scrape.

    "new"  -> pages whose URL contains "/new-"
    "used" -> pages whose URL contains "/used-"
    "all"  -> both
    """
    cond = (condition or "new").strip().lower()
    if cond == "used":
        return ["/used-"]
    if cond == "all":
        return ["/new-", "/used-"]
    return ["/new-"]


def _vin_from_url(url):
    """The VIN is the last dash-separated chunk of the URL, e.g. ...-1GTUUEE1XXXXXXXXX.

    Returns the uppercase VIN, or "" if the last chunk does not look like a VIN.
    A VIN is always exactly 17 letters/digits, which is a strong enough test that we
    do not accidentally treat "/new-inventory" style pages as vehicles.
    """
    slug = url.split("?")[0].rstrip("/").split("/")[-1]
    parts = slug.split("-")
    candidate = parts[-1] if parts else ""
    if len(candidate) == 17 and candidate.isalnum():
        return candidate.upper()
    return ""


def collect_vehicle_urls(base_url, condition="new"):
    """Return a list of {"vin", "url", "condition"} dicts, one per vehicle page.

    One HTTP request for the whole lot (plus child sitemaps if the site uses them).
    Duplicates are removed -- some sites list the same vehicle twice.
    """
    markers = _condition_markers(condition)
    sitemap_url = base_url.rstrip("/") + "/sitemap.xml"
    xml = polite_get(sitemap_url)
    if not xml:
        return []

    locs = _url_slugs(xml)

    # Fallback: this was a sitemap index (a list of other sitemaps), not a list of pages.
    # Detect it by "no vehicle URLs here, but plenty of links to more .xml files".
    if not any(marker in u for u in locs for marker in markers):
        child_sitemaps = [u for u in locs if u.lower().endswith(".xml")][:MAX_CHILD_SITEMAPS]
        if child_sitemaps:
            print("    Sitemap is an index; opening %d child sitemaps..." % len(child_sitemaps))
            locs = []
            for child in child_sitemaps:
                child_xml = polite_get(child)
                if child_xml:
                    locs.extend(_url_slugs(child_xml))

    items = []
    seen_vins = set()
    for url in locs:
        matched = None
        for marker in markers:
            if marker in url:
                matched = marker
                break
        if matched is None:
            continue
        vin = _vin_from_url(url)
        if not vin or vin in seen_vins:
            continue
        seen_vins.add(vin)
        items.append({
            "vin": vin,
            "url": url,
            # In "all" mode each vehicle's condition comes from its own URL.
            "condition": "used" if matched == "/used-" else "new",
        })
    return items


# ---------------------------------------------------------------------------
# Step 2: read one vehicle page
# ---------------------------------------------------------------------------


def _parse_trim(name, make, model):
    """Turn "2025 GMC Sierra 1500 AT4" into "AT4".

    The site gives us a full display name; the trim is whatever is left once we strip the
    year off the front and remove the make and model.
    """
    if not name:
        return ""
    trim = re.sub(r"^\d{4}\s*", "", name)
    if make:
        trim = re.sub(re.escape(make), "", trim, count=1, flags=re.IGNORECASE).strip()
    if model:
        trim = re.sub(re.escape(model), "", trim, count=1, flags=re.IGNORECASE).strip()
    return trim.strip(" -")


def _photo_sort_key(photo_url):
    """Sort photos the way the site numbers them: .../ip/1.jpg, .../ip/2.jpg, ...

    Without this, sorting is alphabetical and photo 10 lands before photo 2, which makes
    the first photo in our database the wrong one.
    """
    m = re.search(r"/(\d+)\.jpg", photo_url)
    return int(m.group(1)) if m else 0


def _extract_photos(html, base_url, vin):
    """Find the full-size photos for this VIN.

    DealerOn stores photos at a predictable path that contains the VIN in lowercase:
        inventoryphotos/18868/1gtuuee1xxxxxxxxx/ip/3.jpg   <- "ip" = real lot photos
        inventoryphotos/18868/1gtuuee1xxxxxxxxx/sp/1.jpg   <- "sp" = manufacturer stock photos

    We take real photos when the store has taken them, and fall back to the
    manufacturer's stock photos otherwise. That fallback matters: a brand-new unit that
    is still in transit has NO lot photos yet, and on Lighthouse today that describes
    most of the new inventory -- an /ip/-only match would return zero photos for them.

    We deliberately skip the ".../thumbs/..." copies and the "?width=400" resized
    variants of the same picture, or we would store the same photo six times.
    """
    if not vin:
        return []
    vin_lower = vin.lower()
    pattern = r"inventoryphotos/\d+/" + re.escape(vin_lower) + r"/(ip|sp)/(\d+)\.jpg"
    real_photos = []
    stock_photos = []
    for match in re.finditer(pattern, html, re.IGNORECASE):
        full_url = base_url.rstrip("/") + "/" + match.group(0)
        if match.group(1).lower() == "ip":
            real_photos.append(full_url)
        else:
            stock_photos.append(full_url)
    chosen = real_photos or stock_photos
    return sorted(set(chosen), key=_photo_sort_key)


def _vehicle_data_attributes(html):
    """Read DealerOn's own "data-" attributes off the main vehicle container.

    Every DealerOn vehicle page wraps the listing in a tag tagged `data-vehicle-information`
    that carries the whole vehicle as HTML attributes:

        <div class="vdp vdp--mod" data-vehicle-information data-vin="3GTUUGED5TG131175"
             data-stocknum="W663" data-bodystyle="Crew Cab" data-odometer="11238" ...>

    This is the single most reliable source on the page -- it is what the site's own
    JavaScript reads -- and it carries fields the price blob and the Google structured
    data simply do not have, most importantly stock number, body style and odometer.
    Returns a plain dict like {"vin": "...", "stocknum": "W663", ...}; empty if the tag
    is missing (an older DealerOn theme, or a page that is not a vehicle page).
    """
    tag = re.search(r"<[a-zA-Z]+[^>]{0,6000}?data-vehicle-information[^>]{0,6000}?>", html, re.DOTALL)
    if not tag:
        return {}
    attrs = {}
    for name, value in re.findall(r'data-([a-zA-Z0-9-]+)="([^"]*)"', tag.group(0)):
        attrs[name.lower()] = html_unescape(value).strip()
    return attrs


def _text(value):
    """Force whatever a page handed us into a plain, trimmed string.

    Structured data is inconsistent across sites: "brand" is the word "GMC" on one store
    and {"@type": "Brand", "name": "GMC"} on the next. Without this, the second store
    would put a chunk of raw JSON in your make column.
    """
    if value is None:
        return ""
    if isinstance(value, dict):
        value = value.get("name") or value.get("value") or ""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
        if isinstance(value, dict):
            value = value.get("name") or value.get("value") or ""
    return str(value).strip()


def _json_ld_blocks(html):
    """Return the Vehicle and Product "structured data" blocks Google reads.

    Most dealership sites embed these so their cars show up in search results, which
    conveniently makes them a clean, standardized source of vehicle data for us too.
    """
    vehicle = {}
    product = {}
    for block in re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL
    ):
        try:
            data = json.loads(block)
        except (json.JSONDecodeError, ValueError):
            continue  # One malformed block should never stop the whole page.
        if not isinstance(data, dict):
            continue
        if data.get("@type") == "Vehicle":
            vehicle = data
        elif data.get("@type") == "Product":
            product = data
    return vehicle, product


def _extract_mileage(html, js_data, vehicle, attrs):
    """Odometer reading. Used cars always have one; new cars have 0 or a delivery mile or two.

    We return None rather than 0 for a brand-new unit, because "0" in a mileage column
    reads like a real measurement while None honestly means "not applicable".
    """
    candidates = [
        js_data.get("mileage"),
        js_data.get("odometer"),
        attrs.get("odometer"),
    ]
    odo = vehicle.get("mileageFromOdometer")
    if isinstance(odo, dict):
        odo = odo.get("value")
    candidates.append(odo)

    for candidate in candidates:
        miles = safe_int(candidate)
        if miles:  # skips both None and 0
            return miles

    m = re.search(r"Mileage[:\s]*</?[^>]*>?\s*([\d,]{3,9})", html, re.IGNORECASE)
    if m:
        return safe_int(m.group(1).replace(",", "")) or None
    return None


def parse_vdp(url, base_url, fallback_vin="", condition="new"):
    """Download one VDP ("vehicle detail page") and return a raw vehicle dict.

    Raises ValueError if the page could not be read, so the caller can count it as an
    error and keep going with the rest of the lot.
    """
    html = polite_get(url)
    if not html:
        # polite_get returns "" for a 404 -- the vehicle was probably sold and the page
        # removed between the sitemap being generated and us getting here.
        raise ValueError("page was empty or missing (404)")

    # --- Source 1: the hidden JavaScript object that powers the price display.
    # It is the most reliable source of price on DealerOn, so we look here first.
    js_data = {}
    js_match = re.search(r'(\{[^{}]*"displayedPrice"[^{}]*"msrp"[^{}]*\})', html)
    if js_match:
        try:
            js_data = json.loads(js_match.group(1))
        except (json.JSONDecodeError, ValueError):
            js_data = {}

    # --- Source 2: Google structured data.
    vehicle, product = _json_ld_blocks(html)

    # --- Source 3: the site's own data- attributes (see _vehicle_data_attributes).
    attrs = _vehicle_data_attributes(html)

    vin = _text(
        js_data.get("vin")
        or attrs.get("vin")
        or vehicle.get("vehicleIdentificationNumber")
        or product.get("productID")
        or ""
    ).upper()
    # A VIN is exactly 17 characters. If the page gave us something else (blank, or a
    # marketing id), trust the VIN we already read out of the URL instead -- the VIN is
    # half of the database key, so getting it wrong would create a duplicate vehicle.
    if len(vin) != 17:
        vin = (fallback_vin or "").upper()

    # Every line below reads "use the first source that actually filled this in".
    raw = {
        "vin": vin,
        "stock_number": _text(
            js_data.get("stockNumber") or attrs.get("stocknum") or product.get("sku")
        ),
        "year": safe_int(
            js_data.get("year") or attrs.get("year") or vehicle.get("vehicleModelDate")
        ),
        "make": _text(
            js_data.get("make")
            or attrs.get("make")
            or (vehicle.get("manufacturer") or {}).get("name")
            or product.get("brand")
        ),
        "model": _text(
            js_data.get("model")
            or attrs.get("model")
            or vehicle.get("model")
            or product.get("model")
        ),
        "trim": _text(js_data.get("trim") or attrs.get("trim")),
        "body_type": _text(vehicle.get("bodyType") or attrs.get("bodystyle")),
        "engine": _text(
            js_data.get("engine")
            or attrs.get("engine")
            or (vehicle.get("vehicleEngine") or {}).get("name")
        ),
        "fuel_type": _text(
            js_data.get("fuelType") or attrs.get("fueltype") or vehicle.get("fuelType")
        ),
        "drivetrain": _text(js_data.get("drivetrain") or attrs.get("drivetrain")),
        # Colors are None (not "") when unknown, because the shared contract says so.
        "exterior_color": _text(
            js_data.get("exteriorColor") or attrs.get("extcolor") or product.get("color")
        ) or None,
        "interior_color": _text(js_data.get("interiorColor") or attrs.get("intcolor")) or None,
        "msrp": safe_float(js_data.get("msrp")),
        "selling_price": safe_float(js_data.get("displayedPrice")),
        "listing_url": url,
        "condition": condition,
    }

    # --- Source 4: plain-text fallbacks, only for the fields still blank.
    if not raw["trim"]:
        raw["trim"] = _parse_trim(
            _text(vehicle.get("name") or product.get("name") or attrs.get("name")),
            raw["make"],
            raw["model"],
        )

    if not raw["exterior_color"]:
        m = re.search(
            r'Exterior\s*Color</span>\s*<span[^>]*title="([^"]+)"', html, re.IGNORECASE
        )
        if m:
            raw["exterior_color"] = m.group(1).strip()

    if not raw["interior_color"]:
        m = re.search(
            r'Interior\s*Color</span>\s*<span[^>]*title="([^"]+)"', html, re.IGNORECASE
        )
        if m:
            raw["interior_color"] = m.group(1).strip()

    if not raw["drivetrain"]:
        m = re.search(r"DriveType:\s*([^<\n]+)", html)
        if m:
            raw["drivetrain"] = m.group(1).strip()

    # Price fallbacks. If neither price came from the JavaScript blob, the structured
    # data "offers" price is the number the shopper actually sees, so it is the selling
    # price, not the MSRP.
    if not raw["msrp"] and not raw["selling_price"]:
        raw["selling_price"] = safe_float(
            (vehicle.get("offers") or {}).get("price")
            or (product.get("offers") or {}).get("price")
        )
    # MSRP from the data- attribute, but ONLY for new vehicles. On a used listing
    # DealerOn reuses data-msrp for the asking price, and a "sticker price" on a
    # three-year-old truck would be a made-up number in your reports.
    if not raw["msrp"] and raw["condition"] == "new":
        raw["msrp"] = safe_float(attrs.get("msrp"))

    hp = re.search(r"Horse\s*Power:\s*(\d+)", html)
    raw["horsepower"] = safe_int(hp.group(1)) if hp else None

    raw["mileage"] = _extract_mileage(html, js_data, vehicle, attrs)
    raw["photo_urls"] = _extract_photos(html, base_url, vin)

    # normalize_vehicle does the shared clean-up every platform gets: title casing,
    # drivetrain wording ("Four Wheel Drive" -> "4WD"), interior color clean-up, etc.
    result = normalize_vehicle(raw)

    # If the site never said what the drivetrain is, ask the government's free VIN
    # decoder. This costs an extra request per vehicle, so we only do it when needed.
    if not result.get("drivetrain"):
        result["drivetrain"] = decode_drivetrain_from_vin(result.get("vin") or "")

    return result


# ---------------------------------------------------------------------------
# Step 3: the one function the rest of the program calls
# ---------------------------------------------------------------------------


def scrape(dealer, limit=None):
    """Scrape a DealerOn store and return a list of vehicle dicts.

    dealer: one entry from config/dealers.yml (needs at least "url").
    limit:  stop after this many vehicle pages. Use it for a quick demo run
            (`--limit 20`) instead of waiting on 700+ pages.
    """
    base_url = dealer["url"].rstrip("/")
    condition = dealer.get("condition", "new")
    workers = safe_int(os.environ.get("SCRAPER_WORKERS")) or DEFAULT_WORKERS

    print("  [DealerOn] Reading sitemap.xml for %s..." % base_url)
    items = collect_vehicle_urls(base_url, condition)
    print("    Found %d %s vehicle pages in the sitemap" % (len(items), condition))

    if not items:
        print("    WARNING: no vehicles found. The site may be down, may not be")
        print("             DealerOn, or may have no '%s' inventory right now." % condition)
        return []

    # Honour --limit right here, before we spend any time downloading pages.
    if limit is not None and limit > 0 and len(items) > limit:
        print("    LIMITING to the first %d of %d vehicles (demo mode)" % (limit, len(items)))
        items = items[:limit]

    print("    Opening %d vehicle pages with %d workers..." % (len(items), workers))

    vehicles = []
    errors = 0
    completed = 0
    total = len(items)

    def _scrape_one(item):
        return parse_vdp(item["url"], base_url, item["vin"], item["condition"])

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_scrape_one, item): item for item in items}
        for future in as_completed(futures):
            completed += 1
            item = futures[future]
            try:
                vdata = future.result()
                # A vehicle with no VIN cannot be stored (VIN is half of the database
                # key), so fall back to the VIN we read out of the URL.
                if not vdata.get("vin"):
                    vdata["vin"] = item["vin"]
                vehicles.append(vdata)
            except Exception as exc:  # one bad page must never kill the whole run
                errors += 1
                if errors <= MAX_ERRORS_PRINTED:
                    print("    ERROR on %s: %s" % (item["url"], exc))
                elif errors == MAX_ERRORS_PRINTED + 1:
                    print("    (further errors hidden; the count keeps going up)")
            if completed % PROGRESS_EVERY == 0 or completed == total:
                print("    Scraped %d/%d (%d errors)" % (completed, total, errors))

    # Optional: some stores sell several brands but you only care about one.
    # Set `makes: [GMC]` on the dealer in config/dealers.yml. We filter here, after
    # parsing, because a DealerOn URL mixes the city name and the make together with
    # dashes ("/new-Grand-Rapids-2025-GMC-...") and guessing from the URL is unreliable.
    makes_filter = dealer.get("makes")
    if makes_filter:
        wanted = set(m.strip().lower() for m in makes_filter)
        before = len(vehicles)
        vehicles = [v for v in vehicles if (v.get("make") or "").strip().lower() in wanted]
        print("    Kept %d of %d vehicles matching makes: %s"
              % (len(vehicles), before, ", ".join(makes_filter)))

    print("    Done: %d vehicles with usable data" % len(vehicles))
    return vehicles
