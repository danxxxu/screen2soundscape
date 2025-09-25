#@tool
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
	label = $Label3D

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
		if not sound:
			sound = load("res://assets/audio/places/" + place_data.category + ".mp3")
			
		var rng := RandomNumberGenerator.new()
		rng.randomize()
		
		if sound:
			ambient_player.stream = sound
			ambient_player.stream.loop = true
			ambient_player.add_to_group("occludable_audio")
			ambient_player.play()
			
			var start_offset := 0.0
			var dur := 0.0
			if sound is AudioStreamWAV:
				dur = (sound as AudioStreamWAV).get_length()
			elif sound is AudioStreamOggVorbis:
				dur = (sound as AudioStreamOggVorbis).get_length()
			elif sound is AudioStreamMP3:
				dur = (sound as AudioStreamMP3).get_length()
			if dur > 0.1:
				start_offset = rng.randf() * dur

			ambient_player.call_deferred("play", start_offset)
		else:			
			print("⚠️ Could not load ambient sound for type:", type, " using unknown.mp3")


	# Set the text label
	if label:
		label.text = place_data.name
		label.position.y = 2.0  # Position above the mesh
		# Add type if it's not "unknown"
		if place_data.type != "unknown":
			label.text += "\n(type: " + place_data.type + ")"
			label.text += "\n(category: " + place_data.category + ")"
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
		if place_data.name != 'Unnamed Place':
			announcement += place_data.name
		Speaker.speak(announcement)
		emit_signal("player_entered", self)


func _on_area_3d_body_exited(body):
	if body.name == "Player":
		#Speaker.stop_speaking()
		emit_signal("player_exited", self)
