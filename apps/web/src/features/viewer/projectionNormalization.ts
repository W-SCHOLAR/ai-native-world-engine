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
import { actionLabel, clamp, dict, hashString, numeric, stringValue } from "./projectionShared";
import { tribeActivityCenter } from "./tribeActivityAreas";
import { currentActionPayloads } from "./currentActionProjection";

const RELATIONSHIP_LINK_LIMIT = 180;
const INFLUENCE_LINK_LIMIT = 18;
const MIRRORED_COVERAGE_NODE_LIMIT = 120;
const MIND_UNFOLD_TTL_SECONDS = 8;
const MIND_UNFOLD_GAP_SECONDS = 1.5;
const THOUGHT_START_SECONDS = 0.2;
const THOUGHT_INTERVAL_SECONDS = 0.48;
const PERSONA_GIVEN_NAMES = ["Mira", "Lina", "Vera", "Noor", "Iris", "Sana", "Rhea", "Yara", "Niko", "Ezra", "Tao", "Omar", "Jun", "Milo", "Ari", "Leon"];
const PERSONA_FAMILY_NAMES = ["Voss", "Sable", "Rook", "Vale", "Cross", "Nadir", "Kade", "Storm", "Lin", "Moreau", "Bose", "Klein", "Okafor", "Marin", "Ishikawa", "Santos"];
const PERSONA_TITLES = [
  "黑手党的小公主",
  "边境线上的情报经纪",
  "沉默的实验室继承人",
  "地下物流的白手套",
  "旧城媒体线人",
  "危机谈判桌上的影子顾问",
  "港口路线的年轻掌舵人",
  "公共卫生网络的夜班哨兵",
  "科学委员会的异端记录员",
  "能源转型局的灰色协调者",
  "人道响应链路里的现场耳目",
  "教育网络中的流动组织者",
];


