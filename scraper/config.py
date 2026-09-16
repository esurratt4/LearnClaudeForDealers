"""
Reads your dealership list out of config/dealers.yml.

PLAIN ENGLISH: this file is the scraper's address book. You tell it which store is
YOURS and which stores are your COMPETITORS, and every other part of the program asks
this file "who am I scraping today?"

You never edit this file. You edit `config/dealers.yml` -- the friendly text file with
your store names and website addresses in it. This file's only job is to read that text
file, clean it up, and complain loudly (in English) if something in it is wrong.

A "dealer" in this program is just a bundle of facts, stored as a Python dictionary:

    {
      "key":          "laura",                        # short nickname, see note below
      "name":         "Laura Buick GMC",
      "url":          "https://www.laurabuickgmc.com",
      "city":         "Collinsville",
      "state":        "IL",
      "platform":     "dealeron" or None,             # None = "figure it out for me"
      "is_own_store": False,
      "makes":        ["GMC"] or None,                # None = scrape every brand
      "site_id":      "skpontiacgmcinc" or None,      # only some platforms need this
      "condition":    "new",                          # "new" or "used"
    }
"""

import os

import yaml


# The keys every dealer dictionary is guaranteed to have once we are done with it.
# Other files in this project rely on this, so they never have to write defensive code
# like `dealer.get("site_id", None)` -- the key is always there.
DEALER_KEYS = (
    "key",
    "name",
    "url",
    "city",
    "state",
    "platform",
    "is_own_store",
    "makes",
    "site_id",
    "condition",
)

# Where we look for your config if you don't say otherwise. Relative to wherever you
# are standing when you run the scraper, which for this project is the repo folder.
DEFAULT_CONFIG_PATH = "config/dealers.yml"

# Shown whenever the config file is missing or broken. It names the exact command to
# type, because a dealership manager should never have to go hunting through a README
# to recover from an error message.
_SETUP_HINT = (
    "Copy the example file and then edit it:\n"
    "    cp config/dealers.example.yml config/dealers.yml"
)


def _normalize_dealer(raw, is_own_store, where):
    """
    Turn one entry from dealers.yml into a complete, trustworthy dealer dictionary.

    `raw`   is whatever YAML handed us (hopefully a dict).
    `where` is a human-readable label like "own_store" or "competitors[2]" that we put
            into error messages so you know which line of the file to go fix.
    """
    if not isinstance(raw, dict):
        raise ValueError(
            "Config error in {0}: expected a block of settings (key/name/url/...), "
            "got {1!r}.\n{2}".format(where, raw, _SETUP_HINT)
        )

    # --- key ---------------------------------------------------------------
    # `key` is REQUIRED. It is the join key in the database: every row in the
    # `vehicles` table is stamped with `dealer_key`, and the UNIQUE constraint is
    # (vin, dealer_key). That means changing a dealer's key later makes the database
    # treat it as a brand-new store and you lose the price history tied to the old key.
    # Pick a short slug once and leave it alone.
    key = raw.get("key")
    if key is None or str(key).strip() == "":
        raise ValueError(
            "Config error in {0}: every dealer needs a `key` (a short nickname like "
            "`laura` or `my-store`). It is how this dealer's cars are labelled in the "
            "database.\n{1}".format(where, _SETUP_HINT)
        )
    key = str(key).strip()

    name = str(raw.get("name") or key).strip()

    # --- url ---------------------------------------------------------------
    url = str(raw.get("url") or "").strip()
    if not url.lower().startswith("http"):
        raise ValueError(
            "Config error for dealer '{0}' ({1}): `url` must be a full web address "
            "starting with http:// or https:// -- got {2!r}. Copy it out of your "
            "browser's address bar, including the https:// part.".format(
                key, name, url
            )
        )
    # Strip the trailing slash exactly once, here, so that every other file in the
    # project can safely write `dealer["url"] + "/sitemap.xml"` without accidentally
    # producing a double slash that some dealer websites reject.
    url = url.rstrip("/")

    # --- platform ----------------------------------------------------------
    # Which website software the store runs on (dealeron / dealer_inspire /
    # dealer_com / generic). Leaving it out of the YAML is normal and encouraged --
    # scraper/detect.py sniffs it from the live site. None means "auto-detect me".
    platform = raw.get("platform")
    if platform is not None:
        platform = str(platform).strip().lower() or None

    # --- makes -------------------------------------------------------------
    # Optional brand filter, e.g. ["GMC"] for a store that sells both Chevrolet and
    # GMC when you only care about GMC. None means "give me everything".
    makes = raw.get("makes")
    if makes is not None:
        if isinstance(makes, str):
            makes = [makes]          # be forgiving: `makes: GMC` works as well as a list
        makes = [str(m).strip() for m in makes if str(m).strip()]
        if not makes:
            makes = None

    # --- site_id -----------------------------------------------------------
    # Some platforms (notably Dealer.com) will not answer their inventory API without
    # an internal account id. There is no way to guess it, so it has to be written
    # down here. Kept as text because these ids can have leading zeros.
    site_id = raw.get("site_id")
    if site_id is not None:
        site_id = str(site_id).strip() or None

    # --- condition ---------------------------------------------------------
    # "new" or "used". Defaults to new because that is what most stores compare on.
    condition = str(raw.get("condition") or "new").strip().lower()
    if condition not in ("new", "used"):
        raise ValueError(
            "Config error for dealer '{0}' ({1}): `condition` must be either `new` or "
            "`used` -- got {2!r}.".format(key, name, condition)
        )

    return {
        "key": key,
        "name": name,
        "url": url,
        "city": str(raw.get("city") or "").strip(),
        "state": str(raw.get("state") or "").strip().upper(),
        "platform": platform,
        "is_own_store": bool(is_own_store),
        "makes": makes,
        "site_id": site_id,
        "condition": condition,
    }


