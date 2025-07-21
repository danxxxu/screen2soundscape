# question_to_overpass.py
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
from geoparser import Geoparser
from utils.llama_singleton import get_llm
llm = get_llm()

import contextlib, io

# Initialize geoparser and spaCy
geoparser = Geoparser()
nlp = spacy.load("en_core_web_sm")

# Load OSM tag map (optional) and full OSM keys for fallback
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TAG_VALUES_PATH = os.path.join(BASE_DIR, "..", "osm_tags", "all_osm_tags.json")

TAG_MAP = {}
if os.path.isfile(TAG_VALUES_PATH):
    try:
        with open(TAG_VALUES_PATH, "r", encoding="utf-8") as f:
            tag_values = json.load(f)
        # tag_values is dict: key -> list of values
        for key, values in tag_values.items():
            for val in values:
                TAG_MAP[val] = (key, val)
    except Exception as e:
        print(f"⚠️ Could not load tag values cache: {e}")
else:
    print(f"⚠️ all_osm_tags.json not found at {TAG_VALUES_PATH}")

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

def clean_name(n):
    return n.strip().strip(string.punctuation)

def detect_and_translate(q):
    if detect(q) == "fr":
        try:
            t = GoogleTranslator(source="fr", target="en").translate(q)
            print(f"🌍 {q!r} → {t!r}")
            return t
        except:
            return q
    return q

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

        
def extract_locations_llama(text):
    prompt = (
        "Extract the names of specific places or locations mentioned in the sentence.\n\n"
        "Input: I want to find good sushi near Times Square.\nOutput: Times Square\n\n"
        "Input: Are there any vegan restaurants near Aula Magna?\nOutput: Aula Magna\n\n"
        "Input: Show me hostels near downtown Prague.\nOutput: downtown Prague\n\n"
        f"Input: {text}\nOutput:"
    )
    with contextlib.redirect_stdout(io.StringIO()):
        resp = llm(prompt, max_tokens=32, echo=False)
    return resp["choices"][0]["text"].strip()


