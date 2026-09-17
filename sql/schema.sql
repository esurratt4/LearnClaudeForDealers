-- ============================================================================
--  DEALERSHIP INVENTORY SCRAPER - DATABASE SETUP
-- ============================================================================
--
--  WHAT THIS IS
--  This file builds the three tables and five reports that the scraper writes to
--  and that you read from. You run it once, at the very beginning, and then never
--  think about it again.
--
--  HOW IT GETS RUN
--  Claude applies this whole file, unmodified, to your Supabase project through
--  the Supabase MCP (apply_migration). That is PROMPT 2 in CLAUDE.md. You never
--  open Supabase to paste it.
--
--  IF SOMETHING GOES WRONG
--  Fix it and run the whole file again. Every statement in here is written to be
--  safe to re-run - it either creates a thing or shrugs and moves on if the thing
--  already exists. Running this twice will not duplicate your tables and will not
--  delete your scraped vehicles.
--
--  ABOUT KEYS AND SECURITY (read this part, it is short)
--  Supabase gives you two keys. The "anon" key is public and safe to put in a
--  website - this file grants it READ-ONLY access. The "service_role" key can write
--  anything and IGNORES every security rule below it. The scraper uses that one.
--  It belongs in your .env file and in GitHub Secrets. It must NEVER appear in a
--  browser, a front-end app, a screenshot, or a public repo.
-- ============================================================================


-- ============================================================================
--  TABLE 1 OF 3: vehicles
--  One row per car, per dealer. This is the lot.
-- ============================================================================

create table if not exists public.vehicles (
    id              bigint generated always as identity primary key,

    -- Identity: which car, on whose lot
    vin             text not null,
    dealer_key      text not null,   -- short slug from config/dealers.yml, e.g. "laura_chevy"
    dealer_name     text,
    dealer_city     text,
    dealer_state    text,
    is_own_store    boolean default false,
    condition       text default 'new',   -- 'new' or 'used'

    -- The vehicle itself
    stock_number    text,
    year            integer,
    make            text,
    model           text,
    trim            text,
    body_type       text,
    engine          text,
    fuel_type       text,
    drivetrain      text,            -- normalized to AWD / 4WD / FWD / RWD / 2WD
    exterior_color  text,
    interior_color  text,
    msrp            numeric,
    selling_price   numeric,
    mileage         integer,
    horsepower      integer,
    listing_url     text,
    photo_urls      text[],          -- a list of image links, stored in one column

    -- Timeline
    first_seen_at   timestamptz default now(),  -- DO NOT let the scraper overwrite this
    last_seen_at    timestamptz default now(),
    scraped_at      timestamptz default now(),
    is_active       boolean default true,       -- false = no longer on their website
    removed_at      timestamptz,                -- when it vanished from the site
                                                -- (we never delete the row)

    -- ------------------------------------------------------------------
    --  WHY THE KEY IS (vin, dealer_key) AND NOT JUST vin
    -- ------------------------------------------------------------------
    --  A VIN is unique to a car in the world, so the obvious move is to make VIN the
    --  key. That is wrong here, for two very ordinary reasons:
    --
    --    1. DEALER TRADES. Store A trades a Silverado to Store B. For a few days the
    --       same VIN is legitimately listed on both websites. With VIN alone as the
    --       key, the second store's scrape would overwrite the first store's row and
    --       you would lose a lot's worth of history to a routine trade.
    --
    --    2. SHARED LISTING FEEDS. Dealer groups syndicate inventory across their own
    --       rooftops. The same truck shows up on three sites by design.
    --
    --  Keying on the PAIR means each dealer gets their own row for that VIN, and -
    --  the part that actually matters - their own first_seen_at. Days-on-lot is only
    --  meaningful per dealer: "this truck has been on LAURA's lot 94 days" is a
    --  negotiating position. "This VIN has existed for 94 days" is trivia.
    -- ------------------------------------------------------------------
    constraint vehicles_vin_dealer_key_unique unique (vin, dealer_key)
);

-- Indexes: the database's table of contents. Without them, every report below has to
-- read all 50,000 rows to answer "show me Laura's active trucks."
create index if not exists idx_vehicles_dealer_active on public.vehicles (dealer_key, is_active);
create index if not exists idx_vehicles_make_model    on public.vehicles (make, model);
create index if not exists idx_vehicles_vin           on public.vehicles (vin);