export function normalizeProjection(projection: ViewerProjection): NormalizedWorld {
  const thoughtsByNode = groupPayloads(projection.thoughts);
  const thoughtOriginByNode = latestThoughtOriginByNode(projection.thoughts);
  const agentNodes: AgentNode[] = [];
  const networkLinks: NetworkLink[] = [];
  const groundedActions = normalizeGroundedActions(projection.grounded_actions || []);
  const groundedActionStateByActor = latestGroundedActionStateByActor(groundedActions);
  const scheduledThoughts = scheduledThoughtPayloads(projection.thoughts);
  const speechBubbles = speechBubblePayloads(projection.speech_bubbles || []);
  const summary = projection.summary as Record<string, unknown>;
  const usesTribeSurvivalAgents = summary.viewer_scene === "tribe_survival_world";

  for (const organization of projection.organizations) {
    const activityCenter = usesTribeSurvivalAgents
      ? tribeActivityCenter(organization.id, organization.x, organization.y)
      : { x: organization.x, y: organization.y };
    const hubNode = createAgentNode({
      ...organization,
      x: activityCenter.x,
      y: activityCenter.y,
      kind: "network",
      type: "关系网中枢",
      thought: textList(thoughtsByNode[organization.id]) || [`${organization.name} 正在读取结构化压力。`],
      action: groundedActionStateByActor[organization.id]?.caption
        ? [groundedActionStateByActor[organization.id].caption]
        : [],
      recentAction: groundedActionStateByActor[organization.id]?.action,
      parent: organization.name,
    });
    const memberNodes = (organization.members && organization.members.length > 0 ? organization.members : []).map((member, index, members) => {
      const position = organization.members && organization.members.length > 0
        ? memberPosition(index, members.length)
        : { x: 50, y: 50 };
      const id = member.id;
      const cognitionState = cognitionStateForMember(thoughtOriginByNode[id]);
      const node = createAgentNode({
        id,
        name: displayName(member),
        role: displayRole(member),
        type: "关系网节点",
        kind: "network",
        // Source world positions stay authoritative. This deterministic local
        // arrangement is presentation-only and gives every person a stable
        // activity area around their relationship network.
        x: activityCenter.x + (position.x - 50),
        y: activityCenter.y + (position.y - 50),
        thought: textList(thoughtsByNode[member.id] || thoughtsByNode[organization.id]) || [`${organization.name} 正在读取结构化压力。`],
        action: groundedActionStateByActor[member.id]?.caption
          ? [groundedActionStateByActor[member.id].caption]
          : [],
        recentAction: groundedActionStateByActor[member.id]?.action,
        parent: organization.name,
        cognitionState,
        attributes: member.attributes || {},
      });
      agentNodes.push(node);
      return node;
    });
    agentNodes.push(hubNode);
    networkLinks.push(...hubEdges(hubNode, memberNodes), ...inferredEdges(memberNodes));
  }

  for (const character of projection.characters) {
    const thoughtSeed = typeof character.key_character?.thought_seed === "string"
      ? character.key_character.thought_seed
      : "保持观察。";
    agentNodes.push(createAgentNode({
      ...character,
      kind: "key",
      type: "关键角色智能体",
      thought: textList(thoughtsByNode[character.id]) || [thoughtSeed],
      action: groundedActionStateByActor[character.id]?.caption
        ? [groundedActionStateByActor[character.id].caption]
        : [],
      recentAction: groundedActionStateByActor[character.id]?.action,
    }));
  }
  appendGroundedActionNodes(agentNodes, groundedActions);
  networkLinks.push(...projectedRelationshipLinks(projection.relationships || [], new Set(agentNodes.map((node) => node.id))));
  const influenceLinks = keyCharacterInfluenceLinks(projection.characters || [], new Set(agentNodes.map((node) => node.id)));
  const coverageCopies = usesTribeSurvivalAgents
    ? []
    : mirroredCoverageNodes(agentNodes, MIRRORED_COVERAGE_NODE_LIMIT);
  agentNodes.push(...coverageCopies);
  const normalizedCurrentActions = currentActionPayloads(projection).filter((payload) => {
    if (!usesTribeSurvivalAgents) return true;
    const actor = agentNodes.find((node) => node.id === payload.node_id);
    return actor?.type !== "关系网中枢";
  });

  return {
    summary: projection.summary,
    organizationCount: projection.organizations.length,
    characterCount: projection.characters.length,
    agentNodes,
    networkLinks,
    influenceLinks,
    scheduledThoughts,
    speechBubbles,
    currentActions: normalizedCurrentActions,
    actionCoverage: groundedActionCoverage(projection.summary),
    groundedActions,
  };
}

export function appendGroundedActionNodes(agentNodes: AgentNode[], actions: GroundedAction[]) {
  const visibleIds = new Set(agentNodes.map((node) => node.id));
  const nodesById = new Map<string, AgentNode>();
  for (const action of actions) {
    if (!visibleIds.has(action.actor_id)) {
      nodesById.set(action.actor_id, actionNodeFromGroundedAction(action));
    }
    for (const target of action.targets || []) {
      if (!target.id || visibleIds.has(target.id) || nodesById.has(target.id)) continue;
      nodesById.set(target.id, actionTargetNode(target, action));
    }
    for (const nodeId of effectNodeIdsFromAction(action)) {
      if (!nodeId || visibleIds.has(nodeId) || nodesById.has(nodeId)) continue;
      nodesById.set(nodeId, actionEffectNode(nodeId, action));
    }
  }
  agentNodes.push(...nodesById.values());
}

export function effectNodeIdsFromAction(action: GroundedAction): string[] {
  const ids = new Set<string>();
  for (const effect of action.effects || []) {
    for (const id of effectNodeIds(effect)) ids.add(id);
  }
  return [...ids];
}

export function effectNodeIds(effect: GroundedEffect): string[] {
  return [effect.target?.id, effect.to?.id, effect.from?.id, effect.source?.id]
    .filter((id): id is string => Boolean(id));
}

