import { clamp } from "./projectionModel";
import type { AgentNode, CausalFocus, DisplayPayload, GlobeRuntime, NormalizedWorld, ProjectedAgent } from "./viewerTypes";

export const TRIBE_SURVIVAL_VIEWER_SCENE = "tribe_survival_world";
const TRIBE_SURVIVAL_BACKGROUND_SRC = "/assets/tribe-survival-map.png";
const TRIBE_SURVIVAL_CHARACTER_SHEET_SRC = "/assets/tribe-survival-characters.png";
const TRIBE_SURVIVAL_SETTLEMENT_SRC = "/assets/tribe-survival-settlement.png";
const TRIBE_SURVIVAL_BACKGROUND_ZOOM = 1.18;
const CHARACTER_SHEET_COLUMNS = 4;
const CHARACTER_SHEET_ROWS = 3;
const TRIBE_PRESENTATION_SCALE = 1.5;
const TRIBE_MEMBER_STANDEE_HEIGHT = 10 * TRIBE_PRESENTATION_SCALE;
const MAP_SAFE_PERCENT = {
  left: 8.5,
  right: 93.5,
  top: 8,
  bottom: 91,
};

let tribeSurvivalBackgroundImage: HTMLImageElement | null = null;
let tribeSurvivalCharacterSheetImage: HTMLImageElement | null = null;
let tribeSurvivalSettlementImage: HTMLImageElement | null = null;

export function isTribeSurvivalScene(summary: Record<string, unknown> | undefined): boolean {
  return summary?.viewer_scene === TRIBE_SURVIVAL_VIEWER_SCENE;
}

export function drawTribeSurvivalWorld(
  context: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  runtime: GlobeRuntime,
  world: NormalizedWorld,
  selectedId: string,
  causalFocus: CausalFocus | null,
  highlightedNetworkNodeIds: Set<string>,
  now: number,
) {
  const rect = canvas.getBoundingClientRect();
  const width = rect.width;
  const height = rect.height;
  const time = (now - runtime.startedAt) / 1000;
  const delta = Math.min(now - runtime.lastFrame, 48);
  runtime.lastFrame = now;

  if (!runtime.dragging && !runtime.focused) {
    runtime.yaw += runtime.velocityYaw * delta;
    runtime.pitch = clamp(runtime.pitch + runtime.velocityPitch * delta, -0.72, 0.72);
    runtime.velocityYaw *= 0.92;
    runtime.velocityPitch *= 0.9;
  }

  context.clearRect(0, 0, width, height);
  drawTerrain(context, width, height, time);
  drawVillageStructures(context, width, height, time);
  drawRoutes(context, width, height, time);
  const agents = projectTribeAgents(
    world.agentNodes,
    width,
    height,
    runtime,
    time,
  );
  runtime.visibleAgents = agents;
  canvas.dataset.visibleAgents = String(agents.length);
  canvas.dataset.visiblePersonActors = String(
    agents.filter((agent) => !isOrganizationHub(agent)).length,
  );
  canvas.dataset.focusedNetwork = runtime.tribeFocusedNetworkId || "";
  drawRelationshipLines(context, world, agents, time);
  drawCausalFocus(context, causalFocus, agents, time);
  drawAgents(context, agents, selectedId, highlightedNetworkNodeIds, runtime, time);
  drawStickyActionCaptions(context, agents, world.currentActions);
  drawMapLabels(context, width, height);
}

export function focusTribeNetwork(runtime: GlobeRuntime, agent: ProjectedAgent): boolean {
  const networkId = String(agent.attributes.parent_network || (isOrganizationHub(agent) ? agent.id : ""));
  if (!networkId) return false;
  const peers = runtime.visibleAgents.filter((item) => String(item.attributes.parent_network || "") === networkId);
  const center = peers.length > 0
    ? peers.reduce((total, item) => {
      const percent = agentPercent(item);
      return { x: total.x + percent.x / peers.length, y: total.y + percent.y / peers.length };
    }, { x: 0, y: 0 })
    : agentPercent(agent);
  if (!runtime.focused) {
    runtime.tribeOverviewFocusX = runtime.tribeFocusX;
    runtime.tribeOverviewFocusY = runtime.tribeFocusY;
  }
  runtime.focused = true;
  runtime.tribeFocusedNetworkId = networkId;
  runtime.targetTribeFocusX = center.x;
  runtime.targetTribeFocusY = center.y;
  runtime.targetZoom = 2.35;
  runtime.velocityYaw = 0;
  runtime.velocityPitch = 0;
  return true;
}

export function restoreTribeOverview(runtime: GlobeRuntime) {
  runtime.focused = false;
  runtime.targetTribeFocusX = runtime.tribeOverviewFocusX ?? 50;
  runtime.targetTribeFocusY = runtime.tribeOverviewFocusY ?? 50;
  runtime.targetZoom = 1;
  runtime.tribeFocusedNetworkId = null;
  runtime.velocityYaw = 0;
  runtime.velocityPitch = 0;
}

