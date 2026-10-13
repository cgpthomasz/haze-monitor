"""
Singapore town-to-region mapping for NEA haze/PSI reporting.

NEA publishes PSI and PM2.5 readings for 5 regions:
    North, South, East, West, Central

This module maps towns, planning areas, and common abbreviations to their
NEA region, so readings from data.gov.sg can be resolved to a user's
approximate location.

Sources
-------
- NEA PSI/PM2.5 region definitions:
  https://www.nea.gov.sg/our-services/pollution-control/air-pollution/faqs
- Town list (URA planning areas):
  https://www.bcs.org.sg/form/region
- data.gov.sg real-time APIs (region keys: central, west, south, east, north)

Important notes
---------------
1. These are NEA's haze-reporting regions, NOT URA planning regions.
   URA uses: Central, North, North-East, East, West (different boundaries).
2. Some towns near region borders may be debatable. Assignments below
   follow NEA's published region map as closely as possible.
3. If a town is not found, NEA advises using the nearest region.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Canonical region names (as returned by the data.gov.sg API)
# ---------------------------------------------------------------------------

REGIONS = ["central", "west", "south", "east", "north"]


# ---------------------------------------------------------------------------
# Alias table — common abbreviations and alternate spellings
# Applied BEFORE the main town lookup.
# ---------------------------------------------------------------------------

TOWN_ALIASES: dict[str, str] = {
    # Common abbreviations
    "amk":      "ang mo kio",
    "bb":       "bukit batok",
    "bdk":      "bedok",
    "bp":       "bukit panjang",
    "bt":       "bukit timah",
    "btm":      "bukit merah",
    "cbd":      "city",
    "cck":      "choa chu kang",
    "cwc":      "central water catchment",
    "gl":       "geylang",
    "hg":       "hougang",
    "je":       "jurong east",
    "ji":       "jurong island",
    "jw":       "jurong west",
    "kb":       "kallang",
    "lck":      "lim chu kang",
    "mp":       "marine parade",
    "pg":       "punggol",
    "pl":       "paya lebar",
    "pr":       "pasir ris",
    "qt":       "queenstown",
    "sk":       "sengkang",
    "srg":      "serangoon",
    "srgn":     "serangoon",
    "sw":       "sembawang",
    "tamp":     "tampines",
    "tp":       "toa payoh",
    "wl":       "woodlands",
    "ys":       "yishun",

    # Alternate spellings and case variants
    "angmokio":         "ang mo kio",
    "bkt batok":        "bukit batok",
    "bkt merah":        "bukit merah",
    "bkt panjang":      "bukit panjang",
    "bkt timah":        "bukit timah",
    "choa chu kang":    "choa chu kang",
    "chu kang":         "choa chu kang",
    "jurong":           "jurong west",     # unqualified "Jurong" defaults to West
    "marine parade":    "marine parade",
    "paya lebar":       "paya lebar",
    "southern isls":    "southern islands",
    "sungei kadut":     "sungei kadut",
    "western isls":     "western islands",
    "western water catchment": "western water catchment",
    "yio chu kang":     "yio chu kang",
}


# ---------------------------------------------------------------------------
# Town → NEA region mapping
# Covers all 47 URA planning areas plus commonly referenced subzones.
# ---------------------------------------------------------------------------

TOWN_TO_REGION: dict[str, str] = {
    # --- NORTH ---
    "central water catchment":  "north",
    "lim chu kang":             "north",
    "mandai":                   "north",
    "pulau tekong":             "north",
    "pulau ubin":               "north",
    "punggol":                  "north",
    "seletar":                  "north",
    "sembawang":                "north",
    "sengkang":                 "north",
    "sungei kadut":             "north",
    "woodlands":                "north",
    "yishun":                   "north",

    # --- CENTRAL ---
    "bishan":                   "central",
    "toa payoh":                "central",

    # --- SOUTH ---
    "bukit merah":              "south",
    "bukit timah":              "south",
    "city":                     "south",
    "marine parade":            "south",
    "newton":                   "south",
    "novena":                   "south",
    "orchard":                  "south",
    "outram":                   "south",
    "queenstown":               "south",
    "sentosa":                  "south",
    "southern islands":         "south",
    "tanglin":                  "south",

    # --- EAST ---
    "ang mo kio":               "east",
    "bedok":                    "east",
    "changi":                   "east",
    "geylang":                  "east",
    "hougang":                  "east",
    "kallang":                  "east",
    "pasir ris":                "east",
    "paya lebar":               "east",
    "serangoon":                "east",
    "tampines":                 "east",

    # --- WEST ---
    "boon lay":                 "west",
    "bukit batok":              "west",
    "bukit panjang":            "west",
    "choa chu kang":            "west",
    "clementi":                 "west",
    "jalan bahar":              "west",
    "jurong east":              "west",
    "jurong island":            "west",
    "jurong west":              "west",
    "pioneer":                  "west",
    "tengah":                   "west",
    "tuas":                     "west",
    "western islands":          "west",
    "western water catchment":  "west",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise(name: str) -> str:
    """Lowercase, strip, collapse internal whitespace."""
    return " ".join(name.strip().lower().split())


def resolve_town(town: str) -> str | None:
    """Resolve an alias to its canonical town name, or return the input
    normalised if no alias matches. Returns None if the input is empty.
    """
    key = _normalise(town)
    if not key:
        return None
    return TOWN_ALIASES.get(key, key)


def region_for_town(town: str) -> str | None:
    """Return the NEA region for a town name, or None if not found.

    Pipeline:
        1. Normalise input (lowercase, strip, collapse whitespace)
        2. Resolve alias if one matches
        3. Look up the canonical town in TOWN_TO_REGION
    """
    canonical = resolve_town(town)
    if canonical is None:
        return None
    return TOWN_TO_REGION.get(canonical)


def region_or_default(town: str, default: str = "central") -> str:
    """Like region_for_town, but returns a default instead of None."""
    return region_for_town(town) or default


def towns_in_region(region: str) -> list[str]:
    """Return all canonical town names mapped to the given region."""
    r = _normalise(region)
    return sorted(t for t, reg in TOWN_TO_REGION.items() if reg == r)
