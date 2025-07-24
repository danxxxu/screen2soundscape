# question_to_overpass.py - OPTIMIZED VERSION
import re
import spacy
import json
from difflib import get_close_matches
from geopy.geocoders import Nominatim
import sys
import os
from langdetect import detect
from deep_translator import GoogleTranslator
import string
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
import asyncio
import aiohttp
import time

# Lazy loading and caching optimizations
@lru_cache(maxsize=1)
def get_nlp():
    """Load spaCy model only once and cache it"""
    import spacy
    return spacy.load("en_core_web_sm")

@lru_cache(maxsize=1)
def get_geocoder():
    """Create geocoder instance once"""
    return Nominatim(user_agent="osmv", timeout=3)  # Reduced timeout

@lru_cache(maxsize=1)
def get_llm():
    """Load LLM only when needed"""
    try:
        from utils.llama_singleton import get_llm as load_llm
        return load_llm()
    except ImportError:
        return None

# Cache for geocoding results
@lru_cache(maxsize=500)
def geocode_point_cached(loc):
    """Cached geocoding with reduced timeout"""
    geo = get_geocoder()
    place = geo.geocode(loc, exactly_one=True)
    if not place:
        raise ValueError(f"Could not geocode: {loc}")
    return place.latitude, place.longitude

# Pre-compiled regex patterns for better performance
ROUTE_PATTERN1 = re.compile(r"\b(walk|drive|bike|bus|train)\b.*?from\s+(.+?)\s+to\s+(.+?)(?:\s+(?:past|via)\s+(.+))?$", re.IGNORECASE)
ROUTE_PATTERN2 = re.compile(r"\bfrom\s+(.+?)\s+to\s+(.+)", re.IGNORECASE)
PREPOSITION_PATTERN = re.compile(r"(?:in|near|around|by)\s+(.+)", re.IGNORECASE)
COFFEE_PATTERN = re.compile(r"coffee\s+(shop|place|bar|café|house)", re.IGNORECASE)
PET_PATTERN = re.compile(r"pet[- ]friendly", re.IGNORECASE)
OPENING_PATTERN = re.compile(r"open(?:ing)? past (\d+)(am|pm)?", re.IGNORECASE)
BABY_PATTERN = re.compile(r"baby chang(?:ing)? stations?", re.IGNORECASE)
NEAREST_PATTERN = re.compile(r"\b(?:nearest|closest)\s+(\w+)\b", re.IGNORECASE)
WITHIN_PATTERN = re.compile(r"within\s+(\d+)\s*km\s+of\s+(.+)", re.IGNORECASE)
WHERE_PATTERN = re.compile(r"where\s+is\s+(.+)", re.IGNORECASE)
PLACES_PATTERN = re.compile(r"places\s+near\s+(.+)", re.IGNORECASE)

# Load OSM tags once at startup
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TAG_VALUES_PATH = os.path.join(BASE_DIR, "..", "osm_tags", "all_osm_tags.json")

TAG_MAP = {}
if os.path.isfile(TAG_VALUES_PATH):
    try:
        with open(TAG_VALUES_PATH, "r", encoding="utf-8") as f:
            tag_values = json.load(f)
        for key, values in tag_values.items():
            for val in values:
                TAG_MAP[val] = (key, val)
    except Exception as e:
        print(f"⚠️ Could not load tag values cache: {e}")

# Constants
STOPWORDS = {"is","a","an","the","in","on","at","of","to","from","with","for","near","by"}
DEFAULT_RADIUS = 1000
CUISINE_KEYWORDS = [
    "chinese", "italian", "japanese", "indian", "thai", "mexican", "greek", "french",
    "vietnamese", "turkish", "korean", "lebanese", "ethiopian", "burger", "pizza",
    "vegetarian", "vegan", "halal", "kosher"
]

def clean_name(n):
    return n.strip().strip(string.punctuation)

def detect_and_translate_fast(q):
    """Faster language detection with early exit"""
    try:
        # Skip translation for obviously English text
        if any(word in q.lower() for word in ['the', 'and', 'or', 'in', 'at', 'to', 'from']):
            return q
        
        lang = detect(q)
        if lang != "en":
            t = GoogleTranslator(source=lang, target="en").translate(q)
            print(f"🌍 Detected {lang}: {q!r} → {t!r}")
            return t
    except:
        pass
    return q

def is_probably_not_location(text):
    """Quick location filter"""
    food_words = {"restaurant", "cafe", "bar", "pizzeria", "bakery"}
    cuisine_words = set(CUISINE_KEYWORDS)
    tokens = set(text.lower().split())
    return bool(tokens & food_words) and bool(tokens & cuisine_words)