function drawTerrain(context: CanvasRenderingContext2D, width: number, height: number, time: number) {
  const background = getTribeSurvivalBackgroundImage();
  if (background?.complete && background.naturalWidth > 0) {
    drawCoverImage(context, background, width, height);
    drawMapOverlay(context, width, height);
    return;
  }

  const gradient = context.createLinearGradient(0, 0, width, height);
  gradient.addColorStop(0, "#182218");
  gradient.addColorStop(0.46, "#263721");
  gradient.addColorStop(1, "#151b14");
  context.fillStyle = gradient;
  context.fillRect(0, 0, width, height);

  context.save();
  context.globalAlpha = 0.28;
  for (let index = 0; index < 34; index += 1) {
    const x = ((index * 37) % 100) / 100 * width;
    const y = ((index * 61) % 100) / 100 * height;
    context.fillStyle = index % 3 === 0 ? "#425836" : "#31452d";
    context.beginPath();
    context.ellipse(x, y, 42 + (index % 5) * 18, 16 + (index % 4) * 9, index * 0.31, 0, Math.PI * 2);
    context.fill();
  }
  context.restore();

  drawRiver(context, width, height, time);
  drawForest(context, width, height);
  drawHills(context, width, height);
}

function getTribeSurvivalBackgroundImage(): HTMLImageElement | null {
  if (typeof Image === "undefined") return null;
  if (!tribeSurvivalBackgroundImage) {
    tribeSurvivalBackgroundImage = new Image();
    tribeSurvivalBackgroundImage.decoding = "async";
    tribeSurvivalBackgroundImage.src = TRIBE_SURVIVAL_BACKGROUND_SRC;
  }
  return tribeSurvivalBackgroundImage;
}

function getTribeSurvivalCharacterSheetImage(): HTMLImageElement | null {
  if (typeof Image === "undefined") return null;
  if (!tribeSurvivalCharacterSheetImage) {
    tribeSurvivalCharacterSheetImage = new Image();
    tribeSurvivalCharacterSheetImage.decoding = "async";
    tribeSurvivalCharacterSheetImage.src = TRIBE_SURVIVAL_CHARACTER_SHEET_SRC;
  }
  return tribeSurvivalCharacterSheetImage;
}

function getTribeSurvivalSettlementImage(): HTMLImageElement | null {
  if (typeof Image === "undefined") return null;
  if (!tribeSurvivalSettlementImage) {
    tribeSurvivalSettlementImage = new Image();
    tribeSurvivalSettlementImage.decoding = "async";
    tribeSurvivalSettlementImage.src = TRIBE_SURVIVAL_SETTLEMENT_SRC;
  }
  return tribeSurvivalSettlementImage;
}

function drawCoverImage(context: CanvasRenderingContext2D, image: HTMLImageElement, width: number, height: number) {
  const scale = Math.max(width / image.naturalWidth, height / image.naturalHeight) * TRIBE_SURVIVAL_BACKGROUND_ZOOM;
  const drawWidth = image.naturalWidth * scale;
  const drawHeight = image.naturalHeight * scale;
  context.drawImage(image, (width - drawWidth) / 2, (height - drawHeight) / 2, drawWidth, drawHeight);
}

function drawMapOverlay(context: CanvasRenderingContext2D, width: number, height: number) {
  const gradient = context.createLinearGradient(0, 0, width, height);
  gradient.addColorStop(0, "rgba(8, 15, 11, 0.48)");
  gradient.addColorStop(0.44, "rgba(9, 18, 12, 0.18)");
  gradient.addColorStop(1, "rgba(6, 10, 9, 0.5)");
  context.fillStyle = gradient;
  context.fillRect(0, 0, width, height);
}

function drawRiver(context: CanvasRenderingContext2D, width: number, height: number, time: number) {
  const p = (x: number, y: number) => ({ x: (x / 100) * width, y: (y / 100) * height });
  const points = [p(5, 71), p(19, 65), p(34, 61), p(48, 55), p(63, 46), p(78, 42), p(96, 36)];
  context.save();
  context.lineCap = "round";
  context.lineJoin = "round";
  context.strokeStyle = "rgba(71, 149, 160, 0.34)";
  context.lineWidth = Math.max(width, height) * 0.028;
  context.beginPath();
  context.moveTo(points[0].x, points[0].y);
  for (let index = 1; index < points.length - 1; index += 1) {
    const current = points[index];
    const next = points[index + 1];
    context.quadraticCurveTo(current.x, current.y, (current.x + next.x) / 2, (current.y + next.y) / 2);
  }
  context.stroke();
  context.strokeStyle = "rgba(126, 223, 225, 0.42)";
  context.lineWidth = 2;
  context.setLineDash([10, 9]);
  context.lineDashOffset = -time * 8;
  context.stroke();
  context.setLineDash([]);
  context.fillStyle = "rgba(195, 238, 226, 0.72)";
  context.font = "800 13px Inter, system-ui, sans-serif";
  context.fillText("河谷侦察线", p(56, 50).x, p(56, 50).y);
  context.restore();
}

