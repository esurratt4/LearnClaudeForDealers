"""
Cleans up messy vehicle data so every dealership's cars look the same.

PLAIN ENGLISH: every dealership website describes the same car differently. One site
says "All-Wheel Drive", another says "AWD", another says "4x4". One writes the colour as
"Ebony Twilight Metallic" and the next writes "EBONY TWILIGHT METALLIC". One calls the
truck a "Sierra 2500 Hd" and another a "SIERRA 2500HD".

If you load all of that into a spreadsheet as-is, you cannot compare anything: your
"AWD Yukon XL" count will be split across four spellings and every number you report
will be wrong.

This file is the laundry. Every scraper sends its raw results through `normalize_vehicle`
and gets back a car described the same way every single time, so that a Yukon XL from
your store and a Yukon XL from the competitor down the road actually line up.

Nothing in here talks to the database, and nothing in here scrapes a website. It only
takes messy text in and hands tidy text back -- which also makes it the easiest file in
the project to experiment with.
"""

import re

import requests


# ---------------------------------------------------------------------------
# Text tidying
# ---------------------------------------------------------------------------

# Words that must stay SHOUTED rather than be politely capitalised. Without this list,
# "GMC Sierra AT4X" comes out of a normal title-caser as "Gmc Sierra At4x", which looks
# broken to anyone who sells cars for a living.
ACRONYMS = {
    # brands and badges
    "gmc", "at4", "at4x", "sle", "slt", "slt1", "slt2", "elt", "gx", "xl", "xt",
    "hd", "ev", "cc", "dc", "st", "ss", "lt", "ls", "rst", "zr2", "z71", "sv",
    # drivetrain shorthand that shows up inside trim names
    "awd", "fwd", "rwd", "4wd", "2wd", "4x4", "4x2",
    # powertrain shorthand
    "v6", "v8", "tdi", "phev", "hev", "bev", "mpg", "mph", "hp",
    # body styles. These come through body_type, which is a column people
    # actually look at -- without these you get "Suv" and "Cuv" on screen.
    "suv", "cuv", "suvs",
}


def _capitalize_word(word):
    """Capitalise one word, respecting hyphens ("all-terrain" -> "All-Terrain")."""
    return "-".join(part.capitalize() for part in word.split("-"))


def title_case(s):
    """
    Make a phrase read like a person wrote it, without flattening the acronyms.

        "GMC SIERRA 2500HD"   -> "GMC Sierra 2500HD"
        "yukon xl denali"     -> "Yukon XL Denali"
        "all-terrain package" -> "All-Terrain Package"

    Returns the input untouched if it is empty, so it is always safe to call.
    """
    if not s:
        return s
    words = str(s).strip().split()
    out = []
    for w in words:
        if w.lower() in ACRONYMS:
            out.append(w.upper())
        elif any(ch.isdigit() for ch in w):
            # Anything with a number in it is a badge, not a word: 2500HD, 1SB, 4X4,
            # AT4X. Capitalising those produces nonsense, so shout them instead.
            out.append(w.upper())
        else:
            out.append(_capitalize_word(w))
    return " ".join(out)


def safe_int(v):
    """
    Turn whatever the website gave us into a whole number, or None if we cannot.

    Handles the junk that shows up in real listings: "12,345", " 8 ", "1,234 miles".
    Never raises -- a single weird mileage field should not kill an entire scrape.
    """
    if v is None:
        return None
    if isinstance(v, bool):        # True would otherwise quietly become 1
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    text = re.sub(r"[^0-9\-]", "", str(v))   # keep digits and a leading minus
    if text in ("", "-"):
        return None
    try:
        return int(text)
    except (ValueError, TypeError):
        return None


def safe_float(v):
    """
    Turn whatever the website gave us into a number with decimals, or None.

    Prices arrive as "$54,995", "54995.00", "Call for price" -- only the first two are
    really numbers, and this returns None for the third rather than crashing.
    """
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    text = re.sub(r"[^0-9.\-]", "", str(v))
    if text in ("", "-", ".", "-."):
        return None
    try:
        return float(text)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Drivetrain
# ---------------------------------------------------------------------------