-- ============================================================================
--  TABLE 2 OF 3: scraper_runs
--  The logbook. One row every time the scraper runs.
--
--  This table's whole job is to let you tell these two things apart:
--    "the competitor sold 40 cars"   (real, interesting)
--    "the scraper broke"             (not real, fix it)
--  Without a logbook those look identical in the data.
-- ============================================================================

create table if not exists public.scraper_runs (
    id                   bigint generated always as identity primary key,
    dealer_key           text,
    dealer_name          text,
    started_at           timestamptz default now(),
    finished_at          timestamptz,
    status               text default 'running',  -- running | success | partial | error
    vehicles_found       integer,
    vehicles_added       integer,
    vehicles_updated     integer,
    vehicles_deactivated integer,
    error_message        text
);

create index if not exists idx_scraper_runs_dealer on public.scraper_runs (dealer_key, started_at desc);


-- ============================================================================
--  TABLE 3 OF 3: price_history
--  One row every time a vehicle's price changes, plus one the day we first see it.
--
--  This is the table that pays for the whole project. The `vehicles` table only ever
--  knows today's price. This one remembers that the F-150 in stall 12 was $58,900 in
--  March and is $54,400 now, and that it has not moved in 71 days.
-- ============================================================================

create table if not exists public.price_history (
    id             bigint generated always as identity primary key,
    vin            text not null,
    dealer_key     text not null,
    observed_at    timestamptz default now(),
    msrp           numeric,
    selling_price  numeric
);

-- Sorted newest-first per car, because that is how every price question is asked:
-- "what is the latest price, and what was it before that?"
create index if not exists idx_price_history_vin_dealer
    on public.price_history (vin, dealer_key, observed_at desc);


-- ============================================================================
--  THE REPORTS ("VIEWS")
--
--  A view is a saved question. It stores no data of its own - it re-runs against the
--  live tables every time you look at it, so it is never stale.
--
--  We DROP then CREATE each one instead of using CREATE OR REPLACE. Replacing a view
--  fails if you have changed its columns, which would make this file un-re-runnable
--  the first time you tweak a report. Dropping a view deletes zero vehicles; a view
--  is just a saved question, not a filing cabinet.
--
--  security_invoker = true means the view checks the permissions of whoever is
--  READING it, rather than running with the elevated rights of whoever created it.
--  That is what keeps the read-only anon key genuinely read-only.
-- ============================================================================


-- ----------------------------------------------------------------------------
--  v_active_inventory
--  Everything currently on a lot, with how long it has been sitting.
--  Start here. This is the report you will open most often.
-- ----------------------------------------------------------------------------
drop view if exists public.v_active_inventory cascade;
create view public.v_active_inventory
with (security_invoker = true) as
select
    v.dealer_key,
    v.dealer_name,
    v.dealer_city,
    v.dealer_state,
    v.is_own_store,
    v.condition,
    v.vin,
    v.stock_number,
    v.year,
    v.make,
    v.model,
    v.trim,
    v.body_type,
    v.drivetrain,
    v.exterior_color,
    v.interior_color,
    v.msrp,
    v.selling_price,
    v.mileage,
    v.listing_url,
    v.first_seen_at,
    v.last_seen_at,
    -- Days on lot. Measured from the FIRST time we ever saw this car on THIS dealer's
    -- site. Anything over ~60 is a car the manager is losing sleep over, and anything
    -- over ~90 is a car they will deal on.
    (current_date - v.first_seen_at::date) as days_on_lot
from public.vehicles v
where v.is_active = true;


