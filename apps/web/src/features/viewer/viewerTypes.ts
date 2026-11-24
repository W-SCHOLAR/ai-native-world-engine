import type {
  GroundedAction,
  ProjectionNode,
  RunStatus,
  ViewerProjection,
} from "../../types/contracts";

export type { GroundedAction, ProjectionNode, RunStatus, ViewerProjection };

export type GlobeParticle = {
  x: number;
  y: number;
  z: number;
  size: number;
  land: boolean;
  cityLight: boolean;
  dataPulse: boolean;
  phase: number;
};

export type AgentKind = "network" | "key" | "world";

export type AgentNode = {
  id: string;
  name: string;
  role: string;
  type: string;
  kind: AgentKind;
  parent: string;
  theta: number;
  phi: number;
  orbit: number;
  phase: number;
  thought: string[];
  action: string[];
  recentAction?: string;
  cognitionState?: "active" | "ripple" | "background" | "idle";
  keyCharacter: Record<string, unknown>;
  attributes: Record<string, unknown>;
};

export type NetworkLink = {
  source: string;
  target: string;
  type: string;
  weight: number;
};

export type InfluenceLink = {
  source: string;
  target: string;
  label: string;
  weight: number;
};

export type DisplayPayload = {
  node_id: string;
  text: string;
  occurrence_id?: string;
  expired?: boolean;
  display_at?: string;
  expires_at?: string;
  generation?: number;
  cognition_id?: string;
  feedback_sequence?: number;
  delay?: number;
  ttl?: number;
  salience?: number;
  origin?: string;
  ripple_from?: string;
};

export type AiTrace = {
  node_id?: string;
  thought?: Record<string, unknown>;
  pressure?: Record<string, unknown>;
  matched?: boolean;
  action?: Record<string, unknown>;
  tick?: number | string;
};

export type AiCausalityHistoryItem = {
  tick: number | string;
  nodeId: string;
  matched: boolean;
  thought: string;
  pressure: string;
  action: string;
};

export type GroundedEffect = NonNullable<GroundedAction["effects"]>[number];

export type ProjectedAgent = AgentNode & {
  screenX: number;
  screenY: number;
  /** Presentation anchor for thought bubbles; source coordinates stay unchanged. */
  thoughtAnchorY?: number;
  /** Presentation anchor at the actor's visible feet for behavior captions. */
  actionAnchorY?: number;
  depth: number;
};

export type NormalizedWorld = {
  summary: ViewerProjection["summary"];
  organizationCount: number;
  characterCount: number;
  agentNodes: AgentNode[];
  networkLinks: NetworkLink[];
  influenceLinks: InfluenceLink[];
  scheduledThoughts: DisplayPayload[];
  speechBubbles: DisplayPayload[];
  currentActions: DisplayPayload[];
  actionCoverage: ActionCoverage;
  groundedActions: GroundedAction[];
};

export type ActionCoverageRow = {
  action: string;
  label: string;
  count: number;
  state: "hit" | "missing" | "idle";
};

export type ActionCoverage = {
  hasSummary: boolean;
  coveragePct: number;
  hitCount: number;
  missingCount: number;
  totalCount: number;
  rows: ActionCoverageRow[];
};

export type DomainSignal = {
  key: string;
  label: string;
  value: string;
  detail: string;
  state: "low" | "watch" | "high" | "idle";
  actionHints: string[];
};

export type DomainSignalHistoryPoint = {
  tick: number | string;
  value: string;
  state: DomainSignal["state"];
  present: boolean;
};

export type DomainSignalHistory = {
  key: string;
  label: string;
  points: DomainSignalHistoryPoint[];
  hasTrend: boolean;
};

export type StateFact = {
  kind: string;
  label: string;
  value: string;
};

export type MemoryHighlight = {
  kind: string;
  text: string;
  source: string;
  tick: number | string;
  importance?: number;
  memoryCount?: number;
};

export type RelationshipFact = {
  type: string;
  direction: "out" | "in" | "mutual";
  counterpartId: string;
  counterpartName: string;
  weight: string;
  detail: string;
};

export type RunHealthFact = {
  key: string;
  label: string;
  value: string;
  state: "clean" | "watch" | "issue";
};

export type GovernanceNotice = {
  label: string;
  scenario: string;
  message: string;
  riskLevel: string;
  state: "normal" | "watch" | "high";
};

export type MemoryMaintenanceFact = {
  key: string;
  label: string;
  value: string;
  state: "idle" | "active" | "forgetting";
};

export type MemoryMaintenanceRow = {
  nodeId: string;
  tick: number | string;
  kind: string;
  text: string;
  memoryCount: number;
  forgottenCount: number;
  tickStart: number | string;
  tickEnd: number | string;
  keywords: string[];
};

export type WorldEventTickerItem = {
  kind: "grounded" | "action" | "thought";
  tick: number | string;
  label: string;
  text: string;
  salience: number;
};

export type RuntimeMetrics = {
  state: string;
  mode: string;
  lastStepStatus: string;
  tickLabel: string;
  percentLabel: string;
  percent: number;
};

export type CausalPathItem = {
  id: string;
  label: string;
  role: "actor" | "target" | "effect";
};

export type CausalFocus = {
  actorId: string;
  targetIds: string[];
  effectNodeIds: string[];
  selectedEffectNodeIds: string[];
  pathItems: CausalPathItem[];
};

export type GlobeRuntime = {
  particles: GlobeParticle[];
  startedAt: number;
  yaw: number;
  pitch: number;
  zoom: number;
  targetYaw: number | null;
  targetPitch: number | null;
  targetZoom: number | null;
  focused: boolean;
  overviewYaw: number | null;
  overviewPitch: number | null;
  tribeFocusX: number;
  tribeFocusY: number;
  targetTribeFocusX: number | null;
  targetTribeFocusY: number | null;
  tribeFocusedNetworkId: string | null;
  tribeOverviewFocusX: number | null;
  tribeOverviewFocusY: number | null;
  velocityYaw: number;
  velocityPitch: number;
  dragging: boolean;
  pointerMoved: boolean;
  lastPointerX: number;
  lastPointerY: number;
  lastFrame: number;
  visibleAgents: ProjectedAgent[];
};

export type OverlayItem = {
  id: string;
  type: "thought" | "speech" | "action";
  nodeId: string;
  text: string;
  x: number;
  y: number;
  offsetX: number;
  offsetY: number;
  salience: number;
  origin?: string;
  createdAt: number;
  lifetimeMs: number;
  renderLines?: string[];
  renderWidth?: number;
  renderHeight?: number;
  renderText?: string;
};

export const WORLD_ACTION_LABELS: Array<[string, string]> = [
  ["combat_attack", "战斗"],
  ["collaboration", "协作"],
  ["economic_exchange", "交易"],
  ["infection_progress", "病程"],
  ["infection_spread", "传播"],
  ["logistics_transfer", "物流"],
  ["migration", "迁徙"],
  ["organization_decision", "决策"],
  ["production", "生产"],
  ["quarantine_policy", "隔离"],
  ["science_publish", "发表"],
  ["social_spread", "舆论"],
];

export const EMPTY_WORLD: NormalizedWorld = {
  summary: {},
  organizationCount: 0,
  characterCount: 0,
  agentNodes: [],
  networkLinks: [],
  influenceLinks: [],
  scheduledThoughts: [],
  speechBubbles: [],
  currentActions: [],
  actionCoverage: {
    hasSummary: false,
    coveragePct: 0,
    hitCount: 0,
    missingCount: 0,
    totalCount: 0,
    rows: [],
  },
  groundedActions: [],
};
