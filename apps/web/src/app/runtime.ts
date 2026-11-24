import { advanceRun, getRunProjection, getRunStream } from "../api/client";
import type { JsonObject, ProjectionDelta, Run as RunDetail, Scenario, TimelineFrame, ViewerProjection, WorldBootstrapState } from "../types/contracts";
import type { StreamTelemetry } from "../types/ui";

export type StreamHydrationHooks = {
  onProjection: (projection: ViewerProjection) => void;
  onTimeline: (timeline: TimelineFrame[]) => void;
  onStatus: (message: string) => void;
  onRunStatus?: (status: RunDetail["status"]) => void;
  onControlState?: (controlState: NonNullable<RunDetail["control_state"]>) => void;
  onRuntimeState?: (runtimeState: Record<string, unknown>) => void;
  onBootstrapState?: (bootstrapState: WorldBootstrapState) => void;
  onStreamTelemetry?: (telemetry: StreamTelemetry) => void;
  getDelayMs?: () => number;
};

export function selectDemoScenario(scenarios: Scenario[]): Scenario {
  const fallback = {
    id: "tribe_survival",
    name: "蛮荒世界",
    description: "Default engine-backed survival demo scenario.",
    source: "engine",
    defaults: { ticks: 8, demo_priority: 200 },
  };
  if (scenarios.length === 0) return fallback;
  return [...scenarios].sort((left, right) => {
    const leftPriority = left.defaults?.demo_priority ?? (left.id === "tribe_survival" ? 200 : left.id === "compound_crisis" ? 100 : 0);
    const rightPriority = right.defaults?.demo_priority ?? (right.id === "tribe_survival" ? 200 : right.id === "compound_crisis" ? 100 : 0);
    return rightPriority - leftPriority || left.name.localeCompare(right.name) || left.id.localeCompare(right.id);
  })[0];
}

export async function hydrateFromRunStream(
  run: RunDetail,
  hooks: StreamHydrationHooks,
  options: { attempts?: number; delayMs?: number } = {},
): Promise<{ completed: boolean; status: RunDetail["status"]; timeline: TimelineFrame[] }> {
  const attempts = options.attempts ?? 140;
  const delayMs = options.delayMs ?? 600;
  let cursor = 0;
  let timeline = run.timeline && run.timeline.length > 0 ? run.timeline : [];
  let status = run.status;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    let latestBootstrap = run.bootstrap_state;
    if (status !== "completed" && status !== "failed") {
      const advance = await advanceRun(run.id);
      status = advance.status;
      hooks.onRunStatus?.(status);
      if (advance.control_state) hooks.onControlState?.(advance.control_state);
      hooks.onRuntimeState?.(advance.runtime_state ?? {});
      latestBootstrap = advance.bootstrap_state ?? bootstrapFromRuntimeState(advance.runtime_state) ?? latestBootstrap;
      if (latestBootstrap) hooks.onBootstrapState?.(latestBootstrap);
    }
    const stream = await getRunStream(run.id, cursor, 50);
    status = stream.status;
    hooks.onRunStatus?.(status);
    if (stream.control_state) hooks.onControlState?.(stream.control_state);
    hooks.onRuntimeState?.(stream.runtime_state ?? {});
    latestBootstrap = stream.bootstrap_state ?? bootstrapFromRuntimeState(stream.runtime_state) ?? latestBootstrap;
    if (latestBootstrap) hooks.onBootstrapState?.(latestBootstrap);
    cursor = stream.next_cursor;
    const tickCursor = typeof stream.runtime_state?.tick_cursor === "number" ? stream.runtime_state.tick_cursor : null;
    let streamedFrames = stream.updates
      .map((update) => update.timeline_frame)
      .filter((frame): frame is TimelineFrame => Boolean(frame));
    const projectionDeltas = stream.updates
      .map((update) => update.projection_delta)
      .filter((delta): delta is ProjectionDelta => Boolean(delta));
    if (projectionDeltas.length > 0) {
      const refreshed = await getRunProjection(run.id);
      const projection = mergeLocallyExpandedThoughtSchedules(refreshed, projectionDeltas);
      hooks.onProjection(projection);
      streamedFrames = projectionDeltas.map((delta) => ({
        sequence: delta.sequence,
        tick: delta.tick,
        event_cursor: 0,
        trace_cursor: 0,
        events: [],
        traces: [],
        deltas: [],
        projection,
        projection_delta: delta,
      }));
    }
    if (streamedFrames.length > 0) {
      timeline = stream.cursor_expired ? streamedFrames : mergeTimelineFrames(timeline, streamedFrames);
      hooks.onTimeline(timeline);
      const latestProjection = latestStreamProjection(streamedFrames, stream.updates);
      if (latestProjection) hooks.onProjection(latestProjection);
    }
    hooks.onStreamTelemetry?.({
      cursor: stream.cursor,
      nextCursor: stream.next_cursor,
      updateBatchSize: stream.updates.length,
      timelineFrameCount: timeline.length,
      cursorExpired: stream.cursor_expired,
      retainedFromCursor: stream.retained_from_cursor,
      retainedToCursor: stream.retained_to_cursor,
      latestTick: tickCursor ?? timeline[timeline.length - 1]?.tick,
    });
    const pendingLabel = providerPendingLabel(stream.runtime_state ?? {});
    hooks.onStatus(
      `${timeline.length > 0
        ? `Run ${stream.status} · ${stream.control_state ?? "active"} · tick ${tickCursor ?? cursor} · ${timeline.length} frame timeline`
        : `Run ${stream.status} · ${stream.control_state ?? "active"} · tick ${tickCursor ?? cursor}`}${pendingLabel}`,
    );
    if (latestBootstrap && ["failed", "timed_out", "canceled"].includes(latestBootstrap.phase)) {
      throw new Error(latestBootstrap.error_message || latestBootstrap.error_code || `World bootstrap ${latestBootstrap.phase}`);
    }
    if (stream.completed && !stream.has_more) {
      return { completed: true, status, timeline };
    }
    if (stream.has_more) continue;
    await delay(hooks.getDelayMs?.() ?? delayMs);
  }
  return { completed: false, status, timeline };
}

