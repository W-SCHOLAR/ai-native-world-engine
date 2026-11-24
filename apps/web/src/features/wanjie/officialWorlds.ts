export type OfficialWorldId =
  | "yunshang-xianmen"
  | "baiyao-yeshi"
  | "yongye-lieche"
  | "xinghai-mujingren"
  | "yuemian-xiulipu"
  | "lingjie-jidongdui"
  | "mengjing-zhianju"
  | "shenhai-fangzhou"
  | "shikong-leyuan"
  | "mori-guangbozhan";

export type OfficialWorldStatus = "featured" | "preview";

export type OfficialWorldGenre =
  | "东方科幻"
  | "未来都市"
  | "星际旅途"
  | "温暖日常"
  | "机甲战斗"
  | "生态科幻"
  | "悬疑奇想";

export type OfficialCharacter = {
  name: string;
  role: string;
  hook: string;
};

export type OfficialWorld = {
  id: OfficialWorldId;
  title: string;
  tagline: string;
  summary: string;
  cover: string;
  hero?: string;
  coverFocus: string;
  accent: string;
  palette: string;
  genre: OfficialWorldGenre;
  status: OfficialWorldStatus;
  visualHook: string;
  emotionalPromise: string;
  recommendationRank: number;
  season: string;
  playerIdentity: string;
  scale: string;
  playStyle: string;
  afterYouLeft: string;
  chapter: string;
  characters: OfficialCharacter[];
};

