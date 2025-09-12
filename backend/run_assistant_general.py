# backend/run_assistant_general.py
import os
import warnings
import logging
import argparse
import time

# Quiet some libs (optional)
os.environ["TORCH_CPP_LOG_LEVEL"] = "ERROR"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
os.environ["TF_CPP_MIN_VLOG_LEVEL"] = "3"
warnings.filterwarnings("ignore")
logging.getLogger("tensorflow").setLevel(logging.ERROR)

from backend.utils.bitnet_singleton import stream_chat, chat  # <-- bitnet.cpp backend
from backend.utils.transcribe import record_and_transcribe
from backend.utils.speak_piper import speak, find_best_piper_model, MODEL_DIR


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
        # Heuristics by script
        s = text
        if any("\u3040" <= ch <= "\u30ff" or "\u31f0" <= ch <= "\u31ff" for ch in s):  # Hiragana/Katakana
            return "ja"
        if any("\u4e00" <= ch <= "\u9fff" for ch in s):  # CJK Unified Ideographs (likely zh)
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


def main(
    speaker,
    language,            # "auto" will detect from question
    speed,
    text,
    text_file,
    output_mode="stream",  # default to stream
    system_prompt="You are a helpful AI assistant for everyday tasks, please always respond in the same language as the question",
    max_new_tokens=256,
    temperature=0.7,
    top_p=0.95,
    ctx=4096,
    threads=None,
    bitnet_bin="bitnet",
    bitnet_model=None,
    extra_args=None,
):
    if not speaker:
        print("❌ You must specify a --speaker.")
        return

    # Step 1: Get question
    print("🕒 Step 1: Getting question...")
    t1 = time.time()
    question = get_question(text=text, text_file=text_file)
    t2 = time.time()
    print(f"✅ Got question: {question}")
    print(f"⏱️ Step 1 duration: {t2 - t1:.2f} seconds\n")

    # Auto-detect language if needed
    if (language is None) or (language.strip().lower() == "auto"):
        language = detect_language(question)
        print(f"🌐 Detected language: {language}")

    # Prepare TTS model path once
    model_path_tts = find_best_piper_model(MODEL_DIR, language, speaker)

    # Step 2: Ask BitNet (streaming)
    print("🕒 Step 2: Asking BitNet (streaming via bitnet.cpp)...")
    t3 = time.time()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]

    collected = []

    # Speed influences streaming chunk cadence in bitnet_singleton.stream_chat:
    #   - <=1.0: sentence-level
    #   - 1.0~1.5: phrase-level (commas etc.) if long enough
    #   - >=1.5: aggressive phrase-level / long-run flushes
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
            speed=speed,                 # <-- speed-aware chunking
            min_phrase_chars=100,        # tune if you want larger/smaller chunks
        )

        if output_mode == "stream":
            print("🔊 Streaming as it generates...\n")
            for chunk in gen:
                # Show user immediately
                print(chunk, end="", flush=True)
                collected.append(chunk)
                # Speak this chunk now
                speak(
                    chunk,
                    language=language,
                    speaker_key=model_path_tts,
                    speed=speed,
                    output_mode="stream"
                )
            print()  # newline after stream
            response_text = "".join(collected).strip()
        else:
            # Non-streaming: just collect and speak once
            for chunk in gen:
                print(chunk, end="", flush=True)
                collected.append(chunk)
            print()
            response_text = "".join(collected).strip()

    except Exception as e:
        print(f"\n❌ BitNet inference failed: {e}")
        return

    t4 = time.time()
    print(f"\n⏱️ Step 2 duration: {t4 - t3:.2f} seconds\n")

    # Step 3: Speak response (file mode only; stream mode already spoke)
    if output_mode != "stream":
        print("🕒 Step 3: Speaking response with TTS...")
        t5 = time.time()
        try:
            output = speak(
                response_text,
                language=language,
                speaker_key=model_path_tts,
                speed=speed,
                output_mode="file"
            )
        except Exception as e:
            print(f"❌ TTS failed: {e}")
            return
        t6 = time.time()
        print(f"✅ Finished speaking.")
        print(f"🔉 Output audio: {output}")
        print(f"⏱️ Step 3 duration: {t6 - t5:.2f} seconds\n")

    total_time = time.time() - t1
    print(f"🎉 Assistant process completed in {total_time:.2f} seconds.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the general-purpose voice assistant (BitNet via bitnet.cpp, streaming).")
    parser.add_argument("--speaker", type=str, default="amy", help="Speaker name (matches speaker folder)")
    parser.add_argument("--language", type=str, default="auto", help="TTS language code (or 'auto' to detect from input)")
    parser.add_argument("--speed", type=float, default=1.0, help="Speech speed multiplier (also influences chunk size)")
    parser.add_argument("--text", type=str, help="Provide a question as text input instead of recording")
    parser.add_argument("--text-file", type=str, help="Provide a question via a text file instead of recording")
    parser.add_argument("--output-mode", type=str, choices=["file", "stream"], default="stream",
                        help="If 'stream' (default), each chunk is spoken as soon as it's generated.")
    # LLM / bitnet.cpp
    parser.add_argument("--system-prompt", type=str,
                        default="You are a helpful AI assistant for everyday tasks, please always respond in the same language as the question",
                        help="System instruction to steer responses.")
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--ctx", type=int, default=4096)
    parser.add_argument("--threads", type=int, default=None, help="CPU threads (default: os.cpu_count())")
    parser.add_argument("--bitnet-bin", type=str, default="bitnet", help="Path to the bitnet.cpp binary")
    parser.add_argument("--bitnet-model", type=str, default=None,
                        help="Path to a .gguf file or a directory containing GGUF files. "
                             "Default: backend/models/microsoft/bitnet-b1.58-2B-4T-gguf/")
    parser.add_argument("--extra-args", type=str, nargs="*", default=None,
                        help="Extra args passed to the bitnet.cpp binary (advanced)")

    args = parser.parse_args()

    main(
        speaker=args.speaker,
        language=args.language,
        speed=args.speed,
        text=args.text,
        text_file=args.text_file,
        output_mode=args.output_mode,
        system_prompt=args.system_prompt,
        max_new_tokens=args.max_new_tokens,
        temperature=args.temperature,
        top_p=args.top_p,
        ctx=args.ctx,
        threads=args.threads,
        bitnet_bin=args.bitnet_bin,
        bitnet_model=args.bitnet_model,
        extra_args=args.extra_args,
    )
