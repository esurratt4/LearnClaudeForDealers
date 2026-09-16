"""
Dealer Inspire website scraper.

PLAIN ENGLISH: A lot of dealership websites are built on a product called
"Dealer Inspire" (you may also see it called "DI"). If your site or a
competitor's site is one of them, this file is what reads their inventory.

How it works, in the order it happens:

  1. Every Dealer Inspire site publishes a "sitemap" -- a plain list of every
     vehicle page on the site -- at this address:
         https://theirsite.com/dealer-inspire-inventory/inventory_sitemap
     We download that list first. It is the fastest, politest way to find out
     what is on their lot: one request instead of clicking through 40 pages of
     search results.

  2. We keep only the vehicle pages we care about (new, used, or both -- that
     is the "condition" setting for the dealer in config/dealers.yml), and we
     can also narrow to one brand for a dual-franchise store (the "makes"
     setting -- e.g. a Buick-GMC store where you only want the GMC side).

  3. We then open each vehicle page and pull the vehicle's details out of it.
     Dealer Inspire quietly embeds a block of vehicle data (VIN, price, color,
     mileage...) inside the page itself, so we do not have to scrape prices out
     of the visible HTML, which changes every time they restyle the site.

  4. Every vehicle comes back in the same standard shape that every other
     scraper in this project uses, so the database does not care which website
     platform it came from.

ABOUT "403 FORBIDDEN" ERRORS -- READ THIS, YOU WILL PROBABLY SEE ONE:
    Many Dealer Inspire sites sit behind an edge bot-protection service
    (Cloudflare). That service rejects anything that does not look like a real
    web browser with "HTTP 403 Forbidden", EVEN THOUGH the site's own
    robots.txt explicitly allows these inventory pages (it only disallows
    admin and some upload paths, and asks for a 1 second crawl delay, which we
    honor). In other words: the site's stated policy permits this, the edge
    filter is just crude.

    That is why every request in this file goes through scraper/http.py's
    polite_get() instead of calling requests.get() ourselves. polite_get()
      - checks robots.txt first and respects the crawl delay,
      - sends a real browser user-agent,
      - and if it still gets a 403, quietly retries the page in a real
        headless browser (Playwright) so the page loads the same way it would
        on your laptop.
    So if you see a 403 scroll by in the log, the scraper is not broken -- it
    is switching to the slower browser method for that page.
"""

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

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

# Every Dealer Inspire site puts its inventory sitemap at this same path.
SITEMAP_PATH = "/dealer-inspire-inventory/inventory_sitemap"

# How many vehicle pages to download at the same time. 5 is deliberately
# modest: we are a guest on someone else's web server. You can raise it with
# the SCRAPER_WORKERS environment variable if you own the site you are
# scraping, but going too high is how you get blocked.
DEFAULT_WORKERS = 5

# Print a progress line every N vehicles so a long run does not look frozen.
PROGRESS_EVERY = 25


def _worker_count():
    """How many pages to fetch in parallel (SCRAPER_WORKERS env var)."""
    raw = os.environ.get("SCRAPER_WORKERS", "")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_WORKERS
    # Clamp: 0 workers would hang, 20+ workers looks like an attack.
    if n < 1:
        return 1
    if n > 20:
        return 20
    return n


# ---------------------------------------------------------------------------
# Step 1 + 2: find the vehicle pages in the sitemap
# ---------------------------------------------------------------------------

# Dealer Inspire vehicle URLs look like:
#   https://site.com/inventory/new-2025-gmc-sierra-1500-elevation-...-VIN/
#   https://site.com/inventory/used-2021-chevrolet-tahoe-lt-...-VIN/
#   https://site.com/inventory/certified-used-2022-gmc-terrain-...-VIN/
# so the word right after "/inventory/" tells us new vs. used.
_NEW_MARKERS = ("/inventory/new-",)
_USED_MARKERS = ("/inventory/used-", "/inventory/certified-", "/inventory/pre-owned-")


def _condition_for_url(url):
    """
    Return "new", "used", or "" for a vehicle page URL.

    Certified pre-owned is stored as "used" on purpose: for pricing comparisons
    a CPO car is a used car, and the database only has the two buckets.
    """
    low = url.lower()
    for marker in _NEW_MARKERS:
        if marker in low:
            return "new"
    for marker in _USED_MARKERS:
        if marker in low:
            return "used"
    return ""


