"""
Dealer.com inventory scraper.

PLAIN ENGLISH: Some dealership websites are built by Dealer.com (a Cox Automotive
product). If your site's pages have addresses like ".../new/Chevrolet/2024-Silverado-...htm"
and the page visibly "pops in" a second after it loads, you are probably on Dealer.com.

Those sites are the hardest ones we scrape, for two reasons:

  1. The inventory you see on screen is NOT in the page's HTML. The page loads empty
     and then a bit of JavaScript asks a private data feed for the vehicles. So there
     is no way to do this with a simple "download the page" request -- we have to run
     a real (invisible) web browser and let the site's own JavaScript do the asking.
  2. The site sits behind Akamai bot protection. Akamai hands out a set of cookies to
     real browsers and blocks everything else. Driving an actual browser gets us those
     cookies for free.

  3. (The annoying bonus round) The vehicle list feed does NOT include prices. Prices
     only live on each individual vehicle's detail page. So after we get the list, we
     go back and pull pricing out of each vehicle page, ten at a time.

WHAT YOU NEED FROM YOUR OWN SITE: a "site_id". Dealer.com's data feed will not answer
without it. See the error message in scrape() below -- it tells you exactly where to
find yours.

This whole file runs a headless browser, which means there is NO visible window. It can
look frozen for a couple of minutes. That is why almost every step here prints a line of
progress: the log is your only sign of life.
"""

import time

from ..normalize import normalize_vehicle, safe_float, decode_drivetrain_from_vin


# ---------------------------------------------------------------------------
# Settings you might reasonably want to tune
# ---------------------------------------------------------------------------

# Dealer.com silently caps every response at 35 vehicles no matter what page size we
# ask for. Asking for 100 does not get you 100 -- it gets you 35 and a wrong idea of
# where the next page starts. So we ask for exactly what we are going to get.
PAGE_SIZE = 35

# How many vehicle detail pages to fetch inside a single trip into the browser.
# Each trip has overhead, so batching helps; but a huge batch means one slow page
# stalls the whole batch and we go a long time with nothing to print.
VDP_BATCH_SIZE = 10

# The listing feed sometimes returns a 5xx under load. Retry with a growing pause.
MAX_RETRIES = 3

# We cap stored photos. A vehicle can have 40+ images and we do not need them all.
MAX_PHOTOS = 10

# The fields we ask the listing feed to include for each vehicle. Dealer.com only
# returns what you explicitly request, so anything missing from this list comes back
# blank no matter how well-populated it is in the dealer's inventory system.
_LISTING_ATTRIBUTES = [
    "askingPrice", "bodyStyle", "cityMpg", "driveLine",
    "engine", "extColor", "fuelType", "highwayMpg",
    "intColor", "make", "mileage", "model", "msrp",
    "odometer", "salePrice", "stockNumber", "transmission",
    "trim", "type", "vin", "year", "internetPrice",
    "invoicePrice",
]

# The price fields we dig out of each vehicle detail page. Dealer.com embeds a blob of
# JSON called DDC.dataLayer in the page source; these are the keys we care about.
_PRICING_FIELDS = ["askingPrice", "msrp", "internetPrice", "salePrice", "retailValue"]

# Dealer.com serves every vehicle photo from this one CDN host, and the feed gives us
# host-less paths like "/xxx/yyy.jpg". Without this prefix the photo links are broken.
_PICTURES_HOST = "https://pictures.dealer.com"


# ---------------------------------------------------------------------------
# Browser plumbing
# ---------------------------------------------------------------------------


