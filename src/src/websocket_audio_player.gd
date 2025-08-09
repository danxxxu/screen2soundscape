extends Node

signal audio_stream_started
signal audio_stream_completed
signal connection_established
signal connection_failed

var websocket: WebSocketPeer
var audio_stream_player: AudioStreamPlayer
var audio_buffer: PackedByteArray
var is_streaming: bool = false
var is_connected: bool = false
var is_audio_ready: bool = false

# WebSocket server URL
var server_url: String = "ws://localhost:8000/ws/audio/"

func _ready():
	# Create WebSocket peer
	websocket = WebSocketPeer.new()
	
	# Create audio stream player
	audio_stream_player = AudioStreamPlayer.new()
	add_child(audio_stream_player)
	
	# Connect signals
	audio_stream_player.finished.connect(_on_audio_finished)
	
	# Connect our custom signals
	connection_established.connect(_on_connection_established)
	connection_failed.connect(_on_connection_failed)
	audio_stream_started.connect(_on_audio_stream_started)
	audio_stream_completed.connect(_on_audio_stream_completed)
	websocket.connect_to_url(server_url)

	print("WebSocket Audio Player ready")

func connect_to_server():
	print("Connecting to WebSocket server: ", server_url)
	
	var error = websocket.connect_to_url(server_url)
	if error != OK:
		print("Failed to connect to WebSocket server: ", error)
		connection_failed.emit()
		return
	
	print("Connection request sent to WebSocket server")

func send_command(command_text: String):
	if websocket and websocket.get_ready_state() == WebSocketPeer.STATE_OPEN:
		var message = {"message": command_text}
		var json_string = JSON.stringify(message)
		websocket.send_text(json_string)
		print("Sent command to WebSocket: ", json_string)
	else:
		print("WebSocket not connected, cannot send command: ", command_text)

func _process(delta):
	websocket.poll()
	
	var state = websocket.get_ready_state()
	if websocket.get_ready_state() == WebSocketPeer.STATE_OPEN:
		if not is_connected:
			is_connected = true
			print("WebSocket connection established")
			connection_established.emit()
			
		# Poll for messages
		var code = websocket.get_ready_state()
		
		if code == WebSocketPeer.STATE_OPEN:
			while websocket.get_available_packet_count():
				var packet = websocket.get_packet()
				
				# Check if it's a text message (JSON)
				if websocket.was_string_packet():
					var text = packet.get_string_from_utf8()
					print("Received text message: ", text)
					
					# Parse JSON message
					var json = JSON.new()
					var parse_result = json.parse(text)
					
					if parse_result == OK:
						var data = json.data
						if data.has("type") and data["type"] == "audio_end":
							print("Audio stream completed: ", data["message"])
							is_streaming = false
							is_audio_ready = true
							audio_stream_completed.emit()
							_play_audio_buffer()  # Play the complete audio
				
				# Check if it's binary data (MP3 chunks)
				else:
					if not is_streaming:
						is_streaming = true
						audio_buffer.clear()
						print("Starting to receive audio stream...")
						audio_stream_started.emit()
					
					# Append binary data to buffer
					audio_buffer.append_array(packet)
					print("Received MP3 chunk, buffer size: ", audio_buffer.size())
		
		elif code == WebSocketPeer.STATE_CLOSED:
			print("WebSocket connection closed")
			is_connected = false
			is_streaming = false
		elif code == WebSocketPeer.STATE_CLOSING:
			print("WebSocket connection closing...")
		elif code == WebSocketPeer.STATE_CONNECTING:
			print("WebSocket connecting...")

func _play_audio_buffer():
	if audio_buffer.size() == 0:
		return
	
	print("Playing complete audio stream, size: ", audio_buffer.size())
	
	# Create an AudioStreamMP3 from the buffer
	var audio_stream = AudioStreamMP3.new()
	audio_stream.data = audio_buffer
	
	# Set the stream to the player
	audio_stream_player.stream = audio_stream
	
	# Play the audio
	if not audio_stream_player.playing:
		audio_stream_player.play()
		print("Started playing complete audio stream")

func _on_audio_finished():
	print("Audio playback finished")

func _on_connection_established():
	print("WebSocket connection established")

func _on_connection_failed():
	print("WebSocket connection failed")

func _on_audio_stream_started():
	print("Audio stream started - downloading...")

func _on_audio_stream_completed():
	print("Audio stream completed - ready to play")

func disconnect_from_server():
	if websocket:
		websocket.close()
		is_connected = false
		is_streaming = false
		print("Disconnected from WebSocket server")

func _exit_tree():
	disconnect_from_server() 
