import assert from "node:assert/strict";

import { chromium } from "playwright";


const BASE_URL = process.env.AI_NATIVE_WORLD_WEB_URL || "http://127.0.0.1:5173";
const browser = await chromium.launch({ headless: true });

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const planetRunResponse = page.waitForResponse((response) => (
    response.request().method() === "POST"
    && new URL(response.url()).pathname === "/api/runs"
  ));
  await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
  const planetRun = await (await planetRunResponse).json();
  assert.equal(planetRun.scenario, "enterprise_earth");
  assert.equal(await page.locator(".engine-demo-home").count(), 0);
  assert.equal(await page.locator("a[href*='showcase'], a[href*='multiverse']").count(), 0);

  await verifyActiveWorld(page, "globe");
  const tribeRunResponse = page.waitForResponse((response) => (
    response.request().method() === "POST"
    && new URL(response.url()).pathname === "/api/runs"
  ));
  await page.getByRole("button", { name: "部落", exact: true }).click();
  await page.waitForURL(`${BASE_URL}/worlds/tribe`);
  const tribeRun = await (await tribeRunResponse).json();
  assert.equal(tribeRun.scenario, "tribe_survival");
  await verifyActiveWorld(page, "tribe-survival-map");
} finally {
  await browser.close();
}

async function verifyActiveWorld(page, stageScene) {
  const bar = page.locator(".viewer-interaction-bar");
  await bar.waitFor();
  await page.locator(".runtime-authority-badge").filter({ hasText: "PYTHON ENGINE" }).waitFor();
  await page.locator(`.world-stage[data-scene='${stageScene}']`).waitFor();

  const pause = page.getByRole("button", { name: "Pause", exact: true });
  await pause.waitFor({ state: "visible" });
  await pause.click();
  await page.getByRole("button", { name: "Resume", exact: true }).waitFor();
  await page.getByRole("button", { name: "Resume", exact: true }).click();

  await page.getByRole("button", { name: "释放信号" }).click();
  await page.locator(".interaction-receipts article").filter({ hasText: "干预" }).waitFor();
  await page.getByRole("textbox", { name: "旨意" }).fill("让世界记住这次来自用户的互动");
  await page.getByRole("button", { name: "下旨" }).click();
  await page.locator(".interaction-receipts article").filter({ hasText: "旨意" }).waitFor();

  await page.waitForFunction(() => {
    const layer = document.querySelector(".overlay-announcer");
    return Number(layer?.dataset.thoughtEmissions || 0) > 0;
  }, null, { timeout: 30_000 });
}
