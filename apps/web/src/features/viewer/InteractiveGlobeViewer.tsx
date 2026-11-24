import { memo, useEffect, useMemo, useRef, useState } from "react";
import type { InterventionTemplate, RuntimePace } from "../../app/runtimeTypes";
import type { RunControlRequest, TimelineFrame, ViewerProjection } from "../../types/contracts";
import type { InterventionLogItem, SovereignIntentLogItem, StreamTelemetry } from "../../types/ui";
import {
  aiCausalityTimeline,
  causalFocusForSelection,
  clamp,
  effectNodeIds,
  nodeMemoryHighlights,
  nodeRelationshipFacts,
  nodeStateFacts,
  normalizeProjection,
  rankedAiTraces,
  rankedGroundedActions,
  worldEventTicker,
} from "./projectionModel";
import {
  cancelGlobeOrientationTarget,
  createGlobeRuntime,
  drawGlobe,
  focusGlobeAtScreenPoint,
  nearestVisibleAgent,
  resetGlobeView,
  restoreGlobeOverview,
  screenPointForAgent,
  thoughtPointForAgent,
} from "./globeRenderer";
import {
  drawTribeSurvivalWorld,
  focusTribeNetwork,
  isTribeSurvivalScene,
  restoreTribeOverview,
} from "./tribeSurvivalRenderer";
import { ViewerFooter } from "./ViewerPanels";
import { ViewerInteractionBar } from "./ViewerInteractionBar";
import { ViewerStageHeader } from "./ViewerStageHeader";
import {
  activeActionOverlayIds,
  activeSpeechOverlayIds,
  activeThoughtOverlayIds,
  drawVisibleIntelligenceOverlays,
  overlayLane,
  overlayLifetimeMs,
  spatialOverlayLaneIndex,
  syncOverlayDiagnostics,
} from "./visibleIntelligenceRenderer";
import type {
  AgentNode,
  CausalFocus,
  GlobeRuntime,
  GroundedAction,
  GroundedEffect,
  NormalizedWorld,
  OverlayItem,
  RunStatus,
} from "./viewerTypes";
import { consumeThoughtOccurrences } from "../../api/client";
import { EMPTY_WORLD } from "./viewerTypes";
import {
  ACTION_VISUAL_TTL_SECONDS,
  useActionVisualPlayback,
} from "./useActionVisualPlayback";
type Props = {
  projection: ViewerProjection | null;
  timeline?: TimelineFrame[];
  scenarioCount: number;
  status: string;
  runId?: string;
  runStatus?: RunStatus;
  runtimeState?: Record<string, unknown>;
  controlState?: "active" | "paused" | "canceled";
  runtimePace?: RuntimePace;
  streamTelemetry?: StreamTelemetry | null;
  interventionLog?: InterventionLogItem[];
  sovereignIntentLog?: SovereignIntentLogItem[];
  pendingControl?: RunControlCommand | null;
  pendingIntervention?: InterventionTemplate | null;
  pendingSovereignIntent?: boolean;
  onRunControl?: (command: RunControlCommand) => void;
  onRunIntervention?: (nodeId: string, nodeName: string, template: InterventionTemplate) => void;
  onSovereignIntent?: (text: string) => void;
  onRuntimePaceChange?: (pace: RuntimePace) => void;
  onExitWorld?: () => void;
  runtimeAuthority?: "authoritative_engine" | "static_visual_demo" | "local_projection_fallback";
};
type RunControlCommand = RunControlRequest["command"];
function InteractiveGlobeViewerComponent({
  onExitWorld,
  onRunControl,
  onRunIntervention,
  onSovereignIntent,
  controlState = "active",
  interventionLog = [],
  pendingControl = null,
  pendingIntervention = null,
  pendingSovereignIntent = false,
  projection,
  runId,
  runStatus,
  runtimeAuthority = "local_projection_fallback",
  sovereignIntentLog = [],
  status,
  timeline = [],
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const worldRef = useRef<NormalizedWorld>(EMPTY_WORLD);
  const selectedRef = useRef<AgentNode | null>(null);
  const causalFocusRef = useRef<CausalFocus | null>(null);
  const overlaySeqRef = useRef(0);
  const playbackTimersRef = useRef(new Set<number>());
  const thoughtTimerByOccurrenceRef = useRef(new Map<string, number>());
  const thoughtTimerMetadataRef = useRef(new Map<string, { nodeId: string; generation: number }>());
  const scheduledThoughtIdsRef = useRef(new Set<string>());
  const scheduledSpeechIdsRef = useRef(new Set<string>());
  const overlayExpiryTimersRef = useRef(new Map<string, number>());
  const overlayMetadataRef = useRef(new Map<string, OverlayItem>());
  const bubbleLayerRef = useRef<HTMLDivElement | null>(null);
  const hoverElementRef = useRef<HTMLDivElement | null>(null);
  const hoverNameRef = useRef<HTMLElement | null>(null);
  const hoverMetaRef = useRef<HTMLSpanElement | null>(null);
  const hoveredVisualIdRef = useRef("");
  const highlightedNetworkNodeIdsRef = useRef(new Set<string>());
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [selectedActionSequence, setSelectedActionSequence] = useState<number | null>(null);
  const [selectedEffectLabel, setSelectedEffectLabel] = useState("");
  const [globeFocused, setGlobeFocused] = useState(false);
  const globeRef = useRef<GlobeRuntime>(createGlobeRuntime());
  const actionPlayback = useActionVisualPlayback({
    worldRef,
    globeRef,
    canvasRef,
    emit: (payload, x, y) => emitOverlay(
      "action",
      payload.node_id,
      payload.text,
      x,
      y + 22,
      22,
      payload.salience ?? 0.55,
      payload.origin,
      ACTION_VISUAL_TTL_SECONDS,
    ),
    clearNode: (nodeId) => {
      for (const activeId of activeActionOverlayIds(overlayMetadataRef.current.values(), nodeId)) {
        removeOverlay(activeId);
      }
    },
    reportCurrent: (count) => {
      const layer = bubbleLayerRef.current;
      if (layer) layer.dataset.currentActions = String(count);
    },
  });
  const activeProjection = projection ?? timeline[timeline.length - 1]?.projection ?? null;
  const world = useMemo(
    () => activeProjection ? normalizeProjection(activeProjection) : EMPTY_WORLD,
    [activeProjection],
  );
  const selected = world.agentNodes.find((node) => node.id === selectedNodeId) ?? world.agentNodes[0] ?? null;
  const selectedAction = selectedActionSequence === null
    ? null
    : world.groundedActions.find((action) => action.sequence === selectedActionSequence) ?? null;
  const selectedEffect = selectedAction && selectedEffectLabel
    ? (selectedAction.effects || []).find((effect) => effect.label === selectedEffectLabel) ?? null
    : null;
  const causalFocus = causalFocusForSelection(selectedAction, selectedEffect);
  const highlightedNetworkNodeIds = useMemo(
    () => selectedRelationshipNetworkNodeIds(selected, world.agentNodes),
    [selected, world.agentNodes],
  );
  worldRef.current = world;
  selectedRef.current = selected;
  causalFocusRef.current = causalFocus;
  highlightedNetworkNodeIdsRef.current = highlightedNetworkNodeIds;

  useEffect(() => {
    clearOverlayElements();
    hideHoverCard();
    resetGlobeView(globeRef.current);
    setGlobeFocused(false);
    scheduledThoughtIdsRef.current.clear();
    scheduledSpeechIdsRef.current.clear();
    actionPlayback.reset();
  }, [runId]);

  useEffect(() => () => {
    clearOverlayElements();
  }, []);

  useEffect(() => {
    if (!activeProjection) return;
    if (world.scheduledThoughts.length > 0) {
      const unseenThoughtPayloads = world.scheduledThoughts.filter((payload) => {
        const occurrenceId = payload.occurrence_id
          || `thought:${payload.node_id}:${payload.origin || ""}:${payload.delay || 0}:${payload.text}`;
        if (scheduledThoughtIdsRef.current.has(occurrenceId)) return false;
        scheduledThoughtIdsRef.current.add(occurrenceId);
        return true;
      });
      const newestGenerationByNode = new Map<string, number>();
      for (const payload of unseenThoughtPayloads) {
        newestGenerationByNode.set(
          payload.node_id,
          Math.max(
            newestGenerationByNode.get(payload.node_id) ?? 0,
            Number(payload.generation ?? 0),
          ),
        );
      }
      for (const [occurrenceId, metadata] of thoughtTimerMetadataRef.current) {
        const newestGeneration = newestGenerationByNode.get(metadata.nodeId);
        if (newestGeneration === undefined || newestGeneration <= metadata.generation) continue;
        const timer = thoughtTimerByOccurrenceRef.current.get(occurrenceId);
        if (timer !== undefined) {
          window.clearTimeout(timer);
          playbackTimersRef.current.delete(timer);
        }
        thoughtTimerByOccurrenceRef.current.delete(occurrenceId);
        thoughtTimerMetadataRef.current.delete(occurrenceId);
        acknowledgeOccurrenceId(occurrenceId);
      }
      const thoughtPayloads = unseenThoughtPayloads.filter((payload) => {
        const newestGeneration = newestGenerationByNode.get(payload.node_id) ?? 0;
        if (Number(payload.generation ?? 0) >= newestGeneration) return true;
        acknowledgeThoughtOccurrence(payload);
        return false;
      });
      const expiredThoughtPayloads = thoughtPayloads.filter((payload) => payload.expired);
      for (const payload of expiredThoughtPayloads) {
        acknowledgeThoughtOccurrence(payload);
      }
      const futureThoughtPayloads = thoughtPayloads.filter((payload) => !payload.expired);
      const emitThought = (payload: NormalizedWorld["scheduledThoughts"][number]) => {
        const node = worldRef.current.agentNodes.find((item) => item.id === payload.node_id);
        if (!node) {
          acknowledgeThoughtOccurrence(payload);
          return;
        }
        const point = thoughtPointForAgent(globeRef.current.visibleAgents, node, canvasRef.current);
        emitOverlay("thought", node.id, payload.text, point.x, Math.max(point.y, 16), 0, payload.salience ?? 0.5, payload.origin, payload.ttl);
        acknowledgeThoughtOccurrence(payload);
      };
      if (futureThoughtPayloads.length > 0) {
        schedulePayloadQueue(futureThoughtPayloads, emitThought);
      }
    }
    for (const payload of world.speechBubbles) {
      const occurrenceId = payload.occurrence_id
        || `speech:${payload.node_id}:${payload.text}`;
      if (scheduledSpeechIdsRef.current.has(occurrenceId)) continue;
      scheduledSpeechIdsRef.current.add(occurrenceId);
      const node = worldRef.current.agentNodes.find(
        (item) => item.id === payload.node_id,
      );
      if (!node) continue;
      const point = thoughtPointForAgent(
        globeRef.current.visibleAgents,
        node,
        canvasRef.current,
      );
      emitOverlay(
        "speech",
        node.id,
        payload.text,
        point.x,
        Math.max(point.y, 16),
        0,
        payload.salience ?? 0.82,
        payload.origin,
        payload.ttl,
      );
    }
    const tribeScene = isTribeSurvivalScene((world.summary || {}) as Record<string, unknown>);
    if (tribeScene) {
      if (bubbleLayerRef.current) {
        bubbleLayerRef.current.dataset.currentActions = String(world.currentActions.length);
      }
    } else {
      actionPlayback.syncCurrentActions(world.currentActions);
    }
  }, [activeProjection, world, runId]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      canvas.width = Math.floor(rect.width * dpr);
      canvas.height = Math.floor(rect.height * dpr);
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    window.addEventListener("resize", resize);

    let frame = 0;
    const draw = (now: number) => {
      const highlightedNetworkNodeIds = highlightedNetworkNodeIdsRef.current;
      if (isTribeSurvivalScene((worldRef.current.summary || {}) as Record<string, unknown>)) {
        drawTribeSurvivalWorld(
          context,
          canvas,
          globeRef.current,
          worldRef.current,
          selectedRef.current?.id ?? "",
          causalFocusRef.current,
          highlightedNetworkNodeIds,
          now,
        );
      } else {
        drawGlobe(
          context,
          canvas,
          globeRef.current,
          worldRef.current,
          selectedRef.current?.id ?? "",
          causalFocusRef.current,
          highlightedNetworkNodeIds,
          now,
        );
      }
      drawVisibleIntelligenceOverlays(
        context,
        canvas,
        overlayMetadataRef.current.values(),
        globeRef.current.visibleAgents,
        now,
        isTribeSurvivalScene((worldRef.current.summary || {}) as Record<string, unknown>),
      );
      syncHoverElement();
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("resize", resize);
    };
  }, []);

  useEffect(() => {
    const stage = wrapRef.current;
    const canvas = canvasRef.current;
    if (!stage || !canvas) return;
    const globe = globeRef.current;

    const onPointerDown = (event: PointerEvent) => {
      if ((event.target as Element | null)?.closest(".globe-focus-back")) return;
      globe.dragging = true;
      globe.pointerMoved = false;
      globe.lastPointerX = event.clientX;
      globe.lastPointerY = event.clientY;
      globe.velocityYaw = 0;
      globe.velocityPitch = 0;
      cancelGlobeOrientationTarget(globe);
      stage.classList.add("dragging");
      stage.setPointerCapture(event.pointerId);
    };

    const onPointerMove = (event: PointerEvent) => {
      if (!globe.dragging) {
        const rect = canvas.getBoundingClientRect();
        const agent = nearestVisibleAgent(globe.visibleAgents, event.clientX - rect.left, event.clientY - rect.top);
        const nextVisualId = agent?.id ?? "";
        if (nextVisualId !== hoveredVisualIdRef.current) {
          showHoverCard(agent);
        }
        return;
      }
      const dx = event.clientX - globe.lastPointerX;
      const dy = event.clientY - globe.lastPointerY;
      if (Math.hypot(dx, dy) > 2) globe.pointerMoved = true;
      globe.lastPointerX = event.clientX;
      globe.lastPointerY = event.clientY;
      const yawDelta = dx * 0.006;
      const pitchDelta = dy * 0.0045;
      globe.yaw += yawDelta;
      globe.pitch = clamp(
        globe.pitch + pitchDelta,
        globe.focused ? -1.35 : -0.92,
        globe.focused ? 1.35 : 0.72,
      );
      globe.velocityYaw = yawDelta * 0.08;
      globe.velocityPitch = pitchDelta * 0.08;
    };

    const release = (event: PointerEvent) => {
      if (!globe.dragging) return;
      const shouldHitTest = !globe.pointerMoved;
      globe.dragging = false;
      stage.classList.remove("dragging");
      if (stage.hasPointerCapture(event.pointerId)) {
        stage.releasePointerCapture(event.pointerId);
      }
      if (!shouldHitTest) return;
      const rect = canvas.getBoundingClientRect();
      const localX = event.clientX - rect.left;
      const localY = event.clientY - rect.top;
      const agent = nearestVisibleAgent(globe.visibleAgents, localX, localY);
      if (agent) {
        const selectedAgent = sourceAgent(agent, worldRef.current.agentNodes);
        setSelectedNodeId(selectedAgent.id);
      }
      if (isTribeSurvivalScene((worldRef.current.summary || {}) as Record<string, unknown>) && agent) {
        if (focusTribeNetwork(globe, agent)) {
          hideHoverCard();
          setGlobeFocused(true);
        }
        return;
      }
      if (
        !isTribeSurvivalScene((worldRef.current.summary || {}) as Record<string, unknown>)
        && focusGlobeAtScreenPoint(globe, rect.width, rect.height, localX, localY)
      ) {
        hideHoverCard();
        setGlobeFocused(true);
      }
    };

    const onPointerLeave = () => {
      hideHoverCard();
    };

    stage.addEventListener("pointerdown", onPointerDown);
    stage.addEventListener("pointermove", onPointerMove);
    stage.addEventListener("pointerup", release);
    stage.addEventListener("pointercancel", release);
    stage.addEventListener("pointerleave", onPointerLeave);
    return () => {
      stage.removeEventListener("pointerdown", onPointerDown);
      stage.removeEventListener("pointermove", onPointerMove);
      stage.removeEventListener("pointerup", release);
      stage.removeEventListener("pointercancel", release);
      stage.removeEventListener("pointerleave", onPointerLeave);
    };
  }, []);

  const activeSummary = (activeProjection?.summary || {}) as Record<string, unknown>;
  const usesTribeSurvivalMapScene = isTribeSurvivalScene(activeSummary);
  const stageScene = usesTribeSurvivalMapScene ? "tribe-survival-map" : "globe";
  const stageAriaLabel = usesTribeSurvivalMapScene
    ? "蛮荒世界平面村庄地图"
    : "AI 原生世界地球展示";
  const projectedSceneTitle = typeof activeSummary.scene_title === "string" ? activeSummary.scene_title.trim() : "";
  const sceneTitle = projectedSceneTitle || "AI native world";
  const tick = Number(activeProjection?.summary.tick ?? 0);
  const selectedMeta = selected
    ? [selected.type, selected.role, selected.parent].filter(Boolean).join(" · ")
    : "等待 projection 数据";
  const selectedStatus = typeof selected?.keyCharacter.status === "string" ? selected.keyCharacter.status : "";
  const selectedGoal = typeof selected?.keyCharacter.goal === "string" ? selected.keyCharacter.goal : "";
  const selectedStep = typeof selected?.keyCharacter.current_step === "string" ? selected.keyCharacter.current_step : "";
  const visibleTraces = rankedAiTraces(activeProjection?.ai_traces || [], selected?.id).slice(0, 3);
  const visibleCausalityHistory = aiCausalityTimeline(timeline, activeProjection, selected?.id);
  const selectedDomainSignal = null;
  const visibleGroundedActions = rankedGroundedActions(world.groundedActions, selected?.id, null).slice(0, 6);
  const interventionStatusById = new Map<string, string>();
  const selectedStateFacts = selected ? nodeStateFacts(selected.attributes).slice(0, 10) : [];
  const selectedMemoryHighlights = selected ? nodeMemoryHighlights(selected.attributes) : [];
  const selectedMemoryCount = Number(selected?.attributes._memory_count || selectedMemoryHighlights.length || 0);
  const selectedRelationshipFacts = selected
    ? nodeRelationshipFacts(activeProjection?.relationships || [], selected.id, world.agentNodes)
    : [];
  const tickerItems = worldEventTicker(activeProjection);

  function emitOverlay(
    type: OverlayItem["type"],
    nodeId: string,
    text: string,
    x: number,
    y: number,
    offsetY: number,
    salience: number,
    origin?: string,
    ttlSeconds?: number,
  ) {
    const id = `${type}-${overlaySeqRef.current}`;
    overlaySeqRef.current += 1;
    if (!bubbleLayerRef.current) return;
    if (type === "thought") {
      for (const activeId of activeThoughtOverlayIds(overlayMetadataRef.current.values(), nodeId)) removeOverlay(activeId);
    } else if (type === "speech") {
      for (const activeId of activeSpeechOverlayIds(overlayMetadataRef.current.values(), nodeId)) removeOverlay(activeId);
    } else {
      for (const activeId of activeActionOverlayIds(overlayMetadataRef.current.values(), nodeId)) removeOverlay(activeId);
    }
    const tribeScene = isTribeSurvivalScene((worldRef.current.summary || {}) as Record<string, unknown>);
    const anchoredThought = tribeScene;
    const siblingIndex = anchoredThought ? 0 : spatialOverlayLaneIndex(type, nodeId, x, y - offsetY, offsetY,
      overlayMetadataRef.current.values(), canvasRef.current?.clientWidth || 1600, canvasRef.current?.clientHeight || 1000);
    const { offsetX, offsetY: laneOffsetY } = anchoredThought
      ? { offsetX: 0, offsetY: 0 }
      : overlayLane(type, siblingIndex, offsetY);
    const lifetimeMs = overlayLifetimeMs(salience, ttlSeconds);
    const item: OverlayItem = {
      id,
      type,
      nodeId,
      text,
      x,
      y: y - offsetY,
      offsetX,
      offsetY: laneOffsetY,
      salience,
      origin,
      createdAt: performance.now(),
      lifetimeMs,
    };
    overlayMetadataRef.current.set(id, item);
    // The renderer helper maintains maxThoughtsPerNode and per-type diagnostics.
    syncOverlayDiagnostics(bubbleLayerRef.current, overlayMetadataRef.current.values(), type, text);
    const timer = window.setTimeout(() => {
      overlayExpiryTimersRef.current.delete(id);
      removeOverlay(id, false);
    }, lifetimeMs);
    overlayExpiryTimersRef.current.set(id, timer);
  }

  function schedulePlaybackTimer(callback: () => void, delayMs: number) {
    const timer = window.setTimeout(() => {
      playbackTimersRef.current.delete(timer);
      callback();
    }, delayMs);
    playbackTimersRef.current.add(timer);
    return timer;
  }

  function schedulePayloadQueue<T extends {
    delay?: number;
    occurrence_id?: string;
    node_id?: string;
    generation?: number;
  }>(payloads: T[], emit: (payload: T) => void) {
    const startedAt = performance.now();
    for (const payload of payloads) {
      const remainingDelay = payloadDelayMs(payload.delay) - (performance.now() - startedAt);
      const occurrenceId = payload.occurrence_id;
      const timer = schedulePlaybackTimer(() => {
        if (occurrenceId) {
          thoughtTimerByOccurrenceRef.current.delete(occurrenceId);
          thoughtTimerMetadataRef.current.delete(occurrenceId);
        }
        emit(payload);
      }, Math.max(0, remainingDelay));
      if (occurrenceId) {
        thoughtTimerByOccurrenceRef.current.set(occurrenceId, timer);
        thoughtTimerMetadataRef.current.set(occurrenceId, {
          nodeId: String(payload.node_id ?? ""),
          generation: Number(payload.generation ?? 0),
        });
      }
    }
  }

  function acknowledgeThoughtOccurrence(
    payload: NormalizedWorld["scheduledThoughts"][number],
  ) {
    if (!payload.occurrence_id) return;
    acknowledgeOccurrenceId(payload.occurrence_id);
  }

  function acknowledgeOccurrenceId(occurrenceId: string) {
    if (!runId || !occurrenceId) return;
    void consumeThoughtOccurrences(runId, [occurrenceId]).catch(() => {
      // A later projection refresh safely retries the still-unconsumed id.
    });
  }

  function removeOverlay(id: string, clearExpiryTimer = true) {
    if (clearExpiryTimer) {
      const timer = overlayExpiryTimersRef.current.get(id);
      if (timer !== undefined) window.clearTimeout(timer);
    }
    overlayExpiryTimersRef.current.delete(id);
    overlayMetadataRef.current.delete(id);
    syncOverlayDiagnostics(bubbleLayerRef.current, overlayMetadataRef.current.values());
  }

  function clearOverlayElements() {
    for (const timer of playbackTimersRef.current) window.clearTimeout(timer);
    playbackTimersRef.current.clear();
    thoughtTimerByOccurrenceRef.current.clear();
    thoughtTimerMetadataRef.current.clear();
    for (const timer of overlayExpiryTimersRef.current.values()) window.clearTimeout(timer);
    overlayExpiryTimersRef.current.clear();
    overlayMetadataRef.current.clear();
    syncOverlayDiagnostics(bubbleLayerRef.current, overlayMetadataRef.current.values());
  }

  function showHoverCard(agent: AgentNode | null) {
    const card = hoverElementRef.current;
    if (!card || !agent) {
      hideHoverCard();
      return;
    }
    const source = sourceAgent(agent, worldRef.current.agentNodes);
    hoveredVisualIdRef.current = agent.id;
    if (hoverNameRef.current) hoverNameRef.current.textContent = source.name;
    if (hoverMetaRef.current) hoverMetaRef.current.textContent = hoverPersonalInfo(source);
    card.hidden = false;
  }

  function hideHoverCard() {
    hoveredVisualIdRef.current = "";
    if (hoverElementRef.current) hoverElementRef.current.hidden = true;
  }

  function syncHoverElement() {
    const visibleById = new Map(globeRef.current.visibleAgents.map((agent) => [agent.id, agent]));
    const hoverElement = hoverElementRef.current;
    const hoverVisible = visibleById.get(hoveredVisualIdRef.current);
    if (hoverElement && hoverVisible) {
      hoverElement.hidden = false;
      hoverElement.style.left = `${hoverVisible.screenX}px`;
      hoverElement.style.top = `${Math.max(hoverVisible.screenY - 18, 14)}px`;
    } else if (hoverElement) {
      hoverElement.hidden = true;
    }
  }

  function hoverPersonalInfo(node: AgentNode) {
    return [node.role, node.parent].filter(Boolean).join(" · ");
  }

  function selectGroundedAction(action: GroundedAction) {
    setSelectedActionSequence(action.sequence ?? null);
    setSelectedEffectLabel("");
    const actorNode = worldRef.current.agentNodes.find((node) => node.id === action.actor_id);
    if (actorNode) {
      setSelectedNodeId(actorNode.id);
      return;
    }
    const targetNode = worldRef.current.agentNodes.find((node) => (action.targets || []).some((target) => target.id === node.id));
    if (targetNode) {
      setSelectedNodeId(targetNode.id);
    }
  }

  function selectGroundedEffect(action: GroundedAction, effect: GroundedEffect) {
    setSelectedActionSequence(action.sequence ?? null);
    setSelectedEffectLabel(effect.label ?? "");
    const nodeId = effectNodeIds(effect)[0] || action.actor_id;
    const effectNode = worldRef.current.agentNodes.find((node) => node.id === nodeId);
    if (effectNode) {
      setSelectedNodeId(effectNode.id);
    }
  }

  return (
    <main className="viewer-shell">
      <ViewerStageHeader
        onExitWorld={onExitWorld}
        runtimeAuthority={runtimeAuthority}
        sceneTitle={sceneTitle}
      />
      <section className="world-event-ticker" aria-label="世界事件流">
        {tickerItems.length > 0 ? tickerItems.map((item, index) => (
          <article className="world-event-ticker-item" data-kind={item.kind} key={`${item.kind}-${item.tick}-${index}`}>
            <b>{item.label}</b>
            <span>T{item.tick}</span>
            <p>{item.text}</p>
          </article>
        )) : (
          <span className="world-event-ticker-empty">等待世界事件</span>
        )}
      </section>

      <section
        className="world-stage"
        aria-label={stageAriaLabel}
        data-scene={stageScene}
        data-view-mode={globeFocused ? "local-focus" : "overview"}
      >
        <div
          ref={wrapRef}
          className={usesTribeSurvivalMapScene ? "earth-wrap tribe-survival-wrap" : "earth-wrap"}
          data-scene={stageScene}
        >
          <canvas ref={canvasRef} className="globe-canvas" aria-hidden="true" />
          {globeFocused ? (
            <button
              type="button"
              className="globe-focus-back"
              aria-label="返回全局视图"
              onPointerDown={(event: { stopPropagation(): void }) => event.stopPropagation()}
              onClick={() => {
                if (usesTribeSurvivalMapScene) {
                  restoreTribeOverview(globeRef.current);
                } else {
                  restoreGlobeOverview(globeRef.current);
                }
                hideHoverCard();
                setGlobeFocused(false);
              }}
            >
              <span aria-hidden="true">←</span>
              返回全局视图
            </button>
          ) : null}
          <div ref={hoverElementRef} className="node-hover-card" hidden>
            <strong ref={hoverNameRef} />
            <span ref={hoverMetaRef} />
          </div>
          <div ref={bubbleLayerRef} className="overlay-announcer" aria-live="polite" />
        </div>
      </section>

      <ViewerInteractionBar
        controlState={controlState}
        interventionLog={interventionLog}
        onRunControl={onRunControl}
        onRunIntervention={onRunIntervention}
        onSovereignIntent={onSovereignIntent}
        pendingControl={pendingControl}
        pendingIntervention={pendingIntervention}
        pendingSovereignIntent={pendingSovereignIntent}
        runId={runId}
        runStatus={runStatus}
        runtimeAuthority={runtimeAuthority}
        selected={selected}
        sovereignIntentLog={sovereignIntentLog}
        status={status}
      />

      <ViewerFooter
        causalFocus={causalFocus}
        interventionStatusById={interventionStatusById}
        selectGroundedAction={selectGroundedAction}
        selectGroundedEffect={selectGroundedEffect}
        selected={selected}
        selectedAction={selectedAction}
        selectedDomainSignal={selectedDomainSignal}
        selectedEffect={selectedEffect}
        selectedGoal={selectedGoal}
        selectedMemoryCount={selectedMemoryCount}
        selectedMemoryHighlights={selectedMemoryHighlights}
        selectedMeta={selectedMeta}
        selectedRelationshipFacts={selectedRelationshipFacts}
        selectedStateFacts={selectedStateFacts}
        selectedStatus={selectedStatus}
        selectedStep={selectedStep}
        tick={tick}
        visibleCausalityHistory={visibleCausalityHistory}
        visibleGroundedActions={visibleGroundedActions}
        visibleTraces={visibleTraces}
      />
    </main>
  );
}

