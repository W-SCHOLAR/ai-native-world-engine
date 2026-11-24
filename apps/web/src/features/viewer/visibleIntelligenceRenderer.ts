import { clamp } from "./projectionModel";
import type { OverlayItem, ProjectedAgent } from "./viewerTypes";


export function syncOverlayDiagnostics(
  layer: HTMLDivElement | null,
  overlays: Iterable<OverlayItem>,
  emittedType?: OverlayItem["type"],
  emittedText?: string,
) {
  if (!layer) return;
  let thoughtCount = 0;
  let speechCount = 0;
  let actionCount = 0;
  const thoughtCountsByNode = new Map<string, number>();
  for (const item of overlays) {
    if (item.type === "thought") {
      thoughtCount += 1;
      thoughtCountsByNode.set(item.nodeId, (thoughtCountsByNode.get(item.nodeId) ?? 0) + 1);
    } else if (item.type === "speech") speechCount += 1;
    else actionCount += 1;
  }
  layer.dataset.activeThoughts = String(thoughtCount);
  layer.dataset.activeActions = String(actionCount);
  layer.dataset.activeSpeech = String(speechCount);
  layer.dataset.maxThoughtsPerNode = String(Math.max(0, ...thoughtCountsByNode.values()));
  if (!emittedType) return;
  const emissionKey = emittedType === "thought"
    ? "thoughtEmissions"
    : emittedType === "speech" ? "speechEmissions" : "actionEmissions";
  layer.dataset[emissionKey] = String(Number(layer.dataset[emissionKey] || 0) + 1);
  if (emittedType === "thought" && emittedText) {
    layer.dataset.lastThought = emittedText;
    if (emittedText.trim().length >= 12 && /[.!?。！？]$/.test(emittedText.trim())) {
      layer.dataset.sawReadableThought = "yes";
    }
  }
  const label = emittedType === "thought" ? "思考" : emittedType === "speech" ? "说话" : "行为";
  layer.textContent = `${label}：${emittedText || ""}`;
}


export function drawVisibleIntelligenceOverlays(
  context: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  overlays: Iterable<OverlayItem>,
  visibleAgents: ProjectedAgent[],
  now: number,
  tribeTheme: boolean,
) {
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  const visibleById = new Map(visibleAgents.map((agent) => [agent.id, agent]));
  context.save();
  context.textBaseline = "top";
  for (const item of overlays) {
    const progress = clamp((now - item.createdAt) / item.lifetimeMs, 0, 1);
    const alpha = overlayAlpha(progress);
    if (alpha <= 0.01) continue;
    const visible = visibleById.get(item.nodeId);
    const sourceX = visible?.screenX ?? item.x;
    const sourceY = item.type === "thought" || item.type === "speech"
      ? visible?.thoughtAnchorY ?? visible?.screenY ?? item.y
      : visible?.actionAnchorY ?? visible?.screenY ?? item.y;
    if (item.type === "thought" || item.type === "speech") {
      drawThoughtBubble(context, item, sourceX + item.offsetX, sourceY + item.offsetY, width, height, progress, alpha, tribeTheme);
    } else {
      drawActionText(context, item, sourceX + item.offsetX, sourceY + item.offsetY, width, height, progress, alpha, tribeTheme);
    }
  }
  context.restore();
}

export function overlayLane(type: OverlayItem["type"], siblingIndex: number, baseOffsetY: number) {
  if (type === "thought" || type === "speech") {
    const lane = siblingIndex % 5;
    const row = Math.floor(siblingIndex / 5);
    return {
      offsetX: (lane - 2) * 236,
      offsetY: baseOffsetY - row * 78 - (lane === 2 ? 0 : 12),
    };
  }
  const lane = siblingIndex % 3;
  const row = Math.floor(siblingIndex / 3);
  return {
    offsetX: (lane - 1) * 54,
    offsetY: baseOffsetY + row * 18 + (lane === 1 ? 0 : 8),
  };
}

