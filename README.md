Here’s an updated version of your README to reflect the actual logic and structure of `run_assistant.py`, including accurate step breakdowns, parameter explanations, and small clarifications in capabilities:

---

# ScreenToSoundscapes OpenStreetMap Voice Assistant

A modular Python assistant that lets you **ask spoken or typed questions** about the world, **query OpenStreetMap** using natural language, **summarize** results using LLaMA, and **speak the answer** back in your cloned voice.

---

## ✨ Features

* 🎙️ **Voice input** (via Whisper) or text input (via CLI/file)
* 🌐 **Multilingual natural language → Overpass QL** mapping
* 🧠 **LLM summarization** of OpenStreetMap data (LLaMA or other)
* 🗣️ **Voice cloning & TTS** with OpenVoice + MELo
* 🧭 **Route directions** (via OSRM) if applicable
* ⚡ CLI interface with FastAPI + browser integration coming soon

---

## 📦 Installation

### 1. Clone and install OpenVoice

```bash
git clone https://github.com/myshell-ai/OpenVoice.git
cd OpenVoice
pip install -e .
```

### 2. Download OpenVoice Checkpoints

```bash
curl -L -o checkpoints_v2_0417.zip \
  https://myshell-public-repo-host.s3.amazonaws.com/openvoice/checkpoints_v2_0417.zip

mkdir checkpoints_v2
unzip checkpoints_v2_0417.zip -d checkpoints_v2
rm checkpoints_v2_0417.zip
```

<details>
<summary><strong>Windows PowerShell version</strong></summary>

```powershell
Invoke-WebRequest -Uri https://myshell-public-repo-host.s3.amazonaws.com/openvoice/checkpoints_v2_0417.zip `
  -OutFile checkpoints_v2_0417.zip
New-Item -ItemType Directory -Path checkpoints_v2
Expand-Archive -Path checkpoints_v2_0417.zip -DestinationPath checkpoints_v2
Remove-Item checkpoints_v2_0417.zip
```

</details>

### 3. (Optional) Download LLaMA Model for Summarization

```bash
mkdir models
cd models
curl -L -o llama-2-7b-chat.Q4_K_M.gguf https://huggingface.co/TheBloke/Llama-2-7B-Chat-GGUF/resolve/main/llama-2-7b-chat.Q4_K_M.gguf
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

**Also install Whisper CLI:**

```bash
pip install git+https://github.com/openai/whisper.git
```

**Install OpenVoice + MELo TTS:**

```bash
apt update && apt install -y mecab libmecab-dev mecab-ipadic-utf8
pip install git+https://github.com/myshell-ai/MeloTTS.git
python -m unidic download
```

### 5. System Requirements

* `portaudio` (for `sounddevice`)

  * macOS: `brew install portaudio`
  * Ubuntu: `sudo apt-get install portaudio19-dev`
* `ffmpeg` (for MP3 support via `pydub`)

  * macOS: `brew install ffmpeg`
  * Ubuntu: `sudo apt-get install ffmpeg`

---

## 🗂️ Project Structure

```
osm_voice_assistant/
├── run_assistant.py              # Main CLI interface
├── models/                       # LLaMA or other local LLMs
├── utils/
│   ├── transcribe.py             # Record + transcribe audio (Whisper)
│   ├── question_to_overpass.py   # Parse natural language into Overpass QL
│   ├── overpass_to_osm.py        # Run Overpass query + summarize results
│   ├── speak.py                  # Voice synthesis (OpenVoice + MELo)
│   └── create_speaker.py         # Generate custom speaker embedding
```

---

## 🚀 Usage

### 1. Create a Custom Speaker Voice

```bash
python utils/create_speaker.py \
  --reference sample_audio/arnold_original.mp3 \
  --speaker-name arnold
```

➡️ Saves to: `checkpoints_v2/base_speakers/ses/arnold.pth`

---

### 2. Run the Voice Assistant CLI

```bash
python run_assistant.py --speaker arnold --language EN_NEWEST --speed 1.0
```

#### Text-Based Queries:

```bash
python run_assistant.py --speaker arnold --text "Where are the vegan restaurants in Lyon?"
python run_assistant.py --speaker arnold --text "How do I get from Times Square to Central Park?"
python run_assistant.py --speaker arnold --text "Où est le marché aux puces à Paris ?" --language FR
```

#### With Geolocation:

```bash
python run_assistant.py --speaker arnold --text "Are there any pharmacies nearby?" --lat 50.6683 --lon 4.6156
```

Steps:

1. Question is either spoken, typed, or read from a file
2. Language is detected and optionally translated
3. Location and intent are parsed
4. Overpass QL query is built and run
5. Optionally: Directions are fetched via OSRM
6. Summary is generated via LLaMA
7. If not in English, translated
8. TTS response is played using cloned voice

---

## 🌐 API (Coming Soon)

A FastAPI version is in development. Basic sketch:

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

## 🌍 Multilingual Support

* **Input**: Whisper + `langdetect` + optional `deep-translator` to English
* **Output**: Summary spoken in user's language using OpenVoice (if available)
* Use `--language` to control TTS language (must match speaker model)

---

## 💡 Tips

* Use `--save-json` to save raw OSM results to `osm_assistant_output/raw.json`
* Combine with lat/lon for context-aware queries (e.g., “near me”)
* LLaMA summarization currently returns English output before optional translation

---

## ⚠️ Known Limitations

* LLaMA summarization is English only (translation handled after)
* Speaker voice must be created in advance for each language
* OSRM directions only available for "walk", "bike", or "car"

---

## 🔜 Roadmap

* [ ] Web UI for voice control
* [ ] RAG using OSM wiki/tag metadata
* [ ] Smarter fallback if query fails
* [ ] Interactive map + speech overlay

---

## 🗑 License

MIT © ScreenToSoundscapes
Build your own voice-first mapping assistant using OSM and LLMs.

---

## 🖥 Demo (Preview)

🔗 [DEMO Environment](https://screen2soundscape-671d28241a35.herokuapp.com/)

![screenshot](https://github.com/user-attachments/assets/bed1fcf3-4f42-4772-9c38-9fd18e604516)

---

Let me know if you'd like a Markdown file version, a server `README`, or a minimal public version for GitHub.
