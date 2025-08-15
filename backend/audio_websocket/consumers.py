# audio_websocket/consumers.py
import json
import os
import re
import sys
import asyncio
from pathlib import Path

from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings


class AudioStreamConsumer(AsyncWebsocketConsumer):
    # --- configure your defaults here ---
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

            print(f"Received message: {message}")

            # Acknowledge
            await self.send(text_data=json.dumps({
                "type": "ack",
                "message": f"Received: {message}"
            }))

            # Kick off the assistant and stream its output back
            await self.run_assistant_and_stream_output(user_message=message)

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

    # ---------- NEW: run assistant and stream its output ----------

    async def run_assistant_and_stream_output(self, user_message: str):
        """
        Spawns `python -m backend.run_assistant ...` and streams stdout/stderr lines
        back over the websocket. If it prints an AUDIO_FILE=... line, we stream that file too.
        """
        # Build the command using this Python interpreter
        cmd = [
            sys.executable, "-m", "backend.run_assistant",
            "--speaker", self.DEFAULT_SPEAKER,
            "--text", user_message,
            "--lat", self.DEFAULT_LAT,
            "--lon", self.DEFAULT_LON,
            "--language", self.DEFAULT_LANG,
        ]

        # Notify client we started
        await self.send(text_data=json.dumps({
            "type": "assistant_start",
            "message": "Starting assistant"
        }))

        # Start subprocess (non-blocking)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        audio_path_found = None

        async def _read_stream(stream, stream_type: str):
            nonlocal audio_path_found
            while True:
                line = await stream.readline()
                if not line:
                    break
                decoded = line.decode(errors="ignore").rstrip()

                # Try to detect an audio path from the assistant's output
                maybe_path = self.parse_audio_path_from_line(decoded)
                if maybe_path and not audio_path_found:
                    audio_path_found = maybe_path

                # Stream incremental logs to the client
                await self.send(text_data=json.dumps({
                    "type": "assistant_log",
                    "stream": stream_type,
                    "message": decoded
                }))

        # Read both stdout and stderr concurrently
        stdout_task = asyncio.create_task(_read_stream(proc.stdout, "stdout"))
        stderr_task = asyncio.create_task(_read_stream(proc.stderr, "stderr"))

        # Wait for process to finish
        await asyncio.gather(stdout_task, stderr_task)
        return_code = await proc.wait()

        await self.send(text_data=json.dumps({
            "type": "assistant_done",
            "return_code": return_code
        }))

        # If an audio file was announced, stream it
        if audio_path_found:
            await self.stream_file(audio_path_found)
        else:
            # Fall back to your sample file if you still want to stream something
            # Comment this out if you don't want a fallback
            # await self.stream_file(os.path.join(settings.BASE_DIR, 'sample_audio', 'arnold_original.mp3'))
            pass

    @staticmethod
    def parse_audio_path_from_line(line: str) -> str | None:
        """
        Detect a produced audio file path from a log line.
        Adjust this pattern to whatever your assistant prints.
        Examples it will catch:
          AUDIO_FILE=path/to/file.mp3
          audio_file: C:\...\out.wav
        """
        # Try common "key=value" format
        m = re.search(r"(?:^|\b)AUDIO_FILE\s*=\s*(.+\.(?:mp3|wav|ogg|flac))\b", line, re.IGNORECASE)
        if m:
            return m.group(1).strip('"').strip("'")

        # Try "audio_file:" format
        m = re.search(r"(?:^|\b)audio[_\s-]*file\s*:\s*(.+\.(?:mp3|wav|ogg|flac))\b", line, re.IGNORECASE)
        if m:
            return m.group(1).strip('"').strip("'")

        return None

    # ---------- Streaming helpers ----------

    async def stream_file(self, file_path: str, chunk_size: int = 8192):
        """
        Stream a binary audio file to the client in chunks, sending start/end markers.
        """
        # Resolve path relative to BASE_DIR if not absolute
        path = Path(file_path)
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / path

        if not path.exists():
            await self.send(text_data=json.dumps({
                "type": "error",
                "message": f"Audio file not found: {str(path)}"
            }))
            return

        # Announce start
        await self.send(text_data=json.dumps({
            "type": "audio_start",
            "message": f"Starting audio stream: {path.name}"
        }))

        try:
            with path.open("rb") as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    await self.send(bytes_data=chunk)
                    await asyncio.sleep(0.005)  # gentle pacing
        except Exception as e:
            await self.send(text_data=json.dumps({
                "type": "error",
                "message": f"Error streaming audio: {str(e)}"
            }))
            return

        # Announce end
        await self.send(text_data=json.dumps({
            "type": "audio_end",
            "message": "Audio stream completed"
        }))

# import json
# import os
# from channels.generic.websocket import AsyncWebsocketConsumer
# from django.conf import settings


# class AudioStreamConsumer(AsyncWebsocketConsumer):
#     async def connect(self):
#         await self.accept()
#         print("WebSocket connected")

#     async def disconnect(self, close_code):
#         print(f"WebSocket disconnected with code: {close_code}")

#     async def receive(self, text_data):
#         try:
#             # Parse the incoming text data
#             data = json.loads(text_data)
#             message = data.get('message', '')
            
#             print(f"Received message: {message}")
            
#             # Send acknowledgment
#             await self.send(text_data=json.dumps({
#                 'type': 'ack',
#                 'message': f'Received: {message}'
#             }))
            
#             # Stream the audio file
#             await self.stream_audio()
            
#         except json.JSONDecodeError:
#             await self.send(text_data=json.dumps({
#                 'type': 'error',
#                 'message': 'Invalid JSON format'
#             }))
#         except Exception as e:
#             await self.send(text_data=json.dumps({
#                 'type': 'error',
#                 'message': f'Error: {str(e)}'
#             }))

#     async def stream_audio(self):
#         """Stream the MP3 file to the client"""
#         audio_file_path = os.path.join(settings.BASE_DIR, 'sample_audio', 'arnold_original.mp3')
        
#         if not os.path.exists(audio_file_path):
#             await self.send(text_data=json.dumps({
#                 'type': 'error',
#                 'message': 'Audio file not found'
#             }))
#             return
        
#         try:
#             # Read the audio file in chunks
#             chunk_size = 8192  # 8KB chunks
            
#             with open(audio_file_path, 'rb') as audio_file:
#                 # Send start of audio stream
#                 await self.send(text_data=json.dumps({
#                     'type': 'audio_start',
#                     'message': 'Starting audio stream'
#                 }))
                
#                 # Stream audio data
#                 while True:
#                     chunk = audio_file.read(chunk_size)
#                     if not chunk:
#                         break
                    
#                     # Send binary data
#                     await self.send(bytes_data=chunk)
                    
#                     # Small delay to prevent overwhelming the connection
#                     import asyncio
#                     await asyncio.sleep(0.01)
                
#                 # Send end of audio stream
#                 await self.send(text_data=json.dumps({
#                     'type': 'audio_end',
#                     'message': 'Audio stream completed'
#                 }))
                
#         except Exception as e:
#             await self.send(text_data=json.dumps({
#                 'type': 'error',
#                 'message': f'Error streaming audio: {str(e)}'
#             })) 