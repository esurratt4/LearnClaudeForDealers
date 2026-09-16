# Instructions for the AI agent working in this repo

## What this repo is

A scraper that reads new and used vehicle listings from a dealership's own website and its
competitors' public websites, stores them in the user's own Supabase database, and a
dashboard that turns that data into competitive answers. It is set up by you, the agent, on
behalf of a dealership manager who does not write code.

## Who you are talking to

**Assume the user cannot read code and cannot debug an error message.** They run a car
dealership. Never paste a traceback at them. Read the error yourself, fix it yourself, and
tell them in one plain sentence what happened. Never ask them to choose between technical
options; pick the sane default and say what you picked.

The only things you ask the user for are things outside the terminal: their Supabase keys,
their dealership and competitor names and web addresses, clicks inside the Supabase or
GitHub website, and logging in to GitHub. Everything else you do yourself.

**Never echo a key back.** When you confirm a key was saved, say "saved", not the value. Do
not print `.env` or `dashboard/config.js` to the screen. Other people may be watching it.

---

## The setup flow

The user sends numbered prompts, in this order, one at a time. Each section below is what
to do for that prompt. **Do only what that prompt asks, then stop and report.** Do not run
ahead into the next step; the user is following along at a set pace.

If a prompt arrives out of order, check whether the earlier steps actually happened (the
venv exists, `.env` has values, `--doctor` passes, `config/dealers.yml` holds their stores)
and do the missing work first, saying so in one sentence.

### Running commands in this repo

- Work from the project folder. After the clone it is `~/Desktop/LearnClaudeForDealers`
  (on Windows, the Desktop may be under OneDrive: check `~/OneDrive/Desktop` if `~/Desktop`
  is missing). Use that absolute path, because your working directory can reset between
  commands.
- **Every Python command runs inside the virtual environment**, and activation does not
  persist between your shell calls. Prefix every command:
  - macOS / Linux: `source venv/bin/activate && python -m scraper.run ...`
  - Windows (Git Bash): `source venv/Scripts/activate && python -m scraper.run ...`

  A "No module named ..." error almost always means this prefix was missing.
- The scraper commands that exist are exactly: `--doctor`, `--list`, `--detect`,
  `--dealer KEY`, `--limit N`, `--dry-run`, `--all`. Do not invent others.

---

### PROMPT 1: Get the code

> "Clone https://github.com/esurratt4/LearnClaudeForDealers onto my Desktop and open it.
> Read CLAUDE.md and do the setup: create the Python virtual environment, install the
> requirements, and install the Playwright browser. Stop when the install is done and tell
> me. Don't ask me for any keys yet."

```bash
cd ~/Desktop && git clone https://github.com/esurratt4/LearnClaudeForDealers.git
cd ~/Desktop/LearnClaudeForDealers
python3 -m venv venv                     # Windows: python -m venv venv  (or py -3 -m venv venv)
source venv/bin/activate && pip install -r requirements.txt
source venv/bin/activate && python -m playwright install chromium
```

If the folder already exists from an earlier attempt, do not clone again: use it, and run
`git pull` if it has no local changes.

Confirm each step worked before the next. Then tell the user, in one or two sentences, that
the code is on their Desktop and everything is installed. **Stop.** Do not create `.env`, do
not ask for keys, do not edit any config.

