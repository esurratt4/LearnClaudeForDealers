"""
The catch-all reader, for dealership sites that are not DealerOn, Dealer Inspire,
or Dealer.com.

WHAT THIS IS
------------
The other three adapters in this folder are specialists. Each one knows exactly where
its vendor hides the inventory, so each one gets nearly every field, nearly every time.

This file is the generalist. It knows nothing about your specific website. Instead it
uses two things that almost every website on the internet has, because Google requires
them:

  1. A SITEMAP -- a machine-readable list of every page on the site. Google uses it to
     find pages to index; we use it to find vehicle pages to read.
  2. STRUCTURED DATA -- a hidden block of JSON on each vehicle page that spells out
     "this is a 2024 GMC Sierra, VIN ..., price $54,995" in a standard format called
     schema.org. Dealers publish it so their cars show up properly in Google search
     results. That means it is usually accurate and usually up to date.

Because those two things are near-universal, this adapter will get *something* off
almost any dealer site in the country without anybody writing a line of code.

BE HONEST ABOUT WHAT THIS DOES NOT DO
-------------------------------------
This gets you roughly 70% of the way. Expect it to reliably find VIN, year, make,
model, price, and photos. Expect it to MISS things your specific site keeps somewhere
custom -- interior colour, engine description, horsepower, MSRP as distinct from the
selling price, and stock number are the usual casualties. When a field genuinely is not
on the page, this adapter leaves it empty rather than guessing. An empty cell you can
see is worth more than a made-up number you cannot.

>>> AND THAT GAP IS THE POINT OF THIS WORKSHOP <<<

When you run this against your store and see the holes, do not shrug and accept them,
and do not start reading HTML by hand. Do this instead:

    1. Run the scraper with --limit 5 so it is quick.
    2. Look at which columns came back empty.
    3. Open a vehicle page on your own site, right-click, "View Page Source", and
       save it somewhere.
    4. Hand both to Claude Code and ask, in exactly these words if you like:

         "scraper/platforms/generic.py is missing interior_color and msrp for my site.
          Here is the page source of one vehicle page. Read scraper/platforms/dealeron.py
          to see the pattern this project uses, then write me a new adapter at
          scraper/platforms/mysite.py that returns the same shape, and register it in
          scraper/platforms/__init__.py."

    5. Run it. Fix what is wrong by describing what is wrong.

A new adapter goes in **scraper/platforms/** next to this file, and gets one line added
to PLATFORMS in **scraper/platforms/__init__.py**. That is the whole job. The specialist
adapters in this folder are each a couple hundred lines, and you now have an assistant
that can read a website's source faster than you can scroll it. Building the exact
adapter your store deserves is an afternoon, not a project.
"""

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from urllib.parse import urljoin, urlparse
except ImportError:  # pragma: no cover
    raise

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

# How many vehicle pages to read at the same time.
# WHY this is safe: http.polite_get keeps its own queue and spaces every request to a
# site by that site's own crawl-delay, no matter how many workers we start. More
# workers means we overlap the *waiting*, not that we hammer anybody harder.
DEFAULT_WORKERS = 4

# We only ever follow sitemaps one level deep (a sitemap index pointing at sitemaps).
# Some big sites have hundreds of child sitemaps; reading them all would take longer
# than the workshop. This caps how many we open.
MAX_CHILD_SITEMAPS = 25

# Sitemaps we will guess at if robots.txt does not tell us where the real one is.
COMMON_SITEMAP_PATHS = ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml")

# A 17-character VIN. VINs never use I, O, or Q -- those letters were dropped so nobody
# mistakes them for 1 and 0 -- so this pattern deliberately skips them. The lookarounds
# stop us matching 17 characters out of the middle of a longer random string.
_VIN_RE = re.compile(r"(?<![A-Za-z0-9])([A-HJ-NPR-Z0-9]{17})(?![A-Za-z0-9])")