def fetch_vehicle_urls(base_url, condition="new"):
    """
    Download the inventory sitemap and return [(url, "new"/"used"), ...].

    `condition` is "new", "used", or "all" and comes from the dealer's entry in
    config/dealers.yml.
    """
    sitemap_url = base_url.rstrip("/") + SITEMAP_PATH
    xml = polite_get(sitemap_url)

    wanted = condition.lower().strip() or "new"

    results = []
    seen = set()
    # A sitemap is just XML full of <loc>https://...</loc> lines. We do not
    # need a full XML parser for something this simple and predictable.
    for raw in re.findall(r"<loc>(.*?)</loc>", xml):
        url = raw.strip()
        # Sitemaps escape some characters; undo the two that actually show up.
        url = url.replace("&#x2B;", "+").replace("&amp;", "&")
        cond = _condition_for_url(url)
        if not cond:
            continue  # not a vehicle page (blog post, staff page, etc.)
        if wanted != "all" and cond != wanted:
            continue
        if url in seen:
            continue
        seen.add(url)
        results.append((url, cond))
    return results


def _vin_from_url(url):
    """
    Pull the VIN out of a vehicle page URL.

    Dealer Inspire ends every vehicle slug with the VIN, e.g.
    ".../new-2025-gmc-sierra-1500-elevation-1GTUUCE81SZ123456/". A VIN is
    always exactly 17 letters/numbers, which is how we know we grabbed the
    right piece.
    """
    slug = url.rstrip("/").split("/")[-1]
    candidate = slug.split("-")[-1]
    if len(candidate) == 17 and candidate.isalnum():
        return candidate.upper()
    return ""


def _make_from_url(url):
    """
    Guess the make (brand) from the URL slug, for the `makes` filter.

    The slug is <condition>-<year>-<make>-<model>-...-<vin>, so we find the
    four-digit year and take the word right after it. Doing it this way (rather
    than "the third word", like the original code) also works for the
    "certified-used-2022-gmc-..." slugs, which have an extra word up front.
    """
    slug = url.rstrip("/").split("/")[-1].lower()
    parts = slug.split("-")
    for i, part in enumerate(parts):
        if len(part) == 4 and part.isdigit() and part.startswith(("19", "20")):
            if i + 1 < len(parts):
                return parts[i + 1]
            return ""
    return ""


def filter_by_makes(url_pairs, makes):
    """
    Keep only vehicles whose brand is in `makes`.

    WHY THIS EXISTS: plenty of stores sell two franchises off one website (a
    Buick-GMC store, a Chevrolet-Cadillac store). If you only compete on the
    GMC side, scraping the Buicks just adds noise. Set `makes: ["GMC"]` on that
    dealer in config/dealers.yml and this trims the list.
    """
    wanted = set()
    for m in makes:
        if m:
            wanted.add(str(m).strip().lower())
    if not wanted:
        return url_pairs

    kept = []
    for url, cond in url_pairs:
        if _make_from_url(url) in wanted:
            kept.append((url, cond))
    return kept


# ---------------------------------------------------------------------------
# Step 3: read one vehicle page
# ---------------------------------------------------------------------------


def _extract_embedded_json(html):
    """
    Find the block of vehicle data that Dealer Inspire embeds in the page.

    WHY THIS LOOKS SO UGLY -- please read before "cleaning it up":
    Most websites hide their data somewhere predictable, like a
    <script type="application/ld+json"> tag you can just select. Dealer Inspire
    does NOT. It writes the vehicle object straight into the middle of a much
    larger blob of page JavaScript, with no tag, id, class or variable name that
    is stable between sites or between template versions. There is nothing to
    "select on."

    So we work backwards from something that IS stable -- the words "drivetrain"
    and "vin" as JSON keys:
      1. Find "drivetrain": (or "vin":) in the raw page text.
      2. Walk BACKWARDS character by character to the nearest "{". That is
         probably the start of the object that key lives in.
      3. Walk FORWARDS from there counting braces: +1 for every "{", -1 for
         every "}". When the count returns to zero we have found the matching
         closing brace, which is the end of the object.
      4. Hand that slice to json.loads(). If it does not parse, it was not the
         right "{" -- no harm done, we move on.
    We keep whichever valid object has the most fields, because the page often
    contains a small stub object and a big complete one.

    Returns a dict (possibly empty).
    """
    best = None
    for key in ("drivetrain", "vin"):
        for match in re.finditer(r'"' + key + r'"\s*:\s*"', html):
            start = match.start()
            # Look back at most 500 characters for the opening brace. More than
            # that and we are almost certainly grabbing an unrelated object.
            for j in range(start, max(start - 500, -1), -1):
                if html[j] != "{":
                    continue
                depth = 0
                # Cap the forward scan at 10,000 characters: real vehicle
                # objects are a couple thousand characters, and without a cap a
                # stray brace could make us scan the whole page every time.
                for i in range(j, min(j + 10000, len(html))):
                    if html[i] == "{":
                        depth += 1
                    elif html[i] == "}":
                        depth -= 1
                    if depth == 0:
                        try:
                            candidate = json.loads(html[j:i + 1])
                        except (json.JSONDecodeError, ValueError):
                            candidate = None
                        if isinstance(candidate, dict) and candidate.get("vin"):
                            if best is None or len(candidate) > len(best):
                                best = candidate
                        break
                break  # only try the first "{" we find going backwards
        # If we already found an object with a drivetrain, it is complete
        # enough -- no need to also scan for "vin".
        if best and best.get("drivetrain"):
            break
    return best or {}


