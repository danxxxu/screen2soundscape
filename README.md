````markdown
# ScreenToSoundscapes – OSM & General Voice Assistant

Ask spoken or typed questions about places. For map-y queries, it parses your question into **Overpass QL**, optionally gets **OSRM** directions, summarizes with an **LLM**, and replies using **Piper TTS**. For general questions, it uses your local **LLaMA** and also speaks the answer.

---

## ✨ What it does

- 🎙️ Voice input (Whisper) or text input (CLI/file)
- 🧭 OSM flow: Natural language → Overpass QL → Overpass results → (optional) OSRM route → FLAN summary
- 🧠 General flow: Ask LLaMA anything (local), then speak it
- 🌍 Multilingual: detect input language, translate summaries, speak in your chosen voice/language
- 🔊 TTS via **Piper** (fast local voices)

> **Note:** These scripts use **Piper TTS**, not OpenVoice/MELo. Voice “speaker” picks a Piper voice model you’ve installed.

---

## 🗂️ Scripts

- `backend/run_assistant_osm.py` – place & routing questions (OSM/Overpass/OSRM + FLAN + Piper)
- `backend/run_assistant_general.py` – general questions (LLaMA + Piper)

---

## 🔧 Installation

### System deps
- `ffmpeg` (pydub)
- `portaudio` (sounddevice)

```bash
# macOS
brew install ffmpeg portaudio

# Ubuntu
sudo apt-get update
sudo apt-get install -y ffmpeg portaudio19-dev
````

### Python deps

```bash
pip install \
  openai-whisper \
  sounddevice \
  pydub \
  scipy \
  numpy \
  requests \
  transformers \
  langdetect \
  deep-translator
```

If your parser uses spaCy (recommended):

```bash
pip install spacy
python -m spacy download en_core_web_sm
```

**Piper TTS**

* Install your preferred method (binary or Python wrapper) and download one or more **Piper voice models**.
* Make sure `backend/utils/speak_piper.py` can find your voices (see its `MODEL_DIR` and your `--speaker`/`--language` usage).

**LLaMA (for general assistant)**

* Provide a local model that `backend.utils.llama_singleton.get_llm()` can load (often via `llama-cpp-python` with a GGUF file).

**FLAN (for OSM summaries)**

* `backend.utils.overpass_to_osm_flan` should pull a FLAN-T5 model via `transformers` (e.g., `google/flan-t5-base/large`). No extra step if it auto-downloads.

---

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

---

## 🚀 Usage

### OSM assistant

```bash
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

---

## 🌍 Multilingual behavior

* Input language is **detected** automatically.
* OSM summaries are produced in **English** by FLAN, then **translated** back to the detected language if needed.
* TTS language must match an installed **Piper voice**; control via `--language`.

---

## ⚠️ Notes & limits

* OSRM/Overpass are online services; expect network variability.
* OSM summaries use FLAN; general Q\&A uses your configured LLaMA.
* Piper speakers are voice models you install; there’s no OpenVoice/MELo in these scripts.

---

## 🔜 Roadmap

* FastAPI endpoint + simple web UI
* RAG with OSM wiki/tag metadata
* Richer landmark-based routing cues + via-points
* Map preview export

---

## 🗑 License

MIT © ScreenToSoundscapes

```

If you want, I can also generate a minimal `requirements.txt` from these sections or add a short “Piper voice download” snippet tailored to your `MODEL_DIR` conventions.
```
