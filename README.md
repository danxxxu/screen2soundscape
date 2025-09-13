# ScreenToSoundscapes – OSM & General Voice Assistant


Ask spoken or typed questions about places **and** general topics with one script: `backend/run_assistant.py`.
Map-ish queries are parsed to **Overpass QL** (and optional **OSRM** directions), summarized via **BitNet**, and spoken via **Piper TTS**. General questions are also answered by **BitNet** and spoken via **Piper**.

* 🎙️ Voice input (Whisper) or text input (CLI/file)
* 🧭 OSM flow: Natural language → Overpass QL → Overpass results → (optional) OSRM route → BitNet summary
* 🧠 General flow: Ask anything → BitNet answer
* 🌍 Multilingual: detect input language, translate summaries if needed, and speak in your chosen Piper voice
* 🔊 TTS via **Piper** (fast local voices)

> This project uses **BitNet** only (no LLaMA). You can run BitNet through Hugging Face Transformers (in-process) or via **bitnet.cpp** (GGUF).

---

## 🗂️ Script

### `backend/run_assistant.py` — Unified assistant

Auto-routes between OSM and general modes, or you can force a mode.

**Examples**

```bash
# General question (stream TTS)
python -m backend.run_assistant \
  --speaker amy \
  --text "Where are the top 3 tallest mountains in Europe?" \
  --output-mode stream

# Map / nearby POIs with geo hints
python -m backend.run_assistant \
  --speaker amy \
  --text "Find wheelchair-accessible toilets near me" \
  --lat 52.3728 --lon 4.8936

# Force OSM mode
python -m backend.run_assistant \
  --speaker amy \
  --force-mode osm \
  --text "Cafes within 1km of 48.8566, 2.3522"

# Force General mode
python -m backend.run_assistant \
  --speaker amy \
  --force-mode general \
  --text "Summarize the Schengen Agreement in 5 bullet points."
```

**Key flags**

* `--speaker` *(str)*: Piper voice key (e.g., `amy`)
* `--language` *(str)*: Piper language code or `auto` (default)
* `--speed` *(float)*: TTS speed (default `1.0`)
* `--text` / `--text-file`: bypass recording with direct input
* `--output-mode` `stream|file`: stream chunks or synthesize once to file
* `--force-mode` `auto|osm|general`: routing override (default `auto`)
* `--lat`, `--lon`: optional geohints for “near me”
* BitNet runtime knobs: `--max-new-tokens`, `--temperature`, `--top-p`, `--ctx`, `--threads`, `--bitnet-bin`, `--bitnet-model`, `--extra-args`

---

## 🔧 Installation

### 0) Project & venv

```bash
cd ~/screen2soundscape
python3 -m venv s2svenc
source s2svenc/bin/activate            # (Linux/macOS)
# .\s2svenc\Scripts\activate           # (Windows PowerShell)

pip install --upgrade pip
pip install -r requirements.in
python -m spacy download en_core_web_sm
```

### 1) Piper TTS (voices)

Download one or more **Piper** voices (examples below). The code expects them under `~/screen2soundscape/backend/piper_models`.

**All voices (large download):**

```bash
huggingface-cli download rhasspy/piper-voices \
  --repo-type model \
  --include "*.onnx" "*.json" \
  --local-dir ~/screen2soundscape/backend/piper_models \
  --local-dir-use-symlinks False
```

**Single voice (example: en\_US/amy):**

```bash
huggingface-cli download rhasspy/piper-voices \
  --repo-type model \
  --include "en/en_US/amy/high/*" \
  --local-dir ~/screen2soundscape/backend/piper_models \
  --local-dir-use-symlinks False
```

Directory will look like:

```
backend/piper_models/en/en_US/amy/high/en_US-amy-high.onnx
```

### 2) BitNet via Transformers (in-process, easiest)

This path loads **microsoft/bitnet-b1.58-2B-4T** with Transformers **once per Python process** and reuses it—no reload on each prompt.

```bash
# Transformers snapshot known to work well with BitNet
pip install "git+https://github.com/huggingface/transformers.git@096f25ae1f501a084d8ff2dcaf25fbc2bd60eba4"

# Usual runtime bits
pip install torch accelerate

# (Optional) Use the CLI for local downloads
pip install "huggingface_hub[cli]"
```

**Download the model locally (recommended for offline/consistent runs):**

```bash
mkdir -p ~/screen2soundscape/backend/models/microsoft
huggingface-cli download microsoft/bitnet-b1.58-2B-4T \
  --repo-type model \
  --local-dir ~/screen2soundscape/backend/models/microsoft/bitnet-b1.58-2B-4T
```

> If the local folder is present, the code uses it; otherwise it pulls `microsoft/bitnet-b1.58-2B-4T` from the Hub at runtime.

