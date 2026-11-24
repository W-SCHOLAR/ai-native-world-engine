import { useState } from "react";

import { EntangledMultiverseWebGL, type MultiverseWorldRegion } from "./EntangledMultiverseWebGL";
import "./entangledMultiverseDemo.css";

type EntangledMultiverseDemoProps = {
  onReturnToShowcase: () => void;
};

type MultiverseWorld = MultiverseWorldRegion & {
  index: string;
  title: string;
  english: string;
  detail: string;
  accent: string;
};

const MULTIVERSE_IMAGE = "/assets/multiverse/entangled-ten-worlds.png";

export const MULTIVERSE_WORLDS: MultiverseWorld[] = [
  { id: "astral", index: "01", title: "星轨文明", english: "ASTRAL NETWORK", detail: "漂流星环与文明节点互相牵引", centerX: 16.5, centerY: 17.5, width: 31, height: 31, accent: "#6bc6ff" },
  { id: "tribe", index: "02", title: "火种部落", english: "EMBER TRIBE", detail: "营火、迁徙与古老图腾仍在呼吸", centerX: 42, centerY: 17.5, width: 28, height: 31, accent: "#ffb252" },
  { id: "ink", index: "03", title: "墨色山河", english: "INK DYNASTY", detail: "战争与王朝在卷轴般的云层中展开", centerX: 66, centerY: 18, width: 28, height: 32, accent: "#e9b875" },
  { id: "neon", index: "04", title: "霓虹都市", english: "NEON ASCENSION", detail: "未来塔群穿过紫色风暴持续生长", centerX: 88, centerY: 25, width: 22, height: 36, accent: "#ca7cff" },
  { id: "frost", index: "05", title: "永冻裂谷", english: "FROST CITADEL", detail: "冰川神殿在时间冻结处发出蓝光", centerX: 14, centerY: 44.5, width: 28, height: 35, accent: "#8be7ff" },
  { id: "inferno", index: "06", title: "熔火深渊", english: "INFERNO CORE", detail: "高温核心将相邻世界的边界熔化", centerX: 40.5, centerY: 48.5, width: 31, height: 35, accent: "#ff7449" },
  { id: "verdant", index: "07", title: "苍翠遗迹", english: "VERDANT RUINS", detail: "巨木吞没石城，生命从旧文明中溢出", centerX: 71, centerY: 49.5, width: 30, height: 37, accent: "#7fff9c" },
  { id: "dune", index: "08", title: "赤沙方舟", english: "DUNE ARK", detail: "沙海中的孤城追逐最后一束恒星光", centerX: 18, centerY: 78, width: 36, height: 44, accent: "#ffcb73" },
  { id: "abyss", index: "09", title: "深海圣殿", english: "ABYSSAL TEMPLE", detail: "鲸群环绕沉没的蓝色记忆缓慢游弋", centerX: 50, centerY: 80, width: 32, height: 40, accent: "#58d8ff" },
  { id: "clockwork", index: "10", title: "黄铜纪元", english: "CLOCKWORK AGE", detail: "齿轮城市把时间折叠成可见的机械河流", centerX: 82.5, centerY: 79.5, width: 35, height: 41, accent: "#e9a650" },
];

export function EntangledMultiverseDemo({ onReturnToShowcase }: EntangledMultiverseDemoProps) {
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [lockedId, setLockedId] = useState<string | null>(null);
  const activeId = lockedId ?? hoveredId;
  const activeWorld = MULTIVERSE_WORLDS.find((world) => world.id === activeId) ?? null;

  function toggleWorld(id: string) {
    setLockedId((current) => current === id ? null : id);
    setHoveredId(id);
  }

  return (
    <main className={`multiverse-demo${activeWorld ? " is-world-active" : ""}`} data-active-world={activeWorld?.id ?? "none"}>
      <img className="multiverse-ambient" src={MULTIVERSE_IMAGE} alt="" aria-hidden="true" />
      <div className="multiverse-nebula" aria-hidden="true" />

      <header className="multiverse-demo-header">
        <button type="button" className="multiverse-back" onClick={onReturnToShowcase}>
          <span aria-hidden="true">←</span>
          返回万界首页
        </button>
        <div className="multiverse-title">
          <span>THE ENTANGLED REALMS</span>
          <strong>万界纠缠</strong>
        </div>
        <p>悬停世界 · 撕开空间门</p>
      </header>

      <section className="multiverse-stage" aria-label="十个相互纠缠的世界与空间门">
        <EntangledMultiverseWebGL
          imageUrl={MULTIVERSE_IMAGE}
          worlds={MULTIVERSE_WORLDS}
          activeId={activeId}
          onHoverWorld={(id) => lockedId === null && setHoveredId(id)}
          onSelectWorld={toggleWorld}
        />
      </section>

      <aside className={`multiverse-reading${activeWorld ? " is-visible" : ""}`} aria-live="polite">
        <span>{activeWorld?.index ?? "∞"} / 10</span>
        <p>{activeWorld?.english ?? "ENTANGLED MULTIVERSE"}</p>
        <h1 style={{ color: activeWorld?.accent ?? "#f9ecda" }}>{activeWorld?.title ?? "十界共生"}</h1>
        <small>{activeWorld?.detail ?? "悬停一方世界，在它原本的边界撕开空间入口"}</small>
      </aside>

      <nav className="multiverse-world-nav" aria-label="选择纠缠世界">
        {MULTIVERSE_WORLDS.map((world) => (
          <button
            type="button"
            key={world.id}
            className={activeWorld?.id === world.id ? "is-active" : ""}
            style={{ "--world-accent": world.accent }}
            aria-label={`聚焦${world.title}`}
            aria-pressed={lockedId === world.id}
            onPointerEnter={() => lockedId === null && setHoveredId(world.id)}
            onPointerLeave={() => lockedId === null && setHoveredId(null)}
            onFocus={() => setHoveredId(world.id)}
            onBlur={() => lockedId === null && setHoveredId(null)}
            onClick={() => toggleWorld(world.id)}
          >
            <i>{world.index}</i>
            <span>{world.title}</span>
          </button>
        ))}
      </nav>

      <div className="multiverse-coordinate" aria-hidden="true">
        <span>SPATIAL SEAM</span>
        <i />
        <b>{activeWorld ? "DOOR OPENING" : "SEALED"}</b>
      </div>
    </main>
  );
}
