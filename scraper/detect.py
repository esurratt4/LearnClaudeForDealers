"""
Figure out which website company built a dealership's site.

WHY THIS FILE EXISTS
--------------------
Almost every franchise dealer website in the country is built by one of a handful of
website vendors. The big three are DealerOn, Dealer Inspire, and Dealer.com. Each one
publishes its inventory in a different place and a different format, so this scraper
needs a different "adapter" for each of them (see scraper/platforms/).

The annoying part is that nothing on a dealer's homepage says "Built by Dealer Inspire"
in plain English. You have to look at the plumbing. This module does that looking for
you: hand it any dealership web address and it tells you which vendor built the site,
and -- just as importantly -- it tells you WHY it thinks so, so you can sanity-check it
instead of trusting a black box.

HOW TO USE IT
-------------
    from scraper.detect import detect, detect_platform

    detect_platform("https://www.examplemotors.com")
    # -> "dealer_inspire"

    detect("https://www.examplemotors.com")
    # -> {
    #      "platform": "dealer_inspire",
    #      "site_id": None,
    #      "evidence": ["homepage mentions 'dealerinspire' (Dealer Inspire's own name)",
    #                   "found /dealer-inspire-inventory/inventory_sitemap with 412 listings"],
    #    }

HOW HARD IT LOOKS
-----------------
Two or three web requests, total. It reads the homepage, and only if that is unclear
does it go knock on a couple of known doors (the vendor-specific sitemaps). It is
deliberately NOT a crawler -- this runs live in front of an audience and needs to
answer in a few seconds.

WHEN IT IS NOT SURE
-------------------
It answers "generic" and says so in the evidence. "generic" is a real, working
fallback adapter (scraper/platforms/generic.py), not an error message. A dead or
unreachable site also comes back as "generic" with the reason attached -- this
function never raises an exception, because a typo in a URL should not crash a demo.
"""

import re

try:
    # Python 3
    from urllib.parse import urlparse
except ImportError:  # pragma: no cover - Python 2 is not supported, this is a guard
    raise

from .http import polite_get


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

# Keep detection snappy. If a site is so slow that it cannot answer in 20 seconds we
# would rather fall back to "generic" than stall a live workshop.
HOMEPAGE_TIMEOUT = 20
PROBE_TIMEOUT = 15

# The homepage gets retries (and a real browser fallback) because some dealer sites sit
# behind bot protection that blocks the first plain request. The extra probes do not --
# a 404 on a vendor-specific sitemap is an *answer*, not a failure, so retrying wastes
# time we do not have on stage.
HOMEPAGE_RETRIES = 2
PROBE_RETRIES = 1

# A score of this much or more from homepage clues alone is treated as a confident
# answer, and we skip the extra requests. Scores are assigned in _MARKERS below:
# roughly, 3 = "the vendor's own name is in the page source" and 1 = "suggestive but
# lots of sites do this".
CONFIDENT_SCORE = 3


# ---------------------------------------------------------------------------
# What we look for
# ---------------------------------------------------------------------------

