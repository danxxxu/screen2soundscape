# question_to_overpass.py
import os
import re
import json
import string
import time
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
from geopy.geocoders import Nominatim
from langdetect import detect
from deep_translator import GoogleTranslator
from geoparser import Geoparser
from OSMPythonTools.overpass import Overpass, overpassQueryBuilder
from OSMPythonTools.nominatim import Nominatim as OSMToolsNominatim

# =============== Global NLP ===============
@lru_cache()
def get_nlp():
    import spacy
    return spacy.load("en_core_web_sm")

nlp = get_nlp()
geoparser = Geoparser()

# =============== Geocoding ===============
@lru_cache()
def shared_nominatim():
    return Nominatim(user_agent="osmv", timeout=5)

GEOCODE_CACHE_FILE = "geocode_cache.json"
if os.path.exists(GEOCODE_CACHE_FILE):
    with open(GEOCODE_CACHE_FILE, "r", encoding="utf-8") as f:
        GEOCODE_CACHE = json.load(f)
else:
    GEOCODE_CACHE = {}

def save_geocode_cache():
    with open(GEOCODE_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(GEOCODE_CACHE, f)

@lru_cache(maxsize=300)
def geocode_point_cached(loc):
    key = loc.strip().lower()
    if key in GEOCODE_CACHE:
        return tuple(GEOCODE_CACHE[key])
    geo = shared_nominatim()
    place = geo.geocode(loc, exactly_one=True)
    if not place:
        raise ValueError(f"Could not geocode: {loc}")
    coords = (place.latitude, place.longitude)
    GEOCODE_CACHE[key] = coords
    save_geocode_cache()
    return coords

@lru_cache(maxsize=200)
def geocode_point(loc):
    geo = shared_nominatim()
    place = geo.geocode(loc, exactly_one=True)
    if not place:
        raise ValueError(f"Could not geocode: {loc}")
    return place.latitude, place.longitude

# =============== Helpers ===============
DEFAULT_RADIUS = 1000
CUISINE_KEYWORDS = [
    "chinese", "italian", "japanese", "indian", "thai", "mexican", "greek", "french",
    "vietnamese", "turkish", "korean", "lebanese", "ethiopian", "burger", "pizza",
    "vegetarian", "vegan", "halal", "kosher"
]

STOPWORDS = {"is","a","an","the","in","on","at","of","to","from","with","for","near","by"}

def clean_name(n):
    return n.strip().strip(string.punctuation)

def detect_and_translate(q):
    try:
        if all(ord(c) < 128 for c in q):
            return q
        lang = detect(q)
        if lang != "en":
            t = GoogleTranslator(source=lang, target="en").translate(q)
            print(f"\U0001F30D {lang} → EN: {q!r} → {t!r}")
            return t
    except Exception as e:
        print(f"⚠️ Lang detect fail: {e}")
    return q

def extract_location_bitnet(text: str) -> str:
    """
    Use BitNet to extract the most salient named place/landmark from 'text'.
    Returns a short string like 'Times Square' (no extra words).
    """
    from utils.bitnet_singleton import chat as bitnet_chat

    system = (
        "You are a precise information extractor. "
        "Return ONLY the primary real-world place or landmark mentioned. "
        "No explanations, no quotes, no extra words."
    )
    # Few-shot to anchor format
    user = (
        "Extract the single most likely place/landmark name.\n\n"
        "Input: I want sushi near Times Square.\nAnswer: Times Square\n\n"
        f"Input: {text}\nAnswer:"
    )
    out = bitnet_chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_new_tokens=32,
        temperature=0.0,
        top_p=1.0,
    ).strip()

    # Clean up: first line, strip bullets/quotes/punct
    out = out.splitlines()[0]
    out = re.sub(r"^[\-\*\s:>]+", "", out).strip().strip("\"'`.,;:")
    # If model echoed "Answer:" or similar, remove it
    out = re.sub(r"(?i)^(answer|output)\s*:\s*", "", out).strip()
    return out

