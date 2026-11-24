import type { GroundedAction, ProjectionNode, ProjectionRelationship, ViewerProjection } from "../../types/contracts";

const SCENE_ID = "tribe_survival_world";
const MEMBER_COUNT = 56;

const HOME_ORGANIZATIONS = [
  ["ember-guard", "余烬守卫队", "北门防线", 49, 47],
  ["river-scouts", "河谷斥候营", "河谷与外圈侦察", 42, 39],
  ["stone-builders", "石木工匠营", "墙、塔、仓与避难屋", 50, 55],
  ["dawn-hunters", "晨猎队", "猎场与粮食", 39, 56],
  ["elder-council", "长老会", "粮食配给与迁徙判断", 52, 43],
  ["ash-shamans", "灰火祭司团", "恐慌、士气与记忆", 58, 48],
  ["granary-keepers", "粮仓看守组", "储粮、种子与冬季账本", 47, 61],
  ["fire-diplomats", "篝火使者团", "停战、贡礼与联盟", 60, 58],
] as const;

const EXTERNAL_FACTIONS = [
  ["black-hill-tribe", "黑山部落", "自主敌对部落", 72, 30],
  ["wolf-tooth-raiders", "狼牙掠夺队", "流动掠夺联盟", 78, 62],
  ["salt-road-caravan", "盐路商队", "中立贸易与情报", 25, 68],
] as const;

const KEY_CHARACTERS = [
  ["chieftain-aya", "首领阿娅", "部落最高意志的执行者", "把玩家旨意变成可执行的生存优先级", 50, 50],
  ["captain-tor", "守卫队长托尔", "北门守将", "把木墙、哨塔和民兵排成真正能拖住夜袭的防线", 48, 45],
  ["scout-nara", "斥候首领娜拉", "河谷眼线", "确认黑山部落是否只是饥饿，还是已经准备夜袭", 41, 37],
  ["shaman-ru", "祭司茹", "灰火记忆守护者", "安抚恐慌，让伤亡不把部落撕裂", 58, 47],
  ["builder-kun", "工匠大师昆", "塔墙与粮仓工程师", "在木材不足时决定先修墙还是先扩仓", 51, 57],
  ["young-chief-ren", "少壮派仁", "好战的年轻将领", "想主动出击，但必须面对粮食和伤员的代价", 56, 42],
] as const;

const ORGANIZATION_THOUGHTS = [
  "木墙缺口还在北门，夜里如果起雾，敌人会先摸这里。",
  "粮仓只够七天，猎队若越过河谷会触发黑山部落记忆。",
  "斥候回报不是命令敌人，而是让我们看清敌人会怎么来。",
  "国王视角只能落在我方组织，外部部落会按自己的恐惧和利益回应。",
  "修塔、巡逻、配给和谈判都在争同一批木材与人手。",
];

const ORGANIZATION_ACTIONS = [
  "加固北门木墙",
  "派两名斥候贴河前进",
  "削减夜间粮食配给",
  "记录黑山部落侦察痕迹",
  "召集工匠修补箭塔",
  "让祭司团安抚伤员家属",
];

