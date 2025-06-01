@tool
extends Node3D
class_name Place
const PlaceData = preload("res://src/models/Place.gd")
var place_data = null
var mesh_instance: MeshInstance3D
var audio_player: AudioStreamPlayer3D
var ambient_player: AudioStreamPlayer3D
var area: Area3D
var label: Label3D


func _ready():
	mesh_instance = $MeshInstance3D
	audio_player = $AudioStreamPlayer3D
	ambient_player = $ambient_audio
	area = $Area3D
	label = $MeshInstance3D/Label3D

	# Connect area signals to scene
	var scene = get_tree().get_root().get_node("Scene")
	if scene:
		area.body_entered.connect(
			func(body):
				if body.name == "Player":
					scene._on_place_entered(self))
		area.body_exited.connect(
			func(body):
				if body.name == "Player":
					scene._on_place_exited(self))

	# If we already have place_data, set it up now that we're ready
	if place_data:
		_setup_place_data()


func set_place_data(data: PlaceData):
	if not data:
		print("⚠️ No PlaceData provided!")
		return

	place_data = data

	# If we're not ready yet, wait for _ready to call _setup_place_data
	if not is_node_ready():
		return

	_setup_place_data()


func _setup_place_data():
	# Assign mesh
	if place_data.mesh:
		var mesh_scene = place_data.mesh.instantiate()
		if mesh_scene.get_node("MeshInstance3D"):
			mesh_instance.mesh = mesh_scene.get_node("MeshInstance3D").mesh

	# Assign sound
	if place_data.sound:
		audio_player.stream = place_data.sound

	# Assign ambient sound based on type
	var allowed = [
		  "Park",
		  "Railway",
		  "Sidewalk",
		  "atm",
		  "attraction",
		  "bank",
		  "bus_station",
		  "cafe",
		  "pub",
		  "convenience",
		  "clothes",
		  "firestation",
		  "fuel",
		  "hospital",
		  "hotel",
		  "pharmacy",
		  "police",
		  "post_office",
		  "restaurant",
		  "school",
		  "supermarket",
		  "toilets",
		  "trainstation",
		  "university",
		  "unknown",
	]
	if place_data.type or place_data.category:
		var type = ''
		if place_data.type:
			type = place_data.type
		else:
			type = place_data.category
		if type in allowed:
			var sound_path = "res://assets/audio/places/" + type + ".mp3"
			var sound = load(sound_path)
			if sound:
				ambient_player.stream = sound
				ambient_player.play()
			else:
				print("⚠️ Could not load ambient sound for type:", type, " using unknown.mp3")


	# Set the text label
	if label:
		label.text = place_data.name
		label.position.y = 2.0  # Position above the mesh
		# Add type if it's not "unknown"
		if place_data.type != "unknown":
			label.text += "\n(" + place_data.type + ")"
		# Add address if available
		if place_data.tags and place_data.tags.has("addr:street"):
			var address = place_data.tags["addr:street"]
			if place_data.tags.has("addr:housenumber"):
				address += " " + place_data.tags["addr:housenumber"]
			label.text += "\n" + address


func _on_area_3d_body_entered(body):
	if body.name == "Player" and place_data:
		# Announce place name and type
		var announcement = ''
		if place_data.type != "unknown":
			announcement += place_data.type + " "
		announcement += place_data.name
		Speaker.speak(announcement)
		if audio_player.stream:
			audio_player.play()


func _on_area_3d_body_exited(body):
	if body.name == "Player":
		Speaker.stop_speaking()
		if audio_player.playing:
			audio_player.stop()
