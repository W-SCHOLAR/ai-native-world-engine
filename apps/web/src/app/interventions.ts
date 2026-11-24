import type { GroundedAction, ViewerProjection } from "../types/contracts";
import type { InterventionLogItem } from "../types/ui";
import type { InterventionTemplate } from "./runtimeTypes";

export type InterventionPayload = Record<string, unknown> & {
  id: string;
  action: string;
  summary: string;
  effects: Array<Record<string, unknown>>;
};

const INTERVENTION_LOG_LIMIT = 6;

export function interventionPayload(
  template: InterventionTemplate,
  nodeId: string,
  nodeName: string,
  tickCursor: number,
): InterventionPayload {
  const target = `node:${nodeId}`;
  const name = nodeName || nodeId;
  const base = {
    tick: tickCursor,
    source: "web_operator",
    actor_type: "user",
    actor_id: "web-operator",
  };
  if (template === "supply") {
    return {
      ...base,
      id: `web-supply-${Date.now()}`,
      action: "operator_supply",
      summary: `Operator supply for ${name}`,
      effects: [
        {
          type: "resource_delta",
          target,
          resource: "supplies",
          delta: 3,
          floor: 0,
        },
      ],
    };
  }
  if (template === "policy") {
    return {
      ...base,
      id: `web-policy-${Date.now()}`,
      action: "operator_policy",
      summary: `Operator policy for ${name}`,
      effects: [
        {
          type: "policy_state",
          target,
          policy: "operator_priority",
          status: "active",
          note: `priority-${tickCursor}`,
        },
      ],
    };
  }
  return {
    ...base,
    id: `web-signal-${Date.now()}`,
    action: "operator_signal",
    summary: `Operator signal for ${name}`,
    effects: [
      {
        type: "node_state",
        target,
        field: "operator_signal",
        value: `inspect-${tickCursor}`,
      },
    ],
  };
}

export function interventionLogItem(
  intervention: InterventionPayload,
  template: InterventionTemplate,
  nodeId: string,
  nodeName: string,
  tickCursor: number,
): InterventionLogItem {
  return {
    id: intervention.id,
    template,
    targetId: nodeId,
    targetName: nodeName || nodeId,
    scheduledTick: tickCursor,
    summary: intervention.summary,
    status: "queued",
    effectCount: intervention.effects.length,
  };
}

export function prependInterventionLog(items: InterventionLogItem[], nextItem: InterventionLogItem): InterventionLogItem[] {
  return [nextItem, ...items.filter((item) => item.id !== nextItem.id)].slice(0, INTERVENTION_LOG_LIMIT);
}

export function updateInterventionLogStatus(
  items: InterventionLogItem[],
  id: string,
  status: InterventionLogItem["status"],
  error?: string,
): InterventionLogItem[] {
  return items.map((item) => (
    item.id === id
      ? { ...item, status, error }
      : item
  ));
}

export function markAppliedInterventions(items: InterventionLogItem[], projection: ViewerProjection | null): InterventionLogItem[] {
  const appliedById = new Map<string, GroundedAction>();
  for (const action of projection?.grounded_actions || []) {
    const interventionId = action.intervention?.id;
    if (interventionId) appliedById.set(interventionId, action);
  }
  let changed = false;
  const nextItems = items.map((item) => {
    const action = appliedById.get(item.id);
    if (!action || item.status === "applied") return item;
    changed = true;
    return {
      ...item,
      status: "applied" as const,
      appliedTick: action.tick ?? action.intervention?.scheduled_tick,
      effectCount: action.intervention?.effect_count ?? action.effect_count ?? item.effectCount,
      error: undefined,
    };
  });
  return changed ? nextItems : items;
}
