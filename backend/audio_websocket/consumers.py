import json
import asyncio

from channels.generic.websocket import AsyncWebsocketConsumer

from backend import run_assistant_osm, run_assistant_general


class AudioStreamConsumer(AsyncWebsocketConsumer):
    DEFAULT_SPEAKER = "amy"
    DEFAULT_LAT = "50.6683"
    DEFAULT_LON = "4.6156"
    DEFAULT_LANG = "en"

    async def connect(self):
        await self.accept()
        print("WebSocket connected")

    async def disconnect(self, close_code):
        print(f"WebSocket disconnected with code: {close_code}")

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            message = data.get("message", "")
            lat = data.get("lat")
            lon = data.get("lon")

            print(f"Received message: {message}")

            await self.send(text_data=json.dumps({
                "type": "ack",
                "message": f"Received: {message}"
            }))

            if message.startswith("?"):
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