function actionNodeFromGroundedAction(action: GroundedAction): AgentNode {
  return createAgentNode({
    id: action.actor_id,
    name: action.actor_name || action.actor_id,
    role: actionLabel(action.action),
    type: "真实行动节点",
    kind: "world",
    x: typeof action.x === "number" ? action.x : 50,
    y: typeof action.y === "number" ? action.y : 50,
    attributes: action.actor_attributes || {},
    thought: [action.summary || action.action],
    action: [groundedActionCaption(action)],
    recentAction: action.action,
  });
}

function actionTargetNode(
  target: { id: string; name?: string; attributes?: Record<string, unknown> },
  action: GroundedAction,
): AgentNode {
  return createAgentNode({
    id: target.id,
    name: target.name || target.id,
    role: "行动目标",
    type: "真实行动目标",
    kind: "world",
    x: typeof action.x === "number" ? clamp(action.x + 3, 0, 100) : 52,
    y: typeof action.y === "number" ? clamp(action.y + 3, 0, 100) : 52,
    attributes: target.attributes || {},
    thought: [action.summary || action.action],
    action: [],
  });
}

function actionEffectNode(nodeId: string, action: GroundedAction): AgentNode {
  const effect = (action.effects || []).find((item) => effectNodeIds(item).includes(nodeId));
  return createAgentNode({
    id: nodeId,
    name: effectRefName(effect, nodeId),
    role: "Effect target",
    type: "真实影响节点",
    kind: "world",
    x: typeof action.x === "number" ? clamp(action.x + 5, 0, 100) : 54,
    y: typeof action.y === "number" ? clamp(action.y - 4, 0, 100) : 48,
    attributes: effectRefAttributes(effect, nodeId),
    thought: [effect?.label || action.summary || action.action],
    action: [],
  });
}


export function effectRefName(effect: GroundedEffect | undefined, fallback: string): string {
  if (!effect) return fallback;
  const ref = effect.target || effect.to || effect.from || effect.source;
  return ref?.name || ref?.id || fallback;
}

function effectRefAttributes(effect: GroundedEffect | undefined, nodeId: string): Record<string, unknown> {
  if (!effect) return {};
  const refs = [effect.target, effect.to, effect.from, effect.source];
  return refs.find((ref) => ref?.id === nodeId)?.attributes || {};
}

export function normalizeGroundedActions(actions: GroundedAction[]): GroundedAction[] {
  return (actions || [])
    .filter((action) => action && typeof action.action === "string" && typeof action.actor_id === "string")
    .map((action) => ({
      ...action,
      summary: typeof action.summary === "string" ? action.summary : "",
      actor_name: typeof action.actor_name === "string" ? action.actor_name : action.actor_id,
      targets: Array.isArray(action.targets) ? action.targets : [],
      effect_count: typeof action.effect_count === "number" ? action.effect_count : 0,
      effects: Array.isArray(action.effects) ? action.effects.filter((effect) => effect && typeof effect.label === "string") : [],
    }));
}