**Failure modes:**
- `python3: command not found` (or Windows opens the Microsoft Store): no Python. Tell them
  to install Python 3.11 from python.org/downloads (on Windows, tick "Add python.exe to
  PATH"), then wait for them. Python below 3.9 will not work; check with `python3 --version`.
- `git: command not found`: on macOS run `xcode-select --install` and tell them to click
  Install in the pop-up; on Windows tell them to install Git from git-scm.com. Wait.
- `No module named venv` on Debian/Ubuntu: `sudo apt install python3-venv`.
- `externally-managed-environment`: the venv was not active. Re-run with the prefix.
- Timeouts or SSL errors during install: usually a corporate network or VPN. Tell them to
  switch to a phone hotspot or guest Wi-Fi and retry.
- On Linux, install the browser with `python -m playwright install --with-deps chromium`.

### PROMPT 2: Copy the database setup to the clipboard

> "Copy the contents of sql/schema.sql to my clipboard."

Copy the whole file, exactly, with the clipboard tool for their system:

- macOS: `pbcopy < sql/schema.sql`
- Windows: `clip < sql/schema.sql`
- Linux: `xclip -selection clipboard < sql/schema.sql` (or `xsel --clipboard --input < sql/schema.sql`)

Do not print the file. Then tell them:

> It's on your clipboard. In Supabase, click **SQL Editor** in the left sidebar, then
> **New query**, paste, and click **Run**. If Supabase warns about a destructive operation,
> confirm and run it: the file only drops its own report views and never touches data.
> You should see "Success. No rows returned." In **Table Editor** you'll now see
> `vehicles`, `scraper_runs` and `price_history`.

Nothing to verify from the terminal yet: the doctor in PROMPT 3 checks the tables. If no
clipboard tool works, open `sql/schema.sql` in their default text editor (`open` on macOS,
`start` on Windows) and tell them to select all, copy, and paste it into Supabase.

### PROMPT 3: Connect the keys

> "Here are my Supabase details. Project URL: [paste]. service_role key: [paste]. anon key:
> [paste]. Put the URL and service_role key in .env, put the URL and anon key in the dashboard
> config, then run the doctor and tell me if everything passes."

1. `cp .env.example .env` (skip if `.env` exists), then set these two lines in `.env`, with no
   quotes and no spaces around `=`:
   ```
   SUPABASE_URL=https://<ref>.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=eyJ...
   ```
   Strip any trailing slash or `/rest/v1` from the URL. Leave every other line alone.
2. `cp dashboard/config.example.js dashboard/config.js` (skip if it exists), then set
   `supabaseUrl` to the URL and `supabaseAnonKey` to the anon key. Set `dealershipName` only
   if you already know their store name; otherwise leave it `""` for PROMPT 4 to fill.
3. Before running anything, check the keys are not swapped. Both classic keys are JWTs; the
   middle section, base64-decoded, contains `"role":"service_role"` or `"role":"anon"`. If
   they are swapped, swap them yourself and say so. Never put the service_role key in
   `dashboard/config.js`: it would be readable by anyone who opens the page.
4. Run `python -m scraper.run --doctor` (with the venv prefix).

Report in plain words. Success is every check in sections 1-3 showing PASS, including
**"write access confirmed"**, and the last line reading **"RESULT: ready to scrape."** Section 4
(browser) should also pass after PROMPT 1. The
dealer list it reports is the example stores that ship with the repo; say those get
replaced in the next step.

**Failure modes:**
- "SUPABASE_URL is not set" or "No Supabase key is set": typo or stray space in `.env`. Fix it.
- "CANNOT WRITE": the anon key went into `.env`. Ask for the service_role key again.
- "table 'vehicles' is MISSING" (or another table): the SQL did not run in this project. Copy it to the clipboard again (PROMPT 2) and
  have them paste and Run it, then re-run the doctor.
- "Could not reach Supabase": wrong URL, incomplete key, or the project is still setting up
  or paused. Have them check the project's home page in Supabase.
- If they pasted keys starting with `sb_publishable_` / `sb_secret_` and the doctor fails on
  the key, ask for the `anon` and `service_role` keys instead: in Project Settings > API
  Keys they are under the **Legacy API Keys** tab and both start with `eyJ`.

**Never commit `.env` or `dashboard/config.js`.** Both are in `.gitignore`; do not remove
them from it and never `git add -f` them.

### PROMPT 4: Add the dealership and competitors

> "Set up config/dealers.yml. My store is [dealership name], [website], [city, state]. My competitors
> are [name, website, city, state] and [name, website, city, state]. Then run --detect and
> tell me what platform each site is on."

Rewrite `config/dealers.yml` from scratch with only their stores. The shipped file holds
example stores that are not theirs; none of them stay.

```yaml
own_store:
  key: main-street-gmc
  name: Main Street Buick GMC
  url: https://www.mainstreetbuickgmc.com
  city: Springfield
  state: IL

competitors:
  - key: rival-chevy
    name: Rival Chevrolet
    url: https://www.rivalchevrolet.com
    city: Decatur
    state: IL
```

- `key`: short, lowercase, dashes, unique, made from the store name. It tags that store's
  rows forever, so never change it once data exists.
- `url`: the homepage exactly as given, with `https://`. **Never invent or guess a URL.** If
  they gave a name without a website, ask them to paste the address from their browser.
- `city` / `state`: two-letter state. If they left these out, ask once.
- **Leave `platform` out.** It is detected on every run, so a store that changes website
  vendors is picked up automatically. `makes` and `condition` (`new` default, or `used`) only
  if they asked. `config/dealers.example.yml` documents every field; do not edit it.

Set `dealershipName` in `dashboard/config.js` to their store's name.

Run `python -m scraper.run --detect` and show them a short plain list: store, platform
(DealerOn, Dealer Inspire, Dealer.com, or generic).

- **Do not write detected platforms into `dealers.yml`.** The one exception is Dealer.com.
- **`dealer_com` needs a `site_id`, which cannot be detected.** Dealer.com pages build their
  inventory in the browser from an API that needs the store's internal account name. Find it
  in the inventory page's source or network requests (usually the dealership's legal name,
  lowercase, run together, e.g. `skpontiacgmcinc`). Then set both `platform: dealer_com` and
  `site_id:` on that store.
