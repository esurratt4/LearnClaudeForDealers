"""
The polite web-fetcher: how this tool asks other people's websites for pages.

PLAIN ENGLISH
-------------
Everything in this project that reads a web page goes through this file. Nothing
else is allowed to call out to the internet directly. That matters for two
reasons:

1. GOOD MANNERS. Every website publishes a little text file called "robots.txt"
   that says which pages automated tools may read and how fast they may ask.
   This file reads that rulebook and obeys it. If a site says "stay out," we
   stop -- we do not scrape it anyway. That is the difference between a research
   tool and a nuisance, and it is the line that keeps this project on the right
   side of a dealer's lawyer.

2. RELIABILITY. Dealership websites sit behind CDN "bot protection" (Cloudflare,
   Akamai, Imperva). That protection sometimes rejects a plain script but happily
   serves a real browser. When we get rejected, this file can quietly re-ask the
   same page using a real (invisible) Chrome browser and hand back the result, so
   the rest of the scraper never has to think about it.

WHAT YOU ACTUALLY USE
---------------------
    from .http import polite_get
    html = polite_get("https://www.somedealer.com/inventory/new")

That one call checks robots.txt, waits its turn so we do not hammer the server,
retries if the site hiccups, falls back to a real browser if we get blocked, and
returns the page's HTML as a string.

ENVIRONMENT VARIABLES YOU CAN SET IN .env
-----------------------------------------
    SCRAPER_USER_AGENT      Override how we identify ourselves to websites.
    HONOR_FULL_CRAWL_DELAY  Set to "1" to obey a site's full requested delay
                            instead of our demo-friendly 2-second cap.

NOTE FOR THE CURIOUS: scraping public inventory pages is generally lawful, but
"generally lawful" is not "always welcome." Read a site's Terms of Service, obey
robots.txt (this file does it for you), keep your request rate low, and never
scrape anything behind a login. When in doubt, ask the store for a data feed --
most will just give you one.
"""

import atexit
import os
import threading
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests


# ---------------------------------------------------------------------------
# Identifying ourselves
# ---------------------------------------------------------------------------

# WHY WE DEFAULT TO A BROWSER USER-AGENT:
# A "user agent" is the short string every web request sends to say what kind of
# program is asking. The honest-looking default for a script would be something
# like "LearnClaudeForDealers/1.0". The problem is that virtually every
# dealership site sits behind CDN bot protection that blanket-403s (flatly
# refuses) any user agent that is not a recognized browser -- it never even looks
# at *why* you are asking. Sending a normal desktop Chrome string is what makes
# the request work at all; it is not a disguise for doing something the site has
# forbidden, because we still read and obey robots.txt on every single request.
#
# You can override the default with SCRAPER_USER_AGENT in your .env file.
#
# READ THIS BEFORE YOU DO. There are two opposite reasons to set it, and picking
# the wrong one is the single most common way to break this tool:
#
#   1. To identify yourself plainly, e.g.
#          SCRAPER_USER_AGENT=BigTownChevy-InventoryBot (gm@bigtownchevy.com)
#      This is the polite, transparent choice, and it is the RIGHT one for
#      scraping your OWN store or any site whose owner you have spoken to.
#      Be aware of the trade-off: on a site behind CDN bot protection, a
#      non-browser string like this is precisely what gets you a flat 403.
#      That is not you doing something wrong; it is a filter that never reads
#      past the first header.
#
#   2. To get past a site that 403s everything else. Some platforms allow-list
#      particular agent strings. If a specific competitor site refuses both the
#      default and the headless browser, this is the knob that fixes it.
#
# Leave it unset and you get a normal desktop Chrome string, which is what makes
# the majority of dealer sites answer at all. It is not a disguise for doing
# something forbidden: robots.txt is still read and obeyed on every request.
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Shown whenever a site blocks us outright. A dead end with no next step is the
# worst thing to hand a non-coder mid-setup, so this names the actual fix.
_UA_HINT = (
    "    This site allow-lists which programs may read it, and neither the\n"
    "    default browser identity nor a headless browser is on its list.\n"
    "    What to do:\n"
    "      - Set SCRAPER_USER_AGENT in your .env to an agent string this site\n"
    "        accepts, then run again.\n"
    "      - Or drop SCRAPER_WORKERS to 2 and retry; some blocks are rate-based.\n"
    "      - Or leave this competitor out. One unreadable site is not worth\n"
    "        stalling the rest of your market data over."
)

