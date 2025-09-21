# utils/question_to_overpass.py
import os
import re
import json
import string
import time
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Optional, Tuple

from geopy.geocoders import Nominatim as GeopyNominatim
from langdetect import detect
from deep_translator import GoogleTranslator
from pathlib import Path
OSM_TAG_VALUES_ENV = os.environ.get("OSM_TAG_VALUES_PATH", "").strip()

try:
    from geoparser import Geoparser
    _GEOPARSER = Geoparser()
except Exception:
    _GEOPARSER = None

# OSMPythonTools for areaId() and Overpass wrapper (we only use areaId here)
from OSMPythonTools.overpass import Overpass, overpassQueryBuilder
from OSMPythonTools.nominatim import Nominatim as OSMToolsNominatim

# ========= Embedding / NLP (lazy) =========
@lru_cache()
def _get_nlp():
    try:
        import spacy
        return spacy.load("en_core_web_sm")
    except Exception:
        return None

# ========= Overpass / Nominatim singletons =========
_osm_overpass = Overpass()
_osm_nominatim = OSMToolsNominatim()

# ========= Geocoding (Geopy) =========
@lru_cache()
def _shared_nominatim():
    return GeopyNominatim(user_agent="screen2soundscape/1.0", timeout=6)

_GEOCODE_CACHE_FILE = "geocode_cache.json"
if os.path.exists(_GEOCODE_CACHE_FILE):
    with open(_GEOCODE_CACHE_FILE, "r", encoding="utf-8") as _f:
        _GEOCODE_CACHE = json.load(_f)
else:
    _GEOCODE_CACHE = {}

