import { clamp, uniqueStrings } from "./projectionModel";
import type {
  AgentNode,
  CausalFocus,
  GlobeParticle,
  GlobeRuntime,
  NormalizedWorld,
  ProjectedAgent,
} from "./viewerTypes";

export const GLOBE_OVERVIEW_SCALE = 1;
export const GLOBE_LOCAL_FOCUS_SCALE = 2.6;
const GLOBE_RADIUS_RATIO = 0.43;
const CAMERA_TRANSITION_MS = 240;
const CAMERA_EPSILON = 0.0008;

export function createGlobeRuntime(): GlobeRuntime {
  const now = typeof performance === "undefined" ? Date.now() : performance.now();
  return {
    particles: createGlobeParticles(3600), startedAt: now, yaw: 0, pitch: -0.28,
    zoom: 1, targetYaw: null, targetPitch: null, targetZoom: null, focused: false,
    overviewYaw: null, overviewPitch: null, tribeFocusX: 50, tribeFocusY: 50,
    targetTribeFocusX: null, targetTribeFocusY: null, tribeFocusedNetworkId: null,
    tribeOverviewFocusX: null, tribeOverviewFocusY: null, velocityYaw: 0.0005,
    velocityPitch: 0, dragging: false, pointerMoved: false, lastPointerX: 0,
    lastPointerY: 0, lastFrame: now, visibleAgents: [],
  };
}

export function drawGlobe(
  context: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  globe: GlobeRuntime,
  world: NormalizedWorld,
  selectedId: string,
  causalFocus: CausalFocus | null,
  highlightedNetworkNodeIds: Set<string>,
  now: number,
) {
  const rect = canvas.getBoundingClientRect();
  const width = rect.width;
  const height = rect.height;
  const center = width / 2;
  const time = (now - globe.startedAt) / 1000;
  const delta = Math.min(now - globe.lastFrame, 48);
  globe.lastFrame = now;

  updateGlobeCamera(globe, delta);
  const radius = globeRadius(width, height, globe.zoom);
  canvas.dataset.globeZoom = globe.zoom.toFixed(3);
  canvas.dataset.globeYaw = globe.yaw.toFixed(4);
  canvas.dataset.globePitch = globe.pitch.toFixed(4);
  canvas.dataset.globeFocused = globe.focused ? "yes" : "no";

  if (!globe.dragging && !globe.focused && !hasCameraTarget(globe)) {
    globe.yaw += 0.00008 * delta + globe.velocityYaw * delta;
    globe.pitch = clamp(globe.pitch + globe.velocityPitch * delta, -0.92, 0.72);
    globe.velocityYaw *= 0.965;
    globe.velocityPitch *= 0.94;
  }

  context.clearRect(0, 0, width, height);
  drawGlobeAura(context, center, height / 2, radius, time);

  const visibleParticles = projectParticles(globe, center, height / 2, radius);
  visibleParticles.sort((a, b) => a.depth - b.depth);

  for (const item of visibleParticles) {
    const pulse = 0.72 + Math.sin(time * 2.4 + item.particle.phase) * 0.28;
    const alpha = (0.08 + item.depth * 0.78) * (item.particle.dataPulse ? pulse : 1);
    const size = item.particle.size * (0.42 + item.depth * 1.25) * (item.particle.dataPulse ? 1.55 : 1);
    const color = item.particle.cityLight
      ? `rgba(255, 215, 128, ${Math.min(alpha + 0.15, 1)})`
      : item.particle.land
        ? `rgba(132, 246, 196, ${alpha})`
        : `rgba(104, 190, 255, ${alpha * 0.78})`;
    context.beginPath();
    context.fillStyle = color;
    context.arc(item.x, item.y, size, 0, Math.PI * 2);
    context.fill();
  }

  const projectedAgents = projectAgents(globe, world, center, height / 2, radius, time);
  drawImpactRipples(context, projectedAgents, world, time);
  drawInfluenceArrows(context, projectedAgents, world, radius, time);
  drawCausalFocus(context, projectedAgents, causalFocus, radius, time);
  drawAgentNodes(context, globe, projectedAgents, selectedId, highlightedNetworkNodeIds, time);
  drawGlobeRim(context, center, height / 2, radius);
}

