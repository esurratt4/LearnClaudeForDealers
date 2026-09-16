-- ============================================================================
--  QUESTIONS TO ASK YOUR DATA
-- ============================================================================
--
--  WHAT THIS IS
--  sql/schema.sql built the filing cabinet. This file is the list of questions worth
--  asking it. Each block below is a complete, self-contained query with a plain-English
--  title. Nothing here changes your data - every one of these only reads.
--
--  HOW TO USE IT
--    1. Supabase dashboard -> "SQL Editor" -> "+ New query".
--    2. Copy ONE block (from the -- title down to the semicolon) and paste it.
--    3. Click Run.
--  Do not paste the whole file at once. You will get all the answers stacked up and
--  only be able to see the last one.
--
--  THE ONE THING TO CHANGE
--  Several queries mention a dealer by its key - the short slug from
--  config/dealers.yml, like 'laura_chevy'. Swap in your own. Query #1 lists them all.
--
--  TIP: you do not have to write SQL to modify these. Paste a query into Claude along
--  with "change this to only show trucks under $50,000" and let it do the edit.
-- ============================================================================


-- ============================================================================
--  PART 1 - IS EVERYTHING WORKING?
--  Run these first, especially right after your first scrape.
-- ============================================================================

-- ----------------------------------------------------------------------------
--  1. Who am I tracking, and how much do I have on each of them?
--     Also the fastest way to find the dealer_key values used everywhere below.
-- ----------------------------------------------------------------------------
select *
from v_inventory_by_dealer;


-- ----------------------------------------------------------------------------
--  2. Did the last few scrapes actually work?
--     status should be 'success'. 'partial' means it ran but found nothing, which
--     almost always means the site changed and a scraper needs a small fix.
--     'error' means it crashed - error_message will tell you why.
-- ----------------------------------------------------------------------------
select
    dealer_key,
    status,
    vehicles_found,
    vehicles_added,
    vehicles_updated,
    vehicles_deactivated,
    started_at,
    finished_at,
    error_message
from scraper_runs
order by started_at desc
limit 25;


-- ----------------------------------------------------------------------------
--  3. Which dealers have gone quiet?
--     A store you have not successfully scraped in over 2 days is a store whose
--     numbers you should not be quoting in a meeting.
-- ----------------------------------------------------------------------------
select
    dealer_key,
    max(dealer_name)                                  as dealer_name,
    max(last_seen_at)                                 as last_successful_scrape,
    (current_date - max(last_seen_at)::date)          as days_since,
    count(*) filter (where is_active)                 as active_units
from vehicles
group by dealer_key
having (current_date - max(last_seen_at)::date) >= 2
order by days_since desc;


-- ============================================================================
--  PART 2 - SPY
--  What the competition has, what they are doing about it, and what it costs.
-- ============================================================================

-- ----------------------------------------------------------------------------
--  4. THE HEADLINE REPORT: who is cutting prices, and by how much.
--     Every vehicle in the market whose asking price has fallen since we first
--     saw it. A big drop on a car that has been sitting a long time tells you
--     where their floor is before you ever call them.
-- ----------------------------------------------------------------------------
select
    dealer_name,
    year, make, model, trim,
    original_price,
    current_price,
    price_drop,
    price_drop_pct,
    days_between,
    days_on_lot,
    listing_url
from v_price_drops
where is_own_store = false
order by price_drop desc
limit 50;


-- ----------------------------------------------------------------------------
--  5. Price cuts in the last 14 days only.
--     Same idea as #4 but filtered to "what changed recently" - this is the one
--     to run every Monday morning.
-- ----------------------------------------------------------------------------
select
    dealer_name,
    year, make, model, trim,
    original_price,
    current_price,
    price_drop,
    last_observed_at,
    listing_url
from v_price_drops
where is_own_store = false
  and last_observed_at >= now() - interval '14 days'
order by price_drop desc;


-- ----------------------------------------------------------------------------
--  6. Aged competitor inventory: 90+ days on the lot.
--     These are the units their GM is being asked about in every meeting. If you
--     are shopping for a trade or a wholesale buy, this is your list.
-- ----------------------------------------------------------------------------
select
    dealer_name,
    days_on_lot,
    year, make, model, trim,
    exterior_color,
    msrp,
    selling_price,
    listing_url
from v_active_inventory
where is_own_store = false
  and days_on_lot >= 90
order by days_on_lot desc;


-- ----------------------------------------------------------------------------
--  7. What did one specific competitor stock up on this month?
--     Change the dealer_key. New arrivals tell you what they are betting on.
-- ----------------------------------------------------------------------------
select
    year, make, model, trim,
    drivetrain,
    exterior_color,
    msrp,
    selling_price,
    first_seen_at::date as arrived_on,
    listing_url
from v_active_inventory
where dealer_key = 'CHANGE_ME'          -- <-- put a dealer_key from query #1 here
  and first_seen_at >= now() - interval '30 days'
order by first_seen_at desc;


-- ----------------------------------------------------------------------------
--  8. The full price story for one specific VIN.
--     Every recorded price for one car, oldest to newest. Useful when you want to
--     walk into a conversation holding the receipts.
-- ----------------------------------------------------------------------------
select
    ph.observed_at,
    ph.msrp,
    ph.selling_price,
    v.dealer_name,
    v.year, v.make, v.model, v.trim
from price_history ph
join vehicles v
       on v.vin = ph.vin
      and v.dealer_key = ph.dealer_key
