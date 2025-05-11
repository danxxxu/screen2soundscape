@tool
extends Node3D

const EXTRUDE_HEIGHT = 10.0  # Height of the extruded path
var building_data = {}
var node_data = {}  # Store node coordinates
var building_material: StandardMaterial3D

func _ready():
	if Engine.is_editor_hint():
		# Clear existing children when in editor
		for child in get_children():
			child.queue_free()
	
	load_buildings()
	create_materials()
	create_buildings()

func _process(_delta):
	if Engine.is_editor_hint():
		# Update when properties change in editor
		if Input.is_action_just_pressed("ui_accept"):  # Space bar
			_ready()

func load_buildings():
	var file = FileAccess.open("res://src/models/buildings.json", FileAccess.READ)
	if file:
		var json = JSON.new()
		var error = json.parse(file.get_as_text())
		if error == OK:
			building_data = json.get_data()
			# First, collect all node coordinates
			for element in building_data.elements:
				if element.type == "node":
					node_data[element.id] = {
						"lat": element.lat,
						"lon": element.lon
					}
		else:
			print("JSON Parse Error: ", json.get_error_message())
	else:
		print("Failed to open buildings.json")

func create_materials():
	# Building material
	building_material = StandardMaterial3D.new()
	building_material.albedo_color = Color(0.7, 0.7, 0.7, 1.0)  # Light gray color
	building_material.roughness = 0.8
	building_material.metallic = 0.2
	building_material.transparency = BaseMaterial3D.TRANSPARENCY_DISABLED

func create_extruded_polygon(points: Array, height: float) -> MeshInstance3D:
	var st = SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	
	# Create top and bottom points
	var n = points.size()
	var top_points = []
	var bottom_points = []
	
	for p in points:
		top_points.append(Vector3(p.x, height, p.y))
		bottom_points.append(Vector3(p.x, 0, p.y))
	
	# Create side walls with outward-facing normals
	for i in range(n):
		var a = bottom_points[i]
		var b = bottom_points[(i + 1) % n]
		var c = top_points[(i + 1) % n]
		var d = top_points[i]
		
		# Calculate normal for this wall (pointing outward)
		var edge = b - a
		var up = Vector3.UP
		var normal = edge.cross(up).normalized()
		st.set_normal(normal)
		
		# First triangle (clockwise winding for outward normal)
		st.add_vertex(a)
		st.add_vertex(d)
		st.add_vertex(b)
		
		# Second triangle (clockwise winding for outward normal)
		st.add_vertex(b)
		st.add_vertex(d)
		st.add_vertex(c)
	
	# Create top face (triangulate from center with outward normals)
	var center = Vector3.ZERO
	for p in top_points:
		center += p
	center /= n
	
	st.set_normal(Vector3.UP)  # Top face normal points up
	for i in range(n):
		# Clockwise winding for outward normal
		st.add_vertex(top_points[i])
		st.add_vertex(center)
		st.add_vertex(top_points[(i + 1) % n])
	
	# Create bottom face (triangulate from center with outward normals)
	st.set_normal(Vector3.DOWN)  # Bottom face normal points down
	for i in range(n):
		# Counter-clockwise winding for outward normal
		st.add_vertex(bottom_points[i])
		st.add_vertex(bottom_points[(i + 1) % n])
		st.add_vertex(center)
	
	var mesh_instance = MeshInstance3D.new()
	mesh_instance.mesh = st.commit()
	return mesh_instance

func create_buildings():
	if not building_data.has("elements"):
		return
	
	# Create buildings container
	var buildings_container = Node3D.new()
	buildings_container.name = "Buildings"
	add_child(buildings_container)
	
	# Process each way that represents a building
	for element in building_data.elements:
		if element.type == "way" and element.has("tags") and element.tags.has("building"):
			# Get all nodes for this building in order
			var building_points = []
			
			# First pass: collect points
			for node_id in element.nodes:
				if node_data.has(node_id):
					var node = node_data[node_id]
					var local_coords = MapUtils.convert_to_local_coords(node.lat, node.lon)
					building_points.append(Vector2(local_coords.x, local_coords.y))
			
			if building_points.size() < 3:
				continue  # Skip if not enough points to form a polygon
			
			# Create the extruded building
			var building = create_extruded_polygon(building_points, EXTRUDE_HEIGHT)
			building.material_override = building_material
			
			# Add collision shape
			var collision_body = StaticBody3D.new()
			var collision_shape = CollisionShape3D.new()
			var shape = ConcavePolygonShape3D.new()
			
			# Create collision shape from the mesh
			shape.set_faces(building.mesh.surface_get_arrays(0)[Mesh.ARRAY_VERTEX])
			collision_shape.shape = shape
			collision_body.add_child(collision_shape)
			building.add_child(collision_body)
			
			# Add the building to the container
			buildings_container.add_child(building) 
