"""Deterministic grounded social speech actions."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

from .action_contracts import ActionInstance, ActionTransition
from .events import json_copy
from .feedback import WorldEffect, effect
from .rule_contracts import JsonDict, RuleCandidate
from .world import World, WorldNode


SPEECH_INTENTS = frozenset(
    {
        "inform",
        "ask",
        "warn",
        "request",
        "command",
        "promise",
        "negotiate",
        "comfort",
        "persuade",
        "accuse",
        "threaten",
        "deceive",
        "announce",
        "reply",
    }
)
SPEECH_VISIBILITY = frozenset({"direct", "public", "organization", "remote"})
MAX_SPEECH_CONTENT = 240
MAX_SPEECH_RECIPIENTS = 12
DEFAULT_SPEECH_RANGE = 6.0
DEFAULT_WITNESS_RANGE = 4.0
DEFAULT_DUPLICATE_COOLDOWN = 3


@dataclass(slots=True)
class SpeechDelivery:
    event: JsonDict
    effects: list[WorldEffect]


class SpeakRulePackage:
    name = "speak"
    version = "2"
    action_runtime_version = 2

    def candidates(self, world: World, node: WorldNode) -> list[RuleCandidate]:
        if _speaker_unavailable_reason(node):
            return []
        candidates: list[RuleCandidate] = []
        for pressure in node.rule_pressures:
            if str(pressure.get("rule", "")) not in {
                "speak",
                "speech",
                "social_speech",
                "说话",
                "语言动作",
            }:
                continue
            intent = _intent(pressure.get("intent", "inform"))
            target_ids = _target_ids(pressure)
            visibility = str(pressure.get("visibility", "direct"))
            if visibility not in SPEECH_VISIBILITY:
                visibility = "direct"
            if visibility == "direct" and not target_ids:
                continue
            content = _content_for_intent(intent, pressure)
            if not content:
                continue
            fingerprint = _speech_fingerprint(node.id, target_ids, intent, content)
            cooldown = max(
                int(
                    pressure.get(
                        "cooldown_ticks", DEFAULT_DUPLICATE_COOLDOWN
                    )
                    or 0
                ),
                0,
            )
            if _recent_duplicate(world, fingerprint, cooldown):
                continue
            candidates.append(
                RuleCandidate(
                    node_id=node.id,
                    action="speak",
                    score=1.0 + float(pressure.get("weight", 0.0) or 0.0),
                    rule=self.name,
                    reason=str(pressure.get("reason", f"speech intent: {intent}")),
                    metadata={
                        "channel": "social",
                        "locks": ["voice"],
                        "intent": intent,
                        "target_ids": target_ids,
                        "content": content,
                        "claims": _claims(pressure.get("claims", pressure.get("facts", []))),
                        "visibility": visibility,
                        "conversation_id": str(pressure.get("conversation_id", "")),
                        "reply_to": str(pressure.get("reply_to", "")),
                        "language": str(
                            pressure.get(
                                "language", node.attributes.get("language", "common")
                            )
                        ),
                        "max_range": float(
                            pressure.get("max_range", DEFAULT_SPEECH_RANGE)
                            or DEFAULT_SPEECH_RANGE
                        ),
                        "witness_range": float(
                            pressure.get("witness_range", DEFAULT_WITNESS_RANGE)
                            or DEFAULT_WITNESS_RANGE
                        ),
                        "duration_ticks": max(
                            int(pressure.get("duration_ticks", 1) or 1), 1
                        ),
                        "urgency": max(
                            0.0,
                            min(1.0, float(pressure.get("urgency", 0.5) or 0.0)),
                        ),
                        "fingerprint": fingerprint,
                        "pressure": json_copy(pressure),
                        "root_causality_id": str(
                            pressure.get("root_causality_id", "")
                        ),
                        "caused_by": _string_list(pressure.get("caused_by")),
                    },
                )
            )
        return candidates

    def start(self, world: World, candidate: RuleCandidate) -> ActionTransition:
        speaker = world.node(candidate.node_id)
        unavailable_reason = _speaker_unavailable_reason(speaker)
        if unavailable_reason:
            return ActionTransition(
                status="failed",
                summary=f"{speaker.name} 当前无法说话",
                channel="social",
                progress=0.0,
                locks=["voice"],
                behavior_label="说话",
                status_reason=unavailable_reason,
            )
        target_ids = _string_list(candidate.metadata.get("target_ids"))[
            :MAX_SPEECH_RECIPIENTS
        ]
        intent = _intent(candidate.metadata.get("intent", "inform"))
        content = str(candidate.metadata.get("content", ""))[:MAX_SPEECH_CONTENT]
        event_id = f"speech:{world.tick}:{world.action_sequence + 1}:{speaker.id}"
        conversation_id = str(candidate.metadata.get("conversation_id", "")) or (
            f"conversation:{speaker.id}:{target_ids[0]}:{world.tick}"
            if target_ids
            else f"conversation:{speaker.id}:public:{world.tick}"
        )
        pressure = candidate.metadata.get("pressure", {})
        pressure_data = pressure if isinstance(pressure, dict) else {}
        pressure_id = str(pressure_data.get("pressure_id", "")).strip()
        action_id = (
            f"action:{world.tick}:{world.action_sequence + 1}:"
            f"{speaker.id}:social"
        )
        root_causality_id = str(
            candidate.metadata.get("root_causality_id")
            or pressure_data.get("root_causality_id")
            or pressure_id
            or action_id
        )
        event_causes = _string_list(candidate.metadata.get("caused_by"))
        if pressure_id and pressure_id not in event_causes:
            event_causes.append(pressure_id)
        if action_id not in event_causes:
            event_causes.append(action_id)
        delivery = _resolve_delivery(
            world,
            speaker,
            event_id=event_id,
            conversation_id=conversation_id,
            reply_to=str(candidate.metadata.get("reply_to", "")),
            target_ids=target_ids,
            intent=intent,
            content=content,
            claims=_claims(candidate.metadata.get("claims", [])),
            visibility=str(candidate.metadata.get("visibility", "direct")),
            language=str(candidate.metadata.get("language", "common")),
            max_range=float(candidate.metadata.get("max_range", DEFAULT_SPEECH_RANGE) or 0.0),
            witness_range=float(candidate.metadata.get("witness_range", DEFAULT_WITNESS_RANGE) or 0.0),
            urgency=float(candidate.metadata.get("urgency", 0.5) or 0.0),
            root_causality_id=root_causality_id,
            caused_by=event_causes,
            fingerprint=str(candidate.metadata.get("fingerprint", "")),
        )
        duration = max(int(candidate.metadata.get("duration_ticks", 1) or 1), 1)
        return ActionTransition(
            status="running",
            summary=f"{speaker.name} 发起{_intent_label(intent)}",
            channel="social",
            target_ids=target_ids,
            parameters={
                "speech_event_id": event_id,
                "conversation_id": conversation_id,
                "reply_to": str(candidate.metadata.get("reply_to", "")),
                "intent": intent,
                "content": content,
                "claims": _claims(candidate.metadata.get("claims", [])),
                "visibility": str(candidate.metadata.get("visibility", "direct")),
                "delivered": bool(delivery.event.get("delivered_to")),
            },
            progress=0.1,
            locks=["voice"],
            deadline_tick=world.tick + duration,
            behavior_label=_behavior_label(world, speaker, target_ids, intent),
            salience=max(0.55, float(candidate.metadata.get("urgency", 0.5) or 0.0)),
            effects=delivery.effects,
        )

    def advance(self, world: World, action: ActionInstance) -> ActionTransition:
        deadline = action.deadline_tick or action.started_tick + 1
        completed = world.tick >= deadline
        duration = max(deadline - action.started_tick, 1)
        progress = max(
            action.progress,
            min(1.0, (world.tick - action.started_tick) / duration),
        )
        speaker = world.node(action.actor_id)
        return ActionTransition(
            status="succeeded" if completed else "running",
            summary=(
                f"{speaker.name} 说完了"
                if completed
                else f"{speaker.name} 正在说话"
            ),
            channel="social",
            target_ids=action.target_ids,
            parameters=action.parameters,
            progress=progress,
            locks=["voice"],
            deadline_tick=deadline,
            behavior_label=action.behavior_label,
            salience=action.salience,
            status_reason="utterance_completed" if completed else "",
        )

    def interrupt(
        self, world: World, action: ActionInstance, reason: str
    ) -> ActionTransition:
        speaker = world.node(action.actor_id)
        return ActionTransition(
            status="interrupted",
            summary=f"{speaker.name} 的发言被中断",
            channel="social",
            target_ids=action.target_ids,
            parameters=action.parameters,
            progress=action.progress,
            locks=["voice"],
            behavior_label=action.behavior_label,
            salience=action.salience,
            status_reason=reason,
        )


def _resolve_delivery(
    world: World,
    speaker: WorldNode,
    *,
    event_id: str,
    conversation_id: str,
    reply_to: str,
    target_ids: list[str],
    intent: str,
    content: str,
    claims: list[JsonDict],
    visibility: str,
    language: str,
    max_range: float,
    witness_range: float,
    urgency: float,
    root_causality_id: str,
    caused_by: list[str],
    fingerprint: str,
) -> SpeechDelivery:
    recipients = _public_recipients(world, speaker, max_range) if visibility == "public" else target_ids
    delivered: list[str] = []
    understood: list[str] = []
    failed: list[JsonDict] = []
    for recipient_id in recipients[:MAX_SPEECH_RECIPIENTS]:
        if not world.has_node(recipient_id):
            failed.append({"id": recipient_id, "reason": "missing_recipient"})
            continue
        recipient = world.node(recipient_id)
        if recipient.attributes.get("alive", True) is False:
            failed.append({"id": recipient_id, "reason": "recipient_unavailable"})
            continue
        distance = speaker.position.distance_to(recipient.position)
        if visibility != "remote" and distance > max_range:
            failed.append(
                {"id": recipient_id, "reason": "out_of_range", "distance": distance}
            )
            continue
        delivered.append(recipient_id)
        if _understands(recipient, language):
            understood.append(recipient_id)
    witness_ids = _witness_ids(
        world, speaker, set(recipients), witness_range, language
    )
    event = {
        "schema": "ai-native-world.speech-event.v1",
        "id": event_id,
        "tick": world.tick,
        "speaker_id": speaker.id,
        "recipient_ids": recipients[:MAX_SPEECH_RECIPIENTS],
        "delivered_to": delivered,
        "understood_by": understood,
        "witness_ids": witness_ids,
        "failed_deliveries": failed,
        "intent": intent,
        "content": content,
        "claims": json_copy(claims),
        "visibility": visibility,
        "language": language,
        "conversation_id": conversation_id,
        "reply_to": reply_to,
        "fingerprint": fingerprint,
        "root_causality_id": root_causality_id,
        "caused_by": json_copy(caused_by),
        "command_authority": {
            recipient_id: _command_authority(world, speaker.id, recipient_id)
            for recipient_id in delivered
        }
        if intent == "command"
        else {},
    }
    effects: list[WorldEffect] = [effect("speech_event_add", event=event)]
    effects.append(
        effect(
            "speech_bubble_add",
            target=f"node:{speaker.id}",
            text=content,
            source="speak",
            speech_event_id=event_id,
            conversation_id=conversation_id,
            target_ids=recipients,
            ttl=max(2.5, min(8.0, 2.0 + len(content) / 18.0)),
            root_causality_id=root_causality_id,
            caused_by=caused_by,
        )
    )
    for recipient_id in understood:
        pressure_id = f"listener-pressure:{event_id}:{recipient_id}"
        effects.extend(
            [
                effect(
                    "message_receive",
                    target=f"node:{recipient_id}",
                    speech_event_id=event_id,
                    speaker_id=speaker.id,
                    content=content,
                    intent=intent,
                    claims=claims,
                    conversation_id=conversation_id,
                    understood=True,
                    root_causality_id=root_causality_id,
                    caused_by=[event_id],
                ),
                effect(
                    "memory_add",
                    target=f"node:{recipient_id}",
                    text=f"{speaker.name} 对我说：“{content}”",
                    source="speak",
                    importance=max(0.45, urgency),
                    metadata={
                        "speech_event_id": event_id,
                        "conversation_id": conversation_id,
                        "root_causality_id": root_causality_id,
                        "caused_by": [event_id],
                    },
                ),
                effect(
                    "rule_pressure_add",
                    target=f"node:{recipient_id}",
                    rule="speech_appraisal",
                    weight=max(0.25, urgency),
                    ttl=3,
                    source="speak",
                    reason=f"需要判断{speaker.name}的{_intent_label(intent)}",
                    pressure_id=pressure_id,
                    speech_event_id=event_id,
                    speaker_id=speaker.id,
                    intent=intent,
                    claims=claims,
                    conversation_id=conversation_id,
                    response_optional=True,
                    root_causality_id=root_causality_id,
                    caused_by=[event_id],
                ),
            ]
        )
    for witness_id in witness_ids:
        pressure_id = f"witness-pressure:{event_id}:{witness_id}"
        effects.extend(
            [
                effect(
                    "message_receive",
                    target=f"node:{witness_id}",
                    speech_event_id=event_id,
                    speaker_id=speaker.id,
                    content=content,
                    intent=intent,
                    conversation_id=conversation_id,
                    understood=True,
                    witness=True,
                    root_causality_id=root_causality_id,
                    caused_by=[event_id],
                ),
                effect(
                    "memory_add",
                    target=f"node:{witness_id}",
                    text=f"我听见{speaker.name}说：“{content}”",
                    source="speak",
                    importance=max(0.35, urgency * 0.8),
                    metadata={
                        "speech_event_id": event_id,
                        "conversation_id": conversation_id,
                        "witness": True,
                        "root_causality_id": root_causality_id,
                        "caused_by": [event_id],
                    },
                ),
                effect(
                    "rule_pressure_add",
                    target=f"node:{witness_id}",
                    rule="speech_appraisal",
                    weight=max(0.2, urgency * 0.8),
                    ttl=3,
                    source="speak",
                    reason=f"需要判断听到的{speaker.name}的{_intent_label(intent)}",
                    pressure_id=pressure_id,
                    speech_event_id=event_id,
                    speaker_id=speaker.id,
                    intent=intent,
                    claims=claims,
                    conversation_id=conversation_id,
                    witness=True,
                    response_optional=True,
                    root_causality_id=root_causality_id,
                    caused_by=[event_id],
                ),
            ]
        )
    return SpeechDelivery(event=event, effects=effects)


def _content_for_intent(intent: str, pressure: JsonDict) -> str:
    supplied = str(pressure.get("content", pressure.get("text", ""))).strip()
    if supplied:
        return supplied[:MAX_SPEECH_CONTENT]
    facts = [str(item) for item in pressure.get("facts", [])] if isinstance(pressure.get("facts"), list) else []
    if intent == "warn" and "north_gate_enemy_trace" in facts:
        return "北门发现敌踪，先不要独自过河。"
    topic = str(pressure.get("topic", "这件事")).strip() or "这件事"
    templates = {
        "inform": f"我需要告诉你：{topic}。",
        "ask": f"关于{topic}，你知道什么？",
        "warn": f"小心{topic}。",
        "request": f"请帮我处理{topic}。",
        "command": f"立即处理{topic}。",
        "promise": f"我会处理好{topic}。",
        "negotiate": f"我们谈谈{topic}。",
        "comfort": f"别担心{topic}，我会陪着你。",
        "persuade": f"请再考虑一下{topic}。",
        "accuse": f"你必须解释{topic}。",
        "threaten": f"如果你不停止{topic}，后果自负。",
        "deceive": f"我听说{topic}已经解决了。",
        "announce": f"所有人注意：{topic}。",
        "reply": f"关于{topic}，这是我的回答。",
    }
    return templates[intent][:MAX_SPEECH_CONTENT]


def _behavior_label(
    world: World, speaker: WorldNode, target_ids: list[str], intent: str
) -> str:
    target_name = "众人"
    if target_ids and world.has_node(target_ids[0]):
        target_name = world.node(target_ids[0]).name
    labels = {
        "warn": "示警",
        "ask": "询问",
        "command": "下令",
        "request": "请求",
        "promise": "承诺",
        "negotiate": "谈判",
        "comfort": "安慰",
        "persuade": "劝说",
        "accuse": "指责",
        "threaten": "威胁",
        "announce": "宣布",
        "reply": "回应",
        "deceive": "交谈",
        "inform": "告知",
    }
    return f"正在向{target_name}{labels[intent]}"


def _target_ids(pressure: JsonDict) -> list[str]:
    raw = pressure.get("target_ids")
    if isinstance(raw, list):
        return [_node_id(item) for item in raw if _node_id(item)][:MAX_SPEECH_RECIPIENTS]
    target = _node_id(pressure.get("target", pressure.get("to", "")))
    return [target] if target else []


def _public_recipients(world: World, speaker: WorldNode, max_range: float) -> list[str]:
    return [
        node.id
        for node in sorted(world.nodes.values(), key=lambda item: item.id)
        if node.id != speaker.id
        and node.attributes.get("alive", True) is not False
        and speaker.position.distance_to(node.position) <= max_range
    ][:MAX_SPEECH_RECIPIENTS]


def _witness_ids(
    world: World,
    speaker: WorldNode,
    recipients: set[str],
    witness_range: float,
    language: str,
) -> list[str]:
    return [
        node.id
        for node in sorted(world.nodes.values(), key=lambda item: item.id)
        if node.id != speaker.id
        and node.id not in recipients
        and node.attributes.get("alive", True) is not False
        and speaker.position.distance_to(node.position) <= witness_range
        and _understands(node, language)
    ][:MAX_SPEECH_RECIPIENTS]


def _understands(node: WorldNode, language: str) -> bool:
    languages = node.attributes.get("languages")
    if isinstance(languages, list):
        return language in {str(item) for item in languages}
    return str(node.attributes.get("language", "common")) == language


def _speaker_unavailable_reason(node: WorldNode) -> str:
    if node.attributes.get("alive", True) is False:
        return "speaker_dead"
    if node.attributes.get("conscious", True) is False:
        return "speaker_unconscious"
    if node.attributes.get("awake", True) is False:
        return "speaker_asleep"
    if node.attributes.get("muted", False) is True:
        return "speaker_muted"
    return ""


def _command_authority(
    world: World, speaker_id: str, recipient_id: str
) -> JsonDict:
    score = 0.0
    sources: list[str] = []
    speaker = world.node(speaker_id)
    if str(speaker.attributes.get("role", "")).lower() in {
        "leader",
        "chief",
        "captain",
        "首领",
        "队长",
    }:
        score += 0.5
        sources.append("speaker_role")
    for edge in world.relationships.values():
        if edge.source != speaker_id or edge.target != recipient_id:
            continue
        if edge.type in {"authority", "command", "leadership", "权威"}:
            score += max(edge.weight, 0.0)
            sources.append(edge.type)
    score = max(0.0, min(score, 1.0))
    return {"score": score, "authorized": score >= 0.5, "sources": sources}


def _recent_duplicate(world: World, fingerprint: str, cooldown: int) -> bool:
    if cooldown <= 0:
        return False
    for event in reversed(world.speech_events):
        if str(event.get("fingerprint", "")) != fingerprint:
            continue
        return world.tick - int(event.get("tick", world.tick) or world.tick) < cooldown
    return False


def _speech_fingerprint(
    speaker_id: str, target_ids: list[str], intent: str, content: str
) -> str:
    raw = json.dumps(
        [speaker_id, sorted(target_ids), intent, content],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(raw).hexdigest()[:20]


def _claims(value: object) -> list[JsonDict]:
    if not isinstance(value, list):
        return []
    result: list[JsonDict] = []
    for item in value[:12]:
        if isinstance(item, dict):
            result.append(json_copy(item))
        elif str(item):
            result.append({"proposition": str(item), "speaker_belief": "unknown"})
    return result


def _intent(value: object) -> str:
    intent = str(value).strip().lower()
    return intent if intent in SPEECH_INTENTS else "inform"


def _intent_label(intent: str) -> str:
    return {
        "warn": "警告",
        "ask": "询问",
        "command": "命令",
        "request": "请求",
        "promise": "承诺",
        "negotiate": "谈判",
        "comfort": "安慰",
        "persuade": "劝说",
        "accuse": "指责",
        "threaten": "威胁",
        "deceive": "欺骗性陈述",
        "announce": "公开宣布",
        "reply": "回应",
        "inform": "告知",
    }[intent]


def _node_id(value: object) -> str:
    text = str(value)
    return text.split(":", 1)[1] if ":" in text else text


def _string_list(value: object) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []
