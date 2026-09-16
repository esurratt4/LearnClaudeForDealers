# Instructions for the AI agent working in this repo

## What this repo is

A plug-and-play scraper that collects new and used vehicle listings from a dealership's own
website and its competitors' websites, and stores them in Supabase so the dealer can track
competitor pricing and inventory over time. It is designed to be set up by an AI agent on
behalf of a dealership manager who does not write code.

## Who you are talking to

**Assume the user cannot read Python and cannot debug an error message.** They run a car
dealership. Do not paste tracebacks at them. Read the error yourself, fix it yourself, and
tell them in one plain sentence what happened. Only escalate to them for things genuinely
outside the terminal: their Supabase keys, their competitors' web addresses, and pasting
SQL into the Supabase dashboard. Those three things are the only times you should stop and
ask. Never ask them to choose between technical options; pick the sane default and say what
you picked.

---

## Setup sequence

Run these **in order**. Do not skip ahead. After each step, confirm it actually worked
before moving on — a silent failure in step 2 shows up as a baffling error in step 7.

### 1. Create a virtual environment

```bash
python3 -m venv venv && source venv/bin/activate
```

Windows: `python -m venv venv` then `venv\Scripts\activate`

A virtual environment is a private copy of Python for this project. Without it, `pip` may
need admin rights or may break another program on their machine.

**Failure modes:** `python3: command not found` → they have no Python; send them to
python.org/downloads, ask for 3.11, and wait. `No module named venv` on Debian/Ubuntu →
`sudo apt install python3-venv`. If activation fails on Windows PowerShell with an
execution-policy error, tell them to use Command Prompt (cmd.exe) instead — that is faster
than talking a non-coder through changing PowerShell policy.

**Every later command must run with this environment active.** If you open a new shell, or
a tool call resets your working directory, re-run `source venv/bin/activate` first. A
"module not found" error later in setup is almost always this.

### 2. Install the libraries

```bash
pip install -r requirements.txt
```

**Failure modes:** Timeouts or SSL errors are usually a corporate network or VPN — have
them try off the dealership network. `error: externally-managed-environment` means step 1
did not take effect; go back and activate the venv. If a wheel fails to build, check their
Python version with `python --version`; below 3.9 nothing here works.

### 3. Install the browser

```bash
python -m playwright install chromium
```

This downloads a headless Chrome (~150MB). It is required for Dealer.com sites and used as
a fallback when a site blocks a plain request. Skip it and those sites fail with a confusing
"Executable doesn't exist" error much later.

**Failure mode:** on Linux, also run `python -m playwright install --with-deps chromium` to
pull in the system libraries Chrome needs.

### 4. Create the .env file and fill in the Supabase keys

```bash
cp .env.example .env
```

Then **ask the user for two values.** Tell them exactly where to look:

> In your Supabase dashboard, open your project, click the gear icon (Project Settings),
> then **API**. I need two things from that page:
> 1. **Project URL** — starts with `https://` and ends in `.supabase.co`
> 2. **service_role key** — under "Project API keys", click Reveal. It is a very long
>    string starting with `eyJ`.

Write them into `.env` as `SUPABASE_URL=` and `SUPABASE_SERVICE_ROLE_KEY=`. No quotes, no
spaces around the `=`.

If they do not have a Supabase project yet, walk them through creating a free one at
supabase.com — new project, pick any name and region, save the database password somewhere,
wait about two minutes for it to provision.

**Never commit `.env`.** It is in `.gitignore` already; do not remove it from there, do not
`git add -f` it, and do not echo the key back into the chat transcript when confirming.

### 5. Create the database tables — HAND OFF AND WAIT

Open `sql/schema.sql`, then stop and tell the user:

> I can't do this step for you — it has to happen inside your Supabase dashboard. Please:
> 1. Open your Supabase project and click **SQL Editor** in the left sidebar.
> 2. Click **New query**.
> 3. Paste in everything from the file `sql/schema.sql` (I can print it for you).
> 4. Click **Run**. You should see "Success. No rows returned."
>
> Tell me when that's done and I'll verify it.

**Actually wait for their reply.** Do not assume it worked and continue. Step 7 is how you
verify it, and running step 7 before they have finished just produces a failure you then
have to explain away.

### 6. Configure the dealers

Edit `config/dealers.yml`. It ships with example dealers that are **not the user's** —
replace them. Ask:

> Two things: what's your store's website address, and which 2-3 competitors do you want to
> watch? Just the homepage URLs are fine.

