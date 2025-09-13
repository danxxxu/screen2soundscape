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

from backend.utils.bitnet_singleton import stream_chat
from backend.utils.transcribe import record_and_transcribe
from backend.utils.speak_piper import speak, find_best_piper_model, MODEL_DIR

# ---- OSM utils ----
from backend.utils.osm_tags import find_osm_tags
from backend.utils.question_to_overpass import parse_question, build_overpass_query
from backend.utils.overpass_to_osm_bitnet import (
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
                speak(
                    chunk,
                    language=language,
                    speaker_key=model_path_tts,
                    speed=speed,
                    output_mode="stream",
                )
            print()
            response_text = "".join(collected).strip()
        else:
            for chunk in gen:
                print(chunk, end="", flush=True)
                collected.append(chunk)
            print()
            response_text = "".join(collected).strip()
            speak(
                response_text,
                language=language,
                speaker_key=model_path_tts,
                speed=speed,
                output_mode="file",
            )
        return response_text
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
    speak(
        spoken_text,
        language=language,
        speaker_key=model_path,
        speed=speed,
        output_mode=output_mode,  # "file" or "stream"
    )
    print(spoken_text)
    return spoken_text


# ---------- Main unified runner ----------
def main(
    speaker,
    language,  # "auto" → detect from question
    speed,
    text,
    text_file,
    output_mode,  # "stream" (general) or "file"/"stream" (OSM)
    force_mode,  # "auto" | "osm" | "general"
    save_txt,  # save Q&A to saved_questions/<timestamp>.txt
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
    t1 = time.time
