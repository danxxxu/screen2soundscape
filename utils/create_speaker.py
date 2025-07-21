# create_speaker.py

import os
import re
import torch
import argparse
from openvoice import se_extractor
from openvoice.api import ToneColorConverter
from melo.api import TTS
import warnings
warnings.filterwarnings("ignore")

def sanitize_text(text, max_length=30):
    """Clean text for safe filenames."""
    text = re.sub(r'[^a-zA-Z0-9\s]', '', text)  # remove special chars
    text = re.sub(r'\s+', '_', text.strip())    # replace spaces with underscores
    return text[:max_length]

def main(reference_speaker=None, input_text=None, input_language=None, speaker_name='tmp_speaker'):
    ckpt_converter = 'checkpoints_v2/converter'
    base_output_dir = 'openvoice_voices'
    output_dir = os.path.join(base_output_dir, speaker_name) if speaker_name else base_output_dir
    os.makedirs(output_dir, exist_ok=True)

    device = "cuda:0" if torch.cuda.is_available() else "cpu"

    tone_color_converter = ToneColorConverter(f'{ckpt_converter}/config.json', device=device)
    tone_color_converter.load_ckpt(f'{ckpt_converter}/checkpoint.pth')

    # Get speaker embedding
    if reference_speaker:
        target_se, _ = se_extractor.get_se(reference_speaker, tone_color_converter, vad=True)
        # Save the speaker embedding
        speaker_path = f'checkpoints_v2/base_speakers/ses/{speaker_name}.pth'
        os.makedirs(os.path.dirname(speaker_path), exist_ok=True)
        torch.save(target_se, speaker_path)
        print(f"[INFO] Saved speaker embedding to {speaker_path}")
    else:
        fallback_speaker_name = 'en-default'
        target_se = torch.load(f'checkpoints_v2/base_speakers/ses/{fallback_speaker_name}.pth', map_location=device)

    # Use either custom input or example texts
    if input_text:
        if not input_language:
            raise ValueError("If text is provided, --language must also be specified.")
        texts = {input_language.upper(): input_text}
    else:
        texts = {
            'EN_NEWEST': "Did you ever hear a folk tale about a giant turtle?",
            'EN': "Did you ever hear a folk tale about a giant turtle?",
            'ES': "El resplandor del sol acaricia las olas, pintando el cielo con una paleta deslumbrante.",
            'FR': "La lueur dorée du soleil caresse les vagues, peignant le ciel d'une palette éblouissante.",
            'ZH': "在这次vacation中，我们计划去Paris欣赏埃菲尔铁塔和卢浮宫的美景。",
            'JP': "彼は毎朝ジョギングをして体を健康に保っています。",
            'KR': "안녕하세요! 오늘은 날씨가 정말 좋네요.",
        }

    src_path = os.path.join(output_dir, 'tmp.wav')
    speed = 1.0

    for language, text in texts.items():
        model = TTS(language=language, device=device)
        speaker_ids = model.hps.data.spk2id

        for speaker_key in speaker_ids.keys():
            speaker_id = speaker_ids[speaker_key]
            model.tts_to_file(text, speaker_id, src_path, speed=speed)

            source_key = speaker_key.lower().replace('_', '-')
            source_path = f'checkpoints_v2/base_speakers/ses/{source_key}.pth'
            if not os.path.exists(source_path):
                print(f"[WARNING] Source embedding not found for {source_key}, skipping.")
                continue

            source_se = torch.load(source_path, map_location=device)

            # Build filename
            if input_text:
                text_snippet = sanitize_text(text)
                filename = f"{speaker_name}_{language}_{text_snippet}.wav" if speaker_name else f"output_v2_{language}_{text_snippet}.wav"
            else:
                lang_lc = language.lower()
                if lang_lc == source_key:
                    filename = f"{speaker_name}_{language}.wav" if speaker_name else f"output_v2_{language}.wav"
                else:
                    filename = f"{speaker_name}_{language}_{source_key}.wav" if speaker_name else f"output_v2_{language}_{source_key}.wav"

            save_path = os.path.join(output_dir, filename)
            tone_color_converter.convert(
                audio_src_path=src_path,
                src_se=source_se,
                tgt_se=target_se,
                output_path=save_path,
                message="@MyShell"
            )
            print(f"[INFO] Saved converted audio to {save_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Voice cloning with optional reference audio and custom text.")
    parser.add_argument('--reference', type=str, help="Path to reference audio for voice cloning.")
    parser.add_argument('--speaker-name', type=str, help="Optional name for the reference speaker.")
    parser.add_argument('--text', type=str, help="Input text to synthesize.")
    parser.add_argument('--language', type=str, help="Language code (e.g., EN, FR, ES, etc.) for the input text.")
    args = parser.parse_args()

    main(
        reference_speaker=args.reference,
        input_text=args.text,
        input_language=args.language,
        speaker_name=args.speaker_name
    )