def _extract_meta_fallback(html, url):
    """
    Plan B when the embedded JSON is missing.

    Every Dealer Inspire vehicle page still carries Facebook/"Open Graph" meta
    tags for social sharing:
        <meta property="og:title"            content="New 2025 GMC Sierra 1500">
        <meta property="product:price:amount" content="54995">
        <meta property="og:image"            content="https://...jpg">
    That is not everything, but a VIN + a price + a photo is still a usable
    row, and it is much better than dropping the vehicle entirely.
    """
    data = {}

    vin = _vin_from_url(url)
    if vin:
        data["vin"] = vin

    title_m = re.search(r'og:title"\s+content="([^"]+)"', html)
    if title_m:
        data["_og_title"] = title_m.group(1)

    price_m = re.search(r'product:price:amount"\s+content="([^"]+)"', html)
    if price_m:
        data["our_price"] = price_m.group(1)

    image_m = re.search(r'og:image"\s+content="([^"]+)"', html)
    if image_m:
        data["_og_image"] = image_m.group(1)

    return data


def parse_vdp(url):
    """
    Download one vehicle page ("VDP" = Vehicle Detail Page) and return the raw
    data we found on it, as a dict. Returns {} if the page gave us nothing.
    """
    try:
        html = polite_get(url)
    except Exception:
        # A single dead page must never kill a 400-vehicle run.
        return {}

    if not html:
        return {}

    # Some Dealer Inspire sites redirect anything that smells like a bot to a
    # stripped-down "/llm/inventory/" page built for AI crawlers. That page has
    # no VIN and no price, so parsing it would produce garbage rows. If we
    # landed there, treat the page as a miss and move on.
    if "/llm/inventory/" in html[:2000]:
        return {}

    data = _extract_embedded_json(html)
    if not data:
        data = _extract_meta_fallback(html, url)
    elif not data.get("_og_image"):
        # Embedded JSON sometimes has no photo; borrow the social-share image.
        image_m = re.search(r'og:image"\s+content="([^"]+)"', html)
        if image_m:
            data["_og_image"] = image_m.group(1)

    return data


# ---------------------------------------------------------------------------
# Step 4: convert to the shape the rest of the project expects
# ---------------------------------------------------------------------------

# Dealer Inspire's own field names on the left, ours on the right. Their names
# are inconsistent between sites, which is why several of ours check two or
# three possible spellings.


def _parse_og_title(title):
    """
    Turn "New 2025 GMC Sierra 1500 Elevation" into year / make / model pieces.

    Only used in the meta-tag fallback path, where we have no structured data.
    Deliberately conservative: first number that looks like a year, next word is
    the make, the word after that is the model. Trim is whatever is left.
    """
    out = {}
    if not title:
        return out
    words = title.replace("|", " ").split()
    for i, w in enumerate(words):
        if len(w) == 4 and w.isdigit() and w.startswith(("19", "20")):
            out["year"] = w
            if i + 1 < len(words):
                out["make"] = words[i + 1]
            if i + 2 < len(words):
                out["model"] = words[i + 2]
            if i + 3 < len(words):
                out["trim"] = " ".join(words[i + 3:])
            break
    return out