export function spatialOverlayLaneIndex(
  type: OverlayItem["type"],
  nodeId: string,
  x: number,
  y: number,
  baseOffsetY: number,
  activeItems: Iterable<OverlayItem>,
  stageWidth: number,
  stageHeight: number,
) {
  const items = [...activeItems];
  if (type === "thought" || type === "speech") {
    for (let laneIndex = 0; laneIndex < 30; laneIndex += 1) {
      const candidate = overlayLane(type, laneIndex, baseOffsetY);
      const candidateX = clamp(x + candidate.offsetX, 128, stageWidth - 128);
      const candidateY = clamp(y + candidate.offsetY, 40, stageHeight - 40);
      const collides = items.some((item) => {
        if (item.type !== "thought" && item.type !== "speech") return false;
        const existingX = clamp(item.x + item.offsetX, 128, stageWidth - 128);
        const existingY = clamp(item.y + item.offsetY, 40, stageHeight - 40);
        return Math.abs(existingX - candidateX) < 250
          && Math.abs(existingY - candidateY) < 74;
      });
      if (!collides) return laneIndex;
    }
  }
  return items.filter((item) => (
    item.type === type
    && (item.nodeId === nodeId || (
      Math.abs(item.x - x) <= 80 && Math.abs(item.y - y) <= 60
    ))
  )).length;
}

export function activeThoughtOverlayIds(activeItems: Iterable<OverlayItem>, nodeId: string) {
  return [...activeItems]
    .filter((item) => item.type === "thought" && item.nodeId === nodeId)
    .map((item) => item.id);
}

export function activeActionOverlayIds(activeItems: Iterable<OverlayItem>, nodeId: string) {
  return [...activeItems]
    .filter((item) => item.type === "action" && item.nodeId === nodeId)
    .map((item) => item.id);
}

export function activeSpeechOverlayIds(activeItems: Iterable<OverlayItem>, nodeId: string) {
  return [...activeItems]
    .filter((item) => item.type === "speech" && item.nodeId === nodeId)
    .map((item) => item.id);
}

export function overlayLifetimeMs(salience: number, ttlSeconds?: number) {
  const defaultTtl = salience >= 0.7 ? 4500 : 3700;
  return Number.isFinite(ttlSeconds) ? Math.max(500, Number(ttlSeconds) * 1000) : defaultTtl;
}

function drawThoughtBubble(
  context: CanvasRenderingContext2D,
  item: OverlayItem,
  rawX: number,
  rawY: number,
  stageWidth: number,
  stageHeight: number,
  progress: number,
  alpha: number,
  tribeTheme: boolean,
) {
  context.font = tribeTheme
    ? '800 6px "Songti SC", "STSong", serif'
    : "800 12px Inter, system-ui, sans-serif";
  const layout = thoughtLayout(context, item, tribeTheme);
  const x = clamp(rawX, layout.width / 2 + 8, stageWidth - layout.width / 2 - 8);
  // In the Tribe scene the supplied point is the person's head anchor. Keep
  // the bubble attached to that person instead of applying the globe's float
  // animation, which would make it appear above a different standee.
  const rise = tribeTheme ? 0 : progress * 18;
  const y = clamp(rawY - layout.height - rise, 8, stageHeight - layout.height - 8);
  context.globalAlpha = alpha;
  const speech = item.type === "speech";
  context.fillStyle = speech
    ? tribeTheme ? "rgba(239, 250, 255, 0.97)" : "rgba(13, 35, 48, 0.94)"
    : tribeTheme ? "rgba(255, 252, 242, 0.96)" : "rgba(31, 25, 12, 0.92)";
  context.strokeStyle = speech
    ? tribeTheme ? "rgba(28, 94, 122, 0.42)" : "rgba(104, 211, 255, 0.72)"
    : tribeTheme ? "rgba(46, 35, 22, 0.28)" : "rgba(255, 209, 102, 0.62)";
  context.lineWidth = 1;
  context.beginPath();
  context.roundRect(x - layout.width / 2, y, layout.width, layout.height, tribeTheme ? 6 : 8);
  context.fill();
  context.stroke();
  context.fillStyle = speech
    ? tribeTheme ? "#173c4d" : "#d8f6ff"
    : tribeTheme ? "#2d2115" : "#fff1bd";
  context.textAlign = "left";
  for (const [index, line] of layout.lines.entries()) {
    const padding = tribeTheme ? 4.5 : 10;
    const lineHeight = tribeTheme ? 8 : 16;
    const textTop = tribeTheme ? 4.5 : 9;
    context.fillText(line, x - layout.width / 2 + padding, y + textTop + index * lineHeight);
  }
  context.globalAlpha = 1;
}