export function createTribeSurvivalProjection(): ViewerProjection {
  const homeOrganizations = HOME_ORGANIZATIONS.map(([id, name, role, x, y], index) => ({
    id,
    name,
    role,
    type: "relationship_network",
    x,
    y,
    attributes: {
      viewer_scene: SCENE_ID,
      faction: "home_tribe",
      sovereign_command_scope: "home_tribe_only",
      survival_loop: survivalLoopForOrganization(id),
      resources: resourcesForOrganization(id),
      defense_rating: defenseRatingForOrganization(id),
      morale: moraleForOrganization(index),
      "signal:sovereign_scope": "我方组织可下旨",
      _memory_count: 3 + index,
      _memory_highlights: [
        {
          kind: "survival_memory",
          text: `${name}记住了上次夜袭后的执行差异。`,
          source: "tribe_survival_seed",
          tick: 2,
          importance: 0.68,
        },
      ],
    },
    members: createMembers(id, name, role, x, y, index),
  }));

  const externalOrganizations = EXTERNAL_FACTIONS.map(([id, name, role, x, y], index) => ({
    id,
    name,
    role,
    type: "relationship_network",
    x,
    y,
    attributes: {
      viewer_scene: SCENE_ID,
      faction: index === 2 ? "neutral_external" : "autonomous_enemy",
      sovereign_command_scope: "not_commandable",
      display_role: role,
      threat_level: index === 0 ? 0.82 : index === 1 ? 0.76 : 0.34,
      resources: index === 2 ? { salt: 12, rumor: 4 } : { warriors: 18 + index * 6, hunger: 7 - index },
      "signal:enemy_autonomy": "不可直接下旨",
      _memory_count: 4,
      _memory_highlights: [
        {
          kind: "external_memory",
          text: `${name}按自己的饥饿、仇恨和利益行动，不接受玩家直接命令。`,
          source: "tribe_survival_boundary",
          tick: 3,
          importance: 0.8,
        },
      ],
    },
    members: createExternalMembers(id, name, role, x, y),
  }));

  const organizations = [...homeOrganizations, ...externalOrganizations];
  const characters = KEY_CHARACTERS.map(([id, name, role, goal, x, y], index) => ({
    id,
    name,
    role,
    type: "key_character",
    x,
    y,
    attributes: {
      viewer_scene: SCENE_ID,
      faction: "home_tribe",
      display_role: role,
      loyalty: 0.74 + index * 0.03,
      morale: 0.66 + index * 0.04,
      resources: characterResourceState(id),
      "signal:commandable": "可接收我方旨意",
      _memory_count: 6 + index,
      _memory_highlights: [
        {
          kind: "key_character_memory",
          text: `${name}记得上一道旨意带来的收益和代价。`,
          source: "tribe_survival_key_character",
          tick: 4,
          importance: 0.77,
        },
      ],
    },
    key_character: {
      agent_layer: "key_character",
      status: keyCharacterStatus(id),
      goal,
      current_step: keyCharacterStep(id),
      thought_seed: `${name}正在把国王视角拆成部落内部可执行任务。`,
      salience_score: 0.88,
      influence_circle: influenceCircleForCharacter(id),
    },
  }));

  const relationships = createRelationships(organizations, characters);
  const thoughts = createThoughts(organizations, characters);
  const actions = createActions(organizations, characters);
  const groundedActions = createGroundedActions();

  return {
    summary: {
      world_id: "tribe-survival-interactive-world",
      tick: 6,
      scenario: "tribe_survival",
      node_count: organizations.reduce((total, organization) => total + 1 + (organization.members?.length || 0), 0) + characters.length,
      relationship_count: relationships.length,
      score: 96,
      viewer_scene: SCENE_ID,
      scene_title: "蛮荒世界",
      agent_total: organizations.reduce((total, organization) => total + 1 + (organization.members?.length || 0), 0) + characters.length,
      relationship_network_count: organizations.length,
      home_organization_count: homeOrganizations.length,
      external_faction_count: externalOrganizations.length,
      key_character_agent_count: characters.length,
      sovereign_scope: {
        label: "国王视角只作用于我方部落",
        commandable: "我方组织、将领、关键角色",
        not_commandable: "敌对部落、掠夺队、中立商队",
        rule: "敌人只能被侦察、外交、威慑、战斗和世界事件间接影响。",
      },
      survival_loops: ["food", "shelter", "defense", "scouting", "diplomacy", "memory", "morale"],
      domain_summary: {
        resources: { scarcity_nodes: 3, food_days: 7, wood_pressure: "high" },
        policies: { active_count: 2, rationing: "night_watch_priority" },
        risk: { score: 42, level: "watch" },
        domain_model_coverage: {
          by_domain: {
            resources: 8,
            defense: 7,
            scouting: 5,
            diplomacy: 3,
            memory: 11,
            morale: 8,
          },
          covered_domains: 6,
        },
      },
      domain_risk: { score: 42, level: "watch" },
      grounded_action_summary: {
        counts_by_type: {
          organization_decision: 2,
          production: 1,
          resource_transfer: 1,
          combat_attack: 1,
          logistics_transfer: 1,
          social_spread: 1,
        },
        grounded_action_class_count: 6,
        world_ecosystem_action_coverage: 67,
        world_ecosystem_actions_hit: [
          "organization_decision",
          "production",
          "resource_transfer",
          "combat_attack",
          "logistics_transfer",
          "social_spread",
        ],
        world_ecosystem_actions_missing: ["migration", "science_publish", "economic_exchange"],
      },
      run_health: {
        score: 96,
        penalty_count: 0,
        world_errors: 0,
        governance_rejections: 0,
        domain_state_issues: 0,
        unmatched_pressures: 1,
      },
      governance_notice: {
        label: "娱乐化生存沙盒",
        scenario: "蛮荒世界",
        message: "国王视角只对我方部落下旨；敌方部落是自主 AI 势力，只能通过侦察、外交、威慑、战斗和世界事件间接影响。",
        risk_level: "low",
      },
      memory_maintenance: {
        consolidated_nodes: 6,
        summary_count: 2,
        forgotten_count: 0,
        recent: [
          {
            node_id: "ember-guard",
            tick: 6,
            kind: "memory_summary",
            text: "北门夜袭记忆被压缩为防线优先级。",
            memory_count: 8,
            forgotten_count: 0,
            keywords: ["北门", "夜袭", "防线"],
          },
        ],
      },
    } as ViewerProjection["summary"],
    organizations,
    characters,
    people: [],
    relationships,
    thoughts,
    actions,
    grounded_actions: groundedActions,
    action_visuals: groundedActions.map((action, index) => ({
      feedback_sequence: Number(action.sequence ?? index + 1),
      sequence: Number(action.sequence ?? index + 1),
      tick: Number(action.tick ?? 0),
      actor_id: action.actor_id,
      actor_type: action.actor_type,
      actor_name: action.actor_name,
      action: action.action,
      label: action.action.replace(/_/g, " "),
      summary: action.summary,
      source: action.source,
      ttl: 2.4,
      targets: action.targets || [],
      effects: action.effects || [],
    })),
    impact_ripples: [
      { source: "chieftain-aya", target: "ember-guard", label: "旨意转译为巡逻压力", salience: 0.78 },
      { source: "scout-nara", target: "black-hill-tribe", label: "侦察发现饥饿压力", salience: 0.7 },
    ],
    key_character_trajectories: [],
    ai_traces: [
      {
        tick: 6,
        node_id: "captain-tor",
        matched: true,
        thought: { text: "北门防线薄，但木材也被粮仓占用。" },
        pressure: { rule: "organization_decision", weight: 0.82 },
        action: { action: "organization_decision", summary: "守卫队优先加固北门。" },
      },
      {
        tick: 6,
        node_id: "black-hill-tribe",
        matched: false,
        thought: { text: "敌方自主评估是否夜袭。" },
        pressure: { rule: "raid_pressure", weight: 0.76 },
        action: { action: "pending", summary: "等待规则层与侦察结果。" },
      },
    ],
  };
}

