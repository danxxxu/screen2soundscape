import os
import re
import argparse
import datetime
from typing import Tuple, List

import numpy as np
import soundfile as sf
import tensorflow as tf
from tensorflow_tts.inference import AutoProcessor, TFAutoModel

# Base path: project root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUTPUT_DIR = os.path.join(BASE_DIR, "osm_assistant_speaker_audio")

# Global TTS components
processor: AutoProcessor
fastspeech2: TFAutoModel
mb_melgan: TFAutoModel

# Preload TF-TTS models on import
try:
    print("[tf_tts] 🔄 Preloading FastSpeech2 + MB-MelGAN...")
    processor = AutoProcessor.from_pretrained(
        "tensorspeech/tts-fastspeech2-ljspeech-en"
    )
    fastspeech2 = TFAutoModel.from_pretrained(
        config_path="tensorspeech/tts-fastspeech2-ljspeech-en/config.json",
        checkpoint_path="tensorspeech/tts-fastspeech2-ljspeech-en/model.ckpt"
    )
    mb_melgan = TFAutoModel.from_pretrained(
        config_path="tensorspeech/tts-mb_melgan-ljspeech-en/config.json",
        checkpoint_path="tensorspeech/tts-mb_melgan-ljspeech-en/model.ckpt"
    )
    print("[tf_tts] ✅ Models preloaded successfully")
except Exception as e:
    print(f"[tf_tts] ⚠️ Failed to preload models: {e}")


def clean_sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text.strip()) if s.strip()]


def synthesize_sentence(sentence: str, speed: float = 1.0) -> np.ndarray:
    # Text -> sequence IDs
    input_ids = processor.text_to_sequence(sentence, inference=True)
    # FastSpeech2 inference: produce mel spectrogram
    mel_before, mel_after, _, _ = fastspeech2.inference(
        tf.expand_dims(tf.convert_to_tensor(input_ids, dtype=tf.int32), 0),
        speaker_ids=tf.convert_to_tensor([0], dtype=tf.int32),
        speed_ratios=tf.convert_to_tensor([speed], dtype=tf.float32)
    )
    # Vocoder: mel -> waveform
    audio = mb_melgan.inference(mel_after)[0, :, 0]
    return audio.numpy().astype(np.float32)


def speak(
    text: str,
    speed: float = 1.0,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    fast_mode: bool = True
) -> Tuple[np.ndarray, int]:
    """
    Convert text to speech using TensorFlowTTS. Returns (audio, sample_rate).
    If fast_mode=True, only the first sentence is synthesized.
    """
    os.makedirs(output_dir, exist_ok=True)
    sentences = clean_sentences(text)
    if fast_mode and len(sentences) > 1:
        sentences = [sentences[0]]

    sample_rate = 22050  # MB-MelGAN default
    silence_between = np.zeros(int(0.2 * sample_rate), dtype=np.float32)
    full_audio = np.zeros(0, dtype=np.float32)

    print(f"[tf_tts] Synthesizing {len(sentences)} sentence(s) at speed={speed}")
    for sent in sentences:
        wav = synthesize_sentence(sent, speed=speed)
        full_audio = np.concatenate([full_audio, wav, silence_between])

    # Save to disk
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    wav_path = os.path.join(output_dir, f"tts_tf_{timestamp}.wav")
    sf.write(wav_path, full_audio, sample_rate)
    print(f"[tf_tts] ✅ Saved TTS to '{wav_path}'")

    return full_audio, sample_rate


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate speech via TensorFlowTTS.")
    parser.add_argument("text", help="Text to speak.")
    parser.add_argument(
        "--speed", type=float, default=1.0,
        help="Speech speed multiplier (1.0 = normal)."
    )
    parser.add_argument(
        "--output-dir", default=DEFAULT_OUTPUT_DIR,
        help="Directory to save WAV files."
    )
    parser.add_argument(
        "--no-fast", action="store_true",
        help="Disable fast_mode (synthesize all sentences)."
    )
    args = parser.parse_args()
    speak(
        text=args.text,
        speed=args.speed,
        output_dir=args.output_dir,
        fast_mode=not args.no_fast
    )
