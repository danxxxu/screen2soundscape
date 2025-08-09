#!/usr/bin/env python3
"""
Test script for the WebSocket audio streaming functionality
"""

import asyncio
import websockets
import json
import os

async def test_websocket():
    uri = "ws://localhost:8000/ws/audio/"
    
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected to WebSocket server")
            
            # Send a test message
            test_message = {
                "message": "Hello, please stream some audio!"
            }
            
            print(f"Sending message: {test_message}")
            await websocket.send(json.dumps(test_message))
            
            # Receive responses
            audio_chunks = []
            is_receiving_audio = False
            
            while True:
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                    
                    if isinstance(message, bytes):
                        # Binary audio data
                        if is_receiving_audio:
                            audio_chunks.append(message)
                            print(f"Received audio chunk: {len(message)} bytes")
                    else:
                        # Text message
                        try:
                            data = json.loads(message)
                            print(f"Received: {data}")
                            
                            if data.get('type') == 'audio_start':
                                is_receiving_audio = True
                                print("Starting to receive audio...")
                            elif data.get('type') == 'audio_end':
                                is_receiving_audio = False
                                print("Audio stream completed")
                                print(f"Total audio chunks received: {len(audio_chunks)}")
                                print(f"Total audio data: {sum(len(chunk) for chunk in audio_chunks)} bytes")
                                break
                        except json.JSONDecodeError:
                            print(f"Received text: {message}")
                            
                except asyncio.TimeoutError:
                    print("Timeout waiting for message")
                    break
                    
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    print("Testing WebSocket audio streaming...")
    asyncio.run(test_websocket()) 