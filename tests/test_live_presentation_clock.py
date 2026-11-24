from ai_native_world_engine.core.projection_delta import apply_projection_delta, projection_keyframe
from ai_native_world_engine.core import World


def test_schedule_is_not_expired_by_simulation_tick() -> None:
    world = World.scenario("seed", seed=7)
    keyframe = projection_keyframe(world, sequence=1)
    delta = {
        "sequence": 2,
        "tick": 500,
        "world_patch": {"tick": 500, "upsert_nodes": [], "delete_node_ids": [], "upsert_relationships": [], "delete_relationship_keys": []},
        "thought_schedules": [{"sequence": 9, "node_id": "agent-a", "tick": 1, "delay": 0.5, "interval": 8, "ttl": 4, "slice_count": 6, "text": "still playing"}],
        "action_visuals": [],
        "summary_patch": {},
    }

    projected = apply_projection_delta(keyframe, delta)

    assert projected["thought_schedules"][0]["sequence"] == 9


def test_dense_epoch_is_not_truncated_at_the_old_schedule_limit() -> None:
    world = World.scenario("seed", seed=7)
    keyframe = projection_keyframe(world, sequence=1)
    schedules = [
        {
            "sequence": index + 1,
            "node_id": f"agent-{index}",
            "occurrences": [
                {
                    "occurrence_id": f"dense-{index}",
                    "node_id": f"agent-{index}",
                    "text": "观察。",
                    "delay": index % 60,
                    "duration": 4,
                }
            ],
        }
        for index in range(400)
    ]

    projected = apply_projection_delta(
        keyframe,
        {
            "sequence": 2,
            "tick": 1,
            "world_patch": {},
            "thought_schedules": schedules,
            "action_visuals": [],
            "summary_patch": {},
        },
    )

    assert len(projected["thought_schedules"]) == 400
    assert projected["thought_schedules"][0]["sequence"] == 1
