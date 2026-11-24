import type { RunStatus } from "../../types/contracts";
import type { RuntimePace } from "../../app/runtimeTypes";
import type { RuntimeMetrics } from "./viewerTypes";
import { clamp } from "./projectionModel";

export const RUNTIME_PACE_OPTIONS: Array<{ id: RuntimePace; label: string }> = [
  { id: "slow", label: "0.5x" },
  { id: "normal", label: "1x" },
  { id: "fast", label: "2x" },
];

export function runtimePaceLabel(pace: RuntimePace): string {
  const option = RUNTIME_PACE_OPTIONS.find((item) => item.id === pace);
  return option?.label ?? "1x";
}

export function telemetryValue(value: number | string | undefined): string {
  if (typeof value === "number" && Number.isFinite(value)) return fmt(value);
  if (typeof value === "string" && value.trim()) return value;
  return "--";
}

export function runtimeProgress(
  runtimeState: Record<string, unknown>,
  runStatus: RunStatus | undefined,
  controlState: "active" | "paused" | "canceled",
): RuntimeMetrics {
  const tickCursor = numeric(runtimeState.tick_cursor);
  const targetTicks = numeric(runtimeState.target_ticks);
  const mode = stringValue(runtimeState.mode) || "snapshot";
  const pendingProviders = Array.isArray(runtimeState.provider_pending) ? runtimeState.provider_pending : [];
  const firstPending = pendingProviders[0];
  const pendingElapsedMs = firstPending && typeof firstPending === "object"
    ? numeric((firstPending as Record<string, unknown>).elapsed_ms)
    : null;
  const rawStepStatus = stringValue(runtimeState.last_step_status) || runStatus || "offline";
  const lastStepStatus = rawStepStatus === "provider_pending" && pendingElapsedMs !== null
    ? `provider_pending · ${(pendingElapsedMs / 1000).toFixed(1)}s`
    : rawStepStatus;
  const state = controlState === "paused"
    ? "paused"
    : controlState === "canceled" || runStatus === "failed"
      ? "stopped"
      : runStatus || "offline";
  const safeCursor = tickCursor ?? 0;
  const safeTarget = targetTicks && targetTicks > 0 ? targetTicks : null;
  const percent = safeTarget ? Math.round(clamp(safeCursor / safeTarget, 0, 1) * 100) : 0;
  return {
    state,
    mode,
    lastStepStatus,
    tickLabel: safeTarget ? `${fmt(safeCursor)} / ${fmt(safeTarget)} ticks` : `${fmt(safeCursor)} ticks`,
    percentLabel: safeTarget ? `${percent}%` : "--",
    percent,
  };
}

export function clampIndex(value: number, length: number) {
  if (length <= 0) return 0;
  return Math.min(Math.max(Math.round(value), 0), length - 1);
}

function numeric(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function fmt(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}
