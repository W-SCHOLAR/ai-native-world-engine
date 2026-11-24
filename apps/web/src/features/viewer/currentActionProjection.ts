import type { ViewerProjection } from "../../types/contracts";
import type { DisplayPayload } from "./viewerTypes";


export function currentActionPayloads(projection: ViewerProjection): DisplayPayload[] {
  const explicit = projection.current_actions;
  const items = explicit === undefined
    ? latestActionVisualsByActor(projection.action_visuals || [])
    : explicit;
  const payloads: DisplayPayload[] = [];
  for (const item of latestActionVisualsByActor(items)) {
    const nodeId = typeof item.actor_id === "string" ? item.actor_id : "";
    const text = typeof item.label === "string" ? item.label.trim() : "";
    const sequence = actionSequence(item);
    if (!nodeId || !text || sequence <= 0) continue;
    payloads.push({
      node_id: nodeId,
      text,
      occurrence_id: `action:${sequence}`,
      feedback_sequence: sequence,
      ttl: 0.5,
      salience: 0.58,
      origin: typeof item.source === "string" ? item.source : "grounded_action",
    });
  }
  return payloads;
}

function latestActionVisualsByActor(
  items: Array<Record<string, unknown>>,
): Array<Record<string, unknown>> {
  const latestByActor = new Map<string, Record<string, unknown>>();
  for (const item of items || []) {
    const actorId = typeof item.actor_id === "string" ? item.actor_id : "";
    const actorType = typeof item.actor_type === "string" ? item.actor_type : "";
    const sequence = actionSequence(item);
    if (!actorId || sequence <= 0 || (actorType && actorType !== "node" && actorType !== "person")) continue;
    const previous = latestByActor.get(actorId);
    if (!previous || sequence > actionSequence(previous)) latestByActor.set(actorId, item);
  }
  return [...latestByActor.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([, item]) => item);
}

function actionSequence(item: Record<string, unknown>) {
  return typeof item.feedback_sequence === "number"
    ? item.feedback_sequence
    : typeof item.sequence === "number" ? item.sequence : 0;
}