def extract_location_fast(q, doc):
    """Optimized location extraction with parallel geocoding"""
    candidates = []
    
    # Collect all potential locations first
    for ent in doc.ents:
        if ent.label_ in {"GPE", "LOC", "FAC", "ORG"}:
            candidates.append((clean_name(ent.text), "spaCy NER"))
    
    # Preposition pattern
    m = PREPOSITION_PATTERN.search(q)
    if m:
        candidates.append((clean_name(m.group(1)), "preposition regex"))
    
    # Noun chunks with proper nouns
    for chunk in doc.noun_chunks:
        if any(tok.pos_ == "PROPN" for tok in chunk):
            candidates.append((clean_name(chunk.text), "noun chunk"))
    
    # Filter out non-locations and duplicates
    seen = set()
    filtered_candidates = []
    for cand, source in candidates:
        if cand not in seen and not is_probably_not_location(cand):
            seen.add(cand)
            filtered_candidates.append((cand, source))
    
    # Parallel geocoding with early success return
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_candidate = {
            executor.submit(geocode_point_cached, cand): (cand, source) 
            for cand, source in filtered_candidates[:3]  # Limit to top 3
        }
        
        for future in as_completed(future_to_candidate):
            try:
                coords = future.result()
                cand, source = future_to_candidate[future]
                return cand, source, coords
            except:
                continue
    
    return None, None, None

def apply_quick_patterns(P, q):
    """Apply quick pattern matching before expensive operations"""
    
    # Route queries
    m1 = ROUTE_PATTERN1.search(q)
    m2 = ROUTE_PATTERN2.search(q)
    
    if m1:
        mode, start, end, via = m1.groups()
        return handle_route_query(P, start, end, via, mode)
    elif m2:
        start, end = m2.groups()
        return handle_route_query(P, start, end, None, "walk")
    
    # Quick amenity patterns
    if COFFEE_PATTERN.search(q):
        return apply_coffee_filter(P, q)
    
    if PET_PATTERN.search(q):
        return apply_pet_filter(P, q)
    
    m = OPENING_PATTERN.search(q)
    if m:
        return apply_opening_hours_filter(P, q, m)
    
    if BABY_PATTERN.search(q):
        return apply_baby_changing_filter(P, q)
    
    m = NEAREST_PATTERN.search(q)
    if m:
        return apply_nearest_filter(P, q, m)
    
    m = WITHIN_PATTERN.search(q)
    if m:
        return apply_within_filter(P, q, m)
    
    m = WHERE_PATTERN.match(q)
    if m:
        P.update({"mode": "boundary_lookup", "place_name": clean_name(m.group(1).title())})
        return True
    
    m = PLACES_PATTERN.search(q)
    if m:
        return apply_places_near_filter(P, q, m)
    
    return False

def handle_route_query(P, start, end, via, mode):
    """Handle route queries with parallel geocoding"""
    def clean_route_text(text):
        text = clean_name(text)
        return re.sub(r"\s+(along|via|past|through|near|by)\b.*", "", text)
    
    locations = [(clean_route_text(start), 'start'), (clean_route_text(end), 'end')]
    if via:
        locations.append((clean_route_text(via), 'via'))
    
    results = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_loc = {executor.submit(geocode_point_cached, loc): (loc, key) for loc, key in locations}
        
        for future in as_completed(future_to_loc):
            try:
                coords = future.result()
                loc, key = future_to_loc[future]
                results[key] = coords
                print(f"📍 Route {key}: {loc} → {coords}")
            except Exception as e:
                print(f"⚠️ Failed geocoding {loc}: {e}")
                return False
    
    if 'start' in results and 'end' in results:
        P.update({
            "start_coords": results['start'],
            "end_coords": results['end'],
            "mode": "route_via" if 'via' in results else "route_check"
        })
        if 'via' in results:
            P["poi_coords"] = results['via']
        return True
    
    return False

def apply_coffee_filter(P, q):
    if P.get("center"):
        P.update({
            "tag_key": "amenity", "tag_value": "cafe",
            "mode": "generic", "radius": DEFAULT_RADIUS
        })
        return True
    return False

def apply_pet_filter(P, q):
    if P.get("center"):
        P.update({
            "tag_key": "tourism", "tag_value": "hotel",
            "pet_friendly": True, "mode": "generic", "radius": DEFAULT_RADIUS
        })
        return True
    return False