function bootstrapFromRuntimeState(runtimeState: Record<string, unknown> | undefined): WorldBootstrapState | null {
  const value = runtimeState?.bootstrap_state;
  if (!value || typeof value !== "object" || typeof (value as { phase?: unknown }).phase !== "string") return null;
  return value as WorldBootstrapState;
}

function mergeLocallyExpandedThoughtSchedules(
  projection: ViewerProjection,
  deltas: ProjectionDelta[],
): ViewerProjection {
  const expanded = deltas.flatMap((delta) =>
    (delta.thought_schedules ?? []).flatMap((schedule) => expandThoughtSchedule(schedule)),
  );
  const speechBubbles = deltas.flatMap((delta) => delta.speech_bubbles ?? []);
  if (expanded.length === 0 && speechBubbles.length === 0) return projection;
  const keyed = new Map<string, JsonObject>();
  for (const thought of [...expanded, ...projection.thoughts]) {
    const key = `${String(thought.schedule_sequence ?? thought.sequence ?? 0)}:${String(thought.node_id ?? "")}:${String(thought.sequence_index ?? 0)}`;
    keyed.set(key, thought);
  }
  const keyedSpeech = new Map<string, JsonObject>();
  for (const item of [...speechBubbles, ...(projection.speech_bubbles ?? [])]) {
    const key = String(
      item.speech_event_id
      ?? item.sequence
      ?? `${String(item.node_id ?? "")}:${String(item.text ?? "")}`,
    );
    keyedSpeech.set(key, item);
  }
  return {
    ...projection,
    thoughts: [...keyed.values()],
    speech_bubbles: [...keyedSpeech.values()],
  };
}