export function focusGlobeAtScreenPoint(
  globe: GlobeRuntime,
  width: number,
  height: number,
  screenX: number,
  screenY: number,
): boolean {
  const radius = globeRadius(width, height, globe.zoom);
  if (radius <= 0) return false;
  const rotatedX = (screenX - width / 2) / radius;
  const tiltedY = (screenY - height / 2) / radius;
  const radialSquared = rotatedX * rotatedX + tiltedY * tiltedY;
  if (radialSquared > 1) return false;

  const tiltedZ = Math.sqrt(Math.max(1 - radialSquared, 0));
  const baseY = tiltedY * Math.cos(globe.pitch) + tiltedZ * Math.sin(globe.pitch);
  const rotatedZ = -tiltedY * Math.sin(globe.pitch) + tiltedZ * Math.cos(globe.pitch);
  const baseX = rotatedX * Math.cos(globe.yaw) + rotatedZ * Math.sin(globe.yaw);
  const baseZ = -rotatedX * Math.sin(globe.yaw) + rotatedZ * Math.cos(globe.yaw);

  if (!globe.focused) {
    globe.overviewYaw = globe.yaw;
    globe.overviewPitch = globe.pitch;
  }
  globe.focused = true;
  globe.targetYaw = Math.atan2(baseX, baseZ);
  globe.targetPitch = clamp(
    Math.atan2(baseY, Math.hypot(baseX, baseZ)),
    -1.35,
    1.35,
  );
  globe.targetZoom = GLOBE_LOCAL_FOCUS_SCALE;
  globe.velocityYaw = 0;
  globe.velocityPitch = 0;
  return true;
}

export function restoreGlobeOverview(globe: GlobeRuntime) {
  globe.focused = false;
  globe.targetYaw = globe.overviewYaw ?? globe.yaw;
  globe.targetPitch = globe.overviewPitch ?? globe.pitch;
  globe.targetZoom = GLOBE_OVERVIEW_SCALE;
  globe.velocityYaw = 0;
  globe.velocityPitch = 0;
}

export function resetGlobeView(globe: GlobeRuntime) {
  globe.yaw = 0;
  globe.pitch = -0.28;
  globe.zoom = GLOBE_OVERVIEW_SCALE;
  globe.targetYaw = null;
  globe.targetPitch = null;
  globe.targetZoom = null;
  globe.focused = false;
  globe.overviewYaw = null;
  globe.overviewPitch = null;
  globe.tribeFocusX = 50;
  globe.tribeFocusY = 50;
  globe.targetTribeFocusX = null;
  globe.targetTribeFocusY = null;
  globe.tribeFocusedNetworkId = null;
  globe.tribeOverviewFocusX = null;
  globe.tribeOverviewFocusY = null;
  globe.velocityYaw = 0.0005;
  globe.velocityPitch = 0;
}

export function cancelGlobeOrientationTarget(globe: GlobeRuntime) {
  globe.targetYaw = null;
  globe.targetPitch = null;
}

function globeRadius(width: number, height: number, zoom: number) {
  return Math.min(width, height) * GLOBE_RADIUS_RATIO * Math.max(zoom, GLOBE_OVERVIEW_SCALE);
}

function hasCameraTarget(globe: GlobeRuntime) {
  return globe.targetYaw !== null || globe.targetPitch !== null || globe.targetZoom !== null;
}

function updateGlobeCamera(globe: GlobeRuntime, deltaMs: number) {
  const blend = 1 - Math.exp(-Math.max(deltaMs, 0) / CAMERA_TRANSITION_MS);
  if (globe.targetYaw !== null) {
    const delta = shortestAngle(globe.targetYaw - globe.yaw);
    globe.yaw += delta * blend;
    if (Math.abs(delta) <= CAMERA_EPSILON) {
      globe.yaw = globe.targetYaw;
      globe.targetYaw = null;
    }
  }
  if (globe.targetPitch !== null) {
    const delta = globe.targetPitch - globe.pitch;
    globe.pitch += delta * blend;
    if (Math.abs(delta) <= CAMERA_EPSILON) {
      globe.pitch = globe.targetPitch;
      globe.targetPitch = null;
    }
  }
  if (globe.targetZoom !== null) {
    const delta = globe.targetZoom - globe.zoom;
    globe.zoom += delta * blend;
    if (Math.abs(delta) <= CAMERA_EPSILON) {
      globe.zoom = globe.targetZoom;
      globe.targetZoom = null;
    }
  }
}

