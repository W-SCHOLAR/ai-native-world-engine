import type { FormEvent } from "react";

import type { InterventionTemplate, RuntimePace } from "../../app/runtimeTypes";
import type { TimelineFrame } from "../../types/contracts";
import type { InterventionLogItem, SovereignIntentLogItem, StreamTelemetry } from "../../types/ui";
import {
  actionLabel,
  causalPathRoleLabel,
  domainActionMatches,
  interventionStatusLabel,
  pick,
  targetNames,
  traceText,
} from "./projectionModel";
import { RUNTIME_PACE_OPTIONS, runtimePaceLabel, telemetryValue } from "./timelineModel";
import type {
  ActionCoverage,
  AgentNode,
  AiCausalityHistoryItem,
  AiTrace,
  CausalFocus,
  DomainSignal,
  DomainSignalHistory,
  GovernanceNotice,
  GroundedAction,
  GroundedEffect,
  MemoryHighlight,
  MemoryMaintenanceFact,
  MemoryMaintenanceRow,
  NormalizedWorld,
  RelationshipFact,
  RunHealthFact,
  RuntimeMetrics,
  StateFact,
} from "./viewerTypes";
import { WORLD_ACTION_LABELS } from "./viewerTypes";

type RunControlCommand = "pause" | "resume" | "cancel";

type ViewerHeaderProps = {
  world: NormalizedWorld;
  sceneTitle: string;
  onExitWorld?: () => void;
  onOpenShowcase?: () => void;
  tick: number;
  scenarioCount: number;
  hasTimeline: boolean;
  isFollowingLatest: boolean;
  isPlaying: boolean;
  setIsPlaying: (value: boolean | ((current: boolean) => boolean)) => void;
  setIsFollowingLatest: (value: boolean | ((current: boolean) => boolean)) => void;
  stepFrame: (delta: number) => void;
  currentFrame: number;
  frameCount: number;
  scrubTimeline: (frame: number) => void;
  returnToLiveFrame: () => void;
  status: string;
  controlLabel: string;
  runtimeMetrics: RuntimeMetrics;
  streamTelemetry: StreamTelemetry | null;
  runtimePace: RuntimePace;
  runtimeAuthority: "authoritative_engine" | "static_visual_demo" | "local_projection_fallback";
  onRuntimePaceChange?: (pace: RuntimePace) => void;
  canControlRun: boolean;
  onRunControl?: (command: RunControlCommand) => void;
  pendingControl: RunControlCommand | null;
  controlState: "active" | "paused" | "canceled";
  terminalRun: boolean;
  canIntervene: boolean;
  selected: AgentNode | null;
  pendingIntervention: InterventionTemplate | null;
  onRunIntervention?: (nodeId: string, nodeName: string, template: InterventionTemplate) => void;
  interventionTemplates: Array<{ id: InterventionTemplate; label: string }>;
  sovereignIntentText: string;
  setSovereignIntentText: (value: string | ((current: string) => string)) => void;
  submitSovereignIntent: (event: FormEvent<HTMLFormElement>) => void;
  canIssueSovereignIntent: boolean;
  pendingSovereignIntent: boolean;
  visibleInterventionLog: InterventionLogItem[];
  visibleSovereignIntentLog: SovereignIntentLogItem[];
  actionByInterventionId: Map<string, GroundedAction>;
  selectInterventionLogItem: (item: InterventionLogItem) => void;
  healthFacts: RunHealthFact[];
  scenarioGovernanceNotice: GovernanceNotice;
  memoryFacts: MemoryMaintenanceFact[];
  memoryRows: MemoryMaintenanceRow[];
  globalDomainSignals: DomainSignal[];
  selectedDomainSignalKey: string;
  selectDomainSignal: (key: string) => void;
  domainHistoryByKey: Record<string, DomainSignalHistory>;
  selectedDomainEvidenceCount: number;
  selectedDomainRecentEvidenceCount: number;
  selectedDomainSignal: DomainSignal | null;
  actionCoverage: ActionCoverage;
};

