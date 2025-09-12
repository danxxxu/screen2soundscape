# backend/run_assistant_general.py
"""
General-purpose voice assistant runner using BitNet (bitnet.cpp).

This script shells out to the bitnet.cpp runtime for maximum speed.
- It builds a simple chat-style prompt (system + user).
- It invokes the bitnet binary with the provided GGUF model.
- It captures stdout and uses that as the assistant reply.
- Then it speaks the reply via Piper TTS.

Example:
  python -m backend.run_assistant_general \
    --speaker amy \
    --text "Where are the top 10 tallest mountains" \
    --output-mode file
"""

import os
import sys
import glob
import shlex
import warnings
import logging
import argparse
import time
import subprocess

# Suppress noisy logs before imports
os.environ["TORCH_CPP_LOG_LEVEL"] = "ERROR"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
os.environ["TF_CPP_MIN_VLOG_LEVEL"] = "3"

warnings.filterwarnings("ignore")
logging.getLogger("tensorflow").setLevel(logging.ERROR)

# --- App imports (unchanged) ---
from backend.utils.transcribe import record_and_transcribe
from backend.utils.speak_piper import speak, find_best_piper_model, MODEL_DIR


# ---------- Utilities ----------

def get_question(text=None, text_file=None):
    """
    Returns the user's question from:
      - direct text argument
      - a text file
      - or microphone transcription (fallback)
    """
    if text:
        return text.strip()
    elif text_file and os.path.isfile(text_file):
        with open(text_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    else:
        return record_and_transcribe()


def _project_root():
    return os.path.dirname(os.path.dirname(__file__))


def default_gguf_dir():
    """
    Default location where GGUF was downloaded (you can override with --bitnet-model).
    """
    return os.path.join(_project_root(), "models", "microsoft", "bitnet-b1.58-2B-4T-gguf")


def _prefer_gguf(files):
    """
    Prefer i2_s quant if available, else any *.gguf (largest lexicographically last by default sort).
    """
    if not files:
        return None
    # Prefer i2_s first
    for f in files:
        name = os.path.basename(f).lower()
        if "i2_s" in name:
            return f
    # Otherwise just pick the first
    return files[0]


def find_gguf_model(path_hint: str | None) -> str | None:
    """
    Try to resolve a usable GGUF path.
    - If path_hint points to a file and endswith .gguf -> return it.
    - If path_hint is a dir -> search for *.gguf inside.
    - If path_hint is None -> try default dir.
    """
    candidates = []

    def search_dir(d):
        if not os.path.isdir(d):
            return []
        # Common naming: ggml-model-*.gguf / *.gguf
        hits = glob.glob(os.path.join(d, "*.gguf"))
        # If repo layout nested, search one level deeper too
        if not hits:
            hits = glob.glob(os.path.join(d, "**", "*.gguf"), recursive=True)
        return sorted(hits)

    if path_hint:
        if os.path.isfile(path_hint) and path_hint.endswith(".gguf"):
            return path_hint
        if os.path.isdir(path_hint):
            candidates = search_dir(path_hint)
    else:
        candidates = search_dir(default_gguf_dir())

    return _prefer_gguf(candidates)


def build_chat_prompt(system_prompt: str, user_question: str) -> str:
    """
    Build a robust, model-agnostic chat prompt. We avoid framework-specific tokens
    to keep compatibility with bitnet.cpp CLI.

    If you later enable a native chat mode flag in bitnet.cpp, you can switch this
    to that template. For now this works well in practice.
    """
    return (
        f"System instruction:\n{system_prompt.strip()}\n\n"
        f"User:\n{user_question.strip()}\n\n"
        f"Assistant:\n"
    )


def run_bitnet_cpp(
    bitnet_bin: str,
    model_path: str,
    prompt: str,
    max_new_tokens: int = 256,
    threads: int | None = None,
    ctx: int = 4096,
    temperature: float = 0.7,
    top_p: float = 0.95,
    extra_args: list[str] | None = None,
    timeout_sec: int | None = None,
) -> str:
    """
    Invoke the bitnet.cpp runtime as a subprocess and return its generated text.

    We assume a llama.cpp-like CLI (many bitnet.cpp builds follow this pattern):
      <bin> -m <model.gguf> -p "<prompt>" -n <tokens> -t <threads> -c <ctx> --temp <T> --top-p <P>

    If your binary uses different flags, pass them via `extra_args` or update below.
    """
    if not os.path.isfile(model_path):
        raise FileNotFoundError(f"GGUF model not found: {model_path}")

    if threads is None:
        threads = os.cpu_count() or 4

    # Build command; prefer list form (no shell=True) to avoid quoting issues
    cmd = [
        bitnet_bin,
        "-m", model_path,
        "-p", prompt,
        "-n", str(max_new_tokens),
        "-t", str(threads),
        "-c", str(ctx),
        "--temp", str(temperature),
        "--top-p", str(top_p),
    ]

    if extra_args:
        cmd.extend(extra_args)

    try:
        # Capture stdout/stderr; model prints tokens progressively — we wait for completion here.
        # If you want streaming audio, you could stream lines and TTS incrementally instead.
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            text=True,
            timeout=timeout_sec,
        )
    except FileNotFoundError as e:
        raise FileNotFoundError(
            f"bitnet.cpp binary not found: {bitnet_bin}\n"
            f"Make sure it exists and is executable, or pass --bitnet-bin / set it on PATH."
        ) from e

    if proc.returncode != 0:
        # Surface error details for easier debugging
        raise RuntimeError(
            "bitnet.cpp failed with non-zero exit code.\n"
            f"Command: {' '.join(shlex.quote(x) for x in cmd)}\n"
            f"STDERR:\n{proc.stderr}"
        )

    # Many CLIs print prompts back before the answer. We heuristically take stdout as the reply.
    # If your binary has a special flag to print ONLY the completion, add it via --extra-args.
    output = proc.stdout.strip()

    # In case the binary echoes the prompt, try to split on last occurrence of our 'Assistant:' cue.
    if "Assistant:" in prompt:
        idx = output.rfind("Assistant:")
        if idx != -1:
            maybe = output[idx + len("Assistant:") :].strip()
            if maybe:
                return maybe

    return output


