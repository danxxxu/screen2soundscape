@tool
extends Node
class_name OverpassAPI
#const overpass_url = 'http://142.93.234.209/api/interpreter'
const overpass_url = 'https://overpass-api.de/api/interpreter'

# Retry configuration
const MAX_RETRIES = 5
const BASE_DELAY = 1.0  # Base delay in seconds
const TAGS = [
	['access', 'university'],
	['aeroway', 'helipad'],
	['amenity', 'atm'],
	['amenity', 'atm', 'symbol'],
	['amenity', 'bank'],
	['amenity', 'bank', 'symbol'],
	['amenity', 'bar'],
	['amenity', 'bicycle', 'parking'],
	['amenity', 'bicycle', 'rental'],
	['amenity', 'bus', 'station'],
	['amenity', 'cafe'],
	['amenity', 'clinic'],
	['amenity', 'dentist'],
	['amenity', 'fastfood'],
	['amenity', 'fire', 'station'],
	['amenity', 'fountain'],
	['amenity', 'fuel'],
	['amenity', 'hospital'],
	['amenity', 'parking', 'entrance'],
	['amenity', 'parking', 'space'],
	['amenity', 'parking', 'symbol'],
	['amenity', 'pharmacy'],
	['amenity', 'police'],
	['amenity', 'post', 'office'],
	['amenity', 'pub'],
	['amenity', 'pub', 'symbol'],
	['amenity', 'restaurant'],
	['amenity', 'school'],
	['amenity', 'school', 'symbol'],
	['amenity', 'toilets'],
	['amenity', 'university'],
	['barrier', 'gate', 'symbol'],
	['barrier', 'hedge'],
	['barrier', 'wall'],
	['building', 'garage', 'symbol'],
	['bus', 'stop'],
	['charging', 'station'],
	['events', 'venue'],
	['hairdresser', 'symbol'],
	['highway', 'bus', 'stop'],
	['highway', 'crossing'],
	['highway', 'footway'],
	['highway', 'primary'],
	['highway', 'residential'],
	['highway', 'service'],
	['highway', 'tertiary'],
	['highway', 'track'],
	['highway', 'unclassified'],
	['ice', 'cream'],
	['landuse', 'farmland'],
	['landuse', 'farmland', 'symbol'],
	['landuse', 'forest'],
	['landuse', 'grass'],
	['landuse', 'meadow'],
	['landuse', 'railway'],
	['language', 'school'],
	['leisure', 'park'],
	['loading', 'dock'],
	['location', 'forestpark'],
	['location', 'park2'],
	['location', 'store door'],
	['natural', 'tree'],
	['natural', 'water'],
	['natural', 'wetland'],
	['natural', 'wood'],
	['navigation', 'footsteps', 'wet1'],
	['post', 'office'],
	['power', 'generator'],
	['power', 'pole'],
	['power', 'tower'],
	['railway', 'station'],
	['shop', 'bakery'],
	['shop', 'clothes'],
	['shop', 'convenience'],
	['shop', 'supermarket'],
	['social', 'centre'],
	['social', 'facility'],
	['surface', 'asphalt'],
	['surface', 'paved'],
	['surface', 'unpaved'],
	['tourism', 'attraction'],
	['tourism', 'hotel'],
	['type', 'street'],
	['amenity', '*'],
	['shop', '*'],
	['tourism', '*'],
	['waterway', 'stream']
]