function shortestAngle(value: number) {
  return Math.atan2(Math.sin(value), Math.cos(value));
}

export function createGlobeParticles(count: number): GlobeParticle[] {
  const particles: GlobeParticle[] = [];
  let randomState = 9173;
  const random = () => {
    randomState = (randomState * 16807) % 2147483647;
    return (randomState - 1) / 2147483646;
  };

  for (let index = 0; index < count; index += 1) {
    const z = 1 - (2 * (index + 0.5)) / count;
    const radius = Math.sqrt(Math.max(0, 1 - z * z));
    const theta = index * Math.PI * (3 - Math.sqrt(5));
    const continentNoise = Math.sin(theta * 2.7) + Math.cos(z * 8.5) + Math.sin((theta + z) * 5.2);
    const cityLight = random() > 0.965;
    const dataPulse = random() > 0.985;
    particles.push({
      x: Math.cos(theta) * radius,
      y: z,
      z: Math.sin(theta) * radius,
      size: 0.6 + random() * 1.5,
      land: continentNoise > 0.35 || cityLight,
      cityLight,
      dataPulse,
      phase: random() * Math.PI * 2,
    });
  }
  return particles;
}

export function nearestVisibleAgent(agents: ProjectedAgent[], x: number, y: number) {
  let best: { agent: ProjectedAgent; distance: number } | null = null;
  for (const agent of agents) {
    const distance = Math.hypot(agent.screenX - x, agent.screenY - y);
    if (distance > 20) continue;
    if (!best || distance < best.distance) {
      best = { agent, distance };
    }
  }
  return best?.agent ?? null;
}

export function screenPointForAgent(visibleAgents: ProjectedAgent[], node: AgentNode, canvas: HTMLCanvasElement | null) {
  const visible = visibleAgents.find((item) => item.id === node.id);
  if (visible) return { x: visible.screenX, y: visible.screenY };
  const rect = canvas?.getBoundingClientRect();
  return { x: (rect?.width ?? 320) / 2, y: (rect?.height ?? 320) / 2 };
}

export function thoughtPointForAgent(visibleAgents: ProjectedAgent[], node: AgentNode, canvas: HTMLCanvasElement | null) {
  const visible = visibleAgents.find((item) => item.id === node.id);
  if (visible) return { x: visible.screenX, y: visible.thoughtAnchorY ?? visible.screenY };
  return screenPointForAgent(visibleAgents, node, canvas);
}

function projectParticles(globe: GlobeRuntime, centerX: number, centerY: number, radius: number) {
  const visible = [];
  for (const particle of globe.particles) {
    const rotatedX = particle.x * Math.cos(globe.yaw) - particle.z * Math.sin(globe.yaw);
    const rotatedZ = particle.x * Math.sin(globe.yaw) + particle.z * Math.cos(globe.yaw);
    const tiltedY = particle.y * Math.cos(globe.pitch) - rotatedZ * Math.sin(globe.pitch);
    const tiltedZ = particle.y * Math.sin(globe.pitch) + rotatedZ * Math.cos(globe.pitch);
    const depth = (tiltedZ + 1) / 2;
    if (depth < 0.06) continue;
    visible.push({
      particle,
      x: centerX + rotatedX * radius,
      y: centerY + tiltedY * radius,
      depth,
    });
  }
  return visible;
}

