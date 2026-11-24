import { officialWorldById } from "./officialWorlds";
import { WanjieChrome } from "./OfficialWanjieHome";
import "./officialWanjie.css";

type OfficialWanjieWorldProps = {
  worldId: string;
  onNavigate: (path: string) => void;
};

export function OfficialWanjieWorld({ worldId, onNavigate }: OfficialWanjieWorldProps) {
  const world = officialWorldById(worldId);

  if (!world) {
    return (
      <WanjieChrome onNavigate={onNavigate}>
        <main className="wanjie-missing">
          <p>这个世界不在当前官方目录中</p>
          <button type="button" className="wanjie-primary" onClick={() => onNavigate("/wanjie")}>返回万界</button>
        </main>
      </WanjieChrome>
    );
  }

  const isFeatured = world.status === "featured";

  return (
    <WanjieChrome onNavigate={onNavigate}>
      <main className={`wanjie-world is-${world.status}`}>
        <div className="wanjie-world-player">
          <img src={world.hero ?? world.cover} alt={`${world.title}主视觉`} style={{ objectPosition: world.coverFocus }} />
          <span className={`wanjie-detail-status is-${world.status}`}>
            {isFeatured ? "主推制作" : "概念预告"}
          </span>
        </div>
        <div className="wanjie-world-copy">
          <p className="wanjie-kicker">万界原创 · {world.genre} · {world.season}</p>
          <h1>{world.title}</h1>
          <p className="wanjie-hero-tagline">{world.tagline}</p>
          <p className="wanjie-hero-summary">{world.summary}</p>
          <dl className="wanjie-world-facts">
            <div><dt>你的身份</dt><dd>{world.playerIdentity}</dd></div>
            <div><dt>世界规模</dt><dd>{world.scale}</dd></div>
            <div><dt>互动方式</dt><dd>{world.playStyle}</dd></div>
          </dl>
          <p className="wanjie-emotional-promise">{world.emotionalPromise}</p>
          <p className="wanjie-world-status">{isFeatured ? "第一季制作中" : "世界概念预告"}</p>
          <div className="wanjie-world-actions">
            <button type="button" className="wanjie-primary" disabled>
              {isFeatured ? "进入世界" : "关注制作"}
            </button>
            <button type="button" className="wanjie-secondary" onClick={() => onNavigate("/wanjie")}>返回万界</button>
          </div>
        </div>

        <section className="wanjie-panel" aria-labelledby="wanjie-left-title">
          <div className="wanjie-panel-heading">
            <h2 id="wanjie-left-title">{isFeatured ? "你离开后" : "概念中的此刻"}</h2>
          </div>
          <p className="wanjie-world-event">{isFeatured ? world.afterYouLeft : world.chapter}</p>
        </section>

        <section className="wanjie-panel" aria-labelledby="wanjie-people-title">
          <div className="wanjie-panel-heading">
            <h2 id="wanjie-people-title">核心人物</h2>
          </div>
          <div className="wanjie-people">
            {world.characters.map((character) => (
              <article key={character.name} className="wanjie-person wanjie-person-static">
                <img src={world.cover} alt="" style={{ objectPosition: world.coverFocus }} />
                <span>
                  <strong>{character.name}</strong>
                  <small>{character.role}</small>
                  <em>{character.hook}</em>
                </span>
              </article>
            ))}
          </div>
        </section>
      </main>
    </WanjieChrome>
  );
}