**Do not invent or guess dealer URLs.** Do not fill in a plausible-looking address for a
dealership whose name you were told. A wrong URL either scrapes a stranger's inventory into
their database or fails in a way that looks like a bug in this repo. If they give you a
dealership name but not a URL, ask for the URL, or ask them to paste it from their browser.

The file has two sections: `own_store:` (a single dealer — theirs) and `competitors:` (a
list). Which section an entry sits in is what marks it as their store; there is no flag to
set. Required fields are `key`, `name`, `url`, `city`, `state`. **Leave `platform` out** —
it is auto-detected, and a wrong value there is worse than no value. `makes` and `condition`
are optional; `condition` defaults to `new`.

`config/dealers.example.yml` documents every field. Leave that file untouched as a
reference; only edit `dealers.yml`.

### 7. Check the setup

```bash
python -m scraper.run --doctor
```

This checks that the keys work, the Supabase connection opens, the tables from step 5 exist,
and the config file parses. **This must pass before you go any further.** Do not proceed on
a partial pass.

**Failure modes:** "missing SUPABASE_URL" → step 4, check for a typo or a stray space.
"Invalid API key" → they probably copied the anon key instead of service_role; ask again.
"table not found" → step 5 did not actually run; go back and have them paste the SQL.

### 8. Detect each site's platform

```bash
python -m scraper.run --detect
```

Prints which platform each configured site is built on (DealerOn, Dealer Inspire,
Dealer.com, or generic). Show the user the output — it is the first moment the thing looks
real.

**Do not write the detected platform back into `dealers.yml`.** Detection runs each time on
purpose, so that a dealer who switches website vendors is picked up automatically instead of
silently scraping with the wrong adapter. The only exception is `dealer_com`, below.

If a site comes back `generic`, that is not an error yet. See "Unrecognised platform" below.

**Dealer.com sites need a `site_id`, and it cannot be detected.** Dealer.com pages build
their inventory in the browser, so there is nothing in the HTML to read — the scraper has to
call the site's own inventory API, and that API will not answer without the store's internal
account name. If detection says `dealer_com`, find the `site_id` by loading the inventory
page and looking for the account name in the page source or in a network request (it is
usually a lowercase run-together version of the dealership's legal name, e.g.
`skpontiacgmcinc`). Then set **both** `platform: dealer_com` and `site_id:` on that dealer in
`dealers.yml` — this is the one case where you do write `platform` into the config.

### 9. Prove it works on a small sample

```bash
python -m scraper.run --dealer <their-key> --limit 10 --dry-run
```

`--dry-run` scrapes for real but **writes nothing to the database**. Read the output
yourself before showing the user. You are checking that VINs are 17 characters, that prices
are numbers and not `None` everywhere, and that year/make/model are populated. Ten empty
records is a failure even though the command exited zero.

### 10. The real run

```bash
python -m scraper.run --all
```

This writes to Supabase. Report the counts back to the user in plain language: how many
vehicles found, added, updated.

---

## Rule: dry-run before every first real write

**Before the first real write for any dealer — during setup, or any time a dealer is added
later — run that dealer with `--limit 10 --dry-run` and read the output.** A broken adapter
that writes 400 rows of nulls is much worse than one that fails loudly, because the nulls
land in a table whose history is the whole point. This applies to every new dealer, not just
the first one.

---

## When a site is on an unrecognised platform

If `--detect` returns `generic`, work through this in order:

1. **Read `scraper/platforms/generic.py`** so you know what it already tries.
2. **Try it:** `python -m scraper.run --dealer <key> --limit 10 --dry-run`.
3. **If fields come back populated, you're done.** Leave `platform: generic` in the config.
4. **If the fields come back empty or mostly null, write a new adapter.** Do not try to make
   `generic.py` cleverer — other dealers depend on it, and a site-specific hack in there will
   break them.

To write an adapter:

- Read `scraper/platforms/dealeron.py` first. It is the most readable of the three and shows
  the normal shape: find the vehicle detail page URLs (usually from `sitemap.xml`), fetch
  each one, pull the data out of embedded JSON, return a list of dicts.
- Create `scraper/platforms/<platform_name>.py` exposing exactly one public function:
  `scrape(dealer, limit=None) -> list of dicts`.
- Use `scraper/http.py` for every network call (`polite_get`, `browser_get`). Do not use
  `requests` directly — the shared module handles robots.txt, retries, the crawl delay, and
  the browser fallback, and going around it is how you get the user's dealership IP blocked.
- Run the result through `normalize_vehicle()` from `scraper/normalize.py` rather than
  hand-cleaning strings.
