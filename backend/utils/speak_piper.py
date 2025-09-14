# backend/utils/speak_piper.py
import os
import re
import unicodedata
import datetime
import wave
import glob
import io
from pathlib import Path
from typing import Optional, List, Dict, Tuple

from piper.voice import PiperVoice, SynthesisConfig
from pydub import AudioSegment
import torch

# ========================
# Config / Paths
# ========================
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Default to backend/piper_models (can override with env)
MODEL_DIR = os.getenv("PIPER_MODELS_ROOT", os.path.join(ROOT_DIR, "piper_models"))
os.makedirs(MODEL_DIR, exist_ok=True)

DEFAULT_OUTPUT_DIR = os.path.join(ROOT_DIR, "osm_assistant_speaker_audio")
os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)

DEFAULT_LANGUAGE = "en"
DEFAULT_SPEAKER = "en_US-lessac-medium"

# Fallback mapping for convenience (used only if caller doesn’t pass a speaker)
SUPPORTED_SPEAKERS = {
    "en": "en_US-lessac-medium",
    "fr": "fr_FR-siwis-low",
    "es": "es_ES-carlfm-low",
    "de": "de_DE-thorsten-low",
    "ru": "ru_RU-ruslan-low",
    "uk": "uk_UA-ukrainian-low",
    "kk": "kk_KZ-aisuluu-low",
    "uz": "uz_UZ-dilnavoz-low",
}

QUALITY_ORDER = ["high", "medium", "low"]

# Cache of loaded PiperVoice models
_piper_models: Dict[str, PiperVoice] = {}


# ========================
# Helpers
# ========================
def _length_scale_from_speed(speed: float) -> float:
    """Map speed factor → Piper length_scale (inverse)."""
    if not speed or speed <= 0:
        speed = 1.0
    ls = 1.0 / speed
    # keep it sane to avoid artifacts
    return max(0.4, min(3.0, ls))


def clean_text(text: str, lang2: str) -> str:
    """Normalize text. Remove accents only for English."""
    text = text.replace("’", "'").replace("‘", "'").replace("`", "'")
    if lang2.startswith("en"):
        text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-zA-Z0-9À-ÖØ-öø-ÿ\s.,!?'\-]", " ", text).strip()


def chunk_text(text: str, max_len: int = 200) -> List[str]:
    """Split on sentence boundaries; if a sentence is long, split into chunks."""
    chunks = re.split(r"(?<=[.!?])\s+", text)
    result: List[str] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        if len(chunk) > max_len:
            parts = [chunk[i : i + max_len] for i in range(0, len(chunk), max_len)]
            result.extend(parts)
        else:
            result.append(chunk)
    return result


def _dedup(seq: List[str]) -> List[str]:
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out


def _list_available_voices(model_root: str) -> Dict[str, List[str]]:
    """
    Return mapping like {"en": ["en/en_US/amy", "en/en_GB/sarah", ...], ...}
    based on directory structure that contains *.onnx files.
    """
    voices: Dict[str, List[str]] = {}
    for onnx in glob.glob(os.path.join(model_root, "**", "*.onnx"), recursive=True):
        rel = os.path.relpath(onnx, model_root)
        parts = Path(rel).parts
        if len(parts) < 2:
            continue
        lang = parts[0].lower()
        hint = "/".join(parts[:-1])  # path without filename
        voices.setdefault(lang, [])
        if hint not in voices[lang]:
            voices[lang].append(hint)
    # sort for nicer printing
    for k in voices:
        voices[k].sort()
    return voices


def _score_candidate(path: str, lang2: str, speaker: str) -> Tuple[int, int]:
    """
    Lower score is better. Two keys:
      - quality rank: high(0) < medium(1) < low(2) < other(3)
      - language closeness: path contains '/<lang2>/' earlier
    """
    p_lower = path.lower()
    # quality rank
    q_rank = 3
    for idx, q in enumerate(QUALITY_ORDER):
        if f"{os.sep}{q}{os.sep}" in p_lower:
            q_rank = idx
            break
    # language closeness
    lang_hit = 0 if f"{os.sep}{lang2}{os.sep}" in p_lower else 1
    return (q_rank, lang_hit)