# Address shapes that suggest "this page is one specific car" rather than a search page.
_VDP_HINTS = re.compile(r"/inventory/|/vehicle|/new-|/used-|/certified", re.IGNORECASE)

# Address shapes that are definitely NOT one specific car, even though they match above.
_NOT_A_VDP = re.compile(
    r"/inventory/?$|/search|/compare|/quote|/finance|/service|/parts|/trade|/specials",
    re.IGNORECASE,
)

# schema.org calls the "@type" of a car one of these.
_VEHICLE_TYPES = ("vehicle", "car", "motorcycle", "truck", "bus", "motorizedbicycle")
_PRODUCT_TYPES = ("product", "individualproduct", "productmodel")

# schema.org writes drivetrains as clunky URLs like
# "http://schema.org/AllWheelDriveConfiguration". Translate to dealer English first;
# normalize.standardize_drivetrain finishes the job.
_DRIVE_WHEEL_MAP = {
    "allwheeldriveconfiguration": "AWD",
    "fourwheeldriveconfiguration": "4WD",
    "frontwheeldriveconfiguration": "FWD",
    "rearwheeldriveconfiguration": "RWD",
}

# Makes whose names are two words, so "2024 Land Rover Defender" does not come out as a
# Land with the model "Rover Defender". Only needed when we have to guess a vehicle's
# details from its page title.
_TWO_WORD_MAKES = (
    "land rover", "alfa romeo", "aston martin", "rolls royce", "rolls-royce",
    "mercedes benz", "general motors",
)


# ---------------------------------------------------------------------------
# Step 1: find the sitemap
# ---------------------------------------------------------------------------


def _fetch(url, timeout=30, retries=2, browser=True):
    """Fetch a page, and return "" instead of blowing up when anything goes wrong.

    Discovery is full of dead ends on purpose -- we guess three sitemap addresses
    knowing two will 404 -- so a failure here is information, not an emergency.
    """
    try:
        return polite_get(url, timeout=timeout, retries=retries, allow_browser_fallback=browser) or ""
    except Exception:  # noqa: BLE001 - includes PermissionError when robots.txt says no
        return ""


def find_sitemaps(base_url):
    """Work out where this site lists its pages. Returns a list of sitemap addresses.

    We ask robots.txt first. Sites are supposed to declare their sitemap there, and a
    declared address beats a guessed one -- plenty of dealer sites keep the real list at
    something like /sitemap_vehicles.xml that we would never think to try.
    """
    found = []
    seen = set()

    def _remember(url):
        clean = (url or "").strip()
        if clean and clean not in seen:
            seen.add(clean)
            found.append(clean)

    robots = _fetch(base_url + "/robots.txt", timeout=15, retries=1, browser=False)
    for line in re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots):
        _remember(line)

    for path in COMMON_SITEMAP_PATHS:
        _remember(base_url + path)

    return found


def _locations(xml):
    """Pull every <loc>...</loc> address out of a sitemap."""
    out = []
    for raw in re.findall(r"<loc>(.*?)</loc>", xml, re.DOTALL):
        url = raw.strip()
        # Sitemaps are XML, so "&" is written "&amp;". Put it back.
        url = url.replace("&amp;", "&").replace("&#x2B;", "+").replace("&apos;", "'")
        if url.lower().startswith("http"):
            out.append(url)
    return out


def _looks_like_a_sitemap(url):
    """Is this <loc> pointing at another sitemap rather than at a page?"""
    low = url.lower().split("?")[0]
    return low.endswith(".xml") or low.endswith(".xml.gz") or "sitemap" in low


def _sitemap_priority(url):
    """Sort key: 0 for sitemaps whose name suggests cars, 1 for everything else.

    A big site's sitemap index can list a sitemap for the blog, one for staff bios, one
    for each inventory page. We only open MAX_CHILD_SITEMAPS of them, so spend that
    budget on the ones with "inventory" or "vehicle" in the name.
    """
    low = url.lower()
    for word in ("inventory", "vehicle", "vdp", "new", "used", "certified", "car"):
        if word in low:
            return 0
    return 1