func _make_overpass_request(query: String, query_name: String) -> Dictionary:
	"""
	Generic function to make Overpass API requests with retry logic
	Returns: Dictionary with response data or empty dict on failure
	"""
	for attempt in range(MAX_RETRIES):
		print("🔄 %s attempt %d/%d..." % [query_name, attempt + 1, MAX_RETRIES])
		
		# Create HTTP request
		var http_request = HTTPRequest.new()
		add_child(http_request)
		
		# Make the request to Overpass API
		var overpass_url = "https://overpass-api.de/api/interpreter"
		var headers = ["Content-Type: application/x-www-form-urlencoded"]
		
		var error = http_request.request(overpass_url, headers, HTTPClient.METHOD_POST, "data=" + query.uri_encode())
		
		if error != OK:
			print("❌ Error making HTTP request (attempt %d): %d" % [attempt + 1, error])
			http_request.queue_free()
			if attempt < MAX_RETRIES - 1:
				var delay = BASE_DELAY * pow(2, attempt)  # Exponential backoff
				print("⏳ Waiting %.1f seconds before retry..." % delay)
				await get_tree().create_timer(delay).timeout
			continue
		
		# Wait for response
		var result = await http_request.request_completed
		http_request.queue_free()
		
		var response_code = result[1]
		var body = result[3]
		
		print("📥 %s response received (attempt %d). Code: %d" % [query_name, attempt + 1, response_code])
		
		if response_code == 200:
			var json_string = body.get_string_from_utf8()
			var json = JSON.new()
			var parse_error = json.parse(json_string)
			
			if parse_error == OK:
				var data = json.get_data()
				print("✅ %s successful on attempt %d" % [query_name, attempt + 1])
				return data
			else:
				print("❌ JSON Parse Error (attempt %d): %s" % [attempt + 1, json.get_error_message()])
		else:
			print("❌ HTTP Error (attempt %d): %d" % [attempt + 1, response_code])
		
		# If not the last attempt, wait before retrying
		if attempt < MAX_RETRIES - 1:
			var delay = BASE_DELAY * pow(2, attempt)  # Exponential backoff
			print("⏳ Waiting %.1f seconds before retry..." % delay)
			await get_tree().create_timer(delay).timeout
	
	print("❌ %s failed after %d attempts" % [query_name, MAX_RETRIES])
	return {}

func query_buildings(lat1: float, lon1: float, lat2: float, lon2: float) -> Dictionary:
	"""
	Query buildings from Overpass API using real world coordinates
	lat1, lon1: First corner of bounding box
	lat2, lon2: Second corner of bounding box
	Returns: Dictionary with building_data and node_data
	"""
	
	# Ensure proper bounding box order (min_lat, min_lon, max_lat, max_lon)
	var min_lat = min(lat1, lat2)
	var min_lon = min(lon1, lon2)
	var max_lat = max(lat1, lat2)
	var max_lon = max(lon1, lon2)
	
	print("🌐 Querying Overpass API for buildings...")
	print("📍 Bounding box: ", min_lat, ",", min_lon, " to ", max_lat, ",", max_lon)
	
	# Construct Overpass API query
	var query = "[out:json][timeout:25];\n\nway[\"building\"](%f,%f,%f,%f);\nout body;\n>;\nout skel qt;" % [
		min_lat, min_lon, max_lat, max_lon
	]
	
	# Use retry logic to make the request
	var building_data = await _make_overpass_request(query, "Buildings query")
	
	if building_data.is_empty():
		return {"building_data": {}, "node_data": {}}
	
	var node_data = {}
	
	# Process the data and extract node coordinates
	if building_data.has("elements"):
		# First, collect all node coordinates
		for element in building_data.elements:
			if element.type == "node":
				node_data[element.id] = {
					"lat": element.lat,
					"lon": element.lon
				}
		print('✅ Loaded ', building_data.elements.size(), ' building elements from Overpass API')
		print('📍 Extracted ', node_data.size(), ' node coordinates')
		
		return {"building_data": building_data, "node_data": node_data}
	else:
		print("❌ No elements found in Overpass response")
		return {"building_data": {}, "node_data": {}} 

