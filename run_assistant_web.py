import warnings
import transformers
warnings.filterwarnings("ignore")
transformers.logging.set_verbosity_error()

import torch
# Disable JIT profiling for performance consistency
torch._C._jit_set_profiling_mode(False)
torch._C._jit_set_profiling_executor(False)

import requests
import os
import json
import time
from langdetect import detect
from deep_translator import GoogleTranslator
from utils.transcribe import record_and_transcribe
from utils.speak_silero import speak
from utils.question_to_overpass import parse_question, build_overpass_query
from utils.overpass_to_osm_llama import run_overpass_query, summarize_results, summarize_route


def detect_language(text: str) -> str:
    """Detect language code for a given text."""
    try:
        return detect(text)
    except Exception:
        return "unknown"


def get_directions(start: tuple, end: tuple, mode: str = "walk") -> dict:
    """Query OSRM for turn-by-turn directions."""
    profile = {"walk": "foot", "drive": "car", "bike": "bike"}.get(mode.lower(), "foot")
    url = f"https://router.project-osrm.org/route/v1/{profile}/{start[1]},{start[0]};{end[1]},{end[0]}"
    params = {"overview": "simplified", "geometries": "geojson", "steps": "true"}
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.json()


def handle_question(
    question: str,
    speaker: str = "arnold",
    language: str = None,
    speed: float = 1.0,
    save_json: bool = False
) -> str:
    """
    Process a user question to fetch OSM data or routing info,
    summarize with an LLM, optionally translate and speak.

    :param question: User's question in text form
    :param speaker: TTS speaker key (e.g. "arnold")
    :param language: TTS language override (e.g. "EN_NEWEST")
    :param speed: TTS speed multiplier
    :param save_json: If True, save raw Overpass results to ./osm_assistant_output/raw.json
    :return: Final (possibly translated) summary string
    """
    # 1. Detect language
    lang = detect_language(question)

    # 2. Parse question into OSM parameters
    params = parse_question(question)

    # 3. Determine mode: routing vs. POI lookup
    if params.get("mode") in ("route_check", "route_via"):
        # Routing mode
        directions = get_directions(params["start_coords"], params["end_coords"])
        summary = summarize_route(directions)
    else:
        # POI or boundary lookup
        if not params.get("center") and not params.get("bbox") and params.get("mode") != "boundary_lookup":
            raise ValueError("Could not resolve a location from the question.")
        query = build_overpass_query(params)
        results = run_overpass_query(query)
        if save_json:
            os.makedirs("osm_assistant_output", exist_ok=True)
            with open("osm_assistant_output/raw.json", "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
        summary = summarize_results(question, results)

    # 4. Translate if needed
    lang_code = lang.lower()
    translated = summary
    if lang_code not in ("en", "en_us", "en_newest"):
        try:
            translated = GoogleTranslator(source="en", target=lang_code).translate(summary)
        except Exception:
            translated = summary

    # 5. Speak via TTS
    speak(
        translated,
        language=language or lang.upper(),
        speaker_key=speaker,
        speed=speed
    )

    return translated
