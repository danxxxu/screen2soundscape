# backend/utils/bitnet_singleton.py
"""
bitnet.cpp-backed chat wrapper with sentence-level streaming.

- Prefers a local GGUF in: backend/models/microsoft/bitnet-b1.58-2B-4T-gguf/
- Falls back to a model path provided via `bitnet_model` args.
- Uses a simple System/User/Assistant prompt. We stream stdout from the process,
  wait until we detect the "Assistant:" sentinel, then yield sentences as they complete.

Expose two public entry points:
  - chat(messages, ...) -> str              # full, blocking
  - stream_chat(messages, ...) -> iterator  # yields sentences as they complete
"""

import os
import re
import glob
import shlex
import subprocess
from typing import Iterable, Iterator, List, Dict, Optional


# ------- Paths / discovery -------

def _project_root() -> str:
    return os.path.dirname(os.path.dirname(__file__))

def default_gguf_dir() -> str:
    return os.path.join(_project_root(), "models", "microsoft", "bitnet-b1.58-2B-4T-gguf")

def _prefer_gguf(files: List[str]) -> Optional[str]:
    if not files:
        return None
    for f in files:
        if "i2_s" in os.path.basename(f).lower():
            return f
    return files[0]

def find_gguf_model(path_hint: Optional[str] = None) -> Optional[str]:
    """
    Resolve a usable GGUF path.
    - If `path_hint` is a file *.gguf -> return it
    - If `path_hint` is a dir -> search inside for *.gguf (prefers i2_s)
    - Else, search the default gguf dir
    """
    def search_dir(d: str) -> List[str]:
        if not os.path.isdir(d):
            return []
        hits = glob.glob(os.path.join(d, "*.gguf"))
        if not hits:
            hits = glob.glob(os.path.join(d, "**", "*.gguf"), recursive=True)
        return sorted(hits)

    if path_hint:
        if os.path.isfile(path_hint) and path_hint.endswith(".gguf"):
            return path_hint
        if os.path.isdir(path_hint):
            return _prefer_gguf(search_dir(path_hint))
        return None

    return _prefer_gguf(search_dir(default_gguf_dir()))

# ------- Prompting -------

ASSISTANT_TAG = "Assistant:"

def build_chat_prompt(system_prompt: str, user_prompt: str) -> str:
    # Keep it plain-text so any bitnet.cpp build can consume it.
    return (
        f"System instruction:\n{system_prompt.strip()}\n\n"
        f"User:\n{user_prompt.strip()}\n\n"
        f"{ASSISTANT_TAG}\n"
    )

# ------- Streaming process glue -------

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
SENTENCE_RE = re.compile(r"(?<!\b[A-Z])[.!?]+(?=\s|\Z)")        # sentence terminators
PHRASE_RE   = re.compile(r"(?<=[\.\!\?]|[,;:])\s+")             # sentence OR phrase (comma/colon/semicolon)


def strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s)


def _spawn_bitnet(
    bitnet_bin: str,
    model_path: str,
    prompt: str,
    max_new_tokens: int,
    threads: Optional[int],
    ctx: int,
    temperature: float,
    top_p: float,
    extra_args: Optional[List[str]],
) -> subprocess.Popen:
    if not os.path.isfile(model_path):
        raise FileNotFoundError(f"GGUF model not found: {model_path}")

    if threads is None:
        threads = os.cpu_count() or 4

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
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,          # line-buffered
            universal_newlines=True,
        )
    except FileNotFoundError as e:
        raise FileNotFoundError(
            f"bitnet.cpp binary not found: {bitnet_bin}\n"
            f"Command tried: {' '.join(shlex.quote(x) for x in cmd)}"
        ) from e

    return proc

def _iter_model_text(proc: subprocess.Popen, wait_for_tag: str) -> Iterator[str]:
    """
    Yield raw text as it arrives from stdout. We suppress everything until `wait_for_tag`
    is seen in the accumulated buffer so echoed prompt doesn't leak.
    """
    if not proc.stdout:
        return

    buf_all = ""
    saw_tag = False

    # Read character-by-character to minimize latency
    while True:
        ch = proc.stdout.read(1)
        if ch == "" or ch is None:  # EOF
            break
        buf_all += ch

        if not saw_tag:
            if wait_for_tag in buf_all:
                saw_tag = True
            continue
        # After we see the tag, yield the *new* char only
        yield ch

    # Drain stderr on exit for debugging if needed
    proc.wait()
    if proc.returncode not in (0, None):
        if proc.stderr:
            err = proc.stderr.read()
            raise RuntimeError(f"bitnet.cpp exited with {proc.returncode}:\n{err}")


