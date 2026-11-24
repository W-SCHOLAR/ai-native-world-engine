"""Replay reconstruction and world archive helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .events import TraceLedger, json_copy
from .memory import AiCausalityTraceLedger, PressureActionTraceLedger, SocialRippleLedger
from .pressure import StructuredPressureView
from .world import World


JsonDict = dict[str, Any]


@dataclass(slots=True)
class ReplayReconstruction:
    snapshot: JsonDict
    consistency: JsonDict

    def to_dict(self) -> JsonDict:
        return {
            "snapshot": json_copy(self.snapshot),
            "consistency": json_copy(self.consistency),
        }


class ReplayReconstructor:
    """Best-effort reconstruction from feedback effects.

    The authoritative snapshot remains the source of truth. This helper is a
    debug audit surface that verifies whether feedback contains enough
    information to rebuild a minimal observable world.
    """

    def reconstruct(self, snapshot: JsonDict) -> ReplayReconstruction:
        world = World(str(snapshot.get("id", "replay")), json_copy(_dict(snapshot.get("attributes"))))
        world.tick = int(snapshot.get("tick", 0) or 0)
        errors: list[JsonDict] = []
        for node in _list(snapshot.get("nodes")):
            node_data = _dict(node)
            world.add_node(
                str(node_data.get("id", "")),
                str(node_data.get("type", "node")),
                str(node_data.get("name", node_data.get("id", "node"))),
                _dict(node_data.get("position")),
                _dict(node_data.get("attributes")),
            )
        for relationship in _list(snapshot.get("relationships")):
            relation_data = _dict(relationship)
            try:
                world.add_relationship(
                    str(relation_data.get("source", "")),
                    str(relation_data.get("target", "")),
                    str(relation_data.get("type", "")),
                    float(relation_data.get("weight", 0.0) or 0.0),
                    _dict(relation_data.get("metadata")),
                )
            except Exception as exc:  # noqa: BLE001 - archive audit should collect errors.
                errors.append({"kind": "relationship_replay_error", "error": str(exc), "relationship": relation_data})
        world.events.records = json_copy(_list(snapshot.get("events")))
        world.traces = TraceLedger.from_records(_list(snapshot.get("traces")))
        replay_snapshot = world.snapshot()
        consistency = {
            "node_count_matches": len(_list(snapshot.get("nodes"))) == len(replay_snapshot["nodes"]),
            "relationship_count_matches": len(_list(snapshot.get("relationships"))) == len(replay_snapshot["relationships"]),
            "event_count_matches": len(_list(snapshot.get("events"))) == len(replay_snapshot["events"]),
            "trace_count_matches": len(_list(snapshot.get("traces"))) == len(replay_snapshot["traces"]),
            "error_count": len(errors),
            "errors": errors[:20],
        }
        return ReplayReconstruction(replay_snapshot, consistency)


class WorldArchive:
    def export(self, world: World, provider_outputs: list[JsonDict] | None = None, provider_audits: list[JsonDict] | None = None) -> JsonDict:
        snapshot = world.snapshot()
        replay = ReplayReconstructor().reconstruct(snapshot).to_dict()
        social_ripples = SocialRippleLedger().build_report(world)
        pressure_action = PressureActionTraceLedger().build_report(world)
        ai_causality = AiCausalityTraceLedger().build_report(world)
        return {
            "schema": "world_archive_v1",
            "snapshot": snapshot,
            "events": json_copy(snapshot["events"]),
            "traces": json_copy(snapshot["traces"]),
            "structured_pressure": StructuredPressureView().build(world),
            "pressure_action_report": pressure_action,
            "ai_causality_report": ai_causality,
            "social_ripples": social_ripples,
            "provider_outputs": json_copy(provider_outputs or []),
            "provider_audits": json_copy(provider_audits or []),
            "replay": replay,
            "consistency": {
                **json_copy(_dict(replay.get("consistency"))),
                "ai_pressure_alignment_rate": _dict(_dict(ai_causality).get("totals")).get("alignment_rate", 0.0),
                "pressure_action_match_rate": _dict(_dict(pressure_action).get("totals")).get("match_rate", 0.0),
            },
        }


def _dict(value: Any) -> JsonDict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