def _find_candidate_models(model_root: str, language: str, speaker: str) -> List[str]:
    """
    Try common Piper layouts to find a model .onnx file:
      backend/piper_models/<lang>/**/<speaker>/<quality>/*.onnx
      backend/piper_models/<lang>/**/<speaker>/*.onnx
      backend/piper_models/**/<speaker>/*.onnx
      fallback: any onnx containing speaker name
    """
    lang2 = (language or DEFAULT_LANGUAGE).lower()[:2]
    spk = (speaker or "").lower()

    candidates: List[str] = []

    # Prefer quality subdirs first
    for q in QUALITY_ORDER:
        candidates += glob.glob(os.path.join(model_root, lang2, "**", spk, q, "*.onnx"), recursive=True)

    # Then any .onnx under a speaker folder within the lang tree
    candidates += glob.glob(os.path.join(model_root, lang2, "**", spk, "*.onnx"), recursive=True)

    # Speaker folder anywhere
    candidates += glob.glob(os.path.join(model_root, "**", spk, "*.onnx"), recursive=True)

    # Any onnx file with the speaker name in it
    candidates += glob.glob(os.path.join(model_root, "**", f"*{spk}*.onnx"), recursive=True)

    candidates = _dedup(candidates)

    # Sort by (quality, language closeness), then prefer 'model.onnx'
    def sort_key(p: str):
        q_rank, lang_hit = _score_candidate(p, lang2, spk)
        base = os.path.basename(p).lower()
        prefer_model = 0 if base == "model.onnx" else 1
        return (q_rank, lang_hit, prefer_model, len(p))  # shorter path last arg fallback

    candidates.sort(key=sort_key)
    return candidates


# ========================
# Public API
# ========================
def find_best_piper_model(model_root: str, language: str, speaker: str) -> str:
    """
    Return path to a Piper .onnx model for the requested language & speaker,
    with clear errors listing alternatives.
    """
    model_root = os.path.abspath(model_root or MODEL_DIR)
    if not os.path.isdir(model_root):
        raise FileNotFoundError(
            f"Piper models root not found: {model_root}\n"
            f"Set PIPER_MODELS_ROOT or place models under backend/piper_models/."
        )

    # If user passed a direct onnx path as 'speaker', use it
    if speaker and speaker.endswith(".onnx") and os.path.isfile(speaker):
        return os.path.abspath(speaker)

    candidates = _find_candidate_models(model_root, language, speaker)
    if candidates:
        return candidates[0]

    # No exact match → show what *is* available
    voices = _list_available_voices(model_root)
    langs = sorted(voices.keys())
    hint_lines = []
    for lang in langs:
        show = ", ".join(voices[lang][:10])
        more = "…" if len(voices[lang]) > 10 else ""
        hint_lines.append(f"  {lang}: {show}{more}")

    lang_msg = "\n".join(hint_lines) if hint_lines else "  (no voices found)"
    raise FileNotFoundError(
        f"No Piper voice for language='{language}' speaker='{speaker}' under {model_root}.\n"
        f"Available voices by language:\n{lang_msg}"
    )


def _resolve_model_and_config(model_path: str) -> Tuple[str, str]:
    """
    Given a .onnx model path, resolve its .json config.
    Handles both '<name>.onnx.json' and 'model.onnx' → 'model.onnx.json'.
    """
    model_path = os.path.abspath(model_path)
    if not os.path.isfile(model_path):
        raise FileNotFoundError(f"Piper model not found: {model_path}")

    # Common: model.onnx + model.onnx.json (same dir)
    cfg_path = model_path + ".json"
    if os.path.isfile(cfg_path):
        return model_path, cfg_path

    # Fallback: any .json in same dir
    cand = list(Path(model_path).parent.glob("*.onnx.json"))
    if cand:
        return model_path, str(cand[0])

    raise FileNotFoundError(
        f"Missing Piper config JSON next to model: {model_path}\n"
        f"Expected: {model_path}.json or any '*.onnx.json' in the same directory."
    )


