import json
import os
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings


class AudioStreamConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()
        print("WebSocket connected")

    async def disconnect(self, close_code):
        print(f"WebSocket disconnected with code: {close_code}")

    async def receive(self, text_data):
        try:
            # Parse the incoming text data
            data = json.loads(text_data)
            message = data.get('message', '')
            
            print(f"Received message: {message}")
            
            # Send acknowledgment
            await self.send(text_data=json.dumps({
                'type': 'ack',
                'message': f'Received: {message}'
            }))
            
            # Stream the audio file
            await self.stream_audio()
            
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON format'
            }))
        except Exception as e:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Error: {str(e)}'
            }))

    async def stream_audio(self):
        """Stream the MP3 file to the client"""
        audio_file_path = os.path.join(settings.BASE_DIR, 'sample_audio', 'arnold_original.mp3')
        
        if not os.path.exists(audio_file_path):
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Audio file not found'
            }))
            return
        
        try:
            # Read the audio file in chunks
            chunk_size = 8192  # 8KB chunks
            
            with open(audio_file_path, 'rb') as audio_file:
                # Send start of audio stream
                await self.send(text_data=json.dumps({
                    'type': 'audio_start',
                    'message': 'Starting audio stream'
                }))
                
                # Stream audio data
                while True:
                    chunk = audio_file.read(chunk_size)
                    if not chunk:
                        break
                    
                    # Send binary data
                    await self.send(bytes_data=chunk)
                    
                    # Small delay to prevent overwhelming the connection
                    import asyncio
                    await asyncio.sleep(0.01)
                
                # Send end of audio stream
                await self.send(text_data=json.dumps({
                    'type': 'audio_end',
                    'message': 'Audio stream completed'
                }))
                
        except Exception as e:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Error streaming audio: {str(e)}'
            })) 