@tool
extends Node3D

const EXTRUDE_HEIGHT = 10.0  # Height of the extruded path
var building_data = {}
var node_data = {} 
var building_material: StandardMaterial3D
var emitter_dict := {}  # Dictionary[Vector3i, Array[AudioStreamPlayer3D]]
var CELL_SIZE := 15.0    # same as your check radius

func _has_nearby_emitter(pos: Vector3, stream: AudioStream, radius: float = 5.0) -> bool:
	var cell := _cell_key(pos)
	var r := int(ceil(radius / CELL_SIZE))

	for x in range(cell.x - r, cell.x + r + 1):
		for y in range(cell.y - r, cell.y + r + 1):
			for z in range(cell.z - r, cell.z + r + 1):
				var key := Vector3i(x, y, z)
				if not emitter_dict.has(key):
					continue
				for node in emitter_dict[key]:
					if node and node.stream:
						var same = node.stream == stream \
							or (stream.resource_path != "" and node.stream.resource_path == stream.resource_path)
						if same and node.global_position.distance_to(pos) <= radius:
							return true
	return false
	
func _cell_key(pos: Vector3) -> Vector3i:
	return Vector3i(
		int(floor(pos.x / CELL_SIZE)),
		int(floor(pos.y / CELL_SIZE)),
		int(floor(pos.z / CELL_SIZE))
	)
func _ready():
	if Engine.is_editor_hint():
		# Clear existing children when in editor
		for child in get_children():
			child.queue_free()
	
func _process(_delta):
	if Engine.is_editor_hint():
		# Update when properties change in editor
		if Input.is_action_just_pressed("ui_accept"):  # Space bar
			_ready()

# Method to query buildings for a specific area using real world coordinates
func query_buildings_with_bounds(lat1: float, lon1: float, lat2: float, lon2: float):
	"""
	Public method to query buildings from Overpass API with lat/lon bounding box
	lat1, lon1: First corner of bounding box
	lat2, lon2: Second corner of bounding box
	"""
	
	await query_buildings_from_overpass(lat1, lon1, lat2, lon2)
	create_materials()
	create_buildings()


func query_buildings_from_overpass(lat1: float, lon1: float, lat2: float, lon2: float):
	var overpass_api = OverpassAPI.new()
	add_child(overpass_api)
	
	# Query the API
	var result = await overpass_api.query_buildings(lat1, lon1, lat2, lon2)
	
	# Extract results
	building_data = result.get("building_data", {})
	node_data = result.get("node_data", {})
	
	# Clean up
	overpass_api.queue_free()
	
	if building_data.is_empty() or not building_data.has("elements"):
		print("❌ No building data received from Overpass API")
	else:
		print("✅ Successfully loaded building data from Overpass API")

func create_materials():
	# Building material
	building_material = StandardMaterial3D.new()
	building_material.albedo_color = Color(0.7, 0.7, 0.7, 0.5)  # Light gray color with 50% transparency
	building_material.roughness = 0.8
	building_material.metallic = 0.2
	building_material.cull_mode = BaseMaterial3D.CULL_DISABLED
	building_material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA

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
	points = ensure_clockwise(points)  

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

	var mesh_instance = MeshInstance3D.new()
	mesh_instance.mesh = st.commit()
	return mesh_instance

func add_building_proximity(building_points: Array, building: MeshInstance3D) -> Area3D:
	# Add proximity detection area (10 units larger than the building)
	var proximity_area = Area3D.new()
	var proximity_shape = CollisionShape3D.new()
	
	# Create a convex shape from the building points with padding
	var padded_points = []
	var center = Vector2()
	for p in building_points:
		center += p
	center /= building_points.size()
	
	# Expand each point outward from center by 10 units
	for p in building_points:
		var direction = (p - center).normalized()
		var padded_point = p + direction * 10.0  # 10 unit padding
		padded_points.append(Vector2(padded_point.x, padded_point.y))
	
	# Create the proximity detection shape
	var proximity_building = create_extruded_polygon(padded_points, EXTRUDE_HEIGHT + 2.0)
	var proximity_collision_shape = proximity_building.mesh.create_trimesh_shape()
	proximity_shape.shape = proximity_collision_shape
	
	proximity_area.add_child(proximity_shape)
	building.add_child(proximity_area)
	
	# Add the proximity area to the building_proximity group
	proximity_area.add_to_group("building_proximity")
	
	return proximity_area

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
			var outside_of_map = false;
			# First pass: collect points
			for node_id in element.nodes:
				if node_data.has(node_id):
					var node = node_data[node_id]
					var local_coords = MapUtils.convert_to_local_coords(node.lat, node.lon)
					if local_coords.x >=500 or local_coords.x<=-500 or local_coords.y >= 500 or local_coords.y <=-500 :
						outside_of_map = true
					building_points.append(Vector2(local_coords.x, local_coords.y))
			
			if outside_of_map:
				continue		
			
			if building_points.size() < 3:
				continue  # Skip if not enough points to form a polygon
			# Remove duplicate closing point if present
			if building_points.size() > 2 && building_points[0] == building_points[-1]:
				building_points = building_points.slice(0, building_points.size() - 1)
			# Create the extruded building
			var building = create_extruded_polygon(building_points, EXTRUDE_HEIGHT)
			building.material_override = building_material
					
			var rng := RandomNumberGenerator.new()
			rng.randomize()
			var numb = rng.randi_range(1,7)
			var loop = load("res://assets/audio/buildings/building " + str(numb) + ".mp3")

			# Add collision shape for physics
			var collision_body = StaticBody3D.new()
			var collision_shape = CollisionShape3D.new()

			var shape = building.mesh.create_trimesh_shape()
			collision_shape.shape = shape

			collision_body.add_child(collision_shape)
			building.add_child(collision_body)
			
			# Add the building to the buildings group
			collision_body.add_to_group("buildings")
			collision_body.add_to_group("occludable_audio")

			# Add proximity detection using the extracted method
			add_building_proximity(building_points, building)

			# Add the building to the container
			buildings_container.add_child(building) 
			add_wall_sound_emitters(
				building,
				building_points,
				5,
				loop,
				25.0,
				5 * 0.5,
				0.25,
				-8.0,
				15.0,
				true
			)