function drawForest(context: CanvasRenderingContext2D, width: number, height: number) {
  context.save();
  const clusters = [
    [17, 36, 18],
    [24, 78, 14],
    [84, 74, 16],
    [73, 23, 12],
  ];
  for (const [cx, cy, count] of clusters) {
    for (let index = 0; index < count; index += 1) {
      const angle = (index / count) * Math.PI * 2;
      const radius = 12 + (index % 4) * 9;
      const x = (cx / 100) * width + Math.cos(angle) * radius;
      const y = (cy / 100) * height + Math.sin(angle) * radius * 0.72;
      context.fillStyle = index % 2 === 0 ? "rgba(65, 116, 58, 0.62)" : "rgba(43, 89, 48, 0.68)";
      context.beginPath();
      context.moveTo(x, y - 11);
      context.lineTo(x - 8, y + 7);
      context.lineTo(x + 8, y + 7);
      context.closePath();
      context.fill();
    }
  }
  context.restore();
}

function drawHills(context: CanvasRenderingContext2D, width: number, height: number) {
  context.save();
  context.fillStyle = "rgba(93, 84, 64, 0.28)";
  for (const [x, y, w, h] of [
    [75, 27, 150, 58],
    [79, 65, 120, 46],
    [29, 28, 110, 42],
  ]) {
    context.beginPath();
    context.ellipse((x / 100) * width, (y / 100) * height, w, h, -0.18, 0, Math.PI * 2);
    context.fill();
  }
  context.restore();
}

function drawVillageStructures(context: CanvasRenderingContext2D, width: number, height: number, time: number) {
  const p = (x: number, y: number) => ({ x: (x / 100) * width, y: (y / 100) * height });
  const center = p(50, 52);
  const settlement = getTribeSurvivalSettlementImage();

  if (settlement?.complete && settlement.naturalWidth > 0) {
    const size = Math.min(width * 0.52, height * 0.7);
    context.save();
    context.shadowBlur = 24;
    context.shadowColor = "rgba(20, 13, 7, 0.42)";
    context.globalAlpha = 0.9;
    context.drawImage(settlement, center.x - size / 2, center.y - size / 2, size, size);
    context.restore();
    return;
  }

  context.save();

  drawPalisade(context, center.x, center.y, width * 0.18, height * 0.18, time);
  drawGate(context, p(50, 36), "北门");
  drawBuilding(context, p(47, 61), 70, 42, "#8b6a36", "粮仓");
  drawBuilding(context, p(50, 55), 66, 38, "#786247", "工匠营");
  drawBuilding(context, p(58, 48), 58, 38, "#72577d", "祭司火");
  drawBuilding(context, p(39, 56), 70, 36, "#5d6f38", "猎队");
  drawBuilding(context, p(42, 39), 62, 34, "#53646a", "斥候营");
  drawWatchTower(context, p(45, 41), time);
  drawWatchTower(context, p(57, 41), time + 0.6);

  context.restore();
}

function drawPalisade(context: CanvasRenderingContext2D, x: number, y: number, radiusX: number, radiusY: number, time: number) {
  context.save();
  context.strokeStyle = "rgba(180, 128, 70, 0.82)";
  context.lineWidth = 8;
  context.beginPath();
  context.ellipse(x, y, radiusX, radiusY, -0.08, 0, Math.PI * 2);
  context.stroke();
  context.strokeStyle = `rgba(255, 210, 128, ${0.18 + Math.sin(time * 2) * 0.04})`;
  context.lineWidth = 2;
  context.setLineDash([12, 9]);
  context.stroke();
  context.setLineDash([]);
  context.fillStyle = "rgba(34, 21, 13, 0.36)";
  context.beginPath();
  context.ellipse(x, y, radiusX * 0.92, radiusY * 0.88, -0.08, 0, Math.PI * 2);
  context.fill();
  context.restore();
}

function drawGate(context: CanvasRenderingContext2D, point: { x: number; y: number }, label: string) {
  context.save();
  context.fillStyle = "#ad7840";
  roundedRect(context, point.x - 26, point.y - 13, 52, 26, 4);
  context.fill();
  context.strokeStyle = "rgba(255, 231, 172, 0.5)";
  context.lineWidth = 2;
  context.stroke();
  context.fillStyle = "#f6e4b1";
  context.font = "900 13px Inter, system-ui, sans-serif";
  context.fillText(label, point.x - 14, point.y + 5);
  context.restore();
}

function drawBuilding(context: CanvasRenderingContext2D, point: { x: number; y: number }, width: number, height: number, color: string, label: string) {
  context.save();
  context.fillStyle = "rgba(22, 14, 10, 0.46)";
  roundedRect(context, point.x - width / 2 + 5, point.y - height / 2 + 7, width, height, 7);
  context.fill();
  context.fillStyle = color;
  roundedRect(context, point.x - width / 2, point.y - height / 2, width, height, 7);
  context.fill();
  context.strokeStyle = "rgba(255, 238, 184, 0.34)";
  context.lineWidth = 1.4;
  context.stroke();
  context.fillStyle = "#fff0bd";
  context.font = "800 12px Inter, system-ui, sans-serif";
  context.textAlign = "center";
  context.fillText(label, point.x, point.y + 4);
  context.restore();
}

function drawWatchTower(context: CanvasRenderingContext2D, point: { x: number; y: number }, time: number) {
  context.save();
  context.strokeStyle = "rgba(222, 170, 90, 0.8)";
  context.lineWidth = 3;
  context.beginPath();
  context.moveTo(point.x - 13, point.y + 20);
  context.lineTo(point.x - 7, point.y - 10);
  context.lineTo(point.x + 7, point.y - 10);
  context.lineTo(point.x + 13, point.y + 20);
  context.stroke();
  context.fillStyle = "rgba(255, 190, 91, 0.88)";
  context.beginPath();
  context.arc(point.x, point.y - 14, 5 + Math.sin(time * 3) * 1.2, 0, Math.PI * 2);
  context.fill();
  context.restore();
}

