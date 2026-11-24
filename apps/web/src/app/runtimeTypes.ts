import type { RunControlRequest } from "../types/contracts";

export type RuntimeProviderMode = "deterministic" | "deepseek" | "openai_compatible";
export type ProductScenarioId = "enterprise_earth" | "tribe_survival";

export type RuntimeProviderConfig = {
  mode: RuntimeProviderMode;
  base_url: string;
  api_key: string;
  model: string;
  max_tokens: number;
};

export const RUNTIME_PROVIDER_CONFIG_KEY = "ai-native-world-runtime-provider";
export const RUNTIME_SCENARIO_KEY = "ai-native-world-product-scenario";

const PRODUCT_SCENARIO_LABELS: Record<ProductScenarioId, string> = {
  enterprise_earth: "星球文明",
  tribe_survival: "蛮荒世界",
};

export function productScenarioLabel(scenario: ProductScenarioId): string {
  return PRODUCT_SCENARIO_LABELS[scenario];
}

export const DEFAULT_RUNTIME_PROVIDER_CONFIG: RuntimeProviderConfig = {
  mode: "deepseek",
  base_url: "https://api.deepseek.com",
  api_key: "",
  model: "deepseek-v4-flash",
  max_tokens: 2400,
};

export function readRuntimeProviderConfig(): RuntimeProviderConfig | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(RUNTIME_PROVIDER_CONFIG_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<RuntimeProviderConfig>;
    if (!value || typeof value !== "object") return null;
    const mode = value.mode;
    if (mode !== "deterministic" && mode !== "deepseek" && mode !== "openai_compatible") return null;
    return {
      mode,
      base_url: String(value.base_url ?? ""),
      api_key: String(value.api_key ?? ""),
      model: String(value.model ?? ""),
      max_tokens: Math.max(Number(value.max_tokens ?? DEFAULT_RUNTIME_PROVIDER_CONFIG.max_tokens) || 2400, 1),
    };
  } catch {
    return null;
  }
}

export function saveRuntimeProviderConfig(config: RuntimeProviderConfig): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(RUNTIME_PROVIDER_CONFIG_KEY, JSON.stringify(config));
}

export function readProductScenario(): ProductScenarioId | null {
  if (typeof window === "undefined") return null;
  const value = window.sessionStorage.getItem(RUNTIME_SCENARIO_KEY);
  return value === "enterprise_earth" || value === "tribe_survival" ? value : null;
}

export function saveProductScenario(scenario: ProductScenarioId): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(RUNTIME_SCENARIO_KEY, scenario);
}

export type RunControlCommand = RunControlRequest["command"];
export type InterventionTemplate = "signal" | "supply" | "policy";
export type RuntimePace = "slow" | "normal" | "fast";

export const RUNTIME_PACE_DELAY_MS: Record<RuntimePace, number> = {
  slow: 1200,
  normal: 600,
  fast: 240,
};