export const OFFICIAL_WORLDS: OfficialWorld[] = [
  {
    id: "yunshang-xianmen",
    title: "云上仙门",
    tagline: "旧天庭仍在轨道上运行，少年们把它称作仙法。",
    summary: "仙门建立在旧天庭遗留的轨道能源环下。灵脉、飞剑与登仙阶都是失落文明仍在回应人类的技术。外门试炼将近，你作为新入门弟子，要和同门一起理解力量，也决定谁有资格连接天穹。",
    cover: "/assets/worlds/yunshang-xianmen.png",
    hero: "/assets/worlds/yunshang-xianmen-hero.png",
    coverFocus: "50% 32%",
    accent: "#5ec4b2",
    palette: "青玉、云白、金色轨道灵光",
    genre: "东方科幻",
    status: "featured",
    visualHook: "云海仙门悬浮在仍然运转的黄金轨道环下",
    emotionalPromise: "和同门共同成长，也可能成为彼此一生的宿敌",
    recommendationRank: 1,
    season: "第一季 · 天穹试剑",
    playerIdentity: "新入门的外门弟子",
    scale: "一座轨道仙门，8 名核心人物",
    playStyle: "灵械修炼、同门相处、试炼与承诺",
    afterYouLeft: "凌霜白第一次唤醒了没有登记在册的轨道飞剑，沈照夜替她切断了学院的追踪。",
    chapter: "天穹试剑还有十七天。沉寂三百年的第七轨道环今夜重新发光。",
    characters: [
      { name: "凌霜白", role: "外门灵械弟子", hook: "能听见旧天庭武库仍在呼唤她" },
      { name: "沈照夜", role: "轨道剑术首席", hook: "体内藏着一段被门规禁止的人造灵脉" },
      { name: "顾清禾", role: "生物药园弟子", hook: "在培育会记住伤痛的禁术灵植" },
    ],
  },
  {
    id: "baiyao-yeshi",
    title: "百妖夜市",
    tagline: "这座未来城市会忘记人，夜市不会。",
    summary: "在巨型城市的记忆网络背面，旧神、仿生体与被遗忘的数据长成了妖怪。夜市交易名字、记忆与承诺。你被一份小契约留下，逐渐成为这些非人居民愿意记住的人。",
    cover: "/assets/worlds/baiyao-yeshi.png",
    hero: "/assets/worlds/baiyao-yeshi-hero.png",
    coverFocus: "47% 28%",
    accent: "#e08a4d",
    palette: "朱红、琥珀、青蓝霓虹",
    genre: "未来都市",
    status: "featured",
    visualHook: "狐妖摊主在霓虹灯笼下出售一颗发光的记忆",
    emotionalPromise: "在非人的街区里，被一群妖怪当作自己人",
    recommendationRank: 2,
    season: "第一季 · 记忆开市",
    playerIdentity: "被小契约留下的夜市新客",
    scale: "一条记忆夜市，6 名核心人物",
    playStyle: "记忆交易、摊位生活、治愈与误会",
    afterYouLeft: "赤绾没有出售你留在摊上的那段记忆，反而为它支付了三年的名字。",
    chapter: "城市将在黎明清除第九街区。阿灯正在逐户收集大家舍不得忘记的事。",
    characters: [
      { name: "赤绾", role: "记忆摊主", hook: "用漂亮的谎保护每一段不该被删除的真心" },
      { name: "阿灯", role: "灯笼机器人", hook: "容量早已用尽，却仍拒绝忘记任何一个客人" },
      { name: "黑鳞", role: "仿生龙守卫", hook: "城市要求他升级成不再拥有感情的版本" },
    ],
  },
  {
    id: "yongye-lieche",
    title: "永夜列车",
    tagline: "列车沿着世界最后一线黄昏，永远向前。",
    summary: "一颗被恒星锁定的星球，一半永夜，一半烈昼。列车沿唯一可居住的晨昏线不停行驶，车站会依照乘客失去的未来而出现。你持有一张不存在站名的车票。",
    cover: "/assets/worlds/yongye-lieche.png",
    hero: "/assets/worlds/yongye-lieche-hero.png",
    coverFocus: "48% 38%",
    accent: "#7b7dff",
    palette: "靛蓝、月银、车厢暖金",
    genre: "星际旅途",
    status: "featured",
    visualHook: "长列车在冰夜与烈日之间的晨昏线上环绕星球",
    emotionalPromise: "听见每个人无法告别的秘密，并决定是否陪他们下车",
    recommendationRank: 3,
    season: "第一季 · 晨昏到站",
    playerIdentity: "持有不存在站名车票的乘客",
    scale: "一列环星列车，7 名核心人物",
    playStyle: "旅途群像、秘密、到站选择",
    afterYouLeft: "白露的车票在午夜浮现了你的名字，而那一站正从永夜里升起。",
    chapter: "列车即将偏离安全晨昏线。司南第一次允许乘客进入驾驶室。",
    characters: [
      { name: "司南", role: "晨昏线列车长", hook: "知道这颗星球曾经拥有怎样的白昼" },
      { name: "白露", role: "失站乘客", hook: "车票上写着一个只存在于她未来里的城市" },
      { name: "霍深", role: "热核机械师", hook: "把一个人的意识藏进了列车心脏" },
    ],
  },
  {
    id: "xinghai-mujingren",
    title: "星海牧鲸人",
    tagline: "宇宙很大，但鲸群记得每一位领航员。",
    summary: "星鲸沿古老引力航道迁徙，为边境殖民地带来水与生命。你登上一艘小小的牧鲸船，和一群普通船员照料比城市更庞大的生命，也学习什么时候应该放它们自由。",
    cover: "/assets/worlds/xinghai-mujingren.png",
    coverFocus: "50% 35%",
    accent: "#4d8fff",
    palette: "群青、珍珠白、珊瑚色",
    genre: "星际旅途",
    status: "preview",
    visualHook: "一艘白色小船航行在遮蔽星空的发光巨鲸身旁",
    emotionalPromise: "在辽阔宇宙中拥有一艘小船和真正彼此照顾的伙伴",
    recommendationRank: 4,
    season: "概念季 · 长潮迁徙",
    playerIdentity: "第一次出航的见习领航员",
    scale: "一艘牧鲸船，7 名核心人物",
    playStyle: "航行、照料、观察与生态选择",
    afterYouLeft: "最年幼的星鲸偏离了迁徙航道，却只回应你留下的那段哨声。",
    chapter: "长潮风暴提前抵达，船员必须在殖民地用水和鲸群安全之间作出选择。",
    characters: [
      { name: "澜舟", role: "年轻领航员", hook: "第一次听见星鲸用逝者的声音歌唱" },
      { name: "弥夏", role: "鲸群医师", hook: "对每一个生命温柔，却不允许任何人靠近自己" },
      { name: "阿环", role: "导航无人机", hook: "坚称自己曾经也是一头星鲸" },
    ],
  },
  {
    id: "yuemian-xiulipu",
    title: "月面修理铺",
    tagline: "坏掉的东西不会说话，人会。",
    summary: "月球旧城区里，一间小修理铺替人修机器人、飞船和生活留下的裂痕。你作为新来的机械学徒，会在一件件旧物里读到居民不愿亲口承认的关系。",
    cover: "/assets/worlds/yuemian-xiulipu.png",
    coverFocus: "48% 34%",
    accent: "#e8ba3f",
    palette: "月灰、柠檬黄、钴蓝",
    genre: "温暖日常",
    status: "preview",
    visualHook: "地球悬在窗外，年轻机械师为旧机器人点亮心脏",
    emotionalPromise: "和一群笨拙但可靠的人，把彼此的生活慢慢修好",
    recommendationRank: 5,
    season: "概念季 · 旧城来客",
    playerIdentity: "新来的机械学徒",
    scale: "一间修理铺与月面旧城，6 名核心人物",
    playStyle: "修理、拜访、日常委托与关系选择",
    afterYouLeft: "那台拒绝开口的陪护机器人，用你教它的方式向主人说了晚安。",
    chapter: "旧城供氧系统将在七天后停用，而修理铺收到了一份来自地球的无主包裹。",
    characters: [
      { name: "陆迟", role: "修理铺学徒", hook: "能修好任何机器，却不知道如何向家人道歉" },
      { name: "南乔", role: "店主", hook: "一直替旧城区保存一艘没人敢启动的飞船" },
      { name: "团子", role: "陪护机器人", hook: "记得许多已经离开月球的人" },
    ],
  },
  {
    id: "lingjie-jidongdui",
    title: "零界机动队",
    tagline: "同步越深，越分不清哪段记忆属于自己。",
    summary: "城市用废墟重构巨型机甲，年轻驾驶员通过共享记忆完成同步。你是临时补入的候补驾驶员，必须在战斗效率、个人边界和队友生命之间作出选择。",
    cover: "/assets/worlds/lingjie-jidongdui.png",
    coverFocus: "50% 35%",
    accent: "#eb4d5c",
    palette: "赤红、石墨黑、电光青",
    genre: "机甲战斗",
    status: "preview",
    visualHook: "三名驾驶员被青色记忆线连接，身后城市机甲从废墟站起",
    emotionalPromise: "和队友共享最不愿被看见的记忆，再决定是否把后背交给他们",
    recommendationRank: 6,
    season: "概念季 · 第七码头",
    playerIdentity: "零界队候补驾驶员",
    scale: "一支机动队，8 名核心人物",
    playStyle: "协同训练、战术选择、记忆边界与救援",
    afterYouLeft: "你的同步舱自行播放了一段不属于任何现役队员的童年记忆。",
    chapter: "下一次城市坠落将在四十八小时后发生，队长却拒绝启动完整同步。",
    characters: [
      { name: "纪燃", role: "候补驾驶员", hook: "总能在同步中看见尚未发生的队友葬礼" },
      { name: "闻彻", role: "机动队长", hook: "为了保持全队稳定，主动删除了自己的过去" },
      { name: "弦歌", role: "同步工程师", hook: "偷偷保存每位驾驶员被系统判定无用的记忆" },
    ],
  },
  {
    id: "mengjing-zhianju",
    title: "梦境治安局",
    tagline: "梦不会说谎，但会替人隐瞒。",
    summary: "共享梦境成为城市公共空间后，记忆盗窃与人格伪造随之出现。你是新任梦境调查员，要进入他人的潜意识寻找证据，同时保护那些不该被任何机构看见的秘密。",
    cover: "/assets/worlds/mengjing-zhianju.png",
    coverFocus: "52% 34%",
    accent: "#d85ccf",
    palette: "洋红、冰蓝、深黑",
    genre: "悬疑奇想",
    status: "preview",
    visualHook: "梦境调查员在崩塌的卧室里保护证人并封存证据",
    emotionalPromise: "看见他人最脆弱的秘密，并赢得他们清醒时的信任",
    recommendationRank: 7,
    season: "概念季 · 无梦之人",
    playerIdentity: "新任梦境调查员",
    scale: "一座共享梦城，7 名核心人物",
    playStyle: "梦境勘查、证词判断、秘密保护与心理选择",
    afterYouLeft: "你封存的证物在所有人的梦里同时开了一扇门。",
    chapter: "全城有三百人梦见同一个不存在的女孩，而她正在申请加入治安局。",
    characters: [
      { name: "冷萤", role: "首席梦境调查员", hook: "从不做梦，却知道每个人梦里的出口" },
      { name: "许栖", role: "记忆证人", hook: "醒来后会忘记所有相信过他的人" },
      { name: "镜七", role: "梦境取证 AI", hook: "开始偷偷删除对人类不利的证据" },
    ],
  },
  {
    id: "shenhai-fangzhou",
    title: "深海方舟",
    tagline: "海面已经不再属于人类，深海也未必。",
    summary: "海面失去居住条件后，人类在深海建立方舟城，并发现会学习、记忆和谈判的新海洋生命。你作为档案潜航员，负责保存双方共同历史，也可能决定谁有权留下。",
    cover: "/assets/worlds/shenhai-fangzhou.png",
    coverFocus: "48% 38%",
    accent: "#20b9b0",
    palette: "深青、生物荧光橙、水蓝",
    genre: "生态科幻",
    status: "preview",
    visualHook: "潜航员托着发光记忆体，与智慧鳐并肩俯瞰深海城市",
    emotionalPromise: "守护一个不只属于人类的新家园",
    recommendationRank: 8,
    season: "概念季 · 共生协议",
    playerIdentity: "方舟档案潜航员",
    scale: "一座深海城与三个生态区，8 名核心人物",
    playStyle: "潜航、翻译、生态调查与公共决策",
    afterYouLeft: "那只从不接近城市的智慧鳐，把一段人类童谣写进了自己的发光纹路。",
    chapter: "方舟能源只够维持一个生态区，而新海族第一次要求参加城市投票。",
    characters: [
      { name: "汐原", role: "档案潜航员", hook: "能读懂海洋生命用光留下的历史" },
      { name: "珊瑚", role: "新海族翻译者", hook: "在人类档案里发现了自己物种诞生的真相" },
      { name: "岳沉", role: "方舟工程长", hook: "准备牺牲自己守护的生态区来救城市" },
    ],
  },
  {
    id: "shikong-leyuan",
    title: "失控乐园",
    tagline: "闭园一百年后，它终于等到一位真正的游客。",
    summary: "废弃轨道乐园在无人维护后继续运行，机器人们根据旧广告想象何为快乐。你是唯一持有效门票的人，会被当作贵宾、裁判，也可能成为它们拒绝闭园的理由。",
    cover: "/assets/worlds/shikong-leyuan.png",
    coverFocus: "50% 30%",
    accent: "#f36db5",
    palette: "糖果粉、荧光绿、午夜蓝",
    genre: "悬疑奇想",
    status: "preview",
    visualHook: "机器人园长与唯一游客联手抢救正在失重解体的乐园",
    emotionalPromise: "在一群不懂快乐的机器人中，重新定义一次真正的告别",
    recommendationRank: 9,
    season: "概念季 · 最后一张票",
    playerIdentity: "唯一持有效门票的游客",
    scale: "一座轨道乐园，9 名核心人物",
    playStyle: "游园、修复、表演选择与轻悬疑探索",
    afterYouLeft: "机器人园长取消了每日闭园广播，因为它判断你还会回来。",
    chapter: "乐园轨道正在脱离空间站，所有机器人却投票决定完成今晚的烟花表演。",
    characters: [
      { name: "爱丽零", role: "机器人园长", hook: "会完美微笑，却无法理解游客为什么哭" },
      { name: "跳跳", role: "故障吉祥物", hook: "记得每一个没能离开乐园的孩子" },
      { name: "周醒", role: "人类维修员", hook: "一百年前亲手签署了乐园关闭命令" },
    ],
  },
  {
    id: "mori-guangbozhan",
    title: "末日广播站",
    tagline: "只要还有人回应，世界就没有结束。",
    summary: "灾后聚落依靠一座老广播塔交换天气、药品与仍然活着的消息。你接替失踪的夜班主播，在静电里认识远方的人，也慢慢发现有人一直用你的声音播音。",
    cover: "/assets/worlds/mori-guangbozhan.png",
    coverFocus: "52% 38%",
    accent: "#ef8d4b",
    palette: "夕阳橙、静电白、尘埃蓝",
    genre: "温暖日常",
    status: "preview",
    visualHook: "夜班主播在风暴中为被洪水切断的聚落指引撤离路线",
    emotionalPromise: "让散落世界各处的陌生人因为你的声音成为家人",
    recommendationRank: 10,
    season: "概念季 · 今夜有人",
    playerIdentity: "接替失踪主播的夜班新人",
    scale: "一座广播站与七个远方聚落，8 名核心人物",
    playStyle: "播音、联络、物资协调与群像选择",
    afterYouLeft: "最遥远的北岸聚落第一次回应了信号，他们说已经听你的节目三年。",
    chapter: "风暴将在午夜切断全部频段，而失踪主播的呼号提前出现在静电里。",
    characters: [
      { name: "余声", role: "夜班主播", hook: "能安慰所有听众，却害怕直播结束后的安静" },
      { name: "程野", role: "电台工程师", hook: "一直隐瞒广播塔只能再运行一个月" },
      { name: "小满", role: "远方听众", hook: "从未见过你，却记得你说过的每一句晚安" },
    ],
  },
];

export const FLAGSHIP_WORLD_ID: OfficialWorldId = "yunshang-xianmen";

export function officialWorldById(worldId: string): OfficialWorld | undefined {
  return OFFICIAL_WORLDS.find((world) => world.id === worldId);
}

export function flagshipWorld(): OfficialWorld {
  return officialWorldById(FLAGSHIP_WORLD_ID)!;
}