# ---------- Main pipeline ----------

def main(
    speaker: str,
    language: str,
    speed: float,
    text: str | None,
    text_file: str | None,
    output_mode: str = "file",
    system_prompt: str = "You are a helpful AI assistant for everyday tasks, please always respond in the same language as the question",
    max_new_tokens: int = 256,
    temperature: float = 0.7,
    top_p: float = 0.95,
    ctx: int = 4096,
    threads: int | None = None,
    bitnet_bin: str = "bitnet",  # assume available on PATH; override if needed
    bitnet_model: str | None = None,  # file or directory; auto-detect if None
    extra_args: list[str] | None = None,
    timeout_sec: int | None = None,
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

    # Resolve GGUF model
    model_path = find_gguf_model(bitnet_model)
    if not model_path:
        print("❌ Could not find a GGUF model. Provide --bitnet-model pointing to a .gguf file or its folder.")
        print(f"   Tried default: {default_gguf_dir()}")
        return
    print(f"📦 Using GGUF model: {model_path}")

    # Step 2: Ask BitNet (bitnet.cpp)
    print("🕒 Step 2: Asking BitNet via bitnet.cpp...")
    t3 = time.time()
    try:
        prompt = build_chat_prompt(system_prompt, question)
        response_text = run_bitnet_cpp(
            bitnet_bin=bitnet_bin,
            model_path=model_path,
            prompt=prompt,
            max_new_tokens=max_new_tokens,
            threads=threads,
            ctx=ctx,
            temperature=temperature,
            top_p=top_p,
            extra_args=extra_args,
            timeout_sec=timeout_sec,
        )
    except Exception as e:
        print(f"❌ BitNet inference failed: {e}")
        return
    t4 = time.time()

    print("✅ BitNet response:")
    print(response_text)
    print(f"\n⏱️ Step 2 duration: {t4 - t3:.2f} seconds\n")

    # Step 3: Speak response
    print("🕒 Step 3: Speaking response with TTS...")
    t5 = time.time()
    try:
        model_path_tts = find_best_piper_model(MODEL_DIR, language, speaker)
        output = speak(
            response_text,
            language=language,
            speaker_key=model_path_tts,
            speed=speed,
            output_mode=output_mode
        )
    except Exception as e:
        print(f"❌ TTS failed: {e}")
        return
    t6 = time.time()
    print(f"✅ Finished speaking.")
    print(f"🔉 Output audio: {output}")
    print(f"⏱️ Step 3 duration: {t6 - t5:.2f} seconds\n")

    total_time = t6 - t1
    print(f"🎉 Assistant process completed in {total_time:.2f} seconds.")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the general-purpose voice assistant (BitNet via bitnet.cpp).")
    parser.add_argument("--speaker", type=str, default="amy", help="Speaker name (matches speaker folder)")
    parser.add_argument("--language", type=str, default="en", help="Language key for TTS")
    parser.add_argument("--speed", type=float, default=1.0, help="Speech speed multiplier")
    parser.add_argument("--text", type=str, help="Provide a question as text input instead of recording")
    parser.add_argument("--text-file", type=str, help="Provide a question via a text file instead of recording")
    parser.add_argument("--output-mode", type=str, choices=["file", "stream"], default="file",
                        help="Output mode for TTS: 'file' or 'stream' (default: file)")

    # BitNet/bitnet.cpp options
    parser.add_argument("--system-prompt", type=str,
                        default="You are a helpful AI assistant for everyday tasks, please always respond in the same language as the question",
                        help="System instruction used to steer responses")
    parser.add_argument("--max-new-tokens", type=int, default=256, help="Maximum new tokens to generate")
    parser.add_argument("--temperature", type=float, default=0.7, help="Sampling temperature")
    parser.add_argument("--top-p", type=float, default=0.95, help="Top-p nucleus sampling")
    parser.add_argument("--ctx", type=int, default=4096, help="Context length to allocate in bitnet.cpp")
    parser.add_argument("--threads", type=int, default=None, help="Number of CPU threads (defaults to os.cpu_count())")
    parser.add_argument("--bitnet-bin", type=str, default="bitnet",
                        help="Path to the bitnet.cpp binary (or leave 'bitnet' if it's on PATH)")
    parser.add_argument("--bitnet-model", type=str, default=None,
                        help="Path to a .gguf file OR a directory containing GGUF files. "
                             "If not provided, will try: ./backend/models/microsoft/bitnet-b1.58-2B-4T-gguf")
    parser.add_argument("--timeout-sec", type=int, default=None, help="Kill generation if it exceeds this many seconds")
    parser.add_argument("--extra-args", type=str, nargs="*", default=None,
                        help="Extra args to pass to the bitnet.cpp binary (advanced)")

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
        timeout_sec=args.timeout_sec,
    )