# Every spelling of a drivetrain we have actually seen in the wild, mapped to the one
# spelling we store. Keys are lowercase; lookups lowercase the input first.
_DRIVETRAIN_MAP = {
    "all-wheel drive": "AWD",
    "all wheel drive": "AWD",
    "allwheeldrive": "AWD",
    "awd": "AWD",
    "four-wheel drive": "4WD",
    "four wheel drive": "4WD",
    "4-wheel drive": "4WD",
    "4 wheel drive": "4WD",
    "4wd": "4WD",
    "4x4": "4WD",
    "front-wheel drive": "FWD",
    "front wheel drive": "FWD",
    "fwd": "FWD",
    "rear-wheel drive": "RWD",
    "rear wheel drive": "RWD",
    "rwd": "RWD",
    "two-wheel drive": "2WD",
    "two wheel drive": "2WD",
    "2-wheel drive": "2WD",
    "2 wheel drive": "2WD",
    "2wd": "2WD",
    "4x2": "2WD",
    "2x2": "2WD",
}


def standardize_drivetrain(raw):
    """
    Collapse every spelling of a drivetrain into AWD / 4WD / FWD / RWD / 2WD.

    If we genuinely do not recognise it we hand back the original text rather than
    throwing it away -- an unfamiliar value in your report is a clue to add a new
    spelling to `_DRIVETRAIN_MAP`, whereas a blank is just lost information.
    """
    if not raw:
        return ""
    key = str(raw).strip().lower()
    if key in _DRIVETRAIN_MAP:
        return _DRIVETRAIN_MAP[key]

    # The government VIN service answers with slash-stuffed values such as
    # "4WD/4-Wheel Drive/4x4", so try each piece individually.
    for part in re.split(r"[/,|]", key):
        part = part.strip()
        if part in _DRIVETRAIN_MAP:
            return _DRIVETRAIN_MAP[part]

    # Last resort: some sites bury the answer in a sentence, e.g.
    # "3.0L Duramax Diesel AWD". Look for a bare token anywhere in the string.
    m = re.search(r"\b(awd|4wd|fwd|rwd|2wd|4x4|4x2)\b", key)
    if m:
        return _DRIVETRAIN_MAP[m.group(1)]

    return str(raw).strip()


# Remembering VIN lookups we have already done. A scrape can retry the same vehicle
# several times, and the free government API is the slowest thing in the whole program,
# so asking it twice for the same VIN is pure wasted time.
_VIN_DRIVETRAIN_CACHE = {}

# The NHTSA vPIC service: free, public, run by the US Department of Transportation, and
# it needs no API key. Given a VIN it tells you how the factory built that vehicle.
_VPIC_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/{0}?format=json"


def decode_drivetrain_from_vin(vin):
    """
    Ask the government's free VIN database what drivetrain a vehicle has.

    Used only as a backstop: some dealership websites simply do not publish the
    drivetrain, and "AWD or not" is usually the single most important thing a shopper
    filters on, so it is worth one extra lookup to fill the hole.

    Returns "" if anything at all goes wrong -- no internet, slow response, VIN typo,
    unexpected answer. A missing drivetrain is a small problem; a crashed overnight
    scrape is a big one, so this function never raises.
    """
    if not vin:
        return ""
    vin = str(vin).strip().upper()
    if len(vin) != 17:
        return ""
    if vin in _VIN_DRIVETRAIN_CACHE:
        return _VIN_DRIVETRAIN_CACHE[vin]

    result = ""
    try:
        # 5 second ceiling: if the government site is having a bad day we move on
        # rather than letting one VIN stall a scrape of 400 vehicles.
        resp = requests.get(_VPIC_URL.format(vin), timeout=5)
        resp.raise_for_status()
        results = resp.json().get("Results") or []
        if results:
            result = standardize_drivetrain(results[0].get("DriveType") or "")
    except Exception:
        # Deliberately catching everything: network errors, bad JSON, surprise HTML
        # error pages. There is nothing useful we could do differently for any of them.
        result = ""

    _VIN_DRIVETRAIN_CACHE[vin] = result
    return result


# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------