def parse_question(raw_q):
    q = detect_and_translate(raw_q)
    doc = nlp(q)
    P = {
        "tag_key": None, "tag_value": None,
        "mode": None, "center": None, "bbox": None, "radius": None,
        "wheelchair_only": False, "pet_friendly": False,
        "opening_hours_regex": None,
        "start_coords": None, "end_coords": None, "poi_coords": None
    }
    # Early location extraction
    loc, source = extract_location(q, doc)
    if loc:
        try:
            P["center"] = geocode_point(loc)
            P["place_name"] = loc
            P["loc_source"] = source
            print(f"📍 Location “{loc}” detected via {source} → geocoded with Nominatim")
        except Exception as e:
            print(f"⚠️ Failed geocoding extracted location {loc}: {e}")

    
    # Cuisine-specific restaurants
    for cuisine in CUISINE_KEYWORDS:
        if re.search(rf"\b{cuisine}\b", q, re.IGNORECASE) and P.get("center"):
            P.update({
                "tag_key": "cuisine", "tag_value": cuisine.lower(),
                "extra_tag": '["amenity"="restaurant"]',
                "mode": "generic", "radius": DEFAULT_RADIUS
            })
            return P


    # Route queries
    # Full route query: "walk from A to B via C"
    m1 = re.search(r"\b(walk|drive|bike|bus|train)\b.*?from\s+(.+?)\s+to\s+(.+?)(?:\s+(?:past|via)\s+(.+))?$", q, re.IGNORECASE)

    # Simpler fallback: "from A to B"
    m2 = re.search(r"\bfrom\s+(.+?)\s+to\s+(.+)", q, re.IGNORECASE)

    if m1:
        mode, start, end, via = m1.groups()
    elif m2:
        start, end = m2.groups()
        mode = "walk"  # default if not specified
        via = None
    else:
        mode = start = end = via = None

    if start and end:
        def clean_route_endpoint(text):
            text = clean_name(text)
            text = re.sub(r"\s+(along|via|past|through|near|by)\b.*", "", text)
            return text

        try:
            start_clean = clean_route_endpoint(start)
            end_clean = clean_route_endpoint(end)
            P.update({
                "start_coords": geocode_point(start_clean),
                "end_coords": geocode_point(end_clean),
                "mode": "route_via" if via else "route_check"
            })
            print(f"📍 Route start: {start_clean} → {P['start_coords']}")
            print(f"📍 Route end: {end_clean} → {P['end_coords']}")
            if via:
                via_clean = clean_route_endpoint(via)
                P["poi_coords"] = geocode_point(via_clean)
                print(f"📍 Route via: {via_clean} → {P['poi_coords']}")
            return P
        except Exception as e:
            print(f"⚠️ Failed geocoding route components: {e}")


        # Heuristic cleaning: remove trailing fluff like "along the river"
        def clean_route_endpoint(text):
            text = clean_name(text)
            # Remove common trailing descriptors
            text = re.sub(r"\s+(along|via|past|through|near|by)\b.*", "", text)
            return text

        try:
            start_clean = clean_route_endpoint(start)
            end_clean = clean_route_endpoint(end)
            P.update({
                "start_coords": geocode_point(start_clean),
                "end_coords": geocode_point(end_clean),
                "mode": "route_via" if via else "route_check"
            })
            print(f"📍 Route start: {start_clean} → {P['start_coords']}")
            print(f"📍 Route end: {end_clean} → {P['end_coords']}")
            if via:
                via_clean = clean_route_endpoint(via)
                P["poi_coords"] = geocode_point(via_clean)
                print(f"📍 Route via: {via_clean} → {P['poi_coords']}")
            return P
        except Exception as e:
            print(f"⚠️ Failed geocoding route components: {e}")


    # Pet-friendly hotels
    if re.search(r"pet[- ]friendly", q, re.IGNORECASE) and P.get("center"):
        P.update({
            "tag_key": "tourism", "tag_value": "hotel",
            "pet_friendly": True,
            "mode": "generic", "radius": DEFAULT_RADIUS
        })
        return P

    # Opening-hours queries
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
            return P

    # Baby-changing stations
    if re.search(r"baby chang(?:ing)? stations?", q, re.IGNORECASE) and P.get("center"):
        P.update({
            "tag_key": "baby_changing", "tag_value": "yes",
            "mode": "generic", "radius": DEFAULT_RADIUS
        })
        return P

    # Nearest/closest POIs
    m = re.search(r"\b(?:nearest|closest)\s+(\w+)\b", q, re.IGNORECASE)
    if m and P.get("center"):
        poi = m.group(1).lower().rstrip("s")
        P.update({"tag_key": "amenity", "tag_value": poi, "mode": "generic", "radius": DEFAULT_RADIUS})
        return P

    # Within X km of Y
    m = re.search(r"within\s+(\d+)\s*km\s+of\s+(.+)", q, re.IGNORECASE)
    if m:
        dist, place = m.groups()
        try:
            P["center"] = geocode_point(clean_name(place))
            P.update({"radius": int(dist) * 1000, "mode": "generic"})
            return P
        except:
            pass

    # Boundary lookup (where is X)
    m = re.match(r"where\s+is\s+(.+)", q, re.IGNORECASE)
    if m:
        P.update({"mode": "boundary_lookup", "place_name": clean_name(m.group(1).title())})
        return P

    # Places near X
    m = re.search(r"places\s+near\s+(.+)", q, re.IGNORECASE)
    if m:
        place_near = clean_name(m.group(1))
        try:
            P['center'] = geocode_point(place_near)
            P.update({"mode": "generic", "radius": DEFAULT_RADIUS})
            P["place_name"] = place_near
            return P
        except:
            pass

    # Tag detection using full TAG_MAP
    found = False
    for key in sorted(TAG_MAP, key=lambda k: -len(k)):
        phrase = key.replace("_", " ")
        if phrase in q.lower():
            P['tag_key'], P['tag_value'] = TAG_MAP[key]
            found = True
            break
    if found and P.get("center"):
        if re.search(r"\bin\b", q, re.IGNORECASE) and not re.search(r"\bnear\b", q, re.IGNORECASE):
            try:
                P['bbox'] = geocode_bbox(P['place_name'])
            except:
                pass
        P.update({"mode": "generic", "radius": DEFAULT_RADIUS})
        return P

    # Llama fallback for location extraction
    if not P.get("center"):
        try:
            fallback_loc = extract_locations_llama(raw_q)
            try:
                P['center'] = geocode_point(fallback_loc)
            except:
                # Retry with "in [city]" variants or append common type
                retry_phrases = [
                    f"{fallback_loc} building", f"{fallback_loc} museum", f"{fallback_loc} location"
                ]
                for phrase in retry_phrases:
                    try:
                        P['center'] = geocode_point(phrase)
                        fallback_loc = phrase
                        print(f"📍 Retried LLaMA location as “{phrase}” → geocoded successfully")
                        break
                    except:
                        continue
            if P.get("center"):
                P['place_name'] = fallback_loc
                P["loc_source"] = "LLaMA fallback"
                P.update({"mode": "generic", "radius": DEFAULT_RADIUS})
                print(f"📍 Location “{fallback_loc}” extracted via LLaMA fallback → geocoded with Nominatim")
        except Exception as e:
            print(f"⚠️ LLaMA fallback failed: {e}")


    # Final generic fallback
    if P.get("center") and not P.get("mode"):
        P.update({"mode": "generic", "radius": DEFAULT_RADIUS})
    return P


