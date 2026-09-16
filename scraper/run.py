#!/usr/bin/env python3
"""
The control panel for your inventory scraper.

This is the file you actually run. Everything else in the `scraper/` folder is a
part that this file picks up and uses. In plain English, here is what it can do:

    python -m scraper.run --doctor
        "Is everything plugged in?" Checks your dealer list, your password file,
        your Supabase database, and your browser tool -- and tells you exactly
        how to fix anything that is broken. Run this FIRST, every time.

    python -m scraper.run --list
        "Did I set up my stores correctly?" Prints your configured dealerships
        and when each one was last scraped. Never writes anything.

    python -m scraper.run --detect
        "What website software does this store use?" Looks at each dealer's site
        and reports which platform it runs on. Never writes anything.

    python -m scraper.run --dealer village --dry-run
        "Show me what you would collect, but do not save it." Scrapes, prints a
        sample of the cars it found, and touches nothing in the database.

    python -m scraper.run --all
        The real thing: scrape every configured store and save to Supabase.

Two ideas worth knowing before you read further:

 1. Every dealership is scraped INDEPENDENTLY. One store's website being down,
    slow, or redesigned can never stop the other stores from finishing. That is
    why each dealer gets its own try/except and its own database run record.

 2. Nothing here decides *how* to scrape. This file only decides *what order*
    things happen in and *what you see on screen*. The actual scraping lives in
    scraper/platforms/, the database work lives in scraper/db.py.
"""

import argparse
import os
import re
import sys
import time
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Screen layout constants
#
# The output of this file gets projected on a wall during a live workshop, so it
# is written like a printed report, not like developer logs. Fixed widths mean
# the columns line up no matter how long a dealership's name is.
# ---------------------------------------------------------------------------

RULE = "=" * 78          # a heavy line, used above and below section titles
THIN = "-" * 78          # a light line, used between dealers
INDENT = "  "            # every sub-line is indented exactly two spaces

# How many vehicles --dry-run shows in its sample table.
DRY_RUN_SAMPLE = 10

# The fields we promise every platform scraper will return. --dry-run counts how
# many vehicles actually had each one filled in, which is how you spot a scraper
# that technically "worked" but came back with no prices.
CONTRACT_FIELDS = [
    "vin", "stock_number", "year", "make", "model", "trim",
    "body_type", "engine", "fuel_type", "drivetrain",
    "exterior_color", "interior_color",
    "msrp", "selling_price", "mileage", "horsepower",
    "listing_url", "photo_urls", "condition",
]

# The three tables this project needs in Supabase.
REQUIRED_TABLES = ["vehicles", "scraper_runs", "price_history"]

# The environment variable names we accept for the Supabase key. Different
# Supabase screens call it different things, so we look for any of them.
KEY_ENV_NAMES = [
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_KEY",
    "SUPABASE_ANON_KEY",
]


def say(line=""):
    """
    Print one line to the screen, immediately.

    `flush=True` matters more than it looks: without it Python holds output in a
    buffer when you pipe the command into a file or another tool, and a long
    scrape looks frozen for minutes. During a live demo, frozen looks broken.
    """
    print(line, flush=True)


# ---------------------------------------------------------------------------
# Small formatting helpers
# ---------------------------------------------------------------------------

def fit(value, width):
    """Trim a value to `width` characters so table columns never wrap."""
    text = "" if value is None else str(value)
    if len(text) <= width:
        return text
    return text[: width - 1] + "~"


def money(value):
    """Format a price the way a human writes it: $42,995. Blank if missing."""
    if value is None:
        return "-"
    try:
        return "${:,.0f}".format(float(value))
    except (TypeError, ValueError):
        return "-"


def number(value):
    """Format a whole number with thousands separators. Blank if missing."""
    if value is None:
        return "-"
    try:
        return "{:,}".format(int(value))
    except (TypeError, ValueError):
        return "-"


def elapsed(seconds):
    """Turn 83.4 seconds into '1m 23s' so nobody has to do mental math."""
    seconds = int(round(seconds))
    if seconds < 60:
        return "{0}s".format(seconds)
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return "{0}m {1}s".format(minutes, secs)
    hours, minutes = divmod(minutes, 60)
    return "{0}h {1}m".format(hours, minutes)


