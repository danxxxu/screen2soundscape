@tool
extends Node3D

const TUBE_WIDTH = 1.0
const TUBE_HEIGHT = 1
const GRID_STEP = 10.0

@export var map_size: Vector3 = Vector3(200, 0, 200) # Define the map size
@export var center_lat: float = 52.0785266  # Center latitude (Dudok cafe as center point)
@export var center_lon: float = 4.3117263   # Center longitude
@export var scale_factor: float = 1000.0    # Scale factor to convert degrees to local units

var way_data = {}
var node_data = {}  # Store node coordinates
var tube_material: StandardMaterial3D
var grid_material: StandardMaterial3D

func _ready():
	if Engine.is_editor_hint():
		# Clear existing children when in editor
		for child in get_children():
			child.queue_free()
	
	load_ways()
	create_materials()
	create_grid()
	create_tubes()

func _process(_delta):
	if Engine.is_editor_hint():
		# Update when properties change in editor
		if Input.is_action_just_pressed("ui_accept"):  # Space bar
			_ready()

func load_ways():
	var file = FileAccess.open("res://src/models/ways.json", FileAccess.READ)
	if file:
		var json = JSON.new()
		var error = json.parse(file.get_as_text())
		if error == OK:
			way_data = json.get_data()
			# First, collect all node coordinates
			for element in way_data.elements:
				if element.type == "node":
					node_data[element.id] = {
						"lat": element.lat,
						"lon": element.lon
					}
		else:
			print("JSON Parse Error: ", json.get_error_message())
	else:
		print("Failed to open ways.json")

# Convert lat/lon to local coordinates (same as in scene.gd)
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

func create_materials():
	# Tube material
	tube_material = StandardMaterial3D.new()
	tube_material.albedo_color = Color(0.2, 0.6, 1.0, 0.8)
	tube_material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	tube_material.vertex_color_use_as_albedo = true
	
	# Grid material
	grid_material = StandardMaterial3D.new()
	grid_material.albedo_color = Color(0.5, 0.5, 0.5, 0.3)
	grid_material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA

func create_grid():
	var grid = MeshInstance3D.new()
	var mesh = PlaneMesh.new()
	
	# Set grid size based on map_size
	mesh.size = Vector2(map_size.x, map_size.z)
	mesh.subdivide_width = map_size.x / GRID_STEP
	mesh.subdivide_depth = map_size.z / GRID_STEP
	
	grid.mesh = mesh
	grid.material_override = grid_material
	
	# Position grid slightly above floor to prevent z-fighting
	grid.position = Vector3(0, 0.01, 0)
	
	add_child(grid)
	
	# Add coordinate labels
	create_coordinate_labels()

func format_coordinate(value: float, is_lat: bool) -> String:
	var direction = "N" if is_lat else "E"
	if value < 0:
		direction = "S" if is_lat else "W"
		value = abs(value)
	
	# Format to 6 decimal places for precision
	return "%.6f° %s" % [value, direction]

func create_coordinate_labels():
	var label_container = Node3D.new()
	label_container.name = "CoordinateLabels"
	add_child(label_container)
	
	# Calculate grid bounds based on map_size
	var half_width = map_size.x / 2
	var half_depth = map_size.z / 2
	
	# Create labels for all grid intersections
	for x in range(-int(half_width), int(half_width) + 1, int(GRID_STEP)):
		for z in range(-int(half_depth), int(half_depth) + 1, int(GRID_STEP)):
			var lat = center_lat + (z / scale_factor)
			var lon = center_lon + (x / scale_factor)
			
			var lat_str = format_coordinate(lat, true)
			var lon_str = format_coordinate(lon, false)
			var label_text = "(%s, %s)" % [lat_str, lon_str]
			
			create_label(Vector3(x, 0.1, z), label_text, label_container)

func create_label(position: Vector3, text: String, parent: Node3D):
	var label = Label3D.new()
	label.text = text
	label.font_size = 12  # Smaller font size for grid points
	label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	label.position = position
	parent.add_child(label)

func create_tubes():
	if not way_data.has("elements"):
		return
		
	for element in way_data.elements:
		if element.type == "way" and element.has("nodes"):
			create_tube_for_way(element)

func create_tube_for_way(way):
	var points = []
	for node_id in way.nodes:
		if node_data.has(node_id):
			var node = node_data[node_id]
			var local_coords = convert_to_local_coords(node.lat, node.lon)
			points.append(Vector3(local_coords.x, 0, local_coords.y))
	
	if points.size() < 2:
		return
		
	create_tube_segments(points)

func create_tube_segments(points: Array):
	for i in range(points.size() - 1):
		var start = points[i]
		var end = points[i + 1]
		
		# Calculate the direction and length of the segment
		var direction = (end - start).normalized()
		var length = start.distance_to(end)
		
		# Create a box for this segment
		var box = MeshInstance3D.new()
		var mesh = BoxMesh.new()
		
		# Set box properties
		mesh.size = Vector3(TUBE_WIDTH, TUBE_HEIGHT, length)
		
		box.mesh = mesh
		box.material_override = tube_material
		
		# Position and rotate the box
		var mid_point = (start + end) / 2
		box.position = mid_point
		
		# Calculate rotation to align box with direction
		# First, get the forward direction (Z axis)
		var forward = direction
		# Get the up direction (Y axis)
		var up = Vector3.UP
		# Calculate the right direction (X axis) using cross product
		var right = forward.cross(up).normalized()
		# Recalculate up to ensure orthogonality
		up = right.cross(forward).normalized()
		
		# Create the rotation basis
		var basis = Basis(right, up, -forward)
		box.transform.basis = basis
		
		add_child(box) 
