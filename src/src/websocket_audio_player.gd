extends Node

signal audio_stream_started
signal audio_stream_completed
signal connection_established
signal connection_failed

var websocket: WebSocketPeer
var audio_stream_player: AudioStreamPlayer
var waiting_ai_player: AudioStreamPlayer
var audio_buffer: PackedByteArray
var is_streaming: bool = false
var is_connected: bool = false
var is_audio_ready: bool = false
var reconnection_attempts: int = 0
var max_reconnection_attempts: int = 5
var reconnection_delay: float = 1.0

# Waiting AI timeout
var waiting_ai_timer: float = 0.0
var max_waiting_timeout: float = 20.0
var is_waiting_ai_playing: bool = false

# Chunk tracking system
var sent_chunks: Dictionary = {}  # chunk_index -> {data, timestamp, retry_count}
var acknowledged_chunks: Array = []  # Array of acknowledged chunk indices
var current_transmission_id: int = 0
var chunk_timeout: float = 5.0  # seconds to wait before resending
var max_retries: int = 3

# WebSocket server URL
#var server_url: String = "ws://localhost:8000/ws/audio/"

var server_url: String = "ws://142.93.234.209:8000/ws/audio/"

# Reference to player for getting position
var player: CharacterBody3D

# Import MapUtils constants
const MapUtils = preload("res://src/map_utils.gd")

func _ready():
	# Create WebSocket peer
	websocket = WebSocketPeer.new()
	
	# Create audio stream player
	audio_stream_player = AudioStreamPlayer.new()
	add_child(audio_stream_player)
	
	# Create waiting AI audio player
	waiting_ai_player = AudioStreamPlayer.new()
	add_child(waiting_ai_player)
	
	# Load waiting AI audio
	var waiting_ai_path = "res://assets/audio/waiting_ai.wav"
	if ResourceLoader.exists(waiting_ai_path):
		var waiting_ai_stream = load(waiting_ai_path) as AudioStream
		waiting_ai_player.stream = waiting_ai_stream
		print("Loaded waiting_ai audio file")
	else:
		print("Warning: Could not load waiting_ai.wav")
	
	# Get reference to player
	player = get_node("../Player")
	
	# Connect signals
	audio_stream_player.finished.connect(_on_audio_finished)
	waiting_ai_player.finished.connect(_on_waiting_ai_finished)
	
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


func get_player_coordinates() -> Dictionary:
	if not player:
		return {"lat": 0.0, "lon": 0.0}
	
	# Get player position
	var player_pos = player.global_position
	
	# Convert local coordinates to lat/lon using MapUtils
	var local_pos = Vector2(player_pos.x, player_pos.z)
	var global_coords = MapUtils.convert_to_global_coords(local_pos)
	
	return {"lat": global_coords.x, "lon": global_coords.y}

func send_command(command_text: String):
	# Start playing waiting AI audio
	_start_waiting_ai_audio()
	
	# Get player coordinates
	var coords = get_player_coordinates()
	
	# Create message with command and coordinates
	var message = {
		"message": command_text,
		"lat": coords.lat,
		"lon": coords.lon,
		"lang": 'fr',
		"speaker": 'siwis'
		
		# "lang": 'en',
		#"speaker": 'amy'
	}
	
	if websocket and websocket.get_ready_state() == WebSocketPeer.STATE_OPEN:
		var json_string = JSON.stringify(message)
		websocket.send_text(json_string)
		print("Sent command to WebSocket: ", json_string)
	else:
		print("WebSocket not connected. Press F5 to manually reconnect.")
		print("Cannot send command: ", command_text)
		# Stop waiting AI if connection fails
		_stop_waiting_ai_audio()

func _process(delta):
	websocket.poll()
	
	# Update waiting AI timer
	if is_waiting_ai_playing:
		waiting_ai_timer += delta
		if waiting_ai_timer >= max_waiting_timeout:
			print("Waiting AI timeout reached, stopping audio")
			_stop_waiting_ai_audio()
	
	# Check for missing chunks periodically
	if sent_chunks.size() > 0:
		_check_for_missing_chunks()
	
	var state = websocket.get_ready_state()
	if websocket.get_ready_state() == WebSocketPeer.STATE_OPEN:
		if not is_connected:
			is_connected = true
			reconnection_attempts = 0  # Reset reconnection attempts on successful connection
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
						if data.has("type"):
							if data["type"] == "audio_end":
								print("Audio stream completed: ", data["message"])
								is_streaming = false
								is_audio_ready = true
								# Stop waiting AI when audio stream is completed/ready
								_stop_waiting_ai_audio()
								audio_stream_completed.emit()
								_play_audio_buffer()  # Play the complete audio
							elif data["type"] == "ack":
								_handle_acknowledgment(data)
				
				# Check if it's binary data (MP3 chunks)
				else:
					if not is_streaming:
						is_streaming = true
						audio_buffer.clear()
						print("Starting to receive audio stream...")
						# Stop waiting AI audio when receiving audio data back
						_stop_waiting_ai_audio()
						audio_stream_started.emit()
					
					# Append binary data to buffer
					audio_buffer.append_array(packet)
					print("Received MP3 chunk, buffer size: ", audio_buffer.size())
		
		elif code == WebSocketPeer.STATE_CLOSED:
			print("WebSocket connection closed")
			is_connected = false
			is_streaming = false
			print("Press F5 to manually reconnect to WebSocket server")
				
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

func _on_waiting_ai_finished():
	print("Waiting AI audio finished")
	if is_waiting_ai_playing:
		# Loop the waiting AI audio if it finished and we're still waiting
		waiting_ai_player.play()

func _on_connection_established():
	print("WebSocket connection established")
	reconnection_attempts = 0  # Reset reconnection attempts on successful connection

