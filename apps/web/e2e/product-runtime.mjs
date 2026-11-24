import assert from "node:assert/strict";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { createServer } from "node:http";

import { chromium } from "playwright";


const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "../../..");
const WEB = join(ROOT, "apps/web");
const PYTHON = process.env.AI_NATIVE_WORLD_E2E_PYTHON
  || join(ROOT, "apps/api/.venv/bin/python");
const API_PORT = process.env.AI_NATIVE_WORLD_E2E_API_PORT || "8000";
const WEB_PORT = process.env.AI_NATIVE_WORLD_E2E_WEB_PORT || "5173";
const PROVIDER_PORT = process.env.AI_NATIVE_WORLD_E2E_PROVIDER_PORT || "19091";
const API_URL = `http://127.0.0.1:${API_PORT}`;
const WEB_URL = `http://127.0.0.1:${WEB_PORT}`;
const PROVIDER_URL = `http://127.0.0.1:${PROVIDER_PORT}`;
const tempRoot = mkdtempSync(join(tmpdir(), "ai-native-world-e2e-"));
const databasePath = join(tempRoot, "product.sqlite3");
const processes = [];
const browserLogs = [];
let browser;
let diagnosticPage;
let providerServer;
let liveBootstrapDurationMs = 0;
let providerTimeoutDurationMs = 0;
let providerTimeoutBudgetMs = 0;

if (!existsSync(PYTHON)) {
  throw new Error(`API Python environment not found: ${PYTHON}. Run uv sync --project apps/api first.`);
}

const sharedEnvironment = {
  ...process.env,
  PYTHONPATH: [
    join(ROOT, "src"),
    join(ROOT, "apps/api/src"),
    join(ROOT, "apps/worker/src"),
  ].join(":"),
  AI_NATIVE_WORLD_REPOSITORY: "sqlite",
  AI_NATIVE_WORLD_SQLITE_PATH: databasePath,
  AI_NATIVE_WORLD_WORKER_MODE: "external",
  AI_NATIVE_WORLD_AUTH_MODE: "session",
  AI_NATIVE_WORLD_SESSION_SECRET: "e2e-session-secret-0123456789abcdef",
  AI_NATIVE_WORLD_WORKER_POLL_INTERVAL: "0.01",
  AI_NATIVE_WORLD_WORKER_MAX_STEPS_PER_CYCLE: "1",
  AI_NATIVE_WORLD_WORKER_LEASE_SECONDS: "30",
  AI_NATIVE_WORLD_WORKER_HEARTBEAT_INTERVAL: "5",
  DEEPSEEK_API_KEY: "e2e-server-managed-provider-key",
  AI_NATIVE_WORLD_DEEPSEEK_BASE_URL: PROVIDER_URL,
  AI_NATIVE_WORLD_DEEPSEEK_TIMEOUT: "10",
  AI_NATIVE_WORLD_DEEPSEEK_DEADLINE: "10",
};

