import { useEffect, useMemo, useRef, useState } from "react";

import { FLAGSHIP_WORLD_ID, OFFICIAL_WORLDS, flagshipWorld, officialWorldById, type OfficialWorld } from "./officialWorlds";
import "./officialWanjie.css";

type OfficialWanjieHomeProps = {
  onNavigate: (path: string) => void;
};

const CHANNELS = [
  "推荐",
  "全部",
  "主推",
  "东方科幻",
  "未来都市",
  "星际旅途",
  "温暖日常",
  "机甲战斗",
  "生态科幻",
  "悬疑奇想",
] as const;

type EditorialCard = {
  key: string;
  world: OfficialWorld;
  title: string;
  label: string;
  meta: string;
};

const FEATURED_WORLDS = OFFICIAL_WORLDS.filter((world) => world.status === "featured");

function buildEditorialCards(worlds: OfficialWorld[]): EditorialCard[] {
  return [...worlds]
    .sort((left, right) => left.recommendationRank - right.recommendationRank)
    .slice(0, 6)
    .map((world) => ({
      key: world.id,
      world,
      title: world.visualHook,
      label: world.status === "featured" ? "制作中" : "概念预告",
      meta: `${world.genre} · ${world.characters[0].name}`,
    }));
}

export function WanjieChrome({
  onNavigate,
  search,
  children,
}: {
  onNavigate: (path: string) => void;
  search?: {
    value: string;
    onChange: (value: string) => void;
    inputRef?: { current: HTMLInputElement | null };
  };
  children: unknown;
}) {
  return (
    <div className="wanjie-shell">
      <header className="wanjie-header">
        <button className="wanjie-brand" type="button" onClick={() => onNavigate("/wanjie")} aria-label="万界首页">
          <BiliTvLogo />
          <strong>万界</strong>
        </button>
        <nav className="wanjie-header-links" aria-label="主导航">
          <button type="button" className="is-active" onClick={() => onNavigate("/wanjie")}>首页</button>
          <button type="button" onClick={() => onNavigate("/wanjie")}>世界</button>
          <button type="button" onClick={() => onNavigate("/wanjie")}>动态</button>
          <button type="button" onClick={() => onNavigate("/wanjie")}>人物</button>
          <button type="button" onClick={() => onNavigate("/")}>实验室</button>
        </nav>
        <label className="wanjie-search">
          <input
            ref={search?.inputRef}
            value={search?.value ?? ""}
            readOnly={!search}
            onFocus={() => {
              if (!search) onNavigate("/wanjie");
            }}
            onChange={(event: { target: { value: string } }) => search?.onChange(event.target.value)}
            placeholder="搜索世界、角色或正在发生的事件"
            aria-label="搜索世界"
          />
          <span className="wanjie-search-btn" aria-hidden="true"><SearchIcon /></span>
        </label>
        <nav className="wanjie-nav" aria-label="用户入口">
          <button type="button">动态</button>
          <button type="button">历史</button>
          <button type="button" onClick={() => onNavigate("/")}>引擎实验室</button>
          <span className="wanjie-observer"><span>旅</span></span>
        </nav>
      </header>
      {children}
      <footer className="wanjie-footer">
        <strong>万界</strong>
        <span>发现一个世界，然后进入它正在发生的此刻。</span>
      </footer>
    </div>
  );
}