func reset_reconnection_attempts():
	reconnection_attempts = 0
	print("Reconnection attempts reset")

func manual_reconnect():
	print("Manual reconnection requested")
	reconnection_attempts = 0  # Reset attempts for manual reconnection
	connect_to_server()

func _input(event):
	if event is InputEventKey and event.pressed:
		if event.keycode == KEY_F5:
			print("F5 pressed - attempting to reconnect to WebSocket server")
			manual_reconnect()

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

func send_audio_data(audio_data: String):
	# Start playing waiting AI audio when sending voice data
	_start_waiting_ai_audio()
	
	# Get player coordinates
	var coords = get_player_coordinates()
	
	# Create message with complete audio data
	var message = {
		"type": "audio_data",
		"data": audio_data,
		"lat": coords.lat,
		"lon": coords.lon
	}
	
	if websocket and websocket.get_ready_state() == WebSocketPeer.STATE_OPEN:
		var json_string = JSON.stringify(message)
		websocket.send_text(json_string)
		print("Sent complete audio file to WebSocket")
	else:
		print("WebSocket not connected. Press F5 to manually reconnect.")
		print("Cannot send audio file")
		# Stop waiting AI if connection fails
		_stop_waiting_ai_audio()

func send_audio_chunk(audio_chunk: String, chunk_index: int, total_chunks: int):
	# Start playing waiting AI audio when sending first chunk
	if chunk_index == 0:
		_start_waiting_ai_audio()
	
	# Get player coordinates
	var coords = get_player_coordinates()
	
	# Create message with audio chunk data
	var message = {
		"type": "audio_chunk",
		"data": audio_chunk,
		"chunk_index": chunk_index,
		"total_chunks": total_chunks,
		"transmission_id": current_transmission_id,
		"lat": coords.lat,
		"lon": coords.lon
	}
	
	# Track the chunk for potential resending
	sent_chunks[chunk_index] = {
		"data": audio_chunk,
		"timestamp": Time.get_unix_time_from_system(),
		"retry_count": 0,
		"total_chunks": total_chunks,
		"message": message
	}
	
	if websocket and websocket.get_ready_state() == WebSocketPeer.STATE_OPEN:
		var json_string = JSON.stringify(message)
		websocket.send_text(json_string)
		print("Sent audio chunk ", chunk_index + 1, "/", total_chunks, " to WebSocket")
	else:
		print("WebSocket not connected. Press F5 to manually reconnect.")
		print("Cannot send audio chunk: ", chunk_index)
		# Stop waiting AI if connection fails (only for first chunk failure)
		if chunk_index == 0:
			_stop_waiting_ai_audio()

func _handle_acknowledgment(data: Dictionary):
	# Extract chunk number from acknowledgment message
	var message = data.get("message", "")
	var regex = RegEx.new()
	regex.compile("Received chunk (\\d+)/(\\d+)")

	var chunk_match = regex.search(message)
	
	if chunk_match:
		var chunk_num = int(chunk_match.get_string(1)) - 1  # Convert to 0-based index
		var total_chunks = int(chunk_match.get_string(2))
		
		print("Received acknowledgment for chunk ", chunk_num + 1, "/", total_chunks)
		
		# Mark chunk as acknowledged
		if chunk_num not in acknowledged_chunks:
			acknowledged_chunks.append(chunk_num)
		
		# Remove from sent_chunks tracking
		if chunk_num in sent_chunks:
			sent_chunks.erase(chunk_num)
		
		# Check if all chunks are acknowledged
		if acknowledged_chunks.size() == total_chunks:
			print("All chunks acknowledged successfully!")
			_clear_transmission_data()

func _check_for_missing_chunks():
	var current_time = Time.get_unix_time_from_system()
	var chunks_to_resend = []
	
	for chunk_index in sent_chunks.keys():
		var chunk_data = sent_chunks[chunk_index]
		var time_since_sent = current_time - chunk_data.timestamp
		
		if time_since_sent > chunk_timeout and chunk_data.retry_count < max_retries:
			chunks_to_resend.append(chunk_index)
	
	# Resend missing chunks
	for chunk_index in chunks_to_resend:
		_resend_chunk(chunk_index)

func _resend_chunk(chunk_index: int):
	if chunk_index not in sent_chunks:
		return
	
	var chunk_data = sent_chunks[chunk_index]
	chunk_data.retry_count += 1
	chunk_data.timestamp = Time.get_unix_time_from_system()
	
	print("Resending chunk ", chunk_index + 1, "/", chunk_data.total_chunks, " (attempt ", chunk_data.retry_count, ")")
	
	if websocket and websocket.get_ready_state() == WebSocketPeer.STATE_OPEN:
		var json_string = JSON.stringify(chunk_data.message)
		websocket.send_text(json_string)
	else:
		print("WebSocket not connected, cannot resend chunk: ", chunk_index)

func _clear_transmission_data():
	sent_chunks.clear()
	acknowledged_chunks.clear()
	current_transmission_id += 1

func start_new_transmission():
	_clear_transmission_data()
	print("Started new transmission with ID: ", current_transmission_id)

func _start_waiting_ai_audio():
	if waiting_ai_player and waiting_ai_player.stream:
		print("Starting waiting AI audio")
		waiting_ai_player.play()
		is_waiting_ai_playing = true
		waiting_ai_timer = 0.0
	else:
		print("Warning: Could not start waiting AI audio - file not loaded")

func _stop_waiting_ai_audio():
	if waiting_ai_player:
		waiting_ai_player.stop()
		is_waiting_ai_playing = false
		waiting_ai_timer = 0.0
		print("Stopped waiting AI audio")

func _exit_tree():
	disconnect_from_server() 
