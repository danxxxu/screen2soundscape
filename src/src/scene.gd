extends Node3D
"res://rocky_terrain_02_diff_4k.jpg"
const PlaceData = preload("res://src/models/Place.gd")
@export var map_size: Vector3 = Vector3(1000, 0, 1000) # Map size in local units
@export var place_meshes: Array[PackedScene] # Assign random meshes in the editor
@export var place_sounds: Array[AudioStream] # Assign random sounds in the editor

var place_scenes: Array[PlaceData] # Holds dynamically generated places
var center_lat: float = 52.0785266  # Center latitude (Dudok cafe as center point)
var center_lon: float = 4.3117263   # Center longitude
var scale_factor: float = 1000.0    # Scale factor to convert degrees to local units

var command_mode: bool = false
var current_command: String = ""
var command_label: Label
var current_place: Node3D = null  # Store the current place player is near
var player: Node3D = null  # Reference to the player node

# Convert lat/lon to local coordinates
func convert_to_local_coords(lat: float, lon: float) -> Vector2:
	# Calculate difference from center point
	var lat_diff = lat - center_lat
	var lon_diff = lon - center_lon
	
	# Convert to local coordinates
	# We multiply by scale_factor to convert tiny degree differences to meaningful distances
	# Note: cos(center_lat) accounts for longitude distortion at different latitudes
	var x = lon_diff * cos(deg_to_rad(center_lat)) * scale_factor
	var z = lat_diff * scale_factor
	
	# Scale to map bounds
	x = clamp(x * map_size.x, -map_size.x / 2, map_size.x / 2)
	z = clamp(z * map_size.z, -map_size.z / 2, map_size.z / 2)
	
	return Vector2(x, z)

func load_places_from_json() -> void:
	var file = FileAccess.open("res://src/models/places.json", FileAccess.READ)
	if file:
		var json_text = file.get_as_text()
		var json = JSON.parse_string(json_text)
		if json and json.has("elements"):
			for element in json["elements"]:
				if element["type"] == "node" and element.has("tags"):
					var place = PlaceData.new()
					
					# Store all tags
					place.tags = element["tags"].duplicate()
					
					# Get name and type
					place.name = element["tags"].get("name", "Unnamed Place")
					place.type = element["tags"].get("amenity", element["tags"].get("shop", "unknown"))
					
					# Convert coordinates
					var local_coords = MapUtils.convert_to_local_coords(element["lat"], element["lon"])
					place.x = local_coords.x
					place.z = local_coords.y
					
					# Assign random mesh and sound
					if place_meshes.size() > 0:
						place.mesh = place_meshes[randi() % place_meshes.size()]
					if place_sounds.size() > 0:
						place.sound = place_sounds[randi() % place_sounds.size()]
					
					place_scenes.append(place)
					print("Added place with tags:", place.tags)  # Debug print

func _ready():
	load_places_from_json()
	print("Generating", place_scenes.size(), "places...")

	# Create command label
	command_label = Label.new()
	command_label.position = Vector2(15, 300)  # Position below existing HUD
	command_label.visible = false
	$HUD.add_child(command_label)
	update_command_label()
	
	# Get reference to player node
	player = get_node("Player")

	for place_data in place_scenes:
		var scene = load("res://scenes/Place.tscn")
		var place_instance = scene.instantiate()
		place_instance.set_place_data(place_data)
		
		place_instance.position = Vector3(
			place_data.x,
			0,
			place_data.z
		)
		
		add_child(place_instance)
		print("Added place:", place_data.name, "at position:", place_instance.position)

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
