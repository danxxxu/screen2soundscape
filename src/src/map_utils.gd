@tool
extends Node

class_name MapUtils
const MAP_SIDE_LENGTH = 1000

# Map dimensions
const MAP_SIZE = Vector3(MAP_SIDE_LENGTH, 0, MAP_SIDE_LENGTH)
const GRID_STEP = 5.0



#static var start = Vector2(52.372099, 4.892923)
#static var start = Vector2(52.078247, 4.291105)
static var start = Vector2(52.158919, 4.489398) # leiden


# Scale factor to convert degrees to local units
const SCALE_FACTOR = 200

# Convert lat/lon to local coordinates
static func convert_to_local_coords(lat: float, lon: float) -> Vector2:
	# Calculate difference from center point
	var lat_diff = lat - start.x
	var lon_diff = lon - start.y
	
	# Convert to local coordinates
	# We multiply by SCALE_FACTOR to convert tiny degree differences to meaningful distances
	# Note: cos(CENTER_LAT) accounts for longitude distortion at different latitudes
	var x = lon_diff * cos(deg_to_rad(start.x)) * SCALE_FACTOR
	var z = lat_diff * SCALE_FACTOR
	
	# Scale to map bounds
	x = clamp(x * MAP_SIDE_LENGTH, -MAP_SIDE_LENGTH / 2, MAP_SIDE_LENGTH / 2)
	z = clamp(z * MAP_SIDE_LENGTH, -MAP_SIDE_LENGTH / 2, MAP_SIDE_LENGTH / 2)
	
	return Vector2(x, z)

# Convert local coordinates back to lat/lon
static func convert_to_global_coords(local_pos: Vector2) -> Vector2:
	# Convert from local coordinates back to lat/lon differences
	var x = local_pos.x / MAP_SIDE_LENGTH
	var z = local_pos.y / MAP_SIDE_LENGTH
	
	# Convert back to lat/lon differences
	var lon_diff = x / (cos(deg_to_rad(start.x)) * SCALE_FACTOR)
	var lat_diff = z / SCALE_FACTOR
	
	# Add to start coordinates
	var lat = start.x + lat_diff
	var lon = start.y + lon_diff
	
	return Vector2(lat, lon)
