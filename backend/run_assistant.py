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
    """
    Route to OSM only when the text clearly looks like a map/search/routing request.
    Passing lat/lon via CLI must NOT influence this decision.
    """
    q_orig = (question or "").strip()
    q_en = _to_english(q_orig)

    # If it *looks* like a knowledge Q (e.g., “Explain SIMD vs MIMD”), prefer GENERAL,
    # unless there are explicit OSM/map cues.
    looks_general = bool(_GENERAL_CUES_EN.search(q_en))

    # Explicit map cues from text (not from CLI lat/lon)
    has_nearby_or_route = bool(re.search(_NEARBY_WORDS_EN, q_en) or re.search(_ROUTE_WORDS_EN, q_en))
    has_coords_in_text  = bool(_COORDS_RE.search(q_en))
    has_osm_words       = bool(re.search(_OSM_TERMS_EN, q_en))
    tags_detected       = bool(find_osm_tags(q_orig) or find_osm_tags(q_en))

    # Structured parse signals — EXCLUDE default center; require stronger evidence
    parsed = {}
    try:
        parsed = parse_question(q_orig)
    except Exception:
        parsed = {}
    strong_parse = any(
        [
            bool(parsed.get("tags")),
            bool(parsed.get("bbox")),
            parsed.get("mode") in ("route_check", "route_via"),
            (bool(parsed.get("start_coords")) and bool(parsed.get("end_coords"))),
        ]
    )

    # If it looks like a general knowledge query and lacks explicit map cues → GENERAL
    if looks_general and not (has_nearby_or_route or has_coords_in_text or has_osm_words or tags_detected):
        return False

    # Otherwise require *some* clear OSM signal
    return any([has_nearby_or_route, has_coords_in_text, has_osm_words, tags_detected, strong_parse])

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
    model_path_tts = find_best_piper_model(MODEL_DIR, language, speaker)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]

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

        if output_mode == "stream":
            print("🔊 Streaming as it generates...\n")
            for chunk in gen:
                print(chunk, end="", flush=True)
                collected.append(chunk)

            print()
            response_text = "".join(collected).strip()
        else:
            for chunk in gen:
                print(chunk, end="", flush=True)
                collected.append(chunk)
            print()
            response_text = "".join(collected).strip()

        return speak(
            response_text,
            language=language,
            speaker_key=model_path_tts,
            speed=speed,
            output_mode="file",
        )
    except Exception as e:
        print(f"\n❌ BitNet inference failed: {e}")
        return ""


def run_osm(question, language, speaker, speed, output_mode, lat=None, lon=None):
    """
    Robust OSM handler:
    - parse question (lat/lon are just hints; they DO NOT force OSM intent)
    - optional routing summary
    - build deterministic Overpass QL; if invalid AND text clearly looks map-ish, use BitNet fallback
    - run Overpass; summarize; translate; TTS
    - on any API/build failure, speak a friendly message instead of crashing
    """
    # --- local helpers (kept inside to make this function fully drop-in) ---
    def _looks_invalid_overpass(q: str) -> bool:
        if not q or not q.strip():
            return True
        if "area:None" in q or "(area:None)" in q:
            return True
        if re.search(r"\bNone\b", q):
            return True
        return False

    def _text_has_map_intent(q: str) -> bool:
        # Use English for regex cues; tags check both original and translated
        q_en = _to_english(q)
        return any([
            bool(find_osm_tags(q) or find_osm_tags(q_en)),
            bool(re.search(_NEARBY_WORDS_EN, q_en)),
            bool(re.search(_ROUTE_WORDS_EN, q_en)),
            bool(re.search(_OSM_TERMS_EN, q_en)),
            bool(_COORDS_RE.search(q_en)),
        ])

    # Parse → (optional) route → Overpass → Summarize → Translate → TTS
    params = parse_question(question, lat=lat, lon=lon)

    # Optional routing summary
    if params.get("mode") in ("route_check", "route_via"):
        try:
            directions = get_directions(params["start_coords"], params["end_coords"])
            route_summary = summarize_route(directions)
            print("🗺️ Route summary:")
            print(route_summary)
        except Exception as e:
            print(f"⚠️ Routing failed: {e}")

    # Build Overpass QL (deterministic builder first)
    overpass_query = ""
    try:
        overpass_query = build_overpass_query(params)
    except Exception as e:
        print(f"⚠️ build_overpass_query failed: {e}")

    # If invalid, only try BitNet QL when the *text* looks like a map request
    if _looks_invalid_overpass(overpass_query):
        if _text_has_map_intent(question):
            # pick best center we know about
            clat, clon = None, None
            if params.get("center"):
                clat, clon = params["center"]
            elif lat is not None and lon is not None:
                clat, clon = (lat, lon)
            try:
                overpass_query = generate_overpass_query(
                    question,
                    lat=clat,
                    lon=clon,
                    radius=params.get("radius", 2000),
                )
                print("🧭 Overpass query (BitNet fallback):")
            except Exception as e:
                msg = f"❌ Failed to generate Overpass query: {e}"
                print(msg)
                model_path = find_best_piper_model(MODEL_DIR, language, speaker)
                speak(msg, language=language, speaker_key=model_path, speed=speed, output_mode=output_mode)
                return msg
        else:
            # Not a map request—guide to general mode
            msg = (
                "This doesn’t look like a map request. "
                "Re-run with --force-mode general for a regular answer."
            )
            print(msg)
            model_path = find_best_piper_model(MODEL_DIR, language, speaker)
            speak(msg, language=language, speaker_key=model_path, speed=speed, output_mode=output_mode)
            return msg
    else:
        print("🧭 Overpass query (deterministic):")

    print(overpass_query)

    # Run Overpass safely
    try:
        results = run_overpass_query(overpass_query)
    except Exception as e:
        msg = f"Sorry, I couldn't run the map search ({e})."
        print(msg)
        model_path = find_best_piper_model(MODEL_DIR, language, speaker)
        speak(msg, language=language, speaker_key=model_path, speed=speed, output_mode=output_mode)
        return msg

    print(f"✅ Overpass returned {len(results.get('elements', []))} element(s).")

    # Summarize (English)
    summary_en = summarize_results(question, results)

    # Translate if needed
    lang_code = (language or "en").lower()
    spoken_text = summary_en
    if lang_code not in ["en", "en_us", "en_newest"]:
        try:
            spoken_text = GoogleTranslator(source="en", target=lang_code).translate(summary_en)
        except Exception as e:
            print(f"⚠️ Translation failed ({lang_code}): {e}")
            spoken_text = summary_en

    # TTS
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
    r"(where am i|what('?| i)s this (place|location)|history of (this|here|this place|this location)|"
    r"what happened here|what neighborhood am i in|what district am i in|tell me about (here|this place|this location))",
    re.IGNORECASE,
)