function groundedActionCoverage(summary: ViewerProjection["summary"]): ActionCoverage {
  const groundedSummary = summary.grounded_action_summary;
  if (!groundedSummary) {
    return {
      hasSummary: false,
      coveragePct: 0,
      hitCount: 0,
      missingCount: 0,
      totalCount: WORLD_ACTION_LABELS.length,
      rows: [],
    };
  }
  const counts = groundedSummary.counts_by_type || {};
  const hitSet = new Set(groundedSummary.world_ecosystem_actions_hit || []);
  const missingSet = new Set(groundedSummary.world_ecosystem_actions_missing || []);
  const rows = WORLD_ACTION_LABELS.map(([action, label]) => {
    const count = Number(counts[action] || 0);
    const state: ActionCoverageRow["state"] = count > 0 || hitSet.has(action)
      ? "hit"
      : missingSet.has(action)
        ? "missing"
        : "idle";
    return { action, label, count, state };
  });
  const hitCount = rows.filter((row) => row.state === "hit").length;
  const missingCount = rows.filter((row) => row.state === "missing").length;
  const totalCount = hitCount + missingCount || WORLD_ACTION_LABELS.length;
  const metricCoverage = Number(groundedSummary.world_ecosystem_action_coverage);
  const coveragePct = Number.isFinite(metricCoverage)
    ? Math.round(clamp(metricCoverage, 0, 1) * 100)
    : Math.round((hitCount / Math.max(totalCount, 1)) * 100);
  return {
    hasSummary: true,
    coveragePct,
    hitCount,
    missingCount,
    totalCount,
    rows,
  };
}
function createAgentNode(node: ProjectionNode & {
  kind: AgentKind;
  parent?: string;
  thought?: string[];
  action?: string[];
  recentAction?: string;
  cognitionState?: AgentNode["cognitionState"];
  attributes?: Record<string, unknown>;
}): AgentNode {
  const theta = ((Number(node.x || 50) / 100) * Math.PI * 2) - Math.PI;
  const phi = (0.5 - Number(node.y || 50) / 100) * Math.PI * 0.86;
  const hash = hashString(String(node.id));
  return {
    id: node.id,
    name: node.name || node.role || node.id,
    role: node.role || node.name || "agent",
    type: node.type || "agent",
    kind: node.kind,
    parent: node.parent || "",
    keyCharacter: node.key_character || {},
    theta: theta + ((hash % 17) - 8) * 0.006,
    phi: clamp(phi + (((hash >> 3) % 17) - 8) * 0.005, -1.16, 1.16),
    orbit: 0.006 + (hash % 9) * 0.0012,
    phase: (hash % 628) / 100,
    thought: node.thought || ["保持观察。"],
    action: node.action || [],
    recentAction: node.recentAction,
    cognitionState: node.cognitionState,
    attributes: node.attributes || {},
  };
}

function latestThoughtOriginByNode(thoughts: ViewerProjection["thoughts"]) {
  const origins: Record<string, string> = {};
  for (const thought of thoughts || []) {
    const nodeId = typeof thought.node_id === "string" ? thought.node_id : "";
    const origin = typeof thought.origin === "string" ? thought.origin : "";
    if (!nodeId || !origin) continue;
    origins[nodeId] = origin;
  }
  return origins;
}
function cognitionStateForMember(origin: string | undefined): AgentNode["cognitionState"] {
  if (origin === "active_node") return "active";
  if (origin === "ripple_response") return "ripple";
  return "background";
}
type GroundedActionState = {
  action: string;
  caption: string;
};

