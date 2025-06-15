@tool
extends Node

class_name MapUtils

# Map dimensions
const MAP_SIZE = Vector3(1000, 0, 1000)
const GRID_STEP = 5.0
const center = Vector2(51.589286, 4.780329)
const CENTER_LAT = center.x
const CENTER_LON = center.y

# Scale factor to convert degrees to local units
const SCALE_FACTOR = 200

# Convert lat/lon to local coordinates
static func convert_to_local_coords(lat: float, lon: float) -> Vector2:
	# Calculate difference from center point
	var lat_diff = lat - CENTER_LAT
	var lon_diff = lon - CENTER_LON
	
	# Convert to local coordinates
	# We multiply by SCALE_FACTOR to convert tiny degree differences to meaningful distances
	# Note: cos(CENTER_LAT) accounts for longitude distortion at different latitudes
	var x = lon_diff * cos(deg_to_rad(CENTER_LAT)) * SCALE_FACTOR
	var z = lat_diff * SCALE_FACTOR
	
	# Scale to map bounds
	x = clamp(x * MAP_SIZE.x, -MAP_SIZE.x / 2, MAP_SIZE.x / 2)
	z = clamp(z * MAP_SIZE.z, -MAP_SIZE.z / 2, MAP_SIZE.z / 2)
	
	return Vector2(x, z)
