extends Node3D
class_name Place
const PlaceData = preload("res://models/Place.gd")
@export var place_data: PlaceData

func set_place_data(data: PlaceData):
	if not data:
		print("⚠️ No PlaceData provided!")
		return
	
	place_data = data

	# Assign mesh
	var mesh_instance = $MeshInstance3D
	if place_data.mesh:
		var mesh_scene = place_data.mesh.instantiate()
		mesh_instance.add_child(mesh_scene)

	# Assign sound
	var audio_player = $AudioStreamPlayer3D
	if place_data.sound:
		audio_player.stream = place_data.sound

	# Set the text label
	var text_label = $MeshInstance3D/Label3D  # Adjust path if needed
	if text_label:
		text_label.text = place_data.name  # Set name
		text_label.position.y = 2.0  # Adjust height above the cube

	print("✅ Place:", place_data.name, "Type:", place_data.type)


func speak(text, lang = "en-US"):
	if OS.has_feature("web"):
		JavaScriptBridge.eval("""
			(function() {
				var msg = new SpeechSynthesisUtterance();
				msg.text = "%s";
				msg.lang = "%s";
				window.speechSynthesis.speak(msg);
			})();
		""" % [text, lang])
	else:
		DisplayServer.tts_speak(text, "en")



func _on_area_3d_body_shape_entered(body_rid: RID, body: Node3D, body_shape_index: int, local_shape_index: int) -> void:
	if body.name =='Player':
		speak(place_data.name)
