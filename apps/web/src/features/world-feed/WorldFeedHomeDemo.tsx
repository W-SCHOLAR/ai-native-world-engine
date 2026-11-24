import { useEffect, useMemo, useRef, useState } from "react";

import planetRuntimeCover from "../../../../../runtime-screenshot.png";
import tribeRuntimeCover from "../../../../../tribe-survival-all-portraits-final.png";

import "./worldFeedHomeDemo.css";

type WorldChannel = "全部" | "文明" | "幻想" | "历史" | "生存" | "科幻" | "自然" | "悬疑";
type SortMode = "推荐" | "最热" | "新生" | "角色最多";

export type FeedWorld = {
  id: string;
  title: string;
  summary: string;
  channel: Exclude<WorldChannel, "全部">;
  cover: string;
  accent: string;
  heat: number;
  heatLabel: string;
  events: number;
  characters: number;
  age: number;
  worldTime: string;
  status: string;
  keeper: string;
  tags: string[];
  signal: string;
  coverPosition?: string;
  route?: string;
};

const CHANNELS: WorldChannel[] = ["全部", "文明", "幻想", "历史", "生存", "科幻", "自然", "悬疑"];
const SORTS: SortMode[] = ["推荐", "最热", "新生", "角色最多"];
const HOME_CHANNELS: WorldChannel[] = ["全部", "幻想", "历史", "科幻", "生存", "自然"];

