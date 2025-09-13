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

from backend.utils.bitnet_singleton import stream_chat  # general chat (BitNet)
from backend.utils.transcribe import record_and_transcribe
from backend.utils.speak_piper import speak, find_best_piper_model, MODEL_DIR

# ---- OSM utils (your existing modules) ----
from backend.utils.osm_tags import find_osm_tags
from backend.utils.question_to_overpass import parse_question, build_overpass_query
from backend.utils.overpass_to_osm_bitnet import (
    run_overpass_query,
    summarize_results,
    summarize_route,
    warmup_summariser,
)
from deep_translator import GoogleTranslator
import requests


# ---------- Language detection ----------
def detect_language(text: str) -> str:
    """
    Auto-detect language code for TTS.
    Priority:
      1) langdetect (if installed) -> ISO-639-1 like 'en', 'fr', ...
      2) Unicode-script heuristics (CJK, Arabic, Cyrillic, Greek, Hebrew, etc.)
      3) default 'en'
    """
    code = None
    try:
        # pip install langdetect
        from langdetect import detect, DetectorFactory
        DetectorFactory.seed = 0
        code = detect(text)
    except Exception:
        s = text or ""
        if any("\u3040" <= ch <= "\u30ff" or "\u31f0" <= ch <= "\u31ff" for ch in s):  # Hiragana/Katakana
            return "ja"
        if any("\u4e00" <= ch <= "\u9fff" for ch in s):  # CJK (likely zh)
            return "zh"
        if any("\uac00" <= ch <= "\ud7af" for ch in s):  # Hangul
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
        # crude Latin diacritic hints
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
_ROUTE_WORDS_EN = r"(route|directions|navigate|how to get|way to|get to|walk|bike|drive|bus|tram|subway|metro)"
_OSM_TERMS_EN = r"(amenity|highway|shop|leisure|tourism|public\s*transport|osm|overpass|bbox|coordinates?)"
_COORDS_RE = re.compile(r"\b(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)\b")


def _to_english(text: str) -> str:
    """Translate to English if detection says non-English. Fail-safe to original."""
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
    Multilingual intent detector:
      - Translate to English for regex/routing cues.
      - Try TAG_MAP on both original and English.
      - Try parse_question on original for structured hints.
    Scoring:
      +2 if deterministic OSM tags found (TAG_MAP)
      +2 if parse_question reveals mode/center/bbox/tags/start+end coords
      +1 if "nearby"/routing semantics in English
      +1 if explicit coords or OSM-ish terms in English
    Threshold >= 2 => route to OSM.
    """
    q_orig = (question or "").strip()
    q_en = _to_english(q_orig).lower()
    score = 0

    # 1) Deterministic tag hits via your TAG_MAP (try both original & English)
    try:
        if find_osm_tags(q_orig) or find_osm_tags(q_en):
            score += 2
    except Exception:
        pass

    # 2) Parsability signal (use original so parser can leverage numbers/lat-lon text, etc.)
    try:
        params = parse_question(q_orig)
        strong = any(
            [
                bool(params.get("mode")),
                bool(params.get("center")),
                bool(params.get("bbox")),
                bool(params.get("tags")),
                bool(params.get("start_coords")) and bool(params.get("end_coords")),
            ]
        )
        if strong:
            score += 2
    except Exception:
        pass

    # 3) Nearby / routing semantics (after MT)
    if re.search(_NEARBY_WORDS_EN, q_en) or re.search(_ROUTE_WORDS_EN, q_en):
        score += 1

    # 4) Coordinates or OSM-ish terms (after MT)
    if _COORDS_RE.search(q_en) or re.search(_OSM_TERMS_EN, q_en):
        score += 1

    return score >= 2


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
    # Prepare TTS
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
            # Single-shot TTS
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
    warmup_summariser()

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

    # Build Overpass QL
    overpass_query = build_overpass_query(params)
    print("🧭 Overpass query:")
    print(overpass_query)

    # Run Overpass
    results = run_overpass_query(overpass_query)
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
    # Step 1: Get question
    print("🕒 Step 1: Getting question...")
    t1 = time.time()
    question = get_question(text=text, text_file=text_file)
    t2 = time.time()
    print(f"✅ Got question: {question}")
    print(f"⏱️ Step 1 duration: {t2 - t1:.2f} s\n")

    # Step 2: Language
    if (language is None) or (str(language).strip().lower() == "auto"):
        language = detect_language(question)
    print(f"🌐 Using language: {language}")

    # Step 3: Intent routing
    chosen = force_mode.lower()
    if chosen == "auto":
        chosen = "osm" if is_osm_query(question) else "general"
    print(f"🧭 Routed to: {chosen.upper()}")

    # Step 4: Run chosen path
    t3 = time.time()
    if chosen == "osm":
        # For OSM, respect user-selected output_mode ("file" or "stream")
        out = run_osm(
            question=question,
            language=language,
            speaker=speaker,
            speed=speed,
            output_mode=output_mode,
            lat=lat,
            lon=lon,
        )
        # Optional fallback: if no results text suggests emptiness, we could call general; omitted for clarity.
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

    # Step 5: Save Q&A to timestamped TXT (default: on)
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
        choices=["auto", "osm", "general"],
        default="auto",
        help="Force routing (useful for debugging).",
    )

    # Save Q&A toggle (default ON)
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

    # Optional geohints for OSM
    parser.add_argument("--lat", type=float, help="Latitude of the current user location")
    parser.add_argument("--lon", type=float, help="Longitude of the current user location")

    args = parser.parse_args()

    main(
        speaker=args.speaker,
        language=args.language,
        speed=args.speed,
        text=args.text,
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