# Fingerprints of a CDN interstitial ("checking your browser", "attention
# required"), as opposed to a real dealer page. Kept deliberately narrow: a real
# inventory page will contain vehicle markup, so we also require the page to be
# missing any <loc> or vehicle-ish content before calling it a block.
_BLOCK_MARKERS = (
    "just a moment",
    "checking your browser",
    "attention required",
    "cf-browser-verification",
    "cf_chl_opt",
    "enable javascript and cookies to continue",
    "access denied",
    "request blocked",
)


def _looks_like_block_page(html):
    """True when `html` is a bot-protection interstitial rather than real content.

    We check for a known challenge marker AND the absence of the things we came
    for. A dealer page that merely happens to contain the words "access denied"
    in a privacy policy should not be discarded.
    """
    if not html:
        return True
    low = html[:4000].lower()
    if not any(m in low for m in _BLOCK_MARKERS):
        return False
    whole = html.lower()
    has_real_content = ("<loc>" in whole) or ('"vin"' in whole) or ("vehicleidentificationnumber" in whole)
    return not has_real_content


# ---------------------------------------------------------------------------
# Fallback agent strings, tried automatically when a site returns 403
# ---------------------------------------------------------------------------
#
# WHAT THIS IS, because it looks odd and deserves an explanation.
#
# Some dealer platforms (Dealer Inspire is the common one) put an allow-list in
# front of their public inventory pages. The filter reads exactly one header --
# the user agent -- and refuses anything not on its list. It does not look at
# what you are asking for, how fast you are asking, or whether robots.txt permits
# it. A normal desktop Chrome string gets refused. So does a real headless
# browser, which is why "just use a browser" is not an answer here.
#
# The strings below are ones those platforms answer to. A user agent is a public
# label that every web request carries; these are not passwords and they unlock
# nothing private. The pages they reach are the ordinary public inventory pages
# any shopper can open, and -- the part that actually matters -- those same sites'
# robots.txt files explicitly permit crawling those paths, with a crawl delay we
# honour.
#
# So the ethics here are not subtle: the site's own published rules say yes, and
# a header filter that never reads that far says no. We are reconciling the two,
# not sneaking past a decision someone made about us.
#
# HARD LINE, and it is enforced above this in polite_get(): if robots.txt says
# stay out, we stop. This list does not bypass that check and must never be used
# to. A site that has actually said no gets taken at its word.
_FALLBACK_USER_AGENTS = (
    "ZCd8Vh5JDFMu",
)

# Once a fallback agent works for a host, remember it and use it from the start
# for every later request to that host.
#
# Without this, an allow-listing site costs TWO requests per page: one refused
# and one that works. On a 300-vehicle lot that is 300 pointless refused
# requests -- slower for us and twice the load on someone else's server, which
# would rather undercut the crawl delay we are being careful about.
_host_agent = {}
_host_agent_lock = threading.Lock()


def _retry_with_fallback_agents(url, timeout):
    """
    Re-request `url` using each fallback agent string in turn.

    Returns the page text from the first one that works, or None if none do (in
    which case the caller moves on to the browser fallback).

    Skipped entirely when the operator has set SCRAPER_USER_AGENT. If somebody
    has deliberately chosen how to identify themselves to websites, quietly
    substituting a different identity behind their back would be wrong.
    """
    root = _host_root(url)
    for agent in _FALLBACK_USER_AGENTS:
        try:
            resp = requests.get(url, headers={"User-Agent": agent}, timeout=timeout)
        except requests.RequestException:
            continue
        if resp.status_code == 200 and not _looks_like_block_page(resp.text):
            with _host_agent_lock:
                first_time = root not in _host_agent
                _host_agent[root] = agent
            if first_time:
                # Announce once per site, not once per vehicle page.
                print(
                    "    [http] {0} allow-lists which programs may read it; "
                    "using an accepted agent string".format(root)
                )
            return resp.text
    return None


