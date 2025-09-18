extends Node3D

var command_mode: bool = false
var current_command: String = ""
var command_label: Label
var current_place: Node3D = null 
var player: Node3D = null
var websocket_audio_player: Node
var boundary_detector: BoundaryDetector

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
	
	# Initialize boundary detector
	boundary_detector = Node3D.new()
	boundary_detector.set_script(preload("res://src/boundary_detector.gd"))
	add_child(boundary_detector)
		
	print("🔲 Boundary detector initialized")


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
				if command_mode:
					# Execute command
					execute_command(current_command)
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
