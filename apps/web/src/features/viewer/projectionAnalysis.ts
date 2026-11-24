import type { TimelineFrame } from "../../types/contracts";
import type { InterventionLogItem } from "../../types/ui";
import type {
  ActionCoverage, ActionCoverageRow, AgentKind, AgentNode, AiCausalityHistoryItem,
  AiTrace, CausalFocus, CausalPathItem, DisplayPayload, DomainSignalHistory,
  DomainSignal, GovernanceNotice, GroundedAction, GroundedEffect, InfluenceLink,
  MemoryMaintenanceFact, MemoryMaintenanceRow, MemoryHighlight, NetworkLink,
  NormalizedWorld, ProjectionNode, RelationshipFact, RunHealthFact, StateFact,
  ViewerProjection, WorldEventTickerItem,
} from "./viewerTypes";
import { WORLD_ACTION_LABELS } from "./viewerTypes";

import {
  actionLabel, clamp, dedupePathItems, dict, fmt, fmtValue, numeric, pick,
  riskSignalState, stringValue, traceText, uniqueStrings,
} from "./projectionShared";
import {
  effectNodeIds,
  effectNodeIdsFromAction,
  effectRefName,
  normalizeGroundedActions,
} from "./projectionNormalization";

export const DOMAIN_SIGNAL_HISTORY_LIMIT = 6;
export const AI_CAUSALITY_HISTORY_LIMIT = 8;
export const WORLD_EVENT_TICKER_LIMIT = 8;

export function causalFocusForSelection(action: GroundedAction | null, selectedEffect: GroundedEffect | null): CausalFocus | null {
  if (!action?.actor_id) return null;
  const targetIds = uniqueStrings((action.targets || []).map((target) => target.id).filter((id): id is string => Boolean(id)));
  const effectIds = uniqueStrings(selectedEffect ? effectNodeIds(selectedEffect) : effectNodeIdsFromAction(action));
  const selectedEffectNodeIds = selectedEffect ? effectNodeIds(selectedEffect) : [];
  const pathItems: CausalPathItem[] = [
    {
      id: action.actor_id,
      label: action.actor_name || action.actor_id,
      role: "actor",
    },
  ];
  for (const target of action.targets || []) {
    if (!target.id) continue;
    pathItems.push({
      id: target.id,
      label: target.name || target.id,
      role: "target",
    });
  }
  const effects = selectedEffect ? [selectedEffect] : (action.effects || []).slice(0, 4);
  for (const effect of effects) {
    for (const id of effectNodeIds(effect)) {
      if (id === action.actor_id || targetIds.includes(id)) continue;
      pathItems.push({
        id,
        label: effectRefName(effect, id),
        role: "effect",
      });
    }
  }
  return {
    actorId: action.actor_id,
    targetIds,
    effectNodeIds: effectIds,
    selectedEffectNodeIds,
    pathItems: dedupePathItems(pathItems).slice(0, 8),
  };
}

export function causalPathRoleLabel(role: CausalPathItem["role"]): string {
  if (role === "actor") return "Actor";
  if (role === "target") return "Target";
  return "Effect";
}

export function interventionStatusLabel(item: InterventionLogItem): string {
  if (item.status === "applied") {
    const tick = item.appliedTick ?? item.scheduledTick;
    return `Applied · T${tick}`;
  }
  if (item.status === "rejected") return "Rejected";
  return "Queued";
}