export function ViewerHeader(props: ViewerHeaderProps) {
  const {
    world, sceneTitle, onExitWorld, onOpenShowcase, tick, scenarioCount,
    hasTimeline, isFollowingLatest, isPlaying, setIsPlaying, setIsFollowingLatest,
    stepFrame, currentFrame, frameCount, scrubTimeline, returnToLiveFrame, status,
    controlLabel, runtimeMetrics, streamTelemetry, runtimePace, runtimeAuthority, onRuntimePaceChange,
    canControlRun, onRunControl, pendingControl, controlState, terminalRun,
    canIntervene, selected, pendingIntervention, onRunIntervention,
    interventionTemplates: INTERVENTION_TEMPLATES, sovereignIntentText,
    setSovereignIntentText, submitSovereignIntent, canIssueSovereignIntent,
    pendingSovereignIntent, visibleInterventionLog, visibleSovereignIntentLog,
    actionByInterventionId, selectInterventionLogItem, healthFacts,
    scenarioGovernanceNotice, memoryFacts, memoryRows, globalDomainSignals,
    selectedDomainSignalKey, selectDomainSignal, domainHistoryByKey,
    selectedDomainEvidenceCount, selectedDomainRecentEvidenceCount,
    selectedDomainSignal, actionCoverage,
  } = props;
  return (
      <header className="world-hud" aria-label="世界状态">
        <div>
          <h1>{sceneTitle}</h1>
          <div className="runtime-authority-badge" data-authority={runtimeAuthority} aria-label="运行时来源">
            <i />
            <span>{runtimeAuthority === "authoritative_engine" ? "PYTHON ENGINE" : runtimeAuthority === "static_visual_demo" ? "STATIC VISUAL DEMO" : "LOCAL FALLBACK"}</span>
          </div>
          <div className="scene-mode-tabs" aria-label="世界场景">
            <button className="return-to-book" onClick={onExitWorld} type="button">
              返回引擎控制台
            </button>
            <button className="open-showcase" onClick={onOpenShowcase} type="button">探索世界展示</button>
          </div>
        </div>
        <div className="runtime-panel" hidden>
          <div className="runtime-authority" data-authority={runtimeAuthority} aria-label="运行时权威边界">
            <b>{runtimeAuthority === "authoritative_engine" ? "AUTHORITATIVE PYTHON ENGINE" : runtimeAuthority === "static_visual_demo" ? "STATIC VISUAL DEMO" : "LOCAL PROJECTION FALLBACK"}</b>
            <span>{runtimeAuthority === "authoritative_engine" ? "当前 worldline 由 Python Engine 运行；压力、规则、行动与追踪均可审计。" : runtimeAuthority === "static_visual_demo" ? "当前为浏览器本地可视化样例，不是权威 Engine worldline，运行控制与世界写入不可用。" : "API 不可用时显示本地投影；它只用于观察，不能声明世界状态权威。"}</span>
          </div>
          <dl className="stats">
            <div>
              <dt>Tick</dt>
              <dd>{tick}</dd>
            </div>
            <div>
              <dt>关系网</dt>
              <dd>{world.organizationCount}</dd>
            </div>
            <div>
              <dt>场景</dt>
              <dd>{scenarioCount}</dd>
            </div>
          </dl>
          <div className="timeline-controls" data-enabled={hasTimeline ? "yes" : "no"} data-live={isFollowingLatest ? "yes" : "no"}>
            <button type="button" aria-label="Previous frame" disabled={!hasTimeline} onClick={() => stepFrame(-1)}>
              &lt;
            </button>
            <button
              type="button"
              aria-label={isPlaying ? "Pause timeline" : "Play timeline"}
              disabled={!hasTimeline}
              onClick={() => {
                setIsFollowingLatest(false);
                setIsPlaying((value) => !value);
              }}
            >
              {isPlaying ? "||" : ">"}
            </button>
            <button type="button" aria-label="Next frame" disabled={!hasTimeline} onClick={() => stepFrame(1)}>
              &gt;
            </button>
            <input
              aria-label="Timeline frame"
              disabled={!hasTimeline}
              max={Math.max(frameCount - 1, 0)}
              min="0"
              onChange={(event: { target: { value: string } }) => scrubTimeline(Number(event.target.value))}
              type="range"
              value={currentFrame}
            />
            <span>{hasTimeline ? `${currentFrame + 1}/${frameCount}` : "0/0"}</span>
            <button
              aria-label="Follow latest streamed frame"
              aria-pressed={isFollowingLatest}
              className="timeline-live-button"
              disabled={!hasTimeline}
              onClick={returnToLiveFrame}
              type="button"
            >
              Live
            </button>
          </div>
          <section className="run-control-panel" aria-label="运行控制">
            <div className="run-control-head">
              <p className="eyebrow">Run Control</p>
              <span>{controlLabel}</span>
            </div>
            <div className="runtime-progress" data-state={runtimeMetrics.state}>
              <div className="runtime-progress-head">
                <strong>{runtimeMetrics.tickLabel}</strong>
                <em>{runtimeMetrics.percentLabel}</em>
              </div>
              <div className="runtime-progress-bar" aria-hidden="true">
                <i style={{ width: `${runtimeMetrics.percent}%` }} />
              </div>
              <div className="runtime-facts" aria-label="运行态指标">
                <span><b>Mode</b><em>{runtimeMetrics.mode}</em></span>
                <span><b>Step</b><em>{runtimeMetrics.lastStepStatus}</em></span>
                <span><b>Pace</b><em>{runtimePaceLabel(runtimePace)}</em></span>
              </div>
              <div className="stream-telemetry" aria-label="流式更新遥测">
                <span><b>Cursor</b><em>{telemetryValue(streamTelemetry?.cursor)}</em></span>
                <span><b>Next</b><em>{telemetryValue(streamTelemetry?.nextCursor)}</em></span>
                <span><b>Batch</b><em>{telemetryValue(streamTelemetry?.updateBatchSize)}</em></span>
                <span><b>Frames</b><em>{telemetryValue(streamTelemetry?.timelineFrameCount ?? frameCount)}</em></span>
                <span><b>Window</b><em>{telemetryValue(streamTelemetry ? `${streamTelemetry.retainedFromCursor ?? 0}-${streamTelemetry.retainedToCursor ?? 0}` : undefined)}</em></span>
                <span><b>History</b><em>{streamTelemetry?.cursorExpired ? "expired" : "ok"}</em></span>
              </div>
              <div className="run-health-panel" aria-label="运行健康">
                {healthFacts.map((fact) => (
                  <span data-state={fact.state} key={fact.key}>
                    <b>{fact.label}</b>
                    <em>{fact.value}</em>
                  </span>
                ))}
              </div>
              <div className="governance-notice" data-state={scenarioGovernanceNotice.state} aria-label="场景治理提示">
                <b>{scenarioGovernanceNotice.label}</b>
                <span>{scenarioGovernanceNotice.scenario} · {scenarioGovernanceNotice.riskLevel}</span>
                <p>{scenarioGovernanceNotice.message}</p>
              </div>
              <div className="memory-maintenance-panel" aria-label="世界记忆维护">
                <div className="memory-maintenance-facts">
                  {memoryFacts.map((fact) => (
                    <span data-state={fact.state} key={fact.key}>
                      <b>{fact.label}</b>
                      <em>{fact.value}</em>
                    </span>
                  ))}
                </div>
                <div className="memory-maintenance-rows">
                  {memoryRows.length > 0 ? memoryRows.map((row) => (
                    <article className="memory-maintenance-row" data-kind={row.kind} key={`${row.nodeId}-${row.tick}-${row.text}`}>
                      <p>{row.text}</p>
                      <span>
                        {row.nodeId}
                        {row.tick !== "" ? ` · T${row.tick}` : ""}
                        {row.memoryCount > 0 ? ` · ${row.memoryCount} memories` : ""}
                        {row.forgottenCount > 0 ? ` · ${row.forgottenCount} forgotten` : ""}
                      </span>
                    </article>
                  )) : (
                    <span className="memory-maintenance-empty">Memory idle</span>
                  )}
                </div>
              </div>
            </div>
            <div className="run-control-buttons">
              <button
                disabled={!canControlRun || controlState === "paused" || Boolean(pendingControl)}
                onClick={() => onRunControl?.("pause")}
                type="button"
              >
                {pendingControl === "pause" ? "Pausing" : "Pause"}
              </button>
              <button
                disabled={!canControlRun || controlState !== "paused" || Boolean(pendingControl)}
                onClick={() => onRunControl?.("resume")}
                type="button"
              >
                {pendingControl === "resume" ? "Resuming" : "Resume"}
              </button>
              <button
                data-danger="yes"
                disabled={!canControlRun || Boolean(pendingControl)}
                onClick={() => onRunControl?.("cancel")}
                type="button"
              >
                {pendingControl === "cancel" ? "Canceling" : "Cancel"}
              </button>
            </div>
            <div className="runtime-pace-controls" aria-label="运行速度">
              {RUNTIME_PACE_OPTIONS.map((option) => (
                <button
                  aria-pressed={runtimePace === option.id}
                  data-pace={option.id}
                  key={option.id}
                  onClick={() => onRuntimePaceChange?.(option.id)}
                  type="button"
                >
                  {option.label}
                </button>
              ))}
            </div>
            <form className="sovereign-intent-panel" aria-label="国王视角下旨" onSubmit={submitSovereignIntent}>
              <div className="sovereign-intent-head">
                <p className="eyebrow">国王视角</p>
                <span>{pendingSovereignIntent ? "Queuing" : canIssueSovereignIntent ? "Ready" : "Offline"}</span>
              </div>
              <div className="sovereign-intent-input-row">
                <input
                  aria-label="旨意"
                  disabled={!canIssueSovereignIntent}
                  maxLength={180}
                  onChange={(event: { target: { value: string } }) => setSovereignIntentText(event.target.value)}
                  placeholder="让天下..."
                  type="text"
                  value={sovereignIntentText}
                />
                <button disabled={!canIssueSovereignIntent || sovereignIntentText.trim().length === 0} type="submit">
                  下旨
                </button>
              </div>
              {visibleSovereignIntentLog.length > 0 ? (
                <div className="sovereign-intent-log" aria-label="旨意回执">
                  {visibleSovereignIntentLog.map((item) => (
                    <article className="sovereign-intent-log-row" data-status={item.status} key={item.id}>
                      <strong>{item.title}</strong>
                      <span>T{item.scheduledTick} · {item.impactLevel}</span>
                      <em>{sovereignIntentStatusLabel(item)}</em>
                    </article>
                  ))}
                </div>
              ) : null}
            </form>
            <div className="intervention-template-list" aria-label="干预模板">
              {INTERVENTION_TEMPLATES.map((template) => (
                <button
                  className="intervention-button"
                  data-template={template.id}
                  disabled={!canIntervene}
                  key={template.id}
                  onClick={() => selected && onRunIntervention?.(selected.id, selected.name, template.id)}
                  type="button"
                >
                  {pendingIntervention === template.id ? "Queuing" : template.label}
                </button>
              ))}
            </div>
            {visibleInterventionLog.length > 0 ? (
              <div className="intervention-log" aria-label="干预回执">
                {visibleInterventionLog.map((item) => {
                  const hasGroundedAction = actionByInterventionId.has(item.id);
                  return (
                    <article
                      className="intervention-log-row"
                      data-action-linked={hasGroundedAction ? "yes" : "no"}
                      data-status={item.status}
                      key={item.id}
                    >
                      <button
                        className="intervention-log-select"
                        disabled={!hasGroundedAction}
                        onClick={() => selectInterventionLogItem(item)}
                        type="button"
                      >
                        <strong>{item.summary}</strong>
                        <span>{item.targetName} · T{item.scheduledTick}</span>
                      </button>
                      <em>{interventionStatusLabel(item)}</em>
                    </article>
                  );
                })}
              </div>
            ) : null}
          </section>
          <section className="domain-signals" aria-label="全局领域状态">
            <div className="domain-signals-head">
              <div>
                <p className="eyebrow">Domain Signals</p>
                <strong>世界状态信号</strong>
              </div>
              <span>{globalDomainSignals.length || "--"}</span>
            </div>
            <div className="domain-signal-list">
              {globalDomainSignals.length > 0 ? globalDomainSignals.map((signal) => (
                <button
                  aria-pressed={selectedDomainSignalKey === signal.key}
                  className="domain-signal-chip"
                  data-state={signal.state}
                  key={signal.key}
                  onClick={() => selectDomainSignal(signal.key)}
                  type="button"
                >
                  <b>{signal.label}</b>
                  <strong>{signal.value}</strong>
                  <em>{signal.detail}</em>
                  <span className="domain-signal-trend" aria-label={`${signal.label} timeline trend`}>
                    {(domainHistoryByKey[signal.key]?.points || []).map((point, index) => (
                      <i
                        data-present={point.present ? "yes" : "no"}
                        data-state={point.state}
                        key={`${signal.key}-${point.tick}-${index}`}
                        title={point.present ? `T${point.tick}: ${point.value}` : `T${point.tick}: no signal`}
                      />
                    ))}
                  </span>
                </button>
              )) : (
                <span className="domain-signal-empty">等待 domain summary</span>
              )}
            </div>
            {selectedDomainSignal ? (
              <p className="domain-evidence-line">
                {selectedDomainSignal.label} evidence · {selectedDomainEvidenceCount} current · {selectedDomainRecentEvidenceCount} recent
              </p>
            ) : null}
          </section>
          <section className="action-coverage" aria-label="真实动作覆盖">
            <div className="action-coverage-head">
              <div>
                <p className="eyebrow">Grounded Actions</p>
                <strong>规则动作覆盖</strong>
              </div>
              <span>{actionCoverage.hasSummary ? `${actionCoverage.coveragePct}%` : "--"}</span>
            </div>
            <div className="coverage-bar" aria-hidden="true">
              <i style={{ width: `${actionCoverage.hasSummary ? actionCoverage.coveragePct : 0}%` }} />
            </div>
            <p className="coverage-line">
              {actionCoverage.hasSummary
                ? `${actionCoverage.hitCount}/${actionCoverage.totalCount} 类命中 · ${actionCoverage.missingCount} 个缺口`
                : "等待 scorecard action summary"}
            </p>
            <div className="action-chip-list">
              {(actionCoverage.rows.length > 0 ? actionCoverage.rows : WORLD_ACTION_LABELS.map(([action, label]) => ({
                action,
                label,
                count: 0,
                state: "idle" as const,
              }))).map((row) => (
                <span className="action-chip" data-state={row.state} key={row.action} title={row.action}>
                  <b>{row.label}</b>
                  <em>{row.count}</em>
                </span>
              ))}
            </div>
          </section>
        </div>
      </header>


  );
}

