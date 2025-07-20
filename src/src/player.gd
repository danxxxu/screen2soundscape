extends CharacterBody3D

# How fast the player moves in meters per second.
#@export var speed = 50
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
@onready var sliding_audio := $sliding_audio
@onready var wall_audio := $wall_audio
@onready var houses_audio := $houses_audio
@onready var zero_velocity_timer := $zero_velocity_timer
@onready var rotate_audio := $rotate_audio
@onready var proximity_detector := $proximity_detector

var min_distance: float = 5.0  # Closest distance (highest pitch)
var max_distance: float = 300.0 # Farthest distance (lowest pitch)
var base_pitch: float   = 1.0     # Default pitch at mid-range
var min_pitch: float    = 0.5      # Lowest pitch
var max_pitch: float    = 2.0      # Highest pitch
var pitch_range: float = 0.5  # How much the pitch can vary

#preload different footstep sounds, still working on it 
#const footstep_grass = preload("res://sounds/footsteps/footstep_grass.wav")
#const footstep_concrete = preload("res://sounds/footsteps/footstep_concrete.wav")

var _movement_enabled: bool = true
var is_sliding: bool = false
var was_moving: bool = false
var current_rotation: float = 0.0
var is_near_buildings: bool = false
var building_proximity_areas: Array = []

func set_movement_enabled(enabled: bool):
	_movement_enabled = enabled

func _input(event):
	if event is InputEventKey:
		if _movement_enabled:
			if event.pressed and event.keycode == KEY_SHIFT:
				if not distance_audio.playing: # Prevent re-triggering
					distance_audio.play()
			elif not event.pressed and event.keycode == KEY_SHIFT:
				distance_audio.stop()  # Stop when Shift is released
			if event.pressed and event.keycode == KEY_E:
				Speaker.speak('Road on the right.')
			if event.pressed and event.keycode == KEY_Q:
				Speaker.speak('Building on the left.')
			if event.pressed and event.keycode == KEY_TAB:
				if currentTarget == target:
					currentTarget = target2
					Speaker.speak('To the Fountain')
				else:
					currentTarget = target
					Speaker.speak('To the elevator')


func _process(delta):
	if currentTarget:
		var distance: float = global_position.distance_to(currentTarget.global_position)
		update_pitch(distance)
	
	# Update houses sound volume based on building proximity
	if is_near_buildings:
		update_houses_volume()


func update_pitch(distance):
	# Normalize distance to range [0, 1]
	var normalized = clamp((distance - min_distance) / (max_distance - min_distance), 0, 1)
	# Map distance to pitch range
	var pitch_value = lerp(max_pitch, min_pitch, normalized)
	# Apply pitch to audio player
	distance_audio.pitch_scale = pitch_value


func _ready():
	var current_place = "the Kerkplein"
	var to_find = "Cafe Dok 19"
	#	Speaker.speak(" Hello ! You are at " + current_place + " facing north. Find " + to_find + ". Press shift to hear the proximity sensor to the search place. To move around use W. A. S. D. To turn use left and right arrows. When you hear the name of the place, stop. Hit enter and type word address. Hit enter again to hear the address.", "fr")

	# Load the sliding sound
	var sliding_sound = load("res://assets/sounds/sliding.mp3")
	if sliding_sound:
		sliding_audio.stream = sliding_sound
		sliding_audio.volume_db = -10  # Adjust volume as needed
	else:
		push_error("Could not load sliding.mp3 sound file")
		
	# Load the wall hit sound
	var wall_sound = load("res://assets/audio/boundaries/wall.mp3")
	if wall_sound:
		wall_audio.stream = wall_sound
		wall_audio.volume_db = -10  # Adjust volume as needed
	else:
		push_error("Could not load wall.mp3 sound file")
		
	# Load the houses sound
	var houses_sound = load("res://assets/audio/houses.mp3")
	if houses_sound:
		houses_audio.stream = houses_sound
		houses_audio.volume_db = -10  # Adjust volume as needed
	else:
		push_error("Could not load houses.mp3 sound file")
		
	# Load the rotation sound
	var rotate_sound = load("res://assets/audio/rotate.wav")
	if rotate_sound:
		rotate_audio.stream = rotate_sound
		rotate_audio.volume_db = -10  # Adjust volume as needed
	else:
		push_error("Could not load rotate.wav sound file")
		
	# Setup proximity detector if it doesn't exist
	if not proximity_detector:
		proximity_detector = Area3D.new()
		proximity_detector.name = "proximity_detector"
		var prox_shape = CollisionShape3D.new()
		var sphere_shape = SphereShape3D.new()
		sphere_shape.radius = 0.5  # Small detection area around player
		prox_shape.shape = sphere_shape
		proximity_detector.add_child(prox_shape)
		add_child(proximity_detector)
	
	# Connect collision signals
	print("Connecting collision signals...")
	connect("body_entered", _on_body_entered)
	connect("body_exited", _on_body_exited)
	# Connect area signals for proximity detection via the proximity detector
	proximity_detector.connect("area_entered", _on_area_entered)
	proximity_detector.connect("area_exited", _on_area_exited)
	print("Collision signals connected")
	
	# Setup zero velocity timer
	zero_velocity_timer.one_shot = true
	zero_velocity_timer.wait_time = 0.2  # Half a second
	zero_velocity_timer.timeout.connect(_on_zero_velocity_timeout)

