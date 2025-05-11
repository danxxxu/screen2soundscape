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
	building_material.albedo_color = Color(0.7, 0.7, 0.7, 1)  # Light gray color
	building_material.roughness = 0.8
	building_material.metallic = 0.2
	building_material.cull_mode = BaseMaterial3D.CULL_DISABLED

	building_material.transparency = BaseMaterial3D.TRANSPARENCY_DISABLED

func render_vertex(point):
	var debug_material := StandardMaterial3D.new()
	debug_material.albedo_color = Color.RED

	var sphere := MeshInstance3D.new()
	var mesh := SphereMesh.new()
	mesh.radius = 0.1
	mesh.height = 0.1
	mesh.radial_segments = 6
	mesh.rings = 4
	mesh.material = debug_material

	sphere.mesh = mesh
	sphere.transform.origin = Vector3(point.x, 1, -point.y)
	add_child(sphere)
	
func draw_debug_triangle_edges(triangles: Array) -> MeshInstance3D:
	var im_mesh := ImmediateMesh.new()
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.albedo_color = Color(0, 1, 0)  # Green
	mat.line_width = 2.0

	im_mesh.surface_begin(Mesh.PRIMITIVE_LINES, mat)

	for tri in triangles:
		var a = tri[0]
		var b = tri[1]
		var c = tri[2]
		im_mesh.surface_add_vertex(a)
		im_mesh.surface_add_vertex(b)

		im_mesh.surface_add_vertex(b)
		im_mesh.surface_add_vertex(c)

		im_mesh.surface_add_vertex(c)
		im_mesh.surface_add_vertex(a)

	im_mesh.surface_end()

	var mesh_instance := MeshInstance3D.new()
	mesh_instance.mesh = im_mesh
	return mesh_instance
func create_extruded_polygon(points: Array, height: float) -> MeshInstance3D:
	var my_debug_triangles: Array = []
	var st = SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)

	var n = points.size()
	if n < 3:
		push_error("Polygon must have at least 3 points.")
		return null

	var top_points = []
	var bottom_points = []

	# Convert 2D points to 3D top and bottom
	for p in points:
		top_points.append(Vector3(p.x, height, -p.y))
		bottom_points.append(Vector3(p.x, 0, -p.y))

	#for point in top_points + bottom_points:
		#render_vertex(point)

	# Compute 2D center for normal projection
	var center_2d = Vector2.ZERO
	for p in points:
		center_2d += p
	center_2d /= n
	render_vertex(center_2d)
	
	# --- Side walls ---
	for i in range(n):
		var a2d = points[i]
		var b2d = points[(i + 1) % n]

		var a = Vector3(a2d.x, 0, -a2d.y)
		var b = Vector3(b2d.x, 0, -b2d.y)
		var c = Vector3(b2d.x, height, -b2d.y)
		var d = Vector3(a2d.x, height, -a2d.y)

		var mid = (a2d + b2d) * 0.5
		var to_face = (mid - center_2d).normalized()
		var normal = Vector3(to_face.x, 0, -to_face.y)

		# Triangle 1
		st.set_normal(normal); st.add_vertex(a)
		st.set_normal(normal); st.add_vertex(b)
		st.set_normal(normal); st.add_vertex(d)

		# Triangle 2
		st.set_normal(normal); st.add_vertex(b)
		st.set_normal(normal); st.add_vertex(c)
		st.set_normal(normal); st.add_vertex(d)
		
		my_debug_triangles.append([a, b, c])

	# --- Top face (triangulated fan) ---
	var top_center = Vector3.ZERO
	for p in top_points:
		top_center += p
	top_center /= n

	for i in range(n):
		
		st.set_normal(Vector3.UP); st.add_vertex(top_points[(i + 1) % n])
		st.set_normal(Vector3.UP); st.add_vertex(top_points[i])
		
		st.set_normal(Vector3.UP); st.add_vertex(top_center)
		

	# --- Bottom face (triangulated fan) ---
	var bottom_center = Vector3.ZERO
	for p in bottom_points:
		bottom_center += p
	bottom_center /= n

	for i in range(n):
		st.set_normal(Vector3.DOWN); st.add_vertex(bottom_center)
		st.set_normal(Vector3.DOWN); st.add_vertex(bottom_points[(i + 1) % n])
		st.set_normal(Vector3.DOWN); st.add_vertex(bottom_points[i])

	# Commit and return
	var mesh_instance = MeshInstance3D.new()
	mesh_instance.mesh = st.commit()
	var debug_mesh = draw_debug_triangle_edges(my_debug_triangles)
	add_child(debug_mesh)
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

			var shape = building.mesh.create_trimesh_shape()
			collision_shape.shape = shape

			collision_body.add_child(collision_shape)
			building.add_child(collision_body)
			
			# Add the building to the container
			buildings_container.add_child(building) 
