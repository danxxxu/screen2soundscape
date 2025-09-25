extends Node3D

var command_mode: bool = false
var current_command: String = ""
var command_label: Label
var current_place: Node3D = null 
var player: Node3D = null
var websocket_audio_player: Node
var boundary_detector: BoundaryDetector
var polygons_system: Node3D

func _ready():
	command_label = Label.new()
	command_label.position = Vector2(15, 300)  # Position below existing HUD
	command_label.visible = false
	$HUD.add_child(command_label)
	update_command_label()
	player = get_node("Player")
	
	# Initialize WebSocket audio player as a proper node
	websocket_audio_player = Node.new()
	websocket_audio_player.set_script(preload("res://src/websocket_audio_player.gd"))
	add_child(websocket_audio_player)
	
	# Start WebSocket connection
	websocket_audio_player.connect_to_server()
	
	# Get the existing boundary detector from the scene
	boundary_detector = get_node("boundary_detector") as BoundaryDetector
		
	print("🔲 Boundary detector initialized")
	
	# Initialize polygons system
	polygons_system = Node3D.new()
	polygons_system.name = "Polygons"
	polygons_system.set_script(preload("res://src/polygons.gd"))
	add_child(polygons_system)
		
	print("🌿 Polygons system initialized")


func update_command_label():
	if command_mode:
		command_label.text = "> " + current_command
		command_label.visible = true
		if player:
			player.set_movement_enabled(false)  # Disable player movement
	else:
		command_label.visible = false
		if player:
			player.set_movement_enabled(true)  # Re-enable player movement

func execute_command(cmd: String):
	if cmd.begins_with("goto "):
		var location = cmd.substr(5).strip_edges()  # Remove "goto " prefix
		await _handle_goto_command(location)
		return
	
	if cmd.begins_with("restart") or cmd.begins_with("reset"):
		reset_player()
		return
	match cmd.to_lower():
		"address":
			if current_place and current_place.place_data:
				var address = ""
				var tags = current_place.place_data.tags
				if tags.has("addr:street"):
					address += tags["addr:street"]
					if tags.has("addr:housenumber"):
						address += " " + tags["addr:housenumber"]
				if address != "":
					current_place.speak(address)
				else:
					current_place.speak("No address available")
		_:
			# Send unknown commands to WebSocket
			print("Sending command to WebSocket: ", cmd)
			if websocket_audio_player and websocket_audio_player.has_method("send_command"):
				websocket_audio_player.send_command(cmd)
			else:
				print("WebSocket audio player not available or send_command method not found")

func _input(event):
	if event is InputEventKey:
		if event.pressed:
			if event.keycode == KEY_ENTER:
				# Check if Shift is pressed for goto command mode
				if event.shift_pressed:
					# Shift+Enter: Enter goto command mode
					if command_mode:
						current_command = "goto " + current_command
						await execute_command(current_command)	
						current_command = ""
						command_mode = false	
						update_command_label()			
											
				else:
					# Regular Enter: Toggle command mode or execute command
					if command_mode:
						# Execute command
						await execute_command(current_command)
						current_command = ""
						command_mode = false
					else:
						# Enter command mode
						command_mode = true
					update_command_label()
			elif command_mode:
				if event.keycode == KEY_BACKSPACE:
					current_command = current_command.substr(0, max(0, current_command.length() - 1))
				elif event.keycode == KEY_ESCAPE:
					command_mode = false
					current_command = ""
				elif event.is_pressed() and not event.echo:
					var char = char(event.unicode)
					if char.length() > 0 and event.unicode >= 32:  # Printable characters
						current_command += char
				update_command_label()

# Called when player enters a place's area
func _on_place_entered(place: Node3D):
	current_place = place

# Called when player exits a place's area
func _on_place_exited(place: Node3D):
	if current_place == place:
		current_place = null

# Handle goto command - search for location and update start position
func _handle_goto_command(location: String):
	print("🗺️ Searching for location: ", location)
	
	# Show loading message
	command_label.text = "> Searching for " + location + "..."
	
	# URL encode the location
	var encoded_location = location.uri_encode()
	var url = "https://nominatim.openstreetmap.org/search?format=json&q=" + encoded_location
	
	print("🌐 Making request to: ", url)
	
	# Use await approach - much simpler!
	var result = await _make_http_request(url)
	
	if result == null || result == {}:
		print("❌ Request failed or timed out")
		command_label.text = "> Error: Failed to search for location"
		return
	
	# Process the result
	await _process_nominatim_result(result, location)

# Make HTTP request using await
func _make_http_request(url: String) -> Dictionary:
	var http_request = HTTPRequest.new()
	http_request.use_threads = true
	add_child(http_request)
	
	# Wait for the request to complete
	var error = http_request.request(url)
	if error != OK:
		print("❌ Failed to make HTTP request: ", error)
		http_request.queue_free()
		return {}
	
	# Wait for response with timeout
	var response = await http_request.request_completed
	http_request.queue_free()
	
	print("📡 Received response: ", response[1])  # response_code is at index 1
	
	if response[1] != 200:  # response_code
		print("❌ HTTP error: ", response[1])
		return {}
	
	return {
		"result": response[0],
		"response_code": response[1], 
		"headers": response[2],
		"body": response[3]
	}

# Process Nominatim API result
func _process_nominatim_result(result: Dictionary, location: String):
	var body = result["body"]
	print("📦 Processing response body, size: ", body.size(), " bytes")
	
	# Parse JSON response
	var json = JSON.new()
	var parse_result = json.parse(body.get_string_from_utf8())
	
	if parse_result != OK:
		print("❌ Failed to parse JSON response")
		command_label.text = "> Error: Invalid response from server"
		return
	
	var data = json.data
	if not data is Array or data.size() == 0:
		print("❌ No results found for location: ", location)
		command_label.text = "> No results found for: " + location
		return
	
	# Get the first result
	var nom_result = data[0]
	var lat = float(nom_result["lat"])
	var lon = float(nom_result["lon"])
	var display_name = nom_result["display_name"]
	
	# Update the start location in MapUtils
	MapUtils.start = Vector2(lat, lon)
	print("🔄 Updated start location to: ", MapUtils.start)
	
	# Clear existing data and refetch for new area using boundary detector
	await _clear_and_refetch_data()
	
	reset_player()
	command_label.text = "> Moved to: " + display_name

func reset_player():
	if player:
		player.global_position = Vector3(0, player.global_position.y, 0)

		
# Clear existing data and refetch for new area using boundary detector
func _clear_and_refetch_data():
	print("🧹 Clearing existing data...")
	
	if not boundary_detector:
		print("❌ Boundary detector not found")
		return
	
	# Clear existing data using boundary detector's method
	boundary_detector._clear_existing_data()
	print("🧹 Cleared existing data")
	
	# Clear loaded cells and reset boundary detector
	boundary_detector.LoadedCels.clear()
	boundary_detector.current_cell = Vector2i.ZERO
	print("🔄 Reset boundary detector")
	
	# Force boundary check to load new area around the new start location
	print("🌐 Fetching data for new area...")
	await boundary_detector.force_boundary_check()
	
	print("✅ Data cleared and refetched for new location")
