# backend/run_assistant.py
import os

os.environ["TORCH_CPP_LOG_LEVEL"] = "ERROR"
# Suppress TensorFlow logs
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"      # 0=all logs, 1=filter INFO, 2=filter WARNING, 3=only errors
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"     # Disable oneDNN messages

# Optional: Suppress absl and other noisy logs
os.environ["TF_CPP_MIN_VLOG_LEVEL"] = "3"

import time
import warnings
import transformers
warnings.filterwarnings("ignore")
transformers.logging.set_verbosity_error()

import torch
torch._C._jit_set_profiling_mode(False)
torch._C._jit_set_profiling_executor(False)

import logging
logging.getLogger('tensorflow').setLevel(logging.ERROR)

import requests
import argparse
import json
from langdetect import detect
from deep_translator import GoogleTranslator
from backend.utils.transcribe import record_and_transcribe
from backend.utils.speak_piper import speak, find_best_piper_model, MODEL_DIR
from backend.utils.question_to_overpass import (
    parse_question,
    build_overpass_query)

from backend.utils.overpass_to_osm_flan import (
    run_overpass_query,
    summarize_results,
    summarize_route,
    warmup_summariser
)

warmup_summariser() 

def detect_language(text):
    try:
        lang = detect(text)
    except Exception:
        lang = "unknown"
    return lang

