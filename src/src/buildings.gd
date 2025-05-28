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
	
	#test
	#create_extruded_polygon([
		#Vector2(10, 4),
		#Vector2(-10, 4),
		#Vector2(10, -4),
		#Vector2(-10, -4),
		#], 10)
	#

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
	
func draw_normals_as_lines(vertices: Array, normals: Array, length: float = 0.3) -> MeshInstance3D:
	var mesh := ImmediateMesh.new()
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.albedo_color = Color(1, 0, 1)

	mesh.surface_begin(Mesh.PRIMITIVE_LINES, mat)

	for i in range(vertices.size()):
		var v = vertices[i]
		var n = normals[i].normalized()
		mesh.surface_add_vertex(v)
		mesh.surface_add_vertex(v + n * length)

	mesh.surface_end()

	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	return mi
	

func _compare_angles_desc(a, b):
	return int(a["angle"] < b["angle"])  # returns -1 if a > b for descending
	
func sort_points_clockwise(points: Array) -> Array:
	if points.size() < 3:
		return points.duplicate()

	var center = Vector2()
	for p in points:
		center += p
	center /= points.size()

	# Create list of [point, angle]
	var point_angles = []
	for p in points:
		var angle = atan2(p.y - center.y, p.x - center.x)
		point_angles.append({ "point": p, "angle": angle })

	# Sort descending by angle (clockwise)
	point_angles.sort_custom(_compare_angles_desc)

	var sorted_points = []
	for item in point_angles:
		sorted_points.append(item["point"])

	return sorted_points

func create_extruded_polygon2(points: Array, height: float) -> MeshInstance3D:
	var my_debug_triangles: Array = []
#	points = sort_points_clockwise(points);
	var st = SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)

	var n = points.size()
	if n < 3:
		push_error("Polygon must have at least 3 points.")
		return null

	var top_points = []
	var bottom_points = []

	for p in points:
		top_points.append(Vector3(p.x, height, -p.y))
		bottom_points.append(Vector3(p.x, 1, -p.y))

	var center_2d = Vector2.ZERO
	for p in points:
		center_2d += p
	center_2d /= n
	render_vertex(center_2d)

	# --- Side walls ---
	for i in range(n):
		var a2d = points[i]
		var b2d = points[(i + 1) % n]

		var a = Vector3(a2d.x, 0,      -a2d.y)
		var b = Vector3(b2d.x, 0,      -b2d.y)
		var c = Vector3(b2d.x, height, -b2d.y)
		var d = Vector3(a2d.x, height, -a2d.y)

		# 1st triangle (a-b-d)
		st.add_vertex(a)
		st.add_vertex(b)
		st.add_vertex(d)
		my_debug_triangles.append([a, b, d])

		# 2nd triangle (b-c-d)
		st.add_vertex(b)
		st.add_vertex(c)
		st.add_vertex(d)
		my_debug_triangles.append([b, c, d])
	
	# --- Top face ---
	var top_center = Vector3.ZERO
	for p in top_points:
		top_center += p
	top_center /= n

	for i in range(n):
		var a = top_points[(i + 1) % n]
		var b = top_points[i]
		var c = top_center
		my_debug_triangles.append([a, b, c])

	# --- Bottom face ---
	var bottom_center = Vector3.ZERO
	for p in bottom_points:
		bottom_center += p
	bottom_center /= n

	for i in range(n):
		var a = bottom_center
		var b = bottom_points[(i + 1) % n]
		var c = bottom_points[i]

		st.add_vertex(a)
		st.add_vertex(b)

		st.add_vertex(c)  
		my_debug_triangles.append([c, b, a])
	
	st.index()
	st.generate_normals() 
	
	# Commit and return
	var mesh_instance = MeshInstance3D.new()
	var mesh = st.commit()
	mesh_instance.mesh = mesh

	# Draw triangle edges
	#var debug_edges = draw_debug_triangle_edges(my_debug_triangles)
	#add_child(debug_edges)

	# Draw vertex normals
	var arrays = mesh.surface_get_arrays(0)
	var verts = arrays[Mesh.ARRAY_VERTEX]
	var norms = arrays[Mesh.ARRAY_NORMAL]
	
	#var debug_normals = draw_normals_as_lines(verts, norms, 0.3)
	#add_child(debug_normals)

	return mesh_instance
	
	# Returns a positive value for CCW order, negative for CW, 0 for a line.
func _signed_area(points: Array) -> float:
	var a := 0.0
	for i in range(points.size()):
		var p  = points[i]
		var q  = points[(i + 1) % points.size()]
		a += p.x * q.y - q.x * p.y      # shoelace term
	return a * 0.5                     # sign == orientation
	
func ensure_clockwise(points: Array) -> Array:
	var result := points.duplicate()
	if _signed_area(result) > 0.0:     # CCW → flip to CW
		result.reverse()
	return result

func create_extruded_polygon(points: Array, height: float) -> MeshInstance3D:
	#points = sort_points_clockwise(points)  # ← keep this in real use!
	points = ensure_clockwise(points)   # <— ONE-LINE FIX

	if points.size() < 3:
		push_error("Polygon must have at least 3 points.")
		return null

	var st = SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)

	var n = points.size()
	var top_points    = []
	var bottom_points = []
	for p in points:
		top_points.append(   Vector3(p.x, height, -p.y))
		bottom_points.append(Vector3(p.x, 0,      -p.y))

	# ---------- side walls ----------
	for i in range(n):
		var a2d = points[i]
		var b2d = points[(i + 1) % n]

		var a = Vector3(a2d.x, 0,      -a2d.y)
		var b = Vector3(b2d.x, 0,      -b2d.y)
		var c = Vector3(b2d.x, height, -b2d.y)
		var d = Vector3(a2d.x, height, -a2d.y)

		# quad as two triangles (consistent clockwise order)
		st.add_vertex(a); st.add_vertex(b); st.add_vertex(d)
		st.add_vertex(b); st.add_vertex(c); st.add_vertex(d)

	# ---------- top face ----------
	var top_center = Vector3()
	for v in top_points: top_center += v
	top_center /= n                         # barycentre

	for i in range(n):
		var a = top_points[i]
		var b = top_points[(i + 1) % n]
		# clockwise from above:   center → a → b
		st.add_vertex(top_center)
		st.add_vertex(b)
		st.add_vertex(a)
		

	# ---------- bottom face ----------
	var bottom_center = Vector3()
	for v in bottom_points: bottom_center += v
	bottom_center /= n

	for i in range(n):
		var a = bottom_points[i]
		var b = bottom_points[(i + 1) % n]
		# reverse order so the normal points downward
		st.add_vertex(bottom_center)
		st.add_vertex(a)
		st.add_vertex(b)

	# ---------- normals ----------
	st.generate_normals()      # per-face normals (flat) because duplicates still exist
	# st.index()               # OPTIONAL: call *after* normals if you really need welding

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
	var elements = building_data.elements
	#var elements = [building_data.elements[0]]

	for element in elements:
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
			# Remove duplicate closing point if present
			if building_points.size() > 2 && building_points[0] == building_points[-1]:
				building_points = building_points.slice(0, building_points.size() - 1)
			# Create the extruded building
			var building = create_extruded_polygon(building_points, EXTRUDE_HEIGHT)
			#building.material_override = building_material
			
			# Add collision shape
			var collision_body = StaticBody3D.new()
			var collision_shape = CollisionShape3D.new()

			var shape = building.mesh.create_trimesh_shape()
			collision_shape.shape = shape

			collision_body.add_child(collision_shape)
			building.add_child(collision_body)
			
			# Add the building to the container
			buildings_container.add_child(building) 