export const WORLD_FEED: FeedWorld[] = [
  { id: "planet-world", title: "星球互动世界", summary: "观察国家、组织、城市与关键角色在同一颗星球上的关系、压力与真实行动。", channel: "文明", cover: planetRuntimeCover, coverPosition: "50% 52%", accent: "#45b9f4", heat: 982000, heatLabel: "98.2万", events: 1777, characters: 595, age: 18, worldTime: "实时 Tick", status: "关系网络运行中", keeper: "AI 原生世界引擎", tags: ["星球", "关系网络", "关键角色"], signal: "595 个世界主体 · 1,777 条关系连接", route: "/worlds/planet" },
  { id: "tribe-world", title: "部落互动世界", summary: "俯瞰河谷、营火、迁徙与资源压力，部落成员在生存规则裁决下持续行动。", channel: "生存", cover: tribeRuntimeCover, coverPosition: "50% 54%", accent: "#d69a43", heat: 763000, heatLabel: "76.3万", events: 54, characters: 59, age: 3, worldTime: "生存推演中", status: "生存行动运行中", keeper: "部落生存运行时", tags: ["部落", "生存", "迁徙"], signal: "59 个生存主体 · 11 个部落阵营", route: "/worlds/tribe" },
  { id: "neon-ascension", title: "霓虹都市：记忆交易所凌晨停止报价", summary: "算法财团控制着记忆定价，地下街区正在生成自己的公共梦境。", channel: "科幻", cover: "/assets/multiverse/masks/neon.png", accent: "#be51e8", heat: 648000, heatLabel: "64.8万", events: 1627, characters: 890, age: 9, worldTime: "03:47:12", status: "异常涌现", keeper: "零号街区", tags: ["赛博朋克", "AI", "经济"], signal: "公共梦境已覆盖 4 区" },
  { id: "frost-citadel", title: "永冻裂谷：冰层下传来规律的钟声", summary: "时间被冰封在不同深度，探险队每下降一层就会失去一段共同记忆。", channel: "悬疑", cover: "/assets/multiverse/masks/frost.png", accent: "#3f9cd7", heat: 531000, heatLabel: "53.1万", events: 473, characters: 28, age: 6, worldTime: "极昼 42:18", status: "等待抉择", keeper: "北境档案馆", tags: ["冰川", "时间", "探索"], signal: "未知声源距地表 2.7km" },
  { id: "inferno-core", title: "熔火深渊：城市决定向地心再降一层", summary: "以热量为货币的垂直城市，正在资源繁荣与结构崩塌之间下注。", channel: "幻想", cover: "/assets/multiverse/masks/inferno.png", accent: "#ee5444", heat: 419000, heatLabel: "41.9万", events: 782, characters: 164, age: 5, worldTime: "熔炉纪 88", status: "资源繁荣", keeper: "热核议事厅", tags: ["地心", "能源", "城市"], signal: "核心温度 +8.4%" },
  { id: "verdant-ruins", title: "苍翠遗迹：森林学会了城市的语言", summary: "巨木吞没旧文明后，植物网络开始复述最后一代居民的争论。", channel: "自然", cover: "/assets/multiverse/masks/verdant.png", accent: "#3f9d68", heat: 884000, heatLabel: "88.4万", events: 1189, characters: 208, age: 15, worldTime: "生长季 112", status: "生命爆发", keeper: "苔原共听者", tags: ["生态", "遗迹", "共生"], signal: "新物种形成 17 种" },
  { id: "dune-ark", title: "赤沙方舟：最后的水源拒绝被任何人占有", summary: "移动城邦追逐恒星阴影，年轻的水源守护者撕毁了旧分配表。", channel: "生存", cover: "/assets/multiverse/masks/dune.png", accent: "#d7863c", heat: 705000, heatLabel: "70.5万", events: 1024, characters: 191, age: 11, worldTime: "旱季第 61 日", status: "联盟重组", keeper: "方舟气象台", tags: ["沙海", "城邦", "资源"], signal: "水权联盟裂变为 3 方" },
  { id: "abyssal-temple", title: "深海圣殿：鲸群带回一段不属于海洋的歌", summary: "沉没文明的记忆以声波保存，新的旋律可能改写整片海域的迁徙。", channel: "幻想", cover: "/assets/multiverse/masks/abyss.png", accent: "#218fb5", heat: 936000, heatLabel: "93.6万", events: 689, characters: 73, age: 14, worldTime: "潮汐 09:26", status: "神秘信号", keeper: "蓝渊聆听站", tags: ["深海", "鲸群", "记忆"], signal: "未知旋律重复 9 次" },
  { id: "clockwork-age", title: "黄铜纪元：全城的钟慢了一秒", summary: "精确运转三百年的机械共同体，第一次出现无人能够解释的误差。", channel: "文明", cover: "/assets/multiverse/masks/clockwork.png", accent: "#ad7739", heat: 812000, heatLabel: "81.2万", events: 2140, characters: 640, age: 17, worldTime: "齿轮历 301", status: "秩序松动", keeper: "中央校时塔", tags: ["蒸汽", "秩序", "机械"], signal: "全域时差 1.003 秒" },
  { id: "living-planet", title: "活体星球：一场情绪风暴跨越三块大陆", summary: "城市、组织与关键角色构成会呼吸的全球关系网，每个决定都会形成回声。", channel: "文明", cover: "/assets/multiverse/entangled-ten-worlds.png", accent: "#227ec7", heat: 1460000, heatLabel: "146万", events: 3562, characters: 2150, age: 20, worldTime: "UTC 18:42", status: "全域在线", keeper: "世界引擎", tags: ["地球", "社会", "关系网"], signal: "协作倾向 +6%", route: "/worlds/planet" },
  { id: "river-valley", title: "河谷聚落：两个营火正在变成两个制度", summary: "相距不到百米的营火采用了不同的分配规则，信任开始走向岔路。", channel: "生存", cover: "/assets/tribe-survival-settlement.png", accent: "#90723e", heat: 328000, heatLabel: "32.8万", events: 374, characters: 34, age: 2, worldTime: "第 86 夜", status: "缓慢分化", keeper: "营火边的石片", tags: ["聚落", "制度", "信任"], signal: "群体凝聚度差值 18%" },
  { id: "migration-map", title: "无名大陆：迁徙路线突然绕开了丰饶区", summary: "地形没有变化，但所有动物与旅人都像在回避同一个不可见的中心。", channel: "悬疑", cover: "/assets/tribe-survival-map.png", accent: "#62714c", heat: 294000, heatLabel: "29.4万", events: 221, characters: 19, age: 1, worldTime: "勘探第 23 日", status: "原因未知", keeper: "远行者地图室", tags: ["地图", "迁徙", "异常"], signal: "中心区静默半径 41km" },
  { id: "glass-garden", title: "玻璃花园：植物开始为访客编写梦境", summary: "透明温室里的每一次呼吸都被记录，花朵用气味生成私人世界。", channel: "自然", cover: "/assets/multiverse/masks/verdant.png", accent: "#3aaa8a", heat: 388000, heatLabel: "38.8万", events: 342, characters: 126, age: 4, worldTime: "花期 08:15", status: "温和演化", keeper: "第九温室", tags: ["植物", "梦境", "实验"], signal: "共享梦境首次出现" },
  { id: "silent-orbit", title: "寂静轨道：失联飞船仍在发送生日祝福", summary: "自动系统坚持维护一段已经无人接收的社会关系，直到新的访客抵达。", channel: "科幻", cover: "/assets/multiverse/masks/astral.png", accent: "#677dc5", heat: 452000, heatLabel: "45.2万", events: 601, characters: 12, age: 8, worldTime: "任务日 4,091", status: "等待回应", keeper: "轨道中继站", tags: ["飞船", "孤独", "记忆"], signal: "祝福对象最后在线于 11 年前" },
  { id: "paper-kingdom", title: "纸上王国：史官删去一个名字后，北方下雪了", summary: "现实服从史书记录的王朝里，一次善意的删改引发了无法回滚的天气。", channel: "历史", cover: "/assets/multiverse/masks/ink.png", accent: "#93624d", heat: 677000, heatLabel: "67.7万", events: 887, characters: 247, age: 13, worldTime: "永和六年", status: "因果偏移", keeper: "无名史官", tags: ["王朝", "因果", "文字"], signal: "北境积雪已持续 7 日" },
  { id: "cloud-market", title: "云上集市：所有人的影子今天都在讨价还价", summary: "漂浮集市允许居民出租影子劳动，清晨却出现了第一场影子罢工。", channel: "文明", cover: "/assets/multiverse/masks/dune.png", accent: "#ba7f57", heat: 349000, heatLabel: "34.9万", events: 458, characters: 386, age: 10, worldTime: "开市后 2 时", status: "秩序争议", keeper: "云端交易所", tags: ["市场", "身份", "奇想"], signal: "影子劳动力停摆 63%" },
];