function drawRoutes(context: CanvasRenderingContext2D, width: number, height: number, time: number) {
  const p = (x: number, y: number) => ({ x: (x / 100) * width, y: (y / 100) * height });
  drawRoute(context, p(72, 30), p(50, 36), "黑山侦察", "220, 92, 64", time, true);
  drawRoute(context, p(78, 62), p(50, 36), "狼牙夜袭压力", "236, 72, 72", time + 0.4, true);
  drawRoute(context, p(25, 68), p(60, 58), "盐路交易", "255, 204, 102", time + 0.8, false);
  drawRoute(context, p(42, 39), p(72, 30), "斥候回路", "123, 226, 207", time + 1.2, false);
}

function drawRoute(
  context: CanvasRenderingContext2D,
  from: { x: number; y: number },
  to: { x: number; y: number },
  label: string,
  color: string,
  time: number,
  hostile: boolean,
) {
  context.save();
  context.strokeStyle = `rgba(${color}, ${hostile ? 0.58 : 0.46})`;
  context.fillStyle = `rgba(${color}, 0.82)`;
  context.lineWidth = hostile ? 2.4 : 1.8;
  context.setLineDash(hostile ? [8, 7] : [4, 7]);
  context.lineDashOffset = -time * 10;
  const controlX = (from.x + to.x) / 2;
  const controlY = Math.min(from.y, to.y) - 36;
  context.beginPath();
  context.moveTo(from.x, from.y);
  context.quadraticCurveTo(controlX, controlY, to.x, to.y);
  context.stroke();
  context.setLineDash([]);
  context.font = "800 12px Inter, system-ui, sans-serif";
  context.fillText(label, controlX + 8, controlY - 5);
  context.restore();
}

function projectTribeAgents(
  nodes: AgentNode[],
  width: number,
  height: number,
  runtime: GlobeRuntime,
  time: number,
): ProjectedAgent[] {
  updateTribeCamera(runtime);
  const panX = runtime.yaw * 18;
  const panY = runtime.pitch * 22;
  const projected = nodes.filter((node) => (
    shouldRenderTribeActor(node, runtime)
  )).map((node) => {
    const percent = agentPercent(node);
    const faction = String(node.attributes.faction || "");
    const isExternal = faction === "autonomous_enemy" || faction === "neutral_external";
    const drift = node.kind === "key" ? 2.5 : isExternal ? 1.8 : 1.2;
    const mapX = 50 + (percent.x - runtime.tribeFocusX) * runtime.zoom;
    const mapY = 50 + (percent.y - runtime.tribeFocusY) * runtime.zoom;
    const overviewSafeX = MAP_SAFE_PERCENT.left + (percent.x / 100) * (MAP_SAFE_PERCENT.right - MAP_SAFE_PERCENT.left);
    const overviewSafeY = MAP_SAFE_PERCENT.top + (percent.y / 100) * (MAP_SAFE_PERCENT.bottom - MAP_SAFE_PERCENT.top);
    const safeX = runtime.focused
      ? MAP_SAFE_PERCENT.left + (mapX / 100) * (MAP_SAFE_PERCENT.right - MAP_SAFE_PERCENT.left)
      : overviewSafeX;
    const safeY = runtime.focused
      ? MAP_SAFE_PERCENT.top + (mapY / 100) * (MAP_SAFE_PERCENT.bottom - MAP_SAFE_PERCENT.top)
      : overviewSafeY;
    const minX = (MAP_SAFE_PERCENT.left / 100) * width + 18;
    const maxX = (MAP_SAFE_PERCENT.right / 100) * width - 18;
    const minY = (MAP_SAFE_PERCENT.top / 100) * height + 18;
    const maxY = (MAP_SAFE_PERCENT.bottom / 100) * height - 18;
    const screenX = clamp((safeX / 100) * width + panX + Math.sin(time * 1.7 + node.phase) * drift, minX, maxX);
    const screenY = clamp((safeY / 100) * height + panY + Math.cos(time * 1.4 + node.phase) * drift, minY, maxY);
    return { ...node, screenX, screenY, depth: 1 };
  });
  return separateTribeStandees(projected, runtime.focused).map((agent) => ({
    ...agent,
    thoughtAnchorY: tribeThoughtAnchorY(agent),
  }));
}

function shouldRenderTribeActor(
  node: AgentNode,
  runtime: GlobeRuntime,
) {
  const parentNetwork = String(node.attributes.parent_network || "");
  if (!parentNetwork) {
    if (isOrganizationHub(node)) {
      return !runtime.focused || node.id === runtime.tribeFocusedNetworkId;
    }
    // Grounded-action targets such as gates and resource stores may be added
    // to the generic projection. They are not Tribe people and must not be
    // counted or drawn as standees.
    return !runtime.focused && node.attributes.viewer_behavior_actor === true;
  }
  // Person nodes are world entities in their own right. Their visibility must
  // never depend on whether a current-action delta has arrived yet; otherwise
  // most of the Tribe population disappears during startup or action changes.
  return !runtime.focused || parentNetwork === runtime.tribeFocusedNetworkId;
}

