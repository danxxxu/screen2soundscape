# backend/utils/bitnet_singleton.py
"""
bitnet.cpp-backed chat wrapper with sentence-level streaming.

It supports TWO backends transparently:
  1) C++ CLI binary ("bitnet") if present (fastest)
  2) Official Python runner: BitNet/run_inference.py (fallback, no build needed)

- Prefers a local GGUF in: backend/models/microsoft/bitnet-b1.58-2B-4T-gguf/
- Uses a simple System/User/Assistant prompt. We stream stdout from the process
  and yield sentences as they complete.

Public API (unchanged):
  - chat(messages, ...) -> str              # full, blocking
  - stream_chat(messages, ...) -> iterator  # yields sentences as they complete
"""

import os
import re
import glob
import shlex
import shutil
import subprocess
import sys
from typing import Iterator, List, Dict, Optional

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
    # Keep it plain-text so any backend can consume it.
    return (
        f"System instruction:\n{system_prompt.strip()}\n\n"
        f"User:\n{user_prompt.strip()}\n\n"
        f"{ASSISTANT_TAG}\n"
    )

# ------- Streaming helpers -------

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
def strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s)

# Avoids some abbrev false-positives; flush on sentence terminators.
SENTENCE_RE = re.compile(r"(?<!\b[A-Z])[.!?]+(?=\s|\Z)")

# ------- Runner resolution -------

def _default_py_runner() -> str:
    """
    Auto-detect BitNet/run_inference.py relative to the project root.
    """
    cand = os.path.join(_project_root(), "BitNet", "run_inference.py")
    return cand if os.path.isfile(cand) else ""

def _resolve_runner(bitnet_bin: str) -> dict:
    """
    Decide which runner to use.
    Returns dict:
      {"mode": "bin"|"py",
       "exe": <absolute path to binary or python>,
       "script": <path to run_inference.py or None>,
       "why": <text>}
    """
    # 1) Try C++ binary if user passed an absolute path or it's on PATH
    if bitnet_bin:
        if os.path.isabs(bitnet_bin) and os.path.isfile(bitnet_bin):
            return {"mode": "bin", "exe": bitnet_bin, "script": None, "why": "absolute bitnet binary"}
        found = shutil.which(bitnet_bin)
        if found:
            return {"mode": "bin", "exe": found, "script": None, "why": f"found on PATH ({found})"}

    # 2) Fallback to Python runner if present
    py_script = _default_py_runner()
    if py_script:
        # Prefer current interpreter for best venv compatibility
        py_exe = os.environ.get("PYTHON") or sys.executable or shutil.which("python3") or "python3"
        return {"mode": "py", "exe": py_exe, "script": py_script, "why": f"python runner at {py_script}"}

    # 3) Nothing found
    path_str = os.environ.get("PATH", "")
    raise FileNotFoundError(
        "bitnet.cpp runner not found.\n"
        f"- Tried C++ binary name: '{bitnet_bin or 'bitnet'}' (PATH={path_str})\n"
        f"- Also looked for Python runner at: {_default_py_runner() or '<not found>'}\n"
        "Fix:\n"
        "  • Build the C++ binary and pass --bitnet-bin /abs/path/to/bitnet, OR\n"
        "  • git clone https://github.com/microsoft/BitNet under your project root so BitNet/run_inference.py exists, "
        "then ensure 'pip install -r BitNet/requirements.txt' in your venv."
    )

# ------- Process spawner -------

def _spawn_process(
    runner: dict,
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

    mode = runner["mode"]
    exe  = runner["exe"]

    if mode == "bin":
        # C++ CLI flags
        cmd = [
            exe,
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

    else:
        # Python runner flags (per README: -m, -n, -p, -t, -c, -temp; add -cnv to enable chat-ish mode)
        script = runner["script"]
        cmd = [
            exe, "-u", script,
            "-m", model_path,
            "-n", str(max_new_tokens),
            "-p", prompt,
            "-t", str(threads),
            "-c", str(ctx),
            "-temp", str(temperature),
            "-cnv",
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
            f"Failed to spawn runner ({runner['why']}):\n"
            f"Command tried: {' '.join(shlex.quote(x) for x in cmd)}\n"
            f"PATH was: {os.environ.get('PATH','')}"
        ) from e

    return proc

def _iter_model_text(proc: subprocess.Popen, wait_for_tag: str) -> Iterator[str]:
    """
    Yield raw text as it arrives from stdout. We suppress everything until `wait_for_tag`
    is seen in the accumulated buffer so echoed prompt doesn't leak.

    If the process NEVER echoes the tag, we fall back to yielding the whole stdout buffer.
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

    # Process exit
    proc.wait()
    if proc.returncode not in (0, None):
        if proc.stderr:
            err = proc.stderr.read()
            raise RuntimeError(f"Runner exited with {proc.returncode}:\n{err}")

    # Fallback: if the runner didn't echo the tag at all, yield everything we saw.
    if not saw_tag and buf_all:
        yield buf_all

# ------- Public API -------

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
            "No GGUF model found. Provide --bitnet-model or place one in "
            f"{default_gguf_dir()}"
        )

    # Resolve runner (C++ binary or Python script)
    runner = _resolve_runner(bitnet_bin)

    # Build prompt & launch
    prompt = build_chat_prompt(system_msg, user_msg)
    proc = _spawn_process(
        runner=runner,
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

        # Emit every complete sentence currently available, individually
        start = 0
        for m in SENTENCE_RE.finditer(clean):
            end_idx = m.end()
            sentence = clean[start:end_idx]
            yield sentence
            start = end_idx

        # Keep only the unfinished tail
        accum = clean[start:]

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
    """Blocking convenience wrapper that joins the streamed sentences into one string."""
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
    ):
        parts.append(sent)
    return "".join(parts).strip()