function latestGroundedActionStateByActor(actions: GroundedAction[]) {
  const states: Record<string, GroundedActionState> = {};
  for (const action of actions) {
    if (!action.actor_id) continue;
    states[action.actor_id] = {
      action: action.action,
      caption: groundedActionCaption(action),
    };
  }
  return states;
}
export function groundedActionCaption(action: GroundedAction): string {
  const actionCue = [...(action.effects || [])]
    .reverse()
    .find((effect) => (
      effect.type === "action_bullet_add"
      && (!effect.target?.id || effect.target.id === action.actor_id)
      && typeof effect.text === "string"
      && effect.text.trim().length > 0
    ));
  return typeof actionCue?.text === "string" && actionCue.text.trim()
    ? actionCue.text.trim()
    : actionLabel(action.action);
}
function groupPayloads(items: Array<Record<string, unknown>>) {
  const grouped: Record<string, DisplayPayload[]> = {};
  for (const item of items || []) {
    const nodeId = typeof item.node_id === "string" ? item.node_id : "";
    const text = typeof item.text === "string" ? item.text : "";
    if (!nodeId || !text) continue;
    grouped[nodeId] = grouped[nodeId] || [];
    grouped[nodeId].push(toDisplayPayload(item, nodeId, text));
  }
  return grouped;
}
function scheduledThoughtPayloads(items: Array<Record<string, unknown>>) {
  const scheduled: DisplayPayload[] = [];
  for (const [index, item] of (items || []).entries()) {
    const nodeId = typeof item.node_id === "string" ? item.node_id : "";
    const text = typeof item.text === "string" ? item.text : "";
    if (!nodeId || !text) continue;
    const payload = toDisplayPayload(item, nodeId, text);
    if (typeof payload.delay === "number") {
      scheduled.push(payload);
    } else {
      scheduled.push(...unfoldMindPayload(payload, index));
    }
  }
  return scheduled.sort((a, b) => Number(a.delay ?? 0) - Number(b.delay ?? 0));
}
function speechBubblePayloads(items: Array<Record<string, unknown>>) {
  return (items || []).flatMap((item, index) => {
    const nodeId = typeof item.node_id === "string" ? item.node_id : "";
    const text = typeof item.text === "string" ? item.text.trim() : "";
    if (!nodeId || !text) return [];
    const sequence = typeof item.sequence === "number" ? item.sequence : index + 1;
    const speechEventId = typeof item.speech_event_id === "string" ? item.speech_event_id : "";
    return [{
      ...toDisplayPayload(item, nodeId, text),
      occurrence_id: speechEventId
        ? `speech:${speechEventId}`
        : `speech:${sequence}:${nodeId}`,
      ttl: typeof item.ttl === "number" ? item.ttl : 4,
      salience: typeof item.salience === "number" ? item.salience : 0.82,
      origin: "speech",
    }];
  });
}
function unfoldMindPayload(payload: DisplayPayload, sequenceIndex: number): DisplayPayload[] {
  const lines = mindBubbleLines(payload.text);
  const ttl = clamp(Number(payload.ttl ?? MIND_UNFOLD_TTL_SECONDS), 1, 8);
  const interval = mindBubbleInterval(payload.node_id, payload.origin || "", ttl);
  const baseDelay = THOUGHT_START_SECONDS
    + sequenceIndex * THOUGHT_INTERVAL_SECONDS
    + hashFraction(`${payload.origin || "thought"}:${payload.node_id}:start`) * 0.16;
  return lines.map((line, index) => ({
    ...payload,
    text: line,
    delay: baseDelay + index * interval,
    ttl,
    salience: payload.salience ?? 0.86,
  }));
}
function mindBubbleLines(text: string): string[] {
  const clean = text.replace(/\s+/g, " ").trim();
  if (!clean) return [];
  const sentences = clean.match(/[^.!?。！？；;]+(?:[.!?。！？；;]+|$)/g)
    ?.map((sentence) => sentence.trim())
    .filter(Boolean);
  return sentences && sentences.length > 0 ? sentences : [clean];
}
function mindBubbleInterval(nodeId: string, origin: string, ttl: number) {
  const gap = MIND_UNFOLD_GAP_SECONDS + hashFraction(`${origin}:${nodeId}:gap`) * 1.6 - 0.8;
  return Math.max(ttl + 1, ttl + gap);
}

function hashFraction(text: string): number {
  const value = Math.abs(hashString(text));
  return (value % 1000) / 1000;
}

function toDisplayPayload(item: Record<string, unknown>, nodeId: string, text: string): DisplayPayload {
  const sequence = typeof item.sequence === "number" ? item.sequence : 0;
  const sequenceIndex = typeof item.sequence_index === "number" ? item.sequence_index : 0;
  return {
    node_id: nodeId,
    text,
    occurrence_id: typeof item.occurrence_id === "string" && item.occurrence_id
      ? item.occurrence_id
      : sequence > 0 ? `thought:${sequence}:${sequenceIndex}` : undefined,
    expired: item.expired === true,
    display_at: typeof item.display_at === "string" ? item.display_at : undefined,
    expires_at: typeof item.expires_at === "string" ? item.expires_at : undefined,
    generation: typeof item.generation === "number" ? item.generation : undefined,
    cognition_id: typeof item.cognition_id === "string" ? item.cognition_id : undefined,
    delay: typeof item.delay === "number" ? item.delay : undefined,
    ttl: typeof item.ttl === "number" ? item.ttl : undefined,
    salience: typeof item.salience === "number" ? item.salience : undefined,
    origin: typeof item.origin === "string" ? item.origin : undefined,
    ripple_from: typeof item.ripple_from === "string" ? item.ripple_from : undefined,
  };
}

