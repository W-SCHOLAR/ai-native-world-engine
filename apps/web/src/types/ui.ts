export type InterventionLogItem = {
  id: string;
  template: string;
  targetId: string;
  targetName: string;
  scheduledTick: number;
  summary: string;
  status: "queued" | "applied" | "rejected";
  appliedTick?: number | string;
  effectCount?: number | string;
  error?: string;
};

export type SovereignIntentLogItem = {
  id: string;
  text: string;
  title: string;
  scheduledTick: number;
  impactLevel: string;
  summary: string;
  status: "queued" | "applied" | "rejected";
  appliedTick?: number | string;
  dynamicRuleCount?: number | string;
  error?: string;
};

export type StreamTelemetry = {
  cursor: number;
  nextCursor: number;
  updateBatchSize: number;
  timelineFrameCount: number;
  cursorExpired?: boolean;
  retainedFromCursor?: number;
  retainedToCursor?: number;
  latestTick?: number | string;
};