def collect_candidate_urls(base_url):
    """Gather every address on this site that might be a single vehicle's page.

    Returns a plain list of web addresses. Following sitemap indexes one level down is
    enough for every dealer site we have seen -- deeper nesting exists in theory but not
    in this industry.
    """
    page_urls = []
    seen = set()
    child_sitemaps = []

    for sitemap_url in find_sitemaps(base_url):
        xml = _fetch(sitemap_url, timeout=30, retries=1, browser=False)
        if "<loc>" not in xml:
            continue
        print("    Reading sitemap: %s" % sitemap_url)
        for loc in _locations(xml):
            if _looks_like_a_sitemap(loc):
                # .gz sitemaps arrive as compressed bytes, which come through as
                # gibberish text. Skipping them is better than parsing noise.
                if loc.lower().endswith(".gz"):
                    continue
                if loc not in seen:
                    seen.add(loc)
                    child_sitemaps.append(loc)
            elif loc not in seen:
                seen.add(loc)
                page_urls.append(loc)

    # Read the child sitemaps most likely to hold cars first, so that if we hit the cap
    # above we have spent it on inventory rather than on the blog.
    child_sitemaps.sort(key=_sitemap_priority)

    for child in child_sitemaps[:MAX_CHILD_SITEMAPS]:
        xml = _fetch(child, timeout=30, retries=1, browser=False)
        if "<loc>" not in xml:
            continue
        print("    Reading sitemap: %s" % child)
        for loc in _locations(xml):
            if not _looks_like_a_sitemap(loc) and loc not in seen:
                seen.add(loc)
                page_urls.append(loc)

    return page_urls


# ---------------------------------------------------------------------------
# Step 2: keep only the vehicle pages
# ---------------------------------------------------------------------------


def _vin_from_url(url):
    """A dealer URL usually ends with the VIN. Pull it out, or return ""."""
    match = _VIN_RE.search(url.upper())
    return match.group(1) if match else ""


def _condition_from_url(url, default="new"):
    """Guess new vs used from the address. Used wins ties: a "certified pre-owned" page
    often contains the word "new" somewhere in the model name, but never the reverse.
    """
    low = url.lower()
    for marker in ("/used", "-used-", "/pre-owned", "/preowned", "/certified", "/cpo"):
        if marker in low:
            return "used"
    for marker in ("/new", "-new-"):
        if marker in low:
            return "new"
    return default


def filter_vehicle_urls(urls, condition="new"):
    """Narrow a whole sitemap down to the pages that are probably single vehicles.

    Two passes, and the first one matters most:

    If ANY address on this site contains a 17-character VIN, we keep only those. A VIN
    in the address is as close to proof as we get, and using it throws out the search
    pages, the "New Inventory" landing page and the blog in one move. Only when no
    address anywhere has a VIN do we fall back to the fuzzier "does it look like an
    inventory address" test, which is right more often than not but will occasionally
    hand us a listing page.
    """
    with_vin = [u for u in urls if _vin_from_url(u)]

    if with_vin:
        candidates = with_vin
    else:
        candidates = [
            u for u in urls
            if _VDP_HINTS.search(u) and not _NOT_A_VDP.search(u)
        ]

    # Now split by new/used. If the site does not say in its addresses we cannot tell
    # yet, so we keep everything and sort it out once we have read the pages -- better
    # to read a few extra pages than to silently return zero cars.
    matching = [u for u in candidates if _condition_from_url(u, default="") == condition]
    if matching:
        return matching

    return candidates


# ---------------------------------------------------------------------------
# Step 3: read one vehicle page
# ---------------------------------------------------------------------------


def _json_ld_blocks(html):
    """Return the raw text of every structured-data block on the page."""
    return re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    )


