import os
import re
import unicodedata
import datetime
import wave
import subprocess
import glob
import io
from typing import Optional
from piper.voice import PiperVoice, SynthesisConfig
from pydub import AudioSegment
import torch

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

_piper_models = {}

# -------------------------
# Helpers
# -------------------------
def clean_text(text: str, lang: str) -> str:
    """Normalize text. Remove accents only for English."""
    text = text.replace("’", "'").replace("‘", "'").replace("`", "'")
    if lang.startswith("en"):
        text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-zA-Z0-9À-ÖØ-öø-ÿ\s.,!?'\-]", " ", text).strip()


def get_piper_model(language: str = 'en', speaker: Optional[str] = None):
    """Load a Piper TTS model (auto-download if missing)."""
    speaker = speaker or SUPPORTED_SPEAKERS.get(language, DEFAULT_SPEAKER)
    key = f"{language}_{speaker}".lower()
    model_path = os.path.join(MODEL_DIR, f"{speaker}.onnx")
    config_path = os.path.join(MODEL_DIR, f"{speaker}.onnx.json")

    if not (os.path.isfile(model_path) and os.path.isfile(config_path)):
        print(f"[piper] ⚠️ Model '{speaker}' not found locally. Attempting download...")
        subprocess.run(["python3", "-m", "piper.download_voices", "--data-dir", MODEL_DIR, speaker], check=True)
        downloaded_files = glob.glob(os.path.join(MODEL_DIR, f"{speaker}*"))
        if not downloaded_files:
            raise FileNotFoundError(f"No downloaded files found for '{speaker}' in {MODEL_DIR}'")
        print(f"[piper] ✅ Download complete: {downloaded_files}")

    if key not in _piper_models:
        print(f"[piper] ⏬ Loading Piper model: {speaker}")
        _piper_models[key] = PiperVoice.load(model_path, use_cuda=torch.cuda.is_available())

    return _piper_models[key]


def chunk_text(text: str, max_len: int = 200) -> list:
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

# -------------------------
# Main speak function
# -------------------------
def speak(
    text: str,
    language: str = 'en',
    speaker_key: str = None,
    speed: float = 1.0,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    return_stream_mp3: bool = False
):
    """
    Convert text to speech using Piper.
    - If return_stream_mp3=True → returns MP3 bytes
    - Otherwise saves to MP3 file and returns file path
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

    # Convert speed -> length_scale
    length_scale = max(0.5, min(3.0, 1.0 / speed)) if speed > 0 else 1.0
    syn_config = SynthesisConfig(
        volume=1.0,
        length_scale=length_scale,
        noise_scale=1.0,
        noise_w_scale=1.0,
        normalize_audio=True
    )

    # Write WAV
    with wave.open(output_path, "wb") as wav_file:
        for chunk in chunks:
            print(f"[piper] ▶ Synthesizing chunk: {chunk}")
            model.synthesize_wav(chunk, wav_file, syn_config=syn_config)

    # If requested, return MP3 stream instead of saving
    if return_stream_mp3:
        audio_segment = AudioSegment.from_wav(output_path)
        mp3_buffer = io.BytesIO()
        audio_segment.export(mp3_buffer, format="mp3")
        mp3_buffer.seek(0)
        os.remove(output_path)
        return mp3_buffer.read()

    # Otherwise, save MP3 file
    audio_segment = AudioSegment.from_wav(output_path)
    mp3_path = output_path.replace(".wav", ".mp3")
    audio_segment.export(mp3_path, format="mp3")
    os.remove(output_path)

    print(f"[piper] ✅ Saved TTS to '{mp3_path}'")
    return mp3_path