func _on_body_entered(body):
	print("Body entered signal received")
	print("Body name: ", body.name)
	print("Body groups: ", body.get_groups())
	if body.is_in_group("buildings"):
		is_sliding = true
		print("Entered building collision")
		if not sliding_audio.playing and velocity.length() > 0:
			sliding_audio.play()
	else:
		print("Body is not in buildings group")

func _on_body_exited(body):
	print("Body exited signal received")
	print("Body name: ", body.name)
	print("Body groups: ", body.get_groups())
	if body.is_in_group("buildings"):
		is_sliding = false
		print("Exited building collision")
		sliding_audio.stop()
	else:
		print("Body is not in buildings group")

func _on_area_entered(area):
	print("Area entered signal received")
	print("Area name: ", area.name)
	print("Area groups: ", area.get_groups())
	if area.is_in_group("building_proximity"):
		print("Entered building proximity")
		is_near_buildings = true
		building_proximity_areas.append(area)
		# Play houses sound when near buildings (within 10 units)
		if not houses_audio.playing:
			houses_audio.play()
		# Update initial volume
		update_houses_volume()
	else:
		print("Area is not in building_proximity group")

func _on_area_exited(area):
	print("Area exited signal received")
	print("Area name: ", area.name)
	print("Area groups: ", area.get_groups())
	if area.is_in_group("building_proximity"):
		print("Exited building proximity")
		building_proximity_areas.erase(area)
		# Check if we're still near any buildings
		if building_proximity_areas.is_empty():
			is_near_buildings = false
			# Stop houses sound when leaving all building proximity areas
			houses_audio.stop()
	else:
		print("Area is not in building_proximity group")

func _on_zero_velocity_timeout():
	if is_on_wall() and Input.is_action_pressed("move_forward"):
		if not wall_audio.playing:
			wall_audio.play()

