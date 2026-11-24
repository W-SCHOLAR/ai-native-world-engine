import type { GroundedAction, ViewerProjection } from "../types/contracts";
import type { SovereignIntentLogItem } from "../types/ui";

const SOVEREIGN_INTENT_LOG_LIMIT = 6;

export function sovereignIntentLogItem(
  plan: Record<string, unknown>,
  text: string,
  scheduledTick: number,
): SovereignIntentLogItem {
  const dynamicRules = Array.isArray(plan.dynamic_rules) ? plan.dynamic_rules : [];
  return {
    id: String(plan.id || `web-sovereign-${Date.now()}`),
    text,
    title: String(plan.title || text.slice(0, 24) || "用户旨意"),
    scheduledTick,
    impactLevel: String(plan.impact_level || "new_law"),
    summary: String(plan.summary || `国王视角下旨：${text}`),
    status: "queued",
    dynamicRuleCount: dynamicRules.length,
  };
}

export function prependSovereignIntentLog(
  items: SovereignIntentLogItem[],
  nextItem: SovereignIntentLogItem,
): SovereignIntentLogItem[] {
  return [nextItem, ...items.filter((item) => item.id !== nextItem.id)].slice(0, SOVEREIGN_INTENT_LOG_LIMIT);
}

export function updateSovereignIntentLogStatus(
  items: SovereignIntentLogItem[],
  id: string,
  status: SovereignIntentLogItem["status"],
  error?: string,
): SovereignIntentLogItem[] {
  return items.map((item) => (
    item.id === id
      ? { ...item, status, error }
      : item
  ));
}

export function markAppliedSovereignIntents(
  items: SovereignIntentLogItem[],
  projection: ViewerProjection | null,
): SovereignIntentLogItem[] {
  const appliedById = new Map<string, GroundedAction>();
  for (const action of projection?.grounded_actions || []) {
    const intentId = action.sovereign_intent?.id;
    if (intentId) appliedById.set(intentId, action);
  }
  let changed = false;
  const nextItems = items.map((item) => {
    const action = appliedById.get(item.id);
    if (!action || item.status === "applied") return item;
    changed = true;
    return {
      ...item,
      status: "applied" as const,
      appliedTick: action.tick ?? action.sovereign_intent?.scheduled_tick,
      error: undefined,
    };
  });
  return changed ? nextItems : items;
}
