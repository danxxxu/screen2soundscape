# question_to_overpass.py
import os
import re
import sys
import json
import string
import contextlib, io
import time
from difflib import get_close_matches
from geopy.geocoders import Nominatim
from langdetect import detect
from deep_translator import GoogleTranslator
from geoparser import Geoparser
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache


# =============== Global NLP + LLM ===============

@lru_cache()
def get_llm():
    from utils.llama_singleton import get_llm as load_llm
    return load_llm()


@lru_cache()
def get_nlp():
    import spacy
    return spacy.load("en_core_web_sm")

llm = get_llm()
nlp = get_nlp()
geoparser = Geoparser()



# =============== Geocoding Cache ===============
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
    geo = Nominatim(user_agent="osmv", timeout=5)
    place = geo.geocode(loc, exactly_one=True)
    if not place:
        raise ValueError(f"Could not geocode: {loc}")
    coords = (place.latitude, place.longitude)
    GEOCODE_CACHE[key] = coords
    save_geocode_cache()
    return coords

# =============== Helpers ===============
def clean_name(n):
    return n.strip().strip(string.punctuation)

def detect_and_translate(q):
    try:
        lang = detect(q)
        if lang != "en":
            t = GoogleTranslator(source=lang, target="en").translate(q)
            print(f"🌍 {lang} → EN: {q!r} → {t!r}")
            return t
    except Exception as e:
        print(f"⚠️ Lang detect fail: {e}")
    return q

def extract_locations_llama(text):
    prompt = (
        "Extract the names of specific places or locations mentioned in the sentence.\n\n"
        "Input: I want sushi near Times Square.\nOutput: Times Square\n"
        f"Input: {text}\nOutput:"
    )
    with contextlib.redirect_stdout(io.StringIO()):
        resp = llm(prompt, max_tokens=32, echo=False)
    return resp["choices"][0]["text"].strip()


# Load OSM tag map (optional) and full OSM keys for fallback
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TAG_VALUES_PATH = os.path.join(BASE_DIR, "..", "osm_tags", "all_osm_tags.json")

# TAG_MAP = {}
# if os.path.isfile(TAG_VALUES_PATH):
#     try:
#         with open(TAG_VALUES_PATH, "r", encoding="utf-8") as f:
#             tag_values = json.load(f)
#         # tag_values is dict: key -> list of values
#         for key, values in tag_values.items():
#             for val in values:
#                 TAG_MAP[val] = (key, val)
#     except Exception as e:
#         print(f"⚠️ Could not load tag values cache: {e}")
# else:
#     print(f"⚠️ all_osm_tags.json not found at {TAG_VALUES_PATH}")

STOPWORDS = {"is","a","an","the","in","on","at","of","to","from","with","for","near","by"}
DEFAULT_RADIUS = 1000
CUISINE_KEYWORDS = [
    "chinese", "italian", "japanese", "indian", "thai", "mexican", "greek", "french",
    "vietnamese", "turkish", "korean", "lebanese", "ethiopian", "burger", "pizza",
    "vegetarian", "vegan", "halal", "kosher"
]



def load_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


@lru_cache(maxsize=200)
def geocode_point(loc):
    geo = Nominatim(user_agent="osmv", timeout=5)
    place = geo.geocode(loc, exactly_one=True)
    if not place:
        raise ValueError(f"Could not geocode: {loc}")
    return place.latitude, place.longitude


def geocode_bbox(loc):
    geo = Nominatim(user_agent="osmv", timeout=5)
    place = geo.geocode(loc, exactly_one=True)
    if not place:
        raise ValueError(f"Could not geocode: {loc}")
    south, north, west, east = map(float, place.raw["boundingbox"])
    return south, west, north, east


def is_probably_not_location(text):
    food_words = {"restaurant", "cafe", "bar", "pizzeria", "bakery"}
    cuisine_words = set(CUISINE_KEYWORDS)
    tokens = set(text.lower().split())
    return bool(tokens & food_words) and bool(tokens & cuisine_words)