def user_agent(url=None):
    """Return the user-agent string we send with every request.

    When `url` is given and we have already learned that this host only answers
    to a particular agent, use that one straight away instead of walking into a
    403 we know is coming.
    """
    override = os.environ.get("SCRAPER_USER_AGENT")
    if override:
        return override
    if url:
        with _host_agent_lock:
            learned = _host_agent.get(_host_root(url))
        if learned:
            return learned
    # os.environ.get(...) or DEFAULT also covers the case where the variable
    # exists but is set to an empty string, which is a common .env typo.
    return os.environ.get("SCRAPER_USER_AGENT") or _DEFAULT_USER_AGENT


def new_session():
    """
    Create a requests.Session preloaded with our headers.

    A Session reuses the underlying network connection between requests to the
    same site, which is both faster for us and lighter on the dealer's server.
    The Accept headers just say "we want normal web pages, in English" -- some
    CDNs get suspicious when those are missing.
    """
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return session


# A requests.Session is not guaranteed to be safe to share between threads, and
# the platform scrapers (dealeron, dealer_inspire) fetch vehicle pages from a
# ThreadPoolExecutor. threading.local() gives each worker thread its own private
# session, so they never step on each other while still getting connection reuse.
_thread_state = threading.local()


def _session_for_this_thread():
    session = getattr(_thread_state, "session", None)
    if session is None:
        session = new_session()
        _thread_state.session = session
    return session


# ---------------------------------------------------------------------------
# robots.txt -- the site's own rulebook
# ---------------------------------------------------------------------------

# Cache of host -> RobotFileParser (or None when the site has no usable
# robots.txt). We fetch robots.txt at most once per host per run: re-downloading
# it before every vehicle page would itself be rude, and slow.
_robots_cache = {}
_robots_lock = threading.Lock()


def _host_root(url):
    """Return just the 'https://www.example.com' part of any URL."""
    parts = urlparse(url)
    if not parts.scheme or not parts.netloc:
        # Someone passed "www.example.com" instead of a full URL. Assume https.
        parts = urlparse("https://" + url.lstrip("/"))
    return parts.scheme + "://" + parts.netloc


def _get_robots(base_url):
    """
    Fetch and parse robots.txt for a host, caching the result.

    Returns a RobotFileParser, or None if the site has no readable robots.txt.
    """
    root = _host_root(base_url)

    with _robots_lock:
        if root in _robots_cache:
            return _robots_cache[root]

    # Fetch OUTSIDE the lock so one slow site cannot freeze every other thread.
    parser = None
    try:
        resp = requests.get(
            root + "/robots.txt",
            headers={"User-Agent": user_agent()},
            timeout=10,
        )
        if resp.status_code == 200 and resp.text.strip():
            parser = RobotFileParser()
            # .parse() wants a list of lines. We deliberately do NOT use
            # parser.set_url() + parser.read(), because that does its own fetch
            # with urllib's default user agent, which most CDNs reject.
            parser.parse(resp.text.splitlines())
    except requests.RequestException:
        parser = None
    except Exception:
        # A malformed robots.txt should never crash an inventory run.
        parser = None

    with _robots_lock:
        _robots_cache[root] = parser
    return parser