try {
  providerServer = await startFakeProviderServer(Number(PROVIDER_PORT));
  const api = startProcess(
    "api",
    PYTHON,
    ["-m", "uvicorn", "ai_native_world_api.main:app", "--host", "127.0.0.1", "--port", API_PORT],
    ROOT,
    sharedEnvironment,
  );
  processes.push(api);
  const web = startProcess(
    "web",
    process.execPath,
    [join(WEB, "node_modules/vite/bin/vite.js"), "--host", "127.0.0.1", "--port", WEB_PORT, "--strictPort"],
    WEB,
    {
      ...process.env,
      VITE_API_PROXY_TARGET: API_URL,
      VITE_AI_NATIVE_WORLD_SERVER_PROVIDER_KEY: "1",
    },
  );
  processes.push(web);
  await waitForUrl(`${API_URL}/api/scenarios`);
  await waitForUrl(WEB_URL);

  browser = await chromium.launch(chromiumLaunchOptions());
  const firstContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const firstPage = await firstContext.newPage();
  diagnosticPage = firstPage;
  firstPage.on("pageerror", (error) => browserLogs.push(`[browser pageerror] ${error.stack || error}`));
  firstPage.on("console", (message) => {
    if (message.type() === "error") browserLogs.push(`[browser console] ${message.text()}`);
  });
  await firstPage.goto(WEB_URL, { waitUntil: "domcontentloaded" });
  const firstRunResponse = firstPage.waitForResponse((response) => (
    response.status() === 200
    &&
    response.request().method() === "POST"
    && new URL(response.url()).pathname === "/api/runs"
  ));
  await configureDeterministicProvider(firstPage);
  const firstRun = await (await firstRunResponse).json();

  assert.equal(firstRun.scenario, "enterprise_earth");
  assert.equal(firstRun.status, "queued");
  assert.equal(firstRun.bootstrap_state.phase, "creating_world");
  assert.equal(firstRun.bootstrap_state.ready, false);
  assert.match(firstRun.owner_id, /^user_/);
  await firstPage.locator(".world-bootstrap-card").waitFor({ state: "visible" });
  assert.equal(await firstPage.locator(".world-stage").count(), 0);
  await firstPage.waitForFunction(() => Boolean(sessionStorage.getItem("ai-native-world-session-token")));
  const queuedRead = await authenticatedFetch(firstPage, `/api/runs/${firstRun.id}`);
  const queuedReadAgain = await authenticatedFetch(firstPage, `/api/runs/${firstRun.id}`);
  assert.equal(queuedRead.json.runtime_state.tick_cursor, 0);
  assert.equal(queuedReadAgain.json.runtime_state.tick_cursor, 0);

  const worker = startProcess(
    "worker",
    PYTHON,
    ["-m", "ai_native_world_worker.cli"],
    ROOT,
    { ...sharedEnvironment, AI_NATIVE_WORLD_WORKER_ID: "e2e-worker" },
  );
  processes.push(worker);

  const liveRun = await waitForRunReady(firstPage, firstRun.id, 60_000);
  assert.equal(liveRun.status, "running");
  assert.equal(liveRun.bootstrap_state.phase, "ready");
  assert.ok(liveRun.bootstrap_state.committed_pressure_ids.length > 0);
  assert.ok(liveRun.bootstrap_state.accepted_thought_sequences.length > 0);
  await firstPage.locator(".world-stage").waitFor({ state: "visible", timeout: 30_000 });

  const pauseButton = firstPage.getByRole("button", { name: "Pause", exact: true });
  await pauseButton.waitFor({ state: "visible" });
  await pauseButton.click();
  await assertText(firstPage.locator(".interaction-runtime-state span"), /paused/);
  await firstPage.getByRole("button", { name: "Resume" }).click();
  await assertText(firstPage.locator(".interaction-runtime-state span"), /active/);

  const intentInput = firstPage.getByRole("textbox", { name: "旨意" });
  await intentInput.fill("让部落在黎明前点燃新的篝火");
  await firstPage.getByRole("button", { name: "下旨" }).click();
  await firstPage.locator(".interaction-receipts article").waitFor({ state: "visible" });

  await assertText(firstPage.locator(".interaction-receipts article"), /Applied|Queued/);

  const canceledFirstRun = await authenticatedFetch(
    firstPage,
    `/api/runs/${firstRun.id}/control`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command: "cancel", reason: "e2e cleanup", actor_id: "e2e" }),
    },
  );
  assert.equal(canceledFirstRun.json.status, "failed");
  assert.equal(canceledFirstRun.json.control_state, "canceled");
  await assertText(firstPage.locator(".interaction-runtime-state span"), /failed · canceled/, 30_000);

  const readBefore = await authenticatedFetch(firstPage, `/api/runs/${firstRun.id}`);
  await delay(250);
  const readAgain = await authenticatedFetch(firstPage, `/api/runs/${firstRun.id}`);
  assert.ok(readBefore.json.runtime_state.tick_cursor >= 1);
  assert.equal(readAgain.json.runtime_state.tick_cursor, readBefore.json.runtime_state.tick_cursor);

  const secondContext = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const secondPage = await secondContext.newPage();
  await secondPage.goto(WEB_URL, { waitUntil: "domcontentloaded" });
  const secondRunResponse = secondPage.waitForResponse((response) => (
    response.status() === 200
    &&
    response.request().method() === "POST"
    && new URL(response.url()).pathname === "/api/runs"
  ));
  await configureDeterministicProvider(secondPage, "tribe_survival");
  const secondRun = await (await secondRunResponse).json();
  await secondPage.waitForFunction(() => Boolean(sessionStorage.getItem("ai-native-world-session-token")));
  assert.equal(secondRun.scenario, "tribe_survival");
  assert.notEqual(secondRun.owner_id, firstRun.owner_id);
  const hidden = await authenticatedFetch(secondPage, `/api/runs/${firstRun.id}`);
  assert.equal(hidden.json.error, "run_not_found");
  const secondRuns = await authenticatedFetch(secondPage, "/api/runs");
  assert.equal(secondRuns.json.some((run) => run.id === firstRun.id), false);
  assert.equal(secondRuns.json.some((run) => run.id === secondRun.id), true);
  const secondLiveRun = await waitForRunReady(secondPage, secondRun.id, 60_000);
  assert.equal(secondLiveRun.bootstrap_state.phase, "ready");
  await secondPage.locator('.world-stage[data-scene="tribe-survival-map"]').waitFor({ state: "visible", timeout: 30_000 });
  await authenticatedFetch(
    secondPage,
    `/api/runs/${secondRun.id}/control`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command: "cancel", reason: "e2e cleanup", actor_id: "e2e" }),
    },
  );

  providerServer.setMode("hold");
  const heldContext = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const heldPage = await heldContext.newPage();
  await heldPage.goto(WEB_URL, { waitUntil: "domcontentloaded" });
  const heldRunResponse = heldPage.waitForResponse((response) => (
    response.status() === 200
    && response.request().method() === "POST"
    && new URL(response.url()).pathname === "/api/runs"
  ));
  await configureLiveProvider(heldPage, "enterprise_earth", PROVIDER_URL);
  const heldRun = await (await heldRunResponse).json();
  await heldPage.waitForFunction(() => Boolean(sessionStorage.getItem("ai-native-world-session-token")));
  const heldState = await waitForBootstrapPhase(heldPage, heldRun.id, "waiting_provider", 30_000);
  assert.equal(heldState.runtime_state.tick_cursor, 0);
  assert.equal(await heldPage.locator(".world-stage").count(), 0);
  assert.ok(providerServer.requestCount() > 0);
  providerServer.setMode("success");
  const heldReady = await waitForRunReady(heldPage, heldRun.id, 60_000);
  assert.equal(heldReady.bootstrap_state.phase, "ready");
  assert.ok(heldReady.bootstrap_state.committed_pressure_ids.length > 0);
  liveBootstrapDurationMs = bootstrapDurationMs(heldReady.bootstrap_state);
  assert.ok(liveBootstrapDurationMs > 0);
  await heldPage.locator('.world-stage[data-scene="globe"]').waitFor({ state: "visible", timeout: 30_000 });
  await authenticatedFetch(
    heldPage,
    `/api/runs/${heldRun.id}/control`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command: "cancel", reason: "e2e cleanup", actor_id: "e2e" }),
    },
  );
  await heldContext.close();

  providerServer.setMode("fail");
  const failedContext = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const failedPage = await failedContext.newPage();
  await failedPage.goto(WEB_URL, { waitUntil: "domcontentloaded" });
  const failedRunResponse = failedPage.waitForResponse((response) => (
    response.status() === 200
    && response.request().method() === "POST"
    && new URL(response.url()).pathname === "/api/runs"
  ));
  await configureLiveProvider(failedPage, "tribe_survival", PROVIDER_URL);
  const failedRun = await (await failedRunResponse).json();
  await failedPage.getByRole("heading", { name: "暂时无法进入世界" }).waitFor({ state: "visible", timeout: 30_000 });
  const failedState = await authenticatedFetch(failedPage, `/api/runs/${failedRun.id}`);
  assert.equal(failedState.json.status, "failed");
  assert.equal(failedState.json.bootstrap_state.phase, "timed_out");
  providerTimeoutDurationMs = bootstrapDurationMs(failedState.json.bootstrap_state);
  providerTimeoutBudgetMs = bootstrapDeadlineBudgetMs(failedState.json.bootstrap_state);
  assert.ok(providerTimeoutBudgetMs >= 9_500 && providerTimeoutBudgetMs <= 10_500);
  assert.ok(providerTimeoutDurationMs >= 9_500);
  assert.equal(await failedPage.locator(".world-stage").count(), 0);
  providerServer.setMode("success");
  const replacementResponse = failedPage.waitForResponse((response) => (
    response.status() === 200
    && response.request().method() === "POST"
    && new URL(response.url()).pathname === `/api/runs/${failedRun.id}/retry`
  ));
  await failedPage.getByRole("button", { name: "重新创建世界" }).click();
  const replacement = await (await replacementResponse).json();
  assert.equal(replacement.retry_disposition, "replacement");
  assert.equal(replacement.run.retry_of_run_id, failedRun.id);
  assert.notEqual(replacement.run.id, failedRun.id);
  const replacementReady = await waitForRunReady(failedPage, replacement.run.id, 60_000);
  assert.equal(replacementReady.bootstrap_state.phase, "ready");
  await failedPage.locator('.world-stage[data-scene="tribe-survival-map"]').waitFor({ state: "visible", timeout: 30_000 });
  await authenticatedFetch(
    failedPage,
    `/api/runs/${replacement.run.id}/control`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command: "cancel", reason: "e2e cleanup", actor_id: "e2e" }),
    },
  );
  await failedContext.close();

  await assertMockBootstrapFailure(browser, "failed", WEB_URL);
  await assertMockBootstrapFailure(browser, "timed_out", WEB_URL);


  console.log(JSON.stringify({
    status: "passed",
    first_run_id: firstRun.id,
    second_run_id: secondRun.id,
    first_run_tick: readAgain.json.runtime_state.tick_cursor,
    first_run_control_state: readAgain.json.control_state,
    live_bootstrap_duration_ms: liveBootstrapDurationMs,
    provider_timeout_duration_ms: providerTimeoutDurationMs,
    provider_timeout_budget_ms: providerTimeoutBudgetMs,
    fake_provider_request_count: providerServer.requestCount(),
  }, null, 2));
} catch (error) {
  if (diagnosticPage) {
    process.stderr.write(`[browser body]\n${await diagnosticPage.locator("body").innerText().catch(() => "<unavailable>")}\n`);
    await diagnosticPage.screenshot({ path: join(tempRoot, "failure.png"), fullPage: true }).catch(() => undefined);
  }
  if (browserLogs.length > 0) {
    process.stderr.write(`${browserLogs.join("\n")}\n`);
  }
  for (const processRecord of processes) {
    process.stderr.write(`[${processRecord.name} logs]\n${processRecord.logs.join("")}\n`);
  }
  throw error;
} finally {
  if (browser) await browser.close();
  await Promise.all(processes.reverse().map(stopProcess));
  if (providerServer) await providerServer.close();
  rmSync(tempRoot, { recursive: true, force: true });
}


