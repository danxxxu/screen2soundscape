@tool
extends Node
class_name OverpassAPI

const TAGS = [
	["amenity", "cafe"],
	["amenity", "bank"],
	["amenity", "bar"],
	["amenity", "bicycle_parking"],
	["amenity", "clinic"],
	["amenity", "fast_food"],
	["amenity", "hospital"],
	["amenity", "parking_entrance"],
	["amenity", "parking_space"],
	["amenity", "parking_symbol"],
	["amenity", "pharmacy"],
	["amenity", "post_office"],
	["amenity", "pub"],
	["amenity", "restaurant"],
	["amenity", "school"],
	["amenity", "toilets"],
	["amenity", "bus_station"],
	["amenity", "fuel"],
	["tourism", "attraction"],
	["tourism", "hotel"],
	["leisure", "park"],
	["railway", "station"],
	["natural", "tree"],
	["natural", "water"],
	["natural", "wetland"],
	["natural", "wood"],
	["landuse", "farmland"],
	["landuse", "forest"],
	["landuse", "grass"],
	["landuse", "meadow"],
	["landuse", "railway"],
	["barrier", "gate"],
	["barrier", "hedge"],
	["barrier", "wall"],
	["power", "generator"],
	["power", "pole"],
	["power", "tower"]
]

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
	
	# Create HTTP request
	var http_request = HTTPRequest.new()
	add_child(http_request)
	
	# Make the request to Overpass API
	var overpass_url = "https://overpass-api.de/api/interpreter"
	var headers = ["Content-Type: application/x-www-form-urlencoded"]
	
	print("🚀 Sending query to Overpass API...")
	var error = http_request.request(overpass_url, headers, HTTPClient.METHOD_POST, "data=" + query.uri_encode())
	
	if error != OK:
		print("❌ Error making HTTP request: ", error)
		http_request.queue_free()
		return {"building_data": {}, "node_data": {}}
	
	# Wait for response
	var result = await http_request.request_completed
	http_request.queue_free()
	
	var response_code = result[1]
	var body = result[3]
	
	print("📥 Overpass API response received. Code: ", response_code)
	
	if response_code == 200:
		var json_string = body.get_string_from_utf8()
		var json = JSON.new()
		var parse_error = json.parse(json_string)
		
		if parse_error == OK:
			var building_data = json.get_data()
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
		else:
			print("❌ JSON Parse Error: ", json.get_error_message())
			return {"building_data": {}, "node_data": {}}
	else:
		print("❌ HTTP Error: ", response_code)
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
		bodytext += '  node["%s"="%s"]%s;\n' % [tag[0], tag[1], bbox]

	# Final Overpass query
	var query = """[out:json][timeout:1800];
	(%s);
	out center 10000;""" % bodytext

	# Create HTTP request
	var http_request = HTTPRequest.new()
	add_child(http_request)
	
	# Make the request to Overpass API
	var overpass_url = "https://overpass-api.de/api/interpreter"
	var headers = ["Content-Type: application/x-www-form-urlencoded"]
	
	print("🚀 Sending places query to Overpass API...")
	var error = http_request.request(overpass_url, headers, HTTPClient.METHOD_POST, "data=" + query.uri_encode())
	
	if error != OK:
		print("❌ Error making HTTP request: ", error)
		http_request.queue_free()
		return {"places_data": {}}
	
	# Wait for response
	var result = await http_request.request_completed
	http_request.queue_free()
	
	var response_code = result[1]
	var body = result[3]
	
	print("📥 Overpass API places response received. Code: ", response_code)
	
	if response_code == 200:
		var json_string = body.get_string_from_utf8()
		var json = JSON.new()
		var parse_error = json.parse(json_string)
		
		if parse_error == OK:
			var places_data = json.get_data()
			
			if places_data.has("elements"):
				print('✅ Loaded ', places_data.elements.size(), ' place elements from Overpass API')
				return {"places_data": places_data}
			else:
				print("❌ No place elements found in Overpass response")
				return {"places_data": {}}
		else:
			print("❌ JSON Parse Error: ", json.get_error_message())
			return {"places_data": {}}
	else:
		print("❌ HTTP Error: ", response_code)
		return {"places_data": {}} 