def apply_opening_hours_filter(P, q, match):
    if P.get("center"):
        hour = int(match.group(1))
        if match.group(2) and match.group(2).lower() == "pm" and hour < 12:
            hour += 12
        P["opening_hours_regex"] = f"{hour:02d}:"
        if re.search(r"librar", q, re.IGNORECASE):
            P.update({"tag_key": "amenity", "tag_value": "library"})
        if P.get("tag_key"):
            P.update({"mode": "generic", "radius": DEFAULT_RADIUS})
            return True
    return False

def apply_baby_changing_filter(P, q):
    if P.get("center"):
        P.update({
            "tag_key": "baby_changing", "tag_value": "yes",
            "mode": "generic", "radius": DEFAULT_RADIUS
        })
        return True
    return False

def apply_nearest_filter(P, q, match):
    if P.get("center"):
        poi = match.group(1).lower().rstrip("s")
        P.update({
            "tag_key": "amenity", "tag_value": poi,
            "mode": "generic", "radius": DEFAULT_RADIUS
        })
        return True
    return False

def apply_within_filter(P, q, match):
    dist, place = match.groups()
    try:
        P["center"] = geocode_point_cached(clean_name(place))
        P.update({"radius": int(dist) * 1000, "mode": "generic"})
        return True
    except:
        return False

def apply_places_near_filter(P, q, match):
    place_near = clean_name(match.group(1))
    try:
        P['center'] = geocode_point_cached(place_near)
        P.update({"mode": "generic", "radius": DEFAULT_RADIUS})
        P["place_name"] = place_near
        return True
    except:
        return False

def apply_cuisine_query(P, q):
    """Check for cuisine keywords"""
    for cuisine in CUISINE_KEYWORDS:
        if re.search(rf"\b{cuisine}\b", q, re.IGNORECASE) and P.get("center"):
            P.update({
                "tag_key": "cuisine", "tag_value": cuisine.lower(),
                "extra_tag": '["amenity"="restaurant"]',
                "mode": "generic", "radius": DEFAULT_RADIUS
            })
            return True
    return False

def apply_llama_fallback_fast(P, raw_q):
    """Fast LLaMA fallback with timeout"""
    llm = get_llm()
    if not llm:
        return False
    
    try:
        prompt = (
            "Extract location name:\n"
            f"Input: {raw_q}\nLocation:"
        )
        
        # Use shorter timeout and fewer tokens
        resp = llm(prompt, max_tokens=16, echo=False)
        fallback_loc = resp["choices"][0]["text"].strip()
        
        if fallback_loc:
            try:
                P['center'] = geocode_point_cached(fallback_loc)
                P['place_name'] = fallback_loc
                P["loc_source"] = "LLaMA fallback"
                P.update({"mode": "generic", "radius": DEFAULT_RADIUS})
                print(f"📍 LLaMA location: {fallback_loc} → geocoded")
                return True
            except:
                pass
    except Exception as e:
        print(f"⚠️ LLaMA fallback failed: {e}")
    
    return False

def parse_question_optimized(raw_q, lat=None, lon=None):
    """Optimized main parsing function"""
    start_time = time.time()
    
    # Step 1: Quick language detection and translation
    q = detect_and_translate_fast(raw_q)
    
    # Step 2: Initialize parameters
    P = {
        "tag_key": None, "tag_value": None, "mode": None, "center": None, 
        "bbox": None, "radius": None, "wheelchair_only": False, "pet_friendly": False,
        "opening_hours_regex": None, "start_coords": None, "end_coords": None, 
        "poi_coords": None, "place_name": None, "loc_source": None
    }
    
    # Step 3: Quick pattern matching (most queries should match here)
    if apply_quick_patterns(P, q):
        print(f"⚡ Quick pattern match in {time.time() - start_time:.2f}s")
        return P
    
    # Step 4: NLP processing only if needed
    doc = get_nlp()(q)
    
    # Step 5: Location extraction with parallel geocoding
    loc, source, coords = extract_location_fast(q, doc)
    if coords:
        P["center"] = coords
        P["place_name"] = loc
        P["loc_source"] = source
        print(f"📍 Location "{loc}" via {source}")
    
    # Step 6: Cuisine query check
    if apply_cuisine_query(P, q):
        print(f"⚡ Cuisine query in {time.time() - start_time:.2f}s")
        return P
    
    # Step 7: Tag guessing (only if we have a location)
    if P.get("center") and not P.get("tag_key"):
        words = [w.lower().strip(string.punctuation) for w in q.split()]
        candidates = get_close_matches(" ".join(words), TAG_MAP.keys(), n=1, cutoff=0.85)
        if candidates:
            k, v = TAG_MAP[candidates[0]]
            P.update({"tag_key": k, "tag_value": v, "mode": "generic", "radius": DEFAULT_RADIUS})
            print(f"🧠 Fuzzy tag: '{candidates[0]}' → [{k}={v}]")
    
    # Step 8: LLaMA fallback only for location queries
    if not P.get("center") and any(x in q.lower() for x in ["where", "near", "location"]):
        apply_llama_fallback_fast(P, raw_q)
    
    # Step 9: Coordinate fallback
    if not P.get("center"):
        if lat is not None and lon is not None:
            P["center"] = [lat, lon]
            P["loc_source"] = "user_coordinates"
        else:
            P["center"] = [27.9881, 86.9250]  # Everest fallback
            P["loc_source"] = "fallback_everest"
    
    # Step 10: Ensure mode and add fallback amenity filter
    if P.get("center") and not P.get("mode"):
        P["mode"] = "generic"
        P["radius"] = DEFAULT_RADIUS
    
    if P.get("mode") == "generic" and not P.get("tag_key"):
        P.update({"tag_key": "amenity", "tag_value": "~.", "radius": DEFAULT_RADIUS})
    
    print(f"⚡ Total processing time: {time.time() - start_time:.2f}s")
    return P

