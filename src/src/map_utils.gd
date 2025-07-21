@tool
extends Node

class_name MapUtils
const MAP_SIDE_LENGTH = 1000
# Map dimensions
const MAP_SIZE = Vector3(MAP_SIDE_LENGTH, 0, MAP_SIDE_LENGTH)
const GRID_STEP = 5.0
const start = Vector2(51.589286, 4.780329)
const START_LAT = start.x
const START_LON = start.y

# Scale factor to convert degrees to local units
const SCALE_FACTOR = 200

# Convert lat/lon to local coordinates
static func convert_to_local_coords(lat: float, lon: float) -> Vector2:
	# Calculate difference from center point
	var lat_diff = lat - START_LAT
	var lon_diff = lon - START_LON
	
	# Convert to local coordinates
	# We multiply by SCALE_FACTOR to convert tiny degree differences to meaningful distances
	# Note: cos(CENTER_LAT) accounts for longitude distortion at different latitudes
	var x = lon_diff * cos(deg_to_rad(START_LAT)) * SCALE_FACTOR
	var z = lat_diff * SCALE_FACTOR
	
	# Scale to map bounds
	x = clamp(x * MAP_SIDE_LENGTH, -MAP_SIDE_LENGTH / 2, MAP_SIDE_LENGTH / 2)
	z = clamp(z * MAP_SIDE_LENGTH, -MAP_SIDE_LENGTH / 2, MAP_SIDE_LENGTH / 2)
	
	return Vector2(x, z)