function drawAgentLinks(
  context: CanvasRenderingContext2D,
  globe: GlobeRuntime,
  world: NormalizedWorld,
  centerX: number,
  centerY: number,
  radius: number,
  time: number,
) {
  const visibleById = new Map(projectAgents(globe, world, centerX, centerY, radius, time).map((agent) => [agent.id, agent]));
  context.save();
  context.lineCap = "round";
  context.lineJoin = "round";
  for (const edge of world.networkLinks) {
    const from = visibleById.get(edge.source);
    const to = visibleById.get(edge.target);
    if (!from || !to || from.depth < 0.1 || to.depth < 0.1) continue;
    const depth = Math.min(from.depth, to.depth);
    const weight = clamp(Number(edge.weight || 0.4), 0.15, 1);
    const pulse = 0.55 + Math.sin(time * 2.2 + from.phase + to.phase) * 0.18;
    context.strokeStyle = relationshipStroke(edge.type, depth, weight, pulse);
    context.lineWidth = 0.85 + weight * 1.35 + depth * 0.55;
    if (edge.type === "coordination" || edge.type === "influence") {
      context.setLineDash([4, 5]);
    } else {
      context.setLineDash([]);
    }
    const midX = (from.screenX + to.screenX) / 2;
    const midY = (from.screenY + to.screenY) / 2;
    const lift = radius * (0.018 + weight * 0.025);
    context.beginPath();
    context.moveTo(from.screenX, from.screenY);
    context.quadraticCurveTo(midX, midY - lift, to.screenX, to.screenY);
    context.stroke();
  }
  context.setLineDash([]);
  context.restore();
}

function relationshipStroke(type: string, depth: number, weight: number, pulse: number) {
  const alpha = clamp(0.18 + depth * 0.42 + weight * 0.18 + pulse * 0.1, 0.16, 0.82);
  if (type === "member_of") return `rgba(121, 242, 198, ${alpha})`;
  if (type === "operates_in" || type === "located_in" || type === "public_context") return `rgba(128, 199, 255, ${alpha})`;
  if (type === "influence" || type === "trust") return `rgba(255, 209, 102, ${alpha})`;
  if (type === "dependency" || type === "supply_route") return `rgba(255, 153, 153, ${alpha})`;
  return `rgba(174, 225, 255, ${alpha})`;
}

function drawCausalFocus(
  context: CanvasRenderingContext2D,
  projected: ProjectedAgent[],
  focus: CausalFocus | null,
  radius: number,
  time: number,
) {
  if (!focus?.actorId) return;
  const visibleById = new Map(projected.filter((agent) => agent.depth > 0.08).map((agent) => [agent.id, agent]));
  const actor = visibleById.get(focus.actorId);
  if (!actor || actor.depth < 0.1) return;
  const endpointIds = uniqueStrings([...focus.targetIds, ...focus.effectNodeIds]).filter((id) => id !== focus.actorId);
  if (endpointIds.length === 0) return;
  const selectedEffectIds = new Set(focus.selectedEffectNodeIds);

  context.save();
  context.lineCap = "round";
  for (const endpointId of endpointIds.slice(0, 8)) {
    const endpoint = visibleById.get(endpointId);
    if (!endpoint || endpoint.depth < 0.1) continue;
    const selectedEffect = selectedEffectIds.has(endpointId);
    const depth = Math.min(actor.depth, endpoint.depth);
    const pulse = 0.5 + Math.sin(time * 4.2) * 0.5;
    context.strokeStyle = selectedEffect
      ? `rgba(255, 209, 102, ${0.36 + depth * 0.44})`
      : `rgba(121, 242, 198, ${0.28 + depth * 0.36})`;
    context.lineWidth = selectedEffect ? 2.4 : 1.5;
    context.setLineDash(selectedEffect ? [] : [5, 5]);
    context.beginPath();
    context.moveTo(actor.screenX, actor.screenY);
    const cx = (actor.screenX + endpoint.screenX) / 2;
    const cy = (actor.screenY + endpoint.screenY) / 2 - radius * (0.04 + pulse * 0.025);
    context.quadraticCurveTo(cx, cy, endpoint.screenX, endpoint.screenY);
    context.stroke();

    context.setLineDash([]);
    context.fillStyle = selectedEffect
      ? `rgba(255, 209, 102, ${0.42 + depth * 0.38})`
      : `rgba(121, 242, 198, ${0.34 + depth * 0.34})`;
    context.beginPath();
    context.arc(endpoint.screenX, endpoint.screenY, selectedEffect ? 8 : 6, 0, Math.PI * 2);
    context.fill();
  }
  context.setLineDash([]);
  context.strokeStyle = "rgba(255, 255, 255, 0.72)";
  context.lineWidth = 1.4;
  context.beginPath();
  context.arc(actor.screenX, actor.screenY, 9.5, 0, Math.PI * 2);
  context.stroke();
  context.restore();
}

