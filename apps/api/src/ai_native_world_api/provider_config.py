"""Product runtime provider configuration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import os
from typing import Any

from ai_native_world_engine.core import (
    AgentProvider,
    DEFAULT_LLM_MAX_TOKENS,
    DeepSeekJsonClient,
    JsonLlmClient,
    JsonLlmProviderAdapter,
    OpenAICompatibleJsonClient,
    SovereignIntentCompiler,
    expand_rule_names,
)


JsonDict = dict[str, Any]
JsonClientFactory = Callable[[JsonDict], JsonLlmClient]


@dataclass(slots=True)
class RuntimeProviderSelection:
    mode: str
    scheduler_provider: AgentProvider | None
    metadata: JsonDict


@dataclass(slots=True)
class SovereignIntentCompilerSelection:
    mode: str
    compiler: SovereignIntentCompiler
    metadata: JsonDict


@dataclass(slots=True)
class DeterministicSovereignIntentJsonClient:
    intent_index: int = 1

    def complete(self, envelope: JsonDict) -> JsonDict:
        text = str(envelope.get("user_input", "")).strip()
        world_context = _dict(envelope.get("world_context"))
        candidate_nodes = [item for item in _list(world_context.get("candidate_nodes")) if isinstance(item, dict)]
        node_types = sorted({str(item.get("type", "")) for item in candidate_nodes if str(item.get("type", ""))})
        intent_id = f"sovereign-{max(int(self.intent_index), 1)}"
        world_flag = f"sovereign_intent_{max(int(self.intent_index), 1)}_active"
        world_id = str(world_context.get("world_id", "world"))
        return {
            "id": intent_id,
            "title": text[:24] or "用户旨意",
            "summary": f"国王视角向 {world_id} 下旨：{text}",
            "impact_level": "new_law",
            "initial_effects": [
                {
                    "type": "world_state",
                    "field": world_flag,
                    "value": True,
                }
            ],
            "dynamic_rules": [
                {
                    "id": f"{intent_id}_ripple",
                    "action": "sovereign_ripple",
                    "summary": "{node.name} 感受到新的天下旨意。",
                    "trigger": {
                        "node_types": node_types,
                        "world_flag": world_flag,
                    },
                    "score": 9.0,
                    "ttl": 3,
                    "effects": [
                        {
                            "type": "memory_add",
                            "target": "node:{node.id}",
                            "text": "{node.name} 记住了国王视角的旨意：" + text,
                            "source": "sovereign_intent",
                            "importance": 0.82,
                        },
                        {
                            "type": "action_bullet_add",
                            "target": "node:{node.id}",
                            "text": "听见旨意",
                            "source": "sovereign_intent",
                            "salience": 0.78,
                        },
                    ],
                }
            ],
            "metadata": {
                "deterministic_world_id": world_id,
                "deterministic_candidate_node_count": len(candidate_nodes),
            },
        }


def create_runtime_provider_config(
    rules: list[str] | None = None,
    runtime_provider: JsonDict | None = None,
    environ: Mapping[str, str] | None = None,
    json_client_factory: JsonClientFactory | None = None,
) -> RuntimeProviderSelection:
    env = environ or os.environ
    requested = _dict(runtime_provider)
    mode = str(requested.get("mode") or env.get("AI_NATIVE_WORLD_PROVIDER", "deterministic")).strip().lower()
    if mode in {"", "default"}:
        mode = "deterministic"
    if mode == "deterministic":
        return RuntimeProviderSelection(
            mode="deterministic",
            scheduler_provider=None,
            metadata={"mode": "deterministic", "scheduler_provider": ""},
        )
    if mode in {"openai", "openai-compatible", "custom"}:
        mode = "openai_compatible"
    if mode not in {"deepseek", "openai_compatible"}:
        raise ValueError(f"unsupported runtime provider mode: {mode}")

    env_key_name = "DEEPSEEK_API_KEY" if mode == "deepseek" else "OPENAI_API_KEY"
    api_key = str(requested.get("api_key") or env.get(env_key_name, "")).strip()
    if not api_key:
        if mode == "deepseek":
            raise ValueError("DEEPSEEK_API_KEY is required when a live runtime provider is selected")
        raise ValueError("api_key is required when a live runtime provider is selected")

    model = str(requested.get("model") or env.get("AI_NATIVE_WORLD_DEEPSEEK_MODEL", "deepseek-v4-flash"))
    default_base_url = "https://api.deepseek.com" if mode == "deepseek" else "https://api.openai.com/v1"
    base_url_env_name = (
        "AI_NATIVE_WORLD_DEEPSEEK_BASE_URL"
        if mode == "deepseek"
        else "AI_NATIVE_WORLD_OPENAI_BASE_URL"
    )
    base_url = str(requested.get("base_url") or env.get(base_url_env_name, default_base_url))
    timeout = _float(requested.get("timeout"), env.get("AI_NATIVE_WORLD_DEEPSEEK_TIMEOUT"), 60.0)
    temperature = _float(requested.get("temperature"), env.get("AI_NATIVE_WORLD_DEEPSEEK_TEMPERATURE"), 0.2)
    max_attempts = _int(requested.get("max_attempts"), env.get("AI_NATIVE_WORLD_DEEPSEEK_MAX_ATTEMPTS"), 1)
    max_tokens = _int(requested.get("max_tokens"), env.get("AI_NATIVE_WORLD_DEEPSEEK_MAX_TOKENS"), DEFAULT_LLM_MAX_TOKENS)
    deadline_seconds = _float(requested.get("deadline_seconds"), env.get("AI_NATIVE_WORLD_DEEPSEEK_DEADLINE"), timeout)
    input_cost_per_million_tokens = _float(
        requested.get("input_cost_per_million_tokens"),
        env.get("AI_NATIVE_WORLD_INPUT_COST_PER_MILLION_TOKENS"),
        0.0,
    )
    output_cost_per_million_tokens = _float(
        requested.get("output_cost_per_million_tokens"),
        env.get("AI_NATIVE_WORLD_OUTPUT_COST_PER_MILLION_TOKENS"),
        0.0,
    )
    thinking_mode = (
        str(requested.get("thinking_mode") or env.get("AI_NATIVE_WORLD_DEEPSEEK_THINKING", "disabled")).strip().lower()
        if mode == "deepseek"
        else ""
    )
    if thinking_mode not in {"", "enabled", "disabled"}:
        raise ValueError("thinking_mode must be enabled or disabled")
    name = str(requested.get("scheduler_provider") or "deepseek-json-llm-provider")
    client_config = {
        "mode": mode,
        "model": model,
        "base_url": base_url,
        "timeout": timeout,
        "temperature": temperature,
        "max_attempts": max_attempts,
        "max_tokens": max_tokens,
        "deadline_seconds": deadline_seconds,
        "input_cost_per_million_tokens": input_cost_per_million_tokens,
        "output_cost_per_million_tokens": output_cost_per_million_tokens,
        "thinking_mode": thinking_mode,
    }
    if json_client_factory is not None:
        client = json_client_factory(client_config)
    elif mode == "deepseek":
        client = DeepSeekJsonClient(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout=timeout,
            temperature=temperature,
            max_tokens=max_tokens,
            thinking_mode=thinking_mode,
        )
    else:
        client = OpenAICompatibleJsonClient(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout=timeout,
            temperature=temperature,
            max_tokens=max_tokens,
            thinking_mode=thinking_mode,
        )
    metadata = {
        **client_config,
        "scheduler_provider": name,
    }
    return RuntimeProviderSelection(
        mode=mode,
        scheduler_provider=JsonLlmProviderAdapter(
            client=client,
            name=name,
            allowed_rule_names=_allowed_rule_names(rules or ["movement"]),
            max_attempts=max_attempts,
            deadline_seconds=deadline_seconds,
            input_cost_per_million_tokens=input_cost_per_million_tokens,
            output_cost_per_million_tokens=output_cost_per_million_tokens,
        ),
        metadata=metadata,
    )


def create_sovereign_intent_compiler(
    intent_index: int = 1,
    environ: Mapping[str, str] | None = None,
    json_client_factory: JsonClientFactory | None = None,
) -> SovereignIntentCompilerSelection:
    env = environ or os.environ
    mode = str(env.get("AI_NATIVE_WORLD_SOVEREIGN_COMPILER", "deterministic")).strip().lower()
    if mode in {"", "default"}:
        mode = "deterministic"
    if mode == "deterministic":
        compiler_name = "deterministic-sovereign-intent-compiler"
        return SovereignIntentCompilerSelection(
            mode=mode,
            compiler=SovereignIntentCompiler(
                client=DeterministicSovereignIntentJsonClient(intent_index=max(int(intent_index), 1)),
                name=compiler_name,
            ),
            metadata={
                "mode": mode,
                "compiler": compiler_name,
                "client": "deterministic-sovereign-intent-json-client",
            },
        )
    if mode != "deepseek":
        raise ValueError(f"unsupported sovereign compiler mode: {mode}")

    api_key = str(env.get("DEEPSEEK_API_KEY", "")).strip()
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY is required when AI_NATIVE_WORLD_SOVEREIGN_COMPILER=deepseek")
    model = str(env.get("AI_NATIVE_WORLD_SOVEREIGN_MODEL") or env.get("AI_NATIVE_WORLD_DEEPSEEK_MODEL", "deepseek-v4-flash"))
    base_url = str(
        env.get("AI_NATIVE_WORLD_SOVEREIGN_BASE_URL")
        or env.get("AI_NATIVE_WORLD_DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    )
    timeout = _float(None, env.get("AI_NATIVE_WORLD_SOVEREIGN_TIMEOUT") or env.get("AI_NATIVE_WORLD_DEEPSEEK_TIMEOUT"), 60.0)
    temperature = _float(
        None,
        env.get("AI_NATIVE_WORLD_SOVEREIGN_TEMPERATURE") or env.get("AI_NATIVE_WORLD_DEEPSEEK_TEMPERATURE"),
        0.2,
    )
    compiler_name = "deepseek-sovereign-intent-compiler"
    client_config = {
        "mode": mode,
        "model": model,
        "base_url": base_url,
        "timeout": timeout,
        "temperature": temperature,
        "purpose": "sovereign_intent",
    }
    client = (
        json_client_factory(client_config)
        if json_client_factory is not None
        else DeepSeekJsonClient(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout=timeout,
            temperature=temperature,
        )
    )
    return SovereignIntentCompilerSelection(
        mode=mode,
        compiler=SovereignIntentCompiler(client=client, name=compiler_name),
        metadata={
            **client_config,
            "compiler": compiler_name,
            "client": "deepseek-json-client",
        },
    )


def _dict(value: object) -> JsonDict:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _allowed_rule_names(rules: list[str]) -> set[str]:
    expanded = set(expand_rule_names(rules))
    if "movement" in expanded:
        expanded.add("move")
    if "resource_transfer" in expanded:
        expanded.add("transfer")
    return expanded


def _float(primary: object, fallback: object, default: float) -> float:
    value = primary if primary not in {None, ""} else fallback
    if value in {None, ""}:
        return default
    return float(value)


def _int(primary: object, fallback: object, default: int) -> int:
    value = primary if primary not in {None, ""} else fallback
    if value in {None, ""}:
        return default
    return int(value)
