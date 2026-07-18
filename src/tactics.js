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
    title: '拆解开局双车前压', capability: ['spatial', 'defense'], roles: ['哨兵', '步兵'], zone: '己方前场 / 对方主推进通道',
    actions: ['在对方触发时间窗前完成前哨两层站位', '固定一台单位维持正面拒止，另一台机动单位切断后续增援', '对方前压车数降至一台后再恢复中区争夺'],
    success: '对方连续 10 秒无法维持双车过中线', exit: '前哨停止受击且对方阵型回到中央区', fallback: '收缩至前哨—基地之间，禁止继续外扩追击', risk: '过早投入两台机动单位会让另一通道失去控制',
  },
  opening_outpost: {
    title: '延迟开局前哨首压', capability: ['defense', 'spatial'], roles: ['哨兵', '步兵'], zone: '己方前场 / 对方高频通道',
    actions: ['按对方首压 P25 时间提前完成交叉防线', '保留一台高机动单位攻击持续发弹位而非追击低威胁单位', '前哨出现首伤后以 10 秒为窗口判断是否继续增援'],
    success: '对方首次有效前哨伤害晚于历史 P75', exit: '前哨连续 10 秒无扣血或对方转向资源区', fallback: '放弃外线交换，优先保存前哨与基地之间的回防路径', risk: '正面堆叠会被分路或空中火力牵制',
  },
  rune_outpost_chain: {
    title: '切断资源到前哨的转化链', capability: ['spatial', 'resource'], roles: ['步兵', '哨兵'], zone: '中央区 / 己方前场',
    actions: ['能量机关事件发生后立即进入 90 秒高风险窗口', '不追逐资源区残余单位，优先封锁其返回前哨射界的路径', '确认对方目标伤害未形成后再恢复资源争夺'],
    success: '资源事件后 90 秒内前哨无有效扣血', exit: '风险窗口结束且对方纵深回落', fallback: '以基地血量和前哨血量优先级重新分配防守', risk: '过度封锁会放弃后续资源收益',
  },
  opening_aerial: {
    title: '压低空中开局覆盖收益', capability: ['radar', 'defense'], roles: ['雷达', '哨兵', '步兵'], zone: '己方前场 / 掩体侧通道',
    actions: ['在对方空中高频窗口前保留雷达反制资源', '地面输出位避免同时暴露于同一通道', '空中火力下降后再恢复双车协同推进'],
    success: '对方空中发弹后未形成连续前哨或机器人伤害', exit: '空中输出停止或反制窗口结束', fallback: '分散地面队形并以战略目标血量优先', risk: '雷达事件样本仅覆盖已记录的反制 UAV，不代表完整解析能力',
  },
  opening_radar: {
    title: '规避早期雷达反制窗口', capability: ['spatial', 'resource'], roles: ['空中', '地面机动单位'], zone: '中央区两侧通道',
    actions: ['避免把第一次空中支援与固定地面推进完全重叠', '雷达反制触发后由地面单位接管目标压力', '空中恢复前不重复暴露同一节奏'],
    success: '空中受反制后地面目标压力不下降', exit: '反制效果结束且地面阵型稳定', fallback: '取消本轮空中主导推进，保留资源进入下一窗口', risk: '无法从现有数据推断雷达密钥或解析进度',
  },
  rapid_outpost_kill: {
    title: '破坏前哨连续击毁链', capability: ['outpost', 'defense'], roles: ['哨兵', '步兵', '工程'], zone: '己方前场',
    actions: ['以前哨首伤为计时起点进入持续压制防御', '优先驱离稳定输出位并保持一条补位路径', '前哨低血量时停止低价值外线换血'],
    success: '前哨击毁耗时超过对方历史 P75', exit: '前哨连续 15 秒无伤害或攻击源退出射界', fallback: '前哨不可保时提前形成基地第一道防线', risk: '集中保护前哨可能让资源区和基地外围同时失位',
  },
  sustained_17: {
    title: '打断高频 17mm 持续压制', capability: ['defense', 'spatial'], roles: ['步兵', '哨兵'], zone: '主要发弹通道 / 中央区',
    actions: ['识别对方主要 17mm 输出通道而非按总承伤被动回撤', '用机动单位迫使持续输出位移动并中断热量节奏', '窗口结束后立即恢复战略目标站位'],
    success: '对方连续发弹窗口缩短且机器人净伤不再增长', exit: '10 秒内无持续 17mm 受击', fallback: '降低正面暴露并转为目标血量交换', risk: '17mm 受击没有稳定的个体射手身份，执行对象为候选输出位',
  },
  outpost_base_switch: {
    title: '封锁前哨到基地的快速转场', capability: ['base', 'spatial'], roles: ['哨兵', '机动步兵'], zone: '己方前场至后场回廊',
    actions: ['前哨被毁即启动 90 秒基地风险窗口', '一台单位覆盖基地攻击方向，另一台切断对方后续输出位', '禁止在前哨残区进行低价值追击'],
    success: '对方基地首伤晚于其历史 P75 或转场失败', exit: '90 秒结束且基地无有效扣血', fallback: '全队转入基地血量优先，放弃非关键资源交换', risk: '提前回撤会让出中央区，应在风险窗口结束后复位',
  },
  resource_objective: {
    title: '削弱资源事件后的目标爆发', capability: ['resource', 'spatial'], roles: ['步兵', '哨兵'], zone: '中央区至己方目标区',
    actions: ['把能量机关或装配事件作为目标压力预警', '资源事件后 90 秒内减少无目标追击', '对方未完成目标转化时反向争夺下一资源窗口'],
    success: '资源事件后目标净伤低于对方历史中位数', exit: '90 秒窗口结束或对方资源增益失效', fallback: '以基地和前哨剩余血量决定是否继续让出资源', risk: '资源事件本身不等于有效转化，低置信样本不得强制触发',
  },
  dart_base_combo: {
    title: '拆分飞镖与基地伤害窗口', capability: ['base', 'defense'], roles: ['哨兵', '机动步兵'], zone: '己方后场 / 基地攻击方向',
    actions: ['飞镖窗口开启时预先完成基地近区保护', '飞镖命中后优先驱离可继续造成基地伤害的地面输出位', '基地未形成持续扣血时禁止远端追击'],
    success: '飞镖命中后 15 秒内无新增地面基地伤害', exit: '基地连续 15 秒无扣血', fallback: '保持基地血量优先直至下一飞镖窗口结束', risk: '飞镖命中不可通过常规地面拦截，重点是阻断后续伤害链',
  },
  hero42_siege: {
    title: '迫使英雄退出 42mm 基地射界', capability: ['spatial', 'defense'], roles: ['机动步兵', '哨兵'], zone: '对方主要基地攻击通道',
    actions: ['基地出现 42mm 首伤后将英雄候选位提升为最高威胁', '以机动单位迫使英雄移动而非继续正面换血', '英雄停止输出后保持一台单位覆盖其再次进入路径'],
    success: '连续 8 秒无新增 42mm 基地伤害', exit: '英雄离开攻击方向且基地伤害窗口关闭', fallback: '退至基地保护区，以剩余血量优先进行伤害交换', risk: '英雄位置由 42mm 和空间轨迹联合推断，不使用不存在的部署事件',
  },
  mixed_base_siege: {
    title: '拆解多来源基地围攻', capability: ['base', 'defense'], roles: ['哨兵', '步兵'], zone: '己方后场 / 两侧入口',
    actions: ['按飞镖、42mm、17mm的实际伤害占比确定第一威胁', '先切断可持续输出源，再处理一次性伤害窗口', '保留一台单位防止第二通道重新建立射界'],
    success: '基地伤害来源降为单一且连续 15 秒无新增伤害', exit: '所有持续输出候选退出后场', fallback: '放弃外线目标，以基地终局血量作为唯一优先级', risk: '同时追击多个来源会进一步分散基地防守',
  },
  terminal_base_hold: {
    title: '终盘突破高血量基地保持', capability: ['objective', 'firepower'], roles: ['英雄', '步兵', '飞镖'], zone: '对方后场',
    actions: ['最后 60 秒前完成主要输出资源准备', '根据对方基地保护密度选择单路集中而非平均分散', '无法形成基地伤害时切换到前哨、攻击伤害和全队剩余血量判定'],
    success: '在终盘前半段形成基地有效扣血', exit: '基地路线不可达且次级胜负指标占优', fallback: '按规则依次争取前哨、攻击伤害和剩余血量优势', risk: '终盘强攻会降低全队剩余血量，必须结合当前胜负条件',
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

