import { lazy, Suspense, useEffect, useRef, useState } from "react";

import {
  addRunIntervention,
  addRunSovereignIntent,
  controlRun,
  createDemoRun,
  getRunProjection,
  getRunTimeline,
  getRuntimeHealth,
  listScenarios,
  retryRun,
  waitForRunCompletion,
} from "../api/client";
import { ProviderConfigDialog } from "./ProviderConfigDialog";
import {
  interventionLogItem,
  interventionPayload,
  markAppliedInterventions,
  prependInterventionLog,
  updateInterventionLogStatus,
} from "./interventions";
import { hydrateFromRunStream } from "./runtime";
import { productScenarioLabel, RUNTIME_PACE_DELAY_MS } from "./runtimeTypes";
import {
  markAppliedSovereignIntents,
  prependSovereignIntentLog,
  sovereignIntentLogItem,
  updateSovereignIntentLogStatus,
} from "./sovereignIntents";
import {
  readRuntimeProviderConfig,
  readProductScenario,
  saveProductScenario,
  saveRuntimeProviderConfig,
  type InterventionTemplate,
  type ProductScenarioId,
  type RunControlCommand,
  type RuntimePace,
  type RuntimeProviderConfig,
} from "./runtimeTypes";
import type {
  Run as RunDetail,
  Scenario,
  TimelineFrame,
  ViewerProjection,
  WorldBootstrapState,
} from "../types/contracts";
import type { InterventionLogItem, SovereignIntentLogItem, StreamTelemetry } from "../types/ui";
import { OfficialWanjieHome } from "../features/wanjie/OfficialWanjieHome";
import { OfficialWanjieWorld } from "../features/wanjie/OfficialWanjieWorld";
import {
  navigateToPath,
  readWorldRoute,
  scenarioForRoute,
} from "./navigation";

const LIVE_DEMO_MIN_TICKS = 100;
const InteractiveGlobeViewer = lazy(async () => {
  const module = await import("../features/viewer/InteractiveGlobeViewer");
  return { default: module.InteractiveGlobeViewer };
});

export function App() {
  const [route, setRoute] = useState(readWorldRoute);
  const [savedProviderConfig] = useState<RuntimeProviderConfig | null>(readRuntimeProviderConfig);
  const [savedScenario] = useState<ProductScenarioId | null>(readProductScenario);
  const [entry, setEntry] = useState<{ scenario: ProductScenarioId; providerConfig: RuntimeProviderConfig } | null>(null);
  const [entryAttempt, setEntryAttempt] = useState(0);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioError, setScenarioError] = useState("");

  useEffect(() => {
    function syncRoute() {
      setRoute(readWorldRoute());
    }
    window.addEventListener("popstate", syncRoute);
    return () => window.removeEventListener("popstate", syncRoute);
  }, []);

  useEffect(() => {
    let active = true;
    listScenarios()
      .then((items) => {
        if (!active) return;
        const productScenarios = items.filter(
          (item) => item.id === "enterprise_earth" || item.id === "tribe_survival",
        );
        setScenarios(productScenarios);
        setScenarioError(productScenarios.length > 0 ? "" : "后端当前没有可用的产品世界。请检查场景目录。 ");
      })
      .catch((error) => {
        if (!active) return;
        setScenarios([]);
        setScenarioError(error instanceof Error ? error.message : "无法加载世界场景");
      });
    return () => {
      active = false;
    };
  }, []);

  if (route.kind === "wanjie") {
    return <OfficialWanjieHome onNavigate={navigateToPath} />;
  }
  if (route.kind === "wanjie-world") {
    return <OfficialWanjieWorld worldId={route.worldId} onNavigate={navigateToPath} />;
  }

  if (!entry) {
    const preselectedScenario = scenarioForRoute(route) ?? savedScenario ?? "enterprise_earth";
    return (
      <ProviderConfigDialog
        initialConfig={savedProviderConfig}
        initialScenario={preselectedScenario}
        scenarios={scenarios}
        scenarioError={scenarioError}
        onSubmit={(scenario, nextConfig) => {
          saveRuntimeProviderConfig(nextConfig);
          saveProductScenario(scenario);
          setEntry({ scenario, providerConfig: nextConfig });
          setEntryAttempt(0);
        }}
      />
    );
  }

  return (
    <RuntimeWorld
      attempt={entryAttempt}
      providerConfig={entry.providerConfig}
      scenario={entry.scenario}
      scenarioCatalog={scenarios}
      onExitWorld={() => {
        setEntry(null);
        navigateToPath("/");
      }}
      onRetry={() => setEntryAttempt((value) => value + 1)}
    />
  );
}

