extends Node3D
"res://rocky_terrain_02_diff_4k.jpg"
const PlaceData = preload("res://src/models/Place.gd")
@export var map_size: Vector3 = Vector3(1000, 0, 1000) # Map size in local units
@export var place_meshes: Array[PackedScene] # Assign random meshes in the editor
@export var place_sounds: Array[AudioStream] # Assign random sounds in the editor

var place_scenes: Array[PlaceData] # Holds dynamically generated places

var command_mode: bool = false
var current_command: String = ""
var command_label: Label
var current_place: Node3D = null  # Store the current place player is near
var player: Node3D = null  # Reference to the player node

func adjust_place_position(place_pos: Vector2) -> Vector2:
	var buildings_node = get_node("Buildings")
	if not buildings_node:
		return place_pos

	var min_dist = INF
	var best_adjustment = place_pos

	# Get all building meshes
	for building in buildings_node.get_children():
		if building is MeshInstance3D:
			var mesh = building.mesh
			if mesh:
				var arrays = mesh.surface_get_arrays(0)
				var vertices = arrays[Mesh.ARRAY_VERTEX]

				# Convert 3D vertices to 2D points
				var building_points = []
				for v in vertices:
					building_points.append(Vector2(v.x, -v.z))  # Note: z is negated to match coordinate system

				if building_points.size() < 3:
					continue

				# Find nearest point on perimeter
				var nearest = find_nearest_point_on_perimeter(place_pos, building_points)
				if nearest.distance < min_dist:
					min_dist = nearest.distance
					best_adjustment = nearest.point + nearest.normal * 1.0  # 1.0 units outward

	return best_adjustment

func find_nearest_point_on_perimeter(point: Vector2, building_points: Array) -> Dictionary:
	var min_dist = INF
	var nearest_point = Vector2.ZERO
	var normal = Vector2.ZERO

	# For each edge of the building
	for i in range(building_points.size()):
		var p1 = building_points[i]
		var p2 = building_points[(i + 1) % building_points.size()]

		# Calculate the nearest point on this edge
		var edge = p2 - p1
		var edge_length = edge.length()
		var edge_dir = edge / edge_length

		# Vector from p1 to the point
		var to_point = point - p1

		# Project the point onto the edge
		var projection = to_point.dot(edge_dir)
		projection = clamp(projection, 0, edge_length)

		# Calculate the nearest point on the edge
		var nearest = p1 + edge_dir * projection

		# Calculate distance to this point
		var dist = point.distance_to(nearest)

		if dist < min_dist:
			min_dist = dist
			nearest_point = nearest

			# Calculate normal (perpendicular to edge, pointing outward)
			var center = Vector2.ZERO
			for p in building_points:
				center += p
			center /= building_points.size()

			# Calculate normal (perpendicular to edge)
			normal = Vector2(-edge_dir.y, edge_dir.x)

			# Make sure normal points outward
			if normal.dot(nearest - center) < 0:
				normal = -normal

	return {
		"point": nearest_point,
		"normal": normal,
		"distance": min_dist
	}

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

					# Determine type from tags
					var type = "unknown"
					var category = "unknown"
					if element["tags"].has("amenity"):
						type = element["tags"]["amenity"]
						category = "amenity"
					elif element["tags"].has("shop"):
						type = element["tags"]["shop"]
						category = "shop"
					elif element["tags"].has("tourism"):
						type = element["tags"]["tourism"]
						category = "tourism"
					elif element["tags"].has("leisure"):
						type = element["tags"]["leisure"]
						category = "leisure"
					elif element["tags"].has("railway"):
						type = element["tags"]["railway"]
						category = "railway"
					place.type = type
					place.category = category

					# Convert coordinates
					var local_coords = MapUtils.convert_to_local_coords(element["lat"], element["lon"])

					# Adjust position to be on building perimeter if needed
					var adjusted_coords = adjust_place_position(Vector2(local_coords.x, local_coords.y))
					place.x = adjusted_coords.x
					place.z = -adjusted_coords.y

					# Assign random mesh
					if place_meshes.size() > 0:
						place.mesh = place_meshes[randi() % place_meshes.size()]
					if place_sounds.size() > 0:
						place.sound = place_sounds[randi() % place_sounds.size()]

					place_scenes.append(place)

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
