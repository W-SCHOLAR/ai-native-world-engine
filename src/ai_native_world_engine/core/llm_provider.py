"""JSON LLM provider adapter built on context packets and output boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import logging
import os
from threading import Lock
from time import perf_counter
from typing import Any, Protocol
from urllib import request

from .agent_context import compile_agent_model_context
from .action_grounding import (
    materialize_action_option,
    resolve_node_bound_action_option,
)
from .events import json_copy
from .key_character_continuity import apply_key_character_model_output
from .provider_boundary import ProviderOutputBoundary
from .providers import (
    CancellationToken,
    ProviderBudgetExhausted,
    ProviderCancelled,
    ProviderContext,
    ProviderOutput,
)
from .relationship_round import ACTIVE_NODE_LIMIT


JsonDict = dict[str, Any]

LLM_PROMPT_ENVELOPE_SCHEMA = "llm_provider_prompt_envelope_v1"
LLM_SYSTEM_PROMPT_SCHEMA = "llm_provider_system_prompt_v2"
LLM_DYNAMIC_PROMPT_SCHEMA = "llm_provider_dynamic_prompt_v2"
LLM_PROMPT_TEMPLATE_VERSION = "proactive-key-character-context-v3"
LOGGER = logging.getLogger(__name__)
DEFAULT_LLM_MAX_TOKENS = 2400


class ProviderDeadlineExceeded(TimeoutError):
    """The shared provider operation exhausted its wall-clock budget."""


class JsonLlmClient(Protocol):
    def complete(self, envelope: JsonDict) -> "JsonLlmCallResult | JsonDict": ...


@dataclass(slots=True)
class JsonLlmCallResult:
    """One call-local model result and its secret-safe transport telemetry."""

    output: JsonDict
    runtime_metadata: JsonDict = field(default_factory=dict)


@dataclass(slots=True)
class OpenAICompatibleJsonClient:
    """Small JSON client for OpenAI-compatible chat-completion providers."""

    api_key: str = field(repr=False)
    base_url: str
    model: str
    timeout: float = 60.0
    temperature: float = 0.2
    max_tokens: int = DEFAULT_LLM_MAX_TOKENS
    thinking_mode: str = ""
    network_backed: bool = field(default=True, init=False)

    def complete(
        self,
        envelope: JsonDict,
        *,
        cancellation: CancellationToken | None = None,
        timeout: float | None = None,
    ) -> JsonLlmCallResult:
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        started = perf_counter()
        payload = self.build_payload(envelope)
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        runtime_metadata: JsonDict = {
            "request_bytes": len(raw),
            "response_bytes": 0,
            "max_tokens": max(int(self.max_tokens), 1),
            "time_to_headers_ms": 0.0,
            "body_read_ms": 0.0,
            "response_json_decode_ms": 0.0,
            "provider_output_extract_ms": 0.0,
            "total_latency_ms": 0.0,
            **_prompt_layout_metadata(envelope, payload),
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        provider_request_id = envelope.get("_provider_request_id")
        if isinstance(provider_request_id, str) and provider_request_id:
            headers["Idempotency-Key"] = provider_request_id
        http_request = request.Request(
            self._chat_completions_url(),
            data=raw,
            method="POST",
            headers=headers,
        )
        network_started = perf_counter()
        transport_timeout = max(
            min(
                float(self.timeout),
                float(timeout) if timeout is not None else float(self.timeout),
                cancellation.remaining_seconds()
                if cancellation is not None
                and cancellation.remaining_seconds() is not None
                else float(self.timeout),
            ),
            0.001,
        )
        try:
            with request.urlopen(http_request, timeout=transport_timeout) as response:  # noqa: S310 - caller supplies trusted endpoint config.
                headers_received = perf_counter()
                runtime_metadata["time_to_headers_ms"] = round(
                    (headers_received - network_started) * 1000,
                    3,
                )
                body_started = perf_counter()
                response_chunks: list[bytes] = []
                while True:
                    if cancellation is not None:
                        cancellation.raise_if_cancelled()
                    try:
                        chunk = response.read(64 * 1024)
                    except TypeError:
                        # Minimal test/dummy response objects may only implement
                        # read() without the standard optional size argument.
                        chunk = response.read()
                        response_chunks.append(chunk)
                        break
                    if not chunk:
                        break
                    response_chunks.append(chunk)
                response_raw = b"".join(response_chunks)
                runtime_metadata["body_read_ms"] = round(
                    (perf_counter() - body_started) * 1000,
                    3,
                )
            runtime_metadata["response_bytes"] = len(response_raw)
            decode_started = perf_counter()
            data = json.loads(response_raw.decode("utf-8"))
            runtime_metadata["response_json_decode_ms"] = round(
                (perf_counter() - decode_started) * 1000,
                3,
            )
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            runtime_metadata.update(_response_usage_metadata(data))
            extract_started = perf_counter()
            output = extract_json_provider_output(data)
            runtime_metadata["provider_output_extract_ms"] = round(
                (perf_counter() - extract_started) * 1000,
                3,
            )
        except BaseException as exc:
            runtime_metadata["total_latency_ms"] = round(
                (perf_counter() - started) * 1000, 3
            )
            _attach_runtime_metadata(exc, runtime_metadata)
            raise
        finally:
            runtime_metadata["total_latency_ms"] = round(
                (perf_counter() - started) * 1000, 3
            )
        if os.environ.get("AI_NATIVE_WORLD_LOG_LLM_RESPONSES", "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            if not LOGGER.handlers:
                handler = logging.StreamHandler()
                handler.setFormatter(
                    logging.Formatter("%(levelname)s %(name)s %(message)s")
                )
                LOGGER.addHandler(handler)
            LOGGER.setLevel(logging.INFO)
            LOGGER.info(
                "LLM response provider=%s model=%s response=%s",
                self.__class__.__name__,
                self.model,
                json.dumps(output, ensure_ascii=False, sort_keys=True),
            )
        return JsonLlmCallResult(
            output=output, runtime_metadata=json_copy(runtime_metadata)
        )

    def build_payload(self, envelope: JsonDict) -> JsonDict:
        system_content = json.dumps(
            _stable_prompt_contract(envelope),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        user_content = json.dumps(
            _dynamic_prompt_context(envelope),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": max(int(self.max_tokens), 1),
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": system_content,
                },
                {
                    "role": "user",
                    "content": user_content,
                },
            ],
        }
        if self.thinking_mode in {"enabled", "disabled"}:
            payload["thinking"] = {"type": self.thinking_mode}
        return payload

    def _chat_completions_url(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"


class DeepSeekJsonClient(OpenAICompatibleJsonClient):
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "deepseek-v4-flash",
        base_url: str = "https://api.deepseek.com",
        timeout: float = 60.0,
        temperature: float = 0.2,
        max_tokens: int = DEFAULT_LLM_MAX_TOKENS,
        thinking_mode: str = "disabled",
    ) -> None:
        super().__init__(
            api_key=api_key or os.environ.get("DEEPSEEK_API_KEY", ""),
            base_url=base_url,
            model=model,
            timeout=timeout,
            temperature=temperature,
            max_tokens=max_tokens,
            thinking_mode=thinking_mode,
        )


def extract_json_provider_output(response: JsonDict) -> JsonDict:
    if not isinstance(response, dict):
        raise ValueError("LLM response must be a JSON object")
    if _looks_like_provider_output(response):
        return json_copy(response)
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message", {})
            if isinstance(message, dict):
                content = message.get("content", "")
                if isinstance(content, dict):
                    return json_copy(content)
                if isinstance(content, str):
                    if (
                        not content.strip()
                        and str(first.get("finish_reason", "")) == "length"
                    ):
                        raise ValueError(
                            "LLM output-token ceiling was exhausted before JSON content"
                        )
                    return _parse_json_object(content)
    raise ValueError("LLM response did not contain JSON provider output")


@dataclass(slots=True)
class JsonLlmProviderAdapter:
    client: JsonLlmClient
    name: str = "json-llm-provider"
    instructions: str = (
        "Read the agent_context_packet and return AI-Isekai style JSON with summary, node_updates, "
        "edge_updates, optional mood/strategy fields, and optional metadata. Each node_update should "
        "contain id/node_id, visible thought, and optional action_tendencies/rule_mods. Do not emit direct fact mutation."
    )
    allowed_rule_names: set[str] = field(default_factory=set)
    allowed_relationship_types: set[str] = field(default_factory=set)
    max_attempts: int = 1
    estimated_cost_per_attempt: float = 0.0
    input_cost_per_million_tokens: float = 0.0
    output_cost_per_million_tokens: float = 0.0
    deadline_seconds: float | None = None
    _context_bases: dict[str, JsonDict] = field(
        default_factory=dict, init=False, repr=False
    )
    _context_lock: Lock = field(default_factory=Lock, init=False, repr=False)

    @property
    def network_backed(self) -> bool:
        return bool(getattr(self.client, "network_backed", False))

    def observe(self, context: ProviderContext) -> ProviderOutput:
        context_packet = context.params.get("agent_context_packet")
        if not isinstance(context_packet, dict):
            raise ValueError("json LLM provider requires params.agent_context_packet")

        envelope = self.build_envelope(context, context_packet)
        provider_request_id = str(context.params.get("provider_request_id", ""))
        if provider_request_id:
            envelope["_provider_request_id"] = provider_request_id
        envelope["_provider_transport_attempt"] = max(
            int(context.params.get("provider_transport_attempt", 1) or 1),
            1,
        )
        required_active_node_count = _required_active_node_count(context_packet)
        expected_node_ids = _packet_node_ids(context_packet, "active_candidates")
        propagation_node_ids = _packet_node_ids(context_packet, "coverage_nodes")
        allowed_effect_node_ids = set(propagation_node_ids) | set(expected_node_ids)
        root_node_id = str(
            _dict(context_packet.get("constraints")).get("root_node_id", "")
        )
        if root_node_id:
            allowed_effect_node_ids.add(root_node_id)
        attempts = 0
        started = perf_counter()
        deadline_seconds = _provider_deadline_seconds(
            self.client, self.deadline_seconds
        )
        deadline_at = (
            started + deadline_seconds if deadline_seconds is not None else None
        )
        last_error: Exception | None = None
        repair_errors: list[JsonDict] = []
        attempt_runtime: list[JsonDict] = []
        output: ProviderOutput | None = None
        for attempt in range(max(int(self.max_attempts), 1)):
            if context.cancellation is not None:
                context.cancellation.raise_if_cancelled()
            attempts = attempt + 1
            attempt_envelope = _attempt_envelope(envelope, attempts, repair_errors)
            current_runtime: JsonDict = {}
            validation_started: float | None = None
            reserved_prompt_tokens = _prompt_token_upper_bound(
                self.client, attempt_envelope
            )
            reserved_completion_tokens = _client_max_tokens(self.client) or 0
            reserved_cost = self._reserved_attempt_cost(
                reserved_prompt_tokens, reserved_completion_tokens
            )
            reserved = False
            try:
                if context.attempt_budget is not None:
                    context.attempt_budget.reserve(
                        reserved_prompt_tokens,
                        reserved_completion_tokens,
                        reserved_cost,
                    )
                    reserved = True
                call_result = _complete_before_deadline(
                    self.client,
                    json_copy(attempt_envelope),
                    _remaining_deadline(deadline_at),
                    context.cancellation,
                )
                if context.cancellation is not None:
                    context.cancellation.raise_if_cancelled()
                raw_output = call_result.output
                current_runtime = json_copy(call_result.runtime_metadata)
                if context.attempt_budget is not None:
                    context.attempt_budget.record_usage(
                        int(current_runtime.get("prompt_tokens", 0) or 0),
                        int(current_runtime.get("completion_tokens", 0) or 0),
                        self._actual_attempt_cost(current_runtime),
                        reserved_prompt_tokens,
                        reserved_completion_tokens,
                        reserved_cost,
                    )
                    reserved = False
                validation_started = perf_counter()
                if _job_kind(context_packet) == "key_character_continuity":
                    output = _key_character_provider_output(
                        context,
                        context_packet,
                        raw_output,
                        source=self.name,
                        allowed_rule_names=set(self.allowed_rule_names),
                    )
                else:
                    output = ProviderOutputBoundary(
                        source=self.name,
                        allowed_rule_names=set(self.allowed_rule_names),
                        allowed_relationship_types=set(self.allowed_relationship_types),
                        required_active_node_count=required_active_node_count,
                        expected_node_ids=set(expected_node_ids)
                        if required_active_node_count is not None
                        else set(),
                        propagation_node_ids=set(propagation_node_ids)
                        if required_active_node_count is not None
                        else set(),
                        allowed_effect_node_ids=allowed_effect_node_ids
                        if required_active_node_count is not None
                        else set(),
                        groundable_action_options=[
                            json_copy(item)
                            for item in _list(
                                context_packet.get("groundable_action_options")
                            )
                            if isinstance(item, dict)
                        ],
                        provider_job_id=str(
                            _dict(context_packet.get("job")).get("id", "")
                        ),
                        source_tick=context.tick,
                    ).parse(context.world, raw_output)
                current_runtime["boundary_validation_ms"] = round(
                    (perf_counter() - validation_started) * 1000,
                    3,
                )
                self._remember_context_base(attempt_envelope)
                attempt_runtime.append(
                    {"attempt": attempts, "status": "completed", **current_runtime}
                )
                break
            except ProviderCancelled:
                if reserved and context.attempt_budget is not None:
                    # Transport may already have accepted the request. Retain
                    # the conservative reservation as chargeable rather than
                    # accidentally allowing a second over-budget request.
                    context.attempt_budget.record_usage(
                        reserved_prompt_tokens,
                        reserved_completion_tokens,
                        reserved_cost,
                        reserved_prompt_tokens,
                        reserved_completion_tokens,
                        reserved_cost,
                    )
                raise
            except ProviderBudgetExhausted as exc:
                attempt_runtime.append(
                    {
                        "attempt": attempts,
                        "status": "budget_rejected",
                        "error_type": exc.__class__.__name__,
                    }
                )
                output = ProviderOutput(
                    source=self.name,
                    summary="live provider transport budget exhausted",
                    metadata={"provider_budget": {"type": "transport_attempts"}},
                )
                break
            except Exception as exc:  # noqa: BLE001 - provider failures are converted to bounded runtime metadata.
                if reserved and context.attempt_budget is not None:
                    runtime = current_runtime or _exception_runtime_metadata(exc)
                    # Before-send failures have no request_bytes.  Release the
                    # reservation; ambiguous transport failures remain charged
                    # conservatively at their reserved upper bound.
                    sent = int(runtime.get("request_bytes", 0) or 0) > 0
                    context.attempt_budget.record_usage(
                        reserved_prompt_tokens if sent else 0,
                        reserved_completion_tokens if sent else 0,
                        reserved_cost if sent else 0.0,
                        reserved_prompt_tokens,
                        reserved_completion_tokens,
                        reserved_cost,
                    )
                    reserved = False
                runtime = current_runtime or _exception_runtime_metadata(exc)
                if (
                    runtime
                    and "boundary_validation_ms" not in runtime
                    and validation_started is not None
                ):
                    runtime["boundary_validation_ms"] = round(
                        (perf_counter() - validation_started) * 1000,
                        3,
                    )
                if not any(item.get("attempt") == attempts for item in attempt_runtime):
                    attempt_runtime.append(
                        {
                            "attempt": attempts,
                            "status": "timed_out"
                            if isinstance(exc, ProviderDeadlineExceeded)
                            else "failed",
                            "error_type": exc.__class__.__name__,
                            **runtime,
                        }
                    )
                last_error = exc
                repair_errors.append(
                    {
                        "attempt": attempts,
                        "error": str(exc),
                        "error_type": exc.__class__.__name__,
                    }
                )
                if isinstance(exc, ProviderDeadlineExceeded):
                    output = ProviderOutput(
                        source=self.name,
                        summary="live provider deadline exceeded",
                        metadata={
                            "provider_timeout": {
                                "type": "provider_deadline_exceeded",
                                "deadline_seconds": deadline_seconds,
                                "attempt": attempts,
                            }
                        },
                    )
                    break
        if output is None:
            if last_error is not None:
                try:
                    setattr(
                        last_error,
                        "provider_attempt_phases",
                        json_copy(attempt_runtime),
                    )
                except Exception:  # pragma: no cover - unusual immutable exception.
                    pass
            if attempts == 1 and last_error is not None:
                raise last_error
            failure = RuntimeError(
                f"json LLM provider failed after {attempts} attempt(s): {last_error}"
            )
            setattr(
                failure,
                "provider_attempt_phases",
                json_copy(attempt_runtime),
            )
            raise failure from last_error
        metadata = json_copy(output.metadata)
        metadata["llm_provider_adapter"] = {
            "schema": LLM_PROMPT_ENVELOPE_SCHEMA,
            "provider": self.name,
            "context_packet_schema": context_packet.get("schema", ""),
            "active_candidate_count": len(
                _list(context_packet.get("active_candidates"))
            ),
            "required_active_node_count": required_active_node_count,
            "attempts": attempts,
            "repair_attempts": len(repair_errors),
            "repair_errors": json_copy(repair_errors),
            "prompt_template_version": LLM_PROMPT_TEMPLATE_VERSION,
            "model_context": json_copy(_dict(envelope.get("_model_context_metadata"))),
        }
        metadata["provider_runtime"] = {
            "provider": self.name,
            "model": str(getattr(self.client, "model", "")),
            "thinking_mode": str(getattr(self.client, "thinking_mode", "")),
            "attempts": attempts,
            "estimated_cost": round(
                sum(
                    float(
                        item.get("estimated_cost", self.estimated_cost_per_attempt)
                        or 0.0
                    )
                    for item in attempt_runtime
                ),
                6,
            ),
            "cost_unit": "credits",
            "latency_ms": round((perf_counter() - started) * 1000, 3),
            "request_bytes": sum(
                int(item.get("request_bytes", 0) or 0) for item in attempt_runtime
            ),
            "response_bytes": sum(
                int(item.get("response_bytes", 0) or 0) for item in attempt_runtime
            ),
            "max_tokens": _client_max_tokens(self.client),
            "attempt_phases": json_copy(attempt_runtime),
            "deadline_seconds": deadline_seconds,
            "status": "timed_out"
            if isinstance(last_error, ProviderDeadlineExceeded)
            else "completed",
        }
        return ProviderOutput(
            source=output.source,
            summary=output.summary,
            effects=output.effects,
            metadata=metadata,
        )

    def _reserved_attempt_cost(
        self, prompt_tokens: int, completion_tokens: int
    ) -> float:
        usage_cost = (
            max(int(prompt_tokens), 0)
            * max(float(self.input_cost_per_million_tokens), 0.0)
            + max(int(completion_tokens), 0)
            * max(float(self.output_cost_per_million_tokens), 0.0)
        ) / 1_000_000
        return max(float(self.estimated_cost_per_attempt), 0.0, usage_cost)

    def _actual_attempt_cost(self, runtime: JsonDict) -> float:
        prompt = int(runtime.get("prompt_tokens", 0) or 0)
        completion = int(runtime.get("completion_tokens", 0) or 0)
        calculated = (
            prompt * max(float(self.input_cost_per_million_tokens), 0.0)
            + completion * max(float(self.output_cost_per_million_tokens), 0.0)
        ) / 1_000_000
        cost = max(float(self.estimated_cost_per_attempt), 0.0, calculated)
        runtime["estimated_cost"] = round(cost, 6)
        return cost

    def build_envelope(
        self, context: ProviderContext, context_packet: JsonDict
    ) -> JsonDict:
        model_context_packet, model_context_metadata = compile_agent_model_context(
            context_packet
        )
        delivered_context, delivery_metadata = self._context_delivery(
            model_context_packet, model_context_metadata
        )
        if _job_kind(context_packet) == "key_character_continuity":
            target_node_id = _key_character_target_id(context_packet)
            return {
                "schema": LLM_PROMPT_ENVELOPE_SCHEMA,
                "provider": self.name,
                "tick": context.tick,
                "job_kind": "key_character_continuity",
                "instructions": (
                    "Act as exactly one proactive AI-Isekai protagonist agent on its mandatory cognition heartbeat. "
                    "The protagonist is an endogenous source of world change, not a passive event listener. Read the target character, "
                    "L0 decision state, L1 episodic evidence, L2 continuity state, peer cards, relationship graph, "
                    "and world/domain summary in context_packet. Return one JSON object for the target_character_id "
                    "declared in the dynamic context. Provide visible thought, not hidden reasoning. Preserve long-term identity, "
                    "but assess the previous action from evidence, state concrete progress since the prior heartbeat, and launch one "
                    "proactive initiative intended to influence named nearby people and propagate through relationship networks. "
                    "Stable long-term goals are allowed; repeating the prior progress text is invalid. All assessment, progress, "
                    "initiative, selected-action weight/TTL/reason fields in expected_output are mandatory. The initiative is an "
                    "intention: select a grounded option and let local rules and relationship agents determine its real impact. "
                    "Do not emit node_updates, edge_updates, direct effects, or world fact mutations."
                ),
                "context_packet": delivered_context,
                "expected_output": {
                    "summary": "string",
                    "character_id": target_node_id,
                    "insight": "visible first-person mind summary",
                    "self_narrative": "stable self understanding",
                    "personality_profile": {
                        "values": ["string"],
                        "fears": ["string"],
                        "desires": ["string"],
                        "boundaries": ["string"],
                        "bonds": ["string"],
                    },
                    "goal_status": "continue|adjust|abandon",
                    "goal": "string",
                    "previous_action_assessment": {
                        "status": "succeeded|partial|blocked|failed|no_feedback",
                        "evidence": "specific visible evidence or absence of feedback",
                        "consequence": "how that result changes the present decision",
                    },
                    "progress_delta": "specific new progress since the previous heartbeat",
                    "plan_reason": "string",
                    "plan_steps": ["string"],
                    "current_step": "string",
                    "grounded_rule": "registered rule name",
                    "selected_action_option_id": "one option_id for the target character",
                    "rule_weight": 0.0,
                    "rule_ttl": 4,
                    "rule_reason": "short non-empty reason",
                    "initiative": {
                        "action": "one concrete proactive action",
                        "target_node_ids": [
                            "one to five ids from decision_context.influence_nodes or continuity_context.peers"
                        ],
                        "expected_change": "specific local or institutional change",
                        "propagation_goal": "how people and relationship networks may carry the initiative",
                        "impact_scale": 0.8,
                    },
                    "peer_interactions": [
                        {
                            "target": "key character id",
                            "stance": "string",
                            "status": "string",
                            "summary": "string",
                        }
                    ],
                    "commitments": [
                        {"target": "node id", "status": "pending", "summary": "string"}
                    ],
                    "metadata": "object",
                },
                "_model_context_metadata": model_context_metadata,
                "_context_delivery": delivery_metadata,
                "_audit_job": json_copy(_dict(context_packet.get("job"))),
            }
        envelope = {
            "schema": LLM_PROMPT_ENVELOPE_SCHEMA,
            "provider": self.name,
            "tick": context.tick,
            "instructions": self.instructions,
            "context_packet": delivered_context,
            "expected_output": {
                "summary": "short string, no more than 80 characters",
                "node_updates": [
                    {
                        "id": "node id",
                        "thought": "one visible first-person thought; hard generation budget: 36-48 Chinese characters",
                        "selected_action_option_id": "one option_id from this node's action_options_by_node entry",
                        "action_weight": 0.5,
                        "action_ttl": 3,
                        "action_reason": "at most 8 Chinese characters",
                    }
                ],
                "edge_updates": [
                    {
                        "from": "node id",
                        "to": "node id",
                        "relation": "trust",
                        "delta": 0.1,
                        "ttl": 16,
                        "reason": "at most 8 Chinese characters",
                    }
                ],
                "metadata": "object",
            },
            "_model_context_metadata": model_context_metadata,
            "_context_delivery": delivery_metadata,
            "_audit_job": json_copy(_dict(context_packet.get("job"))),
        }
        required_active_node_count = _required_active_node_count(context_packet)
        if required_active_node_count is not None:
            allowed_rules = sorted(self.allowed_rule_names)
            envelope["instructions"] = (
                f"{self.instructions} This is a relationship-network round: return node_updates for exactly "
                f"{required_active_node_count} valid, distinct node ids that each appear in "
                "context_packet.decision_context.action_options_by_node. Each returned node must include exactly one visible core "
                "thought, exactly one node-bound selected_action_option_id from that node's "
                "decision_context.action_options_by_node entry, action_weight, action_ttl, and a non-empty "
                "action_reason. All six fields are mandatory for every returned node; action_weight must be "
                "between 0 and 1, action_ttl must be between 2 and 7, and action_reason must be no more than "
                "8 Chinese characters. All ten returned active nodes must select a complete action intention. "
                "Keep every thought strictly within 36-48 Chinese characters and "
                "do not expand it with explanation or hidden reasoning. "
                "observation-only updates are invalid. Do not return thought_bubbles, "
                "bubble timing, ripple prose, direct effects, or hidden reasoning. The local engine creates the "
                "six visible slices and three ripple responses. When current_pressures_by_node contains origin "
                "key_character_influence, act as the group brain: each affected node may amplify, resist, redirect, "
                "or reinterpret that initiative through its own selected grounded action. Preserve initiative causality "
                "in the thought or action reason. Return no more than 12 edge_updates. All required "
                "node updates must survive validation; an incomplete round is rejected."
            )
            envelope["expected_output"]["required_active_node_count"] = (
                required_active_node_count
            )
            envelope["expected_output"]["allowed_rule_names"] = allowed_rules
        return envelope

    def _context_delivery(
        self, compiled: JsonDict, metadata: JsonDict
    ) -> tuple[JsonDict, JsonDict]:
        """Build a full packet unless the transport explicitly supports refs.

        OpenAI-compatible HTTP endpoints do not implicitly retain a prior
        prompt, so their default is always full. A specialised provider must
        advertise ``supports_context_references`` before a compact envelope is
        ever emitted.
        """

        versions = json_copy(_dict(metadata.get("section_versions")))
        scope = _context_scope(compiled)
        base_id = _context_base_id(scope, compiled)
        supports_references = bool(
            getattr(self.client, "supports_context_references", False)
        )
        if not supports_references:
            return json_copy(compiled), {
                "mode": "full",
                "scope": scope,
                "base_id": base_id,
                "section_versions": versions,
                "reason": "provider_capability_absent",
            }
        with self._context_lock:
            previous = json_copy(self._context_bases.get(scope, {}))
        previous_versions = _dict(previous.get("section_versions"))
        if not previous:
            return json_copy(compiled), {
                "mode": "full",
                "scope": scope,
                "base_id": base_id,
                "section_versions": versions,
                "reason": "first_delivery",
            }
        section_fields = {
            "l0_decision": "decision_context",
            "l1_evidence": "episodic_evidence",
            "l2_continuity": "continuity_context",
        }
        changed = {
            section: json_copy(compiled.get(field))
            for section, field in section_fields.items()
            if str(versions.get(section, "")) != str(previous_versions.get(section, ""))
        }
        return {
            "schema": "agent_model_context_delta_v1",
            "projection": str(compiled.get("projection", "")),
            "job": json_copy(_dict(compiled.get("job"))),
            "context_reference": {
                "base_id": str(previous.get("base_id", "")),
                "base_section_versions": previous_versions,
            },
            "section_versions": versions,
            "changed_sections": changed,
        }, {
            "mode": "delta",
            "scope": scope,
            "base_id": str(previous.get("base_id", "")),
            "section_versions": versions,
            "changed_sections": sorted(changed),
        }

    def _remember_context_base(self, envelope: JsonDict) -> None:
        delivery = _dict(envelope.get("_context_delivery"))
        if str(delivery.get("mode", "")) not in {"full", "delta"}:
            return
        scope = str(delivery.get("scope", ""))
        if not scope:
            return
        with self._context_lock:
            self._context_bases[scope] = {
                "base_id": str(delivery.get("base_id", "")),
                "section_versions": json_copy(_dict(delivery.get("section_versions"))),
            }


def _stable_prompt_contract(envelope: JsonDict) -> JsonDict:
    job_kind = str(
        envelope.get("job_kind", _job_kind(_dict(envelope.get("context_packet"))))
    )
    expected_output = json_copy(_dict(envelope.get("expected_output")))
    if job_kind == "key_character_continuity" and "character_id" in expected_output:
        expected_output["character_id"] = (
            "exact target_character_id from dynamic context"
        )
    return {
        "schema": LLM_SYSTEM_PROMPT_SCHEMA,
        "prompt_template_version": LLM_PROMPT_TEMPLATE_VERSION,
        "envelope_schema": str(envelope.get("schema", LLM_PROMPT_ENVELOPE_SCHEMA)),
        "provider": str(envelope.get("provider", "")),
        "job_kind": job_kind,
        "instructions": str(envelope.get("instructions", "Return JSON only.")),
        "expected_output": expected_output,
        "response_contract": "Return exactly one JSON object and no prose outside it.",
    }


def _dynamic_prompt_context(envelope: JsonDict) -> JsonDict:
    dynamic: JsonDict = {
        "schema": LLM_DYNAMIC_PROMPT_SCHEMA,
        "job_kind": str(
            envelope.get("job_kind", _job_kind(_dict(envelope.get("context_packet"))))
        ),
        "context_packet": json_copy(_dict(envelope.get("context_packet"))),
    }
    for key, value in envelope.items():
        if key in {
            "schema",
            "provider",
            "instructions",
            "expected_output",
            "job_kind",
            "context_packet",
        } or key.startswith("_"):
            continue
        dynamic[str(key)] = json_copy(value)
    return dynamic


def _prompt_layout_metadata(envelope: JsonDict, payload: JsonDict) -> JsonDict:
    messages = _list(payload.get("messages"))
    system_content = str(_dict(messages[0]).get("content", "")) if messages else ""
    user_content = (
        str(_dict(messages[1]).get("content", "")) if len(messages) > 1 else ""
    )
    model_metadata = _dict(envelope.get("_model_context_metadata"))
    section_bytes = _dict(model_metadata.get("section_bytes"))
    return {
        "prompt_template_version": LLM_PROMPT_TEMPLATE_VERSION,
        "stable_prefix_bytes": len(system_content.encode("utf-8")),
        "stable_prefix_sha256": sha256(system_content.encode("utf-8")).hexdigest(),
        "dynamic_message_bytes": len(user_content.encode("utf-8")),
        "model_context_projection": str(model_metadata.get("projection", "")),
        "model_context_bytes": int(model_metadata.get("model_context_bytes", 0) or 0),
        "model_context_section_bytes": json_copy(section_bytes),
        "model_context_section_versions": json_copy(
            _dict(model_metadata.get("section_versions"))
        ),
        "model_context_l0_bytes": int(section_bytes.get("l0_decision", 0) or 0),
        "model_context_l1_bytes": int(section_bytes.get("l1_evidence", 0) or 0),
        "model_context_l2_bytes": int(section_bytes.get("l2_continuity", 0) or 0),
        "evidence_candidate_count": int(
            model_metadata.get("evidence_candidate_count", 0) or 0
        ),
        "evidence_selected_count": int(
            model_metadata.get("evidence_selected_count", 0) or 0
        ),
        "evidence_duplicate_suppressed_count": int(
            model_metadata.get("evidence_duplicate_suppressed_count", 0) or 0
        ),
    }


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict(value: Any) -> JsonDict:
    return value if isinstance(value, dict) else {}


def _attach_runtime_metadata(exc: BaseException, runtime: JsonDict) -> None:
    try:
        setattr(exc, "provider_runtime_metadata", json_copy(runtime))
    except Exception:  # pragma: no cover - unusual immutable third-party exception.
        return


def _exception_runtime_metadata(exc: BaseException) -> JsonDict:
    value = getattr(exc, "provider_runtime_metadata", None)
    return json_copy(value) if isinstance(value, dict) else {}


def _client_max_tokens(client: JsonLlmClient) -> int | None:
    value = getattr(client, "max_tokens", None)
    return max(int(value), 1) if isinstance(value, (int, float)) else None


def _prompt_token_upper_bound(client: JsonLlmClient, envelope: JsonDict) -> int:
    """Return a conservative, request-before-send token reservation.

    Provider-reported prompt usage only arrives after a billable request.  Raw
    UTF-8 byte length is a valid upper bound for ordinary BPE tokenization;
    the small fixed allowance covers chat framing and provider control tokens.
    This intentionally favours rejecting a request before transport over
    permitting a hard budget overrun.
    """

    build_payload = getattr(client, "build_payload", None)
    if callable(build_payload):
        payload = build_payload(json_copy(envelope))
    else:
        payload = {
            "messages": [
                {
                    "role": "system",
                    "content": json.dumps(
                        _stable_prompt_contract(envelope), ensure_ascii=False
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        _dynamic_prompt_context(envelope), ensure_ascii=False
                    ),
                },
            ]
        }
    return (
        len(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        + 64
    )


def _context_scope(compiled: JsonDict) -> str:
    job = _dict(compiled.get("job"))
    return ":".join(
        (
            str(compiled.get("projection", "")),
            str(job.get("kind", "")),
            str(job.get("graph_key", "")),
            str(job.get("target_node_id", job.get("root_node_id", ""))),
        )
    )


def _context_base_id(scope: str, compiled: JsonDict) -> str:
    raw = json.dumps(
        compiled, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return f"ctx-{sha256(f'{scope}:{raw}'.encode('utf-8')).hexdigest()[:24]}"


def _provider_deadline_seconds(
    client: JsonLlmClient, configured: float | None
) -> float | None:
    value = configured if configured is not None else getattr(client, "timeout", None)
    if not isinstance(value, (int, float)):
        return None
    return max(float(value), 0.001)


def _remaining_deadline(deadline_at: float | None) -> float | None:
    if deadline_at is None:
        return None
    remaining = deadline_at - perf_counter()
    if remaining <= 0:
        raise ProviderDeadlineExceeded("live provider deadline exhausted")
    return remaining


def _complete_before_deadline(
    client: JsonLlmClient,
    envelope: JsonDict,
    remaining_seconds: float | None,
    cancellation: CancellationToken | None,
) -> JsonLlmCallResult:
    if cancellation is not None:
        cancellation.raise_if_cancelled()
    started = perf_counter()
    cooperative_complete = getattr(client, "complete_with_context", None)
    if callable(cooperative_complete):
        value = cooperative_complete(
            envelope,
            cancellation=cancellation,
            timeout=remaining_seconds,
        )
    elif isinstance(client, OpenAICompatibleJsonClient):
        value = client.complete(
            envelope,
            cancellation=cancellation,
            timeout=remaining_seconds,
        )
    else:
        value = client.complete(envelope)
    if cancellation is not None:
        cancellation.raise_if_cancelled()
    if remaining_seconds is not None and perf_counter() - started >= remaining_seconds:
        raise ProviderDeadlineExceeded(
            f"live provider exceeded shared deadline of {remaining_seconds:.3f}s"
        )
    return _normalize_call_result(value)


def _normalize_call_result(value: Any) -> JsonLlmCallResult:
    if isinstance(value, JsonLlmCallResult):
        return JsonLlmCallResult(
            output=json_copy(value.output),
            runtime_metadata=json_copy(value.runtime_metadata),
        )
    if isinstance(value, dict):
        return JsonLlmCallResult(output=json_copy(value))
    raise ValueError("LLM client must return a JSON object or JsonLlmCallResult")


def _packet_node_ids(context_packet: JsonDict, field_name: str) -> list[str]:
    return [
        str(item.get("id", ""))
        for item in _list(context_packet.get(field_name))
        if isinstance(item, dict) and str(item.get("id", ""))
    ]


def _required_active_node_count(context_packet: JsonDict) -> int | None:
    job = context_packet.get("job")
    if isinstance(job, dict) and job.get("kind") == "relationship_round":
        return ACTIVE_NODE_LIMIT
    return None


def _job_kind(context_packet: JsonDict) -> str:
    return str(_dict(context_packet.get("job")).get("kind", ""))


def _key_character_target_id(context_packet: JsonDict) -> str:
    constraints = _dict(context_packet.get("constraints"))
    target_node_id = str(constraints.get("target_node_id", ""))
    if target_node_id:
        return target_node_id
    candidates = _packet_node_ids(context_packet, "active_candidates")
    if len(candidates) != 1:
        raise ValueError("key-character provider requires exactly one target candidate")
    return candidates[0]


def _key_character_provider_output(
    context: ProviderContext,
    context_packet: JsonDict,
    raw_output: JsonDict,
    source: str,
    allowed_rule_names: set[str],
) -> ProviderOutput:
    target_node_id = _key_character_target_id(context_packet)
    payload = (
        _dict(raw_output.get("key_character"))
        if isinstance(raw_output.get("key_character"), dict)
        else raw_output
    )
    _validate_key_character_agency_output(context_packet, target_node_id, payload)
    selected_option_id = str(payload.get("selected_action_option_id", ""))
    options = [
        json_copy(item)
        for item in _list(context_packet.get("groundable_action_options"))
        if isinstance(item, dict)
    ]
    selected_option, option_repair = resolve_node_bound_action_option(
        options,
        selected_option_id,
        target_node_id,
        source_tick=context.tick,
        intent_text=" ".join(
            str(value)
            for value in (
                payload.get("rule_reason", ""),
                payload.get("current_step", ""),
                payload.get("insight", ""),
            )
            if value
        ),
        preferred_rule=str(payload.get("grounded_rule", "")),
    )
    grounded_pressure: JsonDict | None = None
    if options and not selected_option_id:
        raise ValueError(
            "key-character provider with groundable options must select one option_id"
        )
    if selected_option:
        selected_option_id = str(selected_option.get("option_id", ""))
        grounded_pressure = materialize_action_option(
            selected_option,
            weight=float(payload.get("rule_weight", 0.52) or 0.52),
            ttl=int(payload.get("rule_ttl", 4) or 4),
            reason=str(
                payload.get("rule_reason")
                or payload.get("current_step")
                or "key character plan"
            ),
        )
        job_id = str(_dict(context_packet.get("job")).get("id", ""))
        seed = f"{job_id}:{context.tick}:{selected_option_id}"
        grounded_pressure.update(
            {
                "pressure_id": f"pressure-{sha256(seed.encode('utf-8')).hexdigest()[:20]}",
                "provider_job_id": job_id,
                "source_tick": context.tick,
                "observation_deadline_tick": context.tick
                + max(int(grounded_pressure.get("ttl", 4) or 4), 2),
            }
        )
    elif selected_option_id:
        raise ValueError(
            "key-character provider selected an unavailable groundable action option"
        )
    result = apply_key_character_model_output(
        context.world,
        target_node_id,
        raw_output,
        source=source,
        allowed_rule_names=allowed_rule_names,
        grounded_pressure=grounded_pressure,
        require_grounded_pressure=True,
    )
    metadata = (
        json_copy(raw_output.get("metadata", {}))
        if isinstance(raw_output.get("metadata"), dict)
        else {}
    )
    metadata["provider_output_boundary"] = {
        "schema": "key_character_output_boundary_v1",
        "target_node_id": target_node_id,
        "accepted_effect_count": len(result.effects),
        "action_option_repair_count": 1 if option_repair is not None else 0,
        **(
            {"action_option_repairs": [json_copy(option_repair)]}
            if option_repair is not None
            else {}
        ),
    }
    metadata["key_character_continuity"] = result.to_metadata()
    return ProviderOutput(
        source=source,
        summary=str(raw_output.get("summary", "")).strip()
        or f"key character continuity updated {target_node_id}",
        effects=result.effects,
        metadata=metadata,
    )


def _validate_key_character_agency_output(
    context_packet: JsonDict,
    target_node_id: str,
    payload: JsonDict,
) -> None:
    required_text = ("insight", "goal", "current_step", "progress_delta")
    missing_text = [
        field_name
        for field_name in required_text
        if not str(payload.get(field_name, "")).strip()
    ]
    if missing_text:
        raise ValueError(
            f"key-character provider requires non-empty agency fields: {missing_text}"
        )

    assessment = _dict(payload.get("previous_action_assessment"))
    allowed_assessment_statuses = {
        "succeeded",
        "partial",
        "blocked",
        "failed",
        "no_feedback",
    }
    if (
        str(assessment.get("status", "")) not in allowed_assessment_statuses
        or not str(assessment.get("evidence", "")).strip()
        or not str(assessment.get("consequence", "")).strip()
    ):
        raise ValueError(
            "key-character provider requires previous_action_assessment with "
            "valid status, evidence, and consequence"
        )

    initiative = _dict(payload.get("initiative"))
    required_initiative_text = ("action", "expected_change", "propagation_goal")
    if any(
        not str(initiative.get(field_name, "")).strip()
        for field_name in required_initiative_text
    ):
        raise ValueError(
            "key-character provider requires initiative action, expected_change, "
            "and propagation_goal"
        )
    impact_scale = float(initiative.get("impact_scale", -1.0))
    if not 0.0 <= impact_scale <= 1.0:
        raise ValueError(
            "key-character initiative impact_scale must be between 0 and 1"
        )
    target_ids = [
        str(node_id)
        for node_id in _list(initiative.get("target_node_ids"))
        if str(node_id)
    ]
    if not 1 <= len(target_ids) <= 5 or len(set(target_ids)) != len(target_ids):
        raise ValueError(
            "key-character initiative requires one to five distinct target_node_ids"
        )
    allowed_target_ids = {
        str(item.get("node_id", item.get("id", "")))
        for field_name in ("influence_context", "key_character_peers")
        for item in _list(context_packet.get(field_name))
        if isinstance(item, dict) and str(item.get("node_id", item.get("id", "")))
    }
    if not set(target_ids) <= allowed_target_ids:
        raise ValueError(
            "key-character initiative target_node_ids must come from current "
            "influence nodes or peers"
        )

    active = next(
        (
            item
            for item in _list(context_packet.get("active_candidates"))
            if isinstance(item, dict) and str(item.get("id", "")) == target_node_id
        ),
        {},
    )
    previous_progress = str(
        _dict(_dict(active).get("key_character")).get("last_progress_delta", "")
    ).strip()
    progress_delta = str(payload.get("progress_delta", "")).strip()
    if previous_progress and _normalized_agency_text(
        previous_progress
    ) == _normalized_agency_text(progress_delta):
        raise ValueError(
            "key-character progress_delta must advance beyond the prior heartbeat"
        )

    options = [
        item
        for item in _list(context_packet.get("groundable_action_options"))
        if isinstance(item, dict) and str(item.get("node_id", "")) == target_node_id
    ]
    if not options:
        return
    missing_action_fields = [
        field_name
        for field_name in (
            "selected_action_option_id",
            "rule_weight",
            "rule_ttl",
            "rule_reason",
        )
        if field_name not in payload
        or (
            field_name in {"selected_action_option_id", "rule_reason"}
            and not str(payload.get(field_name, "")).strip()
        )
    ]
    if missing_action_fields:
        raise ValueError(
            "key-character provider requires complete grounded action fields: "
            f"{missing_action_fields}"
        )
    weight = float(payload.get("rule_weight", 0.0))
    ttl = int(payload.get("rule_ttl", 0))
    if not 0.0 <= weight <= 1.0 or not 2 <= ttl <= 7:
        raise ValueError(
            "key-character grounded action weight must be 0..1 and TTL must be 2..7"
        )


def _normalized_agency_text(value: Any) -> str:
    return " ".join(str(value).split()).casefold()


def _attempt_envelope(
    envelope: JsonDict, attempt: int, repair_errors: list[JsonDict]
) -> JsonDict:
    next_envelope = json_copy(envelope)
    next_envelope["attempt"] = attempt
    if repair_errors:
        job_kind = str(
            envelope.get("job_kind", _job_kind(_dict(envelope.get("context_packet"))))
        )
        repair_instruction = (
            "Return corrected JSON for the same target key character and continuity schema; do not emit "
            "relationship node_updates, direct effects, or world mutations."
            if job_kind == "key_character_continuity"
            else (
                "Return corrected JSON. Keep effects as structured pressure or display payloads only; "
                "prefer node_updates/edge_updates for AI-Isekai style output; do not emit direct world mutation effects. "
                "For a relationship-network round, return exactly the required number of valid, distinct node updates."
            )
        )
        next_envelope["repair_feedback"] = {
            "previous_errors": json_copy(repair_errors),
            "instructions": repair_instruction,
        }
    return next_envelope


def _looks_like_provider_output(value: JsonDict) -> bool:
    return any(
        key in value for key in ("summary", "effects", "node_updates", "edge_updates")
    )


def _parse_json_object(text: str) -> JsonDict:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        parsed = _repair_premature_root_close(stripped, exc)
        if parsed is not None:
            return parsed
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(stripped[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("LLM JSON content must be an object")
    return parsed


def _repair_premature_root_close(
    text: str, error: json.JSONDecodeError
) -> JsonDict | None:
    """Repair one exact provider typo: a root `}` immediately before more fields."""

    position = int(error.pos)
    if (
        error.msg != "Extra data"
        or position <= 0
        or position >= len(text)
        or text[position - 1] != "}"
        or text[position] != ","
        or not text.endswith("}")
    ):
        return None
    candidate = f"{text[: position - 1]}{text[position:]}"
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _response_usage_metadata(response: JsonDict) -> JsonDict:
    choices = _list(response.get("choices"))
    first = _dict(choices[0]) if choices and isinstance(choices[0], dict) else {}
    message = _dict(first.get("message"))
    usage = _dict(response.get("usage"))
    completion_details = _dict(usage.get("completion_tokens_details"))
    prompt_details = _dict(usage.get("prompt_tokens_details"))
    reasoning = message.get("reasoning_content")
    return {
        "finish_reason": str(first.get("finish_reason", "")),
        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        "reasoning_tokens": int(completion_details.get("reasoning_tokens", 0) or 0),
        "reasoning_chars": len(reasoning) if isinstance(reasoning, str) else 0,
        "prompt_cache_hit_tokens": int(
            usage.get("prompt_cache_hit_tokens", prompt_details.get("cached_tokens", 0))
            or 0
        ),
        "prompt_cache_miss_tokens": int(usage.get("prompt_cache_miss_tokens", 0) or 0),
    }
