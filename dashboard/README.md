# The Dashboard

The scraper fills your database. This turns it into answers: what the competition
stocks that you don't, where you sit on price, which of your units are aging, and
which competitor cars have already been marked down.

This folder is the finished, already-built website. Running it needs Python and
nothing else: no npm, no Node.js, no build step.

## Run it

From the project folder, in a terminal:

```
python3 -m http.server 8000 --directory dashboard
```

Open **http://localhost:8000** in your browser. Press Ctrl+C in the terminal to stop it.

Serve it this way. Double-clicking `index.html` opens it as a `file://` page, and
browsers block the database calls from there.

## Settings (once)

The dashboard reads `dashboard/config.js`. Create it from the template:

```
cp dashboard/config.example.js dashboard/config.js
```

and fill in:

| Setting | Where it comes from |
|---|---|
| `supabaseUrl` | Supabase: Project Settings > Data API > Project URL, e.g. `https://abcdefghijklmnop.supabase.co` |
| `supabaseAnonKey` | Supabase: Project Settings > API Keys > the **anon** key. Not the service_role key. |
| `dealershipName` | The name at the top of the page. Leave it `""` to use your `own_store` name from `config/dealers.yml`. |

In Claude Code you can just say: *"put the URL and anon key in the dashboard config."*

`config.js` is gitignored. After changing it, reload the page.

### The two keys

- **anon** is read-only. `sql/schema.sql` lets it read and nothing else. It is the
  one that belongs in a web page.
- **service_role** can change or delete anything. The scraper uses it, from `.env`.
  It must never go in `config.js`. The dashboard checks, and refuses to run if it
  finds one.

## What is on it

**Market** (the home page): your store against every competitor.

| Panel | What it answers |
|---|---|
| KPI row | Your units, average asking price, models, trims and days on lot against the competition's |
| The stores | One line per store: units, average MSRP and selling price, average days on lot, when it was last scraped. Click a competitor to show only that store. |
| Inventory by model | How many of each model you and they have, and each model's share of the lot |
| Color availability | Which exterior colors each side stocks |
| Gap analysis | Model and trim combinations they have and you don't, and the reverse |
| Trim mix | For one model, how your trims split against theirs |
| Price position | Average asking price by model and trim, yours against theirs |
| Who blinked | Competitor units still listed at a lower price than when first seen |
| Competitor inventory | Every competitor vehicle, searchable and sortable |

**My Lot**: your own inventory. Units, days on lot, capital tied up in 60+ day units,
inventory and trim mix, age buckets, days on lot by color, trim, engine and body
style, price bands, and every unit oldest first.

**Price Cuts**: every price drop the scraper has recorded, with what it was, what it
is now, and how many days the dealer held the original price.

**Vehicle page**: click any VIN. Its details, its price history chart, and every
other unit of the same model at your store and each competitor.

### Slice and dice

The filter pills at the top of each page (Dealer, New / Used, Make, Model, Trim,
Color and more) narrow every panel on that page at once. Clicking a bar, a donut
slice or a table row adds that value as a filter too. Click a black chip to remove
it, or **Clear all**. Filters reset when you change pages.

**Asking price** means the selling price when the dealer's site posts one, otherwise
MSRP. **Days on lot** counts from the first day the scraper saw that car on that
dealer's site.

## When a panel is empty

- **Price cuts are empty at first.** A cut is the difference between two looks at the
  same car, so it needs the scraper to run on at least two different days.
- **Days on lot reads near 0 at first** for the same reason. It becomes meaningful
  after a week or two of daily scrapes.
- **Nothing in the database yet**: the page says so and gives you the exact thing to
  paste into Claude Code to run the scraper.

## When something is wrong

The page names the problem instead of showing a blank screen:

| Message | What to do |
|---|---|
| The dashboard has no settings yet | `dashboard/config.js` is missing. Create it from `config.example.js`. |
| Your Supabase Project URL / anon key is not filled in | A value in `config.js` is still a placeholder. |
| The settings file has a typo | Usually a missing quote around a pasted key. |
| That is the service_role key | Swap it for the anon key. |
| The key belongs to a different Supabase project | Copy the URL and key from the same project. |
| Supabase did not accept the key | The anon key was copied incompletely. Copy it again. |
| Your database has no tables yet | Ask Claude to apply `sql/schema.sql` to your project with the Supabase MCP. |
| Could not reach your database | Check the internet connection and the Project URL, and that the address bar says `http://localhost:8000`. |

The page reloads its data every 5 minutes, and the **Refresh** button reloads it now.
Nothing on the page can change your database.

## Changing it

The source code lives in `dashboard-src/`. This folder holds only the built result.
Ask Claude Code in plain English, for example:

- "Add a chart to my dashboard comparing how many vehicles each dealer has in each $10,000 price range."
- "Add an average mileage column to the competitor table."
- "Show the top 50 rows in the gap analysis instead of 25."

Claude edits the files in `dashboard-src/src/` and rebuilds. Rebuilding needs
[Node.js](https://nodejs.org) (the LTS version, 20.19 or newer) on the laptop doing the change:

```
cd dashboard-src
npm install
npm run build
```

`npm run build` rewrites `dashboard/index.html` and `dashboard/assets/`, and never
touches `config.js`, `config.example.js`, this README or `preview.png`. Reload the
browser to see the change. Commit both `dashboard-src/` and the rebuilt `dashboard/`.

Where things are in `dashboard-src/src/`:

| File | What it holds |
|---|---|
| `lib/data.jsx` | Every database read: which tables and columns, price and days-on-lot rules |
| `lib/filters.jsx` | The filter pills and how each one reads a vehicle |
| `pages/MarketIntel.jsx` | Market page layout |
| `pages/LotView.jsx` | My Lot page layout |
| `pages/PriceCuts.jsx` | Price Cuts page |
| `pages/VehicleDetail.jsx` | Single vehicle page with price history |
| `components/market/MarketCharts.jsx` | Every Market panel |
| `components/lot/LotCharts.jsx` | Every My Lot panel |
| `components/StatusScreens.jsx` | The setup, error and empty-database messages |
| `lib/theme.js` | Colors: teal is your store, brown is the competition |

For live editing while you work, `npm run dev` inside `dashboard-src` serves the
source with instant reloads, using the same `dashboard/config.js`.
