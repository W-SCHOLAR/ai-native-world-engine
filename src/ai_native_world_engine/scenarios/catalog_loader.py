"""Governed JSON catalog scenario loader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_native_world_engine.core import ActionBullet, ThoughtBubble, World
from ai_native_world_engine.core.events import json_copy
from ai_native_world_engine.core.world import Position


JsonDict = dict[str, Any]


def load_catalog_world(scenario_path: str | Path, seed: int | None = None) -> World:
    path = Path(scenario_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("catalog root must be an object")

    world_data = _require_dict(data, "world")
    nodes = _require_list(data, "nodes")
    relationships = _list(data.get("relationships"))
    _validate_nodes(nodes)

    attributes = _dict(world_data.get("attributes"))
    attributes.setdefault("scenario", "catalog")
    attributes.setdefault("catalog_path", str(path))
    if seed is not None:
        attributes.setdefault("seed", int(seed))
    world = World(str(world_data.get("id") or path.stem), attributes)

    for node_data in nodes:
        _add_catalog_node(world, _dict(node_data))
    for relationship_data in relationships:
        _add_catalog_relationship(world, _dict(relationship_data))
    return world


def _add_catalog_node(world: World, node_data: JsonDict) -> None:
    node = world.add_node(
        str(node_data["id"]),
        str(node_data["type"]),
        str(node_data["name"]),
        Position.from_value(node_data["position"]),
        _dict(node_data.get("attributes")),
    )
    if node_data.get("movement_target") is not None:
        world.set_movement_target(
            node.id,
            Position.from_value(node_data["movement_target"]),
            float(node_data.get("movement_speed", 0.0) or 0.0),
        )
    node.key_character = json_copy(_dict(node_data.get("key_character")))
    node.memories = json_copy(_list(node_data.get("memories")))
    for bubble in _list(node_data.get("thought_bubbles")):
        bubble_data = _dict(bubble)
        world.emit_thought_bubble(
            ThoughtBubble(
                node_id=node.id,
                text=str(bubble_data.get("text", "")),
                source=str(bubble_data.get("source", "catalog")),
                mood=str(bubble_data.get("mood", "")),
                salience=float(bubble_data.get("salience", 0.5) or 0.5),
                ttl=float(bubble_data.get("ttl", 6.0) or 6.0),
            )
        )
    for bullet in _list(node_data.get("action_bullets")):
        bullet_data = _dict(bullet)
        world.emit_action_bullet(
            ActionBullet(
                node_id=node.id,
                text=str(bullet_data.get("text", "")),
                source=str(bullet_data.get("source", "catalog")),
                salience=float(bullet_data.get("salience", 0.5) or 0.5),
                ttl=float(bullet_data.get("ttl", 4.0) or 4.0),
            )
        )


def _add_catalog_relationship(world: World, relationship_data: JsonDict) -> None:
    for field in ("source", "target", "type"):
        if not relationship_data.get(field):
            raise ValueError(f"relationship missing required field: {field}")
    world.add_relationship(
        str(relationship_data["source"]),
        str(relationship_data["target"]),
        str(relationship_data["type"]),
        float(relationship_data.get("weight", 0.0) or 0.0),
        _dict(relationship_data.get("metadata")),
    )


def _validate_nodes(nodes: list[Any]) -> None:
    seen: set[str] = set()
    for raw_node in nodes:
        node = _dict(raw_node)
        for field in ("id", "type", "name", "position"):
            if field not in node or node[field] in ("", None):
                raise ValueError(f"node missing required field: {field}")
        node_id = str(node["id"])
        if node_id in seen:
            raise ValueError(f"duplicate node id in catalog: {node_id}")
        seen.add(node_id)
        Position.from_value(node["position"])
        _validate_governance(node)


def _validate_governance(node: JsonDict) -> None:
    attributes = _dict(node.get("attributes"))
    node_type = str(node.get("type", ""))
    if node_type == "person":
        synthetic = attributes.get("synthetic") is True
        public_governance = attributes.get("governance_class") in {
            "public_figure",
            "public_historical_demonstration",
        }
        if not synthetic and not public_governance:
            raise ValueError(
                f"person node {node['id']} must be synthetic or explicitly governed as a public figure"
            )
    if node_type == "population_cohort" and attributes.get("privacy") != "anonymous_aggregate":
        raise ValueError(f"population_cohort node {node['id']} must use anonymous_aggregate privacy")


def _require_dict(data: JsonDict, field: str) -> JsonDict:
    value = data.get(field)
    if not isinstance(value, dict):
        raise ValueError(f"catalog field must be object: {field}")
    return value


def _require_list(data: JsonDict, field: str) -> list[Any]:
    value = data.get(field)
    if not isinstance(value, list):
        raise ValueError(f"catalog field must be list: {field}")
    return value


def _dict(value: Any) -> JsonDict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