# Every entry is (platform, needle, points, plain-English reason).
#
# WHY a scoring table instead of a chain of if-statements: several of these clues are
# weak on their own. "wp-content" only tells you the site runs WordPress, and plenty of
# non-Dealer-Inspire sites do. Adding points lets a pile of weak clues lose to a single
# strong one, and it lets us print every clue we found rather than only the first.
#
# All needles are lowercase; we lowercase the page source once before searching.
_MARKERS = (
    # --- Dealer.com ------------------------------------------------------------
    # Dealer.com (a Cox Automotive brand) renders inventory in the browser and stashes
    # its configuration in a global JavaScript object called DDC.dataLayer.
    ("dealer_com", "ddc.datalayer", 3, "homepage source contains 'DDC.dataLayer' (Dealer.com's configuration object)"),
    ("dealer_com", "ws-inv-data", 3, "homepage references the 'ws-inv-data' inventory widget (Dealer.com's inventory API)"),
    ("dealer_com", "pictures.dealer.com", 3, "vehicle photos are served from pictures.dealer.com"),
    ("dealer_com", "static.dealer.com", 2, "page assets load from static.dealer.com"),
    ("dealer_com", "dealer.com", 1, "the string 'dealer.com' appears somewhere in the page"),

    # --- Dealer Inspire --------------------------------------------------------
    # Dealer Inspire sites are WordPress underneath, with the vendor's name baked into
    # theme paths and their CDN hostname.
    ("dealer_inspire", "dealerinspire", 3, "homepage mentions 'dealerinspire' (Dealer Inspire's own name)"),
    ("dealer_inspire", "dealer-inspire", 3, "homepage mentions 'dealer-inspire' (Dealer Inspire's own name)"),
    ("dealer_inspire", "di-cdn", 3, "page assets load from a 'di-cdn' host (Dealer Inspire's CDN)"),
    ("dealer_inspire", "wp-content", 1, "page loads files from /wp-content/ (it is a WordPress site, which DI sites are)"),

    # --- DealerOn --------------------------------------------------------------
    # DealerOn is a .NET shop, so its vehicle pages historically end in .aspx.
    ("dealeron", "dealeron", 3, "homepage mentions 'dealeron' (DealerOn's own name)"),
    ("dealeron", ".aspx", 1, "page links end in '.aspx' (DealerOn builds on ASP.NET)"),
    ("dealeron", "inventoryphotos/", 2, "vehicle photos use DealerOn's /inventoryphotos/ path"),
)

# A 17-character VIN. VINs never contain the letters I, O, or Q -- they were dropped so
# nobody confuses them with 1 and 0 -- so A-HJ-NPR-Z is the real alphabet.
_VIN_RE = re.compile(r"(?<![A-Za-z0-9])([A-HJ-NPR-Z0-9]{17})(?![A-Za-z0-9])")

# Dealer.com puts its account id in the page as  "siteId":"somedealername".
# We want it because the Dealer.com adapter cannot ask the inventory API for anything
# without it, and making the computer find it beats making a dealer go hunting.
_SITE_ID_RES = (
    re.compile(r'"siteId"\s*:\s*"([^"]+)"'),
    re.compile(r"siteId\s*[:=]\s*[\"']([A-Za-z0-9_.-]+)[\"']"),
    re.compile(r'data-site-id\s*=\s*"([^"]+)"'),
)

# Paths we knock on when the homepage was not conclusive.
DI_SITEMAP_PATH = "/dealer-inspire-inventory/inventory_sitemap"
DEALERON_SITEMAP_PATH = "/sitemap.xml"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def base_url(url):
    """Reduce any URL a dealer might paste to just 'https://www.theirsite.com'.

    People paste all sorts of things: a deep link to one truck, a URL with no https://
    on the front, a trailing slash. Everything downstream wants the bare site root, so
    we do the cleanup once, here.
    """
    cleaned = (url or "").strip()
    if not cleaned:
        return ""
    if "://" not in cleaned:
        # Assume https. Every dealer site worth scraping has had TLS for a decade.
        cleaned = "https://" + cleaned
    parts = urlparse(cleaned)
    host = parts.netloc.strip()
    # A real hostname has a dot in it and no spaces. Catching a typo here means the CLI
    # can say "that is not a web address" instead of timing out for 20 seconds first.
    if not host or "." not in host or " " in host:
        return ""
    return "%s://%s" % (parts.scheme or "https", host)


def _safe_get(url, timeout, retries, allow_browser_fallback):
    """Fetch a URL and return (text, error_message).

    polite_get already handles retries and returns "" for a 404. This wrapper adds the
    one thing detection needs on top: it refuses to raise. A detector that explodes on
    a misspelled domain is useless in front of a room of people.
    """
    try:
        text = polite_get(
            url,
            timeout=timeout,
            retries=retries,
            allow_browser_fallback=allow_browser_fallback,
        )
        return text or "", None
    except Exception as exc:  # noqa: BLE001 - any failure here means "no answer"
        return "", str(exc)


