import { WORLD_FEED, worldFeedCover } from "./WorldFeedHomeDemo";
import "./worldFeedHomeDemo.css";
import "./worldFeedDetailDemo.css";

type WorldFeedDetailDemoProps = {
  worldId: string;
  onNavigate: (path: string) => void;
};

export function WorldFeedDetailDemo({ worldId, onNavigate }: WorldFeedDetailDemoProps) {
  const world = WORLD_FEED.find((item) => item.id === worldId);

  if (!world) {
    return (
      <main className="world-detail-demo world-feed-demo world-detail-missing">
        <div className="world-detail-missing-mark">404 / LOST WORLD</div>
        <h1>这个世界不在当前宇宙中</h1>
        <p>它可能尚未诞生、已经归档，或来自另一条时间线。</p>
        <button type="button" onClick={() => onNavigate("/showcase")}>返回世界展示</button>
      </main>
    );
  }

  return (
    <main className="world-landing world-feed-demo" style={{ "--detail-accent": world.accent } as Record<string, string>}>
      <header className="world-landing-header">
        <button type="button" onClick={() => onNavigate("/showcase")}><span>←</span> 返回世界展示</button>
      </header>

      <section className="world-landing-stage" aria-labelledby="world-landing-title">
        <img src={worldFeedCover(world)} alt="" />
        <div className="world-landing-shade" />
        <div className="world-landing-copy">
          <div className="world-landing-kicker"><span>{world.channel}世界</span><i />{world.status}</div>
          <h1 id="world-landing-title">{world.title}</h1>
          <p>{world.summary}</p>
          <strong>{world.signal}</strong>
          <dl>
            <div><dt>世界时间</dt><dd>{world.worldTime}</dd></div>
            <div><dt>活跃角色</dt><dd>{world.characters.toLocaleString()}</dd></div>
            <div><dt>记录事件</dt><dd>{world.events.toLocaleString()}</dd></div>
            <div><dt>世界维护者</dt><dd>{world.keeper}</dd></div>
          </dl>
          <div className="world-landing-tags">{world.tags.map((tag) => <span key={tag}>#{tag}</span>)}</div>
        </div>
      </section>

      <section className="world-landing-status" aria-label="世界接入状态">
        <div>
          <small>WORLD AVAILABILITY</small>
          <h2>{world.route ? "这个世界已经接入互动运行时" : "这个世界仍处于概念孵化阶段"}</h2>
          <p>{world.route ? "继续前往世界主页面，观察它的实时演化与完整互动能力。" : "当前页面只介绍世界概念。待运行时接入后，卡片将直接打开它正在发生的世界。"}</p>
        </div>
        {world.route ? (
          <button type="button" onClick={() => onNavigate(world.route!)}>打开世界 <span>↗</span></button>
        ) : (
          <button type="button" onClick={() => onNavigate("/showcase")}>继续发现世界 <span>→</span></button>
        )}
      </section>
    </main>
  );
}