type RuntimeWorldProps = {
  attempt: number;
  providerConfig: RuntimeProviderConfig;
  scenario: ProductScenarioId;
  scenarioCatalog: Scenario[];
  onExitWorld: () => void;
  onRetry: () => void;
};

function RuntimeWorld({ attempt, providerConfig, scenario, scenarioCatalog, onExitWorld, onRetry }: RuntimeWorldProps) {
  const [projection, setProjection] = useState<ViewerProjection | null>(null);
  const [timeline, setTimeline] = useState<TimelineFrame[]>([]);
  const [status, setStatus] = useState("Loading scenarios");
  const [runId, setRunId] = useState("");
  const [runStatus, setRunStatus] = useState<RunDetail["status"] | undefined>(undefined);
  const [controlState, setControlState] = useState<NonNullable<RunDetail["control_state"]>>("active");
  const [runtimeState, setRuntimeState] = useState<Record<string, unknown>>({});
  const [pendingControl, setPendingControl] = useState<RunControlCommand | null>(null);
  const [pendingIntervention, setPendingIntervention] = useState<InterventionTemplate | null>(null);
  const [pendingSovereignIntent, setPendingSovereignIntent] = useState(false);
  const [interventionLog, setInterventionLog] = useState<InterventionLogItem[]>([]);
  const [sovereignIntentLog, setSovereignIntentLog] = useState<SovereignIntentLogItem[]>([]);
  const [runtimePace, setRuntimePace] = useState<RuntimePace>("normal");
  const [streamTelemetry, setStreamTelemetry] = useState<StreamTelemetry | null>(null);
  const [bootstrapState, setBootstrapState] = useState<WorldBootstrapState>({
    phase: "creating_world",
    scenario_id: scenario,
    provider_mode: providerConfig.mode,
    ready: false,
    retryable: true,
  });
  const [bootstrapError, setBootstrapError] = useState("");
  const [retryPending, setRetryPending] = useState(false);
  const runtimePaceDelayRef = useRef(RUNTIME_PACE_DELAY_MS.normal);
  const initializationRef = useRef<Promise<RunDetail> | null>(null);
  const initializationAttemptRef = useRef(attempt);
  if (initializationAttemptRef.current !== attempt) {
    initializationAttemptRef.current = attempt;
    initializationRef.current = null;
  }

  useEffect(() => {
    setInterventionLog((items) => markAppliedInterventions(items, projection));
    setSovereignIntentLog((items) => markAppliedSovereignIntents(items, projection));
  }, [projection]);

  useEffect(() => {
    runtimePaceDelayRef.current = RUNTIME_PACE_DELAY_MS[runtimePace];
  }, [runtimePace]);

  useEffect(() => {
    let cancelled = false;

    setProjection(null);
    setTimeline([]);
    setRunId("");
    setRunStatus(undefined);
    setControlState("active");
    setRuntimeState({});
    setPendingControl(null);
    setPendingIntervention(null);
    setPendingSovereignIntent(false);
    setInterventionLog([]);
    setSovereignIntentLog([]);
    setStreamTelemetry(null);
    setBootstrapError("");
    setRetryPending(false);
    setStatus(`Checking Engine runtime · ${scenario}`);

    async function boot() {
      try {
        if (!initializationRef.current) {
          initializationRef.current = (async () => {
            const health = await getRuntimeHealth();
            if (!health.runtime_ready) {
              throw new Error(health.reason || `Worker mode ${health.worker_mode} cannot advance Runs`);
            }
            const scenarioList = await listScenarios();
            const selectedScenario = scenarioList.find((item) => item.id === scenario);
            if (!selectedScenario) throw new Error(`Engine scenario unavailable: ${scenario}`);
            const defaultTicks = typeof selectedScenario.defaults?.ticks === "number" ? selectedScenario.defaults.ticks : 7;
            const createdRun = await createDemoRun({
              scenario,
              seed: 7,
              ticks: Math.max(defaultTicks, LIVE_DEMO_MIN_TICKS),
              runtimeProvider: providerConfig,
              requireCognitionReady: true,
            });
            if (!createdRun.id) {
              throw new Error(String(createdRun.error || "Engine did not create a Run"));
            }
            return createdRun;
          })();
        }
        const createdRun = await initializationRef.current;
        if (cancelled) return;
        setRunId(createdRun.id);
        setRunStatus(createdRun.status);
        setControlState(createdRun.control_state ?? "active");
        setRuntimeState(createdRun.runtime_state ?? {});
        setBootstrapState(bootstrapStateFrom(createdRun.bootstrap_state, createdRun.runtime_state, scenario, providerConfig.mode));
        setInterventionLog([]);
        setSovereignIntentLog([]);
        setStreamTelemetry(null);
        let run = createdRun;
        let latestControlState = createdRun.control_state ?? "active";
        let latestRuntimeState = createdRun.runtime_state ?? {};
        let latestBootstrapState = bootstrapStateFrom(createdRun.bootstrap_state, createdRun.runtime_state, scenario, providerConfig.mode);
        let nextProjection = createdRun.projection?.summary ? createdRun.projection : null;
        let nextTimeline = createdRun.timeline && createdRun.timeline.length > 0 ? createdRun.timeline : [];
        if (nextProjection) setProjection(nextProjection);
        if (nextTimeline.length > 0) setTimeline(nextTimeline);
        const streamResult = await hydrateFromRunStream(
          createdRun,
          {
            onProjection: (streamProjection) => {
              if (cancelled) return;
              nextProjection = streamProjection;
              setProjection(streamProjection);
            },
            onTimeline: (streamTimeline) => {
              if (cancelled) return;
              nextTimeline = streamTimeline;
              setTimeline(streamTimeline);
            },
            onStatus: (message) => {
              if (!cancelled) setStatus(message);
            },
            onRunStatus: (nextStatus) => {
              if (!cancelled) setRunStatus(nextStatus);
            },
            onControlState: (streamControlState) => {
              if (cancelled) return;
              latestControlState = streamControlState;
              setControlState(streamControlState);
            },
            onRuntimeState: (streamRuntimeState) => {
              if (cancelled) return;
              latestRuntimeState = streamRuntimeState;
              setRuntimeState(streamRuntimeState);
            },
            onBootstrapState: (nextBootstrapState) => {
              if (cancelled) return;
              latestBootstrapState = nextBootstrapState;
              setBootstrapState(nextBootstrapState);
            },
            onStreamTelemetry: (nextTelemetry) => {
              if (!cancelled) setStreamTelemetry(nextTelemetry);
            },
            getDelayMs: () => runtimePaceDelayRef.current,
          },
        );
        if (cancelled) return;
        if (streamResult.completed) {
          run = {
            ...createdRun,
            status: streamResult.status,
            control_state: latestControlState,
            runtime_state: latestRuntimeState,
            bootstrap_state: latestBootstrapState,
          };
        } else {
          run = createdRun.status === "completed"
            ? createdRun
            : await waitForRunCompletion(
                createdRun.id,
                (nextRun) => {
                  if (!cancelled) {
                    latestControlState = nextRun.control_state ?? "active";
                    latestRuntimeState = nextRun.runtime_state ?? {};
                    latestBootstrapState = bootstrapStateFrom(nextRun.bootstrap_state, nextRun.runtime_state, scenario, providerConfig.mode);
                    setStatus(`Run ${nextRun.status}`);
                    setRunStatus(nextRun.status);
                    setControlState(latestControlState);
                    setRuntimeState(latestRuntimeState);
                    setBootstrapState(latestBootstrapState);
                  }
                },
              );
        }
        if (cancelled) return;
        setRunStatus(run.status);
        setControlState(run.control_state ?? "active");
        setRuntimeState(run.runtime_state ?? {});
        setBootstrapState(latestBootstrapState);
        const finalProjection = nextProjection?.summary
          ? nextProjection
          : run.projection?.summary
            ? run.projection
          : await getRunProjection(run.id);
        const finalTimeline = nextTimeline.length > 0
          ? nextTimeline
          : run.timeline && run.timeline.length > 0
          ? run.timeline
          : (await getRunTimeline(run.id)).timeline;
        setProjection(finalProjection);
        setTimeline(finalTimeline);
        setStatus(finalTimeline.length > 0 ? `Run ${run.status} · ${finalTimeline.length} frame timeline` : `Run ${run.status}`);
      } catch (error) {
        if (cancelled) return;
        const reason = error instanceof Error ? error.message : "Unable to load world";
        setBootstrapError(reason);
        setStatus(reason);
        setBootstrapState((current) => (
          current.phase === "failed" || current.phase === "timed_out" || current.phase === "canceled"
            ? current
            : { ...current, phase: "failed", ready: false, retryable: true, error_code: "web_bootstrap_failed", error_message: reason }
        ));
      }
    }

    boot();
    return () => {
      cancelled = true;
    };
  }, [attempt, providerConfig, scenario]);

  async function handleRunControl(command: RunControlCommand) {
    if (!runId || pendingControl) return;
    setPendingControl(command);
    try {
      const response = await controlRun(runId, {
        command,
        reason: "web-runtime-control",
        actor_id: "web-operator",
      });
      setRunStatus(response.status);
      setControlState(response.control_state);
      setStatus(response.error ? `Run control rejected · ${response.error}` : `Run ${response.status} · control ${response.control_state}`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Run control failed");
    } finally {
      setPendingControl(null);
    }
  }

  async function handleBootstrapRetry() {
    if (retryPending) return;
    if (!runId) {
      onRetry();
      return;
    }
    setRetryPending(true);
    setBootstrapError("");
    try {
      const response = await retryRun(runId, { runtime_provider: providerConfig });
      if (!response.run?.id) {
        throw new Error("后端没有创建可重试的世界");
      }
      initializationRef.current = Promise.resolve(response.run);
      initializationAttemptRef.current = attempt + 1;
      onRetry();
    } catch (error) {
      const reason = error instanceof Error ? error.message : "重新创建世界失败";
      setBootstrapError(reason);
      setStatus(reason);
      setRetryPending(false);
    }
  }

  async function handleRunIntervention(nodeId: string, nodeName: string, template: InterventionTemplate) {
    if (!runId || pendingIntervention) return;
    const tickCursor = typeof runtimeState.tick_cursor === "number" ? runtimeState.tick_cursor : 0;
    const intervention = interventionPayload(template, nodeId, nodeName, tickCursor);
    const logItem = interventionLogItem(intervention, template, nodeId, nodeName, tickCursor);
    setInterventionLog((items) => prependInterventionLog(items, logItem));
    setPendingIntervention(template);
    try {
      const response = await addRunIntervention(runId, intervention);
      setRunStatus(response.status);
      if (response.error) {
        setInterventionLog((items) => updateInterventionLogStatus(items, intervention.id, "rejected", response.error));
      }
      setStatus(
        response.error
          ? `Intervention rejected · ${response.error}`
          : `${intervention.summary} queued · ${response.intervention_count ?? 1} total`,
      );
    } catch (error) {
      setInterventionLog((items) => updateInterventionLogStatus(
        items,
        intervention.id,
        "rejected",
        error instanceof Error ? error.message : "Intervention failed",
      ));
      setStatus(error instanceof Error ? error.message : "Intervention failed");
    } finally {
      setPendingIntervention(null);
    }
  }

  async function handleSovereignIntent(text: string) {
    const trimmed = text.trim();
    if (!runId || pendingSovereignIntent || !trimmed) return;
    const tickCursor = typeof runtimeState.tick_cursor === "number" ? runtimeState.tick_cursor : 0;
    setPendingSovereignIntent(true);
    try {
      const response = await addRunSovereignIntent(runId, {
        text: trimmed,
        actor_id: "web-sovereign",
        scheduled_tick: tickCursor,
      });
      setRunStatus(response.status);
      if (response.error || !response.sovereign_intent) {
        const rejected = sovereignIntentLogItem(
          { id: `web-sovereign-rejected-${Date.now()}`, summary: trimmed },
          trimmed,
          tickCursor,
        );
        setSovereignIntentLog((items) => prependSovereignIntentLog(items, { ...rejected, status: "rejected", error: response.error }));
      } else {
        const logItem = sovereignIntentLogItem(response.sovereign_intent, trimmed, tickCursor);
        setSovereignIntentLog((items) => prependSovereignIntentLog(items, logItem));
      }
      setStatus(
        response.error
          ? `旨意被拒绝 · ${response.error}`
          : `国王视角下旨 queued · ${response.sovereign_intent_count ?? 1} total`,
      );
    } catch (error) {
      const rejected = sovereignIntentLogItem(
        { id: `web-sovereign-failed-${Date.now()}`, summary: trimmed },
        trimmed,
        tickCursor,
      );
      setSovereignIntentLog((items) => prependSovereignIntentLog(
        updateSovereignIntentLogStatus(items, rejected.id, "rejected", error instanceof Error ? error.message : "下旨失败"),
        { ...rejected, status: "rejected", error: error instanceof Error ? error.message : "下旨失败" },
      ));
      setStatus(error instanceof Error ? error.message : "下旨失败");
    } finally {
      setPendingSovereignIntent(false);
    }
  }

  const readyToEnter = bootstrapState.phase === "ready" && bootstrapState.ready && Boolean(projection?.summary);
  if (!readyToEnter) {
    return (
      <WorldBootstrapScreen
        bootstrapError={bootstrapError}
        bootstrapState={bootstrapState}
        onExitWorld={onExitWorld}
        onRetry={handleBootstrapRetry}
        providerConfig={providerConfig}
        retryPending={retryPending}
        scenario={scenario}
        scenarioName={productScenarioLabel(scenario)}
      />
    );
  }

  return (
    <Suspense fallback={<main className="viewer-shell viewer-loading">Loading interactive world…</main>}>
      <InteractiveGlobeViewer
      controlState={controlState}
      onRunIntervention={handleRunIntervention}
      onRunControl={handleRunControl}
      onSovereignIntent={handleSovereignIntent}
      interventionLog={interventionLog}
      sovereignIntentLog={sovereignIntentLog}
      runtimePace={runtimePace}
      runtimeAuthority="authoritative_engine"
      onRuntimePaceChange={setRuntimePace}
      streamTelemetry={streamTelemetry}
      pendingControl={pendingControl}
      pendingIntervention={pendingIntervention}
      pendingSovereignIntent={pendingSovereignIntent}
      projection={projection}
      runId={runId}
      runStatus={runStatus}
      runtimeState={runtimeState}
      scenarioCount={scenarioCatalog.length}
      onExitWorld={onExitWorld}
      status={status}
      timeline={timeline}
      />
    </Suspense>
  );
}

type WorldBootstrapScreenProps = {
  bootstrapError: string;
  bootstrapState: WorldBootstrapState;
  onExitWorld: () => void;
  onRetry: () => void;
  providerConfig: RuntimeProviderConfig;
  retryPending: boolean;
  scenario: ProductScenarioId;
  scenarioName: string;
};

function WorldBootstrapScreen({
  bootstrapError,
  bootstrapState,
  onExitWorld,
  onRetry,
  providerConfig,
  retryPending,
  scenario,
  scenarioName,
}: WorldBootstrapScreenProps) {
  const [now, setNow] = useState(Date.now());
  const terminal = bootstrapState.phase === "failed"
    || bootstrapState.phase === "timed_out"
    || bootstrapState.phase === "canceled"
    || Boolean(bootstrapError);

  useEffect(() => {
    if (terminal) return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [terminal]);

  const startedAt = Date.parse(bootstrapState.started_at ?? "");
  const elapsedSeconds = Number.isFinite(startedAt) ? Math.max((now - startedAt) / 1000, 0) : 0;
  const deadlineAt = Date.parse(bootstrapState.deadline_at ?? "");
  const deadlineText = Number.isFinite(deadlineAt)
    ? `${Math.max((deadlineAt - now) / 1000, 0).toFixed(1)} 秒后超时`
    : "等待后端 Provider 时限";
  const errorMessage = bootstrapError || bootstrapState.error_message || bootstrapState.error_code || "世界启动失败";

  return (
    <main className="world-bootstrap-shell" data-phase={bootstrapState.phase} data-scenario={scenario}>
      <section className="world-bootstrap-card" aria-live="polite">
        <div className="provider-config-kicker">LLM WORLD LOADING</div>
        <h1>{terminal ? "暂时无法进入世界" : `正在唤醒${scenarioName}`}</h1>
        <p className="world-bootstrap-copy">
          {terminal ? errorMessage : bootstrapPhaseMessage(bootstrapState.phase, Boolean(projectionReadyEvidence(bootstrapState)))}
        </p>
        <dl className="world-bootstrap-facts">
          <div><dt>世界</dt><dd>{scenarioName}</dd></div>
          <div><dt>Provider</dt><dd>{providerConfig.mode === "deterministic" ? "本地确定性调试" : providerConfig.model || providerConfig.mode}</dd></div>
          <div><dt>阶段</dt><dd>{bootstrapState.phase}</dd></div>
          <div><dt>耗时</dt><dd>{elapsedSeconds.toFixed(1)} 秒</dd></div>
          {!terminal ? <div><dt>时限</dt><dd>{deadlineText}</dd></div> : null}
        </dl>
        {!terminal ? <div className="world-bootstrap-pulse" aria-hidden="true"><i /><i /><i /></div> : null}
        <div className="world-bootstrap-actions">
          {terminal ? <button type="button" disabled={retryPending} onClick={onRetry}>{retryPending ? "正在重新创建…" : "重新创建世界"}</button> : null}
          <button className="secondary" type="button" onClick={onExitWorld}>返回配置</button>
        </div>
        <p className="provider-config-notice">
          世界会按原有规则持续运行；首个有效模型思考进入投影后，加载页即会移除。
        </p>
      </section>
    </main>
  );
}

function bootstrapStateFrom(
  explicit: WorldBootstrapState | undefined,
  runtimeState: Record<string, unknown> | undefined,
  scenario: ProductScenarioId,
  providerMode: string,
): WorldBootstrapState {
  if (explicit?.phase) return explicit;
  const nested = runtimeState?.bootstrap_state;
  if (nested && typeof nested === "object" && typeof (nested as { phase?: unknown }).phase === "string") {
    return nested as WorldBootstrapState;
  }
  return {
    phase: "creating_world",
    scenario_id: scenario,
    provider_mode: providerMode,
    ready: false,
    retryable: true,
  };
}

function projectionReadyEvidence(state: WorldBootstrapState): boolean {
  return Boolean(state.ready_projection_sequence && (state.accepted_thought_sequences?.length ?? 0) > 0);
}

function bootstrapPhaseMessage(phase: WorldBootstrapState["phase"], hasEvidence: boolean): string {
  const messages: Record<WorldBootstrapState["phase"], string> = {
    creating_world: "正在创建 tick-0 世界快照。",
    dispatching_cognition: "正在把同一份世界快照交给模型观察。",
    waiting_provider: "模型正在理解局势；世界仍按原有规则持续运行。",
    committing_pressure: "正在接收并校验模型输出。",
    grounding_actions: "正在同步模型输出与世界投影。",
    projecting_ready_world: "首个模型思考已收到，正在生成可展示投影。",
    ready: hasEvidence ? "世界已经准备完成。" : "正在等待 ready 投影。",
    legacy_ready: "旧版世界记录没有首轮模型思考证据。",
    failed: "首轮模型请求没有返回可展示的思考。",
    timed_out: "首轮模型响应已超时。",
    canceled: "世界启动已取消。",
  };
  return messages[phase];
}