def _collect_nodes(data, out, depth=0):
    """Flatten structured data into a simple list of dictionaries.

    WHY this is recursive: sites nest this stuff differently. Some publish one Vehicle
    object. Some publish a list. Some wrap everything in an "@graph". Some bury the car
    inside a breadcrumb list. Rather than guess the shape, we walk the whole thing and
    look at every dictionary we find.
    """
    if depth > 6:  # a guard against a self-referencing document spinning forever
        return
    if isinstance(data, list):
        for item in data:
            _collect_nodes(item, out, depth + 1)
    elif isinstance(data, dict):
        out.append(data)
        for key in ("@graph", "mainEntity", "mainEntityOfPage", "itemListElement", "item", "subjectOf"):
            if key in data:
                _collect_nodes(data[key], out, depth + 1)


def structured_data_nodes(html):
    """Every structured-data object on the page, flattened into one list."""
    nodes = []
    for block in _json_ld_blocks(html):
        text = block.strip()
        # Some sites wrap the JSON in an XML CDATA section or an HTML comment.
        text = re.sub(r"^<!\[CDATA\[", "", text)
        text = re.sub(r"\]\]>$", "", text.strip())
        text = re.sub(r"^<!--|-->$", "", text.strip()).strip()
        if not text:
            continue
        try:
            _collect_nodes(json.loads(text), nodes)
        except ValueError:
            # Malformed JSON on a dealer site is common and not our problem. Move on.
            continue
    return nodes


def _types_of(node):
    """The @type of a node, lowercased, as a set (it is sometimes a list)."""
    raw = node.get("@type") or node.get("type") or ""
    if isinstance(raw, str):
        raw = [raw]
    return set(str(t).split("/")[-1].strip().lower() for t in raw if t)


def pick_vehicle_node(nodes):
    """Choose the one object on the page that describes the car.

    Preference order, best first:
      1. anything carrying a VIN -- unambiguous
      2. anything typed Vehicle/Car
      3. anything typed Product, which is how some sites list cars
    """
    for node in nodes:
        if node.get("vehicleIdentificationNumber"):
            return node
    for node in nodes:
        if _types_of(node) & set(_VEHICLE_TYPES):
            return node
    for node in nodes:
        if _types_of(node) & set(_PRODUCT_TYPES):
            return node
    return {}


# --- little readers for messy values ---------------------------------------


def _text(value):
    """Structured data writes the same fact three ways. Get a plain string out of any.

    "GMC"                      -> "GMC"
    {"name": "GMC"}            -> "GMC"
    [{"name": "GMC"}]          -> "GMC"
    """
    if value is None:
        return ""
    if isinstance(value, list):
        return _text(value[0]) if value else ""
    if isinstance(value, dict):
        for key in ("name", "value", "@value", "model", "title"):
            if value.get(key) is not None:
                return _text(value[key])
        return ""
    return str(value).strip()


def _number(value):
    """Same idea as _text, but for quantities like {"value": 310, "unitCode": "BHP"}."""
    if isinstance(value, dict):
        return _number(value.get("value"))
    if isinstance(value, list):
        return _number(value[0]) if value else None
    return safe_float(value)


def _first(*values):
    """The first of these that is actually filled in."""
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return ""


def _offers(node):
    """Flatten the offers block, which may be one offer or several."""
    raw = node.get("offers")
    if not raw:
        return []
    if isinstance(raw, dict):
        raw = [raw]
    out = []
    for offer in raw:
        if isinstance(offer, dict):
            out.append(offer)
            spec = offer.get("priceSpecification")
            if isinstance(spec, dict):
                out.append(spec)
            elif isinstance(spec, list):
                out.extend(s for s in spec if isinstance(s, dict))
    return out