def get_question_and_language(text=None, text_file=None):
    if text:
        lang = detect_language(text)
        return text.strip(), lang
    elif text_file and os.path.isfile(text_file):
        with open(text_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
        lang = detect_language(content)
        return content, lang
    else:
        return record_and_transcribe()


def get_directions(start, end, mode="walk"):
    profile = {"walk": "foot", "drive": "car", "bike": "bike"}.get(mode.lower(), "foot")
    url = f"https://router.project-osrm.org/route/v1/{profile}/{start[1]},{start[0]};{end[1]},{end[0]}"
    params = {"overview": "simplified", "geometries": "geojson", "steps": "true"}
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()


def main(speaker, language, speed, save_json, text, text_file, lat=None, lon=None, output_mode="file"):
    if not speaker:
        print("❌ You must specify a --speaker.")
        return

    print("🕒 Step 1: Getting question (recording or from text)...")
    t1 = time.time()
    question, lang = get_question_and_language(text=text, text_file=text_file)
    t2 = time.time()
    print(f"✅ Got question: [{lang}] {question}")
    print(f"⏱️ Step 1 duration: {t2 - t1:.2f} seconds\n")

    print("🕒 Step 2: Parsing question...")
    t3 = time.time()
    params = parse_question(question, lat=lat, lon=lon)
    t4 = time.time()
    print(f"✅ Parsed parameters: {params}")
    print(f"⏱️ Step 2 duration: {t4 - t3:.2f} seconds\n")

    if params.get("mode") in ("route_check", "route_via"):
        print("🕒 Step 3: Computing directions with OSRM...")
        t5 = time.time()
        try:
            directions = get_directions(params["start_coords"], params["end_coords"])
            summary = summarize_route(directions)
            t6 = time.time()
            print(f"✅ Got directions.")
            print(f"🗺️ Summary:\n{summary}")
            print(f"⏱️ Step 3 duration: {t6 - t5:.2f} seconds\n")
        except Exception as e:
            print(f"❌ Failed to get directions: {e}")
            return

    # if not params.get("center") and not params.get("bbox") and params.get("mode") != "boundary_lookup":
    #     print("❌ Could not resolve a location from the question.")
    #     return

    # Step 3: Build Overpass query
    print("🕒 Step 3: Building Overpass QL query...")
    t5 = time.time()
    try:
        overpass_query = build_overpass_query(params)
        t6 = time.time()
        print("✅ Built Overpass query:")
        print(overpass_query)
        print(f"⏱️ Step 3 duration: {t6 - t5:.2f} seconds\n")
    except Exception as e:
        print(f"❌ Failed to build Overpass query: {e}")
        return

    # Step 4: Run Overpass query
    print("🕒 Step 4: Running Overpass API query...")
    t7 = time.time()
    try:
        results = run_overpass_query(overpass_query)
        t8 = time.time()
        print(f"✅ Got {len(results.get('elements', []))} result(s) from Overpass.")
        if save_json:
            os.makedirs("osm_assistant_output", exist_ok=True)
            with open("osm_assistant_output/raw.json", "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"⏱️ Step 4 duration: {t8 - t7:.2f} seconds\n")
    except Exception as e:
        print(f"❌ Failed to run Overpass query: {e}")
        return

    # Step 5: Summarize results
    print("🕒 Step 5: Summarizing results with LLM...")
    t9 = time.time()
    summary = summarize_results(question, results)
    t10 = time.time()
    print("✅ Summary (English):")
    print(summary)
    print(f"⏱️ Step 5 duration: {t10 - t9:.2f} seconds\n")

    # Step 5.5: Translate summary if needed
    lang_code = lang.lower()
    translated_summary = summary
    if lang_code not in ["en", "en_us", "en_newest"]:
        try:
            print(f"🌍 Detected non-English language '{lang}'. Translating summary...")
            translated_summary = GoogleTranslator(source="en", target=lang_code).translate(summary)
            print(f"✅ Translated summary ({lang_code}):")
            print(translated_summary)
        except Exception as e:
            print(f"⚠️ Failed to translate summary to '{lang_code}': {e}")
            translated_summary = summary

    # Step 6: Speak summary
    print("🕒 Step 6: Speaking response with TTS...")
    t11 = time.time()

    model_path = find_best_piper_model(MODEL_DIR, language, speaker)
    output = speak(
        translated_summary,
        language=language or lang.upper(),
        speaker_key=model_path,  # now passes full path
        speed=speed,
        output_mode=output_mode
    )


    t12 = time.time()
    print(f"✅ Finished speaking.")
    print(f"🔉 Output audio: {output}")
    print(f"⏱️ Step 6 duration: {t12 - t11:.2f} seconds\n")

    total_time = t12 - t1
    print(f"🎉 Assistant process completed in {total_time:.2f} seconds.")
    return output
    
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the OSM voice assistant.")
    parser.add_argument("--speaker", type=str, default="amy", help="Speaker name (matches speaker folder)")
    parser.add_argument("--language", type=str, default="en", help="Language key for TTS (used if not detected)")
    parser.add_argument("--speed", type=float, default=1.0, help="Speech speed multiplier")
    parser.add_argument("--save-json", action="store_true", help="Save raw Overpass results to JSON")
    parser.add_argument("--text", type=str, help="Provide a question as text input instead of recording")
    parser.add_argument("--text-file", type=str, help="Provide a question via a text file instead of recording")
    parser.add_argument("--lat", type=float, help="Latitude of the current user location")
    parser.add_argument("--lon", type=float, help="Longitude of the current user location")
    parser.add_argument("--output-mode", type=str, choices=["file", "stream"], default="file",help="Output mode for TTS: 'file' or 'stream' (default: file)")


    args = parser.parse_args()
    main(
        speaker=args.speaker,
        language=args.language,
        speed=args.speed,
        save_json=args.save_json,
        text=args.text,
        text_file=args.text_file,
        lat=args.lat,
        lon=args.lon
    )


# # Example usage:
# python -m backend.run_assistant_osm --speaker amy --text "Are there any coffee shops nearby?" --lat 50.6683 --lon 4.6156 --language en # python -m backend.run_assistant --speaker amy --text "Are there any coffee shops nearby?" --lat 50.6683 --lon 4.6156 --language en 
# python -m backend.run_assistant_osm --speaker amy --text "Are there any coffee shops nearby?" --lat 50.6683 --lon 4.6156 --language en # python -m backend.run_assistant --speaker amy --text "Are there any coffee shops nearby?" --lat 50.6683 --lon 4.6156 --language en --output-mode stream