-- ----------------------------------------------------------------------------
--  v_market_gaps
--  "What are they all stocking that I am not?"
--
--  Finds make/model/trim combinations that competitors carry in real volume while
--  your own store has little or none. Each row is a potential order.
--
--  We require at least 2 competitor units so that one weird one-off order from one
--  store does not read as a market trend.
-- ----------------------------------------------------------------------------
drop view if exists public.v_market_gaps cascade;
create view public.v_market_gaps
with (security_invoker = true) as
with competitor_stock as (
    select
        make,
        model,
        coalesce(trim, '') as trim,
        count(*)                       as competitor_units,
        count(distinct dealer_key)     as competitor_dealers,
        round(avg(coalesce(selling_price, msrp)), 0) as avg_competitor_price
    from public.vehicles
    where is_active = true
      and is_own_store = false
      and make is not null
      and model is not null
    group by make, model, coalesce(trim, '')
),
own_stock as (
    select
        make,
        model,
        coalesce(trim, '') as trim,
        count(*) as own_units
    from public.vehicles
    where is_active = true
      and is_own_store = true
      and make is not null
      and model is not null
    group by make, model, coalesce(trim, '')
)
select
    c.make,
    c.model,
    nullif(c.trim, '') as trim,
    c.competitor_units,
    c.competitor_dealers,
    coalesce(o.own_units, 0) as own_units,
    c.avg_competitor_price
from competitor_stock c
left join own_stock o
       on o.make = c.make
      and o.model = c.model
      and o.trim = c.trim
where c.competitor_units >= 2
  -- "Zero or near-zero": you have none, or you have one against a field of several.
  and coalesce(o.own_units, 0) <= greatest(1, c.competitor_units / 10)
order by c.competitor_units desc, c.competitor_dealers desc;


-- ----------------------------------------------------------------------------
--  v_price_comparison
--  Head to head. Only shows model/trim combos where BOTH you and at least one
--  competitor have a unit on the ground right now - otherwise you are comparing
--  your truck to nothing.
--
--  price_gap is YOUR price minus THEIRS:
--    positive = you are priced higher
--    negative = you are priced lower
-- ----------------------------------------------------------------------------
drop view if exists public.v_price_comparison cascade;
create view public.v_price_comparison
with (security_invoker = true) as
with own_side as (
    select
        make,
        model,
        coalesce(trim, '') as trim,
        count(*) as own_units,
        round(avg(coalesce(selling_price, msrp)), 0) as own_avg_price
    from public.vehicles
    where is_active = true
      and is_own_store = true
      and coalesce(selling_price, msrp) is not null
    group by make, model, coalesce(trim, '')
),
competitor_side as (
    select
        make,
        model,
        coalesce(trim, '') as trim,
        count(*) as competitor_units,
        count(distinct dealer_key) as competitor_dealers,
        round(avg(coalesce(selling_price, msrp)), 0) as competitor_avg_price
    from public.vehicles
    where is_active = true
      and is_own_store = false
      and coalesce(selling_price, msrp) is not null
    group by make, model, coalesce(trim, '')
)
select
    o.make,
    o.model,
    nullif(o.trim, '') as trim,
    o.own_units,
    c.competitor_units,
    c.competitor_dealers,
    o.own_avg_price,
    c.competitor_avg_price,
    (o.own_avg_price - c.competitor_avg_price) as price_gap,
    case
        when o.own_avg_price < c.competitor_avg_price then 'own_store'
        when o.own_avg_price > c.competitor_avg_price then 'competitor'
        else 'tie'
    end as cheaper_side
-- INNER joins on purpose: both sides must actually have inventory.
from own_side o
join competitor_side c
       on c.make = o.make
      and c.model = o.model
      and c.trim = o.trim
order by abs(o.own_avg_price - c.competitor_avg_price) desc;


-- ----------------------------------------------------------------------------
--  v_inventory_by_dealer
--  The one-line-per-store scoreboard. Good for a morning glance.
-- ----------------------------------------------------------------------------
drop view if exists public.v_inventory_by_dealer cascade;
create view public.v_inventory_by_dealer
with (security_invoker = true) as
select
    dealer_key,
    max(dealer_name)  as dealer_name,
    max(dealer_city)  as dealer_city,
    max(dealer_state) as dealer_state,
    bool_or(is_own_store) as is_own_store,
    count(*) as active_units,
    round(avg(msrp), 0)          as avg_msrp,
    round(avg(selling_price), 0) as avg_selling_price,
    round(avg(current_date - first_seen_at::date), 1) as avg_days_on_lot,
    max(last_seen_at) as last_scraped_at
from public.vehicles
where is_active = true
group by dealer_key
order by active_units desc;


