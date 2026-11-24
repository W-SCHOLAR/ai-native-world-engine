import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";


const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = join(HERE, "..");
const PORT = 5189;
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
  browser = await chromium.launch(chromiumLaunchOptions());
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await page.route(`${WEB_URL}/api/**`, (route) => route.abort());
  await page.goto(`${WEB_URL}/worlds/planet`, { waitUntil: "domcontentloaded" });
  await page.getByRole("combobox", { name: "模型 Provider" }).selectOption("deterministic");
  await page.getByRole("button", { name: "使用本地 Provider" }).click();

  const stage = page.locator('.world-stage[data-scene="globe"]');
  const canvas = page.locator(".globe-canvas");
  await stage.waitFor({ state: "visible" });
  await page.waitForFunction(() => Number(document.querySelector(".globe-canvas")?.dataset.globeZoom) === 1);
  const initialYaw = Number(await canvas.getAttribute("data-globe-yaw"));
  const initialPitch = Number(await canvas.getAttribute("data-globe-pitch"));
  const box = await canvas.boundingBox();
  assert.ok(box);

  await page.mouse.click(box.x + box.width * 0.68, box.y + box.height * 0.43);
  await assertAttribute(stage, "data-view-mode", "local-focus");
  await page.getByRole("button", { name: "返回全局视图" }).waitFor({ state: "visible" });
  await page.waitForFunction(() => Number(document.querySelector(".globe-canvas")?.dataset.globeZoom) > 2.55);
  assert.equal(await canvas.getAttribute("data-globe-focused"), "yes");
  const focusedYaw = Number(await canvas.getAttribute("data-globe-yaw"));
  const focusedZoom = Number(await canvas.getAttribute("data-globe-zoom"));
  assert.ok(Math.abs(focusedYaw - initialYaw) > 0.1);

  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.58, box.y + box.height * 0.46, { steps: 4 });
  await page.mouse.up();
  await assertAttribute(stage, "data-view-mode", "local-focus");
  assert.ok(Number(await canvas.getAttribute("data-globe-zoom")) > 2.55);

  await page.getByRole("button", { name: "返回全局视图" }).click();
  await assertAttribute(stage, "data-view-mode", "overview");
  await page.waitForFunction(() => Number(document.querySelector(".globe-canvas")?.dataset.globeZoom) < 1.01);
  assert.equal(await canvas.getAttribute("data-globe-focused"), "no");
  const restoredYaw = Number(await canvas.getAttribute("data-globe-yaw"));
  const restoredPitch = Number(await canvas.getAttribute("data-globe-pitch"));
  assert.ok(Math.abs(restoredYaw - initialYaw) < 0.03);
  assert.ok(Math.abs(restoredPitch - initialPitch) < 0.03);

  await page.mouse.click(box.x + 3, box.y + 3);
  await delay(250);
  assert.equal(await stage.getAttribute("data-view-mode"), "overview");
  assert.equal(await page.getByRole("button", { name: "返回全局视图" }).count(), 0);

  console.log(JSON.stringify({
    status: "passed",
    overviewScale: 1,
    focusScale: focusedZoom,
    recenteredYawDelta: Math.abs(focusedYaw - initialYaw),
  }, null, 2));
} catch (error) {
  process.stderr.write(`${viteLogs.join("")}\n`);
  throw error;
} finally {
  if (browser) await browser.close();
  await stopProcess(vite);
}


async function assertAttribute(locator, name, expected, timeoutMs = 10_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await locator.getAttribute(name) === expected) return;
    await delay(50);
  }
  assert.equal(await locator.getAttribute(name), expected);
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

function chromiumLaunchOptions() {
  const configured = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  const macChrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
  if (configured) return { headless: true, executablePath: configured };
  return { headless: true, executablePath: macChrome };
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