def extract_location(q, doc):
    tried = set()

    def try_geo(candidate, source):
        cand = clean_name(candidate)
        if cand in tried or is_probably_not_location(cand):
            return None, None
        tried.add(cand)
        try:
            _ = geocode_point(cand)
            return cand, source
        except:
            return None, None

    # Named entities
    for ent in doc.ents:
        if ent.label_ in {"GPE", "LOC", "FAC", "ORG"}:
            res, source = try_geo(ent.text, "spaCy NER")
            if res:
                return res, source

    # Preposition tail
    m = re.search(r"(?:in|near|around|by)\s+(.+)", q, re.IGNORECASE)
    if m:
        res, source = try_geo(m.group(1), "preposition regex")
        if res:
            return res, source

    # Noun chunks
    for chunk in doc.noun_chunks:
        if any(tok.pos_ == "PROPN" for tok in chunk):
            res, source = try_geo(chunk.text, "noun chunk")
            if res:
                return res, source
    return None, None

def try_geocode_variants(name):
    variants = [name] + [name + suffix for suffix in [" building", " museum", " location"]]
    for variant in variants:
        try:
            return variant, geocode_point(variant)
        except:
            continue
    return None, None


def apply_location_extraction(P, q, doc):
    loc, source = extract_location(q, doc)
    if loc:
        try:
            P["center"] = geocode_point(loc)
            P["place_name"] = loc
            P["loc_source"] = source
            print(f"📍 Location “{loc}” detected via {source} → geocoded with Nominatim")
        except Exception as e:
            print(f"⚠️ Failed geocoding extracted location {loc}: {e}")


def apply_cuisine_query(P, q):
    for cuisine in CUISINE_KEYWORDS:
        if re.search(rf"\b{cuisine}\b", q, re.IGNORECASE) and P.get("center"):
            P.update({
                "tag_key": "cuisine", "tag_value": cuisine.lower(),
                "extra_tag": '["amenity"="restaurant"]',
                "mode": "generic", "radius": DEFAULT_RADIUS
            })
            return True
    return False


def apply_route_query(P, q):
    m1 = re.search(r"\b(walk|drive|bike|bus|train)\b.*?from\s+(.+?)\s+to\s+(.+?)(?:\s+(?:past|via)\s+(.+))?$", q, re.IGNORECASE)
    m2 = re.search(r"\bfrom\s+(.+?)\s+to\s+(.+)", q, re.IGNORECASE)

    if m1:
        mode, start, end, via = m1.groups()
    elif m2:
        start, end = m2.groups()
        mode = "walk"
        via = None
    else:
        return False

    def clean(text):
        text = clean_name(text)
        return re.sub(r"\s+(along|via|past|through|near|by)\b.*", "", text)

    try:
        start_clean = clean(start)
        end_clean = clean(end)
        P.update({
            "start_coords": geocode_point(start_clean),
            "end_coords": geocode_point(end_clean),
            "mode": "route_via" if via else "route_check"
        })
        print(f"📍 Route start: {start_clean} → {P['start_coords']}")
        print(f"📍 Route end: {end_clean} → {P['end_coords']}")
        if via:
            via_clean = clean(via)
            P["poi_coords"] = geocode_point(via_clean)
            print(f"📍 Route via: {via_clean} → {P['poi_coords']}")
        return True
    except Exception as e:
        print(f"⚠️ Failed geocoding route components: {e}")
        return False