function drawImpactRipples(
  context: CanvasRenderingContext2D,
  projected: ProjectedAgent[],
  world: NormalizedWorld,
  time: number,
) {
  if (world.groundedActions.length === 0) return;
  const visibleById = new Map(projected.filter((agent) => agent.depth > 0.1).map((agent) => [agent.id, agent]));
  const recentActions = world.groundedActions
    .slice()
    .sort((left, right) => Number(right.sequence ?? 0) - Number(left.sequence ?? 0))
    .slice(0, 6);

  context.save();
  context.lineWidth = 1.15;
  for (const action of recentActions) {
    const nodeIds = actionImpactNodeIds(action).slice(0, 3);
    for (const nodeId of nodeIds) {
      const node = visibleById.get(nodeId);
      if (!node || node.depth < 0.12) continue;
      const sequence = Number(action.sequence ?? action.tick ?? 0);
      const phase = (time * 0.72 + (sequence % 11) * 0.13) % 1;
      const ringRadius = (9 + phase * 22) * (0.65 + node.depth * 0.55);
      const alpha = (1 - phase) * (0.08 + node.depth * 0.22);
      context.strokeStyle = action.intervention?.id
        ? `rgba(255, 209, 102, ${alpha + 0.04})`
        : `rgba(121, 242, 198, ${alpha})`;
      context.beginPath();
      context.arc(node.screenX, node.screenY, ringRadius, 0, Math.PI * 2);
      context.stroke();
    }
  }
  context.restore();
}

function actionImpactNodeIds(action: NormalizedWorld["groundedActions"][number]): string[] {
  const ids = new Set<string>();
  if (action.actor_id) ids.add(action.actor_id);
  for (const target of action.targets || []) {
    if (target.id) ids.add(target.id);
  }
  for (const effect of action.effects || []) {
    for (const ref of [effect.target, effect.to, effect.from, effect.source]) {
      if (ref?.id) ids.add(ref.id);
    }
  }
  return uniqueStrings([...ids]);
}

function drawInfluenceArrows(
  context: CanvasRenderingContext2D,
  projected: ProjectedAgent[],
  world: NormalizedWorld,
  radius: number,
  time: number,
) {
  if (world.influenceLinks.length === 0) return;
  const visibleById = new Map(projected.filter((agent) => agent.depth > 0.12).map((agent) => [agent.id, agent]));

  context.save();
  context.lineCap = "round";
  context.lineJoin = "round";
  context.font = "700 10px Inter, system-ui, sans-serif";
  context.textAlign = "center";
  context.textBaseline = "middle";
  for (const link of world.influenceLinks.slice(0, 18)) {
    const from = visibleById.get(link.source);
    const to = visibleById.get(link.target);
    if (!from || !to || from.depth < 0.14 || to.depth < 0.14) continue;
    const depth = Math.min(from.depth, to.depth);
    const weight = clamp(Number(link.weight || 0.5), 0.2, 1);
    const pulse = 0.52 + Math.sin(time * 2.8 + from.phase) * 0.16;
    const alpha = clamp(0.26 + depth * 0.34 + weight * 0.16 + pulse * 0.08, 0.28, 0.76);
    const control = influenceCurveControl(from, to, radius, weight, time);
    context.strokeStyle = `rgba(255, 217, 112, ${alpha})`;
    context.lineWidth = 1.15 + weight * 1.2;
    context.setLineDash([6, 4]);
    context.beginPath();
    context.moveTo(from.screenX, from.screenY);
    context.quadraticCurveTo(control.x, control.y, to.screenX, to.screenY);
    context.stroke();
    context.setLineDash([]);
    drawArrowHead(context, control.x, control.y, to.screenX, to.screenY, `rgba(255, 217, 112, ${alpha + 0.1})`);
    drawInfluenceLabel(context, link.label, (from.screenX + to.screenX + control.x) / 3, (from.screenY + to.screenY + control.y) / 3, alpha);
  }
  context.setLineDash([]);
  context.restore();
}

