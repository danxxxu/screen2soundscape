@tool
extends Node3D

const MapUtils = preload("res://src/map_utils.gd")

var polygon_data = {}
var node_data = {}
var landuse_polygons: Array = []

func _ready():
	if Engine.is_editor_hint():
		# Clear existing children when in editor
		for child in get_children():
			child.queue_free()
	
	# Wait for buildings to be ready first
	await get_tree().process_frame
	await get_tree().process_frame
	
	print("🌿 Polygons system initialized")

func _process(_delta):
	if Engine.is_editor_hint():
		# Update when properties change in editor
		if Input.is_action_just_pressed("ui_accept"):  # Space bar
			_ready()

# Method to query polygons for a specific area using real world coordinates
func query_polygons_with_bounds(lat1: float, lon1: float, lat2: float, lon2: float):
	"""
	Public method to query landuse polygons from Overpass API with lat/lon bounding box
	lat1, lon1: First corner of bounding box
	lat2, lon2: Second corner of bounding box
	"""
	
	await load_polygons_from_overpass(lat1, lon1, lat2, lon2)
	create_polygon_instances()

func load_polygons_from_overpass(lat1: float, lon1: float, lat2: float, lon2: float):	
	var overpass_api = OverpassAPI.new()
	add_child(overpass_api)
	
	var result = await overpass_api.query_landuse_polygons(lat1, lon1, lat2, lon2)
	polygon_data = result.get("polygon_data", {})
	node_data = result.get("node_data", {})
	
	overpass_api.queue_free()
	
	if polygon_data.has("elements"):
		for element in polygon_data["elements"]:
			if element["type"] == "way" and element.has("tags"):
				var landuse_type = element["tags"].get("landuse", "unknown")
				
				# Only process grass and meadow polygons
				if landuse_type in ["grass", "meadow"]:
					var polygon_points = []
					
					# Get all nodes for this polygon in order
					for node_id in element.nodes:
						if node_data.has(node_id):
							var node = node_data[node_id]
							var local_coords = MapUtils.convert_to_local_coords(node.lat, node.lon)
							polygon_points.append(Vector2(local_coords.x, local_coords.y))
					
					if polygon_points.size() >= 3:
						# Remove duplicate closing point if present
						if polygon_points.size() > 2 and polygon_points[0] == polygon_points[-1]:
							polygon_points = polygon_points.slice(0, polygon_points.size() - 1)
						
						var polygon_info = {
							"type": landuse_type,
							"points": polygon_points,
							"tags": element["tags"]
						}
						landuse_polygons.append(polygon_info)

func create_polygon_instances():
	print("🌿 Creating ", landuse_polygons.size(), " polygon instances...")
	for i in range(landuse_polygons.size()):
		var polygon_info = landuse_polygons[i]
		print("  Polygon ", i, ": type=", polygon_info.type, ", points=", polygon_info.points.size())
	# For now, we just store the polygon data for querying
	# In the future, we could create visual representations if needed

# Method to query polygons at a specific point
func query_polygons_at_point(point: Vector2) -> Array:
	"""
	Query all polygons that contain the given point
	Returns array of polygon info dictionaries
	"""
	var containing_polygons = []
	
	for polygon_info in landuse_polygons:
		if InPolygonChecker.is_point_in_polygon(point, polygon_info.points):
			containing_polygons.append(polygon_info)
	
	return containing_polygons

# Method to get all polygons (for compatibility with existing code)
func get_all_polygons() -> Array:
	"""
	Get all loaded polygon points for compatibility with existing code
	Returns array of polygon point arrays
	"""
	var all_polygon_points = []
	for polygon_info in landuse_polygons:
		all_polygon_points.append(polygon_info.points)
	return all_polygon_points
