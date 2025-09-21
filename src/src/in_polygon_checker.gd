extends Node

class_name InPolygonChecker

# Reference to the polygons system
var polygons_system: Node3D

func _ready():
	# Find the polygons system in the scene
	polygons_system = get_node("/root/Scene/Polygons")
	if not polygons_system:
		print("⚠️ Polygons system not found in scene")

# Query landuse polygons from the polygons system
func query_landuse_polygons() -> Array:
	if polygons_system and polygons_system.has_method("get_all_polygons"):
		return polygons_system.get_all_polygons()
	else:
		print("⚠️ Polygons system not available")
		return []

# Query polygons at a specific point
func query_polygons_at_point(point: Vector2) -> Array:
	if polygons_system and polygons_system.has_method("query_polygons_at_point"):
		return polygons_system.query_polygons_at_point(point)
	else:
		print("⚠️ Polygons system not available")
		return []

# Function to check if a point is inside a polygon using ray casting algorithm
static func is_point_in_polygon(point: Vector2, polygon: Array) -> bool:
	# Handle edge cases
	if polygon.size() < 3:
		return false
	
	var inside = false
	var j = polygon.size() - 1
	
	for i in range(polygon.size()):
		var pi = polygon[i]
		var pj = polygon[j]
		
		# Check if the ray from point intersects with the edge from pj to pi
		if ((pi.y > point.y) != (pj.y > point.y)):
			# Calculate intersection point
			var intersection_x = pj.x + (point.y - pj.y) * (pi.x - pj.x) / (pi.y - pj.y)
			
			# Check if intersection is to the right of the point
			if point.x < intersection_x:
				inside = not inside
		
		j = i
	
	return inside