def parse_timestamp(raw):
    """
    Turn a database timestamp string into a Python datetime, or None.

    Supabase hands back text like '2026-09-15T21:40:02.123456+00:00', sometimes
    ending in 'Z' and sometimes with extra decimal places. Python 3.9 chokes on
    both of those, so we clean them up first. This is display-only -- if it fails
    we just show nothing rather than crash the --list command.
    """
    if not raw:
        return None
    text = str(raw).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # Trim fractional seconds down to the 6 digits Python 3.9 accepts.
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def time_ago(stamp):
    """Turn a datetime into '3h ago' -- far easier to read than a timestamp."""
    if stamp is None:
        return "-"
    delta = (datetime.now(timezone.utc) - stamp).total_seconds()
    if delta < 0:
        return "just now"
    if delta < 90:
        return "just now"
    if delta < 3600:
        return "{0}m ago".format(int(delta // 60))
    if delta < 86400:
        return "{0}h ago".format(int(delta // 3600))
    return "{0}d ago".format(int(delta // 86400))


def header(title, extra_lines=None):
    """Print a titled section banner. Every major step of a run gets one."""
    say()
    say(RULE)
    say(INDENT + title)
    for line in (extra_lines or []):
        say(INDENT + line)
    say(RULE)


def pretty_url(url):
    """Shorten a URL for table display: strip the https:// and the www."""
    text = (url or "").replace("https://", "").replace("http://", "")
    if text.startswith("www."):
        text = text[4:]
    return text.rstrip("/")


# ---------------------------------------------------------------------------
# Finding the config file
# ---------------------------------------------------------------------------

def repo_root():
    """The folder that contains both `scraper/` and `config/`."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def config_path():
    """
    Where dealers.yml lives.

    We build an absolute path from this file's own location rather than trusting
    whatever folder you happened to be standing in when you ran the command.
    That way `python -m scraper.run` works from anywhere on your computer.
    """
    return os.path.join(repo_root(), "config", "dealers.yml")


def load_config_or_die():
    """
    Load the dealer list, or print a plain-English explanation and stop.

    Used by every command except --doctor (which needs to report the failure as a
    numbered check rather than exiting immediately).
    """
    from scraper.config import load_config
    try:
        return load_config(config_path())
    except Exception as exc:
        say()
        say("CONFIG ERROR")
        for line in str(exc).splitlines():
            say(INDENT + line)
        say()
        say(INDENT + "Run `python -m scraper.run --doctor` for a full checkup.")
        sys.exit(1)


def load_dotenv_if_present():
    """
    Load the .env file (your Supabase URL and key) into the environment.

    Returns the path to the .env file if we found one, otherwise None. We never
    read or print the values here -- that is deliberate, because this function's
    output is shown on a projector.
    """
    env_file = os.path.join(repo_root(), ".env")
    try:
        from dotenv import load_dotenv
    except ImportError:
        return env_file if os.path.exists(env_file) else None
    if os.path.exists(env_file):
        load_dotenv(env_file)
        return env_file
    # Fall back to a .env in whatever folder the user is standing in.
    load_dotenv()
    return None


def project_ref(url):
    """
    Pull the Supabase project reference out of the project URL.

    'https://abcdefghijkl.supabase.co' -> 'abcdefghijkl'

    The project ref is safe to show on screen -- it is in every URL your website
    already sends to browsers. The KEY is not, and is never printed anywhere in
    this file.
    """
    if not url:
        return "?"
    match = re.search(r"https?://([^.]+)\.supabase\.", url)
    if match:
        return match.group(1)
    return pretty_url(url)


# ---------------------------------------------------------------------------
# COMMAND: --doctor
# ---------------------------------------------------------------------------

def check_line(passed, message, fix=None, warn_only=False):
    """
    Print one check result and return True/False.

    Shape on screen:
        [PASS] Config file loaded
          5 dealers configured
        [FAIL] Supabase says table 'vehicles' does not exist
          FIX: open your Supabase project, click SQL Editor, and run the
               setup SQL from the README.
    """
    if passed:
        label = "[PASS]"
    elif warn_only:
        label = "[WARN]"
    else:
        label = "[FAIL]"
    say("{0} {1}".format(label, message))
    if not passed and fix:
        lines = fix.splitlines()
        say(INDENT + "FIX: " + lines[0])
        for line in lines[1:]:
            say(INDENT + "     " + line)
    return bool(passed)


def detail(message):
    """A sub-line under a check: indented two spaces, no label."""
    say(INDENT + message)


def cmd_doctor():
    """
    Pre-flight check. Run this before the workshop, before the demo, and any time
    something behaves strangely.

    Checks happen in order because each one depends on the last: there is no
    point testing the database connection if the password file is missing. Every
    failure prints the exact next action to take.

    Returns 0 if checks 1-3 all passed, 1 otherwise. Check 4 (the browser) is a
    warning only, because only Dealer.com sites need it.
    """
    header("DOCTOR - pre-flight check")

    ok = True

    # --- 1. The dealer list ------------------------------------------------
    say()
    say("1. Dealer list (config/dealers.yml)")
    cfg = None
    try:
        from scraper.config import load_config, all_dealers
        cfg = load_config(config_path())
        dealers = all_dealers(cfg)
        own = cfg.get("own_store")
        ok = check_line(True, "config/dealers.yml loaded") and ok
        detail("{0} dealer(s) configured: {1} own store, {2} competitor(s)".format(
            len(dealers), 1 if own else 0, len(cfg.get("competitors") or [])
        ))
        if not own:
            check_line(
                False,
                "No own_store is set",
                "open config/dealers.yml and fill in the own_store: section with\n"
                "your own dealership. Competitor numbers mean nothing without it.",
                warn_only=True,
            )
        if not dealers:
            ok = check_line(
                False,
                "The file loaded but contains zero dealers",
                "open config/dealers.yml and add at least one dealership under\n"
                "own_store: or competitors:.",
            ) and ok
    except Exception as exc:
        ok = check_line(
            False,
            "Could not load config/dealers.yml",
            str(exc).splitlines()[0] if str(exc) else "see the error above",
        ) and ok
        for line in str(exc).splitlines()[1:]:
            detail("     " + line)

    # --- 2. The .env file --------------------------------------------------
    say()
    say("2. Credentials (.env)")
    env_file = load_dotenv_if_present()
    env_ok = True
    if env_file:
        check_line(True, ".env file found")
        detail(env_file)
    else:
        env_ok = check_line(
            False,
            "No .env file in {0}".format(repo_root()),
            "copy the example file and fill it in:\n"
            "  cp .env.example .env\n"
            "then paste your Supabase URL and key into it.",
        )

    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    if supabase_url:
        check_line(True, "SUPABASE_URL is set")
        detail("project ref: {0}".format(project_ref(supabase_url)))
    else:
        env_ok = check_line(
            False,
            "SUPABASE_URL is not set",
            "in Supabase click Project Settings > Data API, copy the Project URL,\n"
            "and put this line in your .env file:\n"
            "  SUPABASE_URL=https://yourproject.supabase.co",
        )

    key_name = None
    for name in KEY_ENV_NAMES:
        if os.environ.get(name, "").strip():
            key_name = name
            break
    if key_name:
        # We print the NAME of the variable and how long the value is. We never
        # print the value. A service role key in a screen recording is a breach.
        check_line(True, "{0} is set".format(key_name))
        detail("value hidden ({0} characters)".format(len(os.environ[key_name].strip())))
    else:
        env_ok = check_line(
            False,
            "No Supabase key is set",
            "in Supabase click Project Settings > API Keys, copy the\n"
            "service_role key, and put this line in your .env file:\n"
            "  SUPABASE_SERVICE_ROLE_KEY=eyJ...\n"
            "Never commit that key to GitHub.",
        )
    ok = env_ok and ok

    # --- 3. Supabase itself ------------------------------------------------
    say()
    say("3. Supabase database")
    if not env_ok:
        ok = check_line(
            False,
            "Skipped - fix the .env problems above first",
            "finish step 2, then run --doctor again.",
        ) and ok
    else:
        try:
            from scraper.db import get_supabase, check_tables
            supabase = get_supabase()
            tables = check_tables(supabase)
            check_line(True, "Connected to Supabase")
            for table in REQUIRED_TABLES:
                exists = bool(tables.get(table))
                ok = check_line(
                    exists,
                    "table '{0}' {1}".format(table, "exists" if exists else "is MISSING"),
                    "open your Supabase project, click SQL Editor > New query, and\n"
                    "run the setup SQL from the README. It creates all three tables\n"
                    "and is safe to run twice.",
                ) and ok
            # A table the code does not know about is not a failure, just noise.
            for table in sorted(tables):
                if table not in REQUIRED_TABLES:
                    detail("also found: '{0}'".format(table))
        except Exception as exc:
            ok = check_line(
                False,
                "Could not reach Supabase: {0}".format(str(exc)[:120]),
                "check that SUPABASE_URL has no typo and no trailing slash, that\n"
                "the key was copied whole, and that the project is not paused\n"
                "(free Supabase projects pause after a week of no use -- open the\n"
                "dashboard and click Restore).",
            ) and ok

    # --- 4. The browser (Playwright) --------------------------------------
    # Warning only, on purpose: requests handles most sites. Only Dealer.com
    # stores need a real browser, so a missing browser should not stop a run
    # that has no Dealer.com stores in it.
    say()
    say("4. Browser engine (only Dealer.com sites need this)")
    try:
        from playwright.sync_api import sync_playwright
        check_line(True, "playwright is installed")
        try:
            with sync_playwright() as pw:
                exe = pw.chromium.executable_path
            if exe and os.path.exists(exe):
                check_line(True, "chromium browser is downloaded")
            else:
                check_line(
                    False,
                    "chromium browser is not downloaded yet",
                    "run this once:\n"
                    "  python -m playwright install chromium",
                    warn_only=True,
                )
        except Exception as exc:
            check_line(
                False,
                "chromium is not usable: {0}".format(str(exc)[:100]),
                "run this once:\n"
                "  python -m playwright install chromium",
                warn_only=True,
            )
    except ImportError:
        check_line(
            False,
            "playwright is not installed",
            "run:\n"
            "  pip install -r requirements.txt\n"
            "  python -m playwright install chromium\n"
            "Skip this if none of your stores are on Dealer.com.",
            warn_only=True,
        )

    # --- Verdict -----------------------------------------------------------
    say()
    say(RULE)
    if ok:
        say(INDENT + "RESULT: ready to scrape.")
        say(INDENT + "Next:   python -m scraper.run --list")
    else:
        say(INDENT + "RESULT: not ready. Fix the FAIL lines above, top to bottom,")
        say(INDENT + "        then run --doctor again. Warnings are safe to ignore")
        say(INDENT + "        unless one of your stores is on Dealer.com.")
    say(RULE)
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# COMMAND: --list
# ---------------------------------------------------------------------------

def latest_runs_by_dealer():
    """
    Ask Supabase for the most recent scrape of each dealership.

    Returns a dict of {dealer_key: run_row}, or raises. The caller catches the
    error, because --list must survive a dead database -- its whole job is to
    let you check your config before anything is connected.

    We read a generous slice of recent rows and pick the newest per dealer in
    Python rather than writing a fancy SQL query, because it keeps this readable
    and the table is small.
    """
    from scraper.db import get_supabase
    supabase = get_supabase()
    query = supabase.table("scraper_runs").select("*").limit(300)
    try:
        # Newest first if the column exists...
        response = query.order("started_at", desc=True).execute()
    except Exception:
        # ...and if it does not, take whatever order we get and sort below.
        response = supabase.table("scraper_runs").select("*").limit(300).execute()

    rows = response.data or []

    def row_time(row):
        stamp = parse_timestamp(
            row.get("started_at") or row.get("created_at") or row.get("finished_at")
        )
        # datetime.min needs a timezone to compare against aware timestamps.
        return stamp or datetime.min.replace(tzinfo=timezone.utc)

    rows.sort(key=row_time, reverse=True)

    latest = {}
    for row in rows:
        key = row.get("dealer_key")
        if key and key not in latest:
            latest[key] = row
    return latest


def cmd_list():
    """
    Show the configured dealerships and when each was last scraped.

    This command must NEVER crash. It is the command you run when you are not
    sure whether anything is set up right, so it degrades in stages: config
    always prints, and the database half prints a note if Supabase is asleep.
    """
    cfg = load_config_or_die()
    from scraper.config import all_dealers
    dealers = all_dealers(cfg)

    header("CONFIGURED DEALERS")
    say()
    say("  {0:<13} {1:<26} {2:<12} {3:<16} {4}".format(
        "KEY", "DEALERSHIP", "PLATFORM", "LOCATION", "WEBSITE"))
    say(THIN)

    for dealer in dealers:
        marker = "*" if dealer.get("is_own_store") else " "
        location = ", ".join([p for p in [dealer.get("city"), dealer.get("state")] if p])
        # A blank platform in the config is not a mistake -- it means "figure it
        # out for me", which is what --detect does.
        platform = dealer.get("platform") or "auto"
        extras = []
        if dealer.get("makes"):
            extras.append("{0} only".format("/".join(dealer["makes"])))
        if (dealer.get("condition") or "new") != "new":
            extras.append(dealer["condition"])
        suffix = "  ({0})".format(", ".join(extras)) if extras else ""
        say("{0} {1:<13} {2:<26} {3:<12} {4:<16} {5}{6}".format(
            marker,
            fit(dealer.get("key"), 13),
            fit(dealer.get("name"), 26),
            fit(platform, 12),
            fit(location, 16),
            pretty_url(dealer.get("url")),
            suffix,
        ))

    say(THIN)
    say("  {0} dealer(s).  * = your own store.".format(len(dealers)))
    if not cfg.get("own_store"):
        say("  NOTE: no own_store set in config/dealers.yml -- you have nothing to")
        say("        compare the competitors against.")

    # --- The database half, which is allowed to fail ----------------------
    say()
    say("  LAST RUN")
    say("  {0:<13} {1:<12} {2:>8}  {3:<10} {4}".format(
        "KEY", "STATUS", "FOUND", "WHEN", "NOTE"))
    say(THIN)
    try:
        latest = latest_runs_by_dealer()
    except Exception as exc:
        say("  (could not reach Supabase, so run history is unavailable)")
        say("  {0}".format(str(exc)[:70]))
        say("  Your dealer list above is still correct. Run --doctor to fix the")
        say("  database connection.")
        say(RULE)
        return 0

    for dealer in dealers:
        row = latest.get(dealer.get("key"))
        if not row:
            say("  {0:<13} {1:<12} {2:>8}  {3:<10} {4}".format(
                fit(dealer.get("key"), 13), "never run", "-", "-", ""))
            continue
        status = str(row.get("status") or "?")
        found = row.get("vehicles_found")
        if found is None:
            found = row.get("records_found")
        when = time_ago(parse_timestamp(
            row.get("started_at") or row.get("created_at") or row.get("finished_at")
        ))
        note = str(row.get("error_message") or "")
        say("  {0:<13} {1:<12} {2:>8}  {3:<10} {4}".format(
            fit(dealer.get("key"), 13),
            fit(status, 12),
            number(found),
            fit(when, 10),
            fit(note, 26),
        ))
    say(THIN)
    return 0


# ---------------------------------------------------------------------------
# Platform detection (shared by --detect and the real scrape)
# ---------------------------------------------------------------------------

def unpack_detection(result):
    """
    Accept whatever scraper/detect.py hands back and return a tidy
    (platform, evidence_lines, site_id) tuple.

    We are deliberately flexible here. detect.py may return a simple string
    ("dealeron") or a richer result carrying the clues it used and any site id it
    found in the page. Being forgiving about the shape means a change in detect.py
    never breaks the command you demo in front of a room.
    """
    if result is None:
        return None, [], None

    if isinstance(result, str):
        return result, [], None

    if isinstance(result, dict):
        get = result.get
    else:
        # Something object-shaped (a namedtuple or a small class).
        get = lambda name, default=None: getattr(result, name, default)

    platform = get("platform") or get("name")
    site_id = get("site_id")
    evidence = get("evidence") or get("reasons") or get("clues") or []
    if isinstance(evidence, str):
        evidence = [evidence]
    return platform, [str(item) for item in evidence], site_id


def detect_dealer(dealer, cache):
    """
    Work out which website platform a dealership runs on.

    Returns (platform, evidence_lines, site_id).

    `cache` is a plain dict shared across the whole run so we never fetch the
    same homepage twice -- polite to the dealer's server and noticeably faster
    when two stores share a URL.
    """
    url = dealer.get("url")
    if url in cache:
        return cache[url]

    from scraper import detect as detect_module

    result = None
    rich = getattr(detect_module, "detect", None)
    if callable(rich):
        result = rich(url)
    platform, evidence, site_id = unpack_detection(result)

    if not platform:
        # Fall back to the one function the module contract guarantees exists.
        platform = detect_module.detect_platform(url)

    cache[url] = (platform, evidence, site_id)
    return cache[url]


def cmd_detect(dealer_keys):
    """
    Look at each dealership's website and report what software it runs on.

    Writes nothing, scrapes nothing -- it just fetches a page or two. Useful
    when adding a new competitor: run this, then paste the answer into
    config/dealers.yml so future runs skip the guessing step.
    """
    cfg = load_config_or_die()
    dealers = select_dealers(cfg, dealer_keys, run_all=not dealer_keys)

    header("PLATFORM DETECTION", ["Nothing is written. This only looks."])

    cache = {}
    for dealer in dealers:
        say()
        say("  {0}  ({1})".format(dealer.get("name"), dealer.get("key")))
        say("  {0}".format(dealer.get("url")))
        configured = dealer.get("platform")
        try:
            platform, evidence, site_id = detect_dealer(dealer, cache)
        except Exception as exc:
            say("    platform : COULD NOT TELL")
            say("    reason   : {0}".format(str(exc)[:90]))
            say("    Try opening the URL in your browser -- if it does not load for")
            say("    you either, the address in dealers.yml is wrong.")
            continue

        say("    platform : {0}".format(platform or "unknown"))
        if site_id:
            say("    site id  : {0}".format(site_id))
            say("               (paste this into dealers.yml as site_id: to make")
            say("                future runs faster and steadier)")
        if evidence:
            say("    evidence :")
            for line in evidence:
                say("      - {0}".format(fit(line, 68)))
        if configured and platform and configured != platform:
            say("    NOTE     : dealers.yml says '{0}' but the site looks like".format(configured))
            say("               '{0}'. The config wins during a real run.".format(platform))

    say()
    say(RULE)
    return 0


# ---------------------------------------------------------------------------
# Choosing which dealers to work on
# ---------------------------------------------------------------------------

def select_dealers(cfg, dealer_keys, run_all):
    """
    Turn the command line flags into an actual list of dealerships.

    Unknown keys stop the program immediately with the list of valid ones,
    because silently scraping the wrong store is worse than an error message.
    """
    from scraper.config import all_dealers, find_dealer

    everyone = all_dealers(cfg)
    if not everyone:
        say()
        say("No dealers are configured in config/dealers.yml.")
        say(INDENT + "Add at least one store, then try again.")
        sys.exit(1)

    if run_all or not dealer_keys:
        return everyone

    chosen = []
    for key in dealer_keys:
        dealer = find_dealer(cfg, key)
        if dealer is None:
            say()
            say("Unknown dealer key: '{0}'".format(key))
            say(INDENT + "Configured keys are:")
            for known in everyone:
                say(INDENT + "  {0:<16} {1}".format(known.get("key"), known.get("name")))
            say(INDENT + "Run `python -m scraper.run --list` to see the whole table.")
            sys.exit(1)
        chosen.append(dealer)
    return chosen


# ---------------------------------------------------------------------------
# --dry-run reporting
# ---------------------------------------------------------------------------

def print_sample_table(vehicles):
    """Print the first few vehicles as a readable table -- the sanity check."""
    sample = vehicles[:DRY_RUN_SAMPLE]
    say()
    say("  First {0} of {1} vehicles:".format(len(sample), len(vehicles)))
    say()
    say("  {0:<4} {1:<9} {2:<12} {3:<6} {4:>9} {5:>7} {6:<5} {7}".format(
        "YEAR", "MAKE", "MODEL", "TRIM", "PRICE", "MILES", "DRIVE", "VIN"))
    say(THIN)
    for vehicle in sample:
        price = vehicle.get("selling_price")
        if price is None:
            price = vehicle.get("msrp")
        say("  {0:<4} {1:<9} {2:<12} {3:<6} {4:>9} {5:>7} {6:<5} {7}".format(
            fit(vehicle.get("year"), 4),
            fit(vehicle.get("make"), 9),
            fit(vehicle.get("model"), 12),
            fit(vehicle.get("trim"), 6),
            fit(money(price), 9),
            fit(number(vehicle.get("mileage")), 7),
            fit(vehicle.get("drivetrain"), 5),
            fit(vehicle.get("vin"), 17),
        ))
    say(THIN)


def print_fill_summary(vehicles):
    """
    Count how many vehicles actually had each field filled in.

    This is the most useful thing --dry-run prints. A scraper that returns 200
    cars with no prices "worked" as far as Python is concerned, and this table is
    how you catch that in ten seconds instead of after you have written garbage
    into your database.
    """
    total = len(vehicles)
    say()
    say("  Field fill rate across all {0} vehicles:".format(total))
    say()
    for field in CONTRACT_FIELDS:
        filled = 0
        for vehicle in vehicles:
            value = vehicle.get(field)
            # An empty string, empty list, or None all count as "not collected".
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            if isinstance(value, (list, tuple, dict)) and len(value) == 0:
                continue
            filled += 1
        percent = (100.0 * filled / total) if total else 0.0
        flag = ""
        if filled == 0:
            flag = "  <- never collected"
        elif percent < 50:
            flag = "  <- mostly missing"
        say("    {0:<16} {1:>5} / {2:<5} {3:>5.0f}%{4}".format(
            field, filled, total, percent, flag))


# ---------------------------------------------------------------------------
# Scraping one dealership
# ---------------------------------------------------------------------------

def run_one_dealer(dealer, position, total, limit, dry_run, supabase, cache):
    """
    Scrape a single dealership from start to finish.

    Returns a result dict. It NEVER raises: a dealership that explodes is a
    recorded outcome, not a crash, so the stores after it in the list still get
    their turn. That structure is the whole point of running competitors in one
    command.
    """
    result = {
        "key": dealer.get("key"),
        "name": dealer.get("name"),
        "found": 0,
        "added": 0,
        "updated": 0,
        "deactivated": 0,
        "status": "ok",
        "error": None,
        "seconds": 0.0,
    }
    started = time.time()

    say()
    say(THIN)
    say("  [{0}/{1}] {2}  ({3})".format(position, total, dealer.get("name"), dealer.get("key")))
    say("  {0:<10}{1}".format("Website", dealer.get("url")))

    run_id = None
    try:
        # --- Which platform? ----------------------------------------------
        # The config always wins. A human who typed a platform into dealers.yml
        # has told us something detection cannot know, and detection costs an
        # extra web request we would rather not make.
        platform = dealer.get("platform")
        if platform:
            say("  {0:<10}{1}  (from config/dealers.yml)".format("Platform", platform))
        else:
            say("  {0:<10}detecting...".format("Platform"))
            platform, _evidence, site_id = detect_dealer(dealer, cache)
            say("  {0:<10}{1}  (auto-detected)".format("Platform", platform))
            # If detection turned up a site id and the config has none, use it.
            # Some platforms cannot scrape without one.
            if site_id and not dealer.get("site_id"):
                dealer["site_id"] = site_id
                say("  {0:<10}{1}  (auto-detected)".format("Site ID", site_id))

        from scraper.platforms import get_scraper
        scrape = get_scraper(platform)

        # --- Open the run record ------------------------------------------
        # Opened BEFORE scraping so that a crash mid-scrape still leaves a row
        # saying "this dealer was attempted and failed", rather than silence.
        # A dry run deliberately skips this: it must write absolutely nothing.
        if not dry_run:
            from scraper.db import start_run
            run_id = start_run(supabase, dealer.get("key"), dealer.get("name"))

        # --- Scrape --------------------------------------------------------
        say("  Scraping...")
        vehicles = scrape(dealer, limit=limit) or []
        result["found"] = len(vehicles)
        say("  Found {0} vehicle(s) in {1}".format(len(vehicles), elapsed(time.time() - started)))

        if not vehicles:
            # Zero cars is suspicious but not an error -- a small store really can
            # sell out, and a site redesign looks identical from here.
            say("  WARNING: nothing came back. Either the store is empty or the")
            say("           site changed. Try: python -m scraper.run --detect --dealer {0}".format(
                dealer.get("key")))
            result["status"] = "empty"
            if not dry_run and run_id is not None:
                from scraper.db import finish_run
                finish_run(supabase, run_id, 0, 0, 0, 0)
            result["seconds"] = time.time() - started
            return result

        # --- Report or save -------------------------------------------------
        if dry_run:
            print_sample_table(vehicles)
            print_fill_summary(vehicles)
            say()
            say("  DRY RUN - nothing written for {0}".format(dealer.get("name")))
            result["status"] = "dry-run"
        else:
            say("  Saving to Supabase...")
            from scraper.db import upsert_vehicles, finish_run
            added, updated, deactivated = upsert_vehicles(supabase, vehicles, dealer)
            result["added"] = added
            result["updated"] = updated
            result["deactivated"] = deactivated
            say("    +{0} added   ~{1} updated   {2} marked sold/removed".format(
                added, updated, deactivated))
            finish_run(supabase, run_id, len(vehicles), added, updated, deactivated)

    except KeyboardInterrupt:
        # Ctrl-C belongs to the person, not to this function. Close the run
        # record honestly and let it travel up to main().
        if run_id is not None and not dry_run:
            try:
                from scraper.db import finish_run
                finish_run(supabase, run_id, result["found"], 0, 0, 0, error="interrupted by user")
            except Exception:
                pass
        raise

    except Exception as exc:
        message = "{0}: {1}".format(type(exc).__name__, exc)
        result["status"] = "ERROR"
        result["error"] = message
        say("  ERROR: {0}".format(message[:200]))
        say("  Moving on to the next dealer -- this one does not stop the others.")
        if run_id is not None and not dry_run:
            try:
                from scraper.db import finish_run
                finish_run(supabase, run_id, result["found"], 0, 0, 0, error=message)
            except Exception as log_error:
                # If even the error logging fails, say so quietly and carry on.
                say("  (could not record the failure in Supabase: {0})".format(
                    str(log_error)[:80]))

    result["seconds"] = time.time() - started
    return result


# ---------------------------------------------------------------------------
# COMMAND: the real scrape
# ---------------------------------------------------------------------------

def print_summary(results, total_seconds, dry_run):
    """The block everyone reads. One row per store, then the totals."""
    header("SUMMARY")
    say()
    say("  {0:<24} {1:>8} {2:>8} {3:>9} {4:>8}  {5}".format(
        "DEALERSHIP", "FOUND", "ADDED", "UPDATED", "REMOVED", "STATUS"))
    say(THIN)

    totals = {"found": 0, "added": 0, "updated": 0, "deactivated": 0}
    for result in results:
        for field in totals:
            totals[field] += result.get(field) or 0
        say("  {0:<24} {1:>8} {2:>8} {3:>9} {4:>8}  {5}".format(
            fit(result.get("name"), 24),
            number(result.get("found")),
            "-" if dry_run else number(result.get("added")),
            "-" if dry_run else number(result.get("updated")),
            "-" if dry_run else number(result.get("deactivated")),
            result.get("status"),
        ))

    say(THIN)
    say("  {0:<24} {1:>8} {2:>8} {3:>9} {4:>8}".format(
        "TOTAL",
        number(totals["found"]),
        "-" if dry_run else number(totals["added"]),
        "-" if dry_run else number(totals["updated"]),
        "-" if dry_run else number(totals["deactivated"]),
    ))
    say()
    say("  Elapsed  {0}".format(elapsed(total_seconds)))

    failures = [r for r in results if r.get("error")]
    if failures:
        say()
        say("  {0} dealer(s) failed:".format(len(failures)))
        for result in failures:
            say("    {0:<20} {1}".format(fit(result.get("key"), 20), fit(result.get("error"), 50)))
        say()
        say("  A failure here usually means the site changed, blocked us, or the")
        say("  URL in config/dealers.yml is wrong. Start with:")
        say("    python -m scraper.run --detect --dealer {0}".format(failures[0].get("key")))

    if dry_run:
        say()
        say("  DRY RUN - nothing written. Remove --dry-run to save for real.")
    say(RULE)


def cmd_scrape(dealer_keys, run_all, limit, dry_run):
    """
    Scrape one, several, or all configured dealerships.

    Every store is handled independently, so the command always reaches the end
    and always prints a summary. If any store failed we exit with code 1 -- but
    only after every other store has had its turn.
    """
    cfg = load_config_or_die()
    dealers = select_dealers(cfg, dealer_keys, run_all)

    extra = [
        "Started  {0}".format(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")),
        "Dealers  {0}".format(len(dealers)),
    ]
    if limit:
        # Said loudly, because a "12 vehicles" headline from a store with 300
        # cars on the lot has confused every room this has ever been shown in.
        extra.append("LIMIT: only {0} vehicles per dealer (a test, NOT the whole lot)".format(limit))
    if dry_run:
        extra.append("DRY RUN - nothing written")
    header("INVENTORY SCRAPE", extra)

    # Connect to Supabase once, up front, so a bad password fails in two seconds
    # instead of after twenty minutes of scraping. A dry run never connects.
    supabase = None
    if not dry_run:
        load_dotenv_if_present()
        try:
            from scraper.db import get_supabase
            supabase = get_supabase()
        except Exception as exc:
            say()
            say("Could not connect to Supabase: {0}".format(str(exc)[:150]))
            say(INDENT + "Run `python -m scraper.run --doctor` -- it will tell you exactly")
            say(INDENT + "which piece is missing. Or add --dry-run to scrape without saving.")
            return 1

    started = time.time()
    detection_cache = {}
    results = []
    for index, dealer in enumerate(dealers, start=1):
        results.append(
            run_one_dealer(dealer, index, len(dealers), limit, dry_run, supabase, detection_cache)
        )

    print_summary(results, time.time() - started, dry_run)

    # Exit code 1 if anything failed, so scheduled runs (cron, GitHub Actions)
    # can tell "it worked" from "it printed a lot and gave up".
    return 1 if any(r.get("error") for r in results) else 0


# ---------------------------------------------------------------------------
# No-arguments help
# ---------------------------------------------------------------------------

def print_help(parser):
    """Show usage plus the dealer keys this particular checkout has configured."""
    parser.print_help()
    say()
    say("Configured dealers:")
    try:
        from scraper.config import load_config, all_dealers
        cfg = load_config(config_path())
        dealers = all_dealers(cfg)
        if not dealers:
            say(INDENT + "(none yet -- add some to config/dealers.yml)")
        for dealer in dealers:
            marker = "*" if dealer.get("is_own_store") else " "
            say("{0} {1:<16} {2}".format(marker, dealer.get("key"), dealer.get("name")))
        say()
        say("  * = your own store")
    except Exception as exc:
        say(INDENT + "(could not read config/dealers.yml: {0})".format(str(exc).splitlines()[0]))
    say()
    say("Start here:  python -m scraper.run --doctor")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m scraper.run",
        description="Scrape car dealership inventory into Supabase.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m scraper.run --doctor                  check the setup\n"
            "  python -m scraper.run --list                    show configured stores\n"
            "  python -m scraper.run --detect                  identify each site's platform\n"
            "  python -m scraper.run --dealer village --dry-run  practice run, saves nothing\n"
            "  python -m scraper.run --all                     scrape everything, for real\n"
        ),
    )
    parser.add_argument("--doctor", action="store_true",
                        help="Check config, credentials, database and browser. Run this first.")
    parser.add_argument("--list", action="store_true", dest="do_list",
                        help="Show configured dealers and when each was last scraped.")
    parser.add_argument("--detect", action="store_true",
                        help="Identify which website platform each dealer uses. Writes nothing.")
    parser.add_argument("--dealer", action="append", metavar="KEY", dest="dealers",
                        help="Scrape one dealer by key. Repeat the flag for several.")
    parser.add_argument("--all", action="store_true", dest="do_all",
                        help="Scrape every configured dealer.")
    parser.add_argument("--limit", type=int, metavar="N",
                        help="Only collect N vehicles per dealer. For quick tests.")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="Scrape and print results, but write nothing to Supabase.")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.doctor:
        return cmd_doctor()

    if args.do_list:
        return cmd_list()

    if args.detect:
        return cmd_detect(args.dealers or [])

    if args.do_all or args.dealers:
        if args.do_all and args.dealers:
            say("NOTE: --all was given, so the individual --dealer flags are ignored.")
        if args.limit is not None and args.limit < 1:
            say("--limit must be 1 or more.")
            return 1
        return cmd_scrape(args.dealers or [], args.do_all, args.limit, args.dry_run)

    return print_help(parser)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        # Ctrl-C during a demo should print one calm word, not forty lines of
        # traceback across the projector. 130 is the standard exit code for
        # "the human stopped this", which schedulers understand.
        print()
        print("Interrupted")
        sys.exit(130)