def _save_geocode_cache():
    with open(_GEOCODE_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(_GEOCODE_CACHE, f)

@lru_cache(maxsize=300)
def geocode_point_cached(loc: str) -> Tuple[float, float]:
    key = (loc or "").strip().lower()
    if not key:
        raise ValueError("Empty location")
    if key in _GEOCODE_CACHE:
        lat, lon = _GEOCODE_CACHE[key]
        return float(lat), float(lon)
    geo = _shared_nominatim()
    place = geo.geocode(loc, exactly_one=True)
    if not place:
        raise ValueError(f"Could not geocode: {loc}")
    coords = (float(place.latitude), float(place.longitude))
    _GEOCODE_CACHE[key] = coords
    _save_geocode_cache()
    return coords

def _split_tag_values(v: str) -> list[str]:
    """Split accidental multi-values like 'herbalist;supermarket' into clean tokens."""
    if not isinstance(v, str):
        return []
    parts = re.split(r"[;,\s]+", v.strip())
    return [p for p in parts if p]

# ========= Language utils =========
def detect_and_translate(q: str) -> str:
    """
    If non-ASCII and non-English, translate to English; otherwise return original.
    Keeps your previous behavior.
    """
    try:
        if all(ord(c) < 128 for c in (q or "")):
            return q
        lang = detect(q or "")
        if lang and lang != "en":
            t = GoogleTranslator(source=lang, target="en").translate(q)
            print(f"\U0001F30D {lang} → EN: {q!r} → {t!r}")
            return t or q
    except Exception as e:
        print(f"⚠️ Lang detect/translate failed: {e}")
    return q

# ========= Data-driven tag resolver (no hardcoding) =========
# Uses your cached list of actual OSM tag values
try:
    from rapidfuzz import fuzz
    def _sim(a, b): return fuzz.token_set_ratio(a, b)  # 0..100
except Exception:
    import difflib
    def _sim(a, b): return int(100 * difflib.SequenceMatcher(None, a, b).ratio())

def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[/_]+", " ", s)
    s = re.sub(r"[^\w\s]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # tiny, general singularization (enough for pharmacies→pharmacy, toilets→toilet)
    if s.endswith("ies"): s = s[:-3] + "y"
    elif s.endswith("ves"): s = s[:-3] + "f"
    elif s.endswith("s") and len(s) > 3: s = s[:-1]
    return s

@lru_cache()
def _load_values_index(data_path: str | None = None) -> dict[str, set]:
    """
    Load the combined tag-values JSON (all_osm_tags.json).
    Tries, in order:
      1) explicit data_path arg (if given)
      2) $OSM_TAG_VALUES_PATH env var (absolute or relative)
      3) paths relative to this file and to the repo root:
         - ../osm_tags/tag_values/all_osm_tags.json
         - ./osm_tags/tag_values/all_osm_tags.json
         - ./backend/../osm_tags/tag_values/all_osm_tags.json
    Returns {key: set(values)} for allowed keys.
    """
    here = Path(__file__).resolve().parent
    repo = here.parent  # backend/
    candidates: list[Path] = []

    # 1) explicit param
    if data_path:
        candidates.append(Path(data_path))

    # 2) env override
    if OSM_TAG_VALUES_ENV:
        candidates.append(Path(OSM_TAG_VALUES_ENV))

    # 3) common relative locations
    candidates.extend([
        here / "../osm_tags/tag_values/all_osm_tags.json",       # e.g. backend/../osm_tags/...
        here / "osm_tags/tag_values/all_osm_tags.json",          # e.g. backend/osm_tags/...
        repo / "osm_tags/tag_values/all_osm_tags.json",          # e.g. <repo>/osm_tags/...
    ])

    chosen: Path | None = None
    for c in candidates:
        try:
            p = c.resolve()
        except Exception:
            p = c
        if p.exists():
            chosen = p
            break

    if not chosen:
        raise FileNotFoundError(
            "Missing tag-values JSON (all_osm_tags.json). "
            "Tried: " + ", ".join(str(c) for c in candidates)
            + "\nSet OSM_TAG_VALUES_PATH or pass data_path to resolve_tag_from_values()."
        )

    # Load and filter allowed keys
    with open(chosen, "r", encoding="utf-8") as f:
        data = json.load(f)

    allowed = {"amenity", "shop", "tourism", "leisure", "healthcare", "craft", "office", "natural", "highway"}
    idx = {k: set(vs) for k, vs in data.items() if k in allowed and isinstance(vs, list)}

    print(f"🔎 Using tag-values file: {chosen}")  # helpful once; cached after
    return idx

def resolve_tag_from_values(phrase: str, threshold: int = 60, data_path: str | None = None):
    phrase_n = _norm(phrase)
    if not phrase_n:
        return None
    idx = _load_values_index(data_path)

    best = ("", "", -1)
    for key, values in idx.items():
        for val in values:
            score = _sim(phrase_n, _norm(val))
            if score > best[2]:
                best = (key, val, score)
    return best if best[2] >= threshold else None

# ========= Parser helpers =========
DEFAULT_RADIUS = 1000  # meters
_COORDS_RE = re.compile(r"\b(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)\b")

def _clean_name(n: str) -> str:
    return (n or "").strip().strip(string.punctuation)

def _candidate_places_from_text(q_en: str) -> list:
    """
    Pull a few likely place strings from the text using spaCy (if available) and a simple regex tail.
    """
    cands = []
    nlp = _get_nlp()
    if nlp:
        try:
            doc = nlp(q_en)
            cands.extend([ent.text for ent in doc.ents if ent.label_ in {"GPE","LOC","FAC","ORG"}])
        except Exception:
            pass
    m = re.search(r"(?:in|near|around|by)\s+(.+)", q_en, re.IGNORECASE)
    if m:
        cands.append(m.group(1))
    # geoparser as an extra (optional)
    if _GEOPARSER:
        try:
            parsed = _GEOPARSER.parse(q_en) or {}
            for loc in (parsed.get("locations") or []):
                nm = loc.get("name")
                if nm: cands.append(nm)
        except Exception:
            pass
    # dedupe keeping order
    seen = set()
    out = []
    for c in cands:
        cc = _clean_name(c)
        if cc and cc.lower() not in seen:
            out.append(cc)
            seen.add(cc.lower())
    return out[:3]

# ========= MAIN: parse_question =========
def parse_question(raw_q: str, lat: float = None, lon: float = None) -> Dict:
    """
    Parse a natural-language question into Overpass query params.

    Preference order:
      1) Explicit CLI coordinates
      2) Tag detection (data-driven resolver using cached OSM values)
      3) NER/regex/geoparser for a place center
      4) Final fallback: Everest center (so we never crash)
    """
    t0 = time.time()
    q_en = detect_and_translate(raw_q or "")

    P = {
        "tag_key": None,
        "tag_value": None,
        "mode": "generic",
        "center": None,
        "radius": DEFAULT_RADIUS,
        "place_name": None,
        "loc_source": None,
        # optional filters you might set elsewhere:
        # "wheelchair_only": False, "pet_friendly": False, "opening_hours_regex": None
    }

    # (1) CLI lat/lon wins for center
    if lat is not None and lon is not None:
        P.update({"center": (float(lat), float(lon)), "loc_source": "cli_coords", "place_name": "user_location"})
    else:
        # also allow explicit coords in text
        m = _COORDS_RE.search(q_en)
        if m:
            P.update({"center": (float(m.group(1)), float(m.group(2))), "loc_source": "coords_in_text", "place_name": "user_location"})

    # (2) Tag detection (data-driven): resolve user phrase to an actual (key,value)
    # Try full question first; if weak, also try simple noun chunks
    tag_hit = resolve_tag_from_values(q_en)
    if not tag_hit:
        # try noun chunks/head nouns for better matching ("hair salon", "public toilet", etc.)
        nlp = _get_nlp()
        if nlp:
            try:
                doc = nlp(q_en)
                chunks = sorted({nc.text for nc in doc.noun_chunks}, key=len, reverse=True)
            except Exception:
                chunks = []
        else:
            chunks = []
        for ph in chunks[:4]:
            tag_hit = resolve_tag_from_values(ph)
            if tag_hit:
                break

    if tag_hit:
        k, v, score = tag_hit
        P["tag_key"], P["tag_value"] = k, v
        print(f"🏷️ Fallback tag from values: {k}={v} (score={score})")

    # (3) If no center yet, try to geocode named places extracted from text
    if P.get("center") is None:
        cands = _candidate_places_from_text(q_en)
        for c in cands:
            try:
                coords = geocode_point_cached(c)
                P.update({"center": coords, "place_name": c, "loc_source": "NER/regex"})
                print(f"📍 Geocoded: {c} → {coords}")
                break
            except Exception:
                continue

    # (4) Final fallback center to avoid crashes downstream
    if P.get("center") is None:
        P.update({"center": (27.9881, 86.9250), "place_name": "Mount Everest", "loc_source": "fallback"})
        print("⚠️ No location found, defaulting to Mount Everest")

    print(f"🕒 parse_question took {time.time() - t0:.2f}s")
    return P

# ========= QUERY BUILDER (with guardrails) =========
def build_overpass_query(P):
    """
    Build Overpass QL query safely.
    Uses `out tags center qt <limit>;` so ways/relations include a centroid,
    and caps rows to avoid huge payloads.
    """
    # ---- filters ----
    selector_parts = []
    
    # NEW: split accidental multi-values (e.g., 'herbalist;supermarket')
    if P.get("tag_key") and P.get("tag_value"):
        key = P["tag_key"]
        vals = _split_tag_values(P["tag_value"])
    
        # Prefer exact supermarket for this very common case; drop unrelated noise like 'herbalist'
        if key == "shop" and "supermarket" in vals:
            vals = ["supermarket"]
    
        if len(vals) == 0:
            selector_parts.append(f'"{key}"')  # key exists
        elif len(vals) == 1:
            selector_parts.append(f'"{key}"="{vals[0]}"')
        else:
            pat = "^(" + "|".join(map(re.escape, vals)) + ")$"
            selector_parts.append(f'"{key}"~"{pat}"')


    # ---- area branch (only if we have a selector) ----
    place_name = P.get("place_name")
    if place_name and place_name != "user_location" and selector:
        try:
            area_id = _osm_nominatim.query(place_name).areaId()
            return (
                f'[out:json][timeout:25];'
                f'(node(area:{area_id}){selector_brackets};'
                f'way(area:{area_id}){selector_brackets};'
                f'relation(area:{area_id}){selector_brackets};);'
                f'out tags center qt {out_limit};'
            )
        except Exception as e:
            print(f"⚠️ Failed to get areaId for {place_name}: {e}")

    # ---- around() branch ----
    if P.get("center"):
        lat, lon = P["center"]

        # Tagless guardrail: tiny, nodes-only, still capped
        if not selector:
            tiny = min(radius, 250)
            return (
                f'[out:json][timeout:25];'
                f'(node(around:{tiny},{lat},{lon}););'
                f'out tags center qt {min(out_limit, 200)};'
            )

        # Normal filtered query: nodes + ways + relations, capped
        return (
            f'[out:json][timeout:25];'
            f'(node(around:{radius},{lat},{lon}){selector_brackets};'
            f'way(around:{radius},{lat},{lon}){selector_brackets};'
            f'relation(around:{radius},{lat},{lon}){selector_brackets};);'
            f'out tags center qt {out_limit};'
        )

    raise ValueError("❌ Cannot build query: need a place_name with selector or a center coordinate.")