def _extract_site_id(html):
    """Pull Dealer.com's siteId out of the page source, or None if it is not there."""
    for pattern in _SITE_ID_RES:
        match = pattern.search(html)
        if match:
            value = match.group(1).strip()
            # Guard against matching a template placeholder like "siteId":"{siteId}".
            if value and "{" not in value and len(value) < 100:
                return value
    return None


def _score_homepage(html):
    """Count up the clues in the homepage source.

    Returns (scores, evidence) where scores is {platform: points} and evidence is a
    list of printable sentences describing every clue that matched.
    """
    lowered = html.lower()
    scores = {}
    evidence = []
    for platform, needle, points, why in _MARKERS:
        if needle in lowered:
            scores[platform] = scores.get(platform, 0) + points
            evidence.append(why)
    return scores, evidence


def _best(scores):
    """Return (platform, points) for the top scorer, or (None, 0) if it is a tie/empty.

    WHY a tie counts as "no answer": a site scoring 3 for two different vendors is
    telling us something is off (a Dealer.com site embedding a Dealer Inspire chat
    widget, say). Better to spend one more request confirming than to guess.
    """
    if not scores:
        return None, 0
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None, ranked[0][1]
    return ranked[0][0], ranked[0][1]


# ---------------------------------------------------------------------------
# The extra "knock on the door" probes
# ---------------------------------------------------------------------------


def _probe_dealer_inspire(base):
    """Ask for Dealer Inspire's inventory sitemap. Returns (matched, evidence_line).

    Every Dealer Inspire store publishes its inventory at this exact path. Nobody else
    does, so a page here with listings in it is about as close to proof as we get.
    """
    text, error = _safe_get(
        base + DI_SITEMAP_PATH,
        timeout=PROBE_TIMEOUT,
        retries=PROBE_RETRIES,
        allow_browser_fallback=False,
    )
    if error or not text:
        return False, None
    locations = re.findall(r"<loc>", text)
    if locations:
        return True, "found %s%s listing %d URLs (only Dealer Inspire publishes this)" % (
            base,
            DI_SITEMAP_PATH,
            len(locations),
        )
    return False, None


def _probe_dealeron(base):
    """Look for DealerOn's signature sitemap entries. Returns (matched, evidence_line).

    DealerOn builds vehicle page addresses that end with the VIN, like
    /new-2025-gmc-sierra-1500-elevation-3gtuuced8rg123456/ -- so a sitemap.xml full of
    URLs whose last chunk is a 17-character VIN is a strong DealerOn tell.
    """
    text, error = _safe_get(
        base + DEALERON_SITEMAP_PATH,
        timeout=PROBE_TIMEOUT,
        retries=PROBE_RETRIES,
        allow_browser_fallback=False,
    )
    if error or not text:
        return False, None

    hits = 0
    for raw in re.findall(r"<loc>(.*?)</loc>", text, re.DOTALL):
        url = raw.strip().rstrip("/")
        if "/new-" not in url and "/used-" not in url:
            continue
        # The VIN is the last dash-separated chunk of the address. Upper-case it first:
        # some sites publish their sitemap in lower case, and a VIN is always capitals.
        tail = url.split("/")[-1].split("-")[-1].upper()
        if _VIN_RE.search(tail):
            hits += 1
            if hits >= 3:  # three is plenty; stop counting and save the CPU
                break

    if hits >= 3:
        return True, "sitemap.xml contains vehicle URLs ending in a 17-character VIN (DealerOn's URL style)"
    return False, None


# ---------------------------------------------------------------------------
# The public API
# ---------------------------------------------------------------------------


