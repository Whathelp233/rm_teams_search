const impactScore = {
  opening: 58,
  outpost: 80,
  transition: 88,
  siege: 100,
  defense: 62,
  terminal: 72,
}

const rules = {
  opening_forward: {
    title: '阻止对方双车越过中线建立前场', capability: ['spatial', 'defense'], roles: ['哨兵', '步兵'], zone: '己方前场 / 对方主要通行路线',
    actions: ['在对方通常越过中线前，让哨兵与一台步兵分别覆盖前哨站正面和侧向通行路线', '正面单位负责阻止继续推进，机动步兵攻击后续跟进单位，避免两车同时取得射界', '对方只剩一台机器人处于己方半场后，再恢复中央区域与增益点争夺'],
    success: '对方连续10秒无法保持两台地面机器人位于己方半场', exit: '己方前哨站停止扣血，且对方主要单位退回中央区域', fallback: '收缩到前哨站与基地之间，优先保留基地回防路线', risk: '两台防守单位同时追出，会让另一条通行路线和前哨站攻击方向失去保护',
  },
  opening_outpost: {
    title: '推迟己方前哨站首次扣血', capability: ['defense', 'spatial'], roles: ['哨兵', '步兵'], zone: '己方前场 / 前哨站攻击方向',
    actions: ['在对方历史最早首伤时间前，完成前哨站正面与侧向的交叉防守', '保留一台机动步兵驱离持续发弹位置，不追击未威胁前哨站的低价值目标', '前哨站首次扣血后观察10秒：若仍连续受击则增援，否则继续控制中央区域'],
    success: '对方打出前哨站首伤的时间晚于其历史75分位', exit: '前哨站连续10秒不再扣血，或对方转向能量机关/增益点', fallback: '放弃外线换血，守住前哨站至基地的回防路线', risk: '所有单位集中于正面时，侧路与空中支援可能绕开防线',
  },
  rune_outpost_chain: {
    title: '阻断能量机关增益向前哨站伤害转化', capability: ['spatial', 'resource'], roles: ['步兵', '哨兵'], zone: '中央区域 / 己方前场',
    actions: ['对方触发能量机关后立即按90秒目标进攻窗口处理', '不追逐离开目标方向的单位，优先封锁其进入前哨站攻击方向的路线', '对方未能使前哨站扣血时，再恢复下一轮能量机关和增益点争夺'],
    success: '对方取得能量机关增益后90秒内，己方前哨站没有有效扣血', exit: '90秒窗口结束，且对方地面单位退回中央区域', fallback: '按基地血量、前哨站血量和能否重建前哨站重新分配兵力', risk: '长时间放弃能量机关会让对方获得后续攻防与热量冷却优势',
  },
  opening_aerial: {
    title: '压低对方首轮空中支援收益', capability: ['radar', 'defense'], roles: ['雷达', '哨兵', '步兵'], zone: '己方前场 / 有掩体通行路线',
    actions: ['在对方空中机器人通常发弹前保留雷达反制机会', '哨兵与步兵分开通行，避免同时暴露在同一条空中射线上', '空中支援结束或被反制后，再恢复双车越线与前哨站防守'],
    success: '对方空中机器人发弹后，没有连续造成机器人或前哨站伤害', exit: '空中机器人停止发弹，或本轮雷达反制结束', fallback: '地面单位分散进入掩体，以前哨站和基地剩余血量为第一优先级', risk: '现有记录只能证明反制UAV事件，不能证明完整的雷达解析与标记进度',
  },
  opening_radar: {
    title: '避开对方开局雷达反制窗口', capability: ['spatial', 'resource'], roles: ['空中', '地面机动单位'], zone: '中央区域两侧通行路线',
    actions: ['不要让首轮空中支援与唯一一波地面推进同时开始', '雷达反制触发后，由哨兵和步兵继续压制前哨站攻击方向', '空中机器人恢复前，改变下一次起飞时间或攻击路线'],
    success: '空中机器人受反制后，地面单位仍能维持前哨站或中央区域压力', exit: '反制效果结束，且地面阵型已经稳定', fallback: '取消本轮以空中机器人为主的推进，把资源留到下一次目标窗口', risk: '现有数据没有雷达密钥与解析进度，不能给出更细的反制时点',
  },
  rapid_outpost_kill: {
    title: '延长前哨站存活时间，维持基地无敌', capability: ['outpost', 'defense'], roles: ['哨兵', '步兵', '工程'], zone: '己方前场',
    actions: ['以前哨站首次扣血为计时起点，立即进入持续防守', '优先驱离能稳定命中前哨站的英雄、步兵或哨兵，并保留一条补位路线', '前哨站低血量时停止外线换血；若满足条件，准备在5:00前占领己方前哨站增益点实施重建'],
    success: '对方从前哨站首伤到击毁的耗时超过其历史75分位', exit: '前哨站连续15秒不再扣血，或主要攻击单位退出射界', fallback: '确认前哨站无法守住时，提前退守基地攻击方向', risk: '集中守前哨站会让出能量机关和其他通行路线，必须保留基地回防单位',
  },
  sustained_17: {
    title: '打断对方17mm连续发弹', capability: ['defense', 'spatial'], roles: ['步兵', '哨兵'], zone: '主要发弹通行路线 / 中央区域',
    actions: ['根据受击方向识别主要17mm射界，不因总承伤上升而全队后撤', '由机动步兵迫使持续发弹单位移动，使其丢失射界并中断热量节奏', '连续发弹停止后，立即回到前哨站、基地或增益点的任务位置'],
    success: '对方连续发弹时间缩短，且己方机器人净损血不再持续增加', exit: '连续10秒没有新的17mm受击', fallback: '减少正面暴露，改为以战略目标剩余血量换取比赛优势', risk: '现有受击记录不能稳定还原每一发的射手，只能定位主要输出候选',
  },
  outpost_base_switch: {
    title: '前哨站被击毁后封锁基地攻击方向', capability: ['base', 'spatial'], roles: ['哨兵', '机动步兵'], zone: '己方前场至基地的回防路线',
    actions: ['前哨站血量降至0、基地无敌解除时，立即启动90秒基地防守窗口', '一台单位覆盖基地攻击方向，另一台驱离对方后续英雄或17mm输出单位', '不要在已被击毁的前哨站附近追击低威胁目标'],
    success: '对方基地首伤晚于其历史75分位，或90秒内未能使基地扣血', exit: '90秒结束且基地没有有效扣血', fallback: '全队按基地血量优先，暂时放弃非关键能量机关和外线换血', risk: '回撤过早会让出中央区域；风险窗口结束后应按场上血量恢复争夺',
  },
  resource_objective: {
    title: '阻止对方把增益或装配转化为目标伤害', capability: ['resource', 'spatial'], roles: ['步兵', '哨兵'], zone: '中央区域至己方战略目标',
    actions: ['对方取得能量机关增益或完成装配后，立即预警其前哨站/基地进攻', '90秒内减少无关追击，守住前哨站与基地的主要攻击方向', '若对方没有形成目标伤害，反向争夺下一次能量机关或增益点'],
    success: '增益或装配事件后，对方造成的前哨站/基地净伤低于其历史中位数', exit: '90秒结束，或规则对应的增益效果已经结束', fallback: '比较双方基地与前哨站血量，决定继续守目标还是争夺下一资源', risk: '资源事件不一定带来目标伤害，低置信样本只能作为预警，不能强制全队回撤',
  },
  dart_base_combo: {
    title: '飞镖命中后切断地面基地攻坚', capability: ['base', 'defense'], roles: ['哨兵', '机动步兵'], zone: '己方后场 / 基地攻击方向',
    actions: ['飞镖闸门开启后，提前让哨兵或步兵回到基地攻击方向', '飞镖命中后优先驱离仍能以17mm或42mm命中基地的地面单位', '基地没有持续扣血时也不向远端追击，守到本次发射与检测窗口结束'],
    success: '飞镖命中后15秒内，没有新增17mm或42mm基地伤害', exit: '基地连续15秒不再扣血，且地面输出单位离开攻击方向', fallback: '在下一飞镖窗口结束前持续按基地血量优先', risk: '地面单位不能拦截已命中的飞镖，任务重点是避免飞镖效果后继续被地面火力扣血',
  },
  hero42_siege: {
    title: '迫使对方英雄离开42mm基地射界', capability: ['spatial', 'defense'], roles: ['机动步兵', '哨兵'], zone: '对方主要基地攻击方向',
    actions: ['基地出现42mm首伤后，把对方英雄所在方向列为最高威胁', '由机动步兵逼迫英雄移动，优先让其丢失基地射界，不与其进行无收益正面换血', '英雄停止输出后，保留一台单位覆盖其再次进入射界的路线'],
    success: '连续8秒没有新增42mm基地伤害', exit: '英雄离开基地攻击方向，且本轮伤害窗口关闭', fallback: '退到基地近区，以保存基地剩余血量为第一目标', risk: '英雄位置由42mm伤害与运动轨迹联合推断，不能把候选位置当作裁判系统确认位置',
  },
  mixed_base_siege: {
    title: '拆解17mm、42mm与飞镖的基地协同', capability: ['base', 'defense'], roles: ['哨兵', '步兵'], zone: '己方后场 / 两侧基地攻击方向',
    actions: ['按飞镖、42mm、17mm实际造成的基地伤害确定第一处理对象', '先驱离能持续发弹的英雄、步兵或哨兵，再处理一次性飞镖效果', '保留一台机器人覆盖第二条基地攻击方向，防止对方重新建立射界'],
    success: '基地伤害来源降为单一，且连续15秒没有新增扣血', exit: '所有持续输出候选离开己方后场', fallback: '放弃外线目标，以终局基地剩余血量为第一优先级', risk: '同时追击多个伤害来源会进一步分散基地防守，应按实际伤害占比逐个处理',
  },
  terminal_base_hold: {
    title: '按终局胜负顺位突破高血量基地', capability: ['objective', 'firepower'], roles: ['英雄', '步兵', '飞镖'], zone: '对方后场',
    actions: ['进入最后60秒前，准备英雄42mm、步兵17mm与可用飞镖窗口', '对方基地近区防守密集时选择单路集中，优先形成一次有效基地扣血', '基地攻击方向不可达时，立即比较前哨站状态、总攻击伤害和双方机器人总血量'],
    success: '在最后60秒的前半段使对方基地有效扣血，并取得基地剩余血量优势', exit: '基地路线不可达，且己方已在后续胜负判定指标上占优', fallback: '依规则顺序争取前哨站状态、总攻击伤害、机器人总血量优势', risk: '终局强攻会损失机器人血量；若基地与前哨站指标相同，机器人总血量仍可能决定胜负',
  },
  outpost_fallback: {
    title: '利用对方回撤，继续压低前哨站血量', capability: ['outpost', 'spatial'], roles: ['英雄', '步兵', '哨兵'], zone: '对方前场 / 前哨站攻击方向',
    actions: ['对方前哨站首次扣血后，确认其地面阵型是否向后收缩', '守方回撤时占住原有射界，不追入基地近区与低价值单位换血', '用17mm持续磨损，英雄保留42mm完成关键扣血或击毁'],
    success: '守方回撤后仍能持续命中前哨站，并保持己方主要输出单位存活', exit: '对方重新形成交叉防守，或己方输出单位无法安全保持射界', fallback: '退出前哨站射界，转争能量机关与增益点后再组织下一轮进攻', risk: '过深追击可能让输出单位被击毁，并失去后续基地攻坚能力',
  },
  base_guard: {
    title: '绕开对方基地近区保护', capability: ['base', 'spatial'], roles: ['英雄', '步兵', '飞镖'], zone: '对方后场 / 基地两侧攻击方向',
    actions: ['基地首次扣血后，判断守方30秒内主要回防方向', '地面主攻避开守方密集路线，另一侧单位只负责牵制，不进行无收益换血', '若有飞镖窗口，先用飞镖效果打乱其信息或增益，再让英雄建立42mm射界'],
    success: '守方保持近区保护时，己方仍能从另一攻击方向造成基地扣血', exit: '两侧基地攻击方向均被封锁，且己方输出单位生存风险过高', fallback: '保存机器人总血量，转争前哨站状态或总攻击伤害优势', risk: '分路后火力不足可能无法形成有效基地伤害，应保留一侧为明确主攻',
  },
  base_denial: {
    title: '打破对方“前哨受压但基地无伤”防守', capability: ['base', 'objective'], roles: ['英雄', '步兵', '飞镖'], zone: '对方前场至基地攻击方向',
    actions: ['把击毁前哨站视为解除基地无敌的起点，而不是本轮进攻终点', '前哨站击毁前让英雄或机动步兵提前靠近基地转场路线', '基地无敌解除后立即以42mm、17mm或飞镖形成首次扣血'],
    success: '击毁前哨站后90秒内使基地首次扣血', exit: '转场路线被封锁，且继续推进会丢失机器人总血量优势', fallback: '控制前哨站增益点，阻止对方在5:00前完成前哨站重建', risk: '过早前置会削弱前哨站输出；必须确保先完成击毁条件',
  },
  terminal_pressure: {
    title: '终局阻止对方保持己方半场压力', capability: ['spatial', 'defense'], roles: ['哨兵', '步兵'], zone: '己方半场 / 基地回防路线',
    actions: ['最后60秒先核对双方基地血量与前哨站状态，再决定是否主动交战', '己方胜负指标领先时，优先驱离越过中线的单位并保存机器人总血量', '己方落后时集中攻击对方主推进单位，争取总攻击伤害与机器人血量反超'],
    success: '对方无法持续占据己方半场，且己方保持当前优先级更高的胜负指标', exit: '比赛结束，或对方全部退回中央区域', fallback: '守住基地攻击方向，按基地血量、前哨站状态、总攻击伤害、机器人总血量依次取舍', risk: '领先时无必要追击可能反而损失最后一级机器人总血量优势',
  },
}