function startProcess(name, command, args, cwd, env) {
  const child = spawn(command, args, { cwd, env, stdio: ["ignore", "pipe", "pipe"] });
  const logs = [];
  const collect = (chunk) => {
    logs.push(chunk.toString());
    if (logs.length > 80) logs.shift();
  };
  child.stdout.on("data", collect);
  child.stderr.on("data", collect);
  child.on("exit", (code, signal) => {
    if (code && code !== 0) {
      process.stderr.write(`[${name}] exited code=${code} signal=${signal}\n${logs.join("")}\n`);
    }
  });
  return { name, child, logs };
}


async function stopProcess(processRecord) {
  const { child } = processRecord;
  if (child.exitCode !== null || child.signalCode !== null) return;
  child.kill("SIGTERM");
  await Promise.race([
    new Promise((resolvePromise) => child.once("exit", resolvePromise)),
    delay(2_000).then(() => child.kill("SIGKILL")),
  ]);
}


async function waitForUrl(url, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
      lastError = new Error(`${url} returned ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await delay(100);
  }
  throw lastError || new Error(`Timed out waiting for ${url}`);
}


async function assertText(locator, pattern, timeout = 30_000) {
  await locator.waitFor({ state: "visible", timeout });
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const value = (await locator.textContent()) || "";
    if (pattern.test(value)) return;
    await delay(100);
  }
  assert.match((await locator.textContent()) || "", pattern);
}


async function configureDeterministicProvider(page, scenario = "enterprise_earth") {
  await page.getByRole("combobox", { name: "世界场景" }).selectOption(scenario);
  await page.getByRole("combobox", { name: "模型 Provider" }).selectOption("deterministic");
  await page.getByRole("button", { name: "使用本地 Provider 启动" }).click();
}


async function configureLiveProvider(page, scenario, providerUrl) {
  await page.getByRole("combobox", { name: "世界场景" }).selectOption(scenario);
  await page.getByRole("combobox", { name: "模型 Provider" }).selectOption("deepseek");
  await page.getByRole("textbox", { name: "API 地址或路径" }).fill(providerUrl);
  await page.getByRole("textbox", { name: "模型名称" }).fill("e2e-causal-model");
  await page.getByRole("button", { name: "启动模型并进入世界" }).click();
}


async function assertMockBootstrapFailure(browserInstance, phase, webUrl) {
  const context = await browserInstance.newContext({ viewport: { width: 1100, height: 760 } });
  const page = await context.newPage();
  const apiRoutePattern = `${new URL(webUrl).origin}/api/**`;
  const bootstrapState = {
    phase,
    scenario_id: "enterprise_earth",
    provider_mode: "deterministic",
    ready: false,
    retryable: true,
    error_code: phase === "timed_out" ? "initial_provider_timeout" : "initial_provider_no_groundable_pressure",
    error_message: phase === "timed_out" ? "Provider timed out" : "Provider failed causal grounding",
  };
  await page.route(apiRoutePattern, async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === "/api/scenarios") {
      await route.fulfill({ json: [{ id: "enterprise_earth", name: "Enterprise Earth", description: "mock", source: "engine", defaults: { ticks: 100 } }] });
      return;
    }
    if (path === "/api/health") {
      await route.fulfill({ json: { status: "ok", repository_mode: "memory", worker_mode: "embedded", queue_available: true, runtime_ready: true } });
      return;
    }
    if (path === "/api/sessions") {
      await route.fulfill({ json: { access_token: "mock-session", token_type: "bearer", expires_in: 3600 } });
      return;
    }
    if (path === "/api/runs" && route.request().method() === "POST") {
      await route.fulfill({ json: {
        id: `mock-${phase}`,
        owner_id: "mock-user",
        scenario: "enterprise_earth",
        seed: 7,
        ticks: 100,
        status: "queued",
        control_state: "active",
        runtime_state: { tick_cursor: 0, bootstrap_state: { ...bootstrapState, phase: "creating_world", error_code: "", error_message: "" } },
        bootstrap_state: { ...bootstrapState, phase: "creating_world", error_code: "", error_message: "" },
      } });
      return;
    }
    if (path === `/api/runs/mock-${phase}/retry` && route.request().method() === "POST") {
      await route.fulfill({ json: {
        source_run_id: `mock-${phase}`,
        retry_disposition: "replacement",
        run: {
          id: `mock-${phase}-retry`,
          owner_id: "mock-user",
          scenario: "enterprise_earth",
          seed: 7,
          ticks: 100,
          status: "queued",
          control_state: "active",
          runtime_state: { tick_cursor: 0, bootstrap_state: { ...bootstrapState, phase: "creating_world", error_code: "", error_message: "" } },
          bootstrap_state: { ...bootstrapState, phase: "creating_world", error_code: "", error_message: "" },
          retry_of_run_id: `mock-${phase}`,
          retry_attempt: 1,
        },
      } });
      return;
    }
    if (path.endsWith("/advance")) {
      await route.fulfill({ json: {
        run_id: `mock-${phase}`,
        status: "failed",
        completed: true,
        control_state: "active",
        runtime_state: { tick_cursor: 0, bootstrap_state: bootstrapState },
        bootstrap_state: bootstrapState,
        advanced: false,
        previous_tick_cursor: 0,
        tick_cursor: 0,
      } });
      return;
    }
    if (path.endsWith("/stream")) {
      await route.fulfill({ json: {
        run_id: `mock-${phase}`,
        status: "failed",
        cursor: 0,
        next_cursor: 0,
        retained_from_cursor: 0,
        retained_to_cursor: 0,
        cursor_expired: false,
        has_more: false,
        completed: true,
        control_state: "active",
        runtime_state: { tick_cursor: 0, bootstrap_state: bootstrapState },
        bootstrap_state: bootstrapState,
        updates: [],
      } });
      return;
    }
    await route.fulfill({ status: 404, json: { error: "unmocked_path", path } });
  });
  await page.goto(webUrl, { waitUntil: "domcontentloaded" });
  await page.getByRole("combobox", { name: "世界场景" }).waitFor({ state: "visible", timeout: 10_000 }).catch(async (error) => {
    throw new Error(`Mock bootstrap page did not render configuration: ${await page.locator("body").innerText()}\n${error}`);
  });
  await configureDeterministicProvider(page);
  await page.getByRole("heading", { name: "暂时无法进入世界" }).waitFor({ state: "visible", timeout: 10_000 });
  assert.equal(await page.locator(".world-stage").count(), 0);
  await page.getByRole("button", { name: "重新创建世界" }).waitFor({ state: "visible" });
  const retryRequestPromise = page.waitForRequest((request) => (
    request.method() === "POST"
    && new URL(request.url()).pathname === `/api/runs/mock-${phase}/retry`
  ));
  await page.getByRole("button", { name: "重新创建世界" }).click();
  const retryRequest = await retryRequestPromise;
  assert.equal(retryRequest.postDataJSON().runtime_provider.mode, "deterministic");
  await page.getByRole("heading", { name: "暂时无法进入世界" }).waitFor({ state: "visible", timeout: 10_000 });
  assert.equal(await page.locator(".world-stage").count(), 0);
  await page.getByRole("button", { name: "返回配置" }).waitFor({ state: "visible" });
  await page.getByRole("button", { name: "返回配置" }).click();
  await page.getByRole("combobox", { name: "世界场景" }).waitFor({ state: "visible" });
  await context.close();
}




async function authenticatedFetch(page, path, init = {}) {
  return page.evaluate(async ({ requestPath, requestInit }) => {
    const token = sessionStorage.getItem("ai-native-world-session-token");
    const headers = new Headers(requestInit.headers || {});
    headers.set("Accept", "application/json");
    headers.set("Authorization", `Bearer ${token}`);
    const response = await fetch(requestPath, { ...requestInit, headers });
    const text = await response.text();
    return { status: response.status, text, json: JSON.parse(text) };
  }, { requestPath: path, requestInit: init });
}


async function waitForRunReady(page, runId, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let lastRun = {};
  while (Date.now() < deadline) {
    const response = await authenticatedFetch(page, `/api/runs/${runId}`);
    lastRun = response.json;
    if (response.json.status === "failed") {
      throw new Error(`Run ${runId} failed: ${response.json.error}`);
    }
    if (response.json.bootstrap_state?.phase === "ready" && response.json.bootstrap_state?.ready) {
      return response.json;
    }
    await delay(100);
  }
  throw new Error(`Timed out waiting for Run ${runId} cognition readiness: ${JSON.stringify({ status: lastRun.status, tick: lastRun.runtime_state?.tick_cursor, bootstrap_state: lastRun.bootstrap_state, provider_pending_count: lastRun.runtime_state?.provider_pending_count, provider_pending: lastRun.runtime_state?.provider_pending, provider_completed: lastRun.runtime_state?.provider_completed, fake_provider: providerServer?.stats(), error: lastRun.error })}`);
}


async function waitForBootstrapPhase(page, runId, phase, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const response = await authenticatedFetch(page, `/api/runs/${runId}`);
    if (response.json.status === "failed") {
      throw new Error(`Run ${runId} failed before ${phase}: ${response.json.error}`);
    }
    if (response.json.bootstrap_state?.phase === phase) return response.json;
    await delay(100);
  }
  throw new Error(`Timed out waiting for Run ${runId} bootstrap phase ${phase}`);
}


async function startFakeProviderServer(port) {
  let mode = "success";
  let requestTotal = 0;
  let responseTotal = 0;
  let lastNodeUpdateCount = -1;
  const requestSummaries = [];
  const held = [];
  const server = createServer((request, response) => {
    const chunks = [];
    request.on("data", (chunk) => chunks.push(chunk));
    request.on("end", () => {
      requestTotal += 1;
      const rawBody = Buffer.concat(chunks).toString("utf8");
      if (mode === "hold") {
        held.push({ response, rawBody });
        return;
      }
      const result = respondToFakeProvider(response, rawBody, mode);
      lastNodeUpdateCount = result.nodeUpdateCount;
      requestSummaries.push(result.summary);
      responseTotal += 1;
    });
  });
  await new Promise((resolvePromise, rejectPromise) => {
    server.once("error", rejectPromise);
    server.listen(port, "127.0.0.1", resolvePromise);
  });
  return {
    requestCount: () => requestTotal,
    stats: () => ({ mode, requestTotal, responseTotal, held: held.length, lastNodeUpdateCount, requestSummaries: requestSummaries.slice(-20) }),
    setMode(nextMode) {
      mode = nextMode;
      if (nextMode !== "hold") {
        while (held.length > 0) {
          const pending = held.shift();
          const result = respondToFakeProvider(pending.response, pending.rawBody, nextMode);
          lastNodeUpdateCount = result.nodeUpdateCount;
          requestSummaries.push(result.summary);
          responseTotal += 1;
        }
      }
    },
    async close() {
      while (held.length > 0) {
        const pending = held.shift();
        const result = respondToFakeProvider(pending.response, pending.rawBody, "fail");
        lastNodeUpdateCount = result.nodeUpdateCount;
        requestSummaries.push(result.summary);
        responseTotal += 1;
      }
      await new Promise((resolvePromise) => server.close(resolvePromise));
    },
  };
}


function respondToFakeProvider(response, rawBody, mode) {
  if (mode === "fail") {
    response.writeHead(503, { "Content-Type": "application/json" });
    response.end(JSON.stringify({ error: { message: "deliberate e2e provider failure" } }));
    return { nodeUpdateCount: -1, summary: { mode: "fail" } };
  }
  let requestBody = {};
  try {
    requestBody = JSON.parse(rawBody);
  } catch {
    requestBody = {};
  }
  const fixture = fakeCausalProviderOutput(requestBody);
  const output = fixture.output;
  const body = JSON.stringify({
    choices: [{ message: { role: "assistant", content: JSON.stringify(output) }, finish_reason: "stop" }],
    usage: { prompt_tokens: 120, completion_tokens: 80, total_tokens: 200 },
  });
  response.writeHead(200, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) });
  response.end(body);
  return { nodeUpdateCount: output.node_updates.length, summary: fixture.summary };
}


function fakeCausalProviderOutput(requestBody) {
  const messages = Array.isArray(requestBody.messages) ? requestBody.messages : [];
  const userMessage = messages.find((message) => message?.role === "user");
  let dynamic = {};
  try {
    dynamic = JSON.parse(userMessage?.content || "{}");
  } catch {
    dynamic = {};
  }
  const packet = dynamic.context_packet && typeof dynamic.context_packet === "object"
    ? dynamic.context_packet
    : {};
  const decision = packet.decision_context && typeof packet.decision_context === "object"
    ? packet.decision_context
    : {};
  const candidates = Array.isArray(decision.active_candidates)
    ? decision.active_candidates
    : Array.isArray(packet.active_candidates)
      ? packet.active_candidates
      : [];
  const optionGroups = Array.isArray(decision.action_options_by_node)
    ? decision.action_options_by_node
    : [];
  const optionsByNode = new Map(optionGroups.map((group) => [group.node_id, group.options]));
  const nodeUpdates = candidates
    .filter((candidate) => Array.isArray(optionsByNode.get(candidate.id)) && optionsByNode.get(candidate.id).length > 0)
    .map((candidate) => ({
      id: candidate.id,
      visible_thought: `Live relationship thought for ${candidate.name || candidate.id} choosing a grounded action now.`,
      selected_action_option_id: optionsByNode.get(candidate.id)[0].option_id,
      action_weight: 0.72,
      action_ttl: 3,
      action_reason: "推进目标",
    }))
    .slice(0, dynamic.job_kind === "relationship_round" ? 10 : 1);
  return {
    output: {
      summary: "E2E live provider supplied grounded node pressure.",
      node_updates: nodeUpdates,
      metadata: { fixture: "causal-live-provider" },
    },
    summary: {
      jobKind: dynamic.job_kind,
      packetKeys: Object.keys(packet),
      decisionKeys: Object.keys(decision),
      candidateCount: candidates.length,
      optionGroupCount: optionGroups.length,
      nodeUpdateCount: nodeUpdates.length,
    },
  };
}


function chromiumLaunchOptions() {
  const configured = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  const macChrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
  if (configured) return { headless: true, executablePath: configured };
  if (existsSync(macChrome)) return { headless: true, executablePath: macChrome };
  return { headless: true };
}


function delay(ms) {
  return new Promise((resolvePromise) => setTimeout(resolvePromise, ms));
}


function bootstrapDurationMs(state) {
  const started = Date.parse(state.started_at || "");
  const updated = Date.parse(state.updated_at || "");
  return Number.isFinite(started) && Number.isFinite(updated) ? Math.max(updated - started, 0) : 0;
}


function bootstrapDeadlineBudgetMs(state) {
  const started = Date.parse(state.started_at || "");
  const deadline = Date.parse(state.deadline_at || "");
  return Number.isFinite(started) && Number.isFinite(deadline) ? Math.max(deadline - started, 0) : 0;
}