function createMembers(networkId: string, networkName: string, role: string, centerX: number, centerY: number, groupIndex: number): ProjectionNode[] {
  return Array.from({ length: MEMBER_COUNT }, (_, index) => {
    const angle = (index / MEMBER_COUNT) * Math.PI * 2;
    const ring = index < 8 ? 3.2 : 5.8;
    return {
      id: `${networkId}-member-${String(index + 1).padStart(2, "0")}`,
      name: `${networkName}${memberRole(networkId, index)}${index + 1}`,
      role: memberRole(networkId, index),
      type: "organization_member",
      x: clampPercent(centerX + Math.cos(angle) * ring + (groupIndex % 3 - 1) * 0.7),
      y: clampPercent(centerY + Math.sin(angle) * ring),
      attributes: {
        viewer_scene: SCENE_ID,
        parent_network: networkId,
        faction: "home_tribe",
        role,
        ai_controlled: true,
        sovereign_command_scope: "home_tribe_only",
        resources: resourcesForMember(networkId, index),
        "signal:morale": index % 4 === 0 ? "shaken" : "steady",
      },
    };
  });
}

function createExternalMembers(networkId: string, networkName: string, role: string, centerX: number, centerY: number): ProjectionNode[] {
  return Array.from({ length: MEMBER_COUNT }, (_, index) => {
    const angle = (index / MEMBER_COUNT) * Math.PI * 2;
    const ring = index < 18 ? 2.8 : index < 36 ? 5.2 : 7.4;
    return {
      id: `${networkId}-agent-${String(index + 1).padStart(2, "0")}`,
      name: `${networkName}${index + 1}`,
      role: index % 3 === 0 ? "侦察者" : index % 3 === 1 ? "战士" : "谈判者",
      type: "organization_member",
      x: clampPercent(centerX + Math.cos(angle) * ring),
      y: clampPercent(centerY + Math.sin(angle) * ring),
      attributes: {
        viewer_scene: SCENE_ID,
        parent_network: networkId,
        display_role: role,
        faction: networkId === "salt-road-caravan" ? "neutral_external" : "autonomous_enemy",
        sovereign_command_scope: "not_commandable",
        ai_controlled: true,
        resources: networkId === "salt-road-caravan" ? { salt: 2, rumor: 1 } : { hunger: 3, weapons: 1 },
        "signal:enemy_autonomy": "不可直接下旨",
      },
    };
  });
}

