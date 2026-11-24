"""确定性种子场景。"""

from __future__ import annotations

from random import Random

from ai_native_world_engine.core import (
    APPLY_AUTHORITATIVE,
    ActionFeedback,
    FeedbackIngestor,
    ThoughtBubble,
    World,
    effect,
    target,
)


def create_seed_world(seed: int = 7) -> World:
    rng = Random(seed)
    world = World("seed-world", {"seed": seed, "scenario": "seed"})
    world.add_node(
        "mira",
        "person",
        "米拉",
        (0.0, 0.0),
        {"role": "研究者", "alive": True, "curiosity": 0.8},
    )
    world.add_node(
        "atlas",
        "organization",
        "阿特拉斯学院",
        (8.0, 0.0),
        {"kind": "research_institute"},
    )
    world.add_node(
        "district",
        "city",
        "东区",
        (4.0, 3.0),
        {"population": 1200 + rng.randint(0, 20)},
    )
    world.add_relationship("mira", "atlas", "member_of", 0.9, {"source": "seed"})
    world.add_relationship("atlas", "district", "influence", 0.4, {"source": "seed"})
    world.set_movement_target("mira", (3.0, 0.0), 1.0)

    ingestor = FeedbackIngestor()
    ingestor.ingest(
        world,
        ActionFeedback(
            source="seed_scenario",
            actor_type="system",
            actor_id="seed",
            action="seed_display_payloads",
            summary="种子场景展示思考气泡和行为弹幕契约",
            targets=[target("node", "mira")],
            effects=[
                effect(
                    "thought_bubble_add",
                    target="node:mira",
                    text="如果学院能组织起来，东区的风险会小很多。",
                    source="seed_scenario",
                    salience=0.7,
                ),
                effect(
                    "action_bullet_add",
                    target="node:mira",
                    text="前往学院",
                    source="seed_scenario",
                    salience=0.6,
                ),
            ],
            apply_mode=APPLY_AUTHORITATIVE,
        ),
    )
    world.emit_thought_bubble(ThoughtBubble("atlas", "需要先建立可信的数据流。", "seed_scenario"))
    return world