export function domainSignals(summary: ViewerProjection["summary"]): DomainSignal[] {
  const domainSummary = dict(summary.domain_summary);
  const risk = { ...dict(domainSummary.risk), ...dict(summary.domain_risk) };
  const infection = dict(domainSummary.infection);
  const resources = dict(domainSummary.resources);
  const policies = dict(domainSummary.policies);
  const coverage = dict(domainSummary.domain_model_coverage);
  const byDomain = dict(coverage.by_domain);
  const signals: DomainSignal[] = [];
  const riskScore = numeric(risk.score);
  const riskLevel = stringValue(risk.level) || "low";
  if (riskScore !== null || riskLevel) {
    signals.push({
      key: "risk",
      label: "风险",
      value: riskScore !== null ? fmt(riskScore) : riskLevel,
      detail: riskLevel,
      state: riskSignalState(riskScore, riskLevel),
      actionHints: ["combat_attack", "social_spread", "quarantine_policy", "organization_decision"],
    });
  }
  const activeInfections = numeric(infection.active_count);
  if (activeInfections !== null) {
    signals.push({
      key: "infection",
      label: "感染",
      value: fmt(activeInfections),
      detail: "active",
      state: activeInfections > 0 ? "high" : "low",
      actionHints: ["infection_progress", "infection_spread", "quarantine_policy", "science_publish"],
    });
  }
  const scarcityNodes = numeric(resources.scarcity_nodes);
  if (scarcityNodes !== null) {
    signals.push({
      key: "resources",
      label: "资源",
      value: fmt(scarcityNodes),
      detail: "scarcity",
      state: scarcityNodes > 0 ? "watch" : "low",
      actionHints: ["logistics_transfer", "resource_transfer", "economic_exchange", "production"],
    });
  }
  const activePolicies = numeric(policies.active_count);
  if (activePolicies !== null) {
    signals.push({
      key: "policies",
      label: "政策",
      value: fmt(activePolicies),
      detail: "active",
      state: activePolicies > 0 ? "watch" : "idle",
      actionHints: ["quarantine_policy", "organization_decision"],
    });
  }
  const coveredDomains = Object.entries(byDomain).filter(([, value]) => Number(value) > 0).length;
  if (coveredDomains > 0) {
    signals.push({
      key: "coverage",
      label: "域覆盖",
      value: fmt(coveredDomains),
      detail: "domains",
      state: coveredDomains >= 5 ? "low" : "watch",
      actionHints: WORLD_ACTION_LABELS.map(([action]) => action),
    });
  }
  return signals.slice(0, 6);
}

export function domainSignalHistory(
  timeline: TimelineFrame[],
  fallbackProjection: ViewerProjection | null = null,
  limit = DOMAIN_SIGNAL_HISTORY_LIMIT,
): Record<string, DomainSignalHistory> {
  const frames = timeline.length > 0
    ? timeline.slice(-limit)
    : fallbackProjection
      ? [{
          tick: Number(fallbackProjection.summary.tick ?? 0),
          projection: fallbackProjection,
        }]
      : [];
  const signalFrames = frames.map((frame) => {
    const projection = frame.projection;
    const tick = projection?.summary?.tick ?? frame.tick ?? 0;
    const signals = domainSignals(projection?.summary || {});
    return {
      tick,
      byKey: new Map(signals.map((signal) => [signal.key, signal])),
      signals,
    };
  });
  const labels = new Map<string, string>();
  for (const frame of signalFrames) {
    for (const signal of frame.signals) {
      labels.set(signal.key, signal.label);
    }
  }
  const histories: Record<string, DomainSignalHistory> = {};
  for (const [key, label] of labels) {
    const points = signalFrames.map((frame) => {
      const signal = frame.byKey.get(key);
      return {
        tick: frame.tick,
        value: signal?.value ?? "",
        state: signal?.state ?? "idle",
        present: Boolean(signal),
      };
    });
    histories[key] = {
      key,
      label,
      points,
      hasTrend: points.filter((point) => point.present).length > 1,
    };
  }
  return histories;
}

export function domainTimelineEvidenceCount(
  signal: DomainSignal | null,
  timeline: TimelineFrame[],
  limit = DOMAIN_SIGNAL_HISTORY_LIMIT,
): number {
  if (!signal || timeline.length === 0) return 0;
  const seen = new Set<string>();
  for (const frame of timeline.slice(-limit)) {
    const actions = normalizeGroundedActions(frame.projection?.grounded_actions || []);
    for (const action of actions) {
      if (!domainActionMatches(signal, action)) continue;
      seen.add([
        action.sequence ?? "seq",
        action.tick ?? frame.tick ?? "tick",
        action.actor_id,
        action.action,
        action.summary,
      ].join(":"));
    }
  }
  return seen.size;
}

