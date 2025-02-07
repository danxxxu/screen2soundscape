extends CharacterBody3D

# How fast the player moves in meters per second.
@export var speed = 14
# The downward acceleration when in the air, in meters per second squared.
@export var fall_acceleration = 75

var target_velocity = Vector3.ZERO

@onready var neck := $Neck
@onready var camera := $Neck/Camera3D
@onready var distance_audio := $"distance_stream"
@onready var target := $"../Target"
@onready var target2 := $"../RainTarget"


@onready var currentTarget := target


var min_distance = 5.0  # Closest distance (highest pitch)
var max_distance = 300.0 # Farthest distance (lowest pitch)
var base_pitch = 1.0     # Default pitch at mid-range
var min_pitch = 0.5      # Lowest pitch
var max_pitch = 2.0      # Highest pitch


func _input(event):
	if event is InputEventKey:
		if event.pressed and event.keycode == KEY_SHIFT:
			if not distance_audio.playing:  # Prevent re-triggering
				distance_audio.play()	
		elif not event.pressed and event.keycode == KEY_SHIFT:
			distance_audio.stop()  # Stop when Shift is released
		if event.pressed and event.keycode == KEY_E:
			speak('Road on the right.')
		if event.pressed and event.keycode == KEY_Q:
			speak('Building on the left.')
		if event.pressed and event.keycode == KEY_TAB:
			if currentTarget == target:
				currentTarget = target2
				speak('To the Fountain')
			else:
				currentTarget = target
				speak('To the elevator')
				
			

func _process(delta):
	if currentTarget:
		var distance = global_position.distance_to(currentTarget.global_position)
		update_pitch(distance)

func update_pitch(distance):
	# Normalize distance to range [0, 1]
	var normalized = clamp((distance - min_distance) / (max_distance - min_distance), 0, 1)
	
	# Map distance to pitch range
	var pitch_value = lerp(max_pitch, min_pitch, normalized)
	
	# Apply pitch to audio player
	distance_audio.pitch_scale = pitch_value
	
func speak(text, lang="en-US"):
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
		DisplayServer.tts_stop()
		var voices = DisplayServer.tts_get_voices_for_language("en")
		var voice_id = voices[0]
		
		DisplayServer.tts_speak(text, DisplayServer.tts_get_voices()[0]["id"])

func _ready():	
	speak("Hello! Walk through the space to find the elevator or the fountain.
	Hold the shift key to hear the approximate distance. 
	
	Press Tab to switch target.")
	
			
func _physics_process(delta):
	var input_dir := Input.get_vector("move_left", "move_right", "move_forward", "move_back")
	var direction = (neck.transform.basis * Vector3(input_dir.x, 0, input_dir.y)).normalized()
	
	# Ground Velocity
	target_velocity.x = direction.x * speed
	target_velocity.z = direction.z * speed

	# Vertical Velocity
	if not is_on_floor(): # If in the air, fall towards the floor. Literally gravity
		target_velocity.y = target_velocity.y - (fall_acceleration * delta)

	# Moving the Character
	velocity = target_velocity
	move_and_slide()
	 ## Define a turn speed (radians per second)
	var turn_speed: float = 3.0
	
	# Check for turn actions
	if Input.is_action_pressed("turn_left"):
		neck.rotate_y(turn_speed * delta) 
		#camera.rotate_x(turn_speed * delta)
	elif Input.is_action_pressed("turn_right"):
		neck.rotate_y(-turn_speed * delta) 
		#camera.rotate_x(-turn_speed * delta)
		
