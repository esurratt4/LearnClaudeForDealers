"""
The list of website platforms this scraper knows how to read.

WHAT A "PLATFORM" IS
--------------------
Dealers do not build their own websites. They rent one from a website vendor, and that
vendor decides how the inventory is published. Three vendors cover most franchise
stores in the US:

    dealeron         DealerOn
    dealer_inspire   Dealer Inspire (a Cars.com company)
    dealer_com       Dealer.com (a Cox Automotive company)

Each one needs its own reader -- its own "adapter" -- because they publish inventory in
completely different places. Those adapters are the other files in this folder.

    generic          the catch-all for everybody else

WHAT THIS FILE DOES
-------------------
It is the switchboard. Given the name of a platform, it hands back the function that
scrapes it. Nothing more.

    from scraper.platforms import get_scraper

    scrape = get_scraper("dealeron")
    vehicles = scrape(dealer, limit=25)

Every adapter in this folder promises the same two things, which is what lets the rest
of the program treat them interchangeably:

    scrape(dealer, limit=None) -> list of vehicle dictionaries

...where every vehicle dictionary has exactly the same keys no matter which vendor it
came from. That shared shape is written down in README.md and enforced by
scraper/normalize.py.

ADDING YOUR OWN
---------------
If your store (or a competitor) runs on something not listed here, you add one line to
PLATFORMS below and one new file next to this one. See scraper/platforms/generic.py --
its docstring walks through exactly that, and it is meant to be done WITH Claude Code,
not by hand.
"""

import importlib


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

# name -> the Python module that knows how to read that platform.
#
# WHY these are text, not real imports: importing a module runs its code. The
# Dealer.com adapter needs Playwright (a robot web browser), which is a big optional
# install. If we imported everything at the top of this file, then a person who has not
# run `playwright install` yet could not even run `--list` or `--detect` -- the program
# would fall over before printing anything. Storing the module *name* and importing it
# only when somebody actually asks to scrape that platform keeps the cheap commands
# working on a fresh laptop.
PLATFORMS = {
    "dealeron": "scraper.platforms.dealeron",
    "dealer_inspire": "scraper.platforms.dealer_inspire",
    "dealer_com": "scraper.platforms.dealer_com",
    "generic": "scraper.platforms.generic",
}

# One-line descriptions, for `--list` and for error messages. Kept next to the registry
# so adding a platform in one place updates the help text too.
PLATFORM_NOTES = {
    "dealeron": "DealerOn -- reads sitemap.xml, then each vehicle page",
    "dealer_inspire": "Dealer Inspire -- reads their inventory sitemap, then each vehicle page",
    "dealer_com": "Dealer.com -- talks to their inventory API through a headless browser",
    "generic": "Anything else -- sitemap + structured data. Gets you most of the way there",
}


# ---------------------------------------------------------------------------
# Looking one up
# ---------------------------------------------------------------------------


def platform_names():
    """The platform names you are allowed to use, in a sensible order for printing."""
    return sorted(PLATFORMS)


def get_scraper(name):
    """Return the scrape() function for a platform name.

    The returned function takes (dealer, limit=None) and gives back a list of vehicle
    dictionaries.

    Raises ValueError if you ask for a platform that does not exist, or if the adapter
    exists but its extra software is not installed. Both messages tell you what to do
    about it.
    """
    key = (name or "").strip().lower()

    if key not in PLATFORMS:
        raise ValueError(
            "Unknown platform %r. Valid platforms are: %s.\n"
            "Check the `platform:` line for this dealer in config/dealers.yml, or "
            "leave it blank and let `--detect` work it out." % (name, ", ".join(platform_names()))
        )

    module_path = PLATFORMS[key]

    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        # Almost always this is Playwright missing for the Dealer.com adapter. Say the
        # actual fix out loud instead of dumping a stack trace on a non-programmer.
        raise ValueError(
            "The '%s' adapter could not start because a piece of software it needs is "
            "missing: %s\n"
            "Try running these two commands, then run the scraper again:\n"
            "    pip install -r requirements.txt\n"
            "    playwright install chromium" % (key, exc)
        )

    scrape = getattr(module, "scrape", None)
    if not callable(scrape):
        # This only happens to somebody writing a new adapter, so tell them the rule.
        raise ValueError(
            "The '%s' adapter (%s) does not define a scrape() function. Every platform "
            "module must provide:  def scrape(dealer, limit=None) -> list of vehicles"
            % (key, module_path)
        )

    return scrape
