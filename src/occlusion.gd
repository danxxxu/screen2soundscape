
extends Node

@export var occlusion_mask: int = 1 << 0

# Tuning
@export var blocked_volume_db := -12.0
@export var open_volume_db := 0.0
@export var blocked_cutoff_hz := 1200.0
@export var open_cutoff_hz := 24000.0
@export var lerp_speed := 0.15  # 0..1 per physics frame

func _physics_process(_dt: float) -> void:
	var listener := get_viewport().get_camera_3d()
	if listener == null:
		return

	var space := get_tree().root.get_world_3d().direct_space_state
	for p in get_tree().get_nodes_in_group("occludable_audio"):
		if p is AudioStreamPlayer3D and p.stream != null:
			var q := PhysicsRayQueryParameters3D.create(listener.global_position, p.global_position)
			q.collision_mask = occlusion_mask
			q.exclude = [p]

			var hit := space.intersect_ray(q)
			var blocked := hit.size() > 0

			var target_db: float
			var target_cut: float
			if blocked:
				target_db = blocked_volume_db
				target_cut = blocked_cutoff_hz
			else:
				target_db = open_volume_db
				target_cut = open_cutoff_hz

			p.volume_db = lerp(p.volume_db, target_db, lerp_speed)
			p.attenuation_filter_cutoff_hz = lerp(p.attenuation_filter_cutoff_hz, target_cut, lerp_speed)