def _prices(node, html):
    """Work out (msrp, selling_price).

    Most dealer pages publish only ONE number in structured data: the price they want
    you to see. We treat that as the selling price, because that is what it is, and go
    looking separately for an MSRP. If we only ever find one number, MSRP stays empty
    rather than being set equal to the selling price -- pretending there is no discount
    would quietly break every price comparison this tool exists to make.
    """
    selling = None
    msrp = None

    for offer in _offers(node):
        price = _number(_first(offer.get("price"), offer.get("lowPrice")))
        if price and price > 100:  # ignore "0" and placeholder dollars
            kind = str(offer.get("priceType") or offer.get("@type") or "").lower()
            if "list" in kind or "msrp" in kind or "suggested" in kind:
                msrp = msrp or price
            elif selling is None:
                selling = price

    if msrp is None:
        # Last resort: most dealer CMSs leave an msrp field somewhere in the page code
        # even when it is not in the structured data.
        match = re.search(r'["\']?msrp["\']?\s*[:=]\s*["\']?([0-9][0-9,.]*)', html, re.IGNORECASE)
        if match:
            msrp = safe_float(match.group(1).replace(",", ""))

    if selling is None:
        meta_price = _meta(html, "product:price:amount")
        selling = safe_float(meta_price.replace(",", "").replace("$", "")) if meta_price else None

    # A "MSRP" lower than the asking price is a mis-read, not a deal. Drop it.
    if msrp and selling and msrp < selling:
        msrp = None

    return msrp, selling


def _meta(html, prop):
    """Read an og: / meta tag. Handles both attribute orders, because both are common."""
    escaped = re.escape(prop)
    patterns = (
        r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]+content=["\']([^"\']*)["\']' % escaped,
        r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']%s["\']' % escaped,
    )
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _split_title(title):
    """Break "2024 GMC Sierra 1500 Denali" into year / make / model / trim.

    Only used when structured data left those fields out. It is a guess, and the
    boundary between model and trim is genuinely ambiguous in English, so we take the
    first word after the make as the model and give the rest to the trim.
    """
    cleaned = re.sub(r"\s+", " ", (title or "").strip())
    # Page titles often carry a "| Dealer Name" suffix. Cut it.
    cleaned = re.split(r"\s+[|–—-]\s+", cleaned)[0].strip()

    match = re.match(r"^(?:New|Used|Certified(?:\s+Pre-Owned)?|Pre-Owned)?\s*(\d{4})\s+(.*)$", cleaned, re.IGNORECASE)
    if not match:
        return None, "", "", ""

    year = safe_int(match.group(1))
    rest = match.group(2).strip()
    low = rest.lower()

    make = ""
    for candidate in _TWO_WORD_MAKES:
        if low.startswith(candidate):
            make = rest[: len(candidate)]
            rest = rest[len(candidate):].strip()
            break
    if not make:
        parts = rest.split(" ", 1)
        make = parts[0]
        rest = parts[1] if len(parts) > 1 else ""

    parts = rest.split(" ", 1)
    model = parts[0] if parts and parts[0] else ""
    trim = parts[1].strip() if len(parts) > 1 else ""
    return year, make, model, trim


def _photos(node, html, page_url):
    """Collect photo addresses, turning any relative ones into full addresses."""
    raw = node.get("image") or node.get("photo") or []
    if isinstance(raw, (str, dict)):
        raw = [raw]

    urls = []
    for item in raw:
        if isinstance(item, dict):
            item = item.get("url") or item.get("contentUrl") or ""
        if item:
            urls.append(urljoin(page_url, str(item).strip()))

    if not urls:
        og_image = _meta(html, "og:image")
        if og_image:
            urls.append(urljoin(page_url, og_image))

    deduped = []
    for url in urls:
        if url not in deduped:
            deduped.append(url)
    return deduped


def _drivetrain(node):
    """Turn schema.org's drivetrain URL into AWD / 4WD / FWD / RWD."""
    raw = _text(_first(node.get("driveWheelConfiguration"), node.get("vehicleTransmission")))
    if not raw:
        return ""
    key = raw.split("/")[-1].strip().lower().replace(" ", "")
    return _DRIVE_WHEEL_MAP.get(key, raw)


