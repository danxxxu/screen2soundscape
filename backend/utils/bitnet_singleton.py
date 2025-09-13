# backend/utils/bitnet_singleton.py
"""
BitNet chat wrapper with sentence-level streaming.

Backends (auto, in this order):
  1) C++ CLI binary ("bitnet") if present (fastest)
  2) Python runner: BitNet/run_inference.py (fallback, no build needed)
  3) 🤗 Transformers: microsoft/bitnet-b1.58-2B-4T (streamed via TextIteratorStreamer)

- Prefers a local GGUF in: backend/models/microsoft/bitnet-b1.58-2B-4T-gguf/
- If HF fallback is used, it prefers a local HF dir:
    backend/models/microsoft/bitnet-b1.58-2B-4T
  otherwise downloads from the Hub.

Public API (unchanged):
  - chat(messages, ...) -> str
  - stream_chat(messages, ...) -> iterator (yields completed sentences)
"""

import os
import re
import glob
import shlex
import shutil
import subprocess
import sys
import threading
from typing import Iterator, List, Dict, Optional, Tuple

# HF fallback lazy imports
_HF_AVAILABLE = True
try:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer
except Exception:
    _HF_AVAILABLE = False

# ---------------- Paths / discovery ----------------

def _project_root() -> str:
    return os.path.dirname(os.path.dirname(__file__))

def default_gguf_dir() -> str:
    return os.path.join(_project_root(), "models", "microsoft", "bitnet-b1.58-2B-4T-gguf")

def default_hf_dir() -> str:
    return os.path.join(_project_root(), "models", "microsoft", "bitnet-b1.58-2B-4T")

def _prefer_gguf(files: List[str]) -> Optional[str]:
    if not files:
        return None
    for f in files:
        if "i2_s" in os.path.basename(f).lower():
            return f
    return files[0]

def find_gguf_model(path_hint: Optional[str] = None) -> Optional[str]:
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

# ---------------- Prompting ----------------

ASSISTANT_TAG = "Assistant:"

def build_chat_prompt(system_prompt: str, user_prompt: str) -> str:
    # Plain text so any backend can consume it.
    return (
        f"System instruction:\n{system_prompt.strip()}\n\n"
        f"User:\n{user_prompt.strip()}\n\n"
        f"{ASSISTANT_TAG}\n"
    )

# ---------------- Streaming helpers ----------------

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
def strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s)

# Light heuristic to avoid some abbreviations; not perfect across languages.
SENTENCE_RE = re.compile(r"[.!?]+(?=\s|\Z)")

def _drain_sentences(accum: str) -> Tuple[List[str], str]:
    """Return (list_of_full_sentences, remainder)."""
    out: List[str] = []
    start = 0
    for m in SENTENCE_RE.finditer(accum):
        end_idx = m.end()
        out.append(accum[start:end_idx])
        start = end_idx
    return out, accum[start:]

# ---------------- Runner resolution ----------------

def _default_py_runner() -> str:
    cand = os.path.join(_project_root(), "BitNet", "run_inference.py")
    return cand if os.path.isfile(cand) else ""

def _resolve_runner(bitnet_bin: str) -> dict:
    """
    Decide which runner to use.
    Returns dict:
      {"mode": "bin"|"py"|"hf",
       "exe": <path or None>,
       "script": <path or None>,
       "why": <text>}
    """
    # 1) C++ binary (absolute or on PATH)
    if bitnet_bin:
        if os.path.isabs(bitnet_bin) and os.path.isfile(bitnet_bin):
            return {"mode": "bin", "exe": bitnet_bin, "script": None, "why": "absolute bitnet binary"}
        found = shutil.which(bitnet_bin)
        if found:
            return {"mode": "bin", "exe": found, "script": None, "why": f"found on PATH ({found})"}

    # 2) Python runner in repo
    py_script = _default_py_runner()
    if py_script:
        py_exe = os.environ.get("PYTHON") or sys.executable or shutil.which("python3") or "python3"
        return {"mode": "py", "exe": py_exe, "script": py_script, "why": f"python runner at {py_script}"}

    # 3) HF fallback
    return {"mode": "hf", "exe": None, "script": None, "why": "HF Transformers fallback"}

# ---------------- Process spawners ----------------

def _spawn_cpp_or_py(
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
        # Python runner flags (stream-friendly, unbuffered)
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
            bufsize=1,
            universal_newlines=True,
        )
    except FileNotFoundError as e:
        raise FileNotFoundError(
            f"Failed to spawn runner ({runner['why']}):\n"
            f"Command tried: {' '.join(shlex.quote(x) for x in cmd)}\n"
            f"PATH was: {os.environ.get('PATH','')}"
        ) from e

    return proc

def _iter_model_text_from_proc(proc: subprocess.Popen, wait_for_tag: str) -> Iterator[str]:
    """Yield raw text as it arrives from stdout (proc)."""
    if not proc.stdout:
        return
    buf_all = ""
    saw_tag = False
    while True:
        ch = proc.stdout.read(1)
        if ch == "" or ch is None:
            break
        buf_all += ch
        if not saw_tag:
            if wait_for_tag in buf_all:
                saw_tag = True
            continue
        yield ch
    proc.wait()
    if proc.returncode not in (0, None):
        if proc.stderr:
            err = proc.stderr.read()
            raise RuntimeError(f"Runner exited with {proc.returncode}:\n{err}")
    if not saw_tag and buf_all:
        yield buf_all

# ---------------- HF fallback (streaming) ----------------

_HF_TOKENIZER = None
_HF_MODEL = None
_HF_DEVICE = "cpu"
_HF_DTYPE = None
_HF_SRC = None  # local dir or repo id