function updateTribeCamera(runtime: GlobeRuntime) {
  const blend = 0.1;
  if (runtime.targetZoom !== null) {
    runtime.zoom += (runtime.targetZoom - runtime.zoom) * blend;
    if (Math.abs(runtime.targetZoom - runtime.zoom) < 0.002) {
      runtime.zoom = runtime.targetZoom;
      runtime.targetZoom = null;
    }
  }
  if (runtime.targetTribeFocusX !== null) {
    runtime.tribeFocusX += (runtime.targetTribeFocusX - runtime.tribeFocusX) * blend;
    if (Math.abs(runtime.targetTribeFocusX - runtime.tribeFocusX) < 0.01) {
      runtime.tribeFocusX = runtime.targetTribeFocusX;
      runtime.targetTribeFocusX = null;
    }
  }
  if (runtime.targetTribeFocusY !== null) {
    runtime.tribeFocusY += (runtime.targetTribeFocusY - runtime.tribeFocusY) * blend;
    if (Math.abs(runtime.targetTribeFocusY - runtime.tribeFocusY) < 0.01) {
      runtime.tribeFocusY = runtime.targetTribeFocusY;
      runtime.targetTribeFocusY = null;
    }
  }
}

function separateTribeStandees(agents: ProjectedAgent[], focused: boolean) {
  const offsets = new Map<string, { x: number; y: number }>();
  for (const agent of agents) offsets.set(agent.id, { x: agent.screenX, y: agent.screenY });
  // Presentation-only relaxation: source world positions remain intact.
  for (let pass = 0; pass < 2; pass += 1) {
    for (let leftIndex = 0; leftIndex < agents.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < agents.length; rightIndex += 1) {
        const left = agents[leftIndex];
        const right = agents[rightIndex];
        const sameNetwork = left.attributes.parent_network === right.attributes.parent_network;
        const minimumDistance = sameNetwork ? (focused ? 8.25 : 4.5) : 3.6;
        const leftPoint = offsets.get(left.id)!;
        const rightPoint = offsets.get(right.id)!;
        const dx = rightPoint.x - leftPoint.x;
        const dy = rightPoint.y - leftPoint.y;
        const distance = Math.hypot(dx, dy) || 0.01;
        if (distance >= minimumDistance) continue;
        const push = (minimumDistance - distance) * (sameNetwork ? 0.26 : 0.14);
        const directionX = distance > 0.02 ? dx / distance : Math.cos(left.phase);
        const directionY = distance > 0.02 ? dy / distance : Math.sin(left.phase);
        leftPoint.x -= directionX * push;
        leftPoint.y -= directionY * push;
        rightPoint.x += directionX * push;
        rightPoint.y += directionY * push;
      }
    }
  }
  return agents.map((agent) => ({ ...agent, screenX: offsets.get(agent.id)!.x, screenY: offsets.get(agent.id)!.y }));
}

function agentPercent(node: AgentNode) {
  const x = ((node.theta + Math.PI) / (Math.PI * 2)) * 100;
  const y = (0.5 - node.phi / (Math.PI * 0.86)) * 100;
  return {
    x: clamp(x, 4, 96),
    y: clamp(y, 4, 96),
  };
}

function drawRelationshipLines(context: CanvasRenderingContext2D, world: NormalizedWorld, agents: ProjectedAgent[], time: number) {
  const byId = new Map(agents.map((agent) => [agent.id, agent]));
  context.save();
  context.lineCap = "round";
  for (const link of world.networkLinks.slice(0, 140)) {
    const from = byId.get(link.source);
    const to = byId.get(link.target);
    if (!from || !to) continue;
    const hostile = link.type.includes("raid") || link.type.includes("tension");
    const weight = clamp(Number(link.weight || 0.4), 0.12, 1);
    context.strokeStyle = hostile
      ? `rgba(255, 99, 86, ${0.16 + weight * 0.36})`
      : `rgba(141, 236, 199, ${0.08 + weight * 0.22})`;
    context.lineWidth = hostile ? 1.4 + weight : 0.7 + weight * 0.7;
    context.setLineDash(hostile ? [5, 5] : link.type === "member_of" ? [] : [3, 7]);
    context.lineDashOffset = -time * 5;
    context.beginPath();
    context.moveTo(from.screenX, from.screenY);
    context.quadraticCurveTo(
      (from.screenX + to.screenX) / 2,
      (from.screenY + to.screenY) / 2 - (hostile ? 24 : 8),
      to.screenX,
      to.screenY,
    );
    context.stroke();
  }
  context.setLineDash([]);
  context.restore();
}

function drawCausalFocus(context: CanvasRenderingContext2D, focus: CausalFocus | null, agents: ProjectedAgent[], time: number) {
  if (!focus?.actorId) return;
  const byId = new Map(agents.map((agent) => [agent.id, agent]));
  const actor = byId.get(focus.actorId);
  if (!actor) return;
  context.save();
  context.strokeStyle = `rgba(255, 218, 112, ${0.52 + Math.sin(time * 3) * 0.08})`;
  context.lineWidth = 2.2;
  for (const targetId of [...focus.targetIds, ...focus.effectNodeIds].slice(0, 8)) {
    const target = byId.get(targetId);
    if (!target || target.id === actor.id) continue;
    context.beginPath();
    context.moveTo(actor.screenX, actor.screenY);
    context.quadraticCurveTo(
      (actor.screenX + target.screenX) / 2,
      Math.min(actor.screenY, target.screenY) - 32,
      target.screenX,
      target.screenY,
    );
    context.stroke();
  }
  context.restore();
}

