import type {
  RunControlRequest,
  RunControlResponse,
  RunAdvanceResponse,
  Run as RunDetail,
  RunInterventionResponse,
  RunRetryRequest,
  RunRetryResponse,
  RunSovereignIntentRequest,
  RunSovereignIntentResponse,
  RunStreamResponse,
  Scenario,
  SessionResponse,
  TimelineResponse,
  ViewerProjection
} from "../types/contracts";
import type { RuntimeProviderConfig } from "../app/runtimeTypes";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";
const SESSION_TOKEN_KEY = "ai-native-world-session-token";

let memorySessionToken = "";
let pendingSession: Promise<string> | null = null;

type DemoRunInput = {
  scenario: string;
  seed: number;
  ticks: number;
  runtimeProvider?: RuntimeProviderConfig;
  requireCognitionReady?: boolean;
};

export type RuntimeHealth = {
  status: "ok" | "degraded";
  repository_mode: string;
  worker_mode: "embedded" | "external" | "disabled";
  queue_available: boolean;
  runtime_ready: boolean;
  reason?: string;
};

export async function getRuntimeHealth(): Promise<RuntimeHealth> {
  return request<RuntimeHealth>("/api/health");
}

export async function listScenarios(): Promise<Scenario[]> {
  return request<Scenario[]>("/api/scenarios");
}

export async function createDemoRun(input: DemoRunInput): Promise<RunDetail> {
  const params = new URLSearchParams({
    scenario: input.scenario,
    seed: String(input.seed),
    ticks: String(input.ticks)
  });
  return request<RunDetail>(`/api/runs?${params.toString()}`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      scenario: input.scenario,
      seed: input.seed,
      ticks: input.ticks,
      runtime_provider: input.runtimeProvider,
      require_cognition_ready: input.requireCognitionReady ?? false,
    }),
  });
}

export async function getRunDetail(runId: string): Promise<RunDetail> {
  return request<RunDetail>(`/api/runs/${encodeURIComponent(runId)}`);
}

export async function getRunProjection(runId: string): Promise<ViewerProjection> {
  return request<ViewerProjection>(`/api/runs/${encodeURIComponent(runId)}/projection`);
}

export async function consumeThoughtSchedules(runId: string, scheduleSequences: number[]): Promise<void> {
  if (scheduleSequences.length === 0) return;
  await request(`/api/runs/${encodeURIComponent(runId)}/presentation/consume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ schedule_sequences: scheduleSequences }),
  });
}

export async function consumeThoughtOccurrences(runId: string, occurrenceIds: string[]): Promise<void> {
  const normalized = [...new Set(occurrenceIds.map(String).filter(Boolean))];
  if (normalized.length === 0) return;
  await request(`/api/runs/${encodeURIComponent(runId)}/presentation/consume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ occurrence_ids: normalized }),
  });
}

export async function getRunTimeline(runId: string, cursor = 0, limit = 200): Promise<TimelineResponse> {
  const params = new URLSearchParams({ cursor: String(cursor), limit: String(limit) });
  return request<TimelineResponse>(`/api/runs/${encodeURIComponent(runId)}/timeline?${params.toString()}`);
}

export async function getRunStream(
  runId: string,
  cursor = 0,
  limit = 50
): Promise<RunStreamResponse> {
  const params = new URLSearchParams({ cursor: String(cursor), limit: String(limit) });
  return request<RunStreamResponse>(`/api/runs/${encodeURIComponent(runId)}/stream?${params.toString()}`);
}

export async function controlRun(runId: string, input: RunControlRequest): Promise<RunControlResponse> {
  return request<RunControlResponse>(`/api/runs/${encodeURIComponent(runId)}/control`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json"
    },
    body: JSON.stringify(input)
  });
}

export async function retryRun(runId: string, input: RunRetryRequest): Promise<RunRetryResponse> {
  return request<RunRetryResponse>(`/api/runs/${encodeURIComponent(runId)}/retry`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json"
    },
    body: JSON.stringify(input)
  });
}

export async function advanceRun(runId: string): Promise<RunAdvanceResponse> {
  return request<RunAdvanceResponse>(`/api/runs/${encodeURIComponent(runId)}/advance`, {
    method: "POST"
  });
}

export async function addRunIntervention(
  runId: string,
  intervention: Record<string, unknown>
): Promise<RunInterventionResponse> {
  return request<RunInterventionResponse>(`/api/runs/${encodeURIComponent(runId)}/interventions`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json"
    },
    body: JSON.stringify(intervention)
  });
}

export async function addRunSovereignIntent(
  runId: string,
  input: RunSovereignIntentRequest
): Promise<RunSovereignIntentResponse> {
  return request<RunSovereignIntentResponse>(`/api/runs/${encodeURIComponent(runId)}/sovereign-intents`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json"
    },
    body: JSON.stringify(input)
  });
}

export async function waitForRunCompletion(
  runId: string,
  onStatus?: (run: RunDetail) => void,
  options: { attempts?: number; delayMs?: number } = {}
): Promise<RunDetail> {
  const attempts = options.attempts ?? 30;
  const delayMs = options.delayMs ?? 600;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const run = await getRunDetail(runId);
    onStatus?.(run);
    if (run.status === "completed") return run;
    if (run.status === "failed") {
      throw new Error(run.error || `Run ${runId} failed`);
    }
    await delay(delayMs);
  }
  throw new Error(`Run ${runId} did not complete after ${attempts} attempts`);
}

async function request<T>(path: string, init?: RequestInit, mayRetry = true): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  const token = readSessionToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers
  });
  if (response.status === 401 && mayRetry) {
    clearSessionToken();
    const nextToken = await ensureSessionToken();
    const retryHeaders = new Headers(init?.headers);
    if (!retryHeaders.has("Accept")) retryHeaders.set("Accept", "application/json");
    retryHeaders.set("Authorization", `Bearer ${nextToken}`);
    return request<T>(path, { ...init, headers: retryHeaders }, false);
  }
  if (!response.ok) {
    let detail = "";
    try {
      const payload = await response.json() as { detail?: string; error?: string };
      detail = String(payload.detail || payload.error || "").trim();
    } catch {
      detail = "";
    }
    throw new Error(detail ? `API request failed: ${response.status} · ${detail}` : `API request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

async function ensureSessionToken(): Promise<string> {
  const existing = readSessionToken();
  if (existing) return existing;
  if (pendingSession) return pendingSession;
  pendingSession = createAnonymousSession();
  try {
    return await pendingSession;
  } finally {
    pendingSession = null;
  }
}

async function createAnonymousSession(): Promise<string> {
  const response = await fetch(`${API_BASE}/api/sessions`, {
    method: "POST",
    headers: { Accept: "application/json" }
  });
  if (!response.ok) throw new Error(`Session request failed: ${response.status}`);
  const session = (await response.json()) as SessionResponse;
  memorySessionToken = session.access_token;
  if (typeof window !== "undefined") {
    window.sessionStorage.setItem(SESSION_TOKEN_KEY, session.access_token);
  }
  return session.access_token;
}

function readSessionToken(): string {
  if (memorySessionToken) return memorySessionToken;
  if (typeof window === "undefined") return "";
  memorySessionToken = window.sessionStorage.getItem(SESSION_TOKEN_KEY) ?? "";
  return memorySessionToken;
}

function clearSessionToken(): void {
  memorySessionToken = "";
  if (typeof window !== "undefined") {
    window.sessionStorage.removeItem(SESSION_TOKEN_KEY);
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