function textList(items: DisplayPayload[] | undefined) {
  if (!items || items.length === 0) return null;
  return items.map((item) => item.text);
}

function displayRole(node: ProjectionNode) {
  const display = typeof node.attributes?.display_role === "string" ? node.attributes.display_role : "";
  const personaTitle = typeof node.attributes?.persona_title === "string" ? node.attributes.persona_title : "";
  const personaArchetype = typeof node.attributes?.persona_archetype === "string" ? node.attributes.persona_archetype : "";
  const identity = typeof node.attributes?.identity === "string" ? node.attributes.identity : "";
  const role = typeof node.attributes?.role === "string" ? node.attributes.role : "";
  if (display || personaArchetype || personaTitle) return display || personaArchetype || personaTitle;
  if (isFunctionalMemberName(node)) {
    const persona = fallbackPersona(node);
    return `${persona.title} / ${role || node.role || node.type || "network"}`;
  }
  return node.role || identity || role || node.type || "节点";
}

function displayName(node: ProjectionNode) {
  if (isFunctionalMemberName(node)) return fallbackPersona(node).name;
  return node.name || node.role || node.id;
}

function isFunctionalMemberName(node: ProjectionNode) {
  if (node.type !== "organization_member") return false;
  const role = String(node.attributes?.role || node.role || "").replace(/_/g, " ").toLowerCase();
  const name = String(node.name || "").replace(/_/g, " ").toLowerCase();
  if (!role || !name) return false;
  return name === role || name === titleCase(role).toLowerCase();
}

function fallbackPersona(node: ProjectionNode) {
  const role = String(node.attributes?.role || node.role || "network");
  const seed = hashString(`${node.id}:${role}`);
  const given = PERSONA_GIVEN_NAMES[seed % PERSONA_GIVEN_NAMES.length];
  const family = PERSONA_FAMILY_NAMES[Math.floor(seed / 7) % PERSONA_FAMILY_NAMES.length];
  const title = PERSONA_TITLES[Math.floor(seed / 13) % PERSONA_TITLES.length];
  return { name: `${given} ${family}`, title };
}

