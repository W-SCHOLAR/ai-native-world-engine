import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
EXPORTER = runpy.run_path(str(ROOT / "examples" / "export_viewer_projection.py"))
build_projection = EXPORTER["build_projection"]


def test_export_projection_contains_scheduled_relationship_round() -> None:
    projection = build_projection()
    thoughts = projection["thoughts"]
    actions = projection["actions"]
    active_thoughts = [
        item for item in thoughts if item.get("origin") == "active_node"
    ]
    ripple_thoughts = [
        item for item in thoughts if item.get("origin") == "ripple_response"
    ]
    active_actions = [
        item for item in actions if item.get("origin") == "active_node"
    ]
    ripple_actions = [
        item for item in actions if item.get("origin") == "ripple_response"
    ]
    assert active_thoughts == []
    assert active_actions == []
    assert ripple_thoughts == []
    assert ripple_actions == []
    grounded_cues = [
        effect
        for action in projection["grounded_actions"]
        for effect in action["effects"]
        if effect["type"] == "action_bullet_add"
    ]
    assert grounded_cues
    assert all(effect["text"] for effect in grounded_cues)
    json.dumps(projection, ensure_ascii=False)
