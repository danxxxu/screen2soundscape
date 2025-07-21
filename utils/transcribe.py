# transcribe.py

import threading
import webrtcvad
import sounddevice as sd
import numpy as np
import tempfile
import scipy.io.wavfile as wav
import whisper
import sys
import os
import datetime
from pydub import AudioSegment

# — load Whisper model once —
_model = whisper.load_model("base")  # choose "tiny"/"small"/"medium"/"large"

def _record_audio(
    max_silence: float = 5.0,
    fs: int = 16000,
    vad_aggressiveness: int = 3,
    stop_on_enter: bool = True
) -> np.ndarray:
    """
    Record until max_silence secs of silence or Enter pressed.
    Returns float32 numpy array in [-1,1].
    """
    stop_flag = False

    def _wait_for_enter():
        input()
        nonlocal stop_flag
        stop_flag = True

    if stop_on_enter:
        print("Press Enter to start recording.")
        input()
        print("Recording… Press Enter again at any time to stop early.")
        threading.Thread(target=_wait_for_enter, daemon=True).start()
    else:
        print("Recording…")

    vad = webrtcvad.Vad(vad_aggressiveness)
    frame_ms = 30
    frame_size = int(fs * frame_ms / 1000)
    frames = []
    silence = 0.0

    with sd.InputStream(samplerate=fs, channels=1, dtype='int16') as stream:
        while True:
            data, overflow = stream.read(frame_size)
            if overflow:
                print("[warning] Audio buffer overflow", file=sys.stderr)
            pcm = data.tobytes()
            is_speech = vad.is_speech(pcm, fs)

            frames.append(data.copy())
            if is_speech:
                silence = 0.0
            else:
                silence += frame_ms / 1000.0

            if silence >= max_silence or stop_flag:
                break

    audio = np.concatenate(frames).astype(np.float32) / 32768.0
    print("Stopped recording.")
    return audio

def record_and_transcribe(
    max_silence: float = 5.0,
    fs: int = 16000,
    vad_aggressiveness: int = 3,
    output_dir: str = "osm_assistant_output",
    save_audio: bool = True
) -> tuple[str, str]:
    """
    Record audio, transcribe with Whisper (auto-language),
    save text, language, and optional mp3 into output_dir.
    Returns (transcription, language_code).
    """
    # 1) record
    audio = _record_audio(max_silence, fs, vad_aggressiveness)

    # 2) timestamp at end
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # make output dir
    os.makedirs(output_dir, exist_ok=True)

    # 3) save transcription
    txt_path = os.path.join(output_dir, f"{ts}.txt")
    print(f"Saving transcription → {txt_path}")
    # transcribe
    # write temp wav for Whisper
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav.write(tmp.name, fs, audio)
        wav_path = tmp.name

    print("Transcribing with Whisper…")
    result = _model.transcribe(wav_path)
    text = result.get("text", "").strip()
    lang = result.get("language", "unknown")

    # write text file (no timestamps inside)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)

    # 4) save language code
    lang_path = os.path.join(output_dir, f"{ts}_lang.txt")
    print(f"Saving language code → {lang_path}")
    with open(lang_path, "w", encoding="utf-8") as f:
        f.write(lang)

    # 5) optionally save audio mp3
    if save_audio:
        mp3_path = os.path.join(output_dir, f"{ts}.mp3")
        print(f"Exporting audio → {mp3_path}")
        # convert wav → mp3 (requires ffmpeg in PATH)
        audio_seg = AudioSegment.from_file(wav_path, format="wav")
        audio_seg.export(mp3_path, format="mp3")
    else:
        mp3_path = None

    # cleanup temp wav
    try:
        os.remove(wav_path)
    except OSError:
        pass

    print("Done.")
    return text, lang

if __name__ == "__main__":
    """
    CLI usage:
      python transcribe.py          # defaults
      python transcribe.py 7 32000 2 my_outputs False
    → max_silence=7, fs=32000Hz, vad=2, output_dir="my_outputs", save_audio=False
    """
    args = sys.argv[1:]
    max_sil = float(args[0]) if len(args) > 0 else 5.0
    fs = int(args[1]) if len(args) > 1 else 16000
    agg = int(args[2]) if len(args) > 2 else 3
    outd = args[3] if len(args) > 3 else "osm_assistant_output"
    save_a = args[4].lower() not in ("0", "false", "no") if len(args) > 4 else True

    text, lang = record_and_transcribe(
        max_silence=max_sil,
        fs=fs,
        vad_aggressiveness=agg,
        output_dir=outd,
        save_audio=save_a
    )
    print(f"\n→ Result written at {outd}/ with timestamp suffix")
    print(f"[{lang}] {text}")
