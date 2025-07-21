# ScreenToSoundscapes Open Street Maps Voice Assistant

A modular Python package that lets you **ask spoken questions** about the world, **query OpenStreetMap**, **summarize** the results via LLaMA, and **speak the answer back** in your cloned voice.

## ✨ Features

* 🎧 **Voice input** with OpenAI Whisper (Enter to start/stop + silence detection)
* 🌍 **Multilingual natural language → Overpass API** mapping + OSM data fetch
* 🧠 **LLaMA summarization** of raw OSM results
* 🗣️ **Voice cloning & TTS** with OpenVoice + MELo
* ⚡ CLI, HTTP (FastAPI), and browser/desktop integration

---

## 📦 Installation

### 1. Clone the Repo & Install OpenVoice

```bash
git clone git@github.com:myshell-ai/OpenVoice.git
cd OpenVoice
pip install -e .
```

### 2. Download the OpenVoice Checkpoints

```bash
curl -L -o checkpoints_v2_0417.zip \
  https://myshell-public-repo-host.s3.amazonaws.com/openvoice/checkpoints_v2_0417.zip

mkdir checkpoints_v2
unzip checkpoints_v2_0417.zip -d checkpoints_v2
rm checkpoints_v2_0417.zip
```

<details>
<summary><strong>Windows (PowerShell)</strong> version</summary>

```powershell
Invoke-WebRequest -Uri https://myshell-public-repo-host.s3.amazonaws.com/openvoice/checkpoints_v2_0417.zip `
  -OutFile checkpoints_v2_0417.zip
New-Item -ItemType Directory -Path checkpoints_v2
Expand-Archive -Path checkpoints_v2_0417.zip -DestinationPath checkpoints_v2
Remove-Item checkpoints_v2_0417.zip
```

</details>

### 3. (Optional) Download LLaMA Model

```bash
mkdir models
cd models
curl -L -o llama-2-7b-chat.Q4_K_M.gguf \
  https://huggingface.co/TheBloke/Llama-2-7B-Chat-GGUF/resolve/main/llama-2-7b-chat.Q4_K_M.gguf
```

### 4. Install Python Dependencies

```bash
pip install \
  openai-whisper \
  webrtcvad \
  sounddevice \
  scipy \
  numpy \
  pydub \
  overpy \
  requests \
  llama-cpp-python \
  transformers \
  spacy \
  langdetect \
  deep-translator \
  geopy
python -m spacy download en_core_web_sm
```

> 🔧 Also install Whisper CLI manually:
>
> ```bash
> pip install git+https://github.com/openai/whisper.git
> ```

### 5. System Requirements

* **PortAudio** (for `sounddevice`)

  * macOS: `brew install portaudio`
  * Ubuntu/Debian: `sudo apt-get install portaudio19-dev`
* **ffmpeg** (for MP3 processing with `pydub`)

  * macOS: `brew install ffmpeg`
  * Ubuntu/Debian: `sudo apt-get install ffmpeg`

---

## 🗂️ Project Structure

```
osm_voice_assistant/
├── run_assistant.py              # Main script to run the assistant
├── utils/
│   ├── __init__.py
│   ├── transcribe.py             # Record + transcribe speech to text (multilingual)
│   ├── question_to_overpass.py   # Natural language → Overpass API (supports translation)
│   ├── overpass_to_osm.py        # Fetch and summarize OSM data with LLaMA
│   ├── speak.py                  # TTS and voice cloning
│   └── create_speaker.py         # Extract speaker embedding from reference audio
```

---

## 🚀 Usage

### 1. Create Your Own Voice (Speaker Embedding)

```bash
python utils/create_speaker.py \
  --reference sample_audio/arnold_original.mp3 \
  --speaker-name arnold
```

Saved to:

```
checkpoints_v2/base_speakers/ses/arnold.pth
```

### 2. Run the CLI Assistant

```bash
python run_assistant.py --speaker arnold --language FR --speed 1.1
```

Steps:

1. Press **Enter** to start speaking your question.
2. Press **Enter** again or pause to stop.
3. The assistant will:

   * Transcribe audio with Whisper (autodetects language)
   * Translate and parse to Overpass query
   * Run Overpass QL
   * Summarize via LLaMA
   * Speak answer in your cloned voice and chosen language

### 3. Run the FastAPI Server

```bash
uvicorn server:app --reload
```

Code:

```python
@app.get("/ask")
async def ask():
    question, lang = record_and_transcribe()
    osm_json = parse_question_to_overpass(question)
    summary = summarize_osm_results(osm_json)
    speak(summary, language=lang, speaker_key="arnold")
    return {"question": question, "summary": summary}
```

---

## ⚙️ Configuration

* Whisper model size: `transcribe.py` → `whisper.load_model("base")`
* LLaMA model path: set `LLAMA_MODEL_PATH` in `overpass_to_osm.py`
* Output folders: configurable in `transcribe.py`, `speak.py`, etc.
* Supported speaker languages: check language options and voice file in `create_speaker.py`

---

## 🌍 Multilingual Support

### Language Input:

* `transcribe.py` uses Whisper's automatic language detection.
* `question_to_overpass.py` uses `langdetect` + `deep_translator` to translate non-English input to English before parsing.

### Language Output:

* `speak.py` uses OpenVoice + MELo to speak in the **chosen target language**.
* Use `--language FR`, `--language ES`, etc. in CLI or API.
* You must create voice clones per language using `create_speaker.py`.

### To Add More Languages:

1. Add TTS support and speaker embedding via `create_speaker.py`
2. Update your CLI or API calls to pass the correct `--language`
3. Ensure text is translated before speech if needed

---

## 🚨 Known Limitations

* Only French → English translation is supported by default; expand via `deep_translator`
* Must generate language-specific voice samples in advance
* LLaMA summarization is language-agnostic but outputs English

---

## 🗑️ License

MIT © Screen2Soundscape
Fork and build your own voice-based mapping assistant!

---

## ✨ Coming Soon

* [ ] French/Spanish/German full localization
* [ ] Voice command web UI
* [ ] RAG integration with OSM wiki tags
* [ ] Smart fallback if Overpass query fails

---