function expandThoughtSchedule(schedule: JsonObject): JsonObject[] {
  const sourceSequence = Number(schedule.sequence ?? 0);
  const explicitOccurrences = Array.isArray(schedule.occurrences)
    ? schedule.occurrences.filter((item): item is JsonObject => Boolean(item) && typeof item === "object")
    : [];
  if (explicitOccurrences.length > 0) {
    const now = Date.now();
    return explicitOccurrences.flatMap((occurrence, index) => {
      const displayAt = Date.parse(String(occurrence.display_at ?? ""));
      const duration = Math.max(Number(occurrence.duration ?? schedule.ttl ?? 4), 0);
      const expiresAt = Date.parse(String(occurrence.expires_at ?? ""));
      const validDisplayAt = Number.isFinite(displayAt) ? displayAt : now + Math.max(Number(occurrence.delay ?? 0), 0) * 1000;
      const validExpiresAt = Number.isFinite(expiresAt) ? expiresAt : validDisplayAt + duration * 1000;
      const nodeId = String(occurrence.node_id ?? schedule.node_id ?? "");
      const text = String(occurrence.text ?? "").trim();
      if (!nodeId || !text) return [];
      return [{
        node_id: nodeId,
        text,
        source: String(schedule.source ?? ""),
        salience: Number(schedule.salience ?? 0.82),
        ttl: duration,
        delay: Math.max((validDisplayAt - now) / 1000, 0),
        display_at: new Date(validDisplayAt).toISOString(),
        expires_at: new Date(validExpiresAt).toISOString(),
        expired: validExpiresAt <= now,
        tick: Number(schedule.tick ?? 0),
        sequence: sourceSequence * 100 + index + 1,
        schedule_sequence: sourceSequence,
        occurrence_id: String(occurrence.occurrence_id ?? `${sourceSequence}:${index}`),
        sequence_index: Number(occurrence.slice_index ?? index),
        sequence_total: explicitOccurrences.length,
        generation: Number(schedule.generation ?? 0),
        cognition_id: String(schedule.cognition_id ?? ""),
        origin: String(occurrence.origin ?? schedule.origin ?? "active_node"),
        ripple_from: String(occurrence.ripple_from ?? schedule.ripple_from ?? ""),
      }];
    });
  }
  const sliceCount = Math.max(Number(schedule.slice_count ?? 6), 1);
  const explicit = Array.isArray(schedule.explicit_slices)
    ? schedule.explicit_slices.map(String).filter(Boolean)
    : [];
  const slices = explicit.length > 0
    ? explicit
    : splitScheduleText(String(schedule.text ?? "保持观察。"), sliceCount);
  const baseDelay = Math.max(Number(schedule.delay ?? 0), 0);
  const interval = Math.max(Number(schedule.interval ?? 8), 0);
  const active = slices.map((text, index) => ({
    node_id: String(schedule.node_id ?? ""),
    text,
    source: String(schedule.source ?? ""),
    salience: Number(schedule.salience ?? 0.82),
    ttl: Number(schedule.ttl ?? 4),
    delay: baseDelay + index * interval,
    tick: Number(schedule.tick ?? 0),
    sequence: sourceSequence * 100 + index + 1,
    schedule_sequence: sourceSequence,
    sequence_index: index,
    sequence_total: slices.length,
    origin: "active_node",
  }));
  return active.filter((item) => item.node_id && item.text);
}

function splitScheduleText(text: string, count: number): string[] {
  const clean = text.trim().replace(/\s+/g, " ") || "保持观察。";
  const clauses = clean.match(/[^。！？；.!?;，、：,:]+[。！？；.!?;，、：,:]*/g)
    ?.map((item) => item.trim()).filter(Boolean) || [clean];
  const semantic: string[] = [];
  let pending = "";
  for (const clause of clauses) {
    pending += clause;
    if (Array.from(pending).length >= 6) {
      semantic.push(pending);
      pending = "";
    }
  }
  if (pending) {
    if (semantic.length > 0) semantic[semantic.length - 1] += pending;
    else semantic.push(pending);
  }
  while (semantic.length > count) {
    const index = semantic.slice(0, -1).reduce((best, _, item) => (
      semantic[item].length + semantic[item + 1].length
        < semantic[best].length + semantic[best + 1].length ? item : best
    ), 0);
    semantic.splice(index, 2, semantic[index] + semantic[index + 1]);
  }
  return semantic;
}

function providerPendingLabel(runtimeState: Record<string, unknown>): string {
  const pending = Array.isArray(runtimeState.provider_pending) ? runtimeState.provider_pending : [];
  if (pending.length === 0) return "";
  const first = pending[0];
  const elapsedMs = first && typeof first === "object"
    ? Number((first as Record<string, unknown>).elapsed_ms ?? 0)
    : 0;
  const elapsed = Number.isFinite(elapsedMs) ? ` · ${(elapsedMs / 1000).toFixed(1)}s` : "";
  return ` · provider_pending ${pending.length}${elapsed}`;
}

export function mergeTimelineFrames(existing: TimelineFrame[], incoming: TimelineFrame[]): TimelineFrame[] {
  const byTick = new Map<number, TimelineFrame>();
  for (const frame of existing) byTick.set(Number(frame.tick), frame);
  for (const frame of incoming) byTick.set(Number(frame.tick), frame);
  return [...byTick.values()].sort((left, right) => Number(left.tick) - Number(right.tick));
}

export function latestStreamProjection(
  frames: TimelineFrame[],
  updates: Array<{ projection?: ViewerProjection }>,
): ViewerProjection | null {
  for (let index = updates.length - 1; index >= 0; index -= 1) {
    const projection = updates[index]?.projection;
    if (projection?.summary) return projection;
  }
  for (let index = frames.length - 1; index >= 0; index -= 1) {
    const projection = frames[index]?.projection;
    if (projection?.summary) return projection;
  }
  return null;
}

export async function loadLocalProjection(): Promise<ViewerProjection> {
  const response = await fetch("/world-data.json", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Local projection unavailable: ${response.status}`);
  }
  return (await response.json()) as ViewerProjection;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