function createRelationships(organizations: ProjectionNode[], characters: ProjectionNode[]): ProjectionRelationship[] {
  const links: ProjectionRelationship[] = [];
  for (const organization of organizations) {
    for (const member of organization.members || []) {
      links.push({ source: member.id, target: organization.id, type: "member_of", weight: 0.66 });
    }
  }
  const characterNetworks: Record<string, string> = {
    "chieftain-aya": "elder-council",
    "captain-tor": "ember-guard",
    "scout-nara": "river-scouts",
    "shaman-ru": "ash-shamans",
    "builder-kun": "stone-builders",
    "young-chief-ren": "ember-guard",
  };
  for (const character of characters) {
    links.push({
      source: character.id,
      target: characterNetworks[character.id] || "elder-council",
      type: "command_influence",
      weight: 0.86,
      metadata: { status: "home command chain" },
    });
  }
  links.push({ source: "black-hill-tribe", target: "river-scouts", type: "scouting_tension", weight: 0.82, metadata: { status: "autonomous enemy pressure" } });
  links.push({ source: "wolf-tooth-raiders", target: "ember-guard", type: "raid_pressure", weight: 0.88, metadata: { status: "enemy not commandable" } });
  links.push({ source: "salt-road-caravan", target: "fire-diplomats", type: "trade_contact", weight: 0.62, metadata: { status: "neutral leverage" } });
  links.push({ source: "granary-keepers", target: "dawn-hunters", type: "food_dependency", weight: 0.76 });
  links.push({ source: "stone-builders", target: "ember-guard", type: "defense_dependency", weight: 0.8 });
  return links;
}

function createThoughts(organizations: ProjectionNode[], characters: ProjectionNode[]) {
  const organizationThoughts = organizations.flatMap((organization, organizationIndex) => {
    const members = organization.members || [];
    return members.slice(0, 40).map((member, memberIndex) => ({
      node_id: member.id,
      text: ORGANIZATION_THOUGHTS[(organizationIndex + memberIndex) % ORGANIZATION_THOUGHTS.length],
      delay: (1.6 + organizationIndex * 0.8 + memberIndex * 1.35) % 60,
      ttl: memberIndex < 10 ? 4 : 6,
      salience: memberIndex < 10 ? 0.76 : 0.58,
      origin: memberIndex < 10 ? "active_node" : "ripple_response",
      ripple_from: memberIndex < 10 ? undefined : members[(memberIndex - 10) % 10]?.id,
      tick: 6,
    }));
  });
  const characterThoughts = characters.map((character, index) => ({
    node_id: character.id,
    text: `${character.name}：${String(character.key_character?.goal || "守住部落生存线")}。`,
    delay: 0.5 + index * 2.1,
    ttl: 4.2,
    salience: 0.82,
    origin: "tribe_survival_key_character",
    tick: 6,
  }));
  return [...characterThoughts, ...organizationThoughts];
}

