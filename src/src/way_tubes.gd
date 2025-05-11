@tool
extends Node3D

const TUBE_WIDTH = 1.0
const TUBE_HEIGHT = 1

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
	mesh.size = Vector2(MapUtils.MAP_SIZE.x, MapUtils.MAP_SIZE.z)
	mesh.subdivide_width = MapUtils.MAP_SIZE.x / MapUtils.GRID_STEP
	mesh.subdivide_depth = MapUtils.MAP_SIZE.z / MapUtils.GRID_STEP
	
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
	var half_width = MapUtils.MAP_SIZE.x / 2
	var half_depth = MapUtils.MAP_SIZE.z / 2
	
	# Create labels for all grid intersections
	for x in range(-int(half_width), int(half_width) + 1, int(MapUtils.GRID_STEP * 2)):  # Double the step for labels
		for z in range(-int(half_depth), int(half_depth) + 1, int(MapUtils.GRID_STEP * 2)):
			# Flip Z coordinate to match the coordinate system
			var geo_coords = MapUtils.convert_to_geo_coords(x, -z)
			var lat_str = format_coordinate(geo_coords.x, true)
			var lon_str = format_coordinate(geo_coords.y, false)
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
			var local_coords = MapUtils.convert_to_local_coords(node.lat, node.lon)
			# Flip Z coordinate to match the coordinate system
			points.append(Vector3(local_coords.x, 0, -local_coords.y))
	
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