func query_places(lat1: float, lon1: float, lat2: float, lon2: float) -> Dictionary:
	"""
	Query places (amenities, shops, tourism, etc.) from Overpass API using real world coordinates
	lat1, lon1: First corner of bounding box
	lat2, lon2: Second corner of bounding box
	Returns: Dictionary with places_data
	"""
	
	# Ensure proper bounding box order (min_lat, min_lon, max_lat, max_lon)
	var min_lat = min(lat1, lat2)
	var min_lon = min(lon1, lon2)
	var max_lat = max(lat1, lat2)
	var max_lon = max(lon1, lon2)
	
	print("🏪 Querying Overpass API for places...")
	print("📍 Bounding box: ", min_lat, ",", min_lon, " to ", max_lat, ",", max_lon)
	var bbox = "(%f,%f,%f,%f)" % [min_lat, min_lon, max_lat, max_lon]

	# Build the query body dynamically
	var bodytext = ""
	for tag in TAGS:
		if tag[1] == "*":
			bodytext += '  node["%s"]%s;\n' % [tag[0], bbox]
		else:
			bodytext += '  node["%s"="%s"]%s;\n' % [tag[0], tag[1], bbox]

	# Final Overpass query
	var query = """[out:json][timeout:1800];
	(%s);
	out center 10000;""" % bodytext

	# Use retry logic to make the request
	var places_data = await _make_overpass_request(query, "Places query")
	
	if places_data.is_empty():
		return {"places_data": {}}
	
	if places_data.has("elements"):
		print('✅ Loaded ', places_data.elements.size(), ' place elements from Overpass API')
		return {"places_data": places_data}
	else:
		print("❌ No place elements found in Overpass response")
		return {"places_data": {}} 

# Function to query landuse polygons for 'grass' and 'meadow'
func query_landuse_polygons(lat1: float, lon1: float, lat2: float, lon2: float) -> Dictionary:
	"""
	Query landuse polygons from Overpass API using real world coordinates
	lat1, lon1: First corner of bounding box
	lat2, lon2: Second corner of bounding box
	Returns: Dictionary with polygon_data and node_data
	"""
	
	# Ensure proper bounding box order (min_lat, min_lon, max_lat, max_lon)
	var min_lat = min(lat1, lat2)
	var min_lon = min(lon1, lon2)
	var max_lat = max(lat1, lat2)
	var max_lon = max(lon1, lon2)
	
	print("📍 Bounding box: ", min_lat, ",", min_lon, " to ", max_lat, ",", max_lon)
	print("🌿 Querying Overpass API for landuse polygons...")

	# bbox as string
	var bbox = "(%f,%f,%f,%f)" % [min_lat, min_lon, max_lat, max_lon]

	# selectors with single quotes → cleaner, no escaping needed
	var selectors = [
		"way['landuse'='grass']",
		"relation['landuse'='grass']",
		"way['landuse'='meadow']",
		"relation['landuse'='meadow']",
		"way['natural'='grassland']",
		"relation['natural'='grassland']",
		"way['landcover'='grass']",
		"relation['landcover'='grass']",
		"way['surface'='grass']['area'='yes']",
		"relation['surface'='grass']['area'='yes']",
	]

	# build body dynamically
	var body_text = ""
	for sel in selectors:
		body_text += "  %s%s;\n" % [sel, bbox]

	# full query
	var query = "[out:json][timeout:25];\n(\n" + body_text + ");\nout body;\n>;\nout skel qt;\n"

	# Use retry logic to make the request
	var polygon_data = await _make_overpass_request(query, "Landuse polygons query")
	
	if polygon_data.is_empty():
		return {"polygon_data": {}, "node_data": {}}
	
	var node_data = {}
	
	# Process the data and extract node coordinates
	if polygon_data.has("elements"):
		# First, collect all node coordinates
		for element in polygon_data.elements:
			if element.type == "node":
				node_data[element.id] = {
					"lat": element.lat,
					"lon": element.lon
				}
		print('✅ Loaded ', polygon_data.elements.size(), ' landuse elements from Overpass API')
		print('📍 Extracted ', node_data.size(), ' node coordinates')
		
		return {"polygon_data": polygon_data, "node_data": node_data}
	else:
		print("❌ No landuse elements found in Overpass response")
		return {"polygon_data": {}, "node_data": {}} 