function createActions(organizations: ProjectionNode[], characters: ProjectionNode[]) {
  const organizationActions = organizations.slice(0, HOME_ORGANIZATIONS.length).map((organization, index) => ({
    node_id: organization.members?.[index % MEMBER_COUNT]?.id || organization.id,
    text: `${organization.name}：${ORGANIZATION_ACTIONS[index % ORGANIZATION_ACTIONS.length]}`,
    delay: 1.4 + index * 1.18,
    ttl: 3.2,
    salience: 0.62,
    origin: "tribe_survival_behavior_text",
    tick: 6,
  }));
  const externalActions = [
    {
      node_id: "black-hill-tribe-agent-01",
      text: "黑山部落自主派出饥饿斥候",
      delay: 5.4,
      ttl: 3.8,
      salience: 0.78,
      origin: "tribe_survival_enemy_autonomy",
      tick: 6,
    },
    {
      node_id: "wolf-tooth-raiders-agent-03",
      text: "狼牙掠夺队绕开北门火光",
      delay: 6.8,
      ttl: 3.8,
      salience: 0.74,
      origin: "tribe_survival_enemy_autonomy",
      tick: 6,
    },
  ];
  const characterActions = characters.slice(0, 3).map((character, index) => ({
    node_id: character.id,
    text: `${character.name}把旨意转交给${HOME_ORGANIZATIONS[index][1]}`,
    delay: 2.3 + index * 1.45,
    ttl: 3.4,
    salience: 0.7,
    origin: "tribe_survival_sovereign_scope",
    tick: 6,
  }));
  return [...organizationActions, ...externalActions, ...characterActions];
}

function createGroundedActions(): GroundedAction[] {
  return [
    groundedAction(1, "organization_decision", "首领阿娅将国王旨意限定为我方部落内部任务。", "chieftain-aya", "首领阿娅", "elder-council", "长老会", [
      effect("policy_state", "下旨边界", "国王视角只对我方组织生效"),
    ]),
    groundedAction(2, "production", "工匠营优先修补北门箭塔，暂缓扩建粮仓。", "stone-builders", "石木工匠营", "ember-guard", "余烬守卫队", [
      effect("node_attribute_delta", "防御", "+2 defense"),
      effect("resource_delta", "木材", "-6 wood"),
    ]),
    groundedAction(3, "resource_transfer", "猎队把两日肉干转给守卫夜哨。", "dawn-hunters", "晨猎队", "ember-guard", "余烬守卫队", [
      effect("resource_transfer", "粮食", "2 food"),
    ]),
    groundedAction(4, "logistics_transfer", "斥候营把黑山足迹送回长老会。", "river-scouts", "河谷斥候营", "elder-council", "长老会", [
      effect("memory_add", "敌情记忆", "black hill scouts seen"),
    ]),
    groundedAction(5, "combat_attack", "狼牙掠夺队试探北门，被哨塔火光迫退。", "wolf-tooth-raiders", "狼牙掠夺队", "ember-guard", "余烬守卫队", [
      effect("health_delta", "试探伤亡", "-1 raider morale"),
    ]),
    groundedAction(6, "social_spread", "祭司团把夜袭恐慌改写成守夜仪式。", "ash-shamans", "灰火祭司团", "granary-keepers", "粮仓看守组", [
      effect("memory_add", "士气记忆", "panic reframed into ritual"),
    ]),
  ];
}

function groundedAction(
  sequence: number,
  action: string,
  summary: string,
  actorId: string,
  actorName: string,
  targetId: string,
  targetName: string,
  effects: GroundedAction["effects"],
): GroundedAction {
  return {
    tick: 6,
    sequence,
    action,
    summary,
    source: "tribe_survival_seed",
    actor_type: "node",
    actor_id: actorId,
    actor_name: actorName,
    targets: [{ id: targetId, name: targetName, type: "node" }],
    decision: {
      rule: action,
      reason: "survival pressure converted into grounded scene event",
      score: 0.72 + sequence * 0.03,
      candidate_count: 3,
    },
    effect_count: effects?.length || 0,
    effects,
  };
}

function effect(type: string, label: string, value: string): NonNullable<GroundedAction["effects"]>[number] {
  return {
    type,
    label,
    target: { id: "tribe-survival-world", name: value },
    change: { kind: type, label, field: value },
  };
}

