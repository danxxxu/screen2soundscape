# Django WebSocket Audio Streamer

A Django project with WebSocket support that receives text messages from clients and streams MP3 audio data back in response.

## Features

- **WebSocket Communication**: Real-time bidirectional communication between client and server
- **Audio Streaming**: Streams MP3 audio files in binary format
- **Text-to-Audio**: Receives text messages and responds with audio streams
- **Modern UI**: Clean, responsive web interface for testing

## Project Structure

```
backend/
├── audio_streamer/          # Django project settings
├── audio_websocket/         # Django app for WebSocket handling
│   ├── consumers.py         # WebSocket consumer for audio streaming
│   ├── routing.py           # WebSocket URL routing
│   ├── views.py             # HTTP views
│   ├── urls.py              # URL configuration
│   └── templates/           # HTML templates
├── sample_audio/            # Sample audio files
│   └── arnold_original.mp3 # Sample MP3 file
├── venv/                    # Virtual environment
├── manage.py                # Django management script
├── requirements.txt         # Python dependencies
└── test_websocket.py       # Test script
```

## Installation

1. **Create and activate virtual environment**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run database migrations**:
   ```bash
   python manage.py migrate
   ```

## Usage

### Starting the Server

```bash
source venv/bin/activate
python manage.py runserver
```

The server will start on `http://localhost:8000/`

### Web Interface

1. Open your browser and navigate to `http://localhost:8000/`
2. Click "Connect" to establish WebSocket connection
3. Enter a message in the text field
4. Click "Send Message" to trigger audio streaming
5. The audio will be streamed and can be played in the audio player

### WebSocket Endpoint

- **URL**: `ws://localhost:8000/ws/audio/`
- **Protocol**: WebSocket
- **Message Format**: JSON
  ```json
  {
    "message": "Your text message here"
  }
  ```

### Response Types

1. **Acknowledgment**:
   ```json
   {
     "type": "ack",
     "message": "Received: Your message"
   }
   ```

2. **Audio Start**:
   ```json
   {
     "type": "audio_start",
     "message": "Starting audio stream"
   }
   ```

3. **Audio Data**: Binary MP3 chunks

4. **Audio End**:
   ```json
   {
     "type": "audio_end",
     "message": "Audio stream completed"
   }
   ```

5. **Error**:
   ```json
   {
     "type": "error",
     "message": "Error description"
   }
   ```

## Testing

### Web Interface Test

1. Open `http://localhost:8000/` in your browser
2. Use the interactive interface to test WebSocket communication

### Command Line Test

```bash
source venv/bin/activate
python test_websocket.py
```

This will connect to the WebSocket server, send a test message, and display the received audio chunks.

## Configuration

### Django Settings

The project is configured with:
- **Channels**: For WebSocket support
- **In-Memory Channel Layer**: For development (no Redis required)
- **Daphne**: ASGI server for WebSocket handling

### Audio File

The system uses `sample_audio/arnold_original.mp3` as the default audio file to stream. You can modify the path in `audio_websocket/consumers.py`.

## Dependencies

- **Django 5.0.2**: Web framework
- **Channels 4.0.0**: WebSocket support
- **Daphne 4.1.0**: ASGI server
- **Redis 5.2.1**: Channel layer backend (optional for development)

## Development

### Adding New Audio Files

1. Place your MP3 files in the `sample_audio/` directory
2. Update the file path in `audio_websocket/consumers.py`

### Modifying the Consumer

The main WebSocket logic is in `audio_websocket/consumers.py`. You can:
- Modify the message processing logic
- Change the audio streaming behavior
- Add authentication or rate limiting
- Implement different audio formats

### Production Deployment

For production:
1. Use Redis as the channel layer backend
2. Configure proper ASGI server (Daphne, Uvicorn, etc.)
3. Set up proper static file serving
4. Configure security settings

## Troubleshooting

### Common Issues

1. **WebSocket Connection Failed**: Ensure the server is running and the URL is correct
2. **Audio Not Playing**: Check browser console for errors and ensure audio format is supported
3. **File Not Found**: Verify the audio file path in the consumer

### Debug Mode

The project runs in debug mode by default. Check the Django console for detailed error messages and WebSocket connection logs. 