def get_piper_model(language: str = DEFAULT_LANGUAGE, speaker: Optional[str] = None) -> PiperVoice:
    """
    Load a Piper TTS model from a given speaker name or a full .onnx path.
    Caches loaded models.
    """
    lang2 = (language or DEFAULT_LANGUAGE).lower()[:2]

    # Allow direct path usage
    if speaker and speaker.endswith(".onnx") and os.path.isfile(speaker):
        model_path = speaker
    else:
        speaker = speaker or SUPPORTED_SPEAKERS.get(lang2, DEFAULT_SPEAKER)
        model_path = find_best_piper_model(MODEL_DIR, lang2, speaker)

    model_path, _cfg = _resolve_model_and_config(model_path)

    key = model_path.lower()
    if key not in _piper_models:
        print(f"[piper] ⏬ Loading Piper model: {model_path}")
        _piper_models[key] = PiperVoice.load(model_path, use_cuda=torch.cuda.is_available())

    return _piper_models[key]


# ========================
# Main speak() function
# ========================
def speak(
    text: str,
    language: str = DEFAULT_LANGUAGE,
    speaker_key: Optional[str] = None,
    speed: float = 1.0,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    output_mode: str = "not used",
):
    """
    Convert text to speech using PiperVoice.
    - output_mode="stream" → returns MP3 bytes
    - output_mode="file" → saves MP3 to file and returns file path
    """
    output_mode = 'stream'
    print("[piper] ✅ Entered speak()")
    os.makedirs(output_dir, exist_ok=True)

    lang2 = (language or DEFAULT_LANGUAGE).lower()[:2]
    speaker = speaker_key or SUPPORTED_SPEAKERS.get(lang2, DEFAULT_SPEAKER)
    model = get_piper_model(language=lang2, speaker=speaker)

    text = clean_text(text, lang2)
    chunks = [c for c in chunk_text(text) if c.strip()]

    length_scale = _length_scale_from_speed(speed)
    syn_config = SynthesisConfig(
        volume=1.0,
        length_scale=length_scale,
        noise_scale=1.0,
        noise_w_scale=1.0,
        normalize_audio=True,
    )

    def synth_chunk_to_bytes(chunk: str) -> Tuple[Tuple[int, int, int], bytes]:
        tmp_buf = io.BytesIO()
        with wave.open(tmp_buf, "wb") as tmp_wav:
            model.synthesize_wav(chunk, tmp_wav, syn_config=syn_config)
        tmp_buf.seek(0)
        with wave.open(tmp_buf, "rb") as in_wav:
            params = (in_wav.getnchannels(), in_wav.getsampwidth(), in_wav.getframerate())
            frames = in_wav.readframes(in_wav.getnframes())
        return params, frames

    final_wav = io.BytesIO()
    with wave.open(final_wav, "wb") as out_wav:
        first = True
        ref_params = None
        for idx, chunk in enumerate(chunks):
            params, frames = synth_chunk_to_bytes(chunk)
            if first:
                nch, sampwidth, framerate = params
                out_wav.setnchannels(nch)
                out_wav.setsampwidth(sampwidth)
                out_wav.setframerate(framerate)
                ref_params = params
                first = False
            else:
                if params != ref_params:
                    raise RuntimeError(
                        f"Inconsistent audio params in chunk {idx}: got {params}, expected {ref_params}"
                    )
            out_wav.writeframes(frames)

    final_wav.seek(0)
    mp3_buffer = io.BytesIO()
    AudioSegment.from_file(final_wav, format="wav").export(mp3_buffer, format="mp3")
    print("[piper] ✅ Streaming now")
    return mp3_buffer.getvalue()
