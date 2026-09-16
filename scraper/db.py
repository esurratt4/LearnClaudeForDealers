"""
db.py - Where the scraped cars go.

PLAIN ENGLISH
-------------
Every other file in this project is about *getting* vehicle data off a dealership
website. This file is about *keeping* it.

We store everything in Supabase, which is a hosted Postgres database with a friendly
web dashboard. Think of it as one giant, permanent spreadsheet that lives in the cloud
instead of on somebody's laptop.

There are three "tabs" in that spreadsheet (see sql/schema.sql):

  * vehicles       - one row per car per dealer. The current state of the lot.
  * scraper_runs   - a logbook. One row every time you run the scraper, so you can
                     tell "the scraper broke" apart from "the competitor sold out."
  * price_history  - one row every time a car's price CHANGES. This is the good stuff.
                     It is how you catch a competitor quietly cutting $3,000 off a
                     truck that has been sitting for 90 days.

THE ONE RULE THIS FILE LIVES BY: we never delete a vehicle.
When a car disappears from a competitor's website, we do not erase the row. We flip a
switch called `is_active` to false and stamp `removed_at` with today's date. That row is
now a permanent record that says "this exact truck sat on their lot from March 2nd to
May 19th." Delete it and you have thrown away the only interesting thing you know.
"""

import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import create_client

# We reuse the cleanup helpers so that what lands in the database is consistent no
# matter which platform scraper produced it. These are pure text functions - they do
# no network calls - which matters because this file runs in a loop over hundreds of
# vehicles during a live demo. (normalize_vehicle() can do a VIN lookup over the
# internet, so the platform scrapers call that one, not us.)
from scraper.normalize import title_case, fix_model, standardize_drivetrain


# Table names live in constants so a typo shows up in one place instead of twelve.
VEHICLES_TABLE = "vehicles"
RUNS_TABLE = "scraper_runs"
PRICE_HISTORY_TABLE = "price_history"

# How many rows we pull back from Supabase per request when reading, and how many we
# push per request when inserting. Supabase caps a single read at 1000 rows, so that
# number is not a preference - it is the ceiling. 500 for writes is just a batch size
# that is comfortably under any request-size limit while still being ~500x faster than
# sending one HTTP request per car.
PAGE_SIZE = 1000
INSERT_CHUNK = 500

# The safety rail. If a scrape comes back with fewer than this fraction of the cars we
# already have on file for that dealer, we refuse to mark anything as gone. Explained
# in detail down in _should_deactivate().
DEACTIVATION_FLOOR = 0.5


# ---------------------------------------------------------------------------
# Connecting to Supabase
# ---------------------------------------------------------------------------

# We cache the client in a module-level variable so that calling get_supabase() fifty
# times in one run does not open fifty connections.
_client = None


