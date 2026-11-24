from __future__ import annotations

from ai_native_world_engine.core import (
    APPLY_AUTHORITATIVE,
    ActionFeedback,
    RuleCandidate,
    RunConfig,
    effect,
    run,
    target,
)


class TestExternalActionPack:
    name = "test_external_action_pack"

    def candidates(self, world, node):  # noqa: ANN001 - mirrors RulePackage protocol in test.
        if node.id != "mira":
            return []
        feedback = ActionFeedback(
            source=self.name,
            actor_type="node",
            actor_id=node.id,
            action="external_signal",
            summary=f"{node.name} emits an external signal",
            targets=[target("node", node.id)],
            effects=[
                effect(
                    "memory_add",
                    target=f"node:{node.id}",
                    text="external action pack applied",
                    source=self.name,
                    importance=0.91,
                ),
                effect(
                    "action_bullet_add",
                    target=f"node:{node.id}",
                    text="外部动作",
                    source=self.name,
                    salience=0.7,
                ),
            ],
            apply_mode=APPLY_AUTHORITATIVE,
            metadata={"dramatic_tags": ["external_action_pack"]},
        )
        return [
            RuleCandidate(
                node_id=node.id,
                action="external_signal",
                score=99.0,
                rule=self.name,
                reason="test external package injection",
                feedback=feedback,
            )
        ]


def test_run_config_defaults_to_no_external_rule_packages() -> None:
    assert RunConfig().to_dict()["external_rule_packages"] == []


def test_external_action_pack_can_emit_feedback() -> None:
    result = run(RunConfig(ticks=1, external_rule_packages=[TestExternalActionPack()])).to_dict()
    node = next(node for node in result["snapshot"]["nodes"] if node["id"] == "mira")

    assert result["config"]["external_rule_packages"] == ["test_external_action_pack"]
    assert any(memory.get("text") == "external action pack applied" for memory in node["memories"])
    assert "action_bullets" not in node
    assert any(
        event.get("kind") == "action_feedback" and event.get("source") == "test_external_action_pack"
        for event in result["events"]
    )
