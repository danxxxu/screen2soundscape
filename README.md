# ScreenToSoundscapes – OSM & General Voice Assistant

Ask spoken or typed questions about places. For map-y queries, it parses your question into **Overpass QL**, optionally gets **OSRM** directions, summarizes with an **LLM**, and replies using **Piper TTS**. For general questions, it uses your local **LLaMA** and also speaks the answer.


## ✨ What it does

- 🎙️ Voice input (Whisper) or text input (CLI/file)
- 🧭 OSM flow: Natural language → Overpass QL → Overpass results → (optional) OSRM route → FLAN summary
- 🧠 General flow: Ask LLaMA anything (local), then speak it
- 🌍 Multilingual: detect input language, translate summaries, speak in your chosen voice/language
- 🔊 TTS via **Piper** (fast local voices)

> **Note:** These scripts use **Piper TTS**, not OpenVoice/MELo. Voice “speaker” picks a Piper voice model you’ve installed.



## 🗂️ Scripts

### `backend/run_assistant_osm.py` — OpenStreetMap & directions
Use this for **map-centric questions** that involve places, proximity, or routes.

**Best for**
- “How do I get from **Point A to Point B** (walk/bike/car)?”
- “**Where are the closest cafés** to here?”
- “Find **pharmacies near me**.”
- “Show **wheelchair-accessible toilets** near 48.8566, 2.3522.”

**What it does**
1) Parses your natural-language question into an **Overpass QL** query  
2) Calls **Overpass API** (POIs, amenities, features)  
3) If it’s a routing question, calls **OSRM** for step-by-step directions  
4) Summarizes results with a **FLAN** model  
5) Speaks the answer with **Piper TTS**

**Tips**
- Modes like `walk/bike/car` are supported in routing.
- Use `--save-json` to dump raw Overpass results.



### `backend/run_assistant_general.py` — General (non-map) inquiries
Use this for **general knowledge or descriptive questions** that aren’t about routing or nearby places.

**Best for**
- “**Tell me about Mount Everest**.”
- “What’s the **history of the Eiffel Tower**?”
- “What are the **top 10 tallest mountains**?”

**What it does**
1) Takes your question (voice or text)  
2) Generates an answer with your local **LLaMA** model  
3) Speaks the answer with **Piper TTS**

**Not for**
- Live map data, nearby searches, or directions (use `run_assistant_osm.py` instead).




## 🔧 Installation

### Python deps

```bash
# 1. Navigate into the project
cd ~/screen2soundscape

# 2. Create a virtual environment called "s2svenc"
python3 -m venv s2svenc

# 3. Activate the virtual environment
source s2svenc/bin/activate   # (Linux/macOS)
# .\s2svenc\Scripts\activate  # (Windows PowerShell)

# 4. Upgrade pip
pip install --upgrade pip

# 5. Install dependencies from requirements.in
pip install -r requirements.in
python -m spacy download en_core_web_sm

```bash

```

**Piper TTS**

The assistants (`run_assistant_osm.py` and `run_assistant_general.py`) use **Piper TTS** for speech synthesis.  
You’ll need to download one or more Piper voices before running the assistant.

### Download all Piper voices

```bash
huggingface-cli download rhasspy/piper-voices \
  --repo-type model \
  --include "*.onnx" "*.json" \
  --local-dir ~/screen2soundscape/backend/piper_models \
  --local-dir-use-symlinks False
````

This will download **all available Piper voices** (\~GBs of data) and preserve the folder structure, e.g.:

```
~/screen2soundscape/backend/piper_models/en/en_GB/alan/low/en_GB-alan-low.onnx
~/screen2soundscape/backend/piper_models/en/en_US/amy/high/en_US-amy-high.onnx
```

### Download a single voice

If you don’t want all voices, you can specify a single voice path on Hugging Face, for example:

```bash
huggingface-cli download rhasspy/piper-voices \
  --repo-type model \
  --include "en/en_US/amy/high/*" \
  --local-dir ~/screen2soundscape/backend/piper_models \
  --local-dir-use-symlinks False
```

### Training your own voice

