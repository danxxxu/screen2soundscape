@tool
extends Node3D
class_name Place
const PlaceData = preload("res://src/models/Place.gd")

# Signals for player interaction - much better than direct parent calls!
signal player_entered(place: Place)
signal player_exited(place: Place)

var place_data = null
var mesh_instance: MeshInstance3D
var audio_player: AudioStreamPlayer3D
var ambient_player: AudioStreamPlayer3D
var area: Area3D
var label: Label3D


func _ready():
	mesh_instance = $MeshInstance3D
	audio_player = $name_audio
	ambient_player = $ambient_audio
	area = $Area3D
	label = $MeshInstance3D/Label3D

	# Connect area signals to our own signal handlers - no more direct parent calls!
	area.body_entered.connect(_on_area_3d_body_entered)
	area.body_exited.connect(_on_area_3d_body_exited)

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

	if place_data.type and place_data.category:
		var type = place_data.category + "_"+ place_data.type
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
		var announcement = ''
		if place_data.type != "unknown":
			announcement += place_data.type + " "
		announcement += place_data.name
		Speaker.speak(announcement)
		if audio_player.stream:
			audio_player.play()
		emit_signal("player_entered", self)


func _on_area_3d_body_exited(body):
	if body.name == "Player":
		Speaker.stop_speaking()
		if audio_player.playing:
			audio_player.stop()
		emit_signal("player_exited", self)