def build_overpass_query(P):
    """Build Overpass query with optimizations"""
    tag_f = f'["{P["tag_key"]}"="{P["tag_value"]}"]' if P.get("tag_key") else ""
    extra_tag = P.get("extra_tag", "")
    wh_f = '["wheelchair"="yes"]' if P.get("wheelchair_only") else ""
    pet_f = '["pets"="yes"]' if P.get("pet_friendly") else ""
    open_f = f'["opening_hours"~"{P.get("opening_hours_regex")}"]' if P.get("opening_hours_regex") else ""

    filters = f"{extra_tag}{tag_f}{wh_f}{pet_f}{open_f}"
    out_limit = "out center 15;"  # Reduced limit for faster queries

    if P.get("mode") == "boundary_lookup":
        name = P["place_name"]
        return (
            f'[out:json][timeout:15];'
            f'relation["boundary"="administrative"]["name"="{name}"]'
            '["admin_level"~"^(8|6|4)$"];out body;>;out skel qt;'
        )

    elif P.get("mode") in ("route_check", "route_via"):
        s_coords, e_coords = P["start_coords"], P["end_coords"]
        lat1, lon1 = s_coords
        lat2, lon2 = e_coords
        south = min(lat1, lat2) - 0.01
        north = max(lat1, lat2) + 0.01
        west = min(lon1, lon2) - 0.01
        east = max(lon1, lon2) + 0.01
        area = f"({south},{west},{north},{east})"

        return (
            "[out:json][timeout:15];(\n"
            f"  node{filters}{area};\n"
            f"  way{filters}{area};\n"
            f"  rel{filters}{area};\n"
            f"){out_limit}"
        )

    elif P.get("mode") == "generic":
        if P.get("bbox"):
            s, w, n, e = P["bbox"]
            area = f"({s},{w},{n},{e})"
        elif P.get("center") and P.get("radius"):
            lat, lon = P["center"]
            area = f"(around:{P['radius']},{lat},{lon})"
        else:
            raise ValueError("No location available for generic query.")

        if filters.strip() == "":
            raise ValueError("Generic query without filters would be too slow.")

        return (
            "[out:json][timeout:15];(\n"
            f"  node{filters}{area};\n"
            f"  way{filters}{area};\n"
            f"  rel{filters}{area};\n"
            f"){out_limit}"
        )

    raise ValueError(f"❌ Unknown mode: {P.get('mode')}")

# Replace the original parse_question function
parse_question = parse_question_optimized

if __name__ == "__main__":
    # Rest of the CLI code remains the same
    input_arg = sys.argv[1] if len(sys.argv) > 1 else "examples"
    
    if input_arg.lower() == "examples":
        examples = [
            "What is near Aula Magna right now?",
            "Are there any vegan restaurants near Aula Magna?",
            "What are the closest ATMs near Musée universitaire de Louvain?",
            "Show me cafes within 2 km of Amsterdam Central Station",
        ]
    else:
        if os.path.isfile(input_arg):
            with open(input_arg, "r", encoding="utf-8") as f:
                examples = [line.strip() for line in f if line.strip()]
        else:
            print(f"❌ Input '{input_arg}' is not valid.")
            sys.exit(1)

    for ex in examples:
        print("Question:", ex)
        start = time.time()
        params = parse_question(ex)
        try:
            result = build_overpass_query(params)
            print("Overpass query:")
            print(result)
        except Exception as e:
            print("❌", e)
        print(f"Total time: {time.time() - start:.2f}s")
        print()