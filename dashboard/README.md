# The Dashboard

This is the part you look at. The scraper fills the database; this page turns it
into an argument you can act on: what the competition is stocking that you are
not, where you sit on price, and which of their cars they have already given up
on.

## Run it

From the project folder, in a terminal:

```
python3 -m http.server 8000 --directory dashboard
```

Then open **http://localhost:8000** in your browser. Press Ctrl+C in the terminal
to stop it.

That is the whole install. There is nothing to `npm install`, no build step, no
framework. It is one HTML file and one small settings file.

**Do not just double-click index.html.** A double-clicked file opens as
`file:///...`, and some browsers refuse to let a `file://` page make network
calls. The dashboard would look broken for a reason that has nothing to do with
your data. Serving it over `http://` costs you one command and avoids that
entirely.

## Set it up (once)

```
cp dashboard/config.example.js dashboard/config.js
```

Open `dashboard/config.js` and paste in three things from your Supabase project
(Settings → API):

| Setting | What it is |
|---|---|
| `supabaseUrl` | Your Project URL, e.g. `https://abcdefgh.supabase.co` |
| `supabaseAnonKey` | The key labelled **anon / public**. Not the service_role key. |
| `dealershipName` | The headline at the top of the page |

`config.js` is gitignored, because a key is a key and it is specific to you.

### About the two keys

Supabase gives you an **anon** key and a **service_role** key.

- The **anon** key is read-only here. `sql/schema.sql` grants it `SELECT` on the
  five reports and nothing else. It goes in the browser. Anyone who opens the
  dashboard can see it, and the worst they can do with it is look at your
  inventory reports.
- The **service_role** key can write and delete anything and ignores every
  security rule in the database. **The scraper** uses it, from `.env`. It must
  never appear in a browser, a screenshot, or a public repo.

The dashboard checks the key you gave it and refuses to run if it is not an anon
key, because that particular mistake is expensive.

## What each panel answers

| Panel | The question it answers | Built from |
|---|---|---|
| **KPI row** | Where do I stand right now? Your units against theirs, how many stores we watch, whether your cars turn faster than theirs, and how many of their price cuts we have caught. | `v_active_inventory`, `v_inventory_by_dealer`, `v_price_drops` |
| **They have it, you don't** | What is the competition stocking in real volume that I have none of? Each row is a car to order or go find. The right-hand column is the mirror image: what you stock that nobody else does. | `v_market_gaps` |
| **Price position** | On the cars we both have on the ground, am I above or below the market, and by how much? Bars left = you are cheaper. Bars right = you are asking more. | `v_price_comparison` |
| **Competitor price cuts** | Who blinked? What they listed it at, what it is now, and how many days they held out first. That last number is their aging pain in days. | `v_price_drops` |
| **The lots** | One line per store: units, average price, average days on lot, and when we last looked — so you can tell "they sold 40 cars" apart from "the scraper did not run". | `v_inventory_by_dealer` |

## Day one: half of it will be empty, and that is correct

If you open this ninety seconds after your first ever scrape:

- **Competitor price cuts will be empty.** A price cut is the difference between
  two looks at the same car, so the earliest it can show anything is the second
  time the scraper runs. The panel says so. Come back in a week and it will be
  the first place you look.
- **Price position may be empty** until both you and a competitor have the same
  model and trim on the ground at the same time.
- **If nothing at all is in the database**, the page says that too, and gives you
  the command to run.

Every empty panel explains what will fill it and when. None of them show a blank
box, a broken chart, or a zero pretending to be a number.

## If something looks wrong

The page tells you which kind of problem it is, which matters — "no rows" and
"wrong key" look identical if you do not separate them:

- **"config.js is missing or incomplete"** — you have not copied the example file
  yet, or a value is still a placeholder.
- **"The database refused the key"** — Supabase answered, so your internet is
  fine. The anon key is wrong, or `sql/schema.sql` has not been run so the anon
  role has no permission to read the views.
- **"The reports do not exist yet"** — the database is there but the views are
  not. Paste `sql/schema.sql` into the Supabase SQL Editor and run it.
- **"Could not reach the database"** — a connection problem, not a data problem.
  Check the wifi, check `supabaseUrl` for a typo, and make sure you served the
  page over `http://localhost:8000` rather than double-clicking it.

## Changing it

Open this folder with Claude Code and ask in plain English:

- "in the dashboard, show the top 25 gap rows instead of 15"
- "add an average mileage column to The Lots table"
- "make the price cuts panel show sold units too"

Everything lives in `dashboard/index.html`, and each block of code in it has a
heading comment saying what it does.

## Notes

- **No chart library.** The bars are plain HTML and CSS. Nothing is downloaded
  from a CDN, so conference wifi cannot turn this page into a blank white screen.
  Its only network call is to your Supabase database.
- **It refreshes itself every two minutes**, so a scrape that finishes while the
  page is open simply appears. There is also a Refresh button.
- **It reads, it never writes.** Nothing you do on this page can change your
  database.