-- ----------------------------------------------------------------------------
--  v_price_drops   <-- THE ONE TO SHOW PEOPLE
--
--  Every vehicle whose asking price is LOWER today than the first time we saw it.
--  This is the report that a competitor cannot hide and did not announce. A price cut
--  on a unit that has been sitting 80 days tells you their floor, their aging pain,
--  and roughly what they will do on a trade - before you ever pick up the phone.
--
--  How it works: for each (vin, dealer_key) we pull the earliest recorded price and
--  the latest recorded price out of price_history using DISTINCT ON, which is
--  Postgres's tidy way of saying "give me one row per group, the first one after
--  sorting." Then we keep only the pairs where the number went down.
-- ----------------------------------------------------------------------------
drop view if exists public.v_price_drops cascade;
create view public.v_price_drops
with (security_invoker = true) as
with first_obs as (
    select distinct on (vin, dealer_key)
        vin, dealer_key, observed_at, selling_price
    from public.price_history
    where selling_price is not null
    order by vin, dealer_key, observed_at asc
),
latest_obs as (
    select distinct on (vin, dealer_key)
        vin, dealer_key, observed_at, selling_price
    from public.price_history
    where selling_price is not null
    order by vin, dealer_key, observed_at desc
)
select
    v.dealer_key,
    v.dealer_name,
    v.is_own_store,
    v.vin,
    v.stock_number,
    v.year,
    v.make,
    v.model,
    v.trim,
    f.selling_price as original_price,
    l.selling_price as current_price,
    (f.selling_price - l.selling_price)            as price_drop,
    round(
        100.0 * (f.selling_price - l.selling_price) / nullif(f.selling_price, 0),
        1
    )                                              as price_drop_pct,
    f.observed_at   as first_observed_at,
    l.observed_at   as last_observed_at,
    -- How long they held out before cutting.
    (l.observed_at::date - f.observed_at::date)    as days_between,
    (current_date - v.first_seen_at::date)         as days_on_lot,
    v.is_active,
    v.listing_url
from first_obs f
join latest_obs l
       on l.vin = f.vin
      and l.dealer_key = f.dealer_key
join public.vehicles v
       on v.vin = f.vin
      and v.dealer_key = f.dealer_key
where l.selling_price < f.selling_price
order by (f.selling_price - l.selling_price) desc;


-- ============================================================================
--  SECURITY (Row Level Security)
--
--  Turning RLS on means "deny everything by default." Then we add exactly one
--  permission back: the public anon key may READ. Nobody using the public key can
--  insert, update or delete a thing.
--
--  So how does the scraper write? It uses the service_role key, and the service_role
--  key BYPASSES RLS entirely - these policies simply do not apply to it. That is by
--  design, and it is exactly why that key must live only in your .env file and in
--  GitHub Secrets, and must NEVER be shipped to a browser or committed to a repo.
--  Anyone holding it has full write access to this database.
--
--  drop policy if exists ... before each create policy, so re-running this file
--  does not error with "policy already exists".
-- ============================================================================

alter table public.vehicles      enable row level security;
alter table public.scraper_runs  enable row level security;
alter table public.price_history enable row level security;

drop policy if exists "anon can read vehicles" on public.vehicles;
create policy "anon can read vehicles"
    on public.vehicles for select to anon using (true);

drop policy if exists "anon can read scraper_runs" on public.scraper_runs;
create policy "anon can read scraper_runs"
    on public.scraper_runs for select to anon using (true);

drop policy if exists "anon can read price_history" on public.price_history;
create policy "anon can read price_history"
    on public.price_history for select to anon using (true);

-- RLS decides WHICH ROWS you may see. GRANT decides whether you may look at the table
-- at all. You need both, and forgetting the GRANT is the single most common reason a
-- correctly-configured Supabase table still returns "permission denied".
grant usage on schema public to anon;

grant select on public.vehicles      to anon;
grant select on public.scraper_runs  to anon;
grant select on public.price_history to anon;

grant select on public.v_active_inventory    to anon;
grant select on public.v_market_gaps         to anon;
grant select on public.v_price_comparison    to anon;
grant select on public.v_inventory_by_dealer to anon;
grant select on public.v_price_drops         to anon;


-- ============================================================================
--  DONE.
--  vehicles, scraper_runs and price_history now exist, empty and waiting.
--  Claude confirms that with the Supabase MCP (list_tables).
-- ============================================================================
