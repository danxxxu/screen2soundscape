extends Node3D
"res://rocky_terrain_02_diff_4k.jpg"
const PlaceData = preload("res://models/Place.gd")
@export var map_size: Vector3 = Vector3(100, 0, 100) # Define the map size
@export var place_meshes: Array[PackedScene] # Assign random meshes in the editor
@export var place_sounds: Array[AudioStream] # Assign random sounds in the editor

var place_scenes: Array[PlaceData] # Holds dynamically generated places


func generate_places():
	var place_names = ["Bar", "Cafe", "School", "Bus Stop", "Hospital", "Park", "Library",
					  "Supermarket", "Restaurant", "Cinema", "Gym", "Stadium", "Mall",
					  "Gas Station", "Hotel"]

	for i in range(15):
		var place = PlaceData.new()
		place.name = place_names[i]

		# Assign a random mesh and sound
		if place_meshes.size() > 0:
			place.mesh = place_meshes[randi() % place_meshes.size()]
		if place_sounds.size() > 0:
			place.sound = place_sounds[randi() % place_sounds.size()]

		place.type = "Building" if i < 10 else "Public Space"  # Example classification

		place_scenes.append(place)  # Store the dynamically created place


func _ready():
	generate_places()  # Automatically create places

	print("Generating", place_scenes.size(), "places...")

	for place_data in place_scenes:
		var scene          = load("res://Place.tscn")
		var place_instance = scene.instantiate() # Load Place Scene
		place_instance.set_place_data(place_data)

		# Set random position within map bounds
		place_instance.position = Vector3(
			randf_range(-map_size.x / 2, map_size.x / 2),
			0, # Keep it on the ground
			randf_range(-map_size.z / 2, map_size.z / 2)
		)

		add_child(place_instance)