where ph.vin = 'CHANGE_ME_17_CHAR_VIN'  -- <-- paste a VIN here
order by ph.observed_at asc;


-- ----------------------------------------------------------------------------
--  9. Who is the volume player in each model?
--     One row per model showing how many units each store is carrying. If one
--     competitor has 22 of something and everyone else has 3, that is their play.
-- ----------------------------------------------------------------------------
select
    make,
    model,
    dealer_name,
    count(*)                     as units,
    round(avg(selling_price), 0) as avg_price,
    round(avg(days_on_lot), 0)   as avg_days_on_lot
from v_active_inventory
group by make, model, dealer_name
having count(*) >= 3
order by make, model, units desc;


-- ============================================================================
--  PART 3 - SELL
--  What all of the above means for your own store.
-- ============================================================================

-- ----------------------------------------------------------------------------
--  10. WHERE THE HOLES ARE: what the market stocks that you do not.
--      Every row is a potential order. competitor_dealers matters as much as
--      competitor_units - four stores each carrying five is a real segment,
--      one store carrying twenty is one buyer's opinion.
-- ----------------------------------------------------------------------------
select *
from v_market_gaps
order by competitor_dealers desc, competitor_units desc
limit 40;


-- ----------------------------------------------------------------------------
--  11. HEAD TO HEAD: where am I priced above the market?
--      Positive price_gap means you are asking more than the average competitor
--      for the same model and trim. Sometimes that is correct and deliberate.
--      Sometimes it is why the phone is not ringing.
-- ----------------------------------------------------------------------------
select
    make, model, trim,
    own_units,
    competitor_units,
    competitor_dealers,
    own_avg_price,
    competitor_avg_price,
    price_gap
from v_price_comparison
where price_gap > 0
order by price_gap desc;


-- ----------------------------------------------------------------------------
--  12. And where am I leaving money on the table?
--      Negative price_gap: you are cheaper than the market on these. If they are
--      also moving quickly, you may be underpricing.
-- ----------------------------------------------------------------------------
select
    make, model, trim,
    own_units,
    competitor_units,
    own_avg_price,
    competitor_avg_price,
    price_gap
from v_price_comparison
where price_gap < 0
order by price_gap asc;


-- ----------------------------------------------------------------------------
--  13. My own aged units, worst first.
--      Change the dealer_key to your store (or rely on is_own_store, which is set
--      from config/dealers.yml).
-- ----------------------------------------------------------------------------
select
    days_on_lot,
    year, make, model, trim,
    exterior_color,
    msrp,
    selling_price,
    stock_number,
    listing_url
from v_active_inventory
where is_own_store = true
order by days_on_lot desc
limit 50;


-- ----------------------------------------------------------------------------
--  14. My mix vs. everyone else's mix, by body type.
--      Are you 60% SUVs in a market that is buying trucks? This answers that in
--      one screen. own_share and market_share are percentages of each side's total.
-- ----------------------------------------------------------------------------
with totals as (
    select
        count(*) filter (where is_own_store)     as own_total,
        count(*) filter (where not is_own_store) as market_total
    from v_active_inventory
)
select
    coalesce(body_type, 'Unknown') as body_type,
    count(*) filter (where is_own_store)     as own_units,
    count(*) filter (where not is_own_store) as market_units,
    round(100.0 * count(*) filter (where is_own_store)
          / nullif((select own_total from totals), 0), 1)    as own_share_pct,
    round(100.0 * count(*) filter (where not is_own_store)
          / nullif((select market_total from totals), 0), 1) as market_share_pct
from v_active_inventory
group by coalesce(body_type, 'Unknown')
order by market_units desc;


-- ----------------------------------------------------------------------------
--  15. How fast does the market actually turn?
--      Vehicles that DISAPPEARED from a competitor's site are, overwhelmingly,
--      vehicles that sold. This measures how many days they lasted. A model with a
--      low avg_days_to_sell and high volume is the thing you want on your lot.
--
--      Caveat worth knowing: a car can also vanish because it got moved to another
--      rooftop or pulled for service. Treat this as a strong signal, not gospel.
-- ----------------------------------------------------------------------------
select
    make,
    model,
    count(*)                                              as units_sold,
    round(avg(removed_at::date - first_seen_at::date), 1) as avg_days_to_sell,
    round(avg(selling_price), 0)                          as avg_price
from vehicles
where is_active = false
  and removed_at is not null
  and is_own_store = false
group by make, model
having count(*) >= 3
order by units_sold desc;


-- ----------------------------------------------------------------------------
--  16. Color check.
--      Which exterior colors actually move in your market, versus which ones sit.
--      Worth a look before the next order guide.
-- ----------------------------------------------------------------------------
select
    coalesce(exterior_color, 'UNKNOWN') as exterior_color,
    count(*)                            as active_units,
    round(avg(days_on_lot), 1)          as avg_days_on_lot
from v_active_inventory
where is_own_store = false
group by coalesce(exterior_color, 'UNKNOWN')
having count(*) >= 5
order by avg_days_on_lot desc;


-- ============================================================================
--  WANT SOMETHING THAT IS NOT HERE?
--  Paste this into Claude, along with sql/schema.sql, and ask in plain English:
--
--    "Using this schema, write me a query that shows every competitor crew-cab
--     4WD truck under $60,000 that has been on the lot more than 45 days,
--     sorted by biggest price drop."
--
--  Then paste what it gives you into the SQL Editor. Everything in this file is
--  read-only, and so is anything you build from it - the worst case is an error
--  message, not lost data.
-- ============================================================================
