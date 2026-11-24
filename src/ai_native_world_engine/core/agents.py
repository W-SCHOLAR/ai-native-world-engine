"""关系网智能体和关键角色智能体的结构化契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .feedback import WorldEffect
from .pressure import KeyCharacterPressure, MemoryPressure, RelationshipPressure, RulePressure
from .world import World


JsonDict = dict[str, Any]


@dataclass(slots=True)
class RelationshipAgentOutput:
    graph_type: str
    strategy: str = ""
    rule_pressures: list[RulePressure] = field(default_factory=list)
    relationship_pressures: list[RelationshipPressure] = field(default_factory=list)
    memory_pressures: list[MemoryPressure] = field(default_factory=list)
    display_effects: list[WorldEffect] = field(default_factory=list)

    def effects(self) -> list[JsonDict]:
        return (
            [pressure.to_effect() for pressure in self.rule_pressures]
            + [pressure.to_effect() for pressure in self.relationship_pressures]
            + [pressure.to_effect() for pressure in self.memory_pressures]
            + [effect.to_dict() for effect in self.display_effects]
        )


@dataclass(slots=True)
class KeyCharacterAgentOutput:
    node_id: str
    self_narrative: str = ""
    goal: str = ""
    plan: str = ""
    grounded_rule: str = ""
    key_pressure: KeyCharacterPressure | None = None
    rule_pressures: list[RulePressure] = field(default_factory=list)
    relationship_pressures: list[RelationshipPressure] = field(default_factory=list)
    display_effects: list[WorldEffect] = field(default_factory=list)

    def effects(self) -> list[JsonDict]:
        effects: list[JsonDict] = []
        if self.key_pressure:
            effects.append(self.key_pressure.to_effect())
        effects.extend(pressure.to_effect() for pressure in self.rule_pressures)
        effects.extend(pressure.to_effect() for pressure in self.relationship_pressures)
        effects.extend(effect.to_dict() for effect in self.display_effects)
        return effects


class AgentRegistry:
    def __init__(self) -> None:
        self.relationship_graph_types: set[str] = set()
        self.rule_names: set[str] = set()
        self.relationship_types: set[str] = set()

    def register_relationship_graph_type(self, graph_type: str) -> None:
        if not graph_type:
            raise ValueError("关系网类型不能为空")
        self.relationship_graph_types.add(graph_type)

    def register_rule_name(self, rule_name: str) -> None:
        if not rule_name:
            raise ValueError("规则名不能为空")
        self.rule_names.add(rule_name)

    def register_relationship_type(self, relationship_type: str) -> None:
        if not relationship_type:
            raise ValueError("关系类型不能为空")
        self.relationship_types.add(relationship_type)

    def validate_relationship_output(self, world: World, output: RelationshipAgentOutput) -> None:
        if output.graph_type not in self.relationship_graph_types:
            raise ValueError(f"未注册关系网类型：{output.graph_type}")
        self._validate_effects(world, output.effects())

    def validate_key_character_output(self, world: World, output: KeyCharacterAgentOutput) -> None:
        if not world.has_node(output.node_id):
            raise ValueError(f"关键角色节点不存在：{output.node_id}")
        self._validate_effects(world, output.effects())

    def _validate_effects(self, world: World, effects: list[JsonDict]) -> None:
        allowed = {
            "rule_pressure_add",
            "relationship_delta",
            "memory_add",
            "thought_bubble_add",
            "action_bullet_add",
            "key_character_state",
        }
        for effect in effects:
            kind = str(effect.get("type", ""))
            if kind not in allowed:
                raise ValueError(f"智能体输出不支持的效果类型：{kind}")
            if kind == "rule_pressure_add":
                rule = str(effect.get("rule", ""))
                if self.rule_names and rule not in self.rule_names:
                    raise ValueError(f"智能体输出引用未注册规则：{rule}")
            if kind == "relationship_delta":
                relation = str(effect.get("relation", effect.get("edge_type", "")))
                if self.relationship_types and relation not in self.relationship_types:
                    raise ValueError(f"智能体输出引用未注册关系类型：{relation}")
            for reference_field in ("target", "source", "from", "to"):
                if reference_field in effect:
                    value = str(effect[reference_field])
                    if value.startswith("node:") and not world.has_node(value.split(":", 1)[1]):
                        raise ValueError(f"智能体输出引用不存在节点：{value}")
