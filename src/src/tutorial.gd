extends Node

# Reference to player (set path as needed)
@onready var player = get_node("../Player")
@onready var narration_player = $NarrationPlayer
@onready var delay_timer = $StepDelay
@onready var scene = get_parent()

# Tutorial state
var current_step := 0
var steps = []
var waiting_for_delay := false
var tutorial_enabled: bool = true

var hit_wall = "res://assets/audio/tutorial-steps/step_hit.mp3"
var slide_wall = "res://assets/audio/tutorial-steps/step_slide.mp3"

var hit = false
var slide = false

func _ready():
	# Define tutorial steps
	steps = [
		{
			"audio": "res://assets/audio/tutorial-steps/step0.mp3",
			"delay": 1.0,
			"condition": func(): return true  
		},
		{
			"audio": "res://assets/audio/tutorial-steps/step1.mp3",
			"delay": 1.0,
			"condition": func(): true
		},
		{
			"audio": "res://assets/audio/tutorial-steps/step2.mp3",
			"delay": 1.0,
			"condition": func(): return Input.is_action_just_pressed("skip_step")    # return when location entered 
		},
		{
			"audio": "res://assets/audio/tutorial-steps/step3.mp3",
			"delay": 2.0,
			"condition": func(): return Input.is_action_just_pressed("move_forward") or Input.is_action_just_pressed("move_back")
		},
		{
			"audio": "res://assets/audio/tutorial-steps/step4.mp3",
			"delay": 2.0,
			"condition": func(): return Input.is_action_just_pressed("turn_right") or Input.is_action_just_pressed("turn_left")
		},
		{
			"audio": "res://assets/audio/tutorial-steps/step5.mp3",
			"delay": 3.0,
			"condition": func(): return true
		},
				{
			"audio": "res://assets/audio/tutorial-steps/step6.mp3",
			"delay": 1.0,
			"condition": func(): return Input.is_action_just_pressed("skip_step") # return when AI interaction finishes 
		},
		{
			"audio": "res://assets/audio/tutorial-steps/step7.mp3",
			"delay": 0.0,
			"condition": func(): return true
		}
	]
	start_step(0)


# ------------------- Step Management -------------------
func start_step(step_index: int):
	current_step = step_index
	var step = steps[step_index]
	waiting_for_delay = false
	play_narration(step["audio"], true)

func play_narration(file_path: String, mute: bool):
	if ResourceLoader.exists(file_path):
		narration_player.stream = load(file_path)
		narration_player.play()
		AudioServer.set_bus_mute(AudioServer.get_bus_index("STS"), mute)

func narration_finished() -> bool:
	return not narration_player.playing

func _process(delta):
	if tutorial_enabled:
		if current_step >= steps.size() or waiting_for_delay:
			return
	
		if not $NarrationPlayer.playing:
			AudioServer.set_bus_mute(AudioServer.get_bus_index("STS"), false)
		
		var step = steps[current_step]
		#print(current_step)

	# Only move forward if narration is finished AND condition is met
		if narration_finished() and step["condition"].call():
			if step["delay"] > 0:
				waiting_for_delay = true
				delay_timer.start(step["delay"])
			else:
				next_step()
				
		# Wall hit detection
		if player.wall_audio.playing and not hit:
			print("hit wall")
			hit = true
			play_narration(hit_wall, false)
		elif not player.wall_audio.playing and hit:
			# Reset flag once sound is finished
			hit = false
		
		# sliding detection
		if player.sliding_audio.playing and not slide:
			print("slide wall")
			slide = true
			play_narration(slide_wall, false)
		elif not player.sliding_audio.playing and slide:
			# Reset flag once sound is finished
			slide = false

func _input(event: InputEvent) -> void:
	if event.is_action_pressed("tutorial_toggle"):
		tutorial_enabled = !tutorial_enabled
		print("Tutorial toggled:", tutorial_enabled)
		if not tutorial_enabled:
			narration_player.stop()
			AudioServer.set_bus_mute(AudioServer.get_bus_index("STS"), false)

		if tutorial_enabled:
			# Resume tutorial from current step
			start_step(current_step)
	
	if event.is_action_pressed("skip_step"):
		if narration_player.playing:
			narration_player.stop()
			next_step()

func next_step():
	current_step += 1
	if current_step < steps.size():
		start_step(current_step)
	else:
		tutorial_complete()

func tutorial_complete():
	print("Tutorial finished!")
	AudioServer.set_bus_mute(AudioServer.get_bus_index("STS"), false)
	queue_free()

func _on_step_delay_timeout() -> void:
	print("timeout")
	waiting_for_delay = false
	next_step()

#func get_location():
	#var location = false
	#print(scene.current_command)
	#location = true
	#return location
	#
#func ai_finished():
	#return true
