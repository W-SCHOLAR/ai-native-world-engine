import { useEffect, useRef } from "react";

import { hashString } from "./projectionShared";
import type { DisplayPayload, GlobeRuntime, NormalizedWorld } from "./viewerTypes";


export const ACTION_PULSE_INTERVAL_MS = 500;
export const ACTION_VISUAL_TTL_SECONDS = 0.5;
export const ACTION_CONTROLLER_TICK_MS = 40;

type PlaybackParams = {
  worldRef: RefBox<NormalizedWorld>;
  globeRef: RefBox<GlobeRuntime>;
  canvasRef: RefBox<HTMLCanvasElement | null>;
  emit: (payload: DisplayPayload, x: number, y: number) => void;
  clearNode: (nodeId: string) => void;
  reportCurrent: (count: number) => void;
};

type CurrentAction = {
  payload: DisplayPayload;
  nextDueAt: number;
};

type RefBox<T> = { current: T };

export function useActionVisualPlayback(params: PlaybackParams) {
  const paramsRef = useRef(params);
  const currentByNodeRef = useRef(new Map<string, CurrentAction>());
  const timerRef = useRef<number | null>(null);
  paramsRef.current = params;

  function syncCurrentActions(payloads: DisplayPayload[]) {
    const incomingByNode = latestPayloadByNode(payloads);
    const now = performance.now();

    for (const nodeId of currentByNodeRef.current.keys()) {
      if (incomingByNode.has(nodeId)) continue;
      currentByNodeRef.current.delete(nodeId);
      paramsRef.current.clearNode(nodeId);
    }

    for (const [nodeId, payload] of incomingByNode) {
      const existing = currentByNodeRef.current.get(nodeId);
      const sequence = Number(payload.feedback_sequence ?? 0);
      const existingSequence = Number(existing?.payload.feedback_sequence ?? 0);
      if (existing && existingSequence === sequence) {
        existing.payload = payload;
        continue;
      }
      if (existing) paramsRef.current.clearNode(nodeId);
      currentByNodeRef.current.set(nodeId, {
        payload,
        nextDueAt: existing ? now : now + stablePhaseOffsetMs(nodeId),
      });
    }

    reportCurrent();
    ensureTimer();
  }

  function ensureTimer() {
    if (timerRef.current !== null || currentByNodeRef.current.size === 0) return;
    timerRef.current = window.setTimeout(runControllerTick, ACTION_CONTROLLER_TICK_MS);
  }

  function runControllerTick() {
    timerRef.current = null;
    const now = performance.now();
    const visibleById = visibleActors(paramsRef.current);
    for (const current of currentByNodeRef.current.values()) {
      if (now < current.nextDueAt) continue;
      const point = visibleById.get(current.payload.node_id);
      if (!point) continue;
      paramsRef.current.emit(current.payload, point.x, point.y);
      current.nextDueAt = now + ACTION_PULSE_INTERVAL_MS;
    }
    ensureTimer();
  }

  function reset() {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = null;
    currentByNodeRef.current.clear();
    reportCurrent();
  }

  function reportCurrent() {
    paramsRef.current.reportCurrent(currentByNodeRef.current.size);
  }

  useEffect(() => () => reset(), []);

  return { syncCurrentActions, reset };
}

function latestPayloadByNode(payloads: DisplayPayload[]) {
  const latest = new Map<string, DisplayPayload>();
  for (const payload of payloads) {
    const sequence = Number(payload.feedback_sequence ?? 0);
    if (!payload.node_id || sequence <= 0) continue;
    const previous = latest.get(payload.node_id);
    if (!previous || sequence > Number(previous.feedback_sequence ?? 0)) {
      latest.set(payload.node_id, payload);
    }
  }
  return latest;
}

function stablePhaseOffsetMs(nodeId: string) {
  return hashString(nodeId) % ACTION_PULSE_INTERVAL_MS;
}

function visibleActors(params: PlaybackParams) {
  const canvas = params.canvasRef.current;
  const visible = new Map<string, { x: number; y: number }>();
  if (!canvas) return visible;
  const width = canvas.clientWidth || canvas.getBoundingClientRect().width;
  const height = canvas.clientHeight || canvas.getBoundingClientRect().height;
  const nodeIds = new Set(params.worldRef.current.agentNodes.map((node) => node.id));
  for (const agent of params.globeRef.current.visibleAgents) {
    if (
      nodeIds.has(agent.id)
      && agent.screenX >= 0
      && agent.screenX <= width
      && agent.screenY >= 0
      && agent.screenY <= height
    ) {
      visible.set(agent.id, { x: agent.screenX, y: agent.actionAnchorY ?? agent.screenY });
    }
  }
  return visible;
}
