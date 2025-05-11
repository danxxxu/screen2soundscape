@tool
extends Node

class_name MapUtils

# Map dimensions
const MAP_SIZE = Vector3(1000, 0, 1000)
const GRID_STEP = 5.0

# Center coordinates (Dudok cafe)
const CENTER_LAT = 52.0785266
const CENTER_LON = 4.3117263

# Scale factor to convert degrees to local units
const SCALE_FACTOR = 100

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

# Convert local coordinates back to lat/lon
static func convert_to_geo_coords(x: float, z: float) -> Vector2:
	# Remove the map bounds clamping effect
	x = x / MAP_SIZE.x
	z = z / MAP_SIZE.z
	
	# Convert back to degrees
	var lon = CENTER_LON + (x / (cos(deg_to_rad(CENTER_LAT)) * SCALE_FACTOR))
	var lat = CENTER_LAT + (z / SCALE_FACTOR)
	
	return Vector2(lat, lon) 
