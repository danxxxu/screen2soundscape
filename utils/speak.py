import os
import sys
os.environ["TORCH_CPP_LOG_LEVEL"] = "ERROR"
# silence stderr from torch hub
sys.stderr = open(os.devnull, 'w')

import re
import argparse
import datetime
from typing import Dict, Any
import soundfile as sf

import torch
import torchaudio
import numpy as np
import warnings

import whisper
# Load Whisper once at import
_whisper_model = whisper.load_model("base")

warnings.filterwarnings("ignore")
torch._C._jit_set_profiling_mode(False)
torch._C._jit_set_profiling_executor(False)

# Base path: project root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUTPUT_DIR = os.path.join(BASE_DIR, "osm_assistant_speaker_audio")

# pick GPU if available
device = "cuda" if torch.cuda.is_available() else "cpu"

# cache for Silero models
_silero_models: Dict[str, Any] = {}

def get_silero_model(language: str = 'en', speaker: str = 'lj_v2'):
    key = f"{language}_{speaker}"
    if key in _silero_models:
        return _silero_models[key]
    model, _ = torch.hub.load(
        repo_or_dir='snakers4/silero-models',
        model='silero_tts',
        language=language,
        speaker=speaker
    )
    model.to(device)
    model.eval()
    _silero_models[key] = model
    return model

def clean_sentences(text: str):
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text.strip()) if s.strip()]


def speak(
    text: str,
    language: str,
    speaker_key: str,
    speed: float = 1.0,
    output_dir: str = DEFAULT_OUTPUT_DIR
) -> str:
    os.makedirs(output_dir, exist_ok=True)

    sentences = clean_sentences(text)
    lang_code = language.lower()[:2]

    # Default speaker mapping
    SUPPORTED_SPEAKERS = {
        'en': 'lj_v2',
        'fr': 'gilles_v2',
        'es': 'tux_v2',
        'de': 'thorsten_v2',
        'ru': 'aidar_v2',
        'ua': 'mykyta_v2',
        'kk': 'aigul_v2',
        'uz': 'dilnavoz_v2'
    }

    # ✅ Check if a custom TTS model is provided
    if os.path.isfile(speaker_key):
        print(f"[speak] Using custom TTS model: {speaker_key}")
        model = torch.package.PackageImporter(speaker_key).load_pickle("tts_models", "model")
        model.to(device)
        model.eval()
    else:
        speaker = SUPPORTED_SPEAKERS.get(lang_code, 'lj_v2')
        model = get_silero_model(language=lang_code, speaker=speaker)

    sample_rate = 48000
    silence_start = np.zeros(int(0.5 * sample_rate), dtype=np.float32)
    silence_between = np.zeros(int(0.3 * sample_rate), dtype=np.float32)

    full_audio = silence_start
    for sent in sentences:
        wav = model.apply_tts(sent, sample_rate=sample_rate)
        full_audio = np.concatenate([full_audio, np.array(wav, dtype=np.float32), silence_between])

    # ✅ Apply speed factor
    if speed != 1.0:
        indices = np.arange(0, len(full_audio), speed)
        indices = indices[indices < len(full_audio)].astype(int)
        full_audio = full_audio[indices]

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    wav_path = os.path.join(output_dir, f"tts_{timestamp}.wav")
    sf.write(wav_path, full_audio, sample_rate)

    print(f"[speak] ✅ Saved TTS to '{wav_path}'")
    return wav_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate speech from text using Silero TTS."
    )
    parser.add_argument("text", help="The text to speak.")
    parser.add_argument("--language", default="en", help="Language code (default: en).")
    parser.add_argument(
        "--speaker",
        required=True,
        help="Speaker key (one of the supported voices, for folder consistency)"
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Speech speed multiplier (currently unused)."
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Where to save the final MP3."
    )
    args = parser.parse_args()
    speak(
        text=args.text,
        language=args.language,
        speaker_key=args.speaker,
        speed=args.speed,
        output_dir=args.output_dir
    )
