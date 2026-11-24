import { useEffect, useState } from "react";

import {
  DEFAULT_RUNTIME_PROVIDER_CONFIG,
  productScenarioLabel,
  type ProductScenarioId,
  type RuntimeProviderConfig,
  type RuntimeProviderMode,
} from "./runtimeTypes";
import type { Scenario } from "../types/contracts";

type ProviderConfigDialogProps = {
  initialConfig?: RuntimeProviderConfig | null;
  initialScenario: ProductScenarioId;
  scenarios: Scenario[];
  scenarioError?: string;
  onSubmit: (scenario: ProductScenarioId, config: RuntimeProviderConfig) => void;
};

export function ProviderConfigDialog({
  initialConfig,
  initialScenario,
  scenarios,
  scenarioError = "",
  onSubmit,
}: ProviderConfigDialogProps) {
  const [config, setConfig] = useState<RuntimeProviderConfig>(initialConfig ?? DEFAULT_RUNTIME_PROVIDER_CONFIG);
  const [scenario, setScenario] = useState<ProductScenarioId>(initialScenario);
  const liveProvider = config.mode !== "deterministic";
  const serverKeyConfigured = import.meta.env.VITE_AI_NATIVE_WORLD_SERVER_PROVIDER_KEY === "1";
  const scenarioAvailable = scenarios.some((item) => item.id === scenario);

  useEffect(() => {
    if (scenarioAvailable || scenarios.length === 0) return;
    setScenario(scenarios[0].id as ProductScenarioId);
  }, [scenarioAvailable, scenarios]);

  useEffect(() => {
    setScenario(initialScenario);
  }, [initialScenario]);

  function update<K extends keyof RuntimeProviderConfig>(field: K, value: RuntimeProviderConfig[K]) {
    setConfig((current) => ({ ...current, [field]: value }));
  }

  function selectMode(mode: RuntimeProviderMode) {
    setConfig((current) => ({
      ...current,
      mode,
      base_url: mode === "deepseek" ? (current.base_url || DEFAULT_RUNTIME_PROVIDER_CONFIG.base_url) : current.base_url,
      model: mode === "deepseek" ? (current.model || DEFAULT_RUNTIME_PROVIDER_CONFIG.model) : current.model,
    }));
  }

  function submit(event: { preventDefault(): void }) {
    event.preventDefault();
    onSubmit(scenario, {
      ...config,
      base_url: config.base_url.trim(),
      api_key: config.api_key.trim(),
      model: config.model.trim(),
      max_tokens: Math.max(Math.round(config.max_tokens), 1),
    });
  }

  return (
    <main className="provider-config-shell">
      <div className="provider-config-backdrop" />
      <section className="provider-config-dialog" role="dialog" aria-modal="true" aria-labelledby="provider-config-title">
        <div className="provider-config-kicker">ENGINE RUNTIME SETUP</div>
        <h1 id="provider-config-title">连接真实大模型</h1>
        <p className="provider-config-intro">
          先选择要进入的世界，再配置 Provider。提交后会显示加载页；首个模型思考进入世界投影后，即展示原本持续运行的场景。
        </p>
        <form onSubmit={submit}>
          <label className="provider-config-field">
            <span>世界场景</span>
            <select
              aria-label="世界场景"
              value={scenario}
              disabled={scenarios.length === 0}
              onChange={(event: { currentTarget: HTMLSelectElement }) => setScenario(event.currentTarget.value as ProductScenarioId)}
            >
              {scenarios.map((item) => (
                <option key={item.id} value={item.id}>
                  {productScenarioLabel(item.id as ProductScenarioId)}
                </option>
              ))}
            </select>
          </label>
          {scenarioError ? <p className="provider-config-error" role="alert">{scenarioError}</p> : null}
          <label className="provider-config-field">
            <span>Provider</span>
            <select
              aria-label="模型 Provider"
              value={config.mode}
              onChange={(event: { currentTarget: HTMLSelectElement }) => selectMode(event.currentTarget.value as RuntimeProviderMode)}
            >
              <option value="deepseek">DeepSeek</option>
              <option value="openai_compatible">OpenAI-compatible API</option>
              <option value="deterministic">本地确定性调试</option>
            </select>
          </label>
          <label className="provider-config-field">
            <span>API 地址 / 路径</span>
            <input
              aria-label="API 地址或路径"
              type="url"
              value={config.base_url}
              disabled={!liveProvider}
              placeholder="https://api.deepseek.com"
              onChange={(event: { currentTarget: HTMLInputElement }) => update("base_url", event.currentTarget.value)}
            />
          </label>
          <label className="provider-config-field">
            <span>API Key</span>
            <input
              aria-label="API Key"
              type="password"
              autoComplete="off"
              value={config.api_key}
              disabled={!liveProvider}
              placeholder={liveProvider ? (serverKeyConfigured ? "本地服务端已配置，可留空" : "sk-…") : "确定性 Provider 不需要 Key"}
              onChange={(event: { currentTarget: HTMLInputElement }) => update("api_key", event.currentTarget.value)}
            />
          </label>
          <label className="provider-config-field">
            <span>模型名称</span>
            <input
              aria-label="模型名称"
              type="text"
              value={config.model}
              disabled={!liveProvider}
              placeholder="deepseek-v4-flash"
              onChange={(event: { currentTarget: HTMLInputElement }) => update("model", event.currentTarget.value)}
            />
          </label>
          <label className="provider-config-field">
            <span>最大输出 Tokens</span>
            <input
              aria-label="最大输出 Tokens"
              type="number"
              min="1"
              step="1"
              value={config.max_tokens}
              disabled={!liveProvider}
              onChange={(event: { currentTarget: HTMLInputElement }) => update("max_tokens", Number(event.currentTarget.value))}
            />
          </label>
          <div className="provider-config-actions">
            <button
              type="submit"
              disabled={!scenarioAvailable || (liveProvider && (!config.base_url.trim() || (!config.api_key.trim() && !serverKeyConfigured) || !config.model.trim()))}
            >
              {liveProvider ? "启动模型并进入世界" : "使用本地 Provider 启动"}
            </button>
          </div>
        </form>
        <p className="provider-config-notice">
          API Key 只保存在当前浏览器会话，不会写入世界快照。模型必须返回 JSON；真实行动仍由 Engine 规则引擎裁决。
          {serverKeyConfigured && liveProvider ? " 本地服务端已配置 Key，浏览器无需再次填写。" : ""}
        </p>
      </section>
    </main>
  );
}
