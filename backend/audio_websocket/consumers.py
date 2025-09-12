import json
import asyncio

from channels.generic.websocket import AsyncWebsocketConsumer

from backend import run_assistant_osm, run_assistant_general
from utils.transcribe import transcribe_base64_audio


class AudioStreamConsumer(AsyncWebsocketConsumer):
    DEFAULT_SPEAKER = "amy"
    DEFAULT_LAT = "50.6683"
    DEFAULT_LON = "4.6156"
    DEFAULT_LANG = "en"
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.audio_chunks = {}  # Store chunks by session
        self.expected_chunks = {}  # Store expected total chunks by session

    async def connect(self):
        await self.accept()
        print("WebSocket connected")

    async def disconnect(self, close_code):
        print(f"WebSocket disconnected with code: {close_code}")
        # Clean up any pending audio chunks
        self.audio_chunks.clear()
        self.expected_chunks.clear()

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            message_type = data.get("type", "")
            lat = data.get("lat")
            lon = data.get("lon")

            # Handle audio data type
            if message_type == "audio_chunk":
                # Handle chunked audio data
                chunk_data = data.get("data", "")
                chunk_index = data.get("chunk_index", 0)
                total_chunks = data.get("total_chunks", 1)
                
                if not chunk_data:
                    await self.send(text_data=json.dumps({
                        "type": "error",
                        "message": "No chunk data provided"
                    }))
                    return

                # Create a unique session ID for this audio transmission
                session_id = f"{lat}_{lon}_{total_chunks}"
                
                # Initialize chunk storage for this session if needed
                if session_id not in self.audio_chunks:
                    self.audio_chunks[session_id] = {}
                    self.expected_chunks[session_id] = total_chunks
                
                # Store the chunk
                self.audio_chunks[session_id][chunk_index] = chunk_data
                
                print(f"Received audio chunk {chunk_index + 1}/{total_chunks}")
                await self.send(text_data=json.dumps({
                    "type": "ack",
                    "message": f"Received chunk {chunk_index + 1}/{total_chunks}"
                }))
                
                # Check if we have all chunks
                if len(self.audio_chunks[session_id]) == total_chunks:
                    print("All audio chunks received, reconstructing...")
                    await self.send(text_data=json.dumps({
                        "type": "ack",
                        "message": "All chunks received, reconstructing audio..."
                    }))
                    
                    # Reconstruct the complete audio data
                    complete_audio_data = ""
                    for i in range(total_chunks):
                        if i in self.audio_chunks[session_id]:
                            complete_audio_data += self.audio_chunks[session_id][i]
                        else:
                            await self.send(text_data=json.dumps({
                                "type": "error",
                                "message": f"Missing chunk {i}"
                            }))
                            return
                    
                    # Clean up chunk storage
                    del self.audio_chunks[session_id]
                    del self.expected_chunks[session_id]
                    
                    print(f"Reconstructed complete audio data (transcribing...")
                    
                    # Transcribe the reconstructed audio
                    transcribed_text, detected_lang = transcribe_base64_audio(complete_audio_data)
                    
                    if not transcribed_text:
                        await self.send(text_data=json.dumps({
                            "type": "error",
                            "message": "Failed to transcribe reconstructed audio"
                        }))
                        return

                    print(f"Transcribed text: {transcribed_text}")
                    message = transcribed_text
                else:
                    # Still waiting for more chunks
                    return
                
            else:
                # Handle regular text message
                message = data.get("message", "")
                print(f"Received message: {message}")

                await self.send(text_data=json.dumps({
                    "type": "ack",
                    "message": f"Received: {message}"
                }))

            # Process the message (either original text or transcribed text)
            if message.startswith("?"):
                message = message[1:]
                output = run_assistant_osm.main(self.DEFAULT_SPEAKER, self.DEFAULT_LANG,1.0, False, message,  None, lat=lat, lon=lon, output_mode='stream')
            else:
                output = run_assistant_general.main(self.DEFAULT_SPEAKER, self.DEFAULT_LANG,1.0, message, None, output_mode='stream')
            await self.stream_audio_bytes(output)

        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                "type": "error",
                "message": "Invalid JSON format"
            }))
        except Exception as e:
            await self.send(text_data=json.dumps({
                "type": "error",
                "message": f"Error: {str(e)}"
            }))


    async def stream_audio_bytes(self, audio_bytes: bytes, chunk_size: int = 8192):
        await self.send(text_data=json.dumps({
            "type": "audio_start",
            "message": "Starting audio stream from bytes"
        }))

        try:
            for i in range(0, len(audio_bytes), chunk_size):
                chunk = audio_bytes[i:i + chunk_size]
                await self.send(bytes_data=chunk)
                await asyncio.sleep(0.005)  # gentle pacing
        except Exception as e:
            await self.send(text_data=json.dumps({
                "type": "error",
                "message": f"Error streaming audio bytes: {str(e)}"
            }))
            return

        await self.send(text_data=json.dumps({
            "type": "audio_end",
            "message": "Audio stream completed"
        }))