export function OfficialWanjieHome({ onNavigate }: OfficialWanjieHomeProps) {
  const [activeId, setActiveId] = useState(FLAGSHIP_WORLD_ID);
  const [paused, setPaused] = useState(false);
  const [query, setQuery] = useState("");
  const [channel, setChannel] = useState<(typeof CHANNELS)[number]>("推荐");
  const searchRef = useRef<HTMLInputElement | null>(null);
  const hero = officialWorldById(activeId) ?? flagshipWorld();

  const worlds = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return OFFICIAL_WORLDS.filter((world) => {
      const inChannel =
        channel === "推荐" ||
        channel === "全部" ||
        (channel === "主推" && world.status === "featured") ||
        world.genre === channel;
      const text = [
        world.title,
        world.tagline,
        world.summary,
        world.season,
        world.genre,
        world.visualHook,
        world.emotionalPromise,
        ...world.characters.map((item) => item.name),
      ].join(" ").toLocaleLowerCase();
      return inChannel && (!needle || text.includes(needle));
    });
  }, [channel, query]);

  const editorialCards = useMemo(() => buildEditorialCards(worlds), [worlds]);
  const browsing = !query.trim() && channel === "推荐";

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "/" && document.activeElement?.tagName !== "INPUT") {
        event.preventDefault();
        searchRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    if (paused) return undefined;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return undefined;
    const filteredFeatured = worlds.filter((world) => world.status === "featured");
    const slides = filteredFeatured.length > 0 ? filteredFeatured : FEATURED_WORLDS;
    const timer = window.setInterval(() => {
      setActiveId((current) => {
        const index = slides.findIndex((world) => world.id === current);
        return slides[(index + 1) % slides.length].id;
      });
    }, 4000);
    return () => window.clearInterval(timer);
  }, [paused, worlds]);

  function openWorld(world: OfficialWorld) {
    onNavigate(`/wanjie/${world.id}`);
  }

  return (
    <WanjieChrome
      onNavigate={onNavigate}
      search={{ value: query, onChange: setQuery, inputRef: searchRef }}
    >
      <div className="wanjie-channels" aria-label="分区">
        {CHANNELS.map((item) => (
          <button
            key={item}
            type="button"
            className={channel === item ? "is-active" : ""}
            onClick={() => setChannel(item)}
          >
            {item}
          </button>
        ))}
      </div>

      <main className="wanjie-home">
        <section
          className="wanjie-recommended"
          aria-labelledby="wanjie-hero-title"
          onMouseEnter={() => setPaused(true)}
          onMouseLeave={() => setPaused(false)}
        >
          <button
            type="button"
            className="wanjie-banner"
            onClick={() => openWorld(hero)}
            aria-label={`打开世界：${hero.title}`}
          >
            <img className="wanjie-hero-art" src={hero.hero ?? hero.cover} alt="" style={{ objectPosition: hero.coverFocus }} />
            <span className="wanjie-banner-copy">
              <strong id="wanjie-hero-title">{hero.title}</strong>
              <small>{hero.visualHook}</small>
              <b>查看世界</b>
            </span>
            <span className="wanjie-banner-thumbs">
              {FEATURED_WORLDS.map((world) => (
                <i
                  key={world.id}
                  className={world.id === hero.id ? "is-active" : ""}
                  onClick={(event: { stopPropagation: () => void }) => {
                    event.stopPropagation();
                    setActiveId(world.id);
                  }}
                />
              ))}
            </span>
          </button>

          {editorialCards.map((card) => (
            <article className="wanjie-vcard" key={card.key}>
              <button type="button" onClick={() => openWorld(card.world)} aria-label={`打开世界：${card.world.title}`}>
                <span className="wanjie-vcard-cover">
                  <img src={card.world.cover} alt="" style={{ objectPosition: card.world.coverFocus }} />
                  <span className="wanjie-vcard-stats">
                    <i>{card.label}</i>
                    <i>{card.world.title}</i>
                  </span>
                </span>
                <strong>{card.title}</strong>
                <small>{card.meta}</small>
              </button>
            </article>
          ))}
        </section>

        {browsing ? (
          <section className="wanjie-block" aria-labelledby="wanjie-continue-title">
            <div className="wanjie-block-head">
              <h2 id="wanjie-continue-title">继续播放</h2>
              <span>更多</span>
            </div>
            <div className="wanjie-continue">
              {FEATURED_WORLDS.map((world) => (
                <button type="button" key={world.id} onClick={() => openWorld(world)} aria-label={`继续探索：${world.title}`}>
                  <span className="wanjie-vcard-cover">
                    <img src={world.cover} alt="" style={{ objectPosition: world.coverFocus }} />
                    <i className="wanjie-progress"><em /></i>
                  </span>
                  <strong>{world.title}</strong>
                  <small>看到 {world.season}</small>
                </button>
              ))}
            </div>
          </section>
        ) : null}

        <section className="wanjie-block" aria-labelledby="wanjie-originals-title">
          <div className="wanjie-block-head">
            <h2 id="wanjie-originals-title">{query ? `“${query}” 的世界` : channel === "推荐" ? "全部世界" : channel}</h2>
            <span>{worlds.length} 个世界</span>
          </div>
          {worlds.length === 0 ? (
            <div className="wanjie-empty">没有找到相关世界</div>
          ) : (
            <div className="wanjie-posters">
              {worlds.map((world) => (
                <button
                  key={world.id}
                  type="button"
                  className="wanjie-poster"
                  onClick={() => openWorld(world)}
                  aria-label={`打开世界：${world.title}`}
                >
                  <span className="wanjie-poster-frame">
                    <img src={world.cover} alt={`${world.title}封面`} />
                    <span className={`wanjie-world-badge is-${world.status}`}>
                      {world.status === "featured" ? "主推制作" : "概念预告"}
                    </span>
                  </span>
                  <strong>{world.title}</strong>
                  <small>{world.genre} · {world.season}</small>
                </button>
              ))}
            </div>
          )}
        </section>

        {browsing ? (
          <section className="wanjie-block" aria-labelledby="wanjie-left-title">
            <div className="wanjie-block-head">
              <h2 id="wanjie-left-title">世界正在发生</h2>
            </div>
            <div className="wanjie-events">
              {OFFICIAL_WORLDS.slice(0, 6).map((world) => (
                <button key={world.id} type="button" className="wanjie-event" onClick={() => openWorld(world)}>
                  <img src={world.cover} alt="" style={{ objectPosition: world.coverFocus }} />
                  <span>
                    <b>{world.status === "featured" ? world.characters[0].name : "概念预告"}</b>
                    <strong>{world.chapter}</strong>
                    <small>{world.title} · {world.genre}</small>
                  </span>
                </button>
              ))}
            </div>
          </section>
        ) : null}

        {browsing ? (
          <section className="wanjie-block wanjie-block--last" aria-labelledby="wanjie-people-title">
            <div className="wanjie-block-head">
              <h2 id="wanjie-people-title">热门人物</h2>
            </div>
            <div className="wanjie-people">
              {FEATURED_WORLDS.map((world) => {
                const character = world.characters[0];
                return (
                  <button key={world.id} type="button" className="wanjie-person" onClick={() => openWorld(world)}>
                    <img src={world.cover} alt="" style={{ objectPosition: world.coverFocus }} />
                    <span>
                      <strong>{character.name}</strong>
                      <small>{world.title}</small>
                      <em>{character.hook}</em>
                    </span>
                  </button>
                );
              })}
            </div>
          </section>
        ) : null}
      </main>
    </WanjieChrome>
  );
}

function BiliTvLogo() {
  return (
    <svg className="wanjie-tv" viewBox="0 0 28 28" aria-hidden="true">
      <path d="M8.2 3.2 11 6h6l2.8-2.8" />
      <rect x="3.2" y="6.2" width="21.6" height="16.4" rx="5.2" />
      <circle cx="10.2" cy="14.4" r="1.7" />
      <circle cx="17.8" cy="14.4" r="1.7" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="11" cy="11" r="6" />
      <path d="m16 16 4 4" />
    </svg>
  );
}