const HERO_WORLDS = [
  { id: "planet-world", title: "星球互动世界", rate: "595 个主体持续演化" },
  { id: "tribe-world", title: "部落互动世界", rate: "59 个生存主体持续行动" },
  { id: "neon-ascension", title: "霓虹都市", rate: "64,876 个事件/分钟" },
];

const CONTINUE_WORLDS = [
  { id: "tribe-world", progress: 76 },
  { id: "planet-world", progress: 45 },
  { id: "neon-ascension", progress: 32 },
];

type WorldFeedHomeDemoProps = {
  onNavigate: (path: string) => void;
};

export function worldFeedCover(world: FeedWorld) {
  return world.cover.replace("/assets/multiverse/masks/", "/assets/world-feed/");
}

export function WorldFeedHomeDemo({ onNavigate }: WorldFeedHomeDemoProps) {
  const [query, setQuery] = useState("");
  const [channel, setChannel] = useState<WorldChannel>("全部");
  const [sort, setSort] = useState<SortMode>("推荐");
  const searchRef = useRef<HTMLInputElement | null>(null);

  const worlds = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    const matching = WORLD_FEED.filter((world) => {
      const inChannel = channel === "全部" || world.channel === channel;
      const text = [world.title, world.summary, world.channel, world.keeper, ...world.tags].join(" ").toLocaleLowerCase();
      return inChannel && (!needle || text.includes(needle));
    });
    if (sort === "最热") return [...matching].sort((a, b) => b.heat - a.heat);
    if (sort === "新生") return [...matching].sort((a, b) => a.age - b.age);
    if (sort === "角色最多") return [...matching].sort((a, b) => b.characters - a.characters);
    return matching;
  }, [channel, query, sort]);

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

  function resetFeed() {
    setQuery("");
    setChannel("全部");
    setSort("推荐");
    searchRef.current?.focus();
  }

  function openWorld(world: FeedWorld) {
    onNavigate(world.route ?? `/worlds/discover/${world.id}`);
  }

  return (
    <main className="world-feed-demo">
      <header className="world-feed-header">
        <div className="world-feed-brand" aria-label="万界首页">
          <span className="world-feed-brand-mark" aria-hidden="true"><i /><b>✦</b></span>
          <strong>万界</strong>
        </div>
        <label className="world-feed-search">
          <WorldIcon name="search" />
          <input ref={searchRef} value={query} onChange={(event: { target: { value: string } }) => setQuery(event.target.value)} placeholder="搜索世界、角色或正在发生的事件" aria-label="搜索世界" />
          <kbd>/</kbd>
          {query && <button type="button" onClick={() => setQuery("")} aria-label="清空搜索">×</button>}
        </label>
        <nav className="world-feed-actions" aria-label="展示入口">
          <span className="world-feed-observer"><span className="world-feed-avatar">旅</span><small>观察者</small></span>
        </nav>
      </header>

      <section className="world-feed-hero" aria-labelledby="world-feed-heading">
        <div className="world-feed-hero-copy">
          <span><i /> 12,480 个世界正在演化 <b>LIVE</b></span>
          <h1 id="world-feed-heading">世界不再被写完，<br /><em>它们正在发生。</em></h1>
          <p>选择一方世界成为观察者。你看到的不只是故事，<br />而是角色、关系和规则此刻共同生成的命运。</p>
          <div>
            <button type="button" onClick={() => document.getElementById("world-feed-grid")?.scrollIntoView({ behavior: "smooth" })}>开始探索 <span>→</span></button>
          </div>
        </div>
        <div className="world-feed-hero-worlds" aria-label="精选实时世界">
          <img className="world-feed-hero-stack-art" src="/assets/world-feed/hero-stack-reference.png" alt="" aria-hidden="true" />
          {HERO_WORLDS.map((featured, index) => {
            const world = WORLD_FEED.find((item) => item.id === featured.id)!;
            return (
              <button
                className={`world-feed-featured-card world-feed-featured-card--${index + 1}`}
                key={world.id}
                onClick={() => openWorld(world)}
                type="button"
                aria-label={`打开世界：${world.title}`}
              >
                <img src={worldFeedCover(world)} alt="" style={{ objectPosition: world.coverPosition ?? "center" }} />
                <span className="world-feed-featured-live"><i />{index === 0 ? "LIVE" : world.status}</span>
                <span className="world-feed-featured-copy"><strong>{featured.title}</strong><small><i />{featured.rate}</small></span>
              </button>
            );
          })}
        </div>
      </section>

      <section className="world-feed-directory" aria-label="世界分类与继续探索">
        <div className="world-feed-channels">
          {HOME_CHANNELS.map((item) => <button type="button" key={item} className={channel === item ? "is-active" : ""} aria-pressed={channel === item} onClick={() => setChannel(item)}><WorldIcon name={channelIcon(item)} />{item}{item === "全部" && <small>{WORLD_FEED.length}</small>}</button>)}
        </div>
        <div className="world-feed-continue">
          <h2>继续探索</h2>
          <div>
            {CONTINUE_WORLDS.map((item) => {
              const world = WORLD_FEED.find((candidate) => candidate.id === item.id)!;
              return (
                <button type="button" key={world.id} onClick={() => openWorld(world)} aria-label={`继续探索：${world.title}`}>
                  <img src={worldFeedCover(world)} alt="" style={{ objectPosition: world.coverPosition ?? "center" }} />
                  <span><b>{world.title}</b><small>上次观看至 {item.progress}%</small><i><em style={{ width: `${item.progress}%` }} /></i></span>
                </button>
              );
            })}
          </div>
          <span className="world-feed-continue-next" aria-hidden="true">›</span>
        </div>
      </section>

      <section className="world-feed-results" id="world-feed-grid" aria-label="世界推荐流">
        <div className="world-feed-results-heading">
          <div><h2>{query ? `“${query}” 的世界` : channel === "全部" ? "此刻值得进入" : `${channel}世界`}</h2><p>找到 <strong>{worlds.length}</strong> 个世界 · 内容随世界状态实时更新</p></div>
          <div className="world-feed-sort">
            {SORTS.map((item) => <button type="button" key={item} className={sort === item ? "is-active" : ""} aria-pressed={sort === item} onClick={() => setSort(item)}>{item}</button>)}
            <span />
            <button type="button" aria-label="卡片网格视图"><WorldIcon name="grid" /></button>
          </div>
        </div>
        {worlds.length > 0 ? (
          <div className="world-feed-grid">
            {worlds.map((world, index) => (
              <article className="world-card" key={world.id} style={{ "--card-accent": world.accent, "--reveal-delay": `${Math.min(index, 9) * 35}ms` } as Record<string, string>}>
                <button type="button" className="world-card-entry" onClick={() => openWorld(world)} aria-label={`打开世界：${world.title}`}>
                  <span className="world-card-cover">
                  <img src={worldFeedCover(world)} alt="" style={{ objectPosition: world.coverPosition ?? "center" }} />
                  <span className="world-card-channel">{world.channel}</span>
                  <span className="world-card-status"><i />{world.status}</span>
                  <span className="world-card-overlay" aria-hidden="true"><b>打开世界</b><i>→</i></span>
                  <span className="world-card-metrics"><i><WorldIcon name="eye" />{world.heatLabel}</i><i><WorldIcon name="event" />{world.events}</i><b>{world.worldTime}</b></span>
                  </span>
                  <span className="world-card-body">
                    <strong className="world-card-title">{world.title}</strong>
                    <span className="world-card-signal"><i />{world.signal}</span>
                    <span className="world-card-summary">{world.summary}</span>
                    <span className="world-card-meta"><span style={{ background: world.accent }}>{world.keeper.slice(0, 1)}</span><i>{world.keeper}</i><b>{world.characters.toLocaleString()} 个活跃角色</b></span>
                  </span>
                </button>
              </article>
            ))}
          </div>
        ) : (
          <div className="world-feed-empty"><span>◎</span><h3>这片虚空里还没有世界</h3><p>换一个关键词，或清除筛选条件继续探索。</p><button type="button" onClick={resetFeed}>重置探索条件</button></div>
        )}
      </section>

      <footer className="world-feed-footer"><strong>万界 WORLDVERSE</strong><span>发现一个世界，然后进入它正在发生的此刻。</span></footer>
    </main>
  );
}