function influenceCurveControl(
  from: ProjectedAgent,
  to: ProjectedAgent,
  radius: number,
  weight: number,
  time: number,
) {
  const midX = (from.screenX + to.screenX) / 2;
  const midY = (from.screenY + to.screenY) / 2;
  const dx = to.screenX - from.screenX;
  const dy = to.screenY - from.screenY;
  const length = Math.max(Math.hypot(dx, dy), 1);
  const lift = radius * (0.035 + weight * 0.025) * (0.88 + Math.sin(time * 1.4 + from.phase) * 0.08);
  return {
    x: midX + (-dy / length) * lift,
    y: midY + (dx / length) * lift - radius * 0.012,
  };
}

function drawArrowHead(
  context: CanvasRenderingContext2D,
  fromX: number,
  fromY: number,
  toX: number,
  toY: number,
  color: string,
) {
  const angle = Math.atan2(toY - fromY, toX - fromX);
  const length = 8;
  context.fillStyle = color;
  context.beginPath();
  context.moveTo(toX, toY);
  context.lineTo(toX - Math.cos(angle - 0.48) * length, toY - Math.sin(angle - 0.48) * length);
  context.lineTo(toX - Math.cos(angle + 0.48) * length, toY - Math.sin(angle + 0.48) * length);
  context.closePath();
  context.fill();
}

function drawInfluenceLabel(
  context: CanvasRenderingContext2D,
  label: string,
  x: number,
  y: number,
  alpha: number,
) {
  const text = label || "关键角色影响";
  const metrics = context.measureText(text);
  const width = Math.min(metrics.width + 12, 176);
  context.fillStyle = `rgba(8, 16, 18, ${clamp(alpha + 0.16, 0.42, 0.82)})`;
  context.fillRect(x - width / 2, y - 9, width, 18);
  context.fillStyle = `rgba(255, 244, 196, ${clamp(alpha + 0.18, 0.52, 0.92)})`;
  context.fillText(text, x, y, width - 8);
}

function drawAgentNodes(
  context: CanvasRenderingContext2D,
  globe: GlobeRuntime,
  projected: ProjectedAgent[],
  selectedId: string,
  highlightedNetworkNodeIds: Set<string>,
  time: number,
) {
  globe.visibleAgents = projected.filter((item) => item.depth > 0.08);
  const sorted = [...globe.visibleAgents].sort((a, b) => a.depth - b.depth);
  context.save();
  for (const item of sorted) {
    const alpha = 0.62 + item.depth * 0.38;
    const pulse = 0.82 + Math.sin(time * 2.6 + item.phase) * 0.18;
    const selectedNetworkPeer = highlightedNetworkNodeIds.has(item.id) && item.id !== selectedId;
    const size = (item.kind === "key" ? 5.8 : item.kind === "network" ? 3.2 : 4.2) * (0.72 + item.depth * 0.72);
    const color = item.kind === "key"
      ? `rgba(255, 222, 112, ${alpha})`
      : item.kind === "network"
        ? `rgba(132, 238, 255, ${alpha})`
        : `rgba(133, 255, 204, ${alpha})`;
    const shouldGlow = selectedNetworkPeer
      || item.id === selectedId
      || item.kind === "key"
      || item.type === "关系网中枢";
    context.shadowBlur = shouldGlow
      ? selectedNetworkPeer
        ? 12 + item.depth * 12
        : 8 + item.depth * 12
      : 0;
    context.shadowColor = selectedNetworkPeer ? `rgba(255, 236, 166, ${0.52 + item.depth * 0.32})` : color;
    context.fillStyle = color;
    context.beginPath();
    context.arc(item.screenX, item.screenY, size * pulse, 0, Math.PI * 2);
    context.fill();
    if (selectedNetworkPeer) {
      context.strokeStyle = `rgba(255, 236, 166, ${0.36 + item.depth * 0.38})`;
      context.lineWidth = 1.05;
      context.beginPath();
      context.arc(item.screenX, item.screenY, size * 1.72, 0, Math.PI * 2);
      context.stroke();
    }
    if (item.id === selectedId) {
      context.strokeStyle = `rgba(255, 255, 255, ${0.55 + item.depth * 0.35})`;
      context.lineWidth = 1.2;
      context.beginPath();
      context.arc(item.screenX, item.screenY, size * 2.05, 0, Math.PI * 2);
      context.stroke();
    }
    context.shadowBlur = 0;
    context.fillStyle = "rgba(255, 255, 255, 0.9)";
    context.beginPath();
    context.arc(item.screenX - size * 0.24, item.screenY - size * 0.24, Math.max(size * 0.22, 1.1), 0, Math.PI * 2);
    context.fill();
    if (item.depth > 0.64 && item.kind === "key") {
      context.fillStyle = "rgba(245, 251, 247, 0.92)";
      context.font = "700 11px Inter, system-ui, sans-serif";
      context.textAlign = "center";
      context.fillText(item.name, item.screenX, item.screenY + size + 16);
    }
  }
  context.restore();
}