# =============== Main Parser ===============
def parse_question(raw_q, lat=None, lon=None):
    t0 = time.time()
    q = detect_and_translate(raw_q)
    doc = nlp(q)

    P = {
        "tag_key": None, "tag_value": None,
        "mode": None, "center": None, "radius": DEFAULT_RADIUS,
        "place_name": None, "loc_source": None
    }

    # inject tags for cafes
    if "coffee" in q.lower() and "shop" in q.lower():
        P.update({"tag_key": "amenity", "tag_value": "cafe"})

    # If CLI provided coords, prefer them and stop early.
    if lat is not None and lon is not None:
        P["center"] = (lat, lon)
        P["loc_source"] = "fallback_coords"
        P["place_name"] = "user_location"
        print(f"📍 Using fallback coordinates: ({lat}, {lon})")
        P["mode"] = "generic"
        print(f"🕒 parse_question took {time.time() - t0:.2f}s")
        return P

    # NER/regex candidates
    candidates = [ent.text for ent in doc.ents if ent.label_ in {"GPE", "LOC", "FAC", "ORG"}]
    regex_match = re.search(r"(?:in|near|around|by)\s+(.+)", q, re.IGNORECASE)
    if regex_match:
        candidates.append(regex_match.group(1))

    # Try fast geocode on the first few candidates
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(geocode_point_cached, clean_name(c)): c for c in candidates[:3]
        }
        for future in as_completed(futures):
            try:
                coords = future.result()
                name = clean_name(futures[future])
                P["center"] = coords
                P["place_name"] = name
                P["loc_source"] = "NER/regex"
                print(f"📍 Geocoded: {name} → {coords}")
                break
            except:
                continue

    # BitNet fallback extractor (replaces LLaMA)
    if not P["center"] and any(kw in q.lower() for kw in ["where", "near", "location", "places", "find"]):
        try:
            fallback_loc = extract_location_bitnet(raw_q)
            if fallback_loc:
                try:
                    coords = geocode_point_cached(fallback_loc)
                    P["center"] = coords
                    P["place_name"] = fallback_loc
                    P["loc_source"] = "BitNet"
                    print(f"🤖 BitNet fallback: {fallback_loc} → {coords}")
                except:
                    # Gentle retries with suffixes to help geocoders
                    for suffix in [" building", " museum", " location"]:
                        retry = (fallback_loc + suffix).strip()
                        try:
                            coords = geocode_point_cached(retry)
                            P["center"] = coords
                            P["place_name"] = retry
                            P["loc_source"] = "BitNet (retry)"
                            print(f"📍 Retried BitNet location as “{retry}” → geocoded successfully")
                            break
                        except:
                            continue
        except Exception as e:
            print(f"⚠️ BitNet extraction failed: {e}")

    # Final fallback if nothing worked
    if not P["center"]:
        P["center"] = (27.9881, 86.9250)
        P["place_name"] = "Mount Everest"
        P["loc_source"] = "fallback_everest"
        print("📍 Default to Mount Everest")

    P["mode"] = "generic"
    print(f"🕒 parse_question took {time.time() - t0:.2f}s")
    return P

_osm_overpass = Overpass()
_osm_nominatim = OSMToolsNominatim()

def build_overpass_query(P):
    selector_parts = []
    if P.get("tag_key") and P.get("tag_value"):
        selector_parts.append(f'"{P["tag_key"]}"="{P["tag_value"]}"')
    if P.get("wheelchair_only"):
        selector_parts.append('"wheelchair"="yes"')
    if P.get("pet_friendly"):
        selector_parts.append('"pets"="yes"')
    if P.get("opening_hours_regex"):
        selector_parts.append(f'"opening_hours"~"{P["opening_hours_regex"]}"')

    selector = " and ".join(selector_parts) if selector_parts else ""
    selector_brackets = f"[{selector}]" if selector else ""

    # Prefer area queries when we have a clear place name (other than user_location)
    if P.get("place_name") and P["place_name"] != "user_location":
        try:
            area_id = _osm_nominatim.query(P["place_name"]).areaId()
            return (
                f'[out:json][timeout:25];'
                f'(node(area:{area_id}){selector_brackets};'
                f'way(area:{area_id}){selector_brackets};'
                f'relation(area:{area_id}){selector_brackets};);out body;'
            )
        except Exception as e:
            print(f"⚠️ Failed to get areaId for {P['place_name']}: {e}")

    # Otherwise use around(center, radius)
    if P.get("center") and P.get("radius"):
        lat, lon = P["center"]
        radius = P["radius"]
        return (
            f'[out:json][timeout:25];'
            f'(node(around:{radius},{lat},{lon}){selector_brackets};'
            f'way(around:{radius},{lat},{lon}){selector_brackets};'
            f'relation(around:{radius},{lat},{lon}){selector_brackets};);out body;'
        )

    raise ValueError("❌ Cannot build query: no area or coordinates available.")
