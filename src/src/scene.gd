extends Node3D
"res://rocky_terrain_02_diff_4k.jpg"
@export var map_size: Vector3 = Vector3(1000, 0, 1000) # Map size in local units
@export var place_meshes: Array[PackedScene] # Assign random meshes in the editor
@export var place_sounds: Array[AudioStream] # Assign random sounds in the editor

var command_mode: bool = false
var current_command: String = ""
var command_label: Label
var current_place: Node3D = null  # Store the current place player is near
var player: Node3D = null  # Reference to the player node

func _ready():
	# Create command label
	command_label = Label.new()
	command_label.position = Vector2(15, 300)  # Position below existing HUD
	command_label.visible = false
	$HUD.add_child(command_label)
	update_command_label()

	# Get reference to player node
	player = get_node("Player")
	
	# Set up places component with assets
	var places_node = get_node("Places")
	if places_node and places_node.has_method("set_place_assets"):
		places_node.set_place_assets(place_meshes, place_sounds)


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
			print("Unknown command: ", cmd)

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