def _load_playwright():
    """
    Import Playwright, or explain how to install it.

    Playwright is the tool that drives the invisible browser. It is a two-step install
    (the Python package, then the actual browser binary), and forgetting step two is
    the single most common setup mistake, so we spell both out.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "This dealership's website is built on Dealer.com, which can only be read "
            "with a real browser, and Playwright is not installed.\n"
            "Fix it with these two commands (BOTH are required):\n"
            "    pip install playwright\n"
            "    playwright install chromium"
        )
    return sync_playwright


def _open_browser_session(pw, base_url, user_agent):
    """
    Start the invisible browser and visit the dealer's homepage once.

    WHY THE HOMEPAGE VISIT MATTERS: we never scrape anything off that homepage. We load
    it purely so Akamai runs its checks and hands our browser the "you are a human"
    cookies. Every request we make after this rides on those cookies. Skip this and
    the data feed returns 403 forever.
    """
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(user_agent=user_agent)
    page = context.new_page()

    print("    Opening an invisible browser and warming up the session...")
    page.goto(base_url.rstrip("/") + "/", wait_until="domcontentloaded", timeout=30000)
    # Akamai's cookie handshake finishes a beat after the HTML arrives. Two seconds is
    # empirically enough; without the wait the very first API call often fails.
    page.wait_for_timeout(2000)
    print("    Browser session ready.")

    return browser, page


def _page_identifiers(site_id, condition):
    """
    Dealer.com needs to know WHICH inventory page we are pretending to be.

    New and used inventory are two different pages on a Dealer.com site, and the feed
    keys off these two strings. Ask the NEW page for used cars and you get an empty
    list rather than an error, which is a maddening way to spend an afternoon.
    """
    suffix = "USED" if condition == "used" else "NEW"
    page_alias = "INVENTORY_LISTING_DEFAULT_AUTO_" + suffix
    page_id = site_id + "_SITEBUILDER_INVENTORY_SEARCH_RESULTS_AUTO_" + suffix + "_V1_1"
    return page_alias, page_id


# ---------------------------------------------------------------------------
# Step 1: the vehicle list
# ---------------------------------------------------------------------------

# This JavaScript runs INSIDE the dealer's own website, in our invisible browser.
# That is the whole trick: because the code is running on their page, the request it
# makes looks exactly like the site's own request -- same origin, same cookies, same
# everything -- so Akamai waves it through.
_FETCH_INVENTORY_JS = r"""
async ([siteId, pageAlias, pageId, pageSize, start, attributes]) => {
    try {
        const resp = await fetch('/api/widget/ws-inv-data/getInventory', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                siteId: siteId,
                locale: 'en_US',
                device: 'DESKTOP',
                pageAlias: pageAlias,
                pageId: pageId,
                windowId: 'inventory-data-bus2',
                widgetName: 'ws-inv-data',
                inventoryParameters: {sz: String(pageSize), start: String(start)},
                required: {display: {attributes: attributes}}
            })
        });
        if (!resp.ok) return {error: 'HTTP ' + resp.status};
        return await resp.json();
    } catch (e) {
        return {error: e.message};
    }
}
"""


def _fetch_inventory_page(page, site_id, condition, start):
    """Ask the feed for one page (up to 35 vehicles) starting at offset `start`."""
    page_alias, page_id = _page_identifiers(site_id, condition)
    return page.evaluate(
        _FETCH_INVENTORY_JS,
        [site_id, page_alias, page_id, PAGE_SIZE, start, _LISTING_ATTRIBUTES],
    )


def _fetch_all_inventory(page, site_id, condition):
    """
    Page through the feed until we have every vehicle.

    Returns the raw vehicle dictionaries exactly as Dealer.com gave them to us --
    messy, nested, and not yet in our shared shape. Cleaning happens later.
    """
    all_vehicles = []
    start = 0
    total = None

    while True:
        data = None
        for attempt in range(1, MAX_RETRIES + 1):
            data = _fetch_inventory_page(page, site_id, condition, start)
            if isinstance(data, dict) and "error" not in data:
                break
            reason = data.get("error") if isinstance(data, dict) else "no response"
            print("    Feed error (%s), retry %d of %d..." % (reason, attempt, MAX_RETRIES))
            # Back off a little longer each time rather than hammering a struggling server.
            time.sleep(2 * attempt)
        else:
            print("    Giving up on this dealer's feed at vehicle #%d." % start)
            break

        vehicles = data.get("inventory", []) or []
        page_info = data.get("pageInfo", {}) or {}

        if total is None:
            total = page_info.get("totalCount", 0) or 0
            print("    The site says it has %d %s vehicles." % (total, condition))

        all_vehicles.extend(vehicles)
        print("    Retrieved %d of %d..." % (len(all_vehicles), total))

        # Stop when the feed runs dry OR when we have collected everything it promised.
        # Both checks matter: a feed that keeps returning the same page would otherwise
        # loop forever.
        if not vehicles or len(all_vehicles) >= total:
            break
        start += PAGE_SIZE

    return all_vehicles


# ---------------------------------------------------------------------------
# Step 2: prices, from each vehicle's detail page
# ---------------------------------------------------------------------------

# Also runs inside the dealer's site. For each vehicle detail page we download the raw
# HTML and pull the price numbers straight out of the embedded JSON with a pattern
# match. We do not parse the whole page -- we only need five numbers, and regex on a
# known-stable JSON blob is dramatically faster than rendering 300 pages.
_FETCH_PRICING_JS = r"""
async ([paths, pricingFields]) => {
    const results = {};
    for (const path of paths) {
        try {
            const resp = await fetch(path, {headers: {'Accept': 'text/html'}});
            if (!resp.ok) { results[path] = {}; continue; }
            const html = await resp.text();
            const pricing = {};
            for (const field of pricingFields) {
                const re = new RegExp('"' + field + '"\\s*:\\s*"(\\d+)"');
                const m = html.match(re);
                if (m) pricing[field] = parseFloat(m[1]);
            }
            results[path] = pricing;
        } catch (e) {
            results[path] = {};
        }
    }
    return results;
}
"""


def _fetch_vdp_pricing_batch(page, vdp_paths):
    """Fetch a handful of vehicle detail pages and return {path: {price field: number}}."""
    return page.evaluate(_FETCH_PRICING_JS, [vdp_paths, _PRICING_FIELDS])


def _collect_pricing(page, raw_vehicles):
    """
    Walk every vehicle detail page in batches and build {VIN: pricing dict}.

    This is the slow part of the run -- one web page per vehicle. On a 300-car store
    expect a couple of minutes, which is exactly why we print a running count.
    """
    path_to_vin = {}
    for v in raw_vehicles:
        link = v.get("link", "")
        vin = (v.get("vin") or "").upper()
        if link and vin:
            # A dict keyed by path also de-duplicates: two listings occasionally share
            # a detail page, and fetching it twice is pure waste.
            path_to_vin[link] = vin

    vdp_paths = list(path_to_vin.keys())
    print("  [Dealer.com] Reading prices from %d vehicle pages, %d at a time..."
          % (len(vdp_paths), VDP_BATCH_SIZE))

    pricing_by_vin = {}
    for i in range(0, len(vdp_paths), VDP_BATCH_SIZE):
        batch = vdp_paths[i:i + VDP_BATCH_SIZE]
        batch_result = _fetch_vdp_pricing_batch(page, batch) or {}
        for path, pricing in batch_result.items():
            vin = path_to_vin.get(path)
            if vin and pricing:
                pricing_by_vin[vin] = pricing
        print("    Priced %d of %d vehicle pages..."
              % (min(i + VDP_BATCH_SIZE, len(vdp_paths)), len(vdp_paths)))

    return pricing_by_vin


# ---------------------------------------------------------------------------
# Digging values out of Dealer.com's awkward data shape
# ---------------------------------------------------------------------------


def _get_attribute(vehicle, attr_name):
    """
    Pull one value out of the vehicle's `attributes` list.

    Dealer.com does not hand us {"exteriorColor": "Red"}. It hands us a LIST of little
    name/value pairs: [{"name": "exteriorColor", "value": "Red"}, ...]. So looking up
    one field means scanning the list for it. These two helpers hide that.
    """
    for attr in vehicle.get("attributes", []) or []:
        if attr.get("name") == attr_name:
            return attr.get("value", "") or ""
    return ""


def _get_tracking_attribute(vehicle, attr_name):
    """
    Same idea, but for the `trackingAttributes` list.

    Dealer.com keeps two parallel sets of fields: one for display and one for their
    analytics tracking. Annoyingly, some values (engine, odometer) are reliably
    populated in only ONE of them, and which one varies by dealer -- so throughout
    this file we check both and take whichever answers.
    """
    for attr in vehicle.get("trackingAttributes", []) or []:
        if attr.get("name") == attr_name:
            return attr.get("value", "") or ""
    return ""


def _photo_urls(vehicle):
    """Build usable photo links, adding the CDN host to the host-less paths we get."""
    urls = []
    for img in vehicle.get("images", []) or []:
        uri = img.get("uri")
        if not uri:
            continue
        if not uri.startswith("http"):
            uri = _PICTURES_HOST + uri
        urls.append(uri)
    return urls[:MAX_PHOTOS]


def _build_vehicle(raw, base_url, pricing, condition):
    """
    Turn one raw Dealer.com vehicle into our shared vehicle shape.

    We assemble the fields here and then hand the result to normalize_vehicle(), which
    is the one place in this project that decides how a color, a model name or a
    drivetrain should be spelled. Every platform scraper funnels through it so the
    Silverados from four different websites end up looking identical in the database.
    """
    pricing = pricing or {}

    # Price preference, most specific first. `internetPrice` is the advertised online
    # price (what a shopper actually sees), `askingPrice` is the fallback. The detail
    # page is more trustworthy than the listing feed, so it wins; the feed's copies are
    # only there for the occasional vehicle whose detail page failed to load.
    selling_price = (
        pricing.get("internetPrice")
        or pricing.get("askingPrice")
        or safe_float(_get_attribute(raw, "internetPrice"))
        or safe_float(_get_attribute(raw, "askingPrice"))
    )
    msrp = pricing.get("msrp") or safe_float(_get_attribute(raw, "msrp"))

    link = raw.get("link", "")
    listing_url = base_url.rstrip("/") + link if link else ""

    vehicle = {
        "vin": (raw.get("vin") or "").upper(),
        "stock_number": raw.get("stockNumber", "") or "",
        "year": raw.get("year"),
        "make": raw.get("make", "") or "",
        "model": raw.get("model", "") or "",
        "trim": raw.get("trim", "") or "",
        "body_type": _get_attribute(raw, "bodyStyle") or raw.get("bodyStyle", "") or "",
        "engine": (_get_tracking_attribute(raw, "engine")
                   or _get_attribute(raw, "normalEngine")),
        "fuel_type": _get_attribute(raw, "fuelType") or raw.get("fuelType", "") or "",
        "drivetrain": (_get_attribute(raw, "normalDriveLine")
                       or _get_tracking_attribute(raw, "driveLine")),
        "exterior_color": _get_attribute(raw, "exteriorColor") or None,
        "interior_color": _get_attribute(raw, "interiorColor") or None,
        "msrp": msrp,
        "selling_price": selling_price,
        "mileage": (_get_tracking_attribute(raw, "odometer")
                    or _get_attribute(raw, "odometer")),
        "horsepower": None,  # Dealer.com's feed simply does not carry horsepower.
        "listing_url": listing_url,
        "photo_urls": _photo_urls(raw),
        "condition": condition,
    }

    return normalize_vehicle(vehicle)


# ---------------------------------------------------------------------------
# The one function the rest of the project calls
# ---------------------------------------------------------------------------


def scrape(dealer, limit=None):
    """
    Scrape a Dealer.com store and return a list of vehicles in our shared shape.

    `dealer` is one entry from config/dealers.yml. `limit` caps how many vehicles we
    process -- handy for a quick test run, because a full store takes minutes.
    """
    base_url = dealer["url"]
    site_id = dealer.get("site_id")
    condition = (dealer.get("condition") or "new").lower()
    if condition not in ("new", "used"):
        condition = "new"

    # Checked BEFORE we launch anything, so a misconfigured dealer fails in a second
    # instead of after a browser start-up. If you are adding your own Dealer.com store
    # to dealers.yml, this is the wall you will hit, so the message is the fix.
    if not site_id:
        raise ValueError(
            "%s is a Dealer.com site, and Dealer.com will not return inventory without "
            "a 'site_id'.\n"
            "How to find yours:\n"
            "  1. Open %s in Chrome.\n"
            "  2. Right-click the page and choose 'View Page Source'.\n"
            "  3. Press Ctrl+F (Cmd+F on a Mac) and search for:  siteId\n"
            "  4. You will find something like  \"siteId\":\"mystoreabc\"  -- copy the "
            "value in quotes after the colon.\n"
            "  5. Add it to this dealer's entry in config/dealers.yml as:  "
            "site_id: mystoreabc"
            % (dealer.get("name") or dealer.get("key") or base_url, base_url)
        )

    sync_playwright = _load_playwright()

    # We ask http.py for the user-agent string so that every request this project makes
    # -- browser or not -- identifies itself the same honest way, in one editable place.
    from ..http import user_agent

    print("  [Dealer.com] Starting %s (%s inventory)."
          % (dealer.get("name") or dealer.get("key"), condition))

    with sync_playwright() as pw:
        browser = None
        try:
            browser, page = _open_browser_session(pw, base_url, user_agent())

            print("  [Dealer.com] Asking the site's data feed for the vehicle list...")
            raw_vehicles = _fetch_all_inventory(page, site_id, condition)
            print("    Got %d vehicles from the list feed." % len(raw_vehicles))

            if not raw_vehicles:
                print("    WARNING: no vehicles came back. Double-check the site_id and "
                      "whether this store actually has %s inventory." % condition)
                return []

            # Trim to `limit` here, before the slow per-vehicle pricing step, so a test
            # run of 5 cars genuinely takes seconds rather than minutes.
            if limit is not None and len(raw_vehicles) > limit:
                raw_vehicles = raw_vehicles[:limit]
                print("    Limiting this run to the first %d vehicles." % limit)

            pricing_by_vin = _collect_pricing(page, raw_vehicles)
        finally:
            # Always close the browser -- on success, on a crash, on anything. A leaked
            # headless Chrome keeps running invisibly and eats memory until you reboot.
            if browser is not None:
                browser.close()
                print("    Browser closed.")

    # Cleanup happens after the browser is shut, because none of it needs the browser
    # and there is no reason to hold Chrome open while we tidy dictionaries.
    print("  [Dealer.com] Cleaning up the data...")
    vehicles = []
    for raw in raw_vehicles:
        vin = (raw.get("vin") or "").upper()
        vehicle = _build_vehicle(raw, base_url, pricing_by_vin.get(vin, {}), condition)
        # A VIN is how we tell one car from another everywhere else in this project, so
        # a record without one is unusable and gets dropped rather than saved as junk.
        if not vehicle.get("vin"):
            continue
        # Last resort for drivetrain: ask the government's free VIN decoder. Some
        # Dealer.com stores leave the drive-line field blank on every single vehicle.
        if not vehicle.get("drivetrain"):
            vehicle["drivetrain"] = decode_drivetrain_from_vin(vehicle["vin"])
        vehicles.append(vehicle)

    print("  [Dealer.com] Done: %d vehicles ready." % len(vehicles))
    return vehicles