def load_config(path=DEFAULT_CONFIG_PATH):
    """
    Read config/dealers.yml and hand back a tidy, validated configuration.

    Returns a dictionary shaped like:
        {"own_store": <dealer dict or None>, "competitors": [<dealer dict>, ...]}

    Raises FileNotFoundError (with copy-paste instructions) if the file is missing,
    and ValueError with a plain-English explanation if something inside it is wrong.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            "Could not find your dealer list at '{0}'.\n{1}\n"
            "Then open config/dealers.yml and put your own store's website in it.".format(
                path, _SETUP_HINT
            )
        )

    with open(path, "r", encoding="utf-8") as fh:
        # safe_load (not load) because a config file should never be able to execute
        # code. This matters: people paste these files around in Slack.
        try:
            data = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            raise ValueError(
                "'{0}' is not valid YAML, so we could not read it. YAML is picky about "
                "indentation -- every line under a dealer must be indented the same "
                "amount, using spaces (never tabs).\n\nThe details:\n{1}".format(
                    path, exc
                )
            )

    # An empty file parses to None, which would otherwise blow up below.
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError(
            "'{0}' should start with `own_store:` and/or `competitors:` at the very "
            "left margin.\n{1}".format(path, _SETUP_HINT)
        )

    own_raw = data.get("own_store")
    own_store = None
    if own_raw:
        own_store = _normalize_dealer(own_raw, True, "own_store")

    competitors_raw = data.get("competitors") or []
    if not isinstance(competitors_raw, list):
        raise ValueError(
            "In '{0}', `competitors:` must be a list. Each competitor starts with a "
            "dash, like:\n"
            "    competitors:\n"
            "      - key: competitor-one\n"
            "        name: Competitor One".format(path)
        )

    competitors = []
    for i, raw in enumerate(competitors_raw):
        competitors.append(
            _normalize_dealer(raw, False, "competitors[{0}]".format(i))
        )

    # --- uniqueness check --------------------------------------------------
    # Duplicate keys are checked AFTER everything is normalized, and it is a hard
    # error rather than a warning. Two dealers sharing a key would collide on the
    # database's UNIQUE (vin, dealer_key) constraint: one store's cars would silently
    # overwrite the other's, and the numbers you report would be wrong without ever
    # looking wrong.
    seen = {}
    for dealer in ([own_store] if own_store else []) + competitors:
        if dealer["key"] in seen:
            raise ValueError(
                "Duplicate dealer key '{0}' in '{1}': it is used by both '{2}' and "
                "'{3}'. Every dealer needs its own key, because the key is what labels "
                "that store's cars in the database. Rename one of them.".format(
                    dealer["key"], path, seen[dealer["key"]], dealer["name"]
                )
            )
        seen[dealer["key"]] = dealer["name"]

    if own_store is None and not competitors:
        raise ValueError(
            "'{0}' does not list any dealers. Add at least an `own_store:` block with "
            "your store's website.\n{1}".format(path, _SETUP_HINT)
        )

    return {"own_store": own_store, "competitors": competitors}


def all_dealers(cfg):
    """
    Every dealer in one flat list, YOUR store first.

    Own store first is deliberate: when the scraper runs the whole list, you find out
    your own inventory scraped correctly before spending ten minutes on competitors.
    """
    dealers = []
    if cfg.get("own_store"):
        dealers.append(cfg["own_store"])
    dealers.extend(cfg.get("competitors") or [])
    return dealers


def find_dealer(cfg, key):
    """Look up one dealer by its key. Returns None if there is no such dealer."""
    if not key:
        return None
    wanted = str(key).strip().lower()
    for dealer in all_dealers(cfg):
        if dealer["key"].lower() == wanted:
            return dealer
    return None