type ViewerFooterProps = {
  selected: AgentNode | null;
  selectedMeta: string;
  selectedStatus: string;
  selectedGoal: string;
  selectedStep: string;
  tick: number;
  selectedStateFacts: StateFact[];
  selectedMemoryCount: number;
  selectedMemoryHighlights: MemoryHighlight[];
  selectedRelationshipFacts: RelationshipFact[];
  selectedAction: GroundedAction | null;
  selectedEffect: GroundedEffect | null;
  causalFocus: CausalFocus | null;
  selectGroundedEffect: (action: GroundedAction, effect: GroundedEffect) => void;
  visibleGroundedActions: GroundedAction[];
  selectedDomainSignal: DomainSignal | null;
  interventionStatusById: Map<string, string>;
  selectGroundedAction: (action: GroundedAction) => void;
  visibleCausalityHistory: AiCausalityHistoryItem[];
  visibleTraces: AiTrace[];
};

export function ViewerFooter(props: ViewerFooterProps) {
  const {
    selected, selectedMeta, selectedStatus, selectedGoal, selectedStep, tick,
    selectedStateFacts, selectedMemoryCount, selectedMemoryHighlights,
    selectedRelationshipFacts, selectedAction, selectedEffect, causalFocus,
    selectGroundedEffect, visibleGroundedActions, selectedDomainSignal,
    interventionStatusById, selectGroundedAction, visibleCausalityHistory,
    visibleTraces,
  } = props;
  return (
      <footer className="node-dock" aria-label="节点详情">
        <section className="detail-panel">
          <p className="eyebrow">Selected Node</p>
          <h2>{selected?.name ?? "世界观察"}</h2>
          <p className="detail-meta">{selectedMeta}</p>
          {selectedStatus ? <p className="detail-line">状态：{selectedStatus}</p> : null}
          {selectedGoal ? <p className="detail-line">目标：{selectedGoal}</p> : null}
          {selectedStep ? <p className="detail-line">当前步骤：{selectedStep}</p> : null}
          <p className="detail-line">思考：{selected ? pick(selected.thought, tick) : "projection 加载后会显示节点状态。"}</p>
          <p className="detail-line">行为：{selected ? pick(selected.action, tick) : "真实行动由后端引擎和规则包裁决。"}</p>
          <div className="node-state-panel" aria-label="节点状态快照">
            <p className="eyebrow">State Snapshot</p>
            <div className="node-state-list">
              {selectedStateFacts.length > 0 ? selectedStateFacts.map((fact) => (
                <span className="node-state-chip" data-kind={fact.kind} key={`${fact.kind}-${fact.label}`}>
                  <b>{fact.label}</b>
                  <em>{fact.value}</em>
                </span>
              )) : (
                <span className="node-state-empty">暂无结构化状态</span>
              )}
            </div>
          </div>
          <div className="node-memory-panel" aria-label="节点记忆摘要">
            <div className="node-memory-head">
              <p className="eyebrow">Memory</p>
              <span>{selectedMemoryCount || "--"}</span>
            </div>
            <div className="node-memory-list">
              {selectedMemoryHighlights.length > 0 ? selectedMemoryHighlights.map((memory, index) => (
                <article className="node-memory-row" data-kind={memory.kind} key={`${memory.kind}-${memory.tick}-${index}`}>
                  <p>{memory.text}</p>
                  <span>
                    {memory.source || memory.kind}
                    {memory.tick !== "" ? ` · T${memory.tick}` : ""}
                    {typeof memory.importance === "number" ? ` · ${memory.importance.toFixed(2)}` : ""}
                  </span>
                </article>
              )) : (
                <span className="node-memory-empty">暂无投影记忆</span>
              )}
            </div>
          </div>
          <div className="node-relationship-panel" aria-label="节点关系摘要">
            <div className="node-relationship-head">
              <p className="eyebrow">Relationship</p>
              <span>{selectedRelationshipFacts.length || "--"}</span>
            </div>
            <div className="node-relationship-list">
              {selectedRelationshipFacts.length > 0 ? selectedRelationshipFacts.map((relationship) => (
                <article
                  className="node-relationship-row"
                  data-direction={relationship.direction}
                  key={`${relationship.type}-${relationship.counterpartId}-${relationship.direction}`}
                >
                  <b>{relationship.direction === "out" ? "→" : relationship.direction === "in" ? "←" : "↔"} {relationship.type}</b>
                  <span>{relationship.counterpartName}</span>
                  <em>{relationship.weight}{relationship.detail ? ` · ${relationship.detail}` : ""}</em>
                </article>
              )) : (
                <span className="node-relationship-empty">暂无直接关系</span>
              )}
            </div>
          </div>
          {selectedAction ? (
            <div className="selected-action-context">
              <p className="eyebrow">Selected Action</p>
              <p className="detail-line">{actionLabel(selectedAction.action)} · T{Number(selectedAction.tick ?? 0)}</p>
              <p className="detail-line">{selectedAction.summary || selectedAction.action}</p>
              {selectedAction.decision ? (
                <div className="rule-evidence" aria-label="规则裁决证据">
                  <span><b>Rule</b><em>{selectedAction.decision.rule || selectedAction.action}</em></span>
                  <span><b>Score</b><em>{String(selectedAction.decision.score ?? "--")}</em></span>
                  <span><b>Candidates</b><em>{String(selectedAction.decision.candidate_count ?? "--")}</em></span>
                  {selectedAction.decision.reason ? (
                    <p>{selectedAction.decision.reason}</p>
                  ) : null}
                </div>
              ) : null}
              {selectedAction.intervention?.id ? (
                <div className="intervention-meta" aria-label="干预元信息">
                  <span><b>ID</b><em>{selectedAction.intervention.id}</em></span>
                  <span><b>Tick</b><em>{String(selectedAction.intervention.scheduled_tick ?? selectedAction.tick ?? 0)}</em></span>
                  <span><b>Effects</b><em>{String(selectedAction.intervention.effect_count ?? selectedAction.effect_count ?? 0)}</em></span>
                </div>
              ) : null}
              {causalFocus?.pathItems.length ? (
                <div className="causal-path-list" aria-label="选中行动因果路径">
                  {causalFocus.pathItems.map((item) => (
                    <span className="causal-path-chip" data-role={item.role} key={`${item.role}-${item.id}`}>
                      <b>{causalPathRoleLabel(item.role)}</b>
                      <em>{item.label}</em>
                    </span>
                  ))}
                </div>
              ) : null}
              <div className="action-effect-list">
                {(selectedAction.effects || []).slice(0, 5).map((effect, index) => (
                  <button
                    className="action-effect-chip"
                    data-effect={effect.type}
                    data-selected={selectedEffect?.label === effect.label ? "yes" : "no"}
                    key={`${effect.type}-${index}`}
                    onClick={() => selectGroundedEffect(selectedAction, effect)}
                    type="button"
                  >
                    {effect.label || effect.type}
                  </button>
                ))}
              </div>
              {selectedEffect ? (
                <div className="selected-effect-context">
                  <p className="detail-line">Effect：{selectedEffect.label || selectedEffect.type}</p>
                  {selectedEffect.change?.label ? (
                    <p className="effect-change-line">{selectedEffect.change.label}</p>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}
        </section>
        <section className="action-feed-panel" aria-label="真实行动流">
          <p className="eyebrow">Grounded Feed</p>
          <h2>真实行动流</h2>
          <div className="action-feed-list">
            {visibleGroundedActions.length > 0 ? visibleGroundedActions.map((action) => {
              const interventionStatus = action.intervention?.id
                ? interventionStatusById.get(action.intervention.id) ?? "external"
                : "none";
              return (
                <article
                  className="action-feed-row"
                  data-domain-match={selectedDomainSignal && domainActionMatches(selectedDomainSignal, action) ? "yes" : "no"}
                  data-intervention={action.intervention?.id ? "yes" : "no"}
                  data-intervention-status={interventionStatus}
                  data-selected={selectedAction?.sequence === action.sequence ? "yes" : "no"}
                  key={`${action.sequence ?? action.tick}-${action.actor_id}-${action.action}`}
                >
                  <button
                    aria-label={`Select ${action.action} by ${action.actor_name || action.actor_id}`}
                    className="action-feed-select"
                    onClick={() => selectGroundedAction(action)}
                    type="button"
                  >
                    <div className="action-feed-head">
                      <span>{actionLabel(action.action)}</span>
                      {action.intervention?.id ? <em>{interventionStatus === "applied" ? "Applied" : "Intervention"}</em> : null}
                      <b>T{Number(action.tick ?? 0)}</b>
                    </div>
                    <p className="action-feed-main">
                      {action.actor_name || action.actor_id}
                      {targetNames(action).length > 0 ? ` → ${targetNames(action).join(", ")}` : ""}
                    </p>
                    <p className="action-feed-sub">{action.summary || action.action}</p>
                  </button>
                  <div className="action-effect-list">
                    {(action.effects || []).slice(0, 4).map((effect, index) => (
                      <button
                        aria-label={`Select effect ${effect.label || effect.type}`}
                        className="action-effect-chip"
                        data-effect={effect.type}
                        data-selected={selectedAction?.sequence === action.sequence && selectedEffect?.label === effect.label ? "yes" : "no"}
                        key={`${effect.type}-${index}`}
                        onClick={() => selectGroundedEffect(action, effect)}
                        type="button"
                      >
                        {effect.label || effect.type}
                      </button>
                    ))}
                    {Number(action.effect_count || 0) > 4 ? (
                      <span className="action-effect-chip" data-effect="more">+{Number(action.effect_count || 0) - 4}</span>
                    ) : null}
                  </div>
                </article>
              );
            }) : (
              <p className="trace-empty">暂无真实行动</p>
            )}
          </div>
        </section>
        <section className="ai-trace-panel" aria-label="AI 因果对账">
          <p className="eyebrow">AI Trace</p>
          <h2>因果对账</h2>
          <div className="ai-causality-timeline" aria-label="近期 AI 因果历史">
            {visibleCausalityHistory.length > 0 ? visibleCausalityHistory.map((item, index) => (
              <span
                className="ai-causality-chip"
                data-matched={item.matched ? "yes" : "no"}
                key={`${item.tick}-${item.nodeId}-${item.pressure}-${index}`}
                title={`${item.thought} → ${item.pressure} → ${item.action}`}
              >
                <b>T{item.tick}</b>
                <em>{item.pressure}</em>
              </span>
            )) : (
              <span className="ai-causality-empty">等待 timeline trace</span>
            )}
          </div>
          <div className="trace-list">
            {visibleTraces.length > 0 ? visibleTraces.map((trace, index) => (
              <article className="trace-row" data-matched={trace.matched ? "yes" : "no"} key={`${trace.node_id || "trace"}-${index}`}>
                <span className="trace-status" />
                <div>
                  <p className="trace-main">{traceText(trace.thought, "text") || "暂无可见思考"} → {traceText(trace.pressure, "rule") || "pressure"}</p>
                  <p className="trace-sub">
                    {trace.matched ? `已采纳：${traceText(trace.action, "action") || traceText(trace.action, "summary") || "action"}` : "未匹配真实行动"}
                  </p>
                </div>
              </article>
            )) : (
              <p className="trace-empty">暂无对账链路</p>
            )}
          </div>
        </section>
        <div className="legend" aria-label="图例">
          <span><i className="legend-dot org-dot" />关系网智能体</span>
          <span><i className="legend-dot key-dot" />关键角色智能体</span>
          <span><i className="legend-dot person-dot" />关系网成员</span>
        </div>
      </footer>

  );
}

function sovereignIntentStatusLabel(item: SovereignIntentLogItem) {
  if (item.status === "applied") {
    return item.appliedTick !== undefined ? `Applied · T${item.appliedTick}` : "Applied";
  }
  if (item.status === "rejected") return "Rejected";
  return item.dynamicRuleCount !== undefined ? `Queued · ${item.dynamicRuleCount} rules` : "Queued";
}