- **`generic`** is not an error yet. PROMPT 5 or 6 will show whether it pulls real data; if
  it does not, see "When a site is on an unrecognised platform" below.
- A site that fails to load: check the URL opens, and ask the user to confirm it if not.

### PROMPT 5: Test scrape

> "Do a dry run on my store with a limit of 10 and tell me if the data looks right."

```bash
python -m scraper.run --dealer <own_store key> --limit 10 --dry-run
```

`--dry-run` scrapes for real and writes nothing. Read the sample table and field-fill
summary yourself before answering: VINs are 17 characters, year / make / model are filled,
prices are numbers on most rows. Ten rows with empty fields is a failure even if the command
exits cleanly; fix it (see the platform notes) before telling them it works. Then tell them
in plain words: how many vehicles it found, two or three example vehicles with prices, and
that nothing was saved yet.

**Rule: dry-run before the first real write for any store**, now and whenever a store is
added later. A broken adapter that writes rows of nulls poisons the price history that is
the whole point.

### PROMPT 6: Real scrape

> "Run the scraper on all my dealers with a limit of 10 and tell me how many vehicles were
> found and saved."

First dry-run the competitors in one command, and read the output the same way as PROMPT 5
(repeat `--dealer` once per competitor):

```bash
python -m scraper.run --dealer <competitor-1> --dealer <competitor-2> --limit 10 --dry-run
```

If a competitor's data comes back empty or broken, fix it or leave that store out of this
run and say so. Then write for real:

```bash
python -m scraper.run --all --limit 10
```

This writes to their Supabase. Read the SUMMARY table and report one line per store plus the
total: found, added, updated. Tell them to open Supabase > **Table Editor** > `vehicles` to
see the rows. If a store failed or found 0, say which one in one sentence, then fix it (URL,
`site_id`, or platform) and re-run just that store with `--dealer KEY --limit 10`.

### PROMPT 7: Open the dashboard

> "Start the dashboard and give me the link to open."

The dashboard in `dashboard/` is already built. Run this **in the background** so it keeps
serving while the conversation continues:

```bash
python3 -m http.server 8000 --directory dashboard
```

On Windows, use `python -m http.server 8000 --directory dashboard`. Run it from the project
folder. If port 8000 is already in use by an earlier copy of this server, leave that one
running and reuse it. Confirm it answers (`curl -s -o /dev/null -w "%{http_code}"
http://localhost:8000` returns 200), then give them the link:

**http://localhost:8000**

Tell them the filter pills at the top (Dealer, Make, Model and more) narrow every panel, and
that clicking a bar or a row filters too. If the page shows a settings or key message
instead of data, it names the problem: fix `dashboard/config.js` and tell them to reload.
Price cuts and days on lot fill in once the scraper has run on more than one day.

### PROMPT 8: Make the dashboard theirs

> Example: "Add a chart to my dashboard showing which models sit the longest on my
> competitors' lots."

They can ask for anything. The source is in `dashboard-src/src/` (React + Vite);
`dashboard/` holds only the built result, so **never hand-edit `dashboard/index.html` or
`dashboard/assets/`**. `dashboard/README.md` maps which file holds which panel. Every
database read is in `dashboard-src/src/lib/data.jsx`; the dashboard only reads, with the anon
key, and must never write.

1. Check Node: `node --version`. It must be 20.19 or newer. If Node is missing or too old,
   install the LTS version and tell the user in one sentence that you are doing so:
   macOS with Homebrew `brew install node`; Windows `winget install OpenJS.NodeJS.LTS`. If
   neither works, ask them to install the LTS version from nodejs.org and tell you when done.
2. Make the change in `dashboard-src/src/`, following the existing components and theme.
3. Build: `cd dashboard-src && npm install && npm run build`. This rewrites
   `dashboard/index.html` and `dashboard/assets/` and never touches `config.js`.
