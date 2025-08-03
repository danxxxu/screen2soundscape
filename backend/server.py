# server.py
from fastapi import FastAPI
from osm_voice_assistant.transcribe import record_and_transcribe
from osm_voice_assistant.query_builder import build_and_run_query
from osm_voice_assistant.speak import speak

app = FastAPI()

@app.get("/ask")
async def ask():
    q = record_and_transcribe()
    answer = build_and_run_query(q)
    speak(answer)
    return {"question": q, "answer": answer}