function drawAgents(
  context: CanvasRenderingContext2D,
  agents: ProjectedAgent[],
  selectedId: string,
  highlightedNetworkNodeIds: Set<string>,
  runtime: GlobeRuntime,
  time: number,
) {
  const sorted = [...agents].sort((left, right) => agentLayer(left) - agentLayer(right));
  const characterSheet = getTribeSurvivalCharacterSheetImage();
  for (const agent of sorted) {
    const faction = String(agent.attributes.faction || "");
    const external = faction === "autonomous_enemy";
    const neutral = faction === "neutral_external";
    const selected = agent.id === selectedId;
    const selectedNetworkPeer = highlightedNetworkNodeIds.has(agent.id) && !selected;
    const pulse = 0.84 + Math.sin(time * 2.4 + agent.phase) * 0.16;
    const size = (agent.kind === "key" ? 13.5 : agent.kind === "network" ? 9.75 : 6.3) * pulse + (selected ? 7.5 : selectedNetworkPeer ? 4.5 : 0);
    agent.actionAnchorY = agent.screenY + size + 4;
    if (isOrganizationHub(agent)) {
      drawOrganizationHubMarker(context, agent, selected, pulse);
      drawAgentLabel(context, agent, 32);
      continue;
    }
    const spriteIndex = spriteIndexForAgent(agent);
    context.save();
    context.shadowBlur = selected ? 24 : agent.kind === "key" ? 18 : external ? 15 : 10;
    context.shadowColor = external ? "rgba(255, 88, 74, 0.6)" : neutral ? "rgba(255, 210, 114, 0.52)" : "rgba(132, 246, 196, 0.55)";
    if (spriteIndex !== null && characterSheet?.complete && characterSheet.naturalWidth > 0) {
      drawCharacterSprite(context, characterSheet, spriteIndex, agent, selected, selectedNetworkPeer, external, neutral, pulse);
      drawCognitionHalo(context, agent, pulse);
      if (agent.kind === "key" || isOrganizationHub(agent) || (runtime.focused && isTribeMember(agent))) {
        drawAgentLabel(context, agent, spriteLabelOffset(agent));
      }
      context.restore();
      continue;
    }
    context.fillStyle = external
      ? "rgba(248, 98, 80, 0.92)"
      : neutral
        ? "rgba(244, 191, 95, 0.92)"
        : agent.kind === "key"
          ? "rgba(255, 230, 128, 0.96)"
          : "rgba(126, 241, 196, 0.88)";
    context.beginPath();
    context.arc(agent.screenX, agent.screenY, size, 0, Math.PI * 2);
    context.fill();
    if (agent.kind === "network") {
      context.strokeStyle = "rgba(8, 16, 13, 0.55)";
      context.lineWidth = 1.6;
      context.stroke();
    }
    if (selected || selectedNetworkPeer || agent.kind === "key") {
      context.shadowBlur = 0;
      context.strokeStyle = selected ? "#fff0b9" : external ? "#ffb29c" : "#c8ffe8";
      context.lineWidth = selected ? 2.4 : 1.5;
      context.beginPath();
      context.arc(agent.screenX, agent.screenY, size + (selected ? 8 : 5), 0, Math.PI * 2);
      context.stroke();
    }
    drawCognitionHalo(context, agent, pulse);
    if (agent.kind === "key" || isOrganizationHub(agent) || (runtime.focused && isTribeMember(agent))) {
      drawAgentLabel(context, agent);
    }
    context.restore();
  }
}

function drawOrganizationHubMarker(
  context: CanvasRenderingContext2D,
  agent: ProjectedAgent,
  selected: boolean,
  pulse: number,
) {
  const radius = 10 + pulse * 2 + (selected ? 4 : 0);
  context.save();
  context.translate(agent.screenX, agent.screenY);
  context.rotate(Math.PI / 4);
  context.fillStyle = selected ? "rgba(255, 225, 139, 0.94)" : "rgba(58, 88, 63, 0.94)";
  context.strokeStyle = selected ? "#fff0b9" : "rgba(183, 238, 180, 0.82)";
  context.lineWidth = selected ? 2.8 : 1.8;
  context.fillRect(-radius, -radius, radius * 2, radius * 2);
  context.strokeRect(-radius, -radius, radius * 2, radius * 2);
  context.rotate(-Math.PI / 4);
  context.fillStyle = selected ? "#3a2b16" : "#e5f3d7";
  context.font = "900 11px Inter, system-ui, sans-serif";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText("组织", 0, 0);
  context.restore();
}