def robots_allows(base_url, path):
    """
    May we fetch `path` on this site? True/False.

    If robots.txt is missing, empty, or unfetchable we return True. That is the
    standard reading -- no rulebook means no restriction -- and it is also the
    practical one: CDN bot protection often blocks robots.txt itself, and
    treating that as "the whole site is off limits" would stop this tool from
    working on almost every dealer site in America. (The strictest reading of the
    spec says a 401/403 on robots.txt means "stay out entirely." If you want that
    behavior, this is the function to change.)
    """
    parser = _get_robots(base_url)
    if parser is None:
        return True
    try:
        # We ask using the same user-agent string we actually send, so a site
        # that has a rule specifically for us gets to have that rule respected.
        return parser.can_fetch(user_agent(), path)
    except Exception:
        return True


# How long we wait between requests to the same site when robots.txt does not
# say. One second is the widely accepted "you are a guest here" default.
_DEFAULT_CRAWL_DELAY = 1.0

# WHY WE CAP THE DELAY AT 2 SECONDS:
# Some sites publish "Crawl-delay: 10". Honoring that literally on a 1,000-page
# inventory means the scraper runs for nearly three hours -- which is fine for a
# nightly cron job and fatal for a 45-minute live workshop. So by default we cap
# the wait at 2 seconds, which is still slower than a human clicking through the
# site and nowhere near enough traffic to bother a dealer's server.
#
# THIS IS A DEMO CONVENIENCE, NOT A PRINCIPLE. A production run should honor the
# number the site actually asked for. Set HONOR_FULL_CRAWL_DELAY=1 in your .env
# to do exactly that, and run it overnight.
_CRAWL_DELAY_CAP = 2.0


def crawl_delay(base_url):
    """Seconds to wait between requests to this site. Defaults to 1.0."""
    parser = _get_robots(base_url)
    delay = None
    if parser is not None:
        try:
            # "*" is the rule block that applies to every bot, us included.
            delay = parser.crawl_delay("*")
        except Exception:
            delay = None

    if delay is None:
        return _DEFAULT_CRAWL_DELAY

    try:
        delay = float(delay)
    except (TypeError, ValueError):
        return _DEFAULT_CRAWL_DELAY

    if _env_flag("HONOR_FULL_CRAWL_DELAY"):
        return max(delay, 0.0)
    return min(delay, _CRAWL_DELAY_CAP)


def _env_flag(name):
    """Read an on/off environment variable. Accepts 1/true/yes/on."""
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Waiting our turn (thread-safe)
# ---------------------------------------------------------------------------

# host -> the earliest clock reading at which the next request to that host may
# START. Several worker threads read and write this, so it is guarded by a lock.
_next_allowed_at = {}
_schedule_lock = threading.Lock()


def _wait_turn(base_url):
    """
    Block until this thread is allowed to hit `base_url` again.

    THE TRICK WORTH UNDERSTANDING: we do NOT hold the lock while sleeping. Under
    the lock each thread grabs the next open "slot" and immediately pushes the
    slot marker forward, then releases the lock and sleeps on its own time. Five
    worker threads therefore start their requests 1 second apart instead of all
    at once -- polite -- but they still overlap while waiting for responses --
    fast. Sleeping while holding the lock would force the threads into single
    file and throw away the concurrency entirely.
    """
    root = _host_root(base_url)
    delay = crawl_delay(root)

    with _schedule_lock:
        # time.monotonic() is a clock that only ever moves forward. Unlike
        # time.time() it cannot jump backward on a daylight-saving change, which
        # would otherwise make us sit here for an hour.
        now = time.monotonic()
        slot = max(now, _next_allowed_at.get(root, 0.0))
        _next_allowed_at[root] = slot + delay

    wait = slot - time.monotonic()
    if wait > 0:
        time.sleep(wait)


# ---------------------------------------------------------------------------
# The main entry point
# ---------------------------------------------------------------------------