func _physics_process(delta):
	if not _movement_enabled:
		return
	var input_dir := Input.get_vector("move_left", "move_right", "move_forward", "move_back")
	var direction =  (neck.transform.basis * Vector3(input_dir.x, 0, input_dir.y)).normalized()

	# Ground Velocity
	target_velocity.x = direction.x * speed
	target_velocity.z = direction.z * speed

	# Vertical Velocity
	if not is_on_floor(): # If in the air, fall towards the floor. Literally gravity
		target_velocity.y = target_velocity.y - (fall_acceleration * delta)

	# Moving the Character
	velocity = target_velocity
	move_and_slide()
	
	# Play sliding sound when touching walls
	if is_on_wall() and Input.is_action_pressed("move_forward"):
		print(velocity)
		if velocity.length() > 0:
			if not sliding_audio.playing:
				sliding_audio.play()
			else:
				wall_audio.stop()
				zero_velocity_timer.stop()
		else:
			sliding_audio.stop()
			if not wall_audio.playing and zero_velocity_timer.is_stopped():
				zero_velocity_timer.start()
	else:
		sliding_audio.stop()
		wall_audio.stop()
		zero_velocity_timer.stop()
	
	footstep(velocity)
	
	# Handle rotation
	var turn_speed: float = 3.0
	var rotation_amount = 0.0
	
	if Input.is_action_pressed("turn_left"):
		rotation_amount = turn_speed * delta
		neck.rotate_y(rotation_amount)
	elif Input.is_action_pressed("turn_right"):
		rotation_amount = -turn_speed * delta
		neck.rotate_y(rotation_amount)
		
	# Update rotation sound
	if rotation_amount != 0:
		neck.rotate_y(rotation_amount)
		if not rotate_audio.playing:
			rotate_audio.play()
		
		# Calculate pitch based on absolute direction (North = 0, South = 1)
		# Get the current rotation in radians and normalize it
		var current_angle = fmod(neck.rotation.y, TAU)  # Keep between 0 and TAU
		if current_angle < 0:
			current_angle += TAU  # Make sure it's positive
		# Map the angle (0 to TAU) to pitch range (1 to 2 and back to 1)
		rotate_audio.pitch_scale = lerp(1.5, 2.0, sin(current_angle))
	else:
		if rotate_audio.playing:
			rotate_audio.stop()

# footstep sounds
func footstep(vel):
	#$footstep.stream = footstep_concrete
	if(vel.length() != 0):
		if($Timer.time_left <= 0):
			$footstep.pitch_scale = randf_range(0.8, 1.2)
			$footstep.play()
#			walk cycle/loop length 
			$Timer.start(0.3)
	else:
		$footstep.stream_paused=true

func update_houses_volume():
	if not houses_audio.playing:
		return
		
	var min_distance = find_nearest_building_distance()
	
	# Map distance to volume (closer = louder)
	# Distance range: 0 to 10 units (based on proximity detection)
	# Volume range: -5db to -25db 
	var max_volume_db = -5.0   # Loudest when very close
	var min_volume_db = -25.0  # Quietest at edge of detection
	var max_distance = 10.0     # Maximum detection distance
	
	# Normalize distance and calculate volume
	var normalized_distance = clamp(min_distance / max_distance, 0.0, 1.0)
	var volume_db = lerp(max_volume_db, min_volume_db, normalized_distance)
	
	houses_audio.volume_db = volume_db
	

func find_nearest_building_distance() -> float:
	var min_distance = 999.0
	var player_pos = global_position
	var world_3d = get_world_3d()
	var space_state = world_3d.direct_space_state
	
	# Cast rays in multiple directions to find the nearest building wall
	var ray_count = 16  # Number of rays to cast in a circle
	var ray_distance = 10.0  # Maximum ray distance
	
	for i in range(ray_count):
		var angle = (i * 2.0 * PI) / ray_count
		var direction = Vector3(cos(angle), 0, sin(angle))
		
		# Create ray query
		var query = PhysicsRayQueryParameters3D.create(
			player_pos,
			player_pos + direction * ray_distance
		)
		
		# Only check for building collision bodies
		query.collision_mask = 1  # Default collision layer
		query.collide_with_areas = false
		query.collide_with_bodies = true
		
		var result = space_state.intersect_ray(query)
		
		if result and result.has("collider"):
			var collider = result.collider
			if collider.is_in_group("buildings"):
				var hit_point = result.position
				var distance_to_wall = player_pos.distance_to(hit_point)
				min_distance = min(min_distance, distance_to_wall)
	
	# Also cast rays vertically up and down for more complete coverage
	for vertical_dir in [Vector3.UP, Vector3.DOWN]:
		var query = PhysicsRayQueryParameters3D.create(
			player_pos,
			player_pos + vertical_dir * ray_distance
		)
		query.collision_mask = 1
		query.collide_with_areas = false
		query.collide_with_bodies = true
		
		var result = space_state.intersect_ray(query)
		if result and result.has("collider"):
			var collider = result.collider
			if collider.is_in_group("buildings"):
				var hit_point = result.position
				var distance_to_wall = player_pos.distance_to(hit_point)
				min_distance = min(min_distance, distance_to_wall)
	
	return min_distance if min_distance < 999.0 else 10.0