function drawActionText(
  context: CanvasRenderingContext2D,
  item: OverlayItem,
  rawX: number,
  rawY: number,
  stageWidth: number,
  stageHeight: number,
  progress: number,
  alpha: number,
  tribeTheme: boolean,
) {
  context.font = tribeTheme
    ? "900 4px Inter, system-ui, sans-serif"
    : "900 13px Inter, system-ui, sans-serif";
  const text = actionDisplayText(context, item);
  const x = clamp(tribeTheme ? rawX : rawX + (progress - 0.5) * 20, 72, stageWidth - 72);
  const y = clamp(rawY - progress * 18, 12, stageHeight - 24);
  context.globalAlpha = alpha;
  context.fillStyle = tribeTheme ? "#000" : "#c9ffe8";
  context.textAlign = "center";
  context.fillText(text, x, y);
  context.globalAlpha = 1;
}

function thoughtLayout(context: CanvasRenderingContext2D, item: OverlayItem, tribeTheme: boolean) {
  if (item.renderLines && item.renderWidth && item.renderHeight) {
    return { lines: item.renderLines, width: item.renderWidth, height: item.renderHeight };
  }
  const maxWidth = tribeTheme ? 111 : 220;
  const padding = tribeTheme ? 9 : 20;
  const lineHeight = tribeTheme ? 8 : 16;
  const minWidth = tribeTheme ? 51 : 100;
  const maxBubbleWidth = tribeTheme ? 120 : 240;
  const lines = wrapText(context, item.text, maxWidth);
  const width = clamp(Math.max(...lines.map((line) => context.measureText(line).width), tribeTheme ? 42 : 80) + padding, minWidth, maxBubbleWidth);
  const height = lines.length * lineHeight + (tribeTheme ? 9 : 18);
  item.renderLines = lines;
  item.renderWidth = width;
  item.renderHeight = height;
  return { lines, width, height };
}

function actionDisplayText(context: CanvasRenderingContext2D, item: OverlayItem) {
  if (item.renderText) return item.renderText;
  let text = item.text.trim();
  while (text.length > 4 && context.measureText(text).width > 220) {
    text = text.slice(0, -1).trimEnd();
  }
  item.renderText = text === item.text.trim() ? text : `${text}…`;
  return item.renderText;
}

function wrapText(context: CanvasRenderingContext2D, text: string, maxWidth: number) {
  const words = text.trim().split(/\s+/).filter(Boolean);
  const usesCharacterWrapping = words.length <= 1;
  const units = usesCharacterWrapping ? Array.from(text.trim()) : words;
  const separator = usesCharacterWrapping ? "" : " ";
  const lines: string[] = [];
  let line = "";
  for (const unit of units) {
    const candidate = line ? `${line}${separator}${unit}` : unit;
    if (line && context.measureText(candidate).width > maxWidth) {
      lines.push(line);
      line = unit;
    } else {
      line = candidate;
    }
  }
  if (line) lines.push(line);
  return lines.length > 0 ? lines : [text.trim()];
}

function overlayAlpha(progress: number) {
  if (progress < 0.14) return progress / 0.14;
  if (progress > 0.78) return (1 - progress) / 0.22;
  return 1;
}