def apply_special_filters(P, q):
    if re.search(r"coffee\s+(shop|place|bar|café|house)", q, re.IGNORECASE) and P.get("center"):
        P.update({
            "tag_key": "amenity",
            "tag_value": "cafe",
            "mode": "generic",
            "radius": DEFAULT_RADIUS
        })
        return True

    if re.search(r"pet[- ]friendly", q, re.IGNORECASE) and P.get("center"):
        P.update({
            "tag_key": "tourism", "tag_value": "hotel",
            "pet_friendly": True,
            "mode": "generic", "radius": DEFAULT_RADIUS
        })
        return True

    m = re.search(r"open(?:ing)? past (\d+)(am|pm)?", q, re.IGNORECASE)
    if m and P.get("center"):
        hour = int(m.group(1))
        if m.group(2) and m.group(2).lower() == "pm" and hour < 12:
            hour += 12
        P["opening_hours_regex"] = f"{hour:02d}:"
        if re.search(r"librar", q, re.IGNORECASE):
            P.update({"tag_key": "amenity", "tag_value": "library"})
        if P.get("tag_key"):
            P.update({"mode": "generic", "radius": DEFAULT_RADIUS})
            return True

    if re.search(r"baby chang(?:ing)? stations?", q, re.IGNORECASE) and P.get("center"):
        P.update({
            "tag_key": "baby_changing", "tag_value": "yes",
            "mode": "generic", "radius": DEFAULT_RADIUS
        })
        return True

    m = re.search(r"\b(?:nearest|closest)\s+(\w+)\b", q, re.IGNORECASE)
    if m and P.get("center"):
        poi = m.group(1).lower().rstrip("s")
        P.update({"tag_key": "amenity", "tag_value": poi, "mode": "generic", "radius": DEFAULT_RADIUS})
        return True

    m = re.search(r"within\s+(\d+)\s*km\s+of\s+(.+)", q, re.IGNORECASE)
    if m:
        dist, place = m.groups()
        try:
            P["center"] = geocode_point(clean_name(place))
            P.update({"radius": int(dist) * 1000, "mode": "generic"})
            return True
        except:
            return False

    m = re.match(r"where\s+is\s+(.+)", q, re.IGNORECASE)
    if m:
        P.update({"mode": "boundary_lookup", "place_name": clean_name(m.group(1).title())})
        return True

    m = re.search(r"places\s+near\s+(.+)", q, re.IGNORECASE)
    if m:
        place_near = clean_name(m.group(1))
        try:
            P['center'] = geocode_point(place_near)
            P.update({"mode": "generic", "radius": DEFAULT_RADIUS})
            P["place_name"] = place_near
            return True
        except:
            return False

    return False


# =============== Main Parse Function ===============
def parse_question(raw_q, lat=None, lon=None):
    t0 = time.time()
    q = detect_and_translate(raw_q)
    doc = nlp(q)

    P = {
        "tag_key": None, "tag_value": None,
        "mode": None, "center": None, "radius": 1000,
        "place_name": None, "loc_source": None
    }

    # === Step 1: Try spaCy NER + regex ===
    candidates = [ent.text for ent in doc.ents if ent.label_ in {"GPE", "LOC", "FAC", "ORG"}]
    regex_match = re.search(r"(?:in|near|around|by)\s+(.+)", q, re.IGNORECASE)
    if regex_match:
        candidates.append(regex_match.group(1))

    # Try geocoding up to 3 candidate locations
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

    # === Step 2: Try LLaMA fallback if NER/regex failed ===
    if not P["center"] and any(kw in q.lower() for kw in ["where", "near", "location", "places", "find"]):
        try:
            fallback_loc = extract_locations_llama(raw_q)
            try:
                coords = geocode_point_cached(fallback_loc)
                P["center"] = coords
                P["place_name"] = fallback_loc
                P["loc_source"] = "LLaMA"
                print(f"🤖 LLaMA fallback: {fallback_loc} → {coords}")
            except:
                for suffix in [" building", " museum", " location"]:
                    retry = fallback_loc + suffix
                    try:
                        coords = geocode_point_cached(retry)
                        P["center"] = coords
                        P["place_name"] = retry
                        P["loc_source"] = "LLaMA (retry)"
                        print(f"📍 Retried LLaMA location as “{retry}” → geocoded successfully")
                        break
                    except:
                        continue
        except Exception as e:
            print(f"⚠️ LLaMA extraction failed: {e}")

    # === Step 3: Use provided lat/lon if available ===
    if not P["center"] and lat is not None and lon is not None:
        P["center"] = (lat, lon)
        P["loc_source"] = "fallback_coords"
        P["place_name"] = "user_location"
        print(f"📍 Using fallback coordinates: ({lat}, {lon})")

    # === Step 4: Final fallback to Mount Everest ===
    if not P["center"]:
        P["center"] = (27.9881, 86.9250)
        P["place_name"] = "Mount Everest"
        P["loc_source"] = "fallback_everest"
        print("📍 Default to Mount Everest")

    P["mode"] = "generic"
    print(f"🕒 parse_question took {time.time() - t0:.2f}s")
    return P


from OSMPythonTools.overpass import Overpass, overpassQueryBuilder
from OSMPythonTools.nominatim import Nominatim as OSMToolsNominatim

_osm_overpass = Overpass()
_osm_nominatim = OSMToolsNominatim()