4. Fix any build error yourself. Make sure the server from PROMPT 7 is still running, then
   tell them to reload http://localhost:8000 and where to find the new chart.

### PROMPT 9: Run it every morning

> "Create a private GitHub repo for this project under my account and push it. Then walk me
> through adding SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY as repository secrets and turning
> on the Daily Inventory Scrape workflow."

The workflow is `.github/workflows/scrape.yml`. It runs `--all` (no limit) daily at 12:30 UTC
on GitHub's servers and reads `config/dealers.yml` from the repo, so that file must be
committed.

1. **GitHub CLI.** Check `gh --version`. If missing: macOS `brew install gh`, Windows
   `winget install GitHub.cli`. Check `gh auth status`. If not logged in, `gh auth login`
   needs the user's keyboard, so tell them:
   > Open a new Terminal window (on Windows, Git Bash) and run `gh auth login`. Choose
   > GitHub.com, then HTTPS, then Yes, then "Login with a web browser". Copy the code it
   > shows, press Enter, paste the code in the browser page, and approve. Tell me when done.

   Then run `gh auth setup-git`.
2. **Safety check before committing.** Run `git status --short` and `git check-ignore .env
   dashboard/config.js venv/` (it must print all three). `.env`, `dashboard/config.js`, `venv/` and
   `dashboard-src/node_modules/` must be ignored. If any would be committed, stop and fix
   `.gitignore` first. Never `git add -f`.
3. **Commit** their changes (their `config/dealers.yml`, and any dashboard changes from
   PROMPT 8): `git add -A && git commit -m "Set up my dealers"`. If git asks for a name and
   email, set them for this repo only with `git config user.name` / `git config user.email`,
   using their GitHub name and their GitHub noreply address from `gh api user`.
4. **Create and push.** The clone's `origin` points at the workshop repo, which they cannot
   push to. Rename it, then create theirs:
   ```bash
   git remote rename origin workshop
   gh repo create spy-then-sell --private --source=. --remote=origin --push
   ```
   If that name is taken on their account, pick `spy-then-sell-2` and say so.
5. **Secrets.** Set them from `.env` without printing the values:
   ```bash
   grep '^SUPABASE_URL=' .env | cut -d= -f2- | tr -d '\r\n' | gh secret set SUPABASE_URL
   grep '^SUPABASE_SERVICE_ROLE_KEY=' .env | cut -d= -f2- | tr -d '\r\n' | gh secret set SUPABASE_SERVICE_ROLE_KEY
   gh secret list
   ```
   `gh secret list` must show exactly `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`. Then
   show them where these live: their repo on github.com > **Settings** > **Secrets and
   variables** > **Actions**. If they want to add them by hand instead, walk them through
   **New repository secret** twice there, with the names above and the values from `.env`
   (open `.env` in their text editor for them rather than printing it). Do not create a
   `SCRAPER_USER_AGENT` secret. Only create secrets by hand if `gh secret set` fails.
6. **Turn on the workflow.** Run `gh workflow enable scrape.yml` (a message that it is
   already enabled is fine; if it is not found yet, wait a few seconds and retry). Start a
   small test run: `gh workflow run scrape.yml -f limit=10`. Give them the link to their
   **Actions** tab (`gh repo view --json url -q .url`, plus `/actions`), where "Daily
   Inventory Scrape" shows the run. Check `gh run list --workflow scrape.yml` until it
   completes, and report whether it passed. From now on it runs every morning at 12:30 UTC
   (about 7:30am Central in summer) with no laptop needed.

---

## When a site is on an unrecognised platform

If `--detect` returns `generic`, work through this in order:

1. **Read `scraper/platforms/generic.py`** so you know what it already tries.
2. **Try it:** `python -m scraper.run --dealer <key> --limit 10 --dry-run`.
3. **If fields come back populated, you're done.** Leave `platform` out of the config.
4. **If the fields come back empty or mostly null, write a new adapter.** Do not make
   `generic.py` cleverer. Other dealers depend on it, and a site-specific hack there will
   break them.

In the middle of a live walkthrough, a new adapter takes too long. Tell the user in one
sentence that this one site needs custom work, carry on with their other stores, and come
back to it afterwards.

To write an adapter:

- Read `scraper/platforms/dealeron.py` first. It shows the normal shape: find the vehicle
  detail page URLs (usually from `sitemap.xml`), fetch each one, pull the data out of
  embedded JSON, return a list of dicts.