export function nodeStateFacts(attributes: Record<string, unknown>): StateFact[] {
  const facts: StateFact[] = [];
  const health = numeric(attributes.health);
  const maxHealth = numeric(attributes.max_health);
  if (health !== null) {
    facts.push({ kind: "health", label: "健康", value: maxHealth !== null ? `${fmt(health)}/${fmt(maxHealth)}` : fmt(health) });
  }
  const budget = numeric(attributes.budget);
  if (budget !== null) {
    facts.push({ kind: "economy", label: "预算", value: fmt(budget) });
  }
  const resources = dict(attributes.resources);
  for (const [resource, amount] of Object.entries(resources).slice(0, 4)) {
    facts.push({ kind: "resource", label: resource, value: fmtValue(amount) });
  }
  const infection = dict(attributes.infection);
  if (Object.keys(infection).length > 0) {
    const pathogen = stringValue(infection.pathogen);
    const status = stringValue(infection.status);
    facts.push({ kind: "infection", label: "感染", value: [pathogen, status].filter(Boolean).join(" · ") || "active" });
  }
  const policies = dict(attributes.policies);
  for (const [policy, state] of Object.entries(policies).slice(0, 3)) {
    const stateDict = dict(state);
    facts.push({ kind: "policy", label: policy, value: stringValue(stateDict.status) || "active" });
  }
  const production = dict(attributes.production);
  const productionOutput = stringValue(production.last_output_resource || production.output_resource);
  if (productionOutput) {
    const amount = numeric(production.last_output_amount);
    facts.push({ kind: "production", label: "生产", value: amount !== null ? `${fmt(amount)} ${productionOutput}` : productionOutput });
  }
  const migration = dict(attributes.migration);
  if (Object.keys(migration).length > 0) {
    facts.push({ kind: "migration", label: "迁徙", value: stringValue(migration.status || migration.destination) || "active" });
  }
  for (const [key, value] of Object.entries(attributes).filter(([key]) => key.startsWith("signal:")).slice(0, 3)) {
    facts.push({ kind: "signal", label: key.replace("signal:", ""), value: fmtValue(value) });
  }
  return facts;
}

export function nodeMemoryHighlights(attributes: Record<string, unknown>): MemoryHighlight[] {
  const highlights = Array.isArray(attributes._memory_highlights) ? attributes._memory_highlights : [];
  return highlights
    .map((item) => dict(item))
    .filter((item) => stringValue(item.text))
    .slice(0, 3)
    .map((item) => ({
      kind: stringValue(item.kind) || "memory",
      text: stringValue(item.text),
      source: stringValue(item.source),
      tick: typeof item.tick === "number" || typeof item.tick === "string" ? item.tick : "",
      importance: numeric(item.importance) ?? undefined,
      memoryCount: numeric(item.memory_count) ?? undefined,
    }));
}

export function nodeRelationshipFacts(
  relationships: Array<Record<string, unknown>>,
  selectedId: string,
  nodes: AgentNode[],
  limit = 5,
): RelationshipFact[] {
  if (!selectedId) return [];
  const namesById = new Map(nodes.map((node) => [node.id, node.name]));
  const facts: RelationshipFact[] = [];
  for (const relationship of relationships || []) {
    const source = stringValue(relationship.source);
    const target = stringValue(relationship.target);
    if (!source || !target || (source !== selectedId && target !== selectedId)) continue;
    const direction: RelationshipFact["direction"] = source === selectedId && target === selectedId
      ? "mutual"
      : source === selectedId
        ? "out"
        : "in";
    const counterpartId = source === selectedId ? target : source;
    const metadata = dict(relationship.metadata);
    const status = stringValue(metadata.status);
    const reason = stringValue(metadata.reason);
    facts.push({
      type: stringValue(relationship.type) || "relationship",
      direction,
      counterpartId,
      counterpartName: namesById.get(counterpartId) || counterpartId,
      weight: fmt(Number(relationship.weight || 0)),
      detail: status || reason || "",
    });
  }
  return facts
    .sort((left, right) => Math.abs(Number(right.weight)) - Math.abs(Number(left.weight)))
    .slice(0, Math.max(limit, 0));
}

export function runHealthFacts(summary: ViewerProjection["summary"]): RunHealthFact[] {
  const health = dict(summary.run_health);
  const score = numeric(health.score) ?? numeric(summary.score) ?? 0;
  const penaltyCount = numeric(health.penalty_count) ?? 0;
  const worldErrors = numeric(health.world_errors) ?? 0;
  const governanceRejections = numeric(health.governance_rejections) ?? 0;
  const domainIssues = numeric(health.domain_state_issues) ?? 0;
  const unmatchedPressures = numeric(health.unmatched_pressures) ?? 0;
  const missingActions = Array.isArray(health.missing_required_actions) ? health.missing_required_actions.length : 0;
  return [
    { key: "score", label: "Score", value: fmt(score), state: score >= 95 ? "clean" : score >= 80 ? "watch" : "issue" },
    { key: "penalties", label: "Penalties", value: fmt(penaltyCount), state: penaltyCount > 0 ? "issue" : "clean" },
    { key: "errors", label: "Errors", value: fmt(worldErrors), state: worldErrors > 0 ? "issue" : "clean" },
    { key: "governance", label: "Governance", value: fmt(governanceRejections), state: governanceRejections > 0 ? "watch" : "clean" },
    { key: "domain", label: "Domain", value: fmt(domainIssues), state: domainIssues > 0 ? "watch" : "clean" },
    { key: "unmatched", label: "Unmatched", value: fmt(unmatchedPressures + missingActions), state: unmatchedPressures + missingActions > 0 ? "watch" : "clean" },
  ];
}

