import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";


const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = join(HERE, "..");
const PORT = 5187;
const WEB_URL = `http://127.0.0.1:${PORT}`;
const vite = spawn(
  process.execPath,
  [join(WEB, "node_modules/vite/bin/vite.js"), "--host", "127.0.0.1", "--port", String(PORT), "--strictPort"],
  { cwd: WEB, env: process.env, stdio: ["ignore", "pipe", "pipe"] },
);
const viteLogs = [];
vite.stdout.on("data", (chunk) => viteLogs.push(chunk.toString()));
vite.stderr.on("data", (chunk) => viteLogs.push(chunk.toString()));

let browser;
try {
  await waitForUrl(WEB_URL);
  browser = await chromium.launch({
    headless: true,
    channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.route(`${WEB_URL}/api/**`, (route) => route.abort());
  await page.goto(`${WEB_URL}/worlds/planet`, { waitUntil: "domcontentloaded" });
  const providerDialog = page.getByRole("dialog", { name: "连接真实大模型" });
  if (await providerDialog.isVisible()) {
    await page.getByLabel("模型 Provider").selectOption("deterministic");
    await page.getByRole("button", { name: "使用本地 Provider" }).click();
  }
  await page.locator(".overlay-announcer").waitFor({ state: "attached" });
  const projectionContract = await page.evaluate(async () => {
    const projection = await fetch("/world-data.json", { cache: "no-store" }).then((response) => response.json());
    const activeThoughts = projection.thoughts.filter((item) => item.origin === "active_node");
    const rippleThoughts = projection.thoughts.filter((item) => item.origin === "ripple_response");
    const activeNodesByGraph = new Map();
    for (const item of activeThoughts) {
      const graph = item.node_id.split(":", 1)[0];
      const nodes = activeNodesByGraph.get(graph) || new Set();
      nodes.add(item.node_id);
      activeNodesByGraph.set(graph, nodes);
    }
    return {
      thoughtCount: projection.thoughts.length,
      actionVisualCount: projection.action_visuals.length,
      currentActionCount: (projection.current_actions || []).length,
      activeThoughtCount: activeThoughts.length,
      activeNodeCount: new Set(activeThoughts.map((item) => item.node_id)).size,
      relationshipGraphCount: activeNodesByGraph.size,
      activeNodeCountsByGraph: Array.from(activeNodesByGraph.values(), (nodes) => nodes.size),
      rippleThoughtCount: rippleThoughts.length,
      lastRippleEnd: Math.max(...rippleThoughts.map((item) => item.delay + item.ttl)),
      hasRippleProvenance: rippleThoughts.every((item) => Boolean(item.ripple_from)),
    };
  });
  if (projectionContract.thoughtCount > 0) {
    assert.equal(
      projectionContract.activeNodeCountsByGraph.every((count) => count === 10),
      true,
    );
    assert.equal(
      projectionContract.activeNodeCount,
      projectionContract.relationshipGraphCount * 10,
    );
    assert.equal(projectionContract.activeThoughtCount, projectionContract.activeNodeCount * 6);
    assert.ok(projectionContract.rippleThoughtCount > 0);
    assert.ok(projectionContract.lastRippleEnd <= 13.2);
    assert.equal(projectionContract.hasRippleProvenance, true);
  }
  assert.ok(projectionContract.currentActionCount > 0);
  await page.evaluate(() => {
    const layer = document.querySelector(".overlay-announcer");
    if (!layer) throw new Error("overlay announcer missing");
    const sample = () => {
      const thought = Number(layer.dataset.activeThoughts || 0);
      const action = Number(layer.dataset.activeActions || 0);
      const stats = window.__visibleIntelligenceStats;
      stats.maxThought = Math.max(stats.maxThought, thought);
      stats.maxAction = Math.max(stats.maxAction, action);
      stats.maxTotal = Math.max(stats.maxTotal, thought + action);
      if (thought > 0) stats.sawThought = true;
    };
    window.__visibleIntelligenceStats = {
      maxThought: 0,
      maxAction: 0,
      maxTotal: 0,
      sawThought: false,
      thoughtAdds: Number(layer.dataset.thoughtEmissions || 0),
      actionAdds: Number(layer.dataset.actionEmissions || 0),
    };
    new MutationObserver(() => {
      window.__visibleIntelligenceStats.thoughtAdds = Number(layer.dataset.thoughtEmissions || 0);
      window.__visibleIntelligenceStats.actionAdds = Number(layer.dataset.actionEmissions || 0);
      sample();
    }).observe(layer, { attributes: true });
    sample();
  });

  try {
    await page.waitForFunction(
      ({ thoughtCount, currentActionCount }) => {
        const layer = document.querySelector(".overlay-announcer");
        return Number(layer?.dataset.thoughtEmissions || 0) >= thoughtCount
          && Number(layer?.dataset.actionEmissions || 0) >= currentActionCount * 2;
      },
      {
        thoughtCount: projectionContract.thoughtCount,
        currentActionCount: projectionContract.currentActionCount,
      },
      { timeout: 65_000 },
    );
  } catch (error) {
    const diagnostics = await page.locator(".overlay-announcer").evaluate((layer) => ({
      thoughtEmissions: Number(layer.dataset.thoughtEmissions || 0),
      actionEmissions: Number(layer.dataset.actionEmissions || 0),
      activeThoughts: Number(layer.dataset.activeThoughts || 0),
      activeActions: Number(layer.dataset.activeActions || 0),
    }));
    console.error(JSON.stringify({ projectionContract, diagnostics }, null, 2));
    throw error;
  }
  const stats = await page.evaluate(() => window.__visibleIntelligenceStats);
  if (projectionContract.thoughtCount > 0) {
    assert.equal(stats.sawThought, true);
    assert.ok(stats.thoughtAdds >= projectionContract.thoughtCount, `only ${stats.thoughtAdds} thought occurrences played`);
  }
  assert.ok(
    stats.actionAdds >= projectionContract.currentActionCount * 2,
    `only ${stats.actionAdds} repeated current-action pulses played`,
  );
  assert.ok(
    stats.maxAction <= projectionContract.currentActionCount,
    `${stats.maxAction} active captions exceeded ${projectionContract.currentActionCount} current actors`,
  );
  const overlayPeakBound = Math.max(
    projectionContract.currentActionCount,
    projectionContract.relationshipGraphCount * 32,
  );
  assert.ok(stats.maxTotal <= overlayPeakBound, `overlay peak ${stats.maxTotal} exceeded ${overlayPeakBound}`);
  if (projectionContract.thoughtCount > 0) {
    assert.equal(await page.locator(".overlay-announcer").getAttribute("data-saw-readable-thought"), "yes");
  }
  assert.deepEqual(pageErrors, []);
  console.log(JSON.stringify({ status: "passed", projectionContract, ...stats }, null, 2));
} catch (error) {
  process.stderr.write(`${viteLogs.join("")}\n`);
  throw error;
} finally {
  if (browser) await browser.close();
  await stopProcess(vite);
}


async function waitForUrl(url, timeoutMs = 20_000) {
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

async function stopProcess(child) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  child.kill("SIGTERM");
  await Promise.race([
    new Promise((resolvePromise) => child.once("exit", resolvePromise)),
    delay(2_000).then(() => child.kill("SIGKILL")),
  ]);
}

function delay(milliseconds) {
  return new Promise((resolvePromise) => setTimeout(resolvePromise, milliseconds));
}