def _condition_from_node(node, url, default):
    """new vs used, from the structured data if it says, otherwise from the address."""
    raw = _text(node.get("itemCondition")).lower()
    if "new" in raw:
        return "new"
    if "used" in raw or "refurb" in raw:
        return "used"
    return _condition_from_url(url, default)


# --- putting one page together ---------------------------------------------


def parse_vehicle_page(html, url, default_condition="new"):
    """Turn one vehicle page into one vehicle dictionary, or None if it is not a car.

    Returns None when the page has no VIN. Without a VIN we cannot tell one truck from
    another, and the database is keyed on it, so a VIN-less row is worse than no row.
    """
    nodes = structured_data_nodes(html)
    node = pick_vehicle_node(nodes)

    vin = _text(_first(
        node.get("vehicleIdentificationNumber"),
        node.get("vin"),
        node.get("productID"),
    )).strip().upper()

    # The address itself is a reliable second source, and often the only one.
    if not _VIN_RE.match(vin):
        vin = _vin_from_url(url)
    if not vin:
        # Last try: some sites print the VIN in the page body but not in the JSON.
        match = re.search(r"VIN[:\s#]*([A-HJ-NPR-Z0-9]{17})", html, re.IGNORECASE)
        vin = match.group(1).upper() if match else ""
    if not vin:
        return None

    title = _first(_text(node.get("name")), _meta(html, "og:title"))
    guessed_year, guessed_make, guessed_model, guessed_trim = _split_title(title)

    engine = node.get("vehicleEngine") or {}
    if isinstance(engine, list):
        engine = engine[0] if engine else {}
    if not isinstance(engine, dict):
        engine = {}

    horsepower = None
    power = engine.get("enginePower")
    if power is not None:
        horsepower = safe_int(_number(power))

    msrp, selling_price = _prices(node, html)

    raw_vehicle = {
        "vin": vin,
        "stock_number": _text(_first(node.get("sku"), node.get("mpn"), node.get("serialNumber"))),
        "year": safe_int(_first(
            _text(node.get("vehicleModelDate")),
            _text(node.get("modelDate")),
            _text(node.get("productionDate"))[:4],
        )) or guessed_year,
        "make": _text(_first(node.get("manufacturer"), node.get("brand"))) or guessed_make,
        "model": _text(node.get("model")) or guessed_model,
        "trim": _text(_first(node.get("vehicleConfiguration"), node.get("trim"))) or guessed_trim,
        "body_type": _text(node.get("bodyType")),
        "engine": _text(_first(engine.get("name"), engine.get("engineType"), engine.get("description"))),
        "fuel_type": _text(_first(node.get("fuelType"), engine.get("fuelType"))),
        "drivetrain": _drivetrain(node),
        "exterior_color": _text(_first(node.get("color"), node.get("vehicleExteriorColor"))) or None,
        "interior_color": _text(node.get("vehicleInteriorColor")) or None,
        "msrp": msrp,
        "selling_price": selling_price,
        "mileage": safe_int(_number(node.get("mileageFromOdometer"))),
        "horsepower": horsepower,
        "listing_url": url,
        "photo_urls": _photos(node, html, url),
        "condition": _condition_from_node(node, url, default_condition),
    }

    # normalize_vehicle is the shared tidy-up every adapter ends with: it uppercases the
    # VIN, fixes capitalisation, strips "$" out of prices and guarantees every field in
    # the contract exists. Never skip it -- the database and the reports assume it ran.
    vehicle = normalize_vehicle(raw_vehicle)

    # The drivetrain is the field generic sites hide most often, and it is the one a
    # dealer actually shops on. If the page did not say, ask the government's free VIN
    # decoder. One extra lookup per car, and only for the cars that need it.
    if not vehicle.get("drivetrain"):
        vehicle["drivetrain"] = decode_drivetrain_from_vin(vehicle["vin"])

    return vehicle