function influenceCircleForCharacter(id: string) {
  const map: Record<string, string[]> = {
    "chieftain-aya": ["elder-council-member-01", "ember-guard-member-01", "stone-builders-member-01"],
    "captain-tor": ["ember-guard-member-02", "ember-guard-member-05", "stone-builders-member-03"],
    "scout-nara": ["river-scouts-member-01", "river-scouts-member-07", "black-hill-tribe-agent-01"],
    "shaman-ru": ["ash-shamans-member-01", "granary-keepers-member-02", "elder-council-member-04"],
    "builder-kun": ["stone-builders-member-02", "granary-keepers-member-03", "ember-guard-member-06"],
    "young-chief-ren": ["ember-guard-member-08", "dawn-hunters-member-04", "wolf-tooth-raiders-agent-03"],
  };
  return (map[id] || []).map((nodeId) => ({
    node_id: nodeId,
    role: "influence",
    reason: "key character pressure reaches this node",
  }));
}

function survivalLoopForOrganization(id: string) {
  if (id.includes("guard")) return "defense";
  if (id.includes("scout")) return "scouting";
  if (id.includes("builder")) return "shelter";
  if (id.includes("hunter") || id.includes("granary")) return "food";
  if (id.includes("shaman")) return "morale";
  if (id.includes("diplomat")) return "diplomacy";
  return "memory";
}

function resourcesForOrganization(id: string) {
  if (id.includes("guard")) return { spears: 14, torches: 8 };
  if (id.includes("scout")) return { scouts: 9, maps: 3 };
  if (id.includes("builder")) return { wood: 18, stone: 7 };
  if (id.includes("hunter")) return { food: 11, arrows: 15 };
  if (id.includes("granary")) return { food: 38, seed: 12 };
  if (id.includes("diplomat")) return { gifts: 4, promises: 2 };
  return { trust: 8, memory: 6 };
}

function resourcesForMember(networkId: string, index: number) {
  const base = resourcesForOrganization(networkId);
  const key = Object.keys(base)[index % Object.keys(base).length];
  return { [key]: 1 + (index % 3) };
}

function defenseRatingForOrganization(id: string) {
  if (id.includes("guard")) return 8;
  if (id.includes("builder")) return 6;
  if (id.includes("scout")) return 5;
  return 3;
}

function moraleForOrganization(index: number) {
  return Number((0.58 + (index % 5) * 0.07).toFixed(2));
}

function characterResourceState(id: string) {
  if (id.includes("captain")) return { authority: 7, militia: 16 };
  if (id.includes("scout")) return { maps: 4, warnings: 3 };
  if (id.includes("builder")) return { wood: 8, repair_plans: 5 };
  if (id.includes("shaman")) return { trust: 9, rituals: 2 };
  return { authority: 8, promises: 3 };
}

function keyCharacterStatus(id: string) {
  if (id.includes("young")) return "想主动出击";
  if (id.includes("captain")) return "守住北门";
  if (id.includes("scout")) return "追踪敌方自主行动";
  if (id.includes("builder")) return "权衡木材";
  if (id.includes("shaman")) return "压住恐慌";
  return "解释国王旨意";
}

function keyCharacterStep(id: string) {
  if (id.includes("scout")) return "把敌方行动转译为可验证情报";
  if (id.includes("builder")) return "计算先修塔还是扩仓";
  if (id.includes("captain")) return "安排北门双层巡逻";
  if (id.includes("young")) return "请求一次有限反击";
  return "分配组织优先级";
}

function memberRole(networkId: string, index: number) {
  if (networkId.includes("guard")) return index % 3 === 0 ? "哨兵" : index % 3 === 1 ? "盾手" : "弓手";
  if (networkId.includes("scout")) return index % 3 === 0 ? "足迹师" : index % 3 === 1 ? "河谷眼线" : "信使";
  if (networkId.includes("builder")) return index % 3 === 0 ? "木匠" : index % 3 === 1 ? "石匠" : "塔工";
  if (networkId.includes("hunter")) return index % 3 === 0 ? "猎人" : index % 3 === 1 ? "剥皮手" : "弓箭手";
  if (networkId.includes("granary")) return index % 3 === 0 ? "账房" : index % 3 === 1 ? "仓卫" : "种子看守";
  if (networkId.includes("shaman")) return index % 3 === 0 ? "祭司" : index % 3 === 1 ? "医者" : "梦兆记录员";
  if (networkId.includes("diplomat")) return index % 3 === 0 ? "使者" : index % 3 === 1 ? "译者" : "贡礼看守";
  return index % 2 === 0 ? "长老" : "记录员";
}

function clampPercent(value: number) {
  return Math.max(8, Math.min(92, Number(value.toFixed(2))));
}
