# backend/run_assistant_general.py
import os

# Suppress noisy logs before imports
os.environ["TORCH_CPP_LOG_LEVEL"] = "ERROR"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
os.environ["TF_CPP_MIN_VLOG_LEVEL"] = "3"

import warnings
import transformers
warnings.filterwarnings("ignore")
transformers.logging.set_verbosity_error()# backend/run_assistant_general.py
"""
General-purpose voice assistant runner using BitNet b1.58 2B4T via Hugging Face transformers.

Usage example:
  python -m backend.run_assistant_general --speaker amy --text "Where are the top 10 tallest mountains" --output-mode file
"""

import os

# Suppress noisy logs before imports
os.environ["TORCH_CPP_LOG_LEVEL"] = "ERROR"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["TF_ENABLE_ONEDNN_OPTS"] = "0"
os.environ["TF_CPP_MIN_VLOG_LEVEL"] = "3"

import warnings
import logging
import argparse
import time

import transformers
warnings.filterwarnings("ignore")
transformers.logging.set_verbosity_error()

# Torch/JIT noise reduction (safe-guarded for version differences)
try:
    import torch
    try:
        torch._C._jit_set_profiling_mode(False)
    except Exception:
        pass
    try:
        torch._C._jit_set_profiling_executor(False)
    except Exception:
        pass
except Exception:
    torch = None  # Torch is required for BitNet, but we don't crash on import

logging.getLogger("tensorflow").setLevel(logging.ERROR)

# --- App imports ---
from backend.utils.bitnet_singleton import chat
from backend.utils.transcribe import record_and_transcribe
from backend.utils.speak_piper import speak, find_best_piper_model, MODEL_DIR


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


def main(
    speaker: str,
    language: str,
    speed: float,
    text: str,
    text_file: str,
    output_mode: str = "file",
    system_prompt: str = "You are a helpful AI assistant for everyday tasks, please always respond in the same language as the question",
    max_new_tokens: int = 256,
    temperature: float = 0.7,
    top_p: float = 0.95,
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

    # Step 2: Ask BitNet
    print("🕒 Step 2: Asking BitNet b1.58 2B4T...")
    t3 = time.time()
    try:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ]
        response_text = chat(
            messages,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            do_sample=True,
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
        model_path = find_best_piper_model(MODEL_DIR, language, speaker)
        output = speak(
            response_text,
            language=language,
            speaker_key=model_path,
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
    parser = argparse.ArgumentParser(description="Run the general-purpose voice assistant (BitNet).")
    parser.add_argument("--speaker", type=str, default="amy", help="Speaker name (matches speaker folder)")
    parser.add_argument("--language", type=str, default="en", help="Language key for TTS")
    parser.add_argument("--speed", type=float, default=1.0, help="Speech speed multiplier")
    parser.add_argument("--text", type=str, help="Provide a question as text input instead of recording")
    parser.add_argument("--text-file", type=str, help="Provide a question via a text file instead of recording")
    parser.add_argument(
        "--output-mode",
        type=str,
        choices=["file", "stream"],
        default="file",
        help="Output mode for TTS: 'file' or 'stream' (default: file)"
    )
    parser.add_argument(
        "--system-prompt",
        type=str,
        default="You are a helpful AI assistant for everyday tasks, please always respond in the same language as the question",
        help="System prompt for the chat template",
    )
    parser.add_argument("--max-new-tokens", type=int, default=256, help="Maximum new tokens to generate")
    parser.add_argument("--temperature", type=float, default=0.7, help="Sampling temperature")
    parser.add_argument("--top-p", type=float, default=0.95, help="Top-p nucleus sampling")

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
    )


import torch
torch._C._jit_set_profiling_mode(False)
torch._C._jit_set_profiling_executor(False)

import logging
logging.getLogger("tensorflow").setLevel(logging.ERROR)

import argparse
import time
import json

from backend.utils.llama_singleton import get_llm
from backend.utils.transcribe import record_and_transcribe
from backend.utils.speak_piper import speak, find_best_piper_model, MODEL_DIR


def get_question(text=None, text_file=None):
    if text:
        return text.strip()
    elif text_file and os.path.isfile(text_file):
        with open(text_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    else:
        return record_and_transcribe()


def _extract_text_from_llm_response(resp):
    """
    Try to extract a plain string from a variety of LLM response formats:
    - OpenAI-like dict: {'choices': [{'text': '...'}]} or {'choices': [{'message': {'content': '...'}}]}
    - Plain string
    - List of strings (join)
    - Objects with .choices and .text/.message.content (best-effort)
    """
    # 1) If it's already a string, return it
    if isinstance(resp, str):
        return resp.strip()

    # 2) OpenAI-like dict
    if isinstance(resp, dict):
        choices = resp.get("choices")
        if isinstance(choices, list) and choices:
            choice0 = choices[0]
            # a) text completion style
            if isinstance(choice0, dict):
                if "text" in choice0 and isinstance(choice0["text"], str):
                    return choice0["text"].strip()
                # b) chat style
                message = choice0.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        return content.strip()
        # fallback to something sensible
        # try 'text' at top-level
        if isinstance(resp.get("text"), str):
            return resp["text"].strip()

    # 3) List of strings -> join
    if isinstance(resp, list) and all(isinstance(x, str) for x in resp):
        return "\n".join(resp).strip()

    # 4) Last resort: stringify
    return str(resp)


def main(speaker, language, speed, text, text_file, output_mode="file"):
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

    # Step 2: Ask LLaMA
    print("🕒 Step 2: Asking LLaMA...")
    t3 = time.time()
    llm = get_llm()
    try:
        raw_response = llm(question)
    except Exception as e:
        print(f"❌ LLaMA inference failed: {e}")
        return
    t4 = time.time()

    # ✅ Only print extracted response text
    response_text = _extract_text_from_llm_response(raw_response)
    print("✅ LLaMA response:")
    print(response_text)
    print(f"\n⏱️ Step 2 duration: {t4 - t3:.2f} seconds\n")


    # Step 3: Speak response
    print("🕒 Step 3: Speaking response with TTS...")
    t5 = time.time()
    model_path = find_best_piper_model(MODEL_DIR, language, speaker)
    output = speak(
        response_text,
        language=language,
        speaker_key=model_path,
        speed=speed,
        output_mode=output_mode
    )
    t6 = time.time()
    print(f"✅ Finished speaking.")
    print(f"🔉 Output audio: {output}")
    print(f"⏱️ Step 3 duration: {t6 - t5:.2f} seconds\n")

    total_time = t6 - t1
    print(f"🎉 Assistant process completed in {total_time:.2f} seconds.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the general-purpose voice assistant.")
    parser.add_argument("--speaker", type=str, default="amy", help="Speaker name (matches speaker folder)")
    parser.add_argument("--language", type=str, default="en", help="Language key for TTS")
    parser.add_argument("--speed", type=float, default=1.0, help="Speech speed multiplier")
    parser.add_argument("--text", type=str, help="Provide a question as text input instead of recording")
    parser.add_argument("--text-file", type=str, help="Provide a question via a text file instead of recording")
    parser.add_argument("--output-mode", type=str, choices=["file", "stream"], default="file",
                        help="Output mode for TTS: 'file' or 'stream' (default: file)")
    args = parser.parse_args()

    main(
        speaker=args.speaker,
        language=args.language,
        speed=args.speed,
        text=args.text,
        text_file=args.text_file,
        output_mode=args.output_mode
    )

# Example
# python -m backend.run_assistant_general --speaker amy --text "Where are the top 10 tallest mountains" --output-mode file