export function governanceNotice(summary: ViewerProjection["summary"]): GovernanceNotice {
  const notice = dict(summary.governance_notice);
  const riskLevel = stringValue(notice.risk_level) || stringValue(dict(summary.domain_risk).level) || "low";
  const normalizedRisk = riskLevel.toLowerCase();
  return {
    label: stringValue(notice.label) || "场景模拟",
    scenario: stringValue(notice.scenario) || stringValue(summary.scenario) || "projection",
    message: stringValue(notice.message) || "此运行是场景模拟和假设推演，不是对现实世界的确定性预测。",
    riskLevel,
    state: normalizedRisk === "critical" || normalizedRisk === "high"
      ? "high"
      : normalizedRisk === "medium" || normalizedRisk === "moderate"
        ? "watch"
        : "normal",
  };
}

export function memoryMaintenanceFacts(summary: ViewerProjection["summary"]): MemoryMaintenanceFact[] {
  const maintenance = dict(summary.memory_maintenance);
  const consolidatedNodes = numeric(maintenance.consolidated_nodes) ?? 0;
  const summaryCount = numeric(maintenance.summary_count) ?? 0;
  const forgottenCount = numeric(maintenance.forgotten_count) ?? 0;
  const state: MemoryMaintenanceFact["state"] = forgottenCount > 0
    ? "forgetting"
    : consolidatedNodes + summaryCount > 0
      ? "active"
      : "idle";
  return [
    { key: "nodes", label: "Nodes", value: fmt(consolidatedNodes), state },
    { key: "summaries", label: "Summaries", value: fmt(summaryCount), state },
    { key: "forgotten", label: "Forgotten", value: fmt(forgottenCount), state: forgottenCount > 0 ? "forgetting" : state },
  ];
}

export function memoryMaintenanceRows(summary: ViewerProjection["summary"]): MemoryMaintenanceRow[] {
  const maintenance = dict(summary.memory_maintenance);
  const rows = Array.isArray(maintenance.recent) ? maintenance.recent : [];
  return rows
    .map((row) => dict(row))
    .filter((row) => stringValue(row.node_id) || stringValue(row.text))
    .slice(0, 3)
    .map((row) => ({
      nodeId: stringValue(row.node_id) || "world",
      tick: typeof row.tick === "number" || typeof row.tick === "string" ? row.tick : "",
      kind: stringValue(row.kind) || "memory_summary",
      text: stringValue(row.text) || "memory summary",
      memoryCount: numeric(row.memory_count) ?? 0,
      forgottenCount: numeric(row.forgotten_count) ?? 0,
      tickStart: typeof row.tick_start === "number" || typeof row.tick_start === "string" ? row.tick_start : "",
      tickEnd: typeof row.tick_end === "number" || typeof row.tick_end === "string" ? row.tick_end : "",
      keywords: Array.isArray(row.keywords) ? row.keywords.map((item) => stringValue(item)).filter(Boolean).slice(0, 5) : [],
    }));
}

export function worldEventTicker(projection: ViewerProjection | null, limit = WORLD_EVENT_TICKER_LIMIT): WorldEventTickerItem[] {
  if (!projection) return [];
  const grounded = normalizeGroundedActions(projection.grounded_actions || [])
    .sort((left, right) => Number(right.sequence ?? 0) - Number(left.sequence ?? 0))
    .map((action) => ({
      kind: "grounded" as const,
      tick: action.tick ?? projection.summary.tick ?? 0,
      label: actionLabel(action.action),
      text: action.summary || `${action.actor_name || action.actor_id} ${action.action}`,
      salience: action.intervention?.id ? 0.95 : 0.82,
    }));
  const actionBullets = (projection.actions || [])
    .slice()
    .sort((left, right) => Number(right.tick ?? 0) - Number(left.tick ?? 0))
    .map((item) => ({
      kind: "action" as const,
      tick: typeof item.tick === "number" || typeof item.tick === "string" ? item.tick : projection.summary.tick ?? 0,
      label: "Action",
      text: stringValue(item.text) || "action payload",
      salience: numeric(item.salience) ?? 0.5,
    }));
  const thoughts = (projection.thoughts || [])
    .slice()
    .sort((left, right) => Number(right.tick ?? 0) - Number(left.tick ?? 0))
    .map((item) => ({
      kind: "thought" as const,
      tick: typeof item.tick === "number" || typeof item.tick === "string" ? item.tick : projection.summary.tick ?? 0,
      label: "Thought",
      text: stringValue(item.text) || "thought payload",
      salience: numeric(item.salience) ?? 0.4,
    }));
  return [...grounded, ...actionBullets, ...thoughts].slice(0, Math.max(limit, 0));
}