function projectAgents(
  globe: GlobeRuntime,
  world: NormalizedWorld,
  centerX: number,
  centerY: number,
  radius: number,
  time: number,
): ProjectedAgent[] {
  return world.agentNodes.map((agent) => {
    const theta = agent.theta + Math.sin(time * 0.22 + agent.phase) * agent.orbit;
    const phi = agent.phi + Math.cos(time * 0.18 + agent.phase) * agent.orbit * 0.45;
    const base = sphereToCartesian(theta, phi);
    const rotatedX = base.x * Math.cos(globe.yaw) - base.z * Math.sin(globe.yaw);
    const rotatedZ = base.x * Math.sin(globe.yaw) + base.z * Math.cos(globe.yaw);
    const tiltedY = base.y * Math.cos(globe.pitch) - rotatedZ * Math.sin(globe.pitch);
    const tiltedZ = base.y * Math.sin(globe.pitch) + rotatedZ * Math.cos(globe.pitch);
    const depth = (tiltedZ + 1) / 2;
    return {
      ...agent,
      screenX: centerX + rotatedX * radius,
      screenY: centerY + tiltedY * radius,
      depth,
    };
  });
}

function drawGlobeAura(context: CanvasRenderingContext2D, x: number, y: number, radius: number, time: number) {
  const gradient = context.createRadialGradient(x - radius * 0.18, y - radius * 0.2, radius * 0.1, x, y, radius * 1.08);
  gradient.addColorStop(0, "rgba(122, 246, 203, 0.18)");
  gradient.addColorStop(0.42, "rgba(41, 116, 148, 0.12)");
  gradient.addColorStop(0.82, "rgba(4, 8, 12, 0.16)");
  gradient.addColorStop(1, "rgba(4, 8, 12, 0)");
  context.fillStyle = gradient;
  context.beginPath();
  context.arc(x, y, radius * 1.12, 0, Math.PI * 2);
  context.fill();

  context.save();
  context.translate(x, y);
  context.rotate(time * 0.03);
  context.strokeStyle = "rgba(121, 242, 198, 0.16)";
  context.lineWidth = 1;
  context.beginPath();
  context.ellipse(0, 0, radius * 1.02, radius * 0.24, 0, 0, Math.PI * 2);
  context.stroke();
  context.rotate(1.34);
  context.strokeStyle = "rgba(128, 199, 255, 0.12)";
  context.beginPath();
  context.ellipse(0, 0, radius * 0.98, radius * 0.21, 0, 0, Math.PI * 2);
  context.stroke();
  context.restore();
}

function drawGlobeRim(context: CanvasRenderingContext2D, x: number, y: number, radius: number) {
  const rim = context.createRadialGradient(x, y, radius * 0.74, x, y, radius * 1.01);
  rim.addColorStop(0, "rgba(255, 255, 255, 0)");
  rim.addColorStop(0.72, "rgba(121, 242, 198, 0.04)");
  rim.addColorStop(1, "rgba(181, 248, 232, 0.28)");
  context.strokeStyle = rim;
  context.lineWidth = 1.2;
  context.beginPath();
  context.arc(x, y, radius, 0, Math.PI * 2);
  context.stroke();
}

function sphereToCartesian(theta: number, phi: number) {
  const cosPhi = Math.cos(phi);
  return {
    x: Math.cos(theta) * cosPhi,
    y: Math.sin(phi),
    z: Math.sin(theta) * cosPhi,
  };
}
