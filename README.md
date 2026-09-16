# Dealership Inventory Scraper

Know what every competitor in your market has on the ground, and what they're asking for it,
before your 8am sales meeting.

This tool reads your competitors' public inventory pages once a day and files every vehicle
into a database you own. After a couple of weeks you can answer questions you currently
guess at:

- Who else has a Denali Ultimate in white within 60 miles, and what are they asking?
- Which of my units has been sitting longest compared to the same trim down the road?
- Did the store in the next town just drop $2,000 across their Sierra 1500s?
- How many days did that trim take to move at their price, versus mine?

It is built to be set up by an AI coding assistant. You clone it, open it with Claude Code,
and say *"read this repo and set it up for me."* The assistant handles the terminal; it will
ask you for your Supabase keys and your competitors' web addresses, and nothing else.

**What it is not:** it reads public web pages only, the same ones any shopper can see. It
never touches a login, a dealer portal, or a DMS.

---

## Quickstart

You need [Python 3.9+](https://www.python.org/downloads/) and a free
[Supabase](https://supabase.com) account.

**1. Get the code and install it**

```bash
git clone https://github.com/esurratt4/LearnClaudeForDealers.git
cd LearnClaudeForDealers
python3 -m venv venv && source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
```

**2. Add your Supabase keys**

```bash
cp .env.example .env
```

Open `.env` and paste in your **Project URL** and **service_role key**. Both are in your
Supabase dashboard under Project Settings → API. This file stays on your machine — it is
already excluded from git.

**3. Create the tables**

In Supabase, open **SQL Editor → New query**, paste the entire contents of `sql/schema.sql`,
and hit Run. You should see "Success. No rows returned."

**4. Point it at your stores**

Edit `config/dealers.yml` — see below.

**5. Check everything**

```bash
python -m scraper.run --doctor     # keys, connection, tables
python -m scraper.run --detect     # what platform each site runs on
```

**6. Test, then run for real**

```bash
python -m scraper.run --dealer my-store --limit 10 --dry-run   # scrapes, saves nothing
python -m scraper.run --all                                    # the real thing
```

Always do a `--dry-run` on a new dealer before letting it write.

---

## Point it at your own sites

Everything the scraper knows about lives in `config/dealers.yml`. Use real homepage URLs,
copied from your browser.

```yaml
# Your store goes under own_store. Everyone you watch goes under competitors.
own_store:
  key: my-store
  name: Main Street Buick GMC
  url: https://www.mainstreetbuickgmc.com
  city: Springfield
  state: IL
  # platform is left out on purpose — the scraper detects it.

competitors:
  - key: rival-chevy
    name: Rival Chevrolet
    url: https://www.rivalchevrolet.com
    city: Decatur
    state: IL

  - key: crosstown-gmc
    name: Crosstown GMC
    url: https://www.crosstowngmc.com
    city: Bloomington
    state: IL
    makes: ["GMC"]        # optional: only keep these brands
    condition: used       # optional: "new" (default) or "used"

  # Dealer.com stores are the one exception — spell both of these out.
  - key: westside-gmc
    name: Westside GMC
    url: https://www.westsidegmc.com
    city: Normal
    state: IL
    platform: dealer_com
    site_id: westsidegmcinc
```

Full field-by-field notes live in `config/dealers.example.yml`.

`key` is a short nickname with no spaces — it's what you type after `--dealer`, and it's how
rows are tagged in the database, so don't change it later.

Start with two or three competitors. You can always add more.

---

## Commands

All commands are run as `python -m scraper.run ...` with the virtual environment active.

| Command | What it does |
|---|---|
| `--doctor` | Checks your keys, database connection, tables, and config file. Run this first when anything breaks. |
| `--list` | Shows every dealer in your config and when each was last scraped. |
| `--detect` | Reports which website platform each dealer runs on. |
| `--dealer KEY` | Scrapes one dealer instead of all of them. |
| `--limit N` | Stops after N vehicles per dealer. Use `--limit 10` for testing. |
| `--dry-run` | Scrapes and prints results but writes nothing to the database. |
| `--all` | Scrapes every dealer in the config. This is what the daily schedule runs. |

Flags combine: `--dealer rival-chevy --limit 10 --dry-run` is the standard way to test a new
competitor.

---

## What the tables mean

**Tables — the raw record:**

| Table | What's in it |
|---|---|
| `vehicles` | One row per VIN per dealer: year, make, model, trim, colors, MSRP, asking price, mileage, photos, link. Updated in place each run. Listings that disappear are marked inactive, **never deleted** — that's how you know something sold. |
| `scraper_runs` | A log of every run: which dealer, when, how many found, and any error. Your early-warning system for a scrape that quietly stopped working. |
| `price_history` | An append-only trail of every price seen, with its timestamp. This is the asset that gets more valuable every day the tool runs. |

**Views — the ready-made answers.** A view is a saved question; query it like a table.

| View | Example question it answers |
|---|---|
| `v_active_inventory` | "What's on every lot right now, and how long has each unit been sitting?" |
| `v_price_drops` | "Who cut a price recently, and by how much?" |
| `v_price_comparison` | "For a Sierra 1500 AT4, am I priced above or below the market?" |
| `v_market_gaps` | "What are competitors stocking that I have none of?" |
| `v_inventory_by_dealer` | "How much does each store have on the ground? (the morning scoreboard)" |

You can query these in Supabase's Table Editor, or just point your AI assistant at the
database and ask in plain English.

---

## Run it automatically every morning

The repo includes a GitHub Action that runs the scrape daily at 12:30 UTC (about 7:30am
Central) on GitHub's servers — your laptop can be closed.

1. Push this repo to your own GitHub account.
2. Go to **Settings → Secrets and variables → Actions → New repository secret** and add two:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY`

   Use the same values as your `.env`. GitHub encrypts them and hides them from the logs.
3. Open the **Actions** tab and enable workflows if prompted.

To test it immediately, go to Actions → "Daily Inventory Scrape" → **Run workflow**. You can
optionally pass a single dealer key and a limit to try a small run first.

To change the time, edit the `cron` line in `.github/workflows/scrape.yml`. Remember it's in
UTC.

---

## Troubleshooting

**"403 Forbidden" or the scrape returns nothing for one site.**
The site is refusing automated requests. Lower `SCRAPER_WORKERS` in `.env` to `2`, wait a
few minutes, and try again. The scraper automatically retries with a real browser, but some
sites need the slower pace. Setting `SCRAPER_USER_AGENT` to your dealership name and an
email address also helps — it makes the traffic identifiable rather than anonymous.

**"No site_id configured" on a Dealer.com site.**
Dealer.com sites need an account ID that isn't in the URL. It's usually a lowercase,
run-together version of the dealership's legal name (e.g. `skpontiacgmcinc`). Ask your AI
assistant to find it in the site's page source and add it to that dealer's `site_id:` field
in `config/dealers.yml`.

**"Executable doesn't exist" or a Playwright error.**
You skipped the browser install. Run `python -m playwright install chromium`. On Linux, use
`python -m playwright install --with-deps chromium`.

**A run finishes but finds zero vehicles.**
Usually a wrong URL or the wrong `condition`. Check the URL opens in your browser, and check
whether you asked for `new` on a used-only lot. Then run `--detect` again — a dealer may
have changed website vendors, which happens more often than you'd think.

**"My competitor's site isn't supported."**
Four platforms cover most of the market, and a `generic` fallback handles many of the rest.
If `--detect` says `generic` and the results come back empty, ask your AI assistant to write
an adapter for it — the instructions and the required data format are spelled out in
`CLAUDE.md`, and it's normally a 30-minute job.

**Everything is broken and you don't know where to start.**
`python -m scraper.run --doctor`. Then paste the output to your assistant.

---

## Ethics and licence

This tool reads **public web pages only** — the same listings any shopper sees. It respects
`robots.txt`, waits between requests so it never burdens a small business's server, and
identifies itself honestly. It does not touch anything behind a login, and it does not
attempt to evade bot protection.

The data is for your own competitive analysis. Don't resell or redistribute it. Check your
own obligations before pointing this at anything other than public dealership inventory.

MIT licence. Provided as-is, with no warranty. You are responsible for how you use it.
