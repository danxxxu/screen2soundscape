@tool
extends Node3D

class_name BoundaryDetector

var CELL_LENGTH = 200
var current_cell: Vector2i = Vector2i.ZERO

var LoadedCels: Dictionary = {}

var player: CharacterBody3D
var buildings_node: Node3D
var places_node: Node3D
var polygons_node: Node3D

func _ready():
	# Get references to player and data nodes
	player = get_node("../Player")
	buildings_node = get_node("../Buildings")
	places_node = get_node("../Places")
	polygons_node = get_node("../Polygons")
	
	# Initialize current cell based on player position
	if player:
		_update_current_cell()
		print("🔲 Boundary detector initialized at cell: ", current_cell)
		const prefetch_cells = [
			Vector2i(0,0),
			Vector2i(0,-1),
			Vector2i(-1,0),
			Vector2i(-1,-1)			
		]
		for cell in prefetch_cells:
			var bounds = _calculate_cell_bounds(cell)
			var key: String = "%d,%d" % [cell.x, cell.y]
			await _fetch_new_area_data(bounds)
			LoadedCels[key] = true

func _process(_delta):
	if player and Engine.is_editor_hint():
		# Update when properties change in editor
		if Input.is_action_just_pressed("ui_accept"):  # Space bar
			_check_boundary_crossing()
	

func _physics_process(_delta):
	# Check for boundary crossing during gameplay
	_check_boundary_crossing()

func _check_boundary_crossing():
	if not player:
		return
	
	# Calculate which grid cell the player is currently in
	var player_pos = player.global_position
	var local_pos = Vector2(player_pos.x, player_pos.z)
	var cell_x = int(floor(local_pos.x / CELL_LENGTH))
	var cell_y = int(floor(local_pos.y / CELL_LENGTH))
	var new_cell = Vector2i(cell_x, cell_y)
	
	# Check if player moved to a different cell
	if new_cell != current_cell:
		var old_cell = current_cell
		current_cell = new_cell
		
		print("🔲 Boundary crossed! Old cell: ", old_cell, " -> New cell: ", new_cell)
		
		# Calculate the lat/lon bounds for the new cell
		var bounds = _calculate_cell_bounds(new_cell)
		var key: String = "%d,%d" % [new_cell.x, new_cell.y]

		if not key in LoadedCels:
			await _fetch_new_area_data(bounds)
			LoadedCels[key] = true

func _update_current_cell():
	if not player:
		return
	
	var player_pos = player.global_position
	var local_pos = Vector2(player_pos.x, player_pos.z)
	var cell_x = int(floor(local_pos.x / CELL_LENGTH))
	var cell_y = int(floor(local_pos.y / CELL_LENGTH))
	current_cell = Vector2i(cell_x, cell_y)

func _calculate_cell_bounds(cell: Vector2i) -> Dictionary:
	var GRID_SIZE = CELL_LENGTH
	
	# Calculate the local coordinate bounds for this cell
	var local_min = Vector2(cell.x * GRID_SIZE, -1 * cell.y * GRID_SIZE)
	var local_max = Vector2((cell.x + 1) * GRID_SIZE, -1 * (cell.y + 1) * GRID_SIZE)
	
	# Convert to lat/lon bounds
	var global_min = MapUtils.convert_to_global_coords(local_min)
	var global_max = MapUtils.convert_to_global_coords(local_max)
	
	return {
		"lat1": global_min.x,
		"lon1": global_min.y,
		"lat2": global_max.x,
		"lon2": global_max.y
	}

# Function to clear all existing places and buildings
func _clear_existing_data():
	# Clear buildings
	if buildings_node:
		for child in buildings_node.get_children():
			child.queue_free()

	# Clear places
	if places_node:
		for child in places_node.get_children():
			child.queue_free()
	
	# Clear polygons
	if polygons_node:
		for child in polygons_node.get_children():
			child.queue_free()

func _fetch_new_area_data(bounds: Dictionary):
	print("🌐 Fetching new area data for bounds: ", bounds)
	if buildings_node and buildings_node.has_method("query_buildings_with_bounds"):
		print("🏗️ Querying buildings...")
		await buildings_node.query_buildings_with_bounds(bounds.lat1, bounds.lon1, bounds.lat2, bounds.lon2)
	if places_node and places_node.has_method("query_places_with_bounds"):
		print("🏪 Querying places...")
		await places_node.query_places_with_bounds(bounds.lat1, bounds.lon1, bounds.lat2, bounds.lon2)
	if polygons_node and polygons_node.has_method("query_polygons_with_bounds"):
		print("🌿 Querying polygons...")
		await polygons_node.query_polygons_with_bounds(bounds.lat1, bounds.lon1, bounds.lat2, bounds.lon2)

# Get the current grid cell
func get_current_cell() -> Vector2i:
	return current_cell

# Get the bounds for a specific cell
func get_cell_bounds(cell: Vector2i) -> Dictionary:
	return _calculate_cell_bounds(cell)

# Manually trigger boundary check (useful for testing)
func force_boundary_check():
	_check_boundary_crossing()

# Get all cells that are currently loaded (for debugging)
func get_loaded_cells() -> Array[Vector2i]:
	var loaded_cells: Array[Vector2i] = []
	# This could be expanded to track which cells have been loaded
	loaded_cells.append(current_cell)
	return loaded_cells