def clean_interior_color(raw):
    """
    Strip the upholstery sales copy off an interior colour.

        "Jet Black, Leather-appointed seat trim" -> "Jet Black"
        "Dark Ash Grey cloth seats"              -> "Dark Ash Grey"

    We keep only the colour because that is the part you can actually compare between
    two stores; the material wording differs brand to brand and adds only noise.
    """
    if not raw:
        return ""
    part = str(raw).split(",")[0].strip()
    part = re.sub(
        r"\s+(seats?|seating|with|w/|interior|trim|accents?|leather|leatherette|"
        r"cloth|vinyl|perforated|appointed).*",
        "",
        part,
        flags=re.IGNORECASE,
    ).strip()
    return part


def _clean_exterior_color(raw):
    """Trim the marketing tail off an exterior colour ("Summit White (Extra Cost)")."""
    if not raw:
        return ""
    part = str(raw).strip()
    part = re.sub(r"\s*\([^)]*\)\s*$", "", part).strip()   # drop a trailing (...)
    return part


# ---------------------------------------------------------------------------
# Model names
# ---------------------------------------------------------------------------

# Models whose "correct" spelling no title-caser could ever guess. Keys are lowercase
# with single spaces; `fix_model` looks up that way so it catches every capitalisation
# the websites throw at us.
_MODEL_FIXES = {
    "encore gx": "Encore GX",
    "hummer ev suv": "HUMMER EV SUV",
    "hummer ev pickup": "HUMMER EV Pickup",
    "sierra ev": "Sierra EV",
    "sierra 1500 limited": "Sierra 1500 Limited",
    "sierra 2500 hd": "Sierra 2500HD",
    "sierra 2500hd": "Sierra 2500HD",
    "sierra 3500 hd": "Sierra 3500HD",
    "sierra 3500hd": "Sierra 3500HD",
    "sierra 3500hd cc": "Sierra 3500HD CC",
    "sierra 3500 hd cc": "Sierra 3500HD CC",
    "yukon xl": "Yukon XL",
    # The two Savana cargo vans are the same product to a shopper; the number is a
    # weight rating, so we fold them together to stop splitting the count in reports.
    "savana cargo 2500": "Savana Cargo Van",
    "savana cargo 3500": "Savana Cargo Van",
    "savana cargo van": "Savana Cargo Van",
}


def fix_model(raw):
    """
    Give a model name its official spelling.

        "sierra 2500 hd" -> "Sierra 2500HD"
        "ENCORE GX"      -> "Encore GX"
        "acadia"         -> "Acadia"

    Anything not on the fix list just gets ordinary title casing, so adding a new brand
    does not require touching this function.
    """
    if not raw:
        return ""
    collapsed = " ".join(str(raw).split()).lower()
    if collapsed in _MODEL_FIXES:
        return _MODEL_FIXES[collapsed]
    return title_case(raw)


def fix_trim(raw):
    """
    Tidy a trim level ("at4x premium" -> "AT4X Premium", "slt crew cab" -> "SLT Crew Cab").

    Same idea as `fix_model`, kept separate because trims are where the badge acronyms
    live and they are the field most likely to need a new entry in ACRONYMS later.
    """
    if not raw:
        return ""
    return title_case(raw)


# ---------------------------------------------------------------------------
# The whole car
# ---------------------------------------------------------------------------

# The exact set of fields every vehicle in this project carries, with the value we use
# when a website simply does not publish that detail. Everything downstream -- the
# database writer, the reports -- is written against this list, so a scraper that
# forgets a field still produces a row that loads cleanly.
_DEFAULTS = {
    "vin": "",
    "stock_number": "",
    "year": None,
    "make": "",
    "model": "",
    "trim": "",
    "body_type": "",
    "engine": "",
    "fuel_type": "",
    "drivetrain": "",
    "exterior_color": None,
    "interior_color": None,
    "msrp": None,
    "selling_price": None,
    "mileage": None,
    "horsepower": None,
    "listing_url": "",
    "photo_urls": [],
    "condition": "new",
}


def _clean_photo_urls(value):
    """Always hand back a list of real web addresses, however odd the input was."""
    if not value:
        return []
    if isinstance(value, str):
        value = [value]                      # a single photo, not wrapped in a list
    out = []
    seen = set()
    for item in value:
        if not item:
            continue
        url = str(item).strip()
        # Protocol-relative URLs ("//pictures.dealer.com/...") are valid in a browser
        # but useless in a spreadsheet or an email, so give them a scheme.
        if url.startswith("//"):
            url = "https:" + url
        if not url.lower().startswith("http"):
            continue
        if url not in seen:                  # same photo listed twice is common
            seen.add(url)
            out.append(url)
    return out


