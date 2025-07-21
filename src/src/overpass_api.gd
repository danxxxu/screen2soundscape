@tool
extends Node
class_name OverpassAPI

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
	
	# Construct complex Overpass API query for places
	var bbox = "(%f,%f,%f,%f)" % [min_lat, min_lon, max_lat, max_lon]
	var query = """[out:json][timeout:1800];

(
  node["amenity"="place_of_worship"]%s;
  node["amenity"="restaurant"]%s;
  node["amenity"="cafe"]%s;
  node["amenity"="bar"]%s;
  node["amenity"="fast_food"]%s;
  node["amenity"="pub"]%s;
  node["amenity"="ice_cream"]%s;
  node["amenity"="pharmacy"]%s;
  node["amenity"="bank"]%s;
  node["amenity"="atm"]%s;
  node["amenity"="school"]%s;
  node["amenity"="university"]%s;
  node["amenity"="toilets"]%s;
  node["amenity"="police"]%s;
  node["amenity"="fire_station"]%s;
  node["shop"]%s;
  node["tourism"="hotel"]%s;
  node["tourism"="attraction"]%s;
  node["leisure"="park"]%s;
  node["amenity"="post_office"]%s;
  node["amenity"="fuel"]%s;
  node["amenity"="bus_station"]%s;
  node["railway"="station"]%s;
);

out center 10000;""" % [
		bbox, bbox, bbox, bbox, bbox, bbox, bbox, bbox, bbox, bbox,
		bbox, bbox, bbox, bbox, bbox, bbox, bbox, bbox, bbox, bbox,
		bbox, bbox, bbox
	]
	
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
