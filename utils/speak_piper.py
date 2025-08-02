import os
import re
import argparse
import datetime
import subprocess
from typing import Optional
import soundfile as sf
import numpy as np

import glob
import shutil
import subprocess
import torch
from piper.voice import PiperVoice

# ========================
# Config
# ========================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUTPUT_DIR = os.path.join(BASE_DIR, "osm_assistant_speaker_audio")
MODEL_DIR = os.path.join(BASE_DIR, "piper_models")
os.makedirs(MODEL_DIR, exist_ok=True)

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
_piper_models = {}

DEFAULT_LANGUAGE = 'en'
DEFAULT_SPEAKER = 'en_US-lessac-medium'  # ✅ safer default voice

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

def get_piper_model(language: str = 'en', speaker: Optional[str] = None):
    """
    Load a Piper TTS model for the given language/speaker.
    Auto-downloads into MODEL_DIR using --data-dir if missing.
    """
    speaker = speaker or SUPPORTED_SPEAKERS.get(language, DEFAULT_SPEAKER)
    key = f"{language}_{speaker}".lower()
    model_path = os.path.join(MODEL_DIR, f"{speaker}.onnx")
    config_path = os.path.join(MODEL_DIR, f"{speaker}.onnx.json")

    # ✅ Download if files missing
    if not (os.path.isfile(model_path) and os.path.isfile(config_path)):
        print(f"[piper] ⚠️ Model '{speaker}' not found locally. Attempting download...")
        try:
            subprocess.run(
                [
                    "python3", "-m", "piper.download_voices",
                    "--data-dir", MODEL_DIR,
                    speaker
                ],
                check=True
            )

            # Check download success
            downloaded_files = glob.glob(os.path.join(MODEL_DIR, f"{speaker}*"))
            if not downloaded_files:
                raise FileNotFoundError(
                    f"No downloaded files found for '{speaker}' in {MODEL_DIR}'"
                )

            print(f"[piper] ✅ Download complete: {downloaded_files}")

        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"Failed to download Piper model '{speaker}'. "
                f"Ensure 'piper' is installed and the speaker name is valid.\n{e}"
            )

    # ✅ Load the model
    if key not in _piper_models:
        print(f"[piper] ⏬ Loading Piper model: {speaker}")
        _piper_models[key] = PiperVoice.load(model_path, use_cuda=(DEVICE == "cuda"))

    return _piper_models[key]

def clean_sentences(text: str):
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text.strip()) if s.strip()]


def speak(
    text: str,
    language: str = 'en',
    speaker_key: str = None,
    speed: float = 1.0,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    return_audio: bool = False
) -> str:
    """
    Convert text to speech using Coqui Piper.
    """
    print("[piper] ✅ Entered speak()")
    os.makedirs(output_dir, exist_ok=True)

    sentences = clean_sentences(text)

    if len(sentences) > 1:
        print("[piper] ⚡ Fast mode: limiting to first sentence for speed")
        sentences = [sentences[0]]

    lang_code = language.lower()[:2]
    speaker = speaker_key or SUPPORTED_SPEAKERS.get(lang_code, DEFAULT_SPEAKER)

    model = get_piper_model(language=lang_code, speaker=speaker)

    sample_rate = 22050
    full_audio = np.zeros(0, dtype=np.float32)
    silence_between = np.zeros(int(0.3 * sample_rate), dtype=np.float32)

    print("[piper] ✅ Starting synthesis")
    for sent in sentences:
        audio_chunks = list(model.synthesize(sent))
        if not audio_chunks:
            print(f"[piper] ⚠️ Empty audio returned for sentence: '{sent}', skipping.")
            continue

        # ✅ Extract bytes from AudioChunk objects
        audio_data = b''.join(chunk.data for chunk in audio_chunks if hasattr(chunk, "data"))
        if not audio_data:
            print(f"[piper] ⚠️ No audio data in chunks for sentence: '{sent}', skipping.")
            continue

        wav = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0

        if wav.size == 0:
            print(f"[piper] ⚠️ Empty waveform returned for sentence: '{sent}', skipping.")
            continue

        full_audio = np.concatenate([full_audio, wav, silence_between])


    if speed != 1.0:
        indices = np.arange(0, len(full_audio), speed)
        indices = indices[indices < len(full_audio)].astype(int)
        full_audio = full_audio[indices]

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    wav_path = os.path.join(output_dir, f"tts_{timestamp}.wav")
    sf.write(wav_path, full_audio, sample_rate)

    print(f"[piper] ✅ Saved TTS to '{wav_path}'")
    return (full_audio, sample_rate) if return_audio else wav_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate speech from text using Coqui Piper TTS."
    )
    parser.add_argument("text", help="The text to speak.")
    parser.add_argument("--language", default="en", help="Language code (default: en).")
    parser.add_argument("--speaker", help="Speaker key (must exist in Piper voices).")
    parser.add_argument("--speed", type=float, default=1.0, help="Speech speed multiplier.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Where to save the final WAV.")
    args = parser.parse_args()

    speak(
        text=args.text,
        language=args.language,
        speaker_key=args.speaker,
        speed=args.speed,
        output_dir=args.output_dir
    )