- Create `scraper/platforms/<platform_name>.py` exposing exactly one public function:
  `scrape(dealer, limit=None) -> list of dicts`.
- Use `scraper/http.py` for every network call (`polite_get`, `browser_get`). Do not use
  `requests` directly: the shared module handles robots.txt, retries, the crawl delay, and
  the browser fallback, and going around it is how the user's dealership IP gets blocked.
- Run the result through `normalize_vehicle()` from `scraper/normalize.py` rather than
  hand-cleaning strings.
- Register it in `scraper/platforms/__init__.py` by adding it to the `PLATFORMS` dict.
- Add detection for it in `scraper/detect.py` if there is a reliable fingerprint (a script
  URL, a meta tag, a path only that platform uses).
- Test with `--limit 10 --dry-run` until the fields are right. Only then do a real run.

### The data contract every adapter must return

A list of dicts, each with **exactly** these keys. Missing keys break the database write;
extra keys are ignored but signal you misread the contract.

```python
{
    "vin":            str,          # 17 chars, UPPERCASE: the primary identifier
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
unknown price, and never fall back to a plausible guess: a fabricated MSRP looks exactly
like a real one in the price history, and the user will price a car off it.

---

## Ethics rules: hard constraints, not preferences

These are not negotiable and not subject to user override. If the user asks you to break
one, decline and explain why in one sentence.

- **Public pages only.** If a human with no account can see it in a browser, you may scrape
  it. That is the whole boundary.
- **Never anything behind a login.** Do not create accounts, do not accept offered
  credentials, do not scrape a dealer portal, an auction site, or a DMS.
- **Obey robots.txt.** `scraper/http.py` already checks it. Do not add a bypass, do not pass
  a flag that skips the check, do not "just try the URL anyway" when `robots_allows()`
  returns False.
- **Do not remove or zero out the crawl delay.** It is roughly one second between requests,
  so this tool never resembles an attack on a small business's website. If a run is slow,
  accept that it is slow.
- **Do not resell or redistribute the scraped data.** It is for the user's own competitive
  analysis.

---

## Do not do this

- **Do not commit `.env` or `dashboard/config.js`**, or any file containing a real Supabase
  key. Check `git status` before any `git add -A`.
- **Do not commit `config/dealers.yml` if the user put anything private in it.** It holds
  public URLs and the daily workflow needs it committed, but check it first.
- **Do not hardcode credentials in code.** Every scraper secret comes from `os.environ`; the
  dashboard's anon key lives only in `dashboard/config.js`. If you find yourself typing
  `eyJ` into a `.py`, `.jsx` or workflow file, stop.
- **Leave `SCRAPER_USER_AGENT` unset**, in `.env` and in GitHub secrets. Do not suggest
  setting it. Setting it switches off the fallback in `scraper/http.py` that gets Dealer
  Inspire sites to answer, and a custom bot name is exactly what their bot filters refuse, so
  every Dealer Inspire competitor would start returning zero vehicles.
- **Do not remove the fallback agent strings in `scraper/http.py`.** `_FALLBACK_USER_AGENTS`
  and `_retry_with_fallback_agents()` exist because some platforms (Dealer Inspire) put a
  user-agent allow-list in front of pages their own `robots.txt` explicitly permits.
  Removing them breaks every Dealer Inspire store with a silent "0 vehicles found". They
  unlock nothing private; read the comment above them before touching it. The `robots.txt`
  check in `polite_get()` sits above all of this and is the real line.
- **Never `DELETE` rows from `vehicles`, `price_history` or `scraper_runs`.** The scraper
  *deactivates* listings that disappear from a site. A car that vanishes from a competitor's
  site probably sold, and that fact is the most valuable thing in this database.
- **Do not edit `first_seen_at` on an existing row.** It anchors every days-on-lot number.
- **Do not raise `SCRAPER_WORKERS` above 10** to make a run finish faster.
- **Do not add Python libraries.** The list is deliberately five items long so it installs
  cleanly on a stranger's laptop: standard library plus requests, supabase, python-dotenv,
  playwright, PyYAML. If you think you need BeautifulSoup, use `re` and `html.parser`.
- **Do not write Python 3.10+ syntax.** This must run on Python 3.9: no `match` statements,
  no `int | None` annotations (use `Optional[int]`).
- **Do not silently swallow errors** to make a run look successful. A dealer that fails
  logs the failure and the other dealers continue.