def normalize_vehicle(d, decode_missing_drivetrain=False):
    """
    Take one raw vehicle from any scraper and return it in this project's standard shape.

    Every platform scraper ends by calling this. It guarantees:
      * every field exists (no missing keys later on)
      * the VIN is uppercase with no stray spaces
      * make / model / trim read properly, acronyms intact
      * colours are UPPERCASE and stripped of upholstery sales copy
      * the drivetrain is one of AWD / 4WD / FWD / RWD / 2WD
      * prices and mileages are numbers, not "$54,995"
      * photo_urls is always a list, even when the site gave us nothing
      * condition is "new" or "used"

    `decode_missing_drivetrain` is off by default because turning it on means one
    internet lookup per vehicle that is missing a drivetrain, which can add minutes to
    a big scrape. A platform scraper that knows its site hides the drivetrain should
    pass True (or call `decode_drivetrain_from_vin` itself for just the gaps).
    """
    d = d or {}
    v = dict(_DEFAULTS)
    v["photo_urls"] = []                 # fresh list; never share the default's list

    # --- identity ----------------------------------------------------------
    # VIN is the car's fingerprint and half of the database's uniqueness rule
    # (vin + dealer_key), so it must be upper case with nothing extra around it or the
    # same car scraped twice would land as two different cars.
    v["vin"] = str(d.get("vin") or "").strip().upper().replace(" ", "")
    v["stock_number"] = str(d.get("stock_number") or "").strip()

    # --- description -------------------------------------------------------
    v["year"] = safe_int(d.get("year"))
    v["make"] = title_case(str(d.get("make") or "").strip())
    v["model"] = fix_model(d.get("model"))
    v["trim"] = fix_trim(d.get("trim"))
    v["body_type"] = title_case(str(d.get("body_type") or "").strip())
    # Engine descriptions are full of numbers and units ("3.0L Duramax Turbo-Diesel
    # I6") that title casing would mangle, so we only squeeze out extra whitespace.
    v["engine"] = " ".join(str(d.get("engine") or "").split())
    v["fuel_type"] = title_case(str(d.get("fuel_type") or "").strip())

    # --- drivetrain --------------------------------------------------------
    v["drivetrain"] = standardize_drivetrain(d.get("drivetrain"))
    if not v["drivetrain"] and decode_missing_drivetrain:
        v["drivetrain"] = decode_drivetrain_from_vin(v["vin"])

    # --- colours -----------------------------------------------------------
    # Stored UPPERCASE because that is how a window sticker reads and because it makes
    # "Summit White" and "SUMMIT WHITE" group together in a report instead of
    # appearing as two separate colours.
    ext = _clean_exterior_color(d.get("exterior_color"))
    interior = clean_interior_color(d.get("interior_color"))
    v["exterior_color"] = ext.upper() if ext else None
    v["interior_color"] = interior.upper() if interior else None

    # --- money and numbers -------------------------------------------------
    msrp = safe_float(d.get("msrp"))
    selling_price = safe_float(d.get("selling_price"))
    # A price of zero is never a real price -- it is a site saying "Call for pricing".
    # Storing 0 would drag every average you calculate straight into the floor.
    v["msrp"] = msrp if (msrp and msrp > 0) else None
    v["selling_price"] = selling_price if (selling_price and selling_price > 0) else None
    # Mileage keeps its zero: 0 miles on a new truck is a fact, not a missing value.
    v["mileage"] = safe_int(d.get("mileage"))
    hp = safe_int(d.get("horsepower"))
    v["horsepower"] = hp if (hp and hp > 0) else None

    # --- links and photos --------------------------------------------------
    v["listing_url"] = str(d.get("listing_url") or "").strip()
    v["photo_urls"] = _clean_photo_urls(d.get("photo_urls"))

    # --- condition ---------------------------------------------------------
    condition = str(d.get("condition") or "new").strip().lower()
    if condition not in ("new", "used"):
        # Sites say "certified", "pre-owned", "cpo" -- all of which are used cars as
        # far as a price comparison is concerned.
        condition = "new" if condition.startswith("new") else "used"
    v["condition"] = condition

    return v