**Force Transformers (HF) mode at runtime** (skips cpp/py runners and ensures “load once, reuse”):

```bash
# Option A: environment flag (supported in your code)
BITNET_FORCE_HF=1 python -m backend.run_assistant --speaker amy --text "Hello"

# Option B: pass a non-existent binary AND empty gguf hint
python -m backend.run_assistant --speaker amy --bitnet-bin "no_such_binary" --bitnet-model "" --text "Hello"
```

### 3) BitNet via bitnet.cpp (GGUF, fastest on CPU)

This uses **GGUF** weights and a native runner. Your script auto-selects the cpp/py runner if available.

**Download GGUF weights:**

```bash
huggingface-cli download microsoft/bitnet-b1.58-2B-4T-gguf \
  --repo-type model \
  --local-dir ~/screen2soundscape/backend/models/microsoft/bitnet-b1.58-2B-4T-gguf
```

**Build bitnet.cpp from source (as per your notes):**

```bash
# Clone
git clone --recursive https://github.com/microsoft/BitNet.git
cd BitNet

# (Recommended) Conda env
conda create -n bitnet-cpp python=3.9
conda activate bitnet-cpp

pip install -r requirements.txt

# Download GGUF models (example path)
huggingface-cli download microsoft/BitNet-b1.58-2B-4T-gguf --local-dir models/BitNet-b1.58-2B-4T

# Prepare environment (choose your quant type, e.g. i2_s)
python setup_env.py -md models/BitNet-b1.58-2B-4T -q i2_s
```

> On Windows, use a **Developer Command Prompt / PowerShell for VS2022**.

**Run with cpp binary in ScreenToSoundscapes:**

* Build/locate the `bitnet` binary and point the assistant at it.

```bash
python -m backend.run_assistant \
  --speaker amy \
  --bitnet-bin /path/to/bitnet \
  --bitnet-model ~/screen2soundscape/backend/models/microsoft/bitnet-b1.58-2B-4T-gguf \
  --text "Write a haiku about bicycles."
```

> If you provide a **directory** to `--bitnet-model`, the code will auto-pick a GGUF file (prefers names with `i2_s`). If you pass a **file**, it uses that exact GGUF.

---

## 🚀 Typical runs

**General**

```bash
# HF in-process (recommended for simplicity)
BITNET_FORCE_HF=1 \
python -m backend.run_assistant \
  --speaker amy \
  --text "Give me three tips for solo travel"
```

**OSM nearby**

```bash
python -m backend.run_assistant --speaker amy --text "Find pharmacies near me"

python -m backend.run_assistant --speaker amy --text "¿Hay cafeterías cerca?"
```

**Routing**

```bash
python -m backend.run_assistant \
  --speaker amy \
  --text "How do I walk from Amsterdam Centraal to NEMO Science Museum?"
```

**Force modes**

```bash
python -m backend.run_assistant --speaker amy --force-mode osm --text "Wheelchair-accessible toilets around me"
python -m backend.run_assistant --speaker amy --force-mode general --text "Explain SIMD vs MIMD simply"
python -m backend.run_assistant --speaker amy --force-mode osm --text "itinéraire vers la gare centrale"
```

---

## 🧠 How it works (quick)

* **Intent routing**: `run_assistant.py` detects if the question looks “map-ish.” Otherwise it goes general.
* **OSM flow**: `parse_question()` → (optional) OSRM route → deterministic `build_overpass_query()`; if invalid but text is clearly map-ish, a BitNet fallback builds QL; calls Overpass; then `summarize_results()` with BitNet; translates if needed; speaks with Piper.
* **General flow**: Direct BitNet answer; speaks with Piper.
* **BitNet backends**:

  * **HF Transformers (in-process)**: loads once per process; best for quick integration and reuse.
  * **bitnet.cpp / python runner (GGUF)**: fastest CPU path; each spawned process loads its own model. To keep GGUF resident, run a persistent/server mode (advanced).

---

## 📦 Project layout (key)

```
backend/
├── run_assistant.py
└── utils/
    ├── transcribe.py
    ├── speak_piper.py
    ├── osm_tags.py
    ├── question_to_overpass.py
    ├── overpass_to_osm_bitnet.py
    └── bitnet_singleton.py
```

---

## 🌍 Multilingual behavior

* Input language is auto-detected.
* OSM summaries are produced in English and translated back to the detected language if needed.
* Piper voice must match an installed language; control with `--language` or leave `auto`.

---

## ⚠️ Notes & limits

* Overpass/OSRM are online APIs; results depend on network and OSM coverage.
* For guaranteed “no reloads” during a session, prefer **HF in-process** (set `BITNET_FORCE_HF=1`) or implement a **persistent** cpp/python runner.

---

## 🗑 License

MIT © ScreenToSoundscapes

---




## 🗑 License

MIT © ScreenToSoundscapes