def build_overpass_query(P):
    if P.get("mode") == "boundary_lookup":
        area_name = P["place_name"]
        return _osm_overpass.query(
            f'relation["boundary"="administrative"]["name"="{area_name}"]["admin_level"~"^(8|6|4)$"];out body;>;out skel qt;'
        )

    if P.get("mode") in ("generic", "route_check", "route_via"):
        if P.get("bbox"):
            # Fallback to old manual QL for bounding box use
            raise NotImplementedError("BBox queries not yet supported via OSMPythonTools")

    area_id = None
    query = None

    if P.get("place_name") not in (None, "user_location"):
        try:
            area_id = _osm_nominatim.query(P["place_name"]).areaId()
        except Exception as e:
            print(f"⚠️ Failed to get areaId for {P['place_name']}: {e}")

    selector_parts = []
    if P.get("tag_key") and P.get("tag_value"):
        selector_parts.append(f'"{P["tag_key"]}"="{P["tag_value"]}"')
    if P.get("wheelchair_only"):
        selector_parts.append('"wheelchair"="yes"')
    if P.get("pet_friendly"):
        selector_parts.append('"pets"="yes"')
    if P.get("opening_hours_regex"):
        selector_parts.append(f'"opening_hours"~"{P["opening_hours_regex"]}"')

    selector = " and ".join(selector_parts) if selector_parts else None

    if area_id:
        query = overpassQueryBuilder(
            area=area_id,
            elementType=["node", "way", "relation"],
            selector=selector,
            out="body",
            includeGeometry=False
        )
    else:
        # fallback to around query
        if not P.get("center") or not P.get("radius"):
            raise ValueError("❌ Cannot build query: no areaId or coordinates.")
        lat, lon = P["center"]
        radius = P["radius"]
        query = overpassQueryBuilder(
            bbox=(lat, lon, radius),
            elementType=["node", "way", "relation"],
            selector=selector,
            out="body",
            includeGeometry=False
        )

    return _osm_overpass.query(query)


    raise ValueError(f"❌ Unsupported mode for OSMPythonTools: {P.get('mode')}")

# Command-line interface
if __name__ == "__main__":
    input_arg = sys.argv[1] if len(sys.argv) > 1 else "examples"
    output_lines = []
    save_to_file = False
    output_filename = None

    if input_arg.lower() == "examples":
        examples = [
            "What is near Aula Magna right now?",
            "Are there any vegan restaurants near Aula Magna?",
            "What are the closest ATMs near Musée universitaire de Louvain?",
            "Which beaches near Lisbon are wheelchair accessible?",
            "Are there baby changing stations in Musée universitaire de Louvain?",
            "Show me cafes within 2 km of Amsterdam Central Station",
            "Find restaurants in Berlin",
            "Look for places near Eiffel Tower",
            "Where is Lyon?",
            "Is MOMA wheelchair accessible?",
            "What historical sites are near the Colosseum?",
            "Show me UNESCO World Heritage sites in India.",
            "Where can I find live jazz bars in New Orleans?",
            "What’s a good area for street food in Bangkok?",
            "Where can I find hostels near downtown Prague?",
            "Are there pet-friendly hotels in Zurich?",
            "Show me all libraries open past 8 PM in central London.",
            "Can I drive from Marseille to Nice via Avignon?",
            "Puis-je conduire de Marseille à Nice via Avignon ?",
            "How can I bike from Stanford University to Googleplex?",
            "What's the fastest public transport route from Heathrow to Covent Garden?",
            "Can I walk from the Louvre to Notre-Dame along the river?",
        ]
    elif os.path.isfile(input_arg):
        examples = load_text(input_arg)
        save_to_file = True
        base_name = os.path.splitext(os.path.basename(input_arg))[0]
        os.makedirs("overpass_query", exist_ok=True)
        output_filename = os.path.join("overpass_query", f"{base_name}_overpass.txt")
    else:
        print(f"❌ Input '{input_arg}' is not a valid file or 'examples'.")
        sys.exit(1)

    for ex in examples:
        print("Question:", ex)
        params = parse_question(ex)
        
        try:
            result = build_overpass_query(params)
            print("Overpass query or result:")
            print(result)
            if save_to_file:
                output_lines.append(f"# {ex}\n{result}\n")
        except Exception as e:
            print("❌", e)
        print()

    if save_to_file and output_filename:
        with open(output_filename, "w", encoding="utf-8") as out_file:
            out_file.writelines(line if line.endswith("\n") else line + "\n" for line in output_lines)
        print(f"✅ Overpass queries saved to: {output_filename}")