def _pop_chunks(clean: str, speed: float, min_phrase_chars: int) -> Tuple[List[str], str]:
    """
    Decide how much to flush based on speed:
      - speed <= 1.0: sentence-level
      - 1.0 < speed < 1.5: phrase-level (commas etc.) if long enough, else wait for sentence
      - speed >= 1.5: phrase-level aggressively; if chunk is long (>= min_phrase_chars), flush anyway
    Returns (chunks, remainder).
    """
    chunks: List[str] = []

    # Always prefer full sentences if present
    s_matches = list(SENTENCE_RE.finditer(clean))
    if s_matches:
        last_end = s_matches[-1].end()
        chunks.append(clean[:last_end])
        return chunks, clean[last_end:]

    # If speed <= 1, don't flush on phrases
    if speed <= 1.0:
        return chunks, clean

    # Phrase-level boundaries
    p_matches = list(PHRASE_RE.finditer(clean))
    if p_matches:
        last_end = p_matches[-1].end()
        if speed >= 1.5:
            # be aggressive: flush on last phrase boundary or if text is long enough
            chunk = clean[:last_end]
            if len(chunk.strip()) >= 1:
                chunks.append(chunk)
                return chunks, clean[last_end:]
        else:
            # moderate: flush only if chunk is reasonably long
            chunk = clean[:last_end]
            if len(chunk) >= min_phrase_chars:
                chunks.append(chunk)
                return chunks, clean[last_end:]

    # If very long without punctuation and speed is high, flush a big chunk
    if speed >= 1.5 and len(clean) >= max(80, min_phrase_chars):
        chunks.append(clean)
        return chunks, ""

    return chunks, clean

def stream_chat(
    messages: List[Dict[str, str]],
    *,
    # generation
    max_new_tokens: int = 256,
    temperature: float = 0.7,
    top_p: float = 0.95,
    # runtime
    bitnet_bin: str = "bitnet",
    bitnet_model: Optional[str] = None,    # file or dir; auto-detect if None
    threads: Optional[int] = None,
    ctx: int = 4096,
    extra_args: Optional[List[str]] = None,
) -> Iterator[str]:
    """
    Stream sentences as they complete (naive segmenter). Yields strings that end in . ! or ? (mostly).

    messages: [{"role":"system","content":"..."}, {"role":"user","content":"..."}]
    """
    # Extract content
    system_msg = next((m["content"] for m in messages if m.get("role") == "system"), "")
    user_msg   = next((m["content"] for m in messages if m.get("role") == "user"), "")

    # Resolve gguf
    model_path = find_gguf_model(bitnet_model)
    if not model_path:
        raise FileNotFoundError(
            "No GGUF model found. Provide bitnet_model or place one in "
            f"{default_gguf_dir()}"
        )

    # Build prompt & launch
    prompt = build_chat_prompt(system_msg, user_msg)
    proc = _spawn_bitnet(
        bitnet_bin=bitnet_bin,
        model_path=model_path,
        prompt=prompt,
        max_new_tokens=max_new_tokens,
        threads=threads,
        ctx=ctx,
        temperature=temperature,
        top_p=top_p,
        extra_args=extra_args,
    )

    # Accumulate chars into sentences
    accum = ""
    for ch in _iter_model_text(proc, wait_for_tag=ASSISTANT_TAG):
        accum += ch
        clean = strip_ansi(accum)

        # Find the last full sentence end
        m = SENTENCE_RE.search(clean)
        if m:
            end_idx = m.end()
            sentence = clean[:end_idx]
            remainder = clean[end_idx:]
            # Reset accum to only remainder *including any partial ansi codes stripped already*
            accum = remainder
            # Yield trimmed sentence
            yield sentence

    # Yield leftover tail (if any)
    tail = strip_ansi(accum).strip()
    if tail:
        yield tail

def chat(
    messages: List[Dict[str, str]],
    *,
    max_new_tokens: int = 256,
    temperature: float = 0.7,
    top_p: float = 0.95,
    bitnet_bin: str = "bitnet",
    bitnet_model: Optional[str] = None,
    threads: Optional[int] = None,
    ctx: int = 4096,
    extra_args: Optional[List[str]] = None,
) -> str:
    parts = []
    for sent in stream_chat(
        messages,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
        top_p=top_p,
        bitnet_bin=bitnet_bin,
        bitnet_model=bitnet_model,
        threads=threads,
        ctx=ctx,
        extra_args=extra_args,
        speed=speed,
        min_phrase_chars=min_phrase_chars,
    ):
        parts.append(sent)
    return "".join(parts).strip()