def _repo_root():
    """Absolute path to the top of this project (the folder holding .env)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_supabase():
    """
    Open (or reuse) a connection to your Supabase project.

    Reads two values out of the .env file in the project root:

        SUPABASE_URL               - your project's address
        SUPABASE_SERVICE_ROLE_KEY  - the powerful key that can WRITE data
        SUPABASE_ANON_KEY          - the safe, read-only-ish key (fallback)

    We prefer the service role key because the scraper needs to write. If you only
    have the anon key set, reads will work and writes will be rejected by the database
    with a permissions error - that is Row Level Security doing its job, not a bug.

    NEVER put the service role key in a website, a browser, or a public repo. It
    bypasses every security rule in the database. It belongs in .env (which is
    gitignored) and in GitHub Secrets. That is it.
    """
    global _client
    if _client is not None:
        return _client

    # override=False so that a real environment variable (say, one injected by GitHub
    # Actions) always beats whatever is sitting in a stale local .env file.
    load_dotenv(os.path.join(_repo_root(), ".env"), override=False)

    url = os.environ.get("SUPABASE_URL")
    if not url:
        raise RuntimeError(
            "Missing SUPABASE_URL.\n"
            "Copy .env.example to .env and paste in your Supabase project URL.\n"
            "You can find it in Supabase under Project Settings > API > Project URL."
        )

    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
    if not key:
        raise RuntimeError(
            "Missing SUPABASE_SERVICE_ROLE_KEY (and no SUPABASE_ANON_KEY fallback).\n"
            "Copy .env.example to .env and paste in your key.\n"
            "You can find it in Supabase under Project Settings > API. The scraper "
            "needs the 'service_role' key in order to write rows."
        )

    _client = create_client(url, key)
    return _client


def _now():
    """Current time as an ISO timestamp string, in UTC.

    Always UTC. Storing local time in a database is how you end up with two cars that
    appear to have arrived before they were scraped every November.
    """
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Turning a scraped vehicle into a database row
# ---------------------------------------------------------------------------

def _build_row(v, dealer, now):
    """
    Convert one scraped vehicle dict into the exact shape the `vehicles` table wants.

    READ THIS BEFORE ADDING A FIELD:
    There is deliberately NO `first_seen_at` key in the dictionary below, and there
    must never be one.

    On INSERT, Postgres fills first_seen_at in automatically from the column's DEFAULT
    (now()). On UPDATE, leaving the key out means Supabase does not touch that column,
    so the original value survives.

    first_seen_at is the anchor for days-on-lot. It is the answer to "how long has this
    truck been sitting?", which is the single most useful number in this whole database.
    If you add "first_seen_at": now to this dict, every vehicle silently becomes one day
    old on every run, forever, and nothing will error to tell you.
    """
    return {
        "vin": (v.get("vin") or "").upper(),
        "stock_number": v.get("stock_number"),
        "year": v.get("year"),
        "make": title_case(v.get("make")),
        # fix_model, not title_case: normalize.fix_model knows the official spellings
        # ("HUMMER EV SUV", "Sierra 2500HD"). Re-running a plain title_case over an
        # already-normalized model would quietly undo those and store "Hummer Ev Suv".
        "model": fix_model(v.get("model")),
        "trim": title_case(v.get("trim")),
        "body_type": v.get("body_type"),
        "engine": v.get("engine"),
        "fuel_type": v.get("fuel_type"),
        "drivetrain": standardize_drivetrain(v.get("drivetrain")),
        # Colors get upper-cased so "Summit White", "SUMMIT WHITE" and "summit white"
        # all group together in a report. Empty string becomes None so the database
        # stores a real NULL instead of a blank that looks like data.
        "exterior_color": (v.get("exterior_color") or "").upper() or None,
        "interior_color": (v.get("interior_color") or "").upper() or None,
        "msrp": v.get("msrp"),
        "selling_price": v.get("selling_price"),
        "mileage": v.get("mileage"),
        "horsepower": v.get("horsepower"),
        "listing_url": v.get("listing_url"),
        "photo_urls": v.get("photo_urls") or [],
        "condition": v.get("condition") or dealer.get("condition") or "new",
        # Who this car belongs to. dealer_key is the short slug from config/dealers.yml
        # ("laura_chevy"). It is what every query filters on.
        "dealer_key": dealer["key"],
        "dealer_name": dealer.get("name"),
        "dealer_city": dealer.get("city"),
        "dealer_state": dealer.get("state"),
        "is_own_store": bool(dealer.get("is_own_store")),
        # We saw it on the site just now, so it is on the lot.
        "is_active": True,
        "removed_at": None,
        "last_seen_at": now,
        "scraped_at": now,
    }


def _fetch_existing(sb, dealer_key):
    """
    Pull back every row we already have for this dealer, active or not.

    Supabase will only hand over 1000 rows at a time, so we walk through the results in
    pages until we get a short page, which tells us we hit the end. A big dealer group
    can easily have 2,000+ rows once you count sold inventory, and quietly getting only
    the first 1000 would make the scraper "rediscover" the same cars every single run.

    Returns a dict keyed by VIN: {vin: {"is_active": bool, "msrp": ..., "selling_price": ...}}
    We grab the prices here so we can tell later whether anything changed, without
    making a second round trip per vehicle.
    """
    existing = {}
    start = 0
    while True:
        resp = (
            sb.table(VEHICLES_TABLE)
            .select("vin, is_active, msrp, selling_price")
            .eq("dealer_key", dealer_key)
            .range(start, start + PAGE_SIZE - 1)
            .execute()
        )
        rows = resp.data or []
        for row in rows:
            existing[row["vin"]] = row
        if len(rows) < PAGE_SIZE:
            break
        start += PAGE_SIZE
    return existing


def _prices_differ(a, b):
    """
    True if two price values are meaningfully different.

    Money comes back from Postgres as a numeric, which the Python client may hand us as
    a float, an int, a string, or None depending on the column and the version. Compare
    those raw and you will log a price change every single run because "45000" != 45000.
    So we coerce both sides to float and compare with a penny of tolerance.
    """
    if a is None and b is None:
        return False
    if a is None or b is None:
        return True
    try:
        return abs(float(a) - float(b)) > 0.01
    except (TypeError, ValueError):
        # Unparseable on either side - treat as different so we keep the observation
        # rather than silently dropping it.
        return str(a) != str(b)


def _chunked(items, size):
    """Yield `items` in lists of at most `size`. Used to batch our inserts."""
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _should_deactivate(scraped_count, active_count):
    """
    THE SAFETY RAIL. Ported from lighthouse_scraper.mark_sold().

    Decide whether it is safe to mark missing vehicles as gone.

    Here is the failure we are guarding against. A competitor's website goes down for
    maintenance, or they change their page layout, or they start blocking us. Our
    scraper dutifully returns 4 vehicles instead of 180. Without this check, the very
    next thing we would do is mark 176 cars as "removed from the lot today" - which
    permanently corrupts every days-on-lot number and every price trend for that dealer.
    A bad afternoon on their web host would look like a fire sale in our data.

    So: if the scrape came back with less than half of what we already have on file as
    active, we assume the scrape is wrong, not the lot. We leave every row alone and
    print a loud warning. A stale row is recoverable on tomorrow's run. Erased history
    is not.

    Returns True if deactivation should proceed.
    """
    if active_count == 0:
        # Nothing on file yet (first run for this dealer). Nothing to protect.
        return True
    return scraped_count >= active_count * DEACTIVATION_FLOOR


def upsert_vehicles(sb, vehicles, dealer):
    """
    Save one dealer's scraped inventory.

    Takes the list of vehicle dicts a platform scraper returned and reconciles it
    against what is already in the database for this dealer:

      * VINs we have never seen  -> INSERT (batched, 500 at a time)
      * VINs we already have     -> UPDATE that row in place
      * VINs on file but NOT in this scrape -> is_active = false, removed_at = now
                                               (unless the safety rail trips)

    Along the way it writes a price_history row whenever msrp or selling_price moved,
    plus one baseline row for every brand-new vehicle so that even a car that never
    changes price has a starting point to compare against.

    Returns (added, updated, deactivated) as a tuple of counts.
    """
    now = _now()
    dealer_key = dealer["key"]

    existing = _fetch_existing(sb, dealer_key)
    active_vins = set(vin for vin, row in existing.items() if row.get("is_active"))

    to_insert = []
    to_update = []          # list of (vin, row) pairs
    price_rows = []
    scraped_vins = set()

    for v in vehicles:
        vin = (v.get("vin") or "").upper()
        if not vin:
            # A vehicle with no VIN cannot be deduplicated or tracked over time, and it
            # would break the UNIQUE (vin, dealer_key) constraint the moment a second
            # one showed up. Skip it rather than poison the table.
            continue
        if vin in scraped_vins:
            # Same VIN twice in one scrape (dealers do list a car on two pages).
            # Keep the first, ignore the rest.
            continue
        scraped_vins.add(vin)

        row = _build_row(v, dealer, now)
        prior = existing.get(vin)

        if prior is None:
            to_insert.append(row)
            # Baseline price observation, so day one of this car's life has a data
            # point. Without it, a car that drops price exactly once shows a "change"
            # with nothing to compare it to.
            price_rows.append({
                "vin": vin,
                "dealer_key": dealer_key,
                "observed_at": now,
                "msrp": row["msrp"],
                "selling_price": row["selling_price"],
            })
        else:
            to_update.append((vin, row))
            # Only log a price row when something actually moved. Logging every run
            # would bloat the table and bury the real drops in noise.
            if (_prices_differ(prior.get("msrp"), row["msrp"])
                    or _prices_differ(prior.get("selling_price"), row["selling_price"])):
                price_rows.append({
                    "vin": vin,
                    "dealer_key": dealer_key,
                    "observed_at": now,
                    "msrp": row["msrp"],
                    "selling_price": row["selling_price"],
                })

    # --- Inserts, batched -------------------------------------------------
    # The reference scraper inserted one vehicle per HTTP request. At 200 cars that is
    # 200 round trips and roughly a minute of dead air, which is painful to watch in a
    # 45-minute workshop. Batching makes it a handful of requests.
    added = 0
    for chunk in _chunked(to_insert, INSERT_CHUNK):
        sb.table(VEHICLES_TABLE).insert(chunk).execute()
        added += len(chunk)

    # --- Updates, one at a time -------------------------------------------
    # These stay per-row on purpose. A batch "update" in Supabase is really an upsert,
    # and an upsert would hand Postgres a full row - including a fresh first_seen_at
    # default - which is exactly the history-clobbering we are avoiding. One request
    # per changed car is worth the certainty.
    updated = 0
    for vin, row in to_update:
        (
            sb.table(VEHICLES_TABLE)
            .update(row)
            .eq("vin", vin)
            .eq("dealer_key", dealer_key)
            .execute()
        )
        updated += 1

    # --- Price history, batched -------------------------------------------
    for chunk in _chunked(price_rows, INSERT_CHUNK):
        sb.table(PRICE_HISTORY_TABLE).insert(chunk).execute()

    # --- Deactivation (never deletion) ------------------------------------
    deactivated = 0
    missing = [vin for vin in active_vins if vin not in scraped_vins]

    if not _should_deactivate(len(scraped_vins), len(active_vins)):
        print("")
        print("  " + "!" * 68)
        print("  !! SAFETY RAIL TRIPPED - skipping deactivation for %s" % dealer_key)
        print("  !! This scrape found %d vehicles but we have %d on file as active."
              % (len(scraped_vins), len(active_vins)))
        print("  !! That is under %d%%, which usually means their site was down or"
              % int(DEACTIVATION_FLOOR * 100))
        print("  !! changed layout - NOT that they sold %d cars." % len(missing))
        print("  !! Nothing was marked removed. Re-run once the site is back.")
        print("  " + "!" * 68)
        print("")
        return added, updated, 0

    for vin in missing:
        (
            sb.table(VEHICLES_TABLE)
            .update({"is_active": False, "removed_at": now, "last_seen_at": now})
            .eq("vin", vin)
            .eq("dealer_key", dealer_key)
            .execute()
        )
        deactivated += 1

    return added, updated, deactivated


# ---------------------------------------------------------------------------
# The run logbook
# ---------------------------------------------------------------------------

def start_run(sb, dealer_key, dealer_name):
    """
    Open a new entry in the scraper_runs logbook and return its id.

    Call this before you scrape. It writes a row with status='running' so that if the
    process crashes hard, you are left with visible evidence: a run that started and
    never finished. Silence is the worst failure mode - it looks identical to success.
    """
    resp = (
        sb.table(RUNS_TABLE)
        .insert({
            "dealer_key": dealer_key,
            "dealer_name": dealer_name,
            "status": "running",
        })
        .execute()
    )
    return resp.data[0]["id"]


def finish_run(sb, run_id, found, added, updated, deactivated, error=None):
    """
    Close out a logbook entry with the final numbers.

    status ends up as one of:
      success - it ran and found vehicles
      partial - it ran without crashing but came back empty-handed, which almost always
                means the site changed and a selector needs updating
      error   - it blew up; error_message tells you what happened
    """
    if error:
        status = "error"
    elif found == 0:
        status = "partial"
    else:
        status = "success"

    payload = {
        "finished_at": _now(),
        "status": status,
        "vehicles_found": found,
        "vehicles_added": added,
        "vehicles_updated": updated,
        "vehicles_deactivated": deactivated,
        # Truncated because a Python traceback can be enormous and the column is just
        # meant to be a readable hint, not a full crash dump.
        "error_message": str(error)[:500] if error else None,
    }

    sb.table(RUNS_TABLE).update(payload).eq("id", run_id).execute()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def check_tables(sb):
    """
    Ask the database "do these three tables exist and can I read them?"

    Used by the `doctor` command, which exists so that a brand-new attendee can find out
    in two seconds whether they forgot to paste sql/schema.sql into Supabase.

    Returns something like {"vehicles": True, "scraper_runs": True, "price_history": False}.

    This function must NEVER raise. The whole point of a diagnostic is that it still
    runs when everything else is broken - so each table is checked inside its own
    try/except and a failure just becomes False.
    """
    results = {}
    for table in (VEHICLES_TABLE, RUNS_TABLE, PRICE_HISTORY_TABLE):
        try:
            sb.table(table).select("*").limit(1).execute()
            results[table] = True
        except Exception:
            # Bare Exception on purpose: a missing table, a bad key, a DNS failure and
            # an expired project all surface as different exception types here, and for
            # a health check they all mean the same thing - "no."
            results[table] = False
    return results


# Marker for the doctor's write probe. Distinctive enough to recognise and clean up
# if a crash ever leaves one behind.
_PROBE_DEALER_KEY = "__doctor_write_probe__"


def check_write_access(sb):
    """
    Prove we can actually WRITE, not just read. Returns (ok, message).

    WHY THIS EXISTS, and why reading is not enough:

    Supabase hands you two keys. The `anon` key is public and read-only here; the
    `service_role` key is the one that can write. Both of them can SELECT, because
    schema.sql grants the anon role read access on purpose.

    So a person who pastes the wrong key gets a database connection that looks
    completely healthy. Tables exist, queries return, the doctor goes green - and then
    every scrape writes nothing, silently, forever. Row Level Security rejects the
    insert and the client does not always raise about it.

    That is the single nastiest failure mode in this whole setup, because it presents
    as "the scraper ran fine and found no cars" rather than as an error. The only way
    to catch it up front is to try a real write, so that is what this does: insert one
    throwaway row into scraper_runs, then delete it.
    """
    probe_id = None
    try:
        resp = (
            sb.table(RUNS_TABLE)
            .insert(
                {
                    "dealer_key": _PROBE_DEALER_KEY,
                    "dealer_name": "doctor write probe",
                    "status": "probe",
                }
            )
            .execute()
        )
        rows = getattr(resp, "data", None) or []
        if not rows:
            # Insert "succeeded" but wrote nothing. This is the RLS signature of a
            # read-only key.
            return (
                False,
                "the database accepted the request but saved nothing, which means "
                "this key is not allowed to write (it is almost certainly the anon "
                "key rather than the service_role key)",
            )
        probe_id = rows[0].get("id")
        return (True, "")
    except Exception as exc:
        detail = str(exc)
        lowered = detail.lower()
        if "row-level security" in lowered or "violates" in lowered or "permission" in lowered:
            return (
                False,
                "the database refused the write. That is what happens with the anon "
                "key; the scraper needs the service_role key",
            )
        return (False, detail[:200])
    finally:
        # Always tidy up, even if something above went sideways. A stray probe row in
        # the run log would be confusing the first time somebody reads it.
        if probe_id is not None:
            try:
                sb.table(RUNS_TABLE).delete().eq("id", probe_id).execute()
            except Exception:
                pass
