import os
import re
import argparse
import datetime
import torch
import torchaudio
from pydub import AudioSegment
import numpy as np
import logging
import warnings
import torch

# m whisper.whisper import model
import whisper
model = whisper.load_model("base")
os.environ["TORCH_CPP_LOG_LEVEL"] = "ERROR"
warnings.filterwarnings("ignore")
torch._C._jit_set_profiling_mode(False)
torch._C._jit_set_profiling_executor(False)

# Base path: project root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUTPUT_DIR = os.path.join(BASE_DIR, "osm_assistant_speaker_audio")

device = "cuda" if torch.cuda.is_available() else "cpu"

def get_silero_model(language='en', speaker='lj_v2'):
    try:
        model, _ = torch.hub.load(
            repo_or_dir='snakers4/silero-models',
            model='silero_tts',
            language=language,
            speaker=speaker
        )
        
        model.to('cpu')  # Explicitly set to CPU
        model.eval()

        return model
    except Exception as e:
        raise RuntimeError(f"❌ Failed to load Silero TTS model: {e}")

def clean_sentences(text):
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text.strip()) if s.strip()]

def speak(text: str, language: str, speaker_key: str, speed: float = 1.0, output_dir: str = DEFAULT_OUTPUT_DIR) -> str:
    os.makedirs(output_dir, exist_ok=True)

    sentences = clean_sentences(text)
    lang_code = language.lower()[:2]

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

    speaker = SUPPORTED_SPEAKERS.get(lang_code, 'lj_v2')
    model = get_silero_model(language=lang_code, speaker=speaker)
    sample_rate = 48000

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    wav_paths = []

    print(" > Text split to sentences.")
    for i, sentence in enumerate(sentences):
        out_path = os.path.join(output_dir, f"batch_{i}.wav")
        audio = model.apply_tts(sentence, sample_rate)
        print(f"Sentence {i}: shape={audio.shape}, max={np.max(audio)}, min={np.min(audio)}")

        
        # Ensure waveform is a 2D FloatTensor of shape (1, N)
        audio_np = np.array(audio, dtype=np.float32).squeeze()
        waveform = torch.from_numpy(audio_np).unsqueeze(0)

        torchaudio.save(out_path, waveform, sample_rate=sample_rate)
        wav_paths.append(out_path)

    combined = AudioSegment.silent(duration=500)
    for path in wav_paths:
        seg = AudioSegment.from_wav(path)
        combined += seg + AudioSegment.silent(duration=300)

    final_path = os.path.join(output_dir, f"tts_{timestamp}.wav")
    combined.export(final_path, format="wav")

    for p in wav_paths:
        try:
            os.remove(p)
        except OSError:
            pass

    print(f"[speak] Saved Silero TTS to '{final_path}'")
    return final_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate speech from text using Silero TTS.")
    parser.add_argument("text", help="The text to speak.")
    parser.add_argument("--language", default="en", help="Language (default: en).")
    parser.add_argument("--speaker", required=True, help="Speaker name (for folder consistency only)")
    parser.add_argument("--speed", type=float, default=1.0, help="Speech speed multiplier (currently unused).")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Where to save the final WAV.")
    args = parser.parse_args()

    speak(
        text=args.text,
        language=args.language,
        speaker_key=args.speaker,
        speed=args.speed,
        output_dir=args.output_dir
    )
