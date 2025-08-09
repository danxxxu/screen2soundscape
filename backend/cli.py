# cli.py
import click
from osm_voice_assistant.transcribe import record_and_transcribe
from osm_voice_assistant.query_builder import build_and_run_query
from osm_voice_assistant.speak import speak

@click.command()
def main():
    q = record_and_transcribe()
    print("You said:", q)
    answer = build_and_run_query(q)
    print("Answer:", answer)
    speak(answer)

if __name__ == "__main__":
    main()