function drawCharacterSprite(
  context: CanvasRenderingContext2D,
  image: HTMLImageElement,
  spriteIndex: number,
  agent: ProjectedAgent,
  selected: boolean,
  selectedNetworkPeer: boolean,
  external: boolean,
  neutral: boolean,
  pulse: number,
) {
  const sourceWidth = image.naturalWidth / CHARACTER_SHEET_COLUMNS;
  const sourceHeight = image.naturalHeight / CHARACTER_SHEET_ROWS;
  const sourceX = (spriteIndex % CHARACTER_SHEET_COLUMNS) * sourceWidth;
  const sourceY = Math.floor(spriteIndex / CHARACTER_SHEET_COLUMNS) * sourceHeight;
  const baseHeight = tribeStandeeBaseHeight(agent);
  const cognitionScale = agent.cognitionState === "active" ? 1.18 : agent.cognitionState === "ripple" ? 1.08 : 1;
  const height = baseHeight * cognitionScale * (0.94 + (pulse - 0.84) * 0.22) + (selected ? 21 : selectedNetworkPeer ? 12 : 0);
  const width = height * (sourceWidth / sourceHeight);
  const footY = agent.screenY + height * 0.28;
  agent.actionAnchorY = footY + 4;
  const drawX = agent.screenX - width / 2;
  const drawY = footY - height;
  const haloColor = external
    ? "rgba(255, 93, 72, 0.68)"
    : neutral
      ? "rgba(244, 196, 91, 0.62)"
      : agent.kind === "key"
        ? "rgba(255, 226, 128, 0.68)"
        : "rgba(129, 246, 198, 0.58)";
  context.save();
  context.shadowBlur = 0;
  context.fillStyle = selected ? "rgba(255, 236, 168, 0.48)" : "rgba(8, 14, 10, 0.24)";
  context.beginPath();
  context.ellipse(agent.screenX, footY - 3, width * 0.32, Math.max(2, height * 0.06), 0, 0, Math.PI * 2);
  context.fill();
  context.shadowBlur = selected ? 14 : agent.kind === "key" ? 8 : 4;
  context.shadowColor = haloColor;
  context.drawImage(
    image,
    sourceX,
    sourceY,
    sourceWidth,
    sourceHeight,
    drawX,
    drawY,
    width,
    height,
  );
  context.restore();
}

function tribeThoughtAnchorY(agent: ProjectedAgent) {
  const baseHeight = tribeStandeeBaseHeight(agent);
  const cognitionScale = agent.cognitionState === "active" ? 1.18 : agent.cognitionState === "ripple" ? 1.08 : 1;
  // Standees are drawn from `footY - height`; place the bubble just above that
  // visible head, instead of at the person node's body-center coordinate.
  return agent.screenY - baseHeight * cognitionScale * 0.72 - 12;
}

function standeeMetrics(agent: ProjectedAgent, pulse: number, sourceRatio: number) {
  const baseHeight = tribeStandeeBaseHeight(agent);
  const height = baseHeight * (0.94 + (pulse - 0.84) * 0.22);
  return {
    height,
    width: height * sourceRatio,
  };
}

function tribeStandeeBaseHeight(agent: ProjectedAgent) {
  return agent.kind === "key" ? 70 * TRIBE_PRESENTATION_SCALE : isOrganizationHub(agent) ? 44 * TRIBE_PRESENTATION_SCALE : TRIBE_MEMBER_STANDEE_HEIGHT;
}

function spriteIndexForAgent(agent: ProjectedAgent): number | null {
  if (agent.id === "chieftain-aya") return 0;
  if (agent.id === "captain-tor") return 1;
  if (agent.id === "scout-nara") return 2;
  if (agent.id === "shaman-ru") return 3;
  if (agent.id === "builder-kun") return 4;
  if (agent.id === "young-chief-ren") return 5;
  if (agent.id === "black-hill-tribe" || agent.id === "wolf-tooth-raiders") return 10;
  if (agent.id === "salt-road-caravan" || agent.id === "fire-diplomats") return 11;
  if (agent.id === "ember-guard") return 7;
  if (agent.id === "river-scouts") return 9;
  if (agent.id === "stone-builders") return 4;
  if (agent.id === "dawn-hunters") return 8;
  if (agent.id === "ash-shamans") return 3;
  if (agent.id === "elder-council" || agent.id === "granary-keepers") return 6;
  const faction = String(agent.attributes.faction || "");
  if (faction === "autonomous_enemy") return 10;
  if (faction === "neutral_external") return 11;
  const role = `${agent.role} ${agent.name} ${agent.parent} ${String(agent.attributes.role || "")}`.toLowerCase();
  const parentNetwork = String(agent.attributes.parent_network || "");
  if (agent.parent.includes("黑山") || agent.parent.includes("狼牙") || agent.name.includes("黑山") || agent.name.includes("狼牙")) return 10;
  if (agent.parent.includes("盐路") || agent.name.includes("盐路")) return 11;
  if (parentNetwork === "ember-guard" || role.includes("盾") || role.includes("哨") || role.includes("spear")) return 7;
  if (parentNetwork === "river-scouts" || role.includes("斥候") || role.includes("眼线") || role.includes("信使") || role.includes("足迹")) return 9;
  if (parentNetwork === "stone-builders" || role.includes("匠") || role.includes("塔工")) return 4;
  if (parentNetwork === "dawn-hunters" || role.includes("猎") || role.includes("弓")) return 8;
  if (parentNetwork === "ash-shamans" || role.includes("祭司") || role.includes("医者") || role.includes("梦兆")) return 3;
  if (parentNetwork === "fire-diplomats" || role.includes("使者") || role.includes("译者") || role.includes("贡礼")) return 11;
  return 6;
}