function finite(value, fallback = 0) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

function average(values) {
  const usable = values.map(Number).filter(Number.isFinite)
  return usable.length ? usable.reduce((sum, value) => sum + value, 0) / usable.length : 50
}

function capability(profile, key) {
  const values = profile?.capabilities || {}
  if (key === 'spatial') return finite(values.mobility_score, 50)
  if (key === 'defense') return finite(values.defense_score, 50)
  if (key === 'resource') return finite(values.resource_score, 50)
  if (key === 'base') return average([values.base_denial_pct, values.defense_score])
  if (key === 'outpost') return average([values.outpost_denial_pct, values.defense_score])
  if (key === 'radar') return average([values.radar_counter_game_pct, values.defense_score])
  if (key === 'objective') return finite(values.objective_score, 50)
  if (key === 'firepower') return finite(values.firepower_score, 50)
  return 50
}

function clock(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—'
  const second = Math.max(0, Math.round(Number(value)))
  return `${Math.floor(second / 60)}:${String(second % 60).padStart(2, '0')}`
}

function evidenceScore(value) {
  return value === '高' ? 100 : value === '中' ? 65 : 35
}

function responseAlignment(pattern, executor) {
  const response = pattern.counter_response || {}
  if (!response.usable) return { score: 35, label: '规则型备选', usable: false }
  const own = executor.capabilities || {}
  const comparisons = [
    [own.early_forward_pct, response.early_forward_pct],
    [own.multi_push_seconds, response.multi_push_seconds],
    [own.damage_per_game, response.damage_per_game],
  ].filter(([value, reference]) => Number.isFinite(Number(value)) && Number.isFinite(Number(reference)) && Number(reference) > 0)
  const score = comparisons.length ? average(comparisons.map(([value, reference]) => Math.max(0, Math.min(100, 50 + (Number(value) / Number(reference) - 1) * 50)))) : 50
  return { score, label: `${response.games} 局反例响应`, usable: true }
}

