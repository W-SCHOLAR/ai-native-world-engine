import type { CausalPathItem, DomainSignal } from "./viewerTypes";
import { WORLD_ACTION_LABELS } from "./viewerTypes";

export function actionLabel(action: string): string {
  const found = WORLD_ACTION_LABELS.find(([key]) => key === action);
  return found?.[1] || action.replace(/_/g, " ");
}

export function traceText(value: Record<string, unknown> | undefined, field: string) {
  const raw = value?.[field];
  return typeof raw === "string" ? raw : "";
}

export function clamp(value: number, low: number, high: number) {
  return Math.max(low, Math.min(high, value));
}

export function pick(items: string[], tick: number) {
  if (!Array.isArray(items) || items.length === 0) return "保持观察。";
  return items[tick % items.length];
}


export function dedupePathItems(items: CausalPathItem[]): CausalPathItem[] {
  const seen = new Set<string>();
  const deduped: CausalPathItem[] = [];
  for (const item of items) {
    const key = `${item.role}:${item.id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(item);
  }
  return deduped;
}

export function uniqueStrings(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}


export function dict(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export function numeric(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function fmtValue(value: unknown): string {
  return typeof value === "number" ? fmt(value) : String(value ?? "");
}

export function fmt(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

export function riskSignalState(score: number | null, level: string): DomainSignal["state"] {
  const normalized = level.toLowerCase();
  if (normalized === "critical" || normalized === "high" || (score !== null && score >= 10)) return "high";
  if (normalized === "medium" || normalized === "moderate" || (score !== null && score > 0)) return "watch";
  return "low";
}

export function hashString(value: string) {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = ((hash << 5) - hash + value.charCodeAt(index)) >>> 0;
  }
  return hash;
}
