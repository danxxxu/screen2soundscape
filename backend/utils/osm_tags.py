# utils/osm_tags.py
import re
from typing import Dict, Optional


# --- Canonical map from phrases to OSM tags. Keep keys singular/canonical. ---
TAG_MAP: Dict[str, Dict[str, str]] = {
    # --- Food & Drink ---
    "coffee shop": {"amenity": "cafe"},
    "cafe": {"amenity": "cafe"},
    "restaurant": {"amenity": "restaurant"},
    "fast food": {"amenity": "fast_food"},
    "bar": {"amenity": "bar"},
    "pub": {"amenity": "pub"},
    "bakery": {"shop": "bakery"},
    "supermarket": {"shop": "supermarket"},
    "grocery": {"shop": "convenience"},
    "pizza": {"cuisine": "pizza", "amenity": "restaurant"},
    "ice cream": {"amenity": "ice_cream"},

    # --- Transport ---
    "bus stop": {"highway": "bus_stop"},
    "train station": {"railway": "station"},
    "subway station": {"railway": "station", "station": "subway"},
    "bike rental": {"amenity": "bicycle_rental"},
    "taxi": {"amenity": "taxi"},

    # --- Money & Services ---
    "atm": {"amenity": "atm"},
    "bank": {"amenity": "bank"},
    "post office": {"amenity": "post_office"},
    "pharmacy": {"amenity": "pharmacy"},
    "hospital": {"amenity": "hospital"},
    "clinic": {"amenity": "clinic"},

    # --- Lodging & Tourism ---
    "hotel": {"tourism": "hotel"},
    "motel": {"tourism": "motel"},
    "hostel": {"tourism": "hostel"},
    "camping": {"tourism": "camp_site"},
    "museum": {"tourism": "museum"},
    "park": {"leisure": "park"},
    "playground": {"leisure": "playground"},

    # --- Entertainment ---
    "cinema": {"amenity": "cinema"},
    "theatre": {"amenity": "theatre"},
    "theater": {"amenity": "theatre"},  # alias
    "nightclub": {"amenity": "nightclub"},
    "stadium": {"leisure": "stadium"},

    # --- Shopping ---
    "mall": {"shop": "mall"},
    "clothes shop": {"shop": "clothes"},
    "electronics store": {"shop": "electronics"},
    "bookstore": {"shop": "books"},
    "shoe store": {"shop": "shoes"},
    "jewelry": {"shop": "jewelry"},
    "market": {"amenity": "marketplace"},

    # --- Toilets / WC synonyms ---
    "toilet": {"amenity": "toilets"},
    "wc": {"amenity": "toilets"},
    "restroom": {"amenity": "toilets"},
    "bathroom": {"amenity": "toilets"},
    "lavatory": {"amenity": "toilets"},
    "loo": {"amenity": "toilets"},

    # --- Other ---
    "parking": {"amenity": "parking"},
    "library": {"amenity": "library"},
    "school": {"amenity": "school"},
    "university": {"amenity": "university"},
    "police": {"amenity": "police"},
    "fire station": {"amenity": "fire_station"},
}


# Terms that generally don't pluralize (or where pluralization is odd/ambiguous).
_UNCOUNTABLE = {
    "fast food",
    "ice cream",
    "atm",     # usually used as “an ATM” but we keep it as token
    "taxi",    # “taxis” exists, but we map singular token anyway
    "camping",
    "jewelry",
    "parking",
    "wc",
}


def _plural_variants(word: str) -> list[str]:
    """Return [singular, plural] variants for a single word."""
    w = word
    # Already plural? keep as-is plus a naive singular backoff
    if re.search(r"(s|es|ies|ves)$", w):
        # naive de-plural backoff for matching both ways
        variants = {w}
        if w.endswith("ies"):
            variants.add(w[:-3] + "y")
        elif w.endswith("ves"):
            variants.add(w[:-3] + "f")
            variants.add(w[:-3] + "fe")
        elif w.endswith("es"):
            # boxes -> box, churches -> church
            if w.endswith(("ses", "xes", "zes", "ches", "shes")):
                variants.add(w[:-2])  # remove 'es'
        elif w.endswith("s") and len(w) > 1:
            variants.add(w[:-1])
        return list(variants)

    # Singular → plurals
    if re.search(r"(s|x|z|ch|sh)$", w):
        return [w, w + "es"]
    if re.search(r"[^aeiou]y$", w):
        return [w, w[:-1] + "ies"]
    if w.endswith("fe"):
        return [w, w[:-2] + "ves"]
    if w.endswith("f"):
        return [w, w[:-1] + "ves"]
    return [w, w + "s"]


def _phrase_regex_with_plural(key: str) -> str:
    """
    Build a regex that matches the key phrase in singular OR plural,
    assuming plurality applies to the LAST token.
    """
    tokens = key.split()
    if not tokens:
        return r""

    # If the phrase is uncountable, match exactly (word boundaries + flexible whitespace)
    if key in _UNCOUNTABLE:
        esc = r"\s+".join(re.escape(tok) for tok in tokens)
        return rf"\b{esc}\b"

    # Otherwise pluralize only the last token
    head = tokens[:-1]
    tail = tokens[-1]
    variants = _plural_variants(tail)

    head_part = r"\s+".join(re.escape(tok) for tok in head)
    tail_part = r"(?:%s)" % "|".join(re.escape(v) for v in variants)

    if head_part:
        pattern = rf"\b{head_part}\s+{tail_part}\b"
    else:
        pattern = rf"\b{tail_part}\b"
    return pattern


def _normalize_text(s: str) -> str:
    """Lowercase and collapse whitespace; keep punctuation boundaries helpful for \\b."""
    s = s.lower()
    # Convert some punctuation to spaces to enable \b matches
    s = re.sub(r"[/_-]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def find_osm_tags(question: str) -> Optional[Dict[str, str]]:
    """
    Try to match user query against TAG_MAP keys (singular or plural).
    Returns a dict of OSM tags or None if no match found.
    - Prefers longer phrases first to avoid partial matches (e.g., "bus stop" before "bus").
    """
    if not question:
        return None

    q = _normalize_text(question)

    # Sort keys by length (desc) so multi-word phrases win over single tokens
    keys = sorted(TAG_MAP.keys(), key=lambda k: len(k), reverse=True)

    for key in keys:
        pattern = _phrase_regex_with_plural(key)
        if not pattern:
            continue
        if re.search(pattern, q, flags=re.IGNORECASE):
            return TAG_MAP[key]

    return None