Piper also supports training custom voices.
See the official guide here:
👉 [Piper Training Guide](https://github.com/rhasspy/piper/blob/master/TRAINING.md)



## 🧠 BitNet b1.58 2B4T (for the general assistant)

The general assistant (`run_assistant_general.py`) uses **Microsoft’s BitNet b1.58 2B4T**.
We load the model from a **local folder** if present, falling back to Hugging Face if not.

> ⚠️ For true 1-bit efficiency gains (speed/energy), Microsoft recommends **bitnet.cpp**.
> This project currently uses the **Transformers** path for simplicity and easy integration.

### 1) Install runtime dependencies

```bash
# Transformers fork required by BitNet
pip install "git+https://github.com/huggingface/transformers.git@096f25ae1f501a084d8ff2dcaf25fbc2bd60eba4"

# Usual runtime bits
pip install torch accelerate

# (Optional) Tools to download models
pip install "huggingface_hub[cli]"
# or: sudo apt-get install git-lfs && git lfs install
```

### 2) Download the BitNet model locally

Create the model directory and download the **microsoft/bitnet-b1.58-2B-4T** weights into it.

**Option A — using `huggingface-cli` (recommended):**

```bash
# Create the models directory
mkdir -p ~/screen2soundscape/backend/models/microsoft

# Download the full model repo into the expected local path
huggingface-cli download microsoft/bitnet-b1.58-2B-4T \
  --repo-type model \
  --local-dir ~/screen2soundscape/backend/models/microsoft/bitnet-b1.58-2B-4T
```

**Option B — using Git LFS:**

```bash
mkdir -p ~/screen2soundscape/backend/models/microsoft
cd ~/screen2soundscape/backend/models/microsoft

# If needed:
# sudo apt-get install git-lfs
git lfs install

# Clone the repo (creates ./bitnet-b1.58-2B-4T)
git clone https://huggingface.co/microsoft/bitnet-b1.58-2B-4T
```

After this step, your files will be under:

```
~/screen2soundscape/backend/models/microsoft/bitnet-b1.58-2B-4T
```

Our code auto-detects this local folder; if it’s missing, it will fetch by model ID (`microsoft/bitnet-b1.58-2B-4T`) from Hugging Face.

### 3) GGUF for `bitnet.cpp`

Use the native 1-bit speedups via **bitnet.cpp**:

```bash
# Download GGUF weights (used by bitnet.cpp)
huggingface-cli download microsoft/bitnet-b1.58-2B-4T-gguf \
  --repo-type model \
  --local-dir ~/screen2soundscape/backend/models/microsoft/bitnet-b1.58-2B-4T-gguf
```


### 4) Default system instruction

The assistant uses this default system prompt (overridable via `--system-prompt`):

> **“You are a helpful AI assistant for everyday tasks, please always respond in the same language as the question.”**

---

**Example run:**

```bash
python -m backend.run_assistant_general \
  --speaker amy \
  --text "Where are the top 10 tallest mountains" \
  --output-mode file
```



**FLAN (for OSM summaries)**

* `backend.utils.overpass_to_osm_flan` should pull a FLAN-T5 model via `transformers` (e.g., `google/flan-t5-base/large`). No extra step if it auto-downloads.



## 🧠 How it works

### OSM flow (`run_assistant_osm.py`)

1. **Input**: record (Whisper) or `--text/--text-file`
2. **Detect language** (`langdetect`)
3. **Parse**: `parse_question()` → intent, bounding box/center, start/end coords, mode, etc.
4. **(Optional) Directions**: If mode is `route_check` or `route_via`, fetch route via **OSRM** and summarize path.
5. **Build Overpass QL**: `build_overpass_query()`
6. **Query Overpass**: `run_overpass_query()`
7. **Summarize**: `summarize_results()` using **FLAN**
8. **Translate** (if non-English input): `deep_translator.GoogleTranslator`
9. **Speak**: `speak_piper.speak()` with **Piper** TTS

### General flow (`run_assistant_general.py`)

1. **Input**: record (Whisper) or `--text/--text-file`
2. **Ask LLaMA**: `get_llm()` returns your configured local LLaMA
3. **Speak**: **Piper** TTS



## 🚀 Usage

### OSM assistant

```bash
cd screen2soundscape
# Nearby POIs with geo context
python -m backend.run_assistant_osm \
  --speaker amy \
  --language en \
  --text "Are there any coffee shops nearby?" \
  --lat 50.6683 \
  --lon 4.6156

# Route + map info
python -m backend.run_assistant_osm \
  --speaker amy \
  --language en \
  --text "How do I get from Grand Place to Parc du Cinquantenaire?"
```

**Flags**

* `--speaker` *(str)*: Piper voice key (maps to a voice model file)
* `--language` *(str)*: Piper voice language tag (e.g., `en`, `fr`)
* `--speed` *(float)*: TTS speed (default `1.0`)
* `--text` / `--text-file`: provide input without recording
* `--lat`, `--lon`: user position (helps “near me”)
* `--save-json`: save raw Overpass results to `osm_assistant_output/raw.json`
* `--output-mode`: `file` or `stream` (TTS output handling)

### General assistant

```bash
cd screen2soundscape
python -m backend.run_assistant_general \
  --speaker amy \
  --language en \
  --text "Where are the top 10 tallest mountains?"
```

**Flags**

* `--speaker`, `--language`, `--speed`, `--text`, `--text-file`, `--output-mode`

---

## 📦 Project layout (key parts)

```
backend/
├── run_assistant_osm.py
├── run_assistant_general.py
└── utils/
    ├── transcribe.py                # Whisper recorder/transcriber
    ├── speak_piper.py               # Piper TTS (find_best_piper_model, speak)
    ├── question_to_overpass.py      # parse_question(), build_overpass_query()
    ├── overpass_to_osm_flan.py      # run_overpass_query(), summarize_results(), summarize_route(), warmup_summariser()
    └── llama_singleton.py           # get_llm() → local LLaMA
```



## 🌍 Multilingual behavior

* Input language is **detected** automatically.
* OSM summaries are produced in **English** by FLAN, then **translated** back to the detected language if needed.
* TTS language must match an installed **Piper voice**; control via `--language`.



## ⚠️ Notes & limits

* OSRM/Overpass are online services; expect network variability.
* OSM summaries use FLAN; general Q\&A uses your configured LLaMA.
* Piper speakers are voice models you install; there’s no OpenVoice/MELo in these scripts.



## 🔜 Roadmap

* FastAPI endpoint + simple web UI
* RAG with OSM wiki/tag metadata
* Richer landmark-based routing cues + via-points
* Map preview export



## 🗑 License

MIT © ScreenToSoundscapes