func add_wall_sound_emitters(
	parent_node: Node3D,
	points: Array,                      # Array[Vector2] in local XZ (y -> Z)
	height: float,
	stream: AudioStream,
	spacing: float = 10.0,               # meters between emitters
	emitter_height: float = 0.5,        # from the base; try height*0.5 for mid-wall
	outward_offset: float = 0.25,       # push emitters slightly outside
	volume_db: float = -8.0,
	max_distance: float = 12.0,
	randomize_start: bool = true
) -> void:
	if points.size() < 2 or stream == null:
		return

	# Determine winding to know which side is "outside".
	# Signed area > 0 => CCW; < 0 => CW (we ensured CW above, but double-check).
	var area := 0.0
	for i in range(points.size()):
		var a: Vector2 = points[i]
		var b: Vector2 = points[(i + 1) % points.size()]
		area += a.x * b.y - b.x * a.y
	var is_clockwise := area < 0.0

	var rng := RandomNumberGenerator.new()
	rng.randomize()

	for i in range(points.size()):
		var a2: Vector2 = points[i]
		var b2: Vector2 = points[(i + 1) % points.size()]
		var seg: Vector2 = b2 - a2
		var seg_len := seg.length()
		if seg_len < 0.001:
			continue
		var dir: Vector2 = seg / seg_len

		# Left normal = (-dy, dx). For CW polygon, outside is "left".
		var left_normal := Vector2(-dir.y, dir.x)
		var outward := left_normal if is_clockwise else -left_normal

		# Place emitters from 0..seg_len with a step of `spacing`, include end.
		var steps := int(floor(seg_len / spacing))
		for s in range(steps + 1):
			var dist = min(float(s) * spacing, seg_len)
			var p2 = a2 + dir * dist + outward * outward_offset
			var pos3 := Vector3(p2.x, clamp(emitter_height, 0.0, height), -p2.y)
			var key := _cell_key(parent_node.to_global(pos3))
			if not emitter_dict.has(key):
				emitter_dict[key] = []
				var sphere := MeshInstance3D.new()
				var sm := SphereMesh.new()
				sm.radius = 0.2
				sm.height = 0.2
				sphere.mesh = sm
				# Make it blue
				var mat := StandardMaterial3D.new()
				mat.albedo_color = Color(0.2, 0.5, 1.0)  # light blue
				sphere.material_override = mat
				sphere.transform = Transform3D(Basis(), pos3)
				parent_node.add_child(sphere)
				var player := AudioStreamPlayer3D.new()
				
				player.stream = stream
				player.stream.loop = true
				player.volume_db = volume_db
				player.max_distance = max_distance
				player.attenuation_model = AudioStreamPlayer3D.ATTENUATION_INVERSE_DISTANCE
				player.doppler_tracking = AudioStreamPlayer3D.DOPPLER_TRACKING_DISABLED
				player.transform = Transform3D(Basis(), pos3)
				parent_node.add_child(player)

				# Choose start offset (if any)
				var start_offset := 0.0
				if randomize_start:
					var dur := 0.0
					if stream is AudioStreamWAV:
						dur = (stream as AudioStreamWAV).get_length()
					elif stream is AudioStreamOggVorbis:
						dur = (stream as AudioStreamOggVorbis).get_length()
					elif stream is AudioStreamMP3:
						dur = (stream as AudioStreamMP3).get_length()
					if dur > 0.1:
						start_offset = rng.randf() * dur

				player.call_deferred("play", start_offset)
				emitter_dict[key].append(player)
			