def detect(url, verbose=False):
    """Work out which platform built `url`.

    Returns a dictionary with three keys, always:

        platform  -- "dealeron", "dealer_inspire", "dealer_com", or "generic"
        site_id   -- Dealer.com's account id if we found one, otherwise None.
                     Paste this into config/dealers.yml under `site_id:`.
        evidence  -- a list of plain sentences explaining the decision. Print these.
                     If the answer looks wrong, the evidence tells you why it went wrong.

    Set verbose=True to have it narrate as it goes (handy from a script; the CLI
    normally prints the evidence list itself instead).

    This function never raises. An unreachable site comes back as "generic" with the
    reason in `evidence`.
    """
    evidence = []
    base = base_url(url)

    if not base:
        return {
            "platform": "generic",
            "site_id": None,
            "evidence": ["could not reach site: %r is not a usable web address" % (url,)],
        }

    if verbose:
        print("  [detect] Reading %s ..." % base)

    # --- Step 1: read the homepage once, and squeeze it for everything -----------
    html, error = _safe_get(
        base,
        timeout=HOMEPAGE_TIMEOUT,
        retries=HOMEPAGE_RETRIES,
        allow_browser_fallback=True,
    )

    if not html:
        # A site we cannot open is not a site we can classify. Say so honestly rather
        # than pretending "generic" was a considered decision.
        reason = error or "the homepage returned nothing (404, or blocked)"
        return {
            "platform": "generic",
            "site_id": None,
            "evidence": ["could not reach site: %s" % reason],
        }

    scores, homepage_evidence = _score_homepage(html)
    evidence.extend(homepage_evidence)

    # Dealer.com's site id is worth grabbing whenever it is present, even if we end up
    # deciding the site is something else -- it costs nothing, and a wrong-but-harmless
    # extra field beats a dealer hunting through page source by hand.
    site_id = _extract_site_id(html)

    platform, points = _best(scores)

    if verbose and scores:
        print("  [detect] homepage clues: %s" % scores)

    # --- Step 2: only if the homepage was vague, knock on the known doors --------
    # WHY the order: the Dealer Inspire sitemap is a single request with a yes/no
    # answer, so it is the cheapest way to turn a maybe into a definite.
    if platform is None or points < CONFIDENT_SCORE:
        if verbose:
            print("  [detect] homepage was not conclusive, checking vendor sitemaps...")

        matched, line = _probe_dealer_inspire(base)
        if matched:
            evidence.append(line)
            scores["dealer_inspire"] = scores.get("dealer_inspire", 0) + 5
        else:
            matched, line = _probe_dealeron(base)
            if matched:
                evidence.append(line)
                scores["dealeron"] = scores.get("dealeron", 0) + 5

        platform, points = _best(scores)

    # --- Step 3: decide -----------------------------------------------------------
    if platform is None or points < 2:
        # Either nothing matched, or only the weakest hints did (plenty of sites use
        # WordPress or .aspx without being DI or DealerOn). Be honest about it.
        if not evidence:
            evidence.append("no DealerOn, Dealer Inspire, or Dealer.com fingerprints found on the homepage")
        else:
            evidence.append("clues were too weak to pick a vendor confidently")
        evidence.append("falling back to the 'generic' adapter, which reads the site's sitemap and structured data")
        return {"platform": "generic", "site_id": site_id, "evidence": evidence}

    if platform != "dealer_com":
        # site_id only means something to the Dealer.com adapter. Do not hand a
        # DealerOn config a Dealer.com account number; it would be quietly confusing.
        site_id = None
    elif site_id:
        evidence.append("found Dealer.com siteId '%s' (this goes in dealers.yml as site_id)" % site_id)
    else:
        evidence.append(
            "could not find the Dealer.com siteId in the homepage -- "
            "you may need to fill in site_id by hand in config/dealers.yml"
        )

    if verbose:
        print("  [detect] -> %s" % platform)

    return {"platform": platform, "site_id": site_id, "evidence": evidence}


def detect_platform(url):
    """Just the platform name: "dealeron", "dealer_inspire", "dealer_com" or "generic".

    A thin convenience wrapper over detect(). Use detect() when you want to show a
    person why the answer is what it is.
    """
    return detect(url)["platform"]