def _hf_pick_device_dtype() -> Tuple[str, "torch.dtype"]:
    if torch.cuda.is_available():
        return "cuda", torch.bfloat16
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps", torch.float16
    return "cpu", torch.float32

def _hf_load(src: Optional[str] = None):
    global _HF_TOKENIZER, _HF_MODEL, _HF_DEVICE, _HF_DTYPE, _HF_SRC
    if _HF_MODEL is not None:
        return
    if not _HF_AVAILABLE:
        raise RuntimeError(
            "HF fallback requested but transformers/torch not available. "
            "Install requirements first:\n"
            "  pip install --upgrade torch accelerate sentencepiece\n"
            "  pip install 'git+https://github.com/huggingface/transformers.git@096f25ae1f501a084d8ff2dcaf25fbc2bd60eba4'\n"
        )
    _HF_DEVICE, _HF_DTYPE = _hf_pick_device_dtype()

    # Prefer local dir if present
    local_dir = default_hf_dir()
    if src and os.path.isdir(src):
        _HF_SRC = src
    elif os.path.isdir(local_dir):
        _HF_SRC = local_dir
    else:
        _HF_SRC = os.environ.get("BITNET_HF_MODEL_ID", "microsoft/bitnet-b1.58-2B-4T")

    _HF_TOKENIZER = AutoTokenizer.from_pretrained(_HF_SRC)
    if _HF_TOKENIZER.pad_token_id is None and _HF_TOKENIZER.eos_token_id is not None:
        _HF_TOKENIZER.pad_token = _HF_TOKENIZER.eos_token

    _HF_MODEL = AutoModelForCausalLM.from_pretrained(_HF_SRC, torch_dtype=_HF_DTYPE)
    if _HF_DEVICE != "cpu":
        _HF_MODEL = _HF_MODEL.to(_HF_DEVICE)
    # generation config safety
    gc = _HF_MODEL.generation_config
    if gc.pad_token_id is None and _HF_TOKENIZER.pad_token_id is not None:
        gc.pad_token_id = _HF_TOKENIZER.pad_token_id
    if gc.eos_token_id is None and _HF_TOKENIZER.eos_token_id is not None:
        gc.eos_token_id = _HF_TOKENIZER.eos_token_id

def _hf_stream(system_msg: str, user_msg: str, max_new_tokens: int, temperature: float, top_p: float) -> Iterator[str]:
    _hf_load()
    # Build chat template
    prompt = _HF_TOKENIZER.apply_chat_template(
        [{"role": "system", "content": system_msg}, {"role": "user", "content": user_msg}],
        tokenize=False,
        add_generation_prompt=True,
    )
    inputs = _HF_TOKENIZER(prompt, return_tensors="pt")
    inputs = {k: v.to(_HF_DEVICE) for k, v in inputs.items()}

    streamer = TextIteratorStreamer(_HF_TOKENIZER, skip_prompt=True, skip_special_tokens=True)
    gen_kwargs = dict(
        **inputs,
        streamer=streamer,
        max_new_tokens=max_new_tokens,
        do_sample=(temperature > 0),
        temperature=max(1e-5, float(temperature)),
        top_p=float(top_p),
        eos_token_id=_HF_TOKENIZER.eos_token_id,
        pad_token_id=_HF_TOKENIZER.pad_token_id,
    )

    # Run generation in a background thread so we can iterate the streamer
    def _worker():
        with torch.no_grad():
            _HF_MODEL.generate(**gen_kwargs)

    th = threading.Thread(target=_worker, daemon=True)
    th.start()

    accum = ""
    for chunk in streamer:
        accum += chunk
        sentences, tail = _drain_sentences(accum)
        for s in sentences:
            yield s
        accum = tail

    # Flush tail
    tail = accum.strip()
    if tail:
        yield tail

# ---------------- Public API ----------------

def stream_chat(
    messages: List[Dict[str, str]],
    *,
    # generation
    max_new_tokens: int = 256,
    temperature: float = 0.7,
    top_p: float = 0.95,
    # runtime
    bitnet_bin: str = "bitnet",
    bitnet_model: Optional[str] = None,   # GGUF file/dir for C++/py; HF will ignore
    threads: Optional[int] = None,
    ctx: int = 4096,
    extra_args: Optional[List[str]] = None,
) -> Iterator[str]:
    """
    Stream sentences as they complete. Yields strings that end in . ! or ? (mostly).

    messages: [{"role":"system","content":"..."}, {"role":"user","content":"..."}]
    """
    # Extract content
    system_msg = next((m["content"] for m in messages if m.get("role") == "system"), "")
    user_msg   = next((m["content"] for m in messages if m.get("role") == "user"), "")

    # Resolve desired backend
    runner = _resolve_runner(bitnet_bin)

    if runner["mode"] in ("bin", "py"):
        # Resolve gguf
        model_path = find_gguf_model(bitnet_model)
        if not model_path:
            raise FileNotFoundError(
                "No GGUF model found. Provide --bitnet-model or place one in "
                f"{default_gguf_dir()}"
            )
        prompt = build_chat_prompt(system_msg, user_msg)
        proc = _spawn_cpp_or_py(
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

        accum = ""
        for ch in _iter_model_text_from_proc(proc, wait_for_tag=ASSISTANT_TAG):
            accum += ch
            # Emit sentences as they complete
            sentences, tail = _drain_sentences(accum)
            for s in sentences:
                yield s
            accum = tail

        tail = accum.strip()
        if tail:
            yield tail
        return

    # HF fallback
    for s in _hf_stream(system_msg, user_msg, max_new_tokens, temperature, top_p):
        yield s

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
    ):
        parts.append(sent)
    return "".join(parts).strip()