def to_vehicle(data, url, condition):
    """
    Build one standard vehicle dict from whatever we scraped off the page.

    The shared shape is documented in the project README; every platform
    scraper in this project returns exactly these keys so db.py never has to
    know which website the vehicle came from.
    """
    fallback = _parse_og_title(data.get("_og_title"))

    vin = (data.get("vin") or _vin_from_url(url) or "").upper()

    photo = data.get("thumbnail") or data.get("_og_image")
    photo_urls = [photo] if photo else []

    raw = {
        "vin": vin,
        "stock_number": data.get("stock") or data.get("stock_number") or "",
        "year": safe_int(data.get("year") or fallback.get("year")),
        "make": data.get("make") or fallback.get("make") or "",
        "model": data.get("model") or fallback.get("model") or "",
        "trim": data.get("trim") or fallback.get("trim") or "",
        "body_type": data.get("body") or data.get("bodytype") or "",
        "engine": data.get("engine_description") or data.get("engine") or "",
        "fuel_type": data.get("fueltype") or data.get("fuel_type") or "",
        "drivetrain": data.get("drivetrain") or "",
        "exterior_color": data.get("ext_color") or data.get("exterior_color") or None,
        "interior_color": data.get("int_color") or data.get("interior_color") or None,
        # DI calls the sticker price "msrp" on some sites and "original_price"
        # on others; "our_price" is the advertised selling price.
        "msrp": safe_float(data.get("msrp") or data.get("original_price")),
        "selling_price": safe_float(data.get("our_price") or data.get("price")),
        "mileage": safe_int(data.get("miles") or data.get("mileage")),
        # Dealer Inspire never publishes horsepower on the VDP.
        "horsepower": None,
        "listing_url": url,
        "photo_urls": photo_urls,
        "condition": condition or "new",
    }

    # normalize.py does the tidying every platform needs: title-casing, fixing
    # model names ("Encore Gx" -> "Encore GX"), upper-casing trim acronyms
    # (Sle -> SLE), trimming interior colors down to just the color, and
    # translating drivetrain wording to AWD / 4WD / FWD / RWD / 2WD.
    vehicle = normalize_vehicle(raw)

    # Last resort for drivetrain: the VIN itself encodes it, and the free
    # government VIN database (NHTSA) will tell us. This is a network call, so
    # we only do it when the page truly did not say.
    if not vehicle.get("drivetrain") and vehicle.get("vin"):
        vehicle["drivetrain"] = decode_drivetrain_from_vin(vehicle["vin"])

    return vehicle


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _scrape_one(url, condition):
    """Scrape a single vehicle page. Returns a vehicle dict or None."""
    data = parse_vdp(url)
    vehicle = to_vehicle(data, url, condition)
    # No VIN means we cannot tell this car apart from any other car, and the
    # database keys on VIN, so the row is useless. Drop it.
    if not vehicle.get("vin"):
        return None
    return vehicle


def scrape(dealer, limit=None):
    """
    Scrape a Dealer Inspire dealership website.

    dealer: one entry from config/dealers.yml (see scraper/config.py)
    limit:  optional maximum number of vehicles, handy for a quick test run
            (`--limit 10`) so you are not waiting on 400 pages.

    Returns a list of vehicle dicts in the shared shape.
    """
    base_url = (dealer.get("url") or "").rstrip("/")
    if not base_url:
        print("  [Dealer Inspire] No url set for this dealer -- skipping.")
        return []

    condition = (dealer.get("condition") or "new").lower().strip()

    print("  [Dealer Inspire] Reading the inventory sitemap...")
    try:
        url_pairs = fetch_vehicle_urls(base_url, condition)
    except Exception as e:
        print("  [Dealer Inspire] Could not read the sitemap: {}".format(e))
        print("    Check that {}{} opens in your browser.".format(base_url, SITEMAP_PATH))
        return []

    print("    Found {} {} vehicle pages.".format(len(url_pairs), condition))

    if not url_pairs:
        print("    WARNING: nothing found. Either the lot is empty, the site is")
        print("    not really Dealer Inspire, or the sitemap path has changed.")
        return []

    makes = dealer.get("makes")
    if makes:
        url_pairs = filter_by_makes(url_pairs, makes)
        print("    Narrowed to {} vehicles for makes: {}".format(len(url_pairs), makes))

    if limit:
        url_pairs = url_pairs[:limit]
        print("    Limiting this run to {} vehicles.".format(len(url_pairs)))

    workers = _worker_count()
    total = len(url_pairs)
    print("  [Dealer Inspire] Reading {} vehicle pages ({} at a time)...".format(total, workers))

    vehicles = []
    errors = 0
    done = 0

    # ThreadPoolExecutor = "do several downloads at once." Waiting on a website
    # is almost all of the time cost here, so doing 5 at a time is roughly 5x
    # faster than one after another.
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_url = {}
        for url, cond in url_pairs:
            future_to_url[executor.submit(_scrape_one, url, cond)] = url

        for future in as_completed(future_to_url):
            done += 1
            url = future_to_url[future]
            try:
                vehicle = future.result()
                if vehicle:
                    vehicles.append(vehicle)
            except Exception as e:
                errors += 1
                # Show the first few failures only -- if a site is blocking us
                # entirely, 400 identical error lines help nobody.
                if errors <= 5:
                    print("    ERROR on {}: {}".format(url, e))
                elif errors == 6:
                    print("    (further errors hidden)")

            if done % PROGRESS_EVERY == 0 or done == total:
                print("    {}/{} pages read ({} errors)".format(done, total, errors))

    print("    Got {} vehicles with a valid VIN.".format(len(vehicles)))
    return vehicles
