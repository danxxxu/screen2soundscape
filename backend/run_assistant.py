# backend/run_assistant.py
import os
import re
import time
import json
import argparse
import warnings
import logging
import datetime
import pathlib

# Quiet some libs
os.environ["TORCH_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
os.environ["TF_CPP_MIN_VLOG_LEVEL"] = "3"
warnings.filterwarnings("ignore")
logging.getLogger("tensorflow").setLevel(logging.ERROR)

from utils.bitnet_singleton import stream_chat
from utils.transcribe import record_and_transcribe
from utils.speak_piper import speak, find_best_piper_model, MODEL_DIR

# ---- OSM utils ----
from utils.osm_tags import find_osm_tags
from utils.overpass_helpers import top_k_nearest
from utils.question_to_overpass import parse_question, build_overpass_query
from utils.overpass_to_osm_bitnet import (
    run_overpass_query,
    summarize_results,
    summarize_route,
    generate_overpass_query,
)
from deep_translator import GoogleTranslator
import requests


# ---------- Language detection ----------
def detect_language(text: str) -> str:
    code = None
    try:
        from langdetect import detect, DetectorFactory
        DetectorFactory.seed = 0
        code = detect(text)
    except Exception:
        s = text or ""
        if any("\u3040" <= ch <= "\u30ff" or "\u31f0" <= ch <= "\u31ff" for ch in s):
            return "ja"
        if any("\u4e00" <= ch <= "\u9fff" for ch in s):
            return "zh"
        if any("\uac00" <= ch <= "\ud7af" for ch in s):
            return "ko"
        if any("\u0600" <= ch <= "\u06ff" or "\u0750" <= ch <= "\u077f" for ch in s):
            return "ar"
        if any("\u0590" <= ch <= "\u05ff" for ch in s):
            return "he"
        if any("\u0370" <= ch <= "\u03ff" for ch in s):
            return "el"
        if any("\u0400" <= ch <= "\u04FF" for ch in s):
            return "ru"
        if any("\u0E00" <= ch <= "\u0E7F" for ch in s):
            return "th"
        if any(ch in "ñáéíóúü" for ch in s.lower()):
            return "es"
        if any(ch in "çéàèùâêîôûëï" for ch in s.lower()):
            return "fr"
        if any(ch in "äöüß" for ch in s.lower()):
            return "de"
        if any(ch in "åäö" for ch in s.lower()):
            return "sv"
        if any(ch in "øæå" for ch in s.lower()):
            return "da"
    return code or "en"


def get_question(text=None, text_file=None):
    if text:
        return text.strip()
    elif text_file and os.path.isfile(text_file):
        with open(text_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    else:
        return record_and_transcribe()


# ---------- Intent classifier (multilingual) ----------
_NEARBY_WORDS_EN = r"(near( me|by)?|closest|around|in the area|near to|near\s+me)"
_ROUTE_WORDS_EN  = r"(route|directions|navigate|how to get|way to|get to|walk|bike|drive|bus|tram|subway|metro)"
_OSM_TERMS_EN    = r"(amenity|highway|shop|leisure|tourism|public\s*transport|osm|overpass|bbox|coordinates?)"
_COORDS_RE       = re.compile(r"\b(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)\b")
# Listing / brand cues (general info, not map)
_LISTING_CUES_EN = re.compile(r"\b(list|names?|examples?|give me|show me)\b", re.IGNORECASE)
_BRAND_CUES_EN   = re.compile(r"\b(brands?|chains?)\b", re.IGNORECASE)

# A simple locality cue: "in <Place Name>" (e.g., "in Utrecht")
_IN_PLACE_EN = re.compile(
    r"\b(in|within|around)\s+(the\s+)?([A-Z][\w\-]+(?:\s+[A-Z][\w\-]+)*)\b",
    re.IGNORECASE
)

# NEW: strong “general” cues — if present, we avoid OSM unless there are explicit map cues
_GENERAL_CUES_EN = re.compile(
    r"\b(explain|what is|what's|difference between|compare|how does|why|in simple terms|pros and cons)\b",
    re.IGNORECASE,
)


def _to_english(text: str) -> str:
    try:
        lang = detect_language(text)
        if lang and str(lang).lower().startswith("en"):
            return text
        translated = GoogleTranslator(source="auto", target="en").translate(text)
        return translated or text
    except Exception:
        return text


def is_osm_query(question: str) -> bool:
    q_orig = (question or "").strip()
    q_en = _to_english(q_orig)

    looks_general = bool(_GENERAL_CUES_EN.search(q_en))
    has_nearby_or_route = bool(re.search(_NEARBY_WORDS_EN, q_en) or re.search(_ROUTE_WORDS_EN, q_en))
    has_coords_in_text  = bool(_COORDS_RE.search(q_en))
    has_osm_words       = bool(re.search(_OSM_TERMS_EN, q_en))
    tags_detected       = bool(find_osm_tags(q_orig) or find_osm_tags(q_en))
    in_named_place      = bool(_IN_PLACE_EN.search(q_en))

    wants_list_or_brand = bool(_LISTING_CUES_EN.search(q_en) or _BRAND_CUES_EN.search(q_en))

    # If it looks like a general/explanatory request and lacks strong locality cues, keep it out of OSM.
    if looks_general and not (has_nearby_or_route or has_coords_in_text or has_osm_words or in_named_place or tags_detected):
        return False

    # If user asks for a list/brands and there's NO locality cue, treat as general knowledge, not map.
    if wants_list_or_brand and not (has_nearby_or_route or has_coords_in_text or has_osm_words or in_named_place):
        return False

    # Mentioning an OSM category/tag alone is NOT enough; require locality or OSM/coords/bbox/“in <place>”
    if tags_detected and not (has_nearby_or_route or has_coords_in_text or has_osm_words or in_named_place):
        return False

    # Otherwise, OSM intent if any strong locality cue is present.
    return any([has_nearby_or_route, has_coords_in_text, has_osm_words, in_named_place])


# ---------- Optional: OSRM routing ----------
def get_directions(start, end, mode="walk"):
    profile = {"walk": "foot", "drive": "car", "bike": "bike"}.get(mode.lower(), "foot")
    url = f"https://router.project-osrm.org/route/v1/{profile}/{start[1]},{start[0]};{end[1]},{end[0]}"
    params = {"overview": "simplified", "geometries": "geojson", "steps": "true"}
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()


# ---------- Handlers ----------
def run_general(
    question,
    language,
    speaker,
    speed,
    output_mode,
    system_prompt,
    max_new_tokens,
    temperature,
    top_p,
    ctx,
    threads,
    bitnet_bin,
    bitnet_model,
    extra_args,
):
    """
    BitNet is run strictly in English:
      - translate the user's question -> English
      - force an English system prompt
      - generate English answer with BitNet
      - translate the English answer -> user's original language (for TTS/print)
    """
    # 1) Detect target/output language (the user's original language)
    target_lang = (language or "en").lower()

    # 2) Translate the incoming question to English for BitNet
    question_en = _to_english(question)

    # 3) Force an English system prompt regardless of CLI --system-prompt
    system_prompt_en = (
        "You are a helpful assistant. "
        "Always answer in clear, concise English, even if the user's question is in another language."
    )

    # 4) Build messages for BitNet (English only)
    messages = [
        {"role": "system", "content": system_prompt_en},
        {"role": "user", "content": question_en},
    ]

    # 5) Run BitNet, collect the full English response
    collected = []
    try:
        gen = stream_chat(
            messages,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            ctx=ctx,
            threads=threads,
            bitnet_bin=bitnet_bin,
            bitnet_model=bitnet_model,
            extra_args=extra_args,
        )

        # We still print chunks live, but we do NOT TTS while streaming
        # because we need the full text to translate first.
        print("🔊 Generating (BitNet in EN)...\n")
        for chunk in gen:
            print(chunk, end="", flush=True)  # English chunks to console
            collected.append(chunk)
        print()

        response_en = "".join(collected).strip()

        # 6) Translate the English answer back to the user's language (if not English)
        response_out = response_en
        if not target_lang.startswith("en"):
            try:
                response_out = GoogleTranslator(source="en", target=target_lang).translate(response_en)
            except Exception as e:
                print(f"⚠️ Back-translation failed ({target_lang}): {e}")
                response_out = response_en  # fall back to English

        # 7) Speak in the user's language
        model_path_tts = find_best_piper_model(MODEL_DIR, language, speaker)
        return speak(
            response_out,
            language=language,
            speaker_key=model_path_tts,
            speed=speed,
            output_mode=output_mode,  # "stream" or "file", as requested
        )
    except Exception as e:
        print(f"\n❌ BitNet inference failed: {e}")
        return ""

def run_osm(
    question,
    language,
    speaker,
    speed,
    output_mode,
    lat=None,
    lon=None,
    radius_m=1000,     # NEW: CLI-tunable
    out_limit=300,     # NEW: Overpass row cap
    k_nearest=5,       # NEW: how many to report
):
    """
    Robust OSM handler:
    - parse question → set radius/out_limit from CLI
    - build Overpass (with guardrails and 'out tags center qt')
    - run Overpass
    - pick top-K nearest by great-circle distance
    - speak concise summary
    """
    # ---- Parse → params ----
    params = parse_question(question, lat=lat, lon=lon)
    # override default radius / cap from CLI
    try:
        params["radius"] = int(radius_m)
    except Exception:
        params["radius"] = params.get("radius", 1000)
    try:
        params["out_limit"] = int(out_limit)
    except Exception:
        params["out_limit"] = 300

    # ---- Build query (deterministic builder first) ----
    overpass_query = ""
    try:
        overpass_query = build_overpass_query(params)
        print("🧭 Overpass query (deterministic):")
        print(overpass_query)
    except Exception as e:
        print(f"⚠️ build_overpass_query failed: {e}")
        # If it still looks like a map request, try BitNet fallback
        try:
            clat, clon = None, None
            if params.get("center"):
                clat, clon = params["center"]
            elif lat is not None and lon is not None:
                clat, clon = (lat, lon)
            overpass_query = generate_overpass_query(
                question,
                lat=clat,
                lon=clon,
                radius=params.get("radius", 2000),
            )
            print("🧭 Overpass query (BitNet fallback):")
            print(overpass_query)
        except Exception as e2:
            msg = f"❌ Failed to generate Overpass query: {e2}"
            print(msg)
            model_path = find_best_piper_model(MODEL_DIR, language, speaker)
            return speak(msg, language=language, speaker_key=model_path, speed=speed, output_mode=output_mode)

    # ---- Run Overpass ----
    try:
        results = run_overpass_query(overpass_query)
    except Exception as e:
        msg = f"Sorry, I couldn't run the map search ({e})."
        print(msg)
        model_path = find_best_piper_model(MODEL_DIR, language, speaker)
        return speak(msg, language=language, speaker_key=model_path, speed=speed, output_mode=output_mode)

    # After you fetch results in run_osm()
    elements = results.get("elements", [])
    
    if not elements:
        # widen radius
        params["radius"] = max(params.get("radius", 500), 1500)
        overpass_query = build_overpass_query(params)
        results = run_overpass_query(overpass_query)
        elements = results.get("elements", [])
    
    if not elements and P.get("tag_key") == "shop":
        # temporarily broaden to supermarket|convenience
        lat, lon = params["center"]
        radius = params.get("radius", 1500)
        out_limit = params.get("out_limit", 300)
        overpass_query = (
            f'[out:json][timeout:25];'
            f'(nwr(around:{radius},{lat},{lon})["shop"~"^(supermarket|convenience)$"];);'
            f'out tags center qt {out_limit};'
        )
        results = run_overpass_query(overpass_query)
        elements = results.get("elements", [])

    print(f"✅ Overpass returned {len(elements)} element(s).")

    # ---- Compute nearest K (fast heap), requires 'center' coords and 'out ... center' ----
    if not params.get("center"):
        msg = "I couldn't determine your location to rank by distance."
        print(msg)
        model_path = find_best_piper_model(MODEL_DIR, language, speaker)
        return speak(msg, language=language, speaker_key=model_path, speed=speed, output_mode=output_mode)

    lat0, lon0 = params["center"]
    nearest = top_k_nearest(elements, lat0, lon0, k=k_nearest)

    # ---- Build concise spoken summary ----
    if not nearest:
        spoken_text = "I didn't find any matching places nearby."
    else:
        lines = []
        for i, item in enumerate(nearest, 1):
            tags = item.get("tags", {}) or {}
            name = tags.get("name") or "Unnamed"
            dist = int(round(item.get("distance_m", 0)))
            kind = None
            if "amenity" in tags:
                kind = tags["amenity"]
            elif "shop" in tags:
                kind = tags["shop"]
            kind_str = f" ({kind})" if kind else ""
            lines.append(f"{i}. {name}{kind_str} — {dist} meters away.")
        spoken_text = "Here are the closest places: " + " ".join(lines)

    print(spoken_text, flush=True)


    # ---- TTS ----
    model_path = find_best_piper_model(MODEL_DIR, language, speaker)
    return speak(
        spoken_text,
        language=language,
        speaker_key=model_path,
        speed=speed,
        output_mode=output_mode,  # "file" or "stream"
    )


# Add near the other intent cues:
_LOC_GENERAL_CUES_EN = re.compile(
    r"""
    (
      where\s+am\s+i
      | where\s+exactly\s+am\s+i
      | what('?s|[\s]is)?\s+(this\s+)?(place|location|area)
      | what\s+(neighbo(u)?rhood|district)\s+am\s+i\s+in
      | what('?s|[\s]is)?\s+(this|my)\s+(neighbo(u)?rhood|area|district)(\s+called)?
      | tell\s+me\s+(more\s+)?about\s+(
            here
          | this\s+(place|location|area|neighbo(u)?rhood|district)
          | my\s+(area|neighbo(u)?rhood|district)
          | the\s+(neighbo(u)?rhood|area)\s+(that\s+)?i\s+am\s+in
        )
      | history\s+of\s+(this|here|this\s+place|this\s+location|this\s+area|this\s+neighbo(u)?rhood)
      | what\s+happened\s+here
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def is_location_general(question: str, lat=None, lon=None) -> bool:
    q_orig = (question or "").strip()
    q_en = _to_english(q_orig)

    has_loc_general = bool(_LOC_GENERAL_CUES_EN.search(q_en))
    has_osmish = bool(
        re.search(_NEARBY_WORDS_EN, q_en) or
        re.search(_ROUTE_WORDS_EN, q_en) or
        re.search(_OSM_TERMS_EN, q_en)
    )
    if not has_loc_general or has_osmish:
        return False

    if (lat is not None and lon is not None):
        return True
    if _COORDS_RE.search(q_en):
        return True

    return False



def run_place_info(question, language, speaker, speed, output_mode, lat=None, lon=None, radius_m=500):
    # Resolve coordinates from CLI or explicit coordinates in the text (no LLM, no parse_question)
    coords = None
    if lat is not None and lon is not None:
        coords = (lat, lon)
    else:
        m = _COORDS_RE.search(_to_english(question) or "")
        if m:
            coords = (float(m.group(1)), float(m.group(2)))

    # If no coordinates are available, fall back to general mode (don’t guess Everest)
    if coords is None:
        return run_general(
            question=question,
            language=language,
            speaker=speaker,
            speed=speed,
            output_mode=output_mode,
            system_prompt="You are a helpful AI assistant for everyday tasks, please always respond in the same language as the question",
            max_new_tokens=256,
            temperature=0.7,
            top_p=0.95,
            ctx=4096,
            threads=None,
            bitnet_bin="bitnet",
            bitnet_model="~/screen2soundscape/backend/models/microsoft/bitnet-b1.58-2B-4T-gguf/ggml-model-q4_0.gguf",
            extra_args=None,
        )

    lat_c, lon_c = coords

    # Reverse geocode (respect user language)
    try:
        headers = {"User-Agent": "screen2soundscape/1.0 (contact@example.com)"}
        lang_short = (language or "en").split("_")[0].split("-")[0] or "en"
        r = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "format": "jsonv2",
                "lat": lat_c,
                "lon": lon_c,
                "zoom": 18,
                "addressdetails": 1,
                "accept-language": lang_short,
            },
            headers=headers,
            timeout=10,
        )
        r.raise_for_status()
        rev = r.json()
    except Exception as e:
        rev = {}
        print(f"⚠️ Reverse geocoding failed: {e}")

    display_name = rev.get("display_name") or ""
    addr = rev.get("address") or {}
    house = addr.get("house_number")
    road = addr.get("road") or addr.get("pedestrian") or addr.get("footway")
    neigh = addr.get("neighbourhood") or addr.get("suburb")
    city = addr.get("city") or addr.get("town") or addr.get("village")
    state = addr.get("state")
    postcode = addr.get("postcode")
    country = addr.get("country")

    if any([house, road, neigh, city, state, country]):
        parts_line = []
        if house and road: parts_line.append(f"{house} {road}")
        elif road: parts_line.append(road)
        if neigh: parts_line.append(neigh)
        if city: parts_line.append(city)
        if state: parts_line.append(state)
        if postcode: parts_line.append(postcode)
        if country: parts_line.append(country)
        where_line = ", ".join([p for p in parts_line if p])
    else:
        where_line = display_name or f"{lat_c:.5f}, {lon_c:.5f}"

    # History/about-here intent
    q_en = _to_english(question)
    wants_history = bool(
        re.search(
            r"\b(history|what happened|when was (this|here) (built|founded)|who built (this|here)|tell me about\b)",
            q_en, flags=re.IGNORECASE
        )
    )

    wiki_snippet = ""
    if wants_history:
        try:
            params = {
                "action": "query",
                "generator": "geosearch",
                "prop": "extracts|info",
                "exintro": 1,
                "explaintext": 1,
                "inprop": "url",
                "ggscoord": f"{lat_c}|{lon_c}",
                "ggsradius": max(100, min(radius_m, 3000)),
                "ggslimit": 10,
                "format": "json",
            }
            w = requests.get("https://en.wikipedia.org/w/api.php", params=params, timeout=10)
            w.raise_for_status()
            data = w.json()
            pages = list((data.get("query") or {}).get("pages", {}).values())
            pages = [p for p in pages if p.get("extract")]
            if pages:
                best = max(pages, key=lambda p: len(p.get("extract", "")))
                title = best.get("title", "")
                extract = best.get("extract", "")
                wiki_snippet = f"{title}: {extract.strip()}"
                if len(wiki_snippet) > 900:
                    wiki_snippet = wiki_snippet[:900].rsplit(" ", 1)[0] + "…"
        except Exception as e:
            print(f"⚠️ Wikipedia lookup failed: {e}")

    # Compose response (English → translate)
    lines = []
    if re.search(r"where am i", q_en, re.IGNORECASE):
        lines.append(f"You're at {where_line}.")
        lines.append(f"Coordinates: {lat_c:.5f}, {lon_c:.5f}.")
    else:
        lines.append(f"You're around {where_line} ({lat_c:.5f}, {lon_c:.5f}).")
    if wiki_snippet:
        lines += ["", "A bit of local context:", wiki_snippet]

    summary_en = "\n".join(lines).strip()

    lang_code = (language or "en").lower()
    spoken_text = summary_en
    if lang_code not in ["en", "en_us", "en-newest", "en_newest"]:
        try:
            spoken_text = GoogleTranslator(source="en", target=lang_code).translate(summary_en)
        except Exception as e:
            print(f"⚠️ Translation failed ({lang_code}): {e}")
            spoken_text = summary_en

    # ✅ PRINT BEFORE TTS so you immediately see the result
    print(spoken_text, flush=True)

    # TTS — guard so failures don’t swallow output
    try:
        model_path = find_best_piper_model(MODEL_DIR, language, speaker)
        return speak(
            spoken_text,
            language=language,
            speaker_key=model_path,
            speed=speed,
            output_mode=output_mode,  # "stream" or "file"
        )
    except Exception as e:
        print(f"⚠️ TTS failed: {e}")

    return spoken_text




# ---------- Main unified runner ----------
def main(
    speaker,
    language,
    speed,
    text,
    text_file,
    output_mode,
    force_mode,
    save_txt,
    system_prompt,
    max_new_tokens,
    temperature,
    top_p,
    ctx,
    threads,
    bitnet_bin,
    bitnet_model,
    extra_args,
    lat,
    lon,
    radius_m,     # NEW
    out_limit,    # NEW
    k_nearest,    # NEW
):
    print("🕒 Step 1: Getting question...")
    t1 = time.time()
    question = get_question(text=text, text_file=text_file)
    t2 = time.time()
    print(f"✅ Got question: {question}")
    print(f"⏱️ Step 1 duration: {t2 - t1:.2f} s\n")

    if (language is None) or (str(language).strip().lower() == "auto"):
        language = detect_language(question)
    print(f"🌐 Using language: {language}")

    chosen = force_mode.lower()
    if chosen == "auto":
        if is_osm_query(question):
            chosen = "osm"
        elif is_location_general(question, lat=lat, lon=lon):
            chosen = "place"
        else:
            chosen = "general"
    print(f"🧭 Routed to: {chosen.upper()}")

    t3 = time.time()
    if chosen == "osm":
        out = run_osm(
            question=question,
            language=language,
            speaker=speaker,
            speed=speed,
            output_mode=output_mode,
            lat=lat,
            lon=lon,
            radius_m=radius_m,     # pass through
            out_limit=out_limit,   # pass through
            k_nearest=k_nearest,   # pass through
        )
    elif chosen == "place":
        out = run_place_info(
            question=question,
            language=language,
            speaker=speaker,
            speed=speed,
            output_mode=output_mode,
            lat=lat,
            lon=lon,
        )
    else:
        out = run_general(
            question=question,
            language=language,
            speaker=speaker,
            speed=speed,
            output_mode=output_mode,
            system_prompt=system_prompt,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            ctx=ctx,
            threads=threads,
            bitnet_bin=bitnet_bin,
            bitnet_model=bitnet_model,
            extra_args=extra_args,
        )
    t4 = time.time()
    print(f"\n🎉 Completed in {t4 - t1:.2f} s (handler: {t4 - t3:.2f} s).")

    # Safe text save (don’t try to decode audio bytes)
    if save_txt:
        try:
            ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            outdir = pathlib.Path("saved_questions")
            outdir.mkdir(parents=True, exist_ok=True)
            path = outdir / f"{ts}.txt"
            with open(path, "w", encoding="utf-8") as f:
                f.write("Question:\n")
                f.write((question or "").strip() + "\n\n")
                f.write("Answer:\n")
                if isinstance(out, (bytes, bytearray)):
                    f.write("[Audio output]\n")
                else:
                    f.write((str(out) or "").strip() + "\n")
            print(f"📝 Saved Q&A to {path.as_posix()}")
        except Exception as e:
            print(f"⚠️ Failed to save Q&A: {e}")

    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Unified assistant: auto-routes between general chat and OSM, saves Q&A to txt."
    )
    parser.add_argument("--speaker", type=str, default="amy", help="Piper speaker name")
    parser.add_argument("--language", type=str, default="auto", help="TTS language code (or 'auto')")
    parser.add_argument("--speed", type=float, default=1.0, help="Speech speed multiplier")
    parser.add_argument("--text", type=str, help="Provide a question as text input instead of recording")
    parser.add_argument("--text-file", type=str, help="Provide a question via a text file instead of recording")
    parser.add_argument(
        "--output-mode",
        type=str,
        choices=["file", "stream"],
        default="stream",
        help="General chat streams by default; OSM respects your choice here.",
    )
    parser.add_argument(
        "--force-mode",
        type=str,
        choices=["auto", "osm", "general", "place"],
        default="auto",
        help="Force routing (useful for debugging).",
    )
    parser.add_argument(
        "--save-txt",
        dest="save_txt",
        action="store_true",
        help="Save the question and answer to saved_questions/<timestamp>.txt (default: on)",
    )
    parser.add_argument(
        "--no-save-txt",
        dest="save_txt",
        action="store_false",
        help="Disable saving the question/answer text file",
    )
    parser.set_defaults(save_txt=True)

    # BitNet / general
    parser.add_argument(
        "--system-prompt",
        type=str,
        default="You are a helpful AI assistant for everyday tasks, please always respond in the same language as the question",
        help="System instruction to steer responses.",
    )
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--ctx", type=int, default=4096)
    parser.add_argument("--threads", type=int, default=None, help="CPU threads (default: os.cpu_count())")
    parser.add_argument("--bitnet-bin", type=str, default="bitnet", help="Path to the bitnet.cpp binary")
    parser.add_argument(
        "--bitnet-model",
        type=str,
        default="~/screen2soundscape/backend/models/microsoft/bitnet-b1.58-2B-4T-gguf/ggml-model-q4_0.gguf",
        help="Path to a .gguf file or a directory containing GGUF files.",
    )
    parser.add_argument("--extra-args", type=str, nargs="*", default=None, help="Extra args passed to bitnet.cpp")

    # Optional geohints for OSM / PLACE
    parser.add_argument("--lat", type=float, help="Latitude of the current user location")
    parser.add_argument("--lon", type=float, help="Longitude of the current user location")
    parser.add_argument("--radius-m", type=int, default=500,
                    help="Search radius in meters for OSM around() queries")
    parser.add_argument("--out-limit", type=int, default=100,
                        help="Max rows to return from Overpass (caps runtime)")
    parser.add_argument("--k-nearest", type=int, default=5,
                        help="How many nearest POIs to report")

    # Keep the process alive to reuse the loaded model
    parser.add_argument("--loop", action="store_true", help="Keep process alive to reuse loaded models")

    args = parser.parse_args()

    def run_once(text_value: str):
        return main(
            speaker=args.speaker,
            language=args.language,
            speed=args.speed,
            text=text_value,
            text_file=args.text_file,
            output_mode=args.output_mode,
            force_mode=args.force_mode,
            save_txt=args.save_txt,
            system_prompt=args.system_prompt,
            max_new_tokens=args.max_new_tokens,
            temperature=args.temperature,
            top_p=args.top_p,
            ctx=args.ctx,
            threads=args.threads,
            bitnet_bin=args.bitnet_bin,
            bitnet_model=args.bitnet_model,
            extra_args=args.extra_args,
            lat=args.lat,
            lon=args.lon,
            radius_m=args.radius_m,
            out_limit=args.out_limit,
            k_nearest=args.k_nearest,
        )

    if args.loop:
        current_text = args.text
        while True:
            try:
                run_once(current_text)
                # Prompt for next question (avoid reloading models)
                current_text = input("\n> Ask another question (Enter to exit): ").strip()
                if not current_text:
                    break
            except (KeyboardInterrupt, EOFError):
                break
    else:
        run_once(args.text)