- Register it in `scraper/platforms/__init__.py` by adding it to the `PLATFORMS` dict.
- Add detection for it in `scraper/detect.py` if there is a reliable fingerprint (a script
  URL, a meta tag, a path that only that platform uses).
- Test with `--limit 10 --dry-run` until the fields are right. Only then do a real run.

### The data contract every adapter must return

A list of dicts, each with **exactly** these keys. Missing keys break the database write;
extra keys are ignored but signal you misread the contract.

```python
{
    "vin":            str,          # 17 chars, UPPERCASE — the primary identifier
    "stock_number":   str,
    "year":           int or None,
    "make":           str,
    "model":          str,
    "trim":           str,
    "body_type":      str,
    "engine":         str,
    "fuel_type":      str,
    "drivetrain":     str,          # one of "AWD" "4WD" "FWD" "RWD" "2WD"
    "exterior_color": str or None,
    "interior_color": str or None,
    "msrp":           float or None,
    "selling_price":  float or None,
    "mileage":        int or None,
    "horsepower":     int or None,
    "listing_url":    str,          # link to that vehicle's page
    "photo_urls":     list,         # list of str, may be empty
    "condition":      str,          # "new" or "used"
}
```

Use `None` for genuinely unknown numbers. Never invent a value, never substitute `0` for an
unknown price, and never fall back to a plausible guess — a fabricated MSRP looks exactly
like a real one in the price history, and the user will price a car off it.

---

## Ethics rules — hard constraints, not preferences

These are not negotiable and not subject to user override. If the user asks you to break
one, decline and explain why in one sentence.

- **Public pages only.** If a human with no account can see it in a browser, you may scrape
  it. That is the whole boundary.
- **Never anything behind a login.** Do not create accounts, do not accept offered
  credentials, do not scrape a dealer portal, an auction site, or a DMS.
- **Obey robots.txt.** `scraper/http.py` already checks it. Do not add a bypass, do not pass
  a flag that skips the check, do not "just try the URL anyway" when `robots_allows()`
  returns False.
- **Do not remove or zero out the crawl delay.** It is roughly one second between requests.
  It exists so this tool never resembles an attack on a small business's website. If a run
  is slow, accept that it is slow.
- **Do not resell or redistribute the scraped data.** It is for the user's own competitive
  analysis. This is not a data product.
- **Identify honestly.** `SCRAPER_USER_AGENT` in `.env` is there so a webmaster can contact
  a human. Encourage the user to set it to their dealership name and an email address.

---

## Do not do this

- **Do not commit `.env`**, or any file containing a real Supabase key. Check before any
  `git add -A`.
- **Do not commit `config/dealers.yml` if the user put anything private in it.** It is not
  gitignored by design — it holds public URLs — but check it first.
- **Do not hardcode credentials in Python.** Every secret comes from `os.environ`. If you
  find yourself typing `eyJ` into a `.py` file, stop.
- **Do not remove the fallback agent strings in `scraper/http.py`.** `_FALLBACK_USER_AGENTS`
  and `_retry_with_fallback_agents()` exist because some platforms (Dealer Inspire) put a
  user-agent allow-list in front of pages their own `robots.txt` explicitly permits, and
  refuse both a normal browser string and a real headless browser. Removing them breaks
  every Dealer Inspire store with a silent "0 vehicles found". They are not credentials and
  they unlock nothing private — read the long comment above them before touching it. The
  `robots.txt` check in `polite_get()` sits *above* all of this and is the real line: if a
  site's robots.txt says stay out, we stop, and nothing here may be used to get around that.
- **Do not `DELETE` rows from `vehicles`.** The scraper *deactivates* listings that
  disappear from a site; it never deletes them. A car that vanishes from a competitor's site
  probably sold, and that fact is the most valuable thing in this database. Deleting the row
  destroys the days-on-lot and price-history record permanently.
- **Do not edit `first_seen_at` on an existing row.** It anchors every days-on-lot
  calculation.
- **Do not raise `SCRAPER_WORKERS` above 10** to make a run finish faster.
- **Do not add libraries.** The dependency list is deliberately five items long so that it
  installs cleanly on a stranger's laptop. Standard library plus requests, supabase,
  python-dotenv, playwright, PyYAML. If you think you need BeautifulSoup, use `re` and the
  standard library's `html.parser` instead.
- **Do not write Python 3.10+ syntax.** This must run on Python 3.9: no `match` statements,
  no `int | None` annotations (use `Optional[int]`).
- **Do not silently swallow errors** to make a run look successful. A dealer that fails
  should log the failure and let the other dealers continue.