export function rankedAiTraces(items: Array<Record<string, unknown>>, selectedId?: string): AiTrace[] {
  const traces = (items || []).map((item) => item as AiTrace);
  if (!selectedId) return traces.slice().reverse();
  const selected = traces.filter((trace) => trace.node_id === selectedId).reverse();
  const other = traces.filter((trace) => trace.node_id !== selectedId).reverse();
  return [...selected, ...other];
}

export function aiCausalityTimeline(
  timeline: TimelineFrame[],
  fallbackProjection: ViewerProjection | null = null,
  selectedId = "",
  limit = AI_CAUSALITY_HISTORY_LIMIT,
): AiCausalityHistoryItem[] {
  const frames = timeline.length > 0
    ? timeline
    : fallbackProjection
      ? [{
          tick: Number(fallbackProjection.summary.tick ?? 0),
          projection: fallbackProjection,
        }]
      : [];
  const items: AiCausalityHistoryItem[] = [];
  for (const frame of frames) {
    const traces = (frame.projection?.ai_traces || []).map((trace) => trace as AiTrace);
    for (const trace of traces) {
      const nodeId = String(trace.node_id || "");
      if (!nodeId) continue;
      items.push({
        tick: trace.tick ?? frame.projection?.summary?.tick ?? frame.tick ?? 0,
        nodeId,
        matched: Boolean(trace.matched),
        thought: traceText(trace.thought, "text") || "thought",
        pressure: traceText(trace.pressure, "rule") || "pressure",
        action: traceText(trace.action, "action") || traceText(trace.action, "summary") || "pending",
      });
    }
  }
  const recent = items.slice(-Math.max(limit * 3, limit)).reverse();
  const ordered = selectedId
    ? [
        ...recent.filter((item) => item.nodeId === selectedId),
        ...recent.filter((item) => item.nodeId !== selectedId),
      ]
    : recent;
  return ordered.slice(0, Math.max(limit, 0));
}

export function rankedGroundedActions(
  items: GroundedAction[],
  selectedId?: string,
  selectedDomainSignal?: DomainSignal | null,
): GroundedAction[] {
  const sorted = (items || []).slice().sort((left, right) => Number(right.sequence ?? 0) - Number(left.sequence ?? 0));
  const domainRanked = selectedDomainSignal
    ? [
        ...sorted.filter((item) => domainActionMatches(selectedDomainSignal, item)),
        ...sorted.filter((item) => !domainActionMatches(selectedDomainSignal, item)),
      ]
    : sorted;
  if (!selectedId) return domainRanked;
  const selected = domainRanked.filter((item) => item.actor_id === selectedId || (item.targets || []).some((target) => target.id === selectedId));
  const other = domainRanked.filter((item) => !selected.includes(item));
  return [...selected, ...other];
}

export function domainActionMatches(signal: DomainSignal | null, action: GroundedAction): boolean {
  if (!signal) return false;
  if (signal.actionHints.includes(action.action)) return true;
  const effectTypes = (action.effects || []).map((effect) => effect.type);
  if (signal.key === "resources") return effectTypes.includes("resource_delta") || effectTypes.includes("resource_transfer");
  if (signal.key === "policies") return effectTypes.includes("policy_state");
  if (signal.key === "infection") return action.action.includes("infection") || effectTypes.includes("node_state");
  if (signal.key === "risk") return signal.actionHints.some((hint) => action.action.includes(hint));
  if (signal.key === "coverage") return signal.actionHints.includes(action.action);
  return false;
}

export function targetNames(action: GroundedAction): string[] {
  return (action.targets || [])
    .map((target) => target.name || target.id)
    .filter((name): name is string => Boolean(name));
}

