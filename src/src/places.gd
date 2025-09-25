#@tool
extends Node3D

const PlaceData = preload("res://src/models/Place.gd")
const MapUtils = preload("res://src/map_utils.gd")

var PlacesDictByLocation = {}
var place_data_models: Array[PlaceData] = []

func _ready():
	if Engine.is_editor_hint():
		# Clear existing children when in editor
		for child in get_children():
			child.queue_free()
	
	# Wait for buildings to be ready first
	await get_tree().process_frame
	await get_tree().process_frame
	
	# Wait for buildings to be fully loaded
	var buildings_node = get_parent().get_node("Buildings")
	if buildings_node:
		var max_wait = 100
		var wait_count = 0
		while buildings_node.get_child_count() == 0 and wait_count < max_wait:
			await get_tree().process_frame
			wait_count += 1
		print("🏗️ Buildings loaded, now loading places...")
	

func _process(_delta):
	if Engine.is_editor_hint():
		# Update when properties change in editor
		if Input.is_action_just_pressed("ui_accept"):  # Space bar
			_ready()

# Method to query places for a specific area using real world coordinates
func query_places_with_bounds(lat1: float, lon1: float, lat2: float, lon2: float):
	"""
	Public method to query places from Overpass API with lat/lon bounding box
	lat1, lon1: First corner of bounding box
	lat2, lon2: Second corner of bounding box
	"""
	
	await load_places_from_overpass(lat1, lon1, lat2, lon2)
	create_place_instances()  # This will reconnect all signals properly

func load_places_from_overpass(lat1: float, lon1: float, lat2: float, lon2: float):	
	var overpass_api = OverpassAPI.new()
	add_child(overpass_api)
	
	var result = await overpass_api.query_places(lat1, lon1, lat2, lon2)
	var places_data = result.get("places_data", {})
	
	overpass_api.queue_free()
	
	if places_data.has("elements"):
		for element in places_data["elements"]:
			if element["type"] == "node" and element.has("tags"):
				var place = PlaceData.new()

				# Store all tags
				place.tags = element["tags"].duplicate()

				# Get name and type
				place.name = element["tags"].get("name", "Unnamed Place")
				var type = "unknown"
				var category = "unknown"
				
				for tag in OverpassAPI.TAGS:
					var key = tag[0]
					# Check if this element has the tag key
					if element["tags"].has(key):
						type = element["tags"][key]
						category = key
						break  # stop at the first match (like elif chain)

				place.type = type
				place.category = category

				# Convert coordinates
				var local_coords = MapUtils.convert_to_local_coords(element["lat"], element["lon"])
			
				# Adjust position to be on building perimeter if needed
				var adjusted_coords = adjust_place_position(Vector2(local_coords.x, local_coords.y))
				place.x = adjusted_coords.x
				place.z = -adjusted_coords.y
				
				var key = str(int(place.x)) + ' ' + str(int(place.z))
				if not key in PlacesDictByLocation:
					place_data_models.append(place)
					PlacesDictByLocation[key] = true

func adjust_place_position(place_pos: Vector2) -> Vector2:
	var buildings_node = get_parent().get_node("Buildings")
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

func create_place_instances():
	print("Creating ", place_data_models.size(), " place instances...")
	for place_data in place_data_models:
		var scene = load("res://scenes/Place.tscn")
		var place_instance = scene.instantiate()
		place_instance.set_place_data(place_data)
		place_instance.position = Vector3(place_data.x, 0, place_data.z)
		
		place_instance.player_entered.connect(_on_place_entered)
		place_instance.player_exited.connect(_on_place_exited)
		add_child(place_instance)
	place_data_models.clear()

func _on_place_entered(place: Place):
	var scene = get_parent()
	if scene and scene.has_method("_on_place_entered"):
		scene._on_place_entered(place)

func _on_place_exited(place: Place):
	var scene = get_parent()
	if scene and scene.has_method("_on_place_exited"):
		scene._on_place_exited(place)
