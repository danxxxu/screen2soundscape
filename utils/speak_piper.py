import os
import re
import unicodedata
import datetime
import wave
import subprocess
import glob
from typing import Optional

from piper.voice import PiperVoice

# ========================
# Config
# ========================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUTPUT_DIR = os.path.join(BASE_DIR, "osm_assistant_speaker_audio")
MODEL_DIR = os.path.join(BASE_DIR, "piper_models")
os.makedirs(MODEL_DIR, exist_ok=True)

DEFAULT_LANGUAGE = 'en'
DEFAULT_SPEAKER = 'en_US-lessac-medium'

SUPPORTED_SPEAKERS = {
    'en': 'en_US-lessac-medium',
    'fr': 'fr_FR-siwis-low',
    'es': 'es_ES-carlfm-low',
    'de': 'de_DE-thorsten-low',
    'ru': 'ru_RU-ruslan-low',
    'uk': 'uk_UA-ukrainian-low',
    'kk': 'kk_KZ-aisuluu-low',
    'uz': 'uz_UZ-dilnavoz-low'
}

# Cache loaded models
_piper_models = {}


def clean_text(text: str, lang: str) -> str:
    """
    Normalize text for Piper. Remove accents only for English or non-accent languages.
    """
    text = text.replace("’", "'").replace("‘", "'").replace("`", "'")

    # Remove accents only for English
    if lang.startswith("en"):
        text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")

    # Remove unsupported characters
    text = re.sub(r"[^a-zA-Z0-9À-ÖØ-öø-ÿ\s.,!?'\-]", " ", text)
    return text.strip()


def get_piper_model(language: str = 'en', speaker: Optional[str] = None):
    """
    Load a Piper TTS model for the given language/speaker. Downloads if missing.
    """
    speaker = speaker or SUPPORTED_SPEAKERS.get(language, DEFAULT_SPEAKER)
    key = f"{language}_{speaker}".lower()
    model_path = os.path.join(MODEL_DIR, f"{speaker}.onnx")
    config_path = os.path.join(MODEL_DIR, f"{speaker}.onnx.json")

    # Download model if missing
    if not (os.path.isfile(model_path) and os.path.isfile(config_path)):
        print(f"[piper] ⚠️ Model '{speaker}' not found locally. Attempting download...")
        subprocess.run(
            ["python3", "-m", "piper.download_voices", "--data-dir", MODEL_DIR, speaker],
            check=True
        )
        downloaded_files = glob.glob(os.path.join(MODEL_DIR, f"{speaker}*"))
        if not downloaded_files:
            raise FileNotFoundError(f"No downloaded files found for '{speaker}' in {MODEL_DIR}'")
        print(f"[piper] ✅ Download complete: {downloaded_files}")

    # Load from cache if available
    if key not in _piper_models:
        print(f"[piper] ⏬ Loading Piper model: {speaker}")
        _piper_models[key] = PiperVoice.load(model_path)

    return _piper_models[key]


def chunk_text(text: str, max_len: int = 200) -> list:
    """
    Split text into smaller chunks for safer synthesis.
    """
    chunks = re.split(r'(?<=[.!?])\s+', text)
    result = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        if len(chunk) > max_len:
            parts = [chunk[i:i+max_len] for i in range(0, len(chunk), max_len)]
            result.extend(parts)
        else:
            result.append(chunk)
    return result


def speak(
    text: str,
    language: str = 'en',
    speaker_key: str = None,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    return_audio: bool = False
) -> str:
    """
    Convert text to speech using Piper TTS (safe mode).
    Always produces an audio file, falling back to default text if necessary.
    """
    print("[piper] ✅ Entered speak()")
    os.makedirs(output_dir, exist_ok=True)

    lang_code = language.lower()[:2]
    speaker = speaker_key or SUPPORTED_SPEAKERS.get(lang_code, DEFAULT_SPEAKER)

    model = get_piper_model(language=lang_code, speaker=speaker)

    text = clean_text(text, lang_code)
    chunks = chunk_text(text)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(output_dir, f"tts_{timestamp}.wav")

    print("[piper] ✅ Starting synthesis")
    with wave.open(output_path, "wb") as wav_file:
        for chunk in chunks:
            print(f"[piper] ▶ Synthesizing chunk: {chunk}")
            try:
                model.synthesize_wav(chunk, wav_file)
            except Exception as e:
                print(f"[piper] ⚠️ Failed chunk synthesis: {e}")

    # ✅ Fallback if no audio was generated
    if os.path.getsize(output_path) < 1000:
        print("[piper] ⚠️ No audio generated, using fallback speech")
        with wave.open(output_path, "wb") as wav_file:
            model.synthesize_wav("I found some results nearby.", wav_file)

    print(f"[piper] ✅ Saved TTS to '{output_path}'")
    return output_path