# ---------------------------------------------------------------------------
# The public entry point
# ---------------------------------------------------------------------------


def scrape(dealer, limit=None):
    """Scrape a dealership on an unknown website platform.

    dealer: one entry from config/dealers.yml (needs at least "url").
    limit:  stop after this many vehicle pages. Use it for a quick demo run
            (`--limit 20`) instead of waiting on hundreds of pages.

    Returns a list of vehicle dictionaries in this project's standard shape.
    """
    base_url = dealer["url"].rstrip("/")
    condition = dealer.get("condition", "new")
    makes = dealer.get("makes") or None
    workers = safe_int(os.environ.get("SCRAPER_WORKERS")) or DEFAULT_WORKERS

    print("  [Generic] Looking for a sitemap on %s..." % base_url)
    all_urls = collect_candidate_urls(base_url)
    print("    Sitemap listed %d pages in total" % len(all_urls))

    if not all_urls:
        print("    WARNING: no sitemap found. Without one this adapter is blind.")
        print("             Check the address in config/dealers.yml, then ask Claude Code")
        print("             to write a proper adapter in scraper/platforms/ for this site.")
        return []

    urls = filter_vehicle_urls(all_urls, condition)
    print("    %d of those look like %s vehicle pages" % (len(urls), condition))

    if not urls:
        print("    WARNING: none of the pages looked like vehicle listings.")
        print("             This site probably keeps its inventory somewhere custom --")
        print("             a good moment to have Claude Code write a real adapter.")
        return []

    if limit is not None and limit > 0 and len(urls) > limit:
        print("    LIMITING to the first %d of %d vehicles (demo mode)" % (limit, len(urls)))
        urls = urls[:limit]

    print("    Opening %d vehicle pages with %d workers..." % (len(urls), workers))

    vehicles = []
    errors = 0
    skipped = 0
    completed = 0

    def _read_one(url):
        html = polite_get(url)
        if not html:
            return None
        return parse_vehicle_page(html, url, condition)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_read_one, url): url for url in urls}
        for future in as_completed(futures):
            completed += 1
            url = futures[future]
            try:
                vehicle = future.result()
                if vehicle:
                    vehicles.append(vehicle)
                else:
                    # Not an error: this is how we find out a page was a search result
                    # or an accessory rather than a car.
                    skipped += 1
            except Exception as exc:  # noqa: BLE001
                errors += 1
                if errors <= 5:  # show the first few, then stop shouting
                    print("    ERROR reading %s: %s" % (url, exc))
            if completed % 25 == 0 or completed == len(urls):
                print("    Read %d/%d pages (%d errors)" % (completed, len(urls), errors))

    if skipped:
        print("    Skipped %d pages that had no VIN on them (not vehicle pages)" % skipped)

    # If this dealer only sells one or two brands, drop anything else. Useful when a
    # store's sitemap includes their used lot full of trade-ins.
    if makes:
        wanted = set(m.strip().lower() for m in makes if m)
        before = len(vehicles)
        vehicles = [v for v in vehicles if (v.get("make") or "").strip().lower() in wanted]
        if before != len(vehicles):
            print("    Kept %d of %d vehicles matching makes: %s" % (len(vehicles), before, ", ".join(makes)))

    print("    Found %d vehicles with usable data" % len(vehicles))

    # An honest word about what just happened, because the empty columns are the point.
    if vehicles:
        missing = [
            field for field in ("interior_color", "engine", "msrp", "stock_number", "horsepower")
            if not any(v.get(field) for v in vehicles)
        ]
        if missing:
            print("    NOTE: this generic reader found nothing for: %s" % ", ".join(missing))
            print("          That is normal. See the notes at the top of")
            print("          scraper/platforms/generic.py for how to have Claude Code")
            print("          write a proper adapter for this site.")

    return vehicles