export function buildCounterPlans(target, executor) {
  if (!target || !executor || target.team === executor.team) return []
  const candidates = (target.patterns || []).filter(pattern => rules[pattern.pattern_id] && pattern.observed >= 2 && pattern.rate >= .10)
  const plans = candidates.map(pattern => {
    const rule = rules[pattern.pattern_id]
    const recurrence = finite(pattern.rate) * 100
    const duration = 420
    const urgency = pattern.timing?.median == null ? 45 : Math.max(0, 100 - finite(pattern.timing.median) / duration * 100)
    const threat = .45 * finite(impactScore[pattern.phase], 50) + .25 * recurrence + .15 * urgency + .15 * evidenceScore(pattern.confidence)
    const ownCapability = average(rule.capability.map(key => capability(executor, key)))
    const response = responseAlignment(pattern, executor)
    const targetStrength = average([target.capabilities?.objective_score, target.capabilities?.firepower_score])
    const fit = .45 * ownCapability + .30 * Math.max(0, 100 - targetStrength) + .25 * response.score
    const priority = .65 * threat + .35 * fit
    const lowEvidence = pattern.confidence === '低' || executor.sample?.games < 6 || !response.usable
    return {
      id: pattern.pattern_id,
      title: rule.title,
      phase: pattern.phase,
      priority: Math.round(priority),
      confidence: lowEvidence ? '低 · 规则型备选' : pattern.confidence === '高' ? '高' : '中',
      threat: {
        label: pattern.label,
        ratePct: Math.round(recurrence * 10) / 10,
        observed: pattern.observed,
        eligible: pattern.eligible,
        timing: clock(pattern.timing?.median),
        timingRange: `${clock(pattern.timing?.p25)}–${clock(pattern.timing?.p75)}`,
      },
      matchup: {
        executorCapability: Math.round(ownCapability * 10) / 10,
        targetStrength: Math.round(targetStrength * 10) / 10,
        response: response.label,
        responseScore: Math.round(response.score * 10) / 10,
      },
      roles: rule.roles,
      zone: rule.zone,
      actions: rule.actions,
      success: rule.success,
      exit: rule.exit,
      fallback: rule.fallback,
      risk: rule.risk,
      evidence: pattern.evidence || [],
      association: pattern.association,
    }
  }).sort((first, second) => second.priority - first.priority || second.threat.ratePct - first.threat.ratePct)

  const selected = []
  for (const plan of plans) {
    if (selected.some(item => item.phase === plan.phase) && selected.length < 2) continue
    selected.push(plan)
    if (selected.length === 3) break
  }
  return selected
}

export function visibleTacticalPatterns(profile, phase = 'all', includeInsufficient = false) {
  return (profile?.patterns || []).filter(pattern => (phase === 'all' || pattern.phase === phase) && (includeInsufficient || pattern.classification !== '样本不足'))
}

export function tacticClock(value) {
  return clock(value)
}