def is_location_general(question: str, lat=None, lon=None) -> bool:
    q_orig = (question or "").strip()
    q_en = _to_english(q_orig)

    # Only for “Where am I / tell me about here”-style questions
    has_loc_general = bool(_LOC_GENERAL_CUES_EN.search(q_en))
    # Exclude explicit OSM/nearby/route/amenity intents
    has_osmish = bool(
        re.search(_NEARBY_WORDS_EN, q_en) or
        re.search(_ROUTE_WORDS_EN, q_en) or
        re.search(_OSM_TERMS_EN, q_en)
    )
    if not has_loc_general or has_osmish:
        return False

    # Enter PLACE mode only if we truly have coordinates (CLI or typed in text)
    if (lat is not None and lon is not None):
        return True
    if _COORDS_RE.search(q_en):
        return True

    return False


def run_place_info(question, language, speaker, speed, output_mode, lat=None, lon=None, radius_m=500):
    """
    Location-aware general handler:
    - Reverse geocode coords to a human-readable place (in the user's language).
    - If the question asks for history/about-here, fetch a nearby Wikipedia summary.
    - Answer in the user's language and speak it.
    """
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

    # --- Reverse geocode via Nominatim, forcing labels in the user's language ---
    try:
        headers = {"User-Agent": "screen2soundscape/1.0 (contact@example.com)"}  # set your UA/email
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
    # Useful bits if present
    house = addr.get("house_number")
    road = addr.get("road") or addr.get("pedestrian") or addr.get("footway")
    neigh = addr.get("neighbourhood") or addr.get("suburb")
    city = addr.get("city") or addr.get("town") or addr.get("village")
    state = addr.get("state")
    postcode = addr.get("postcode")
    country = addr.get("country")

    where_line = None
    if any([house, road, neigh, city, state, country]):
        parts = []
        if house and road: parts.append(f"{house} {road}")
        elif road: parts.append(road)
        if neigh: parts.append(neigh)
        if city: parts.append(city)
        if state: parts.append(state)
        if postcode: parts.append(postcode)
        if country: parts.append(country)
        where_line = ", ".join([p for p in parts if p])
    else:
        where_line = display_name or f"{lat_c:.5f}, {lon_c:.5f}"

    # Decide if the user asked about "history/about here"
    q_en = _to_english(question)
    wants_history = bool(
        re.search(
            r"\b(history|what happened|when was (this|here) (built|founded)|who built (this|here)|tell me about\b)",
            q_en,
            flags=re.IGNORECASE,
        )
    )

    wiki_snippet = ""
    if wants_history:
        try:
            # Wikipedia geosearch for nearby pages; pick the best extract
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

    # Compose response in English first, then translate to the question's language
    parts = []
    if re.search(r"where am i", q_en, re.IGNORECASE):
        parts.append(f"You're at {where_line}.")
        parts.append(f"Coordinates: {lat_c:.5f}, {lon_c:.5f}.")
    else:
        parts.append(f"You're around {where_line} ({lat_c:.5f}, {lon_c:.5f}).")

    if wiki_snippet:
        parts.append("")
        parts.append("A bit of local context:")
        parts.append(wiki_snippet)

    summary_en = "\n".join(parts).strip()

    # Translate if needed
    lang_code = (language or "en").lower()
    spoken_text = summary_en
    if lang_code not in ["en", "en_us", "en-newest", "en_newest"]:
        try:
            spoken_text = GoogleTranslator(source="en", target=lang_code).translate(summary_en)
        except Exception as e:
            print(f"⚠️ Translation failed ({lang_code}): {e}")
            spoken_text = summary_en

    # TTS
    model_path = find_best_piper_model(MODEL_DIR, language, speaker)

    return speak(
        spoken_text,
        language=language,
        speaker_key=model_path,
        speed=speed,
        output_mode=output_mode,
    )



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
            chosen = "place"   # new middle lane
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
                f.write((out or "").strip() + "\n")
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