def build_overpass_query(P):
    tag_f = f'["{P.get("tag_key")}"="{P.get("tag_value")}"]' if P.get("tag_key") else ""
    extra_tag = P.get("extra_tag", "")
    wh_f = '["wheelchair"="yes"]' if P.get("wheelchair_only") else ""
    pet_f = '["pets"="yes"]' if P.get("pet_friendly") else ""
    open_f = f'["opening_hours"~"{P.get("opening_hours_regex")}"]' if P.get("opening_hours_regex") else ""

    if P.get("mode") == "boundary_lookup":
        name = P["place_name"]
        return (
            f'[out:json][timeout:25];relation["boundary"="administrative"]["name"="{name}"]'
            '["admin_level"~"^(8|6|4)$"];out body;>;out skel qt;'
        )

    if P.get("mode") == "generic":
        if P.get("bbox"):
            s, w2, n2, e = P["bbox"]
            area = f"({s},{w2},{n2},{e})"
        else:
            lat, lon = P["center"]
            area = f"(around:{P['radius']},{lat},{lon})"
        return (
            "[out:json][timeout:25];(\n"
            f"  node{tag_f}{wh_f}{pet_f}{open_f}{area};\n"
            f"  way{tag_f}{wh_f}{pet_f}{open_f}{area};\n"
            f"  rel{tag_f}{wh_f}{pet_f}{open_f}{area};\n"
            ");out center;"
        )

    if P.get("mode") in ("route_check", "route_via"):
        s_coords, e_coords = P["start_coords"], P["end_coords"]
        lat1, lon1 = s_coords
        lat2, lon2 = e_coords
        south = min(lat1, lat2) - 0.01
        north = max(lat1, lat2) + 0.01
        west = min(lon1, lon2) - 0.01
        east = max(lon1, lon2) + 0.01
        return (
            "[out:json][timeout:25];(\n"
            f"  node{extra_tag}{tag_f}{wh_f}{pet_f}{open_f}{area};\n"
            f"  way{extra_tag}{tag_f}{wh_f}{pet_f}{open_f}{area};\n"
            f"  rel{extra_tag}{tag_f}{wh_f}{pet_f}{open_f}{area};\n"
            ");out center;"
        )


    raise ValueError("No location (bbox or center) could be resolved.")

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