function channelIcon(channel: WorldChannel): "grid" | "fantasy" | "history" | "science" | "survival" | "nature" {
  if (channel === "幻想") return "fantasy";
  if (channel === "历史") return "history";
  if (channel === "科幻") return "science";
  if (channel === "生存") return "survival";
  if (channel === "自然") return "nature";
  return "grid";
}

function WorldIcon({ name }: { name: "search" | "grid" | "eye" | "event" | "fantasy" | "history" | "science" | "survival" | "nature" }) {
  const paths: Record<typeof name, any> = {
    search: <><circle cx="11" cy="11" r="6" /><path d="m16 16 4 4" /></>,
    grid: <><rect x="4" y="4" width="6" height="6" rx="1" /><rect x="14" y="4" width="6" height="6" rx="1" /><rect x="4" y="14" width="6" height="6" rx="1" /><rect x="14" y="14" width="6" height="6" rx="1" /></>,
    fantasy: <><path d="m12 3 1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7z" /><path d="m18 16 .8 2.2L21 19l-2.2.8L18 22l-.8-2.2L15 19l2.2-.8z" /></>,
    history: <><path d="M4 20h16M6 17h12M7 8h10v9H7zM5 8l7-5 7 5z" /></>,
    science: <><path d="m14 5 5 5-8 8-5-5zM12 7l5 5M5 19l4-4M15 4l2-2 5 5-2 2" /></>,
    survival: <path d="M12 21c-4-2-6-5-5-9 1-3 3-5 5-8 2 3 4 5 5 8 1 4-1 7-5 9Z" />,
    nature: <><path d="M20 4c-8 0-13 4-13 10 0 3 2 5 5 5 6 0 8-7 8-15Z" /><path d="M5 21c3-6 7-9 12-12" /></>,
    eye: <><path d="M2.5 12s3.5-5 9.5-5 9.5 5 9.5 5-3.5 5-9.5 5-9.5-5-9.5-5Z" /><circle cx="12" cy="12" r="2.5" /></>,
    event: <><rect x="4" y="5" width="16" height="14" rx="3" /><path d="M8 3v4M16 3v4M4 10h16M8 14h3" /></>,
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}