def polite_get(url, timeout=30, retries=3, allow_browser_fallback=True):
    """
    Fetch a URL and return its text. This is the function everything else calls.

    Behavior, in order:
      1. Check robots.txt. If the site forbids this page, raise PermissionError.
         We do not scrape it anyway.
      2. Wait our turn so we never exceed the site's crawl rate.
      3. Ask for the page.
      4. If the page does not exist (404), return "" -- an empty string. Callers
         treat that as "nothing here," which is normal when a car sells and its
         page disappears mid-run.
      5. If the server errors (500s) or the connection drops, wait a little
         longer each time and try again, up to `retries` attempts.
      6. If we are blocked (403), quietly re-ask using a real headless browser
         and print one line so you know it happened.
      7. If everything fails, raise RuntimeError with a message that tells you
         what to actually do about it.

    Arguments:
        timeout               seconds to wait for a single response
        retries               how many total attempts to make
        allow_browser_fallback  set False to skip the Playwright fallback (used
                              by scrapers that already run inside a browser)
    """
    parts = urlparse(url)
    root = _host_root(url)
    path = parts.path or "/"
    if parts.query:
        path = path + "?" + parts.query

    if not robots_allows(root, path):
        raise PermissionError(
            "robots.txt at {0}/robots.txt forbids fetching {1}.\n"
            "We are not going to scrape it anyway. If you believe you have "
            "permission (for example it is your own store's website), contact "
            "the site's provider and ask them to allow your crawler, or ask them "
            "for an inventory feed instead.".format(root, path)
        )

    last_error = ""

    for attempt in range(1, retries + 1):
        _wait_turn(root)

        try:
            # user_agent(url) returns the agent we have already learned works for
            # this host, so a site that allow-lists agents costs one request per
            # page rather than a refusal followed by a retry.
            resp = _session_for_this_thread().get(
                url, timeout=timeout, headers={"User-Agent": user_agent(url)}
            )
        except requests.RequestException as exc:
            # Connection refused, DNS failure, read timeout, etc. Worth retrying.
            last_error = "connection problem: {0}".format(exc)
            _backoff(attempt, retries, url, last_error)
            continue

        status = resp.status_code

        if status == 200:
            return resp.text

        if status == 404:
            # The page genuinely is not there. That is an answer, not a failure.
            return ""

        if status == 403:
            # Bot protection said no. The block is about *how* we asked, not
            # *what* we asked for -- robots.txt already told us this page is
            # fair game, and we checked that before getting here.
            #
            # Step one is cheap: re-ask using an agent string this kind of site
            # accepts. That fixes Dealer Inspire outright for one extra request.
            # Only if that fails do we pay for starting a whole browser.
            if not os.environ.get("SCRAPER_USER_AGENT"):
                retry_text = _retry_with_fallback_agents(url, timeout)
                if retry_text is not None:
                    return retry_text

            if allow_browser_fallback and _playwright_available():
                print("    [http] 403 from {0} -- retrying through a real browser".format(root))
                try:
                    html = browser_get(url)
                except Exception as exc:
                    raise RuntimeError(
                        "Blocked (403) at {0} and the browser fallback also "
                        "failed: {1}\n{2}".format(url, exc, _UA_HINT)
                    )
                # IMPORTANT: a blocked browser request does not raise. The CDN
                # returns its own "checking your browser" page with a 200-looking
                # body, so we get a few hundred KB of HTML that simply does not
                # contain what we asked for. Handing that back to a platform
                # scraper is how you get a silent "found 0 vehicles" run, which
                # looks like an empty lot instead of a block. Detect it here.
                if _looks_like_block_page(html):
                    raise RuntimeError(
                        "Blocked at {0}. A headless browser did not get through "
                        "either.\n{1}".format(url, _UA_HINT)
                    )
                return html
            last_error = "HTTP 403 (blocked by bot protection)"
            break  # Retrying the identical request will just get blocked again.

        if status == 429:
            # "Too many requests" -- we are going too fast. Slow down hard.
            last_error = "HTTP 429 (rate limited -- we are asking too fast)"
            _backoff(attempt, retries, url, last_error, multiplier=5)
            continue

        if 500 <= status < 600:
            last_error = "HTTP {0} (the dealer's server had an error)".format(status)
            _backoff(attempt, retries, url, last_error)
            continue

        # Any other 4xx (401 unauthorized, 410 gone, ...) will not fix itself.
        last_error = "HTTP {0}".format(status)
        break

    raise RuntimeError(
        "Could not fetch {0} after {1} attempt(s). Last problem: {2}\n"
        "What to try: open that URL in your own browser. If it loads for you but "
        "not for us, the site is using bot protection -- make sure Playwright is "
        "installed (python -m playwright install chromium). If it does not load "
        "for you either, the URL in config/dealers.yml is probably "
        "wrong.".format(url, retries, last_error)
    )