export const InteractiveGlobeViewer = memo(
  InteractiveGlobeViewerComponent,
  (previous, next) => (
    previous.projection === next.projection
    && previous.timeline === next.timeline
    && previous.runtimeAuthority === next.runtimeAuthority
    && previous.status === next.status
    && previous.runId === next.runId
    && previous.runStatus === next.runStatus
    && previous.controlState === next.controlState
    && previous.interventionLog === next.interventionLog
    && previous.sovereignIntentLog === next.sovereignIntentLog
    && previous.pendingControl === next.pendingControl
    && previous.pendingIntervention === next.pendingIntervention
    && previous.pendingSovereignIntent === next.pendingSovereignIntent
    && previous.onExitWorld === next.onExitWorld
  ),
);

function sourceAgent(agent: AgentNode, nodes: AgentNode[]) {
  const sourceNodeId = typeof agent.attributes.source_node_id === "string" ? agent.attributes.source_node_id : "";
  return sourceNodeId ? nodes.find((node) => node.id === sourceNodeId) ?? agent : agent;
}

function selectedRelationshipNetworkNodeIds(selected: AgentNode | null, nodes: AgentNode[]) {
  if (!selected) return new Set<string>();
  const sourceSelected = sourceAgent(selected, nodes);
  if (sourceSelected.kind !== "network" || !sourceSelected.parent) return new Set<string>();
  const highlighted = new Set<string>();
  for (const node of nodes) {
    const sourceNode = sourceAgent(node, nodes);
    if (sourceNode.kind === "network" && sourceNode.parent === sourceSelected.parent) {
      highlighted.add(node.id);
    }
  }
  return highlighted;
}

function payloadDelayMs(delay?: number) {
  return Math.max(0, Number(delay ?? 0)) * 1000;
}