function titleCase(value: string) {
  return value.split(/\s+/).filter(Boolean).map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`).join(" ");
}

function memberPosition(index: number, count: number) {
  if (count <= 1) return { x: 50, y: 50 };
  const ringIndex = Math.floor(index / 14);
  const indexInRing = index % 14;
  const countInRing = Math.min(14, count - ringIndex * 14);
  const angle = (-90 + (360 * indexInRing) / countInRing + ringIndex * 18) * (Math.PI / 180);
  const radius = 4 + ringIndex * 2;
  return {
    x: 50 + Math.cos(angle) * radius,
    y: 50 + Math.sin(angle) * radius * 0.8,
  };
}

function hubEdges(hub: AgentNode, members: AgentNode[]): NetworkLink[] {
  return members
    .filter((member) => member.id !== hub.id)
    .slice(0, 24)
    .map((member) => ({
      source: hub.id,
      target: member.id,
      type: "member_of",
      weight: 0.9,
    }));
}

function inferredEdges(members: AgentNode[]): NetworkLink[] {
  if (members.length < 2) return [];
  return members.slice(0, 48).map((member, index, visibleMembers) => ({
    source: member.id,
    target: visibleMembers[(index + 1) % visibleMembers.length].id,
    type: "coordination",
    weight: 0.42,
  }));
}

function projectedRelationshipLinks(
  relationships: Array<Record<string, unknown>>,
  visibleIds: Set<string>,
): NetworkLink[] {
  const links: NetworkLink[] = [];
  const seen = new Set<string>();
  const typeCounts: Record<string, number> = {};
  for (const relationship of relationships || []) {
    const source = typeof relationship.source === "string" ? relationship.source : "";
    const target = typeof relationship.target === "string" ? relationship.target : "";
    if (!source || !target || source === target) continue;
    if (!visibleIds.has(source) || !visibleIds.has(target)) continue;
    const type = typeof relationship.type === "string" ? relationship.type : "relationship";
    const key = `${source}->${target}:${type}`;
    if (seen.has(key)) continue;
    const perTypeLimit = type === "member_of" ? 80 : 32;
    if ((typeCounts[type] || 0) >= perTypeLimit) continue;
    seen.add(key);
    typeCounts[type] = (typeCounts[type] || 0) + 1;
    links.push({
      source,
      target,
      type,
      weight: Number.isFinite(Number(relationship.weight)) ? Number(relationship.weight) : 0.5,
    });
    if (links.length >= RELATIONSHIP_LINK_LIMIT) break;
  }
  return links;
}

function keyCharacterInfluenceLinks(
  characters: ProjectionNode[],
  visibleIds: Set<string>,
): InfluenceLink[] {
  const links: InfluenceLink[] = [];
  const seen = new Set<string>();
  for (const character of characters || []) {
    const source = character.id;
    if (!source || !visibleIds.has(source)) continue;
    const keyCharacter = dict(character.key_character);
    const circle = Array.isArray(keyCharacter.influence_circle) ? keyCharacter.influence_circle : [];
    const fallback = stringValue(keyCharacter.current_step) || stringValue(keyCharacter.goal) || "关键角色影响";
    const salience = numeric(keyCharacter.salience_score) ?? 0.5;
    for (const item of circle) {
      const target = dict(item);
      const targetId = stringValue(target.node_id || target.id);
      if (!targetId || targetId === source || !visibleIds.has(targetId)) continue;
      const key = `${source}->${targetId}`;
      if (seen.has(key)) continue;
      seen.add(key);
      links.push({
        source,
        target: targetId,
        label: influenceLinkLabel(target, fallback),
        weight: clamp(salience, 0.2, 1),
      });
      if (links.length >= INFLUENCE_LINK_LIMIT) return links;
    }
  }
  return links;
}
function influenceLinkLabel(target: Record<string, unknown>, fallback: string): string {
  const role = stringValue(target.role);
  const parent = stringValue(target.parent_network);
  const subject = role || parent;
  const base = subject ? `${subject}: ${fallback}` : fallback;
  return trimLabel(base, 28);
}
function trimLabel(value: string, limit: number): string {
  const clean = value.trim().replace(/\s+/g, " ");
  if (clean.length <= limit) return clean;
  return `${clean.slice(0, Math.max(limit - 1, 1))}…`;
}
function mirroredCoverageNodes(nodes: AgentNode[], limit: number): AgentNode[] {
  const stride = Math.max(1, Math.ceil(nodes.length / Math.max(limit, 1)));
  return nodes
    .filter((node) => !node.id.includes(":coverage-copy"))
    .filter((_, index) => index % stride === 0)
    .slice(0, limit)
    .map((node) => ({
      ...node,
      id: `${node.id}:coverage-copy`,
      name: node.name,
      theta: wrapTheta(node.theta + Math.PI),
      phi: clamp(node.phi * 0.92, -1.1, 1.1),
      orbit: node.orbit,
      phase: node.phase + 1.73,
      parent: node.parent ? `${node.parent} projection` : "projection copy",
      attributes: {
        ...node.attributes,
        projection_copy: true,
        source_node_id: node.id,
      },
    }));
}
function wrapTheta(value: number) {
  let next = value;
  while (next > Math.PI) next -= Math.PI * 2;
  while (next < -Math.PI) next += Math.PI * 2;
  return next;
}