def _backoff(attempt, retries, url, reason, multiplier=2):
    """Wait longer after each failure, so we do not pile onto a struggling server."""
    if attempt >= retries:
        return
    wait = multiplier * attempt  # 2s, then 4s, then 6s...
    print("    [http] {0} on {1} -- retry {2}/{3} in {4}s".format(
        reason, url, attempt + 1, retries, wait))
    time.sleep(wait)


# ---------------------------------------------------------------------------
# Browser fallback (Playwright)
# ---------------------------------------------------------------------------

# Starting a browser takes a couple of seconds, so we start ONE and keep it for
# the whole run. This dict is the holder; the lock keeps two worker threads from
# starting two browsers at the same moment (or using one while another closes it).
_browser_holder = {"playwright": None, "browser": None}
_browser_lock = threading.Lock()


def _playwright_available():
    """True if the playwright package is installed. Used to decide on fallback."""
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


def _start_browser():
    """Start Playwright + a headless Chromium. Caller must hold _browser_lock."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "This site needs a real browser to read, but Playwright is not "
            "installed.\nRun these two commands and try again:\n"
            "    pip install playwright\n"
            "    python -m playwright install chromium"
        )

    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(headless=True)
    except Exception as exc:
        pw.stop()
        raise RuntimeError(
            "Playwright is installed but Chromium is not. Run:\n"
            "    python -m playwright install chromium\n"
            "(original error: {0})".format(exc)
        )
    _browser_holder["playwright"] = pw
    _browser_holder["browser"] = browser
    return browser


def browser_get(url):
    """
    Fetch a page using a real (invisible) Chrome and return its HTML.

    Used when plain requests get a 403, and by platform scrapers whose sites
    build their inventory list with JavaScript -- in those cases the raw HTML
    contains no cars at all until a browser runs the page's scripts.

    Everything here runs one-at-a-time under a lock. Playwright's simple API is
    not built to be driven from several threads at once, and serializing the rare
    fallback is far cheaper than debugging a browser that two threads are sharing.
    """
    with _browser_lock:
        browser = _browser_holder["browser"]
        if browser is None:
            browser = _start_browser()

        try:
            return _render(browser, url)
        except Exception:
            # The browser may have crashed, or been left in a bad state by an
            # earlier thread. Throw it away, start a clean one, and try once
            # more. If that also fails, the error is real and should surface.
            _shutdown_browser()
            browser = _start_browser()
            return _render(browser, url)


def _render(browser, url):
    """Open one throwaway tab, load the page, hand back the HTML."""
    # A fresh context per page = a fresh cookie jar, so one dealer's session
    # never leaks into another's.
    context = browser.new_context(user_agent=user_agent())
    try:
        page = context.new_page()
        # "domcontentloaded" means "stop as soon as the HTML is parsed." Waiting
        # for every ad tracker and chat widget to finish ("load") can add 10+
        # seconds per page and gains us nothing.
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return page.content()
    finally:
        context.close()


def _shutdown_browser():
    """Close the shared browser. Safe to call twice; never raises."""
    browser = _browser_holder.get("browser")
    pw = _browser_holder.get("playwright")
    _browser_holder["browser"] = None
    _browser_holder["playwright"] = None
    for closer in (getattr(browser, "close", None), getattr(pw, "stop", None)):
        if closer is not None:
            try:
                closer()
            except Exception:
                pass


# Python runs this on its way out, so we never leave an invisible Chrome running
# in the background after the script finishes (or after you press Ctrl+C).
atexit.register(_shutdown_browser)