function isOrganizationHub(agent: AgentNode) {
  return agent.kind === "network" && Boolean(agent.parent) && agent.name === agent.parent;
}

function isTribeMember(agent: ProjectedAgent) {
  return Boolean(agent.attributes.parent_network);
}

function drawStickyActionCaptions(
  context: CanvasRenderingContext2D,
  agents: ProjectedAgent[],
  currentActions: DisplayPayload[],
) {
  const byId = new Map(agents.map((agent) => [agent.id, agent]));
  const latestTextByNode = new Map<string, string>();
  for (const payload of currentActions) {
    const text = payload.text.trim();
    if (!payload.node_id || !text) continue;
    latestTextByNode.set(payload.node_id, text);
  }
  context.save();
  context.font = "900 4px Inter, system-ui, sans-serif";
  context.fillStyle = "#000";
  context.textAlign = "center";
  context.textBaseline = "top";
  context.globalAlpha = 1;
  for (const [nodeId, text] of latestTextByNode) {
    const agent = byId.get(nodeId);
    if (!agent || isOrganizationHub(agent)) continue;
    context.fillText(text, agent.screenX, agent.actionAnchorY ?? agent.screenY);
  }
  context.restore();
}

function drawCognitionHalo(context: CanvasRenderingContext2D, agent: ProjectedAgent, pulse: number) {
  if (!isTribeMember(agent)) return;
  const state = agent.cognitionState;
  if (state !== "active" && state !== "ripple") return;
  const radius = state === "active" ? 9 + pulse * 2.25 : 6 + pulse * 1.5;
  context.save();
  context.strokeStyle = state === "active"
    ? `rgba(255, 234, 148, ${0.58 + pulse * 0.2})`
    : `rgba(130, 231, 255, ${0.32 + pulse * 0.16})`;
  context.lineWidth = state === "active" ? 2.2 : 1.2;
  context.setLineDash(state === "ripple" ? [3, 4] : []);
  context.beginPath();
  context.arc(agent.screenX, agent.screenY, radius, 0, Math.PI * 2);
  context.stroke();
  context.restore();
}

function spriteLabelOffset(agent: ProjectedAgent) {
  if (agent.kind === "key") return 53;
  if (isOrganizationHub(agent)) return 42;
  return 27;
}

function drawAgentLabel(context: CanvasRenderingContext2D, agent: ProjectedAgent, offsetY = 12) {
  const label = isOrganizationHub(agent) ? `${agent.name} · 56 人` : agent.name;
  context.save();
  context.font = "800 11px Inter, system-ui, sans-serif";
  context.textAlign = "center";
  const width = Math.min(context.measureText(label).width + 12, 120);
  context.fillStyle = "rgba(11, 17, 14, 0.68)";
  roundedRect(context, agent.screenX - width / 2, agent.screenY + offsetY, width, 20, 5);
  context.fill();
  context.fillStyle = "rgba(245, 251, 229, 0.92)";
  context.fillText(label, agent.screenX, agent.screenY + offsetY + 14, width - 6);
  context.restore();
}

function drawMapLabels(context: CanvasRenderingContext2D, width: number, height: number) {
  context.save();
  context.font = "900 13px Inter, system-ui, sans-serif";
  context.fillStyle = "rgba(245, 250, 224, 0.82)";
  label(context, width, height, 50, 30, "北门木墙");
  label(context, width, height, 50, 72, "我方部落");
  label(context, width, height, 72, 25, "黑山部落");
  label(context, width, height, 80, 68, "狼牙掠夺队");
  label(context, width, height, 24, 74, "盐路商队");
  context.restore();
}

function label(context: CanvasRenderingContext2D, width: number, height: number, x: number, y: number, text: string) {
  const px = (x / 100) * width;
  const py = (y / 100) * height;
  const textWidth = context.measureText(text).width + 14;
  context.fillStyle = "rgba(8, 12, 10, 0.5)";
  roundedRect(context, px - textWidth / 2, py - 13, textWidth, 24, 6);
  context.fill();
  context.fillStyle = "rgba(245, 250, 224, 0.88)";
  context.fillText(text, px - textWidth / 2 + 7, py + 4);
}

function agentLayer(agent: ProjectedAgent) {
  if (agent.kind === "key") return 3;
  if (agent.attributes.faction === "autonomous_enemy" || agent.attributes.faction === "neutral_external") return 2;
  if (agent.kind === "network") return 1;
  return 0;
}

function roundedRect(context: CanvasRenderingContext2D, x: number, y: number, width: number, height: number, radius: number) {
  const r = Math.min(radius, width / 2, height / 2);
  context.beginPath();
  context.moveTo(x + r, y);
  context.lineTo(x + width - r, y);
  context.quadraticCurveTo(x + width, y, x + width, y + r);
  context.lineTo(x + width, y + height - r);
  context.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
  context.lineTo(x + r, y + height);
  context.quadraticCurveTo(x, y + height, x, y + height - r);
  context.lineTo(x, y + r);
  context.quadraticCurveTo(x, y, x + r, y);
  context.closePath();
}
