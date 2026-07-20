<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import HeatmapCanvas from './components/HeatmapCanvas.vue'
import CounterPlanCard from './components/CounterPlanCard.vue'
import MethodologyDrawer from './components/MethodologyDrawer.vue'
import TacticDimensionCard from './components/TacticDimensionCard.vue'
import TacticalPatternCard from './components/TacticalPatternCard.vue'
import { aggregateHeatCells, densityOpacity, doubleEliminationNextPairings, doubleEliminationStandings, matchupEstimate, monteCarloTournament, officialToMap, predictedWinner, rankRoleTeams, rankTeamsByStrength, rasterMapCenter, rasterMapPlacement, rasterMapPoint, roleFrameSeries, roleMetrics, seriesWinProbability, strengthGrade, summarizeDimensions, swissNextPairings, swissStandings, teamPerspectivePoint, teamStrength } from './domain.js'
import { buildCounterPlans, visibleTacticalPatterns } from './tactics.js'
import { activeDamageEffects as effectsAt, deriveDamageEffects, deriveShotEffects, interpolatedFrame, nativeFrameRate, normalizeReplayData, teamFrameAt } from './replay.js'

const base = import.meta.env.BASE_URL
const dataRevision = 'score-4.0.0-matchup-4.7.0-rank-stability-1.0.0-series-validation-1.1.0-role-data-1.1.0-replay-3.1.0-tournament-3.0.0-tactics-1.0.0'
const index = ref({ teams: [] }), dataManifest = ref(null), selected = ref(null), query = ref(''), region = ref('全部'), error = ref('')
const teamTab = ref('overview'), density = ref(localStorage.getItem('rmuc-density') || 'comfortable'), filtersOpen = ref(false), methodologyOpen = ref(false), loadingTeam = ref(false), loadingHeat = ref(false)
const heat = ref(null), heatSide = ref('全部'), heatRobot = ref('全部'), heatView = ref('actual'), heatFrom = ref(0), heatTo = ref(420), heatMaskOpacity = ref(.34)
const gameData = ref(null), activeGame = ref(null), time = ref(0), playing = ref(false), speed = ref(1), tail = ref(20), mapMode = ref('raster'), routeView = ref('actual')
const damageEffects = ref([]), shotEffects = ref([])
const replayEventFilter = ref('全部'), showLowConfidence = ref(false), selectedReplayRobot = ref(null), loadingGame = ref(false), gameError = ref('')
const visibleRobots = ref({}), compareSlug = ref(''), compareTeam = ref(null), compareStage = ref('小组赛')
const viewMode = ref('team'), roleCatalog = ref({ roles: [] }), selectedRoleSlug = ref('hero'), roleIndex = ref(null), roleTeam = ref(null)
const roleRegion = ref('全部'), roleQuery = ref(''), roleMetric = ref('availability_pct'), activeRoleGameId = ref(null), roleTime = ref(0)
const tournamentConfig = ref(null), tournamentMode = ref('repechage'), tournamentTeams = ref({ repechage: [], finals: [] }), tournamentGroups = ref({ repechage: [[], []], finals: [[], []] }), tournamentRounds = ref({ repechage: { A: [], B: [] }, finals: { A: [], B: [] } }), finalsQualifiers = ref([null, null, null, null]), tournamentBusy = ref(false)
const tournamentPredictionMode = ref('random'), tournamentPlayoffs = ref({ repechage: [], finals: [] }), tournamentMedals = ref({ semifinals: [], final: null, bronze: null }), tournamentOdds = ref({ repechage: [], finals: [] }), tournamentOddsBusy = ref(false)
const expandedTactics = ref(new Set())
const tacticalProfile = ref(null), counterExecutorProfile = ref(null), loadingTactics = ref(false), loadingCounterExecutor = ref(false)
const tacticalError = ref(''), counterExecutorError = ref('')
const tacticPhase = ref('all'), includeInsufficientPatterns = ref(false), expandedPatterns = ref(new Set())
const counterExecutorSlug = ref(localStorage.getItem('rmuc-counter-executor') || '')
const methodologyTrigger = ref(null), teamListNode = ref(null)
const tournamentLabels = ['A', 'B']
const teamTabs = [
  ['overview', '总览'], ['tactics', '战术'], ['map', '地图'], ['matches', '对局'],
  ['roles', '兵种'], ['discipline', '纪律'], ['compare', '对比'],
]
const roleShortcuts = [['hero','英雄'],['engineer','工程'],['infantry3','步兵3'],['infantry4','步兵4'],['aerial','空中'],['sentry','哨兵'],['dart','飞镖']]
const assemblyRules = [
  { level:1, unlock:0, benefit:'首次：每10秒获得50金币；重复：额外5金币' },
  { level:2, unlock:60, benefit:'首次：机器人等级上限提高至7级；重复：额外10金币' },
  { level:3, unlock:120, benefit:'首次：25%防御增益、等级上限10级；重复：额外15金币' },
  { level:4, unlock:180, benefit:'首次：50%防御增益、基地增加2000血量、额外50金币；仅限一次' },
]
let scoreChart, damageChart, chartApiPromise, animationFrame, idleChart, previousFrame = 0, teamController, compareController, detailPromise, counterRequestId = 0
const requestCache = new Map()
const colors = ['#ff5268','#ff9e54','#ffd166','#9b7bff','#ef70cb','#ff355f','#48a8ff','#58d3ff','#41e1a6','#6f8dff','#61b8ff','#16c7e8']
const rankedTeams = computed(() => rankTeamsByStrength(index.value.teams))
const teams = computed(() => rankedTeams.value.filter(t => (region.value === '全部' || t.region === region.value) && (!query.value || t.team.includes(query.value))))
const slug = computed(() => index.value.teams.find(t => t.team === selected.value?.team)?.slug)
const strength = computed(() => teamStrength(selected.value))
const grade = computed(() => strengthGrade(strength.value))
const dimensions = computed(() => summarizeDimensions(selected.value))
const dimensionCards = computed(() => [
  ['firepower','火力'], ['objective','目标'], ['spatial','空间'], ['defense','防守'], ['resource','资源'], ['adaptability','适应'],
].map(([key, label]) => ({ key, label, score: selected.value?.scores?.[key] })))
function regionalRankLabel(team, detailed = false) {
  const evidence = team?.rank_stability
  if (!evidence) return `全局参考 #${team?.overall_rank || team?.strengthRank || '—'}`
  const [low, high] = evidence.region_rank_range || [evidence.region_rank, evidence.region_rank]
  const range = low === high ? `稳定 #${low}` : `波动 #${low}–#${high}`
  return detailed
    ? `赛区 #${evidence.region_rank} · ${low === high ? `10次重算均 #${low}` : `重算范围 #${low}–#${high}`} · 全局参考 #${team?.overall_rank || '—'}`
    : `赛区 #${evidence.region_rank} · ${range}`
}
const tacticalPhases = computed(() => tacticalProfile.value?.phases || [])
const tacticalPatterns = computed(() => visibleTacticalPatterns(tacticalProfile.value, tacticPhase.value, includeInsufficientPatterns.value))
const counterExecutor = computed(() => index.value.teams.find(team => team.slug === counterExecutorSlug.value) || null)
const counterPlans = computed(() => buildCounterPlans(tacticalProfile.value, counterExecutorProfile.value))
const allTacticsExpanded = computed(() => tacticCards.value.length > 0 && tacticCards.value.every(card => expandedTactics.value.has(card.id)))
const tacticCards = computed(() => {
  if (!selected.value) return []
  const d = dimensions.value
  const component = (analysis, label, key, weight) => ({ label, weight, value: show(analysis?.components?.[key]) })
  const card = (id, label, analysis, primaryFacts, secondaryFacts, components, sample) => ({
    id, label, score: show(analysis?.score), rank: dimensionRankText(id), confidence: show(selected.value.dimension_confidence?.[id], '%'), primaryFacts, secondaryFacts, components, sample,
  })
  return [
    card('firepower', '净战斗火力', d.analysis.firepower,
      [{ label:'场均总输出', value:fact(selected.value.summary.avg_damage_dealt,' 点/局',0) }, { label:'机器人命中率', value:fact((d.analysis.firepower?.raw?.accuracy||0)*100,'%',1) }, { label:'场均 17mm 发弹', value:fact(d.firepower.shots17PerGame,' 发',1) }, { label:'场均 42mm 发弹', value:fact(d.firepower.shots42PerGame,' 发',1) }],
      [{ label:'净输出/对手预期', value:fact(d.analysis.firepower?.raw?.clean_output,'×',3) }, { label:'持续施压时间占比', value:fact((d.analysis.firepower?.raw?.pressure_uptime||0)*100,'%',1) }],
      [component(d.analysis.firepower,'对手校正净输出','clean_output','35%'), component(d.analysis.firepower,'机器人命中效率','accuracy','15%'), component(d.analysis.firepower,'阵亡转化','kill_conversion','25%'), component(d.analysis.firepower,'持续施压','pressure_uptime','25%')], `各分项有效样本 ${sampleCount('firepower','clean_output')} 局`),
    card('objective', '目标转化', d.analysis.objective,
      [{ label:'场均前哨伤害', value:fact(selected.value.summary.avg_outpost_damage,' 点/局',0) }, { label:'场均基地伤害', value:fact(selected.value.summary.avg_base_damage,' 点/局',0) }, { label:'击毁前哨中位耗时', value:d.objective.medianOutpostKillSec==null?'—':fmtSecond(d.objective.medianOutpostKillSec) }, { label:'前哨施压覆盖', value:`${d.objective.outpostAttackGames}/${selected.value.summary.games} 局 · ${fact(d.objective.outpostAttackPct,'%',1)}` }],
      [{ label:'首次击打前哨中位', value:d.objective.firstOutpostSec==null?'—':fmtSecond(d.objective.firstOutpostSec) }, { label:'有效击毁前哨', value:`${d.objective.outpostKillGames} 局` }, { label:'最快击毁耗时', value:d.objective.fastestOutpostKillSec==null?'—':fmtSecond(d.objective.fastestOutpostKillSec) }, { label:'首次击打基地中位', value:d.objective.firstBaseSec==null?'—':fmtSecond(d.objective.firstBaseSec) }],
      [component(d.analysis.objective,'前哨施压','outpost_pressure','10%'), component(d.analysis.objective,'前哨转化','outpost_conversion','25%'), component(d.analysis.objective,'基地施压','base_pressure','15%'), component(d.analysis.objective,'基地转化','base_conversion','35%'), component(d.analysis.objective,'战略工具','strategic_tools','15%')], `目标分项有效样本 ${sampleCount('objective','outpost_conversion')} 局`),
    card('spatial', '空间控制', d.analysis.spatial,
      [{ label:'平均推进纵深', value:fact(d.mobility.attackDepthM,' m',1) }, { label:'深压时间', value:fact(d.mobility.deepPressureSec,' s/局',1) }, { label:'相对对手推进纵深', value:signed(d.analysis.spatial?.raw?.relative_territory,' m',2) }, { label:'前压车秒占比', value:fact((d.analysis.spatial?.raw?.forward_presence||0)*100,'%',1) }],
      [{ label:'全队场均里程', value:fact(d.mobility.distanceM,' m',1) }, { label:'平均队形间距', value:fact(d.mobility.pairDistanceM,' m',1) }, { label:'有效场地格覆盖', value:fact(d.analysis.spatial?.raw?.field_coverage,' 格',1) }, { label:'有效定位覆盖', value:fact(d.confidence?.position_coverage_pct,'%',1) }],
      [component(d.analysis.spatial,'相对领土纵深','relative_territory','25%'), component(d.analysis.spatial,'前压在场','forward_presence','30%'), component(d.analysis.spatial,'中区相对控制','neutral_control','35%'), component(d.analysis.spatial,'场地覆盖','field_coverage','10%')], `空间分项有效样本 ${sampleCount('spatial','neutral_control')} 局`),
    card('defense', '防守韧性', d.analysis.defense,
      [{ label:'场均总承伤', value:fact(selected.value.summary.avg_damage_taken,' 点/局',0) }, { label:'校正伤害交换', value:fact(d.analysis.defense?.raw?.trade_resilience,'×',3) }, { label:'机器人韧性', value:fact((d.analysis.defense?.raw?.mobile_resilience||0)*100,'%',1) }, { label:'基地拒止', value:fact((d.analysis.defense?.raw?.base_denial||0)*100,'%',1) }],
      [{ label:'前哨拒止', value:fact((d.analysis.defense?.raw?.outpost_denial||0)*100,'%',1) }, { label:'防守下限', value:fact((d.analysis.defense?.raw?.collapse_resistance||0)*100,'%',1) }, { label:'排除判罚伤害', value:fact(d.analysis.defense?.excluded?.penalty_damage,' 点',0) }, { label:'排除撞击伤害', value:fact(d.analysis.defense?.excluded?.collision_damage,' 点',0) }],
      [component(d.analysis.defense,'校正伤害交换','trade_resilience','35%'), component(d.analysis.defense,'机器人韧性','mobile_resilience','25%'), component(d.analysis.defense,'前哨拒止','outpost_denial','15%'), component(d.analysis.defense,'基地拒止','base_denial','15%'), component(d.analysis.defense,'整体防守下限','collapse_resistance','10%')], `各结构分项有效样本 ${sampleCount('defense','base_denial')} 局`),
    card('resource', '资源转化', d.analysis.resource,
      [{ label:'场均总经济', value:fact(d.resource.totalCoins,'',0) }, { label:'经济使用率', value:fact(d.resource.spendPct,'%',1) }, { label:'目标净伤/经济', value:fact(d.analysis.resource?.raw?.objective_conversion,' 点/币',3) }, { label:'净输出/高热车秒', value:fact(d.analysis.resource?.raw?.thermal_efficiency,'',1) }],
      [{ label:'场均剩余经济', value:fact(d.resource.remainingCoins,'',0) }, { label:'平均底盘功率', value:fact(d.resource.meanPower,'',1) }, { label:'高热量时间', value:fact(d.resource.highHeatSec,' s/局',1) }, { label:'机器人净伤/经济', value:fact(d.analysis.resource?.raw?.combat_conversion,' 点/币',3) }],
      [component(d.analysis.resource,'经济获取','acquisition','40%'), component(d.analysis.resource,'经济使用','utilization','5%'), component(d.analysis.resource,'战斗转化','combat_conversion','10%'), component(d.analysis.resource,'目标转化','objective_conversion','25%'), component(d.analysis.resource,'热控效率','thermal_efficiency','20%')], `资源分项有效样本 ${sampleCount('resource','acquisition')} 局`),
    card('adaptability', '适应能力', d.analysis.adaptability,
      [{ label:'红蓝方弱侧表现', value:signed(d.analysis.adaptability?.raw?.side_floor,' 分',2), meta:`${sampleCount('adaptability','side_floor')} 个成对样本` }, { label:'跨对手下四分位', value:signed(d.analysis.adaptability?.raw?.opponent_floor,' 分',2), meta:`${sampleCount('adaptability','opponent_floor')} 个对手` }, { label:'强敌超预期响应', value:signed(d.analysis.adaptability?.raw?.strong_opponent_response,' 分',2), meta:`${sampleCount('adaptability','strong_opponent_response')} 局` }, { label:'前哨失守后输出变化', value:signed(d.analysis.adaptability?.raw?.setback_response,'×',3), meta:`${sampleCount('adaptability','setback_response')} 局` }],
      [{ label:'败局后复战改善', value:signed(d.analysis.adaptability?.raw?.rematch_improvement,' 分',2), meta:`${sampleCount('adaptability','rematch_improvement')} 组复战` }],
      [component(d.analysis.adaptability,'红蓝方弱侧下限','side_floor','10%'), component(d.analysis.adaptability,'跨对手表现下限','opponent_floor','10%'), component(d.analysis.adaptability,'强敌超预期响应','strong_opponent_response','15%'), component(d.analysis.adaptability,'局内失守后响应','setback_response','35%'), component(d.analysis.adaptability,'败局后复战改善','rematch_improvement','30%')], '下限项防止“两边都差”被误判为适应强；响应项反映局内与复战调整；缺样本时回归中性'),
  ]
})
const filteredHeat = computed(() => (heat.value?.cells || []).filter(c => (heatSide.value === '全部' || c[0] === heatSide.value) && (heatRobot.value === '全部' || c[1] === heatRobot.value) && c[2] >= heatFrom.value && c[2] <= heatTo.value))
const aggregatedHeat = computed(() => aggregateHeatCells(filteredHeat.value, heatXY, heatView.value === 'canonical'))
const maxHeat = computed(() => Math.max(1, ...aggregatedHeat.value.map(c => c.samples)))
const renderedHeat = computed(() => aggregatedHeat.value.map(cell => ({ ...cell, opacity: heatOpacity(cell) })))
const headToHead = computed(() => compareTeam.value ? selected.value.matches.filter(match => match.opponent === compareTeam.value.team) : [])
const matchup = computed(() => compareTeam.value ? matchupEstimate(selected.value, compareTeam.value, headToHead.value, { stage: compareStage.value }) : null)
const comparisonRows = computed(() => {
  if (!compareTeam.value || !matchup.value) return []
  const a = selected.value, b = compareTeam.value
  const metric = (label, first, second, format = value => Number(value ?? 0).toFixed(1), lower = false, neutral = false) => {
    const difference = Number(first ?? 0) - Number(second ?? 0)
    const leader = neutral || Math.abs(difference) < .005 ? (neutral ? '样本' : '持平') : ((lower ? difference < 0 : difference > 0) ? a.team : b.team)
    return { label, first: format(first), second: format(second), leader }
  }
  const pct = value => `${Number(value ?? 0).toFixed(1)}%`
  const number = value => Number(value ?? 0).toFixed(1)
  return [
    metric('样本战绩', a.summary.games, b.summary.games, (_, team = null) => team, false, true),
    metric('历史胜率', a.summary.win_rate, b.summary.win_rate, pct),
    metric('模型综合强度', matchup.value.primaryStrength, matchup.value.opponentStrength, number),
    metric('校正赛果强度', a.strength_analysis?.result_score, b.strength_analysis?.result_score, number),
    metric('对手分（赛程解释）', a.opponent_score_analysis?.score, b.opponent_score_analysis?.score, number),
    metric('数据置信度', a.score_confidence?.overall, b.score_confidence?.overall, pct),
    metric('火力评分', a.scores.firepower, b.scores.firepower, number),
    metric('目标转化评分', a.scores.objective, b.scores.objective, number),
    metric('空间控制评分', a.scores.spatial, b.scores.spatial, number),
    metric('防守韧性评分', a.scores.defense, b.scores.defense, number),
    metric('净承伤控制', a.defense_analysis?.components?.combat_containment, b.defense_analysis?.components?.combat_containment, number),
    metric('机器人血量面积', a.defense_analysis?.components?.mobile_integrity, b.defense_analysis?.components?.mobile_integrity, number),
    metric('机器人在线率', a.defense_analysis?.components?.unit_availability, b.defense_analysis?.components?.unit_availability, number),
    metric('前哨血量面积', a.defense_analysis?.components?.outpost_integrity, b.defense_analysis?.components?.outpost_integrity, number),
    metric('基地保护', a.defense_analysis?.components?.base_protection, b.defense_analysis?.components?.base_protection, number),
    metric('资源转化评分', a.scores.resource, b.scores.resource, number),
    metric('适应能力评分', a.scores.adaptability, b.scores.adaptability, number),
    metric('场均输出', a.summary.avg_damage_dealt, b.summary.avg_damage_dealt, value => Number(value ?? 0).toFixed(0)),
    metric('场均基地伤害', a.summary.avg_base_damage, b.summary.avg_base_damage, value => Number(value ?? 0).toFixed(0)),
    metric('场均前哨伤害', a.summary.avg_outpost_damage, b.summary.avg_outpost_damage, value => Number(value ?? 0).toFixed(0)),
    metric('检测命中/发弹', (a.summary.shot_accuracy || 0) * 100, (b.summary.shot_accuracy || 0) * 100, pct),
  ].map((row, index) => {
    if (index === 0) return { ...row, first: `${a.summary.wins}胜/${a.summary.games}局`, second: `${b.summary.wins}胜/${b.summary.games}局` }
    return row
  })
})
const selectedRole = computed(() => roleCatalog.value.roles.find(role => role.role_slug === selectedRoleSlug.value))
const availableRoleMetrics = computed(() => Object.entries(roleMetrics).filter(([key]) => roleIndex.value?.teams?.some(team => team.summary?.[key] !== null && team.summary?.[key] !== undefined && Number.isFinite(Number(team.summary[key])))))
const roleTeams = computed(() => rankRoleTeams(roleIndex.value?.teams || [], roleMetric.value)
  .filter(team => (roleRegion.value === '全部' || team.region === roleRegion.value) && (!roleQuery.value || team.team.includes(roleQuery.value))))
const activeRoleGame = computed(() => roleTeam.value?.games?.find(game => game.game_id === activeRoleGameId.value) || roleTeam.value?.games?.[0] || null)
const activeRoleFrames = computed(() => activeRoleGame.value ? roleFrameSeries({ ...activeRoleGame.value, frame_columns: roleTeam.value?.frame_columns || [] }) : [])
const roleMaxPower = computed(() => Math.max(1, ...activeRoleFrames.value.map(frame => frame.power)))
const roleCurrentFrame = computed(() => {
  let result = null
  for (const frame of activeRoleFrames.value) { if (frame.second > roleTime.value) break; result = frame }
  return result
})
const roleTrailPoints = computed(() => activeRoleFrames.value.filter(frame => frame.valid).map(frame => {
  const actual = officialToMap(frame.x, frame.y)
  return rasterMapPoint(actual[0], actual[1], 'current').join(',')
}).join(' '))
const activeTournament = computed(() => tournamentConfig.value?.[tournamentMode.value] || null)
const activeTournamentTeams = computed(() => tournamentTeams.value[tournamentMode.value] || [])
const tournamentTeamMap = computed(() => new Map(activeTournamentTeams.value.map(team => [team.team, team])))
const tournamentBoards = computed(() => (tournamentGroups.value[tournamentMode.value] || []).map((names, index) => {
  const members = names.map(name => tournamentTeamMap.value.get(name)).filter(Boolean)
  const label = tournamentLabels[index], rounds = tournamentRounds.value[tournamentMode.value]?.[label] || []
  return { label, members, rounds, standings: swissStandings(members, rounds, activeTournament.value?.win_target, activeTournament.value?.loss_target, activeTournament.value?.swiss_rounds) }
}))
const tournamentSwissFinished = computed(() => tournamentBoards.value.length === 2 && tournamentBoards.value.every(board => board.rounds.length === activeTournament.value?.swiss_rounds && board.rounds.every(round => round.matches.every(match => match.winner))))
const activePlayoffStages = computed(() => tournamentPlayoffs.value[tournamentMode.value] || [])
const activeTournamentOdds = computed(() => tournamentOdds.value[tournamentMode.value] || [])
const methodologyTitle = computed(() => viewMode.value === 'team' ? `数据口径 · ${teamTabs.find(([key]) => key === teamTab.value)?.[1] || '队伍'}` : viewMode.value === 'role' ? '数据口径 · 兵种' : '数据口径 · 赛事模拟')
const methodologySections = computed(() => {
  if (viewMode.value === 'role') return [
    { title:'伤害归因', items:['42mm 按兵种唯一性归因；17mm 按同秒及前 1 秒发弹份额分配。兵种伤害是推定值，不代表射手身份或命中率。','原始秒级数据完整保留；在场率与稳定性汇总排除比赛前 10 秒和后 10 秒。'] },
    { title:'当前兵种限制', items:roleTeam.value?.limitations?.length ? roleTeam.value.limitations : ['当前兵种没有额外口径限制。'] },
  ]
  if (viewMode.value === 'repechage') return [
    { title:'抽签与预测', items:[activeTournament.value?.draw_note || '分组由用户调整或随机模拟生成，不代表官方抽签结果。','显示胜率作为单场随机抽样概率；最高概率路径模式才会固定选择胜率较高的一方。'] },
    { title:'赛制边界', items:['赛制门槛来自全国总决赛参赛手册 V2.1.0。PDF 未给出完整双败对阵树，双败阶段按负场和模型种子交叉配对。','缺少官方末级同分数据时使用模型强度破同分；所有结果均为竞猜模型，不是官方赛果。'] },
  ]
  const common = { title:'共同口径', items:['数据基于规则手册实场图与通信协议官方坐标。判罚、撞击和定位覆盖不进入战术得分。','综合强度仅由六维战术事实构成；赛果与对手强度只用于校准同赛区胜率或作为独立证据。'] }
  const byTab = {
    overview:[{ title:'评分阅读', items:['六维图展示全局排名与证据强度；分数表示同批队伍中的相对表现，不等于确定赛果。','赛区名次波动范围来自10组连续赛程删组重算，是样本敏感性范围，不是置信区间，也不参与评分。'] }],
    tactics:[{ title:'动作链口径', items:['阶段画像来自逐秒位置、兵种、发弹、目标伤害、资源与雷达事件；出现率同时展示局数、对手覆盖和红蓝方分层。','双队克制按规则胜负优先级匹配双方能力；低样本降级为规则型备选，历史关联不解释为因果增益。'] }],
    map:[{ title:'热力图编码', items:[`颜色表示 0.5m 网格内累计在场秒数，使用对数色阶；当前筛选最高密度 ${maxHeat.value} 车·秒。`,`官方坐标仅投影到实场图内墙区域；“己方归一化”会按阵营旋转位置。`] }],
    matches:[{ title:'时间轴与坐标', items:['前 10 秒与后 10 秒不计入强度统计，但时间轴保留完整比赛。','全局视图固定红方在左、蓝方在右；己方视图会整体旋转地图和双方机器人。'] }],
    roles:[{ title:'兵种数据', items:['兵种视图支持按造成伤害、目标伤害、在场率、里程和阵亡数排序；推定伤害与事实指标分开标注。'] }],
    discipline:[{ title:'牌色推断', items:['源数据只有判罚扣血，没有牌色字段；牌色按同步扣血比例推断，并保留高、中或未知置信状态。'] }],
    compare:[{ title:'胜率模型', items:['胜率按赛区分别滚动校准：南部降低与目标终局信息重叠的防守权重并提高空间权重；东部同赛区加入 10% 赛程校正赛果；北部继续降低定位噪声较大的空间权重并提高资源转化权重；跨赛区使用全国统一纯六维。透明对手分和直接交手仅作背景。'] }],
  }
  return [common, ...(byTab[teamTab.value] || [])]
})
const eventGroups = ['全部', '交战', '目标', '资源', '装配', '状态', '纪律']
function eventGroup(event) {
  if (event.type === '装配成功') return '装配'
  if (event.type === '受击' || event.type === '发弹') return event.target_type === '基地' || event.target_type === '前哨站' ? '目标' : '交战'
  if (['飞镖命中', '飞镖闸门开'].includes(event.type) || event.target_type === '基地' || event.target_type === '前哨站') return '目标'
  if (['增益', '能量机关', '雷达反制UAV'].includes(event.type)) return '资源'
  if (event.type === '阵亡' || event.type === '恢复在场') return '状态'
  if (String(event.type).includes('牌') || event.category === '判罚') return '纪律'
  return '资源'
}
const replayEvents = computed(() => {
  const regular = gameData.value?.events || []
  const hits = damageEffects.value.map(effect => ({
    second: effect.second, type: '受击', team: effect.target_team, side: effect.target_side,
    robot: effect.target, robot_type: effect.target_type, target_type: effect.target_type,
    category: effect.category, damage: effect.damage, confidence: effect.confidence, evidence: effect.basis,
  }))
  return [...regular, ...hits].sort((first, second) => Number(first.second) - Number(second.second))
})
const filteredReplayEvents = computed(() => replayEvents.value.filter(event => replayEventFilter.value === '全部' || eventGroup(event) === replayEventFilter.value))
const shownEvents = computed(() => filteredReplayEvents.value.filter(event => event.second <= time.value).slice(-80).reverse())
const currentFrame = computed(() => interpolatedFrame(gameData.value?.frames, time.value))
const currentTeamFrame = computed(() => teamFrameAt(gameData.value?.team_frames, time.value))
const teamStatus = computed(() => Object.fromEntries(currentTeamFrame.value.map(row => [row[0], {
  side: row[0], totalCoins: row[1], remainingCoins: row[2], baseHp: row[3], baseMaxHp: row[4], outpostHp: row[5], outpostMaxHp: row[6],
}])))
const currentFacilities = computed(() => (gameData.value?.facilities || []).map(facility => {
  const status = teamStatus.value[facility.side] || {}
  return { ...facility, hp: facility.type === '基地' ? status.baseHp : status.outpostHp, maxHp: facility.type === '基地' ? status.baseMaxHp : status.outpostMaxHp }
}))
const replayNativeHz = computed(() => nativeFrameRate(gameData.value?.frames).toFixed(1))
const activeDamage = computed(() => effectsAt(damageEffects.value, time.value, 1.15).filter(effect => effect.x != null && effect.y != null && (effect.confidence !== 'low' || showLowConfidence.value)))
const activeShots = computed(() => effectsAt(shotEffects.value, time.value, .6))
const recentDamage = computed(() => damageEffects.value.filter(effect => effect.second <= time.value).slice(-12).reverse())
const keyEngagements = computed(() => gameData.value?.engagements || [])
const activeEngagement = computed(() => keyEngagements.value.find(segment => time.value >= segment.start_sec && time.value <= segment.end_sec) || null)
const attributionCoverage = computed(() => {
  const projectile = damageEffects.value.filter(effect => effect.kind === 'projectile')
  const attributed = projectile.filter(effect => effect.shooter_robot_id != null)
  const high = projectile.filter(effect => effect.confidence === 'high')
  return {
    total: projectile.length, attributed: attributed.length, high: high.length,
    attributedPct: projectile.length ? Math.round(1000 * attributed.length / projectile.length) / 10 : 0,
    highPct: projectile.length ? Math.round(1000 * high.length / projectile.length) / 10 : 0,
  }
})
const selectedReplayRow = computed(() => currentFrame.value.find(row => row[0] === selectedReplayRobot.value) || null)
const selectedReplayMeta = computed(() => selectedReplayRobot.value == null ? null : gameData.value?.robots?.[selectedReplayRobot.value])
const assemblyBySide = computed(() => Object.fromEntries(['红', '蓝'].map(side => [side, [1, 2, 3, 4].map(level => ({
  level,
  events: (gameData.value?.events || []).filter(event => event.type === '装配成功' && event.side === side && event.assembly_level === level),
}))])))
const trails = computed(() => {
  if (!gameData.value) return []
  const result = gameData.value.robots.map((robot, i) => ({ robot, i, points: [] }))
  for (const [sec, rows] of gameData.value.frames) if (sec >= time.value - tail.value && sec <= time.value) for (const row of rows) if (row[10] && visibleRobots.value[row[0]] !== false) result[row[0]].points.push(row)
  return result.filter(x => x.points.length)
})
const mapFile = computed(() => mapMode.value === 'vector' ? 'field-vector.svg' : `field-${gameData.value?.map || 'current'}.jpg`)
const heatPlacement = rasterMapPlacement('current')

function heatXY(cell) {
  let x = (cell[3] + .5) / 2, y = (cell[4] + .5) / 2
  const actual = officialToMap(x, y)
  const point = heatView.value === 'canonical' && cell[0] === '蓝' ? teamPerspectivePoint(actual[0], actual[1], '蓝') : actual
  return rasterMapPoint(point[0], point[1], 'current')
}
function frameXY(row) {
  const actual = officialToMap(row[1], row[2])
  const point = routeView.value === 'own' ? teamPerspectivePoint(actual[0], actual[1], activeGame.value?.side) : actual
  return mapMode.value === 'vector' ? point : rasterMapPoint(point[0], point[1], gameData.value?.map || 'current')
}
function effectXY(effect) { return frameXY([0, effect.x, effect.y]) }
function sourceXY(effect) { return frameXY([0, effect.source_x, effect.source_y]) }
function shotEndXY(shot) {
  if (shot.yaw == null) return effectXY(shot)
  const radians = Number(shot.yaw) * Math.PI / 180
  return effectXY({ x: Number(shot.x) + Math.cos(radians) * .9, y: Number(shot.y) + Math.sin(radians) * .9 })
}
function sideTeam(side) { return side === '红' ? gameData.value?.game?.red_team : gameData.value?.game?.blue_team }
function eventTitle(event) {
  if (event.type === '受击') return `${event.category || ''}${event.target_type || event.robot_type || ''}受击 -${event.damage || 0}`
  if (event.type === '装配成功') return `${event.category}装配成功 · 用时${event.assembly_duration_sec ?? '—'}秒`
  return `${event.type}${event.category ? ` · ${event.category}` : ''}`
}
function candidateText(effect) {
  if (effect.shooter_type || !effect.candidates?.length) return ''
  return `候选：${effect.candidates.map(candidate => `${candidate.robot_type} ${candidate.evidence_score ?? '—'}分${candidate.angle_error == null ? '' : ` / ${candidate.angle_error}°`}`).join(' · ')}`
}
function seekEngagement(segment) { time.value = segment.focus_sec; tail.value = Math.max(6, Math.ceil(segment.end_sec - segment.start_sec)) }
function confidenceLabel(value) { return value === 'high' ? '高置信度' : value === 'medium' ? '中置信度' : '低置信度' }
function routeMapTransform() {
  if (routeView.value !== 'own' || activeGame.value?.side !== '蓝') return ''
  const center = mapMode.value === 'vector' ? [14, 7.5] : rasterMapCenter(gameData.value?.map || 'current')
  return `rotate(180 ${center[0]} ${center[1]})`
}
function heatOpacity(cell) {
  return densityOpacity(cell.samples, maxHeat.value)
}
function heatColor(cell) { return cell.side === '红' ? '#ff3b62' : cell.side === '蓝' ? '#00d9ff' : '#ffd166' }
function fmtSecond(value) { const v = Math.max(0, Math.round(value)); return `${Math.floor(v/60)}:${String(v%60).padStart(2,'0')}` }
function show(value, suffix = '') { return value === null || value === undefined ? '—' : `${value}${suffix}` }
function fact(value, suffix = '', digits = 1) { return value === null || value === undefined || !Number.isFinite(Number(value)) ? '—' : `${Number(value).toFixed(digits)}${suffix}` }
function signed(value, suffix = '', digits = 1) { return value === null || value === undefined || !Number.isFinite(Number(value)) ? '—' : `${Number(value) > 0 ? '+' : ''}${Number(value).toFixed(digits)}${suffix}` }
function sampleCount(dimension, component) { return selected.value?.[`${dimension}_analysis`]?.component_samples?.[component] ?? 0 }
function dimensionRankText(dimension) {
  const rank = selected.value?.dimension_ranks?.[dimension]
  return rank ? (rank <= 20 ? `TOP ${rank}` : `第 ${rank}/96`) : '暂无排名'
}
function rankLabel(dimension) {
  const rank = selected.value?.dimension_ranks?.[dimension]
  const evidence = selected.value?.dimension_confidence?.[dimension]
  const ranking = rank ? (rank <= 20 ? `TOP ${rank}` : `第 ${rank}/96`) : '—'
  return evidence == null ? ranking : `${ranking} · 证据 ${Math.round(evidence)}%`
}
function openMethodology() { filtersOpen.value = false; methodologyOpen.value = true }
function toggleFilters() { methodologyOpen.value = false; filtersOpen.value = !filtersOpen.value }
function closeMethodology() {
  methodologyOpen.value = false
  nextTick(() => methodologyTrigger.value?.focus())
}
function toggleTactic(id) {
  const next = new Set(expandedTactics.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedTactics.value = next
}
function toggleAllTactics() {
  expandedTactics.value = allTacticsExpanded.value ? new Set() : new Set(tacticCards.value.map(card => card.id))
}
function togglePattern(id) {
  const next = new Set(expandedPatterns.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedPatterns.value = next
}
async function scrollSelectedTeam() {
  await nextTick()
  const list = teamListNode.value, active = list?.querySelector('.active')
  if (list && active) list.scrollTop = Math.max(0, active.offsetTop - list.clientHeight / 2 + active.clientHeight / 2)
}
function roleValue(value, suffix = '') { return value === null || value === undefined ? '不适用' : `${Number(value).toFixed(Number(value) % 1 ? 1 : 0)}${suffix}` }
function roleSeriesPoints(key) {
  const duration = Math.max(1, Number(activeRoleGame.value?.duration_sec || 0))
  const maximum = key === 'power' ? roleMaxPower.value : 1
  return activeRoleFrames.value.map(frame => `${frame.second / duration * 1000},${210 - Math.max(0, Math.min(1, frame[key] / maximum)) * 190}`).join(' ')
}
function roleFramePoint(frame) {
  if (!frame?.valid) return [0, 0]
  const actual = officialToMap(frame.x, frame.y)
  return rasterMapPoint(actual[0], actual[1], 'current')
}
function fetchData(path, options = {}) {
  const url = `${base}${path}?v=${dataRevision}`
  if (options.signal) return fetch(url, { cache: 'force-cache', signal: options.signal })
  if (!requestCache.has(url)) requestCache.set(url, fetch(url, { cache: 'force-cache' }).then(response => {
    if (!response.ok) throw new Error(`${path} 加载失败`)
    return response
  }).catch(error => { requestCache.delete(url); throw error }))
  return requestCache.get(url).then(response => response.clone())
}
function resourcePath(key, teamSlug = '') {
  const template = dataManifest.value?.resources?.[key]
  return template ? template.replace('{slug}', teamSlug) : null
}
function saveTournament() {
  localStorage.setItem('rmuc-tournament-pickem-3', JSON.stringify({ groups: tournamentGroups.value, rounds: tournamentRounds.value, finalsQualifiers: finalsQualifiers.value, playoffs: tournamentPlayoffs.value, medals: tournamentMedals.value, predictionMode: tournamentPredictionMode.value }))
}
function clearTournamentPostseason(mode = tournamentMode.value) {
  tournamentPlayoffs.value = { ...tournamentPlayoffs.value, [mode]: [] }
  if (mode === 'finals') tournamentMedals.value = { semifinals: [], final: null, bronze: null }
  tournamentOdds.value = { ...tournamentOdds.value, [mode]: [] }
}
function shuffle(values) {
  const result = [...values]
  for (let index = result.length - 1; index > 0; index -= 1) { const target = Math.floor(Math.random() * (index + 1)); [result[index], result[target]] = [result[target], result[index]] }
  return result
}
function randomizeTournament() {
  const config = activeTournament.value
  if (!config) return
  const groups = [[], []]
  for (const tier of [...new Set(config.teams.map(team => team.tier))].sort()) {
    const names = shuffle(config.teams.filter(team => team.tier === tier).map(team => team.team))
    const firstCount = tournamentMode.value === 'finals' ? ({ 1: 2, 2: 1, 3: 2, 4: 1, 5: 2, 6: 8 }[tier] || names.length / 2) : names.length / 2
    groups[0].push(...names.slice(0, firstCount)); groups[1].push(...names.slice(firstCount))
  }
  tournamentGroups.value = { ...tournamentGroups.value, [tournamentMode.value]: groups }
  resetTournamentResults(); saveTournament()
}
function moveTournamentTeam(team, targetIndex) {
  const target = Number(targetIndex), mode = tournamentMode.value, groups = tournamentGroups.value[mode].map(group => [...group])
  const source = groups.findIndex(group => group.includes(team))
  if (source < 0 || source === target) return
  const tier = activeTournament.value.teams.find(item => item.team === team)?.tier
  const displaced = [...groups[target]].reverse().find(name => activeTournament.value.teams.find(item => item.team === name)?.tier === tier)
  if (!displaced) return
  groups[source] = groups[source].map(name => name === team ? displaced : name)
  groups[target] = groups[target].map(name => name === displaced ? team : name)
  tournamentGroups.value = { ...tournamentGroups.value, [mode]: groups }
  resetTournamentResults(); saveTournament()
}
function resetTournamentResults() {
  tournamentRounds.value = { ...tournamentRounds.value, [tournamentMode.value]: { A: [], B: [] } }
  clearTournamentPostseason()
  saveTournament()
}
function startSwissRound(board) {
  const config = activeTournament.value
  const matches = swissNextPairings(board.members, board.rounds, config.win_target, config.loss_target, config.swiss_rounds)
  if (!matches.length) return
  const modeRounds = { ...tournamentRounds.value[tournamentMode.value], [board.label]: [...board.rounds, { round: board.rounds.length + 1, matches }] }
  tournamentRounds.value = { ...tournamentRounds.value, [tournamentMode.value]: modeRounds }; saveTournament()
}
function setSwissWinner(group, roundIndex, matchIndex, winner) {
  const mode = tournamentMode.value
  const groupRounds = tournamentRounds.value[mode][group].slice(0, roundIndex + 1).map((round, index) => index !== roundIndex ? round : { ...round, matches: round.matches.map((match, matchAt) => matchAt === matchIndex ? { ...match, winner } : match) })
  tournamentRounds.value = { ...tournamentRounds.value, [mode]: { ...tournamentRounds.value[mode], [group]: groupRounds } }
  clearTournamentPostseason(mode)
  saveTournament()
}
function autoSwissRound(board) {
  let rounds = tournamentRounds.value[tournamentMode.value][board.label]
  if (!rounds.length || rounds.at(-1).matches.every(match => match.winner)) startSwissRound({ ...board, rounds })
  rounds = tournamentRounds.value[tournamentMode.value][board.label]
  if (!rounds.length || rounds.at(-1).matches.every(match => match.winner)) return
  const index = rounds.length - 1
  rounds[index].matches.forEach((match, matchIndex) => setSwissWinner(board.label, index, matchIndex, predictedWinner(match, tournamentPredictionMode.value)))
}
function playoffMembers(stage) { return stage.entrants.map(name => tournamentTeamMap.value.get(name)).filter(Boolean) }
function playoffStandings(stage) { return doubleEliminationStandings(playoffMembers(stage), stage.rounds, stage.target) }
function playoffFinished(stage) { const standings = playoffStandings(stage); return standings.length > 0 && standings.filter(record => record.status === '晋级').length === stage.target }
function initializePlayoffStage() {
  const mode = tournamentMode.value, stages = tournamentPlayoffs.value[mode]
  if (!tournamentSwissFinished.value || stages.length >= (mode === 'finals' ? 2 : 1)) return
  const entrants = stages.length ? playoffStandings(stages.at(-1)).filter(record => record.status === '晋级').map(record => record.team) : tournamentBoards.value.flatMap(board => board.standings.filter(record => record.status !== '淘汰').map(record => record.team))
  if (stages.length && !playoffFinished(stages.at(-1))) return
  const definition = mode === 'repechage'
    ? { id: 'qualification', title: '全国赛晋级名额争夺战', target: 4 }
    : stages.length === 0 ? { id: 'top16', title: '16 进 8 双败淘汰赛', target: 8 } : { id: 'top8', title: '8 进 4 双败淘汰赛', target: 4 }
  tournamentPlayoffs.value = { ...tournamentPlayoffs.value, [mode]: [...stages, { ...definition, entrants, rounds: [] }] }; saveTournament()
}
function startPlayoffRound(stageIndex) {
  const mode = tournamentMode.value, stages = [...tournamentPlayoffs.value[mode]], stage = stages[stageIndex]
  const matches = doubleEliminationNextPairings(playoffMembers(stage), stage.rounds, stage.target)
  if (!matches.length) return
  stages[stageIndex] = { ...stage, rounds: [...stage.rounds, { round: stage.rounds.length + 1, matches }] }
  tournamentPlayoffs.value = { ...tournamentPlayoffs.value, [mode]: stages }; saveTournament()
}
function setPlayoffWinner(stageIndex, roundIndex, matchIndex, winner) {
  const mode = tournamentMode.value, stages = tournamentPlayoffs.value[mode].slice(0, stageIndex + 1), stage = stages[stageIndex]
  const rounds = stage.rounds.slice(0, roundIndex + 1).map((round, index) => index !== roundIndex ? round : { ...round, matches: round.matches.map((match, matchAt) => matchAt === matchIndex ? { ...match, winner } : match) })
  stages[stageIndex] = { ...stage, rounds }
  tournamentPlayoffs.value = { ...tournamentPlayoffs.value, [mode]: stages }
  if (mode === 'finals') tournamentMedals.value = { semifinals: [], final: null, bronze: null }
  tournamentOdds.value = { ...tournamentOdds.value, [mode]: [] }; saveTournament()
}
function autoPlayoffRound(stageIndex) {
  let stage = tournamentPlayoffs.value[tournamentMode.value][stageIndex]
  if (!stage.rounds.length || stage.rounds.at(-1).matches.every(match => match.winner)) startPlayoffRound(stageIndex)
  stage = tournamentPlayoffs.value[tournamentMode.value][stageIndex]
  if (!stage?.rounds.length || stage.rounds.at(-1).matches.every(match => match.winner)) return
  const roundIndex = stage.rounds.length - 1
  stage.rounds[roundIndex].matches.forEach((match, matchIndex) => setPlayoffWinner(stageIndex, roundIndex, matchIndex, predictedWinner(match, tournamentPredictionMode.value)))
}
function tournamentMatch(first, second, bestOf = 3) {
  const estimate = matchupEstimate(tournamentTeamMap.value.get(first), tournamentTeamMap.value.get(second), [], { stage: '淘汰赛' })
  const firstPct = seriesWinProbability(estimate.primaryPct, bestOf)
  return { first, second, firstPct, secondPct: Math.round((100 - firstPct) * 10) / 10, bestOf, winner: null }
}
function initializeMedals() {
  const last = tournamentPlayoffs.value.finals.at(-1)
  if (!last || !playoffFinished(last) || tournamentMedals.value.semifinals.length) return
  const seeds = playoffStandings(last).filter(record => record.status === '晋级').map(record => record.team)
  tournamentMedals.value = { semifinals: [tournamentMatch(seeds[0], seeds[3]), tournamentMatch(seeds[1], seeds[2])], final: null, bronze: null }; saveTournament()
}
function setMedalWinner(kind, matchIndex, winner) {
  if (kind === 'semifinals') {
    const semifinals = tournamentMedals.value.semifinals.map((match, index) => index === matchIndex ? { ...match, winner } : match)
    let final = null, bronze = null
    if (semifinals.every(match => match.winner)) {
      const finalists = semifinals.map(match => match.winner)
      const losers = semifinals.map(match => match.winner === match.first ? match.second : match.first)
      final = tournamentMatch(finalists[0], finalists[1], 5); bronze = tournamentMatch(losers[0], losers[1], 5)
    }
    tournamentMedals.value = { semifinals, final, bronze }
  } else tournamentMedals.value = { ...tournamentMedals.value, [kind]: { ...tournamentMedals.value[kind], winner } }
  saveTournament()
}
function autoMedals() {
  if (!tournamentMedals.value.semifinals.length) initializeMedals()
  tournamentMedals.value.semifinals.forEach((match, index) => { if (!match.winner) setMedalWinner('semifinals', index, predictedWinner(match, tournamentPredictionMode.value)) })
  for (const kind of ['bronze', 'final']) { const match = tournamentMedals.value[kind]; if (match && !match.winner) setMedalWinner(kind, 0, predictedWinner(match, tournamentPredictionMode.value)) }
}
async function calculateTournamentOdds() {
  tournamentOddsBusy.value = true
  await new Promise(resolve => setTimeout(resolve, 0))
  const groups = tournamentBoards.value.map(board => board.members)
  tournamentOdds.value = { ...tournamentOdds.value, [tournamentMode.value]: monteCarloTournament(groups, activeTournament.value, tournamentMode.value, 2000, Date.now()) }
  tournamentOddsBusy.value = false
}
function simulateCompleteTournament() {
  const mode = tournamentMode.value, config = activeTournament.value, nextRounds = { A: [], B: [] }
  const qualifiers = []
  for (const board of tournamentBoards.value) {
    const rounds = []
    for (let round = 1; round <= config.swiss_rounds; round += 1) {
      const matches = swissNextPairings(board.members, rounds, config.win_target, config.loss_target, config.swiss_rounds)
      for (const match of matches) match.winner = predictedWinner(match, tournamentPredictionMode.value)
      rounds.push({ round, matches })
    }
    nextRounds[board.label] = rounds
    qualifiers.push(...swissStandings(board.members, rounds, config.win_target, config.loss_target, config.swiss_rounds).filter(record => record.status !== '淘汰').map(record => record.team))
  }
  tournamentRounds.value = { ...tournamentRounds.value, [mode]: nextRounds }
  const buildStage = (definition, entrants) => {
    const members = entrants.map(name => tournamentTeamMap.value.get(name)).filter(Boolean), rounds = []
    for (let round = 1; round <= 12; round += 1) {
      const matches = doubleEliminationNextPairings(members, rounds, definition.target)
      if (!matches.length) break
      for (const match of matches) match.winner = predictedWinner(match, tournamentPredictionMode.value)
      rounds.push({ round, matches })
    }
    const qualified = doubleEliminationStandings(members, rounds, definition.target).filter(record => record.status === '晋级').map(record => record.team)
    return [{ ...definition, entrants, rounds }, qualified]
  }
  if (mode === 'repechage') {
    const [stage] = buildStage({ id: 'qualification', title: '全国赛晋级名额争夺战', target: 4 }, qualifiers)
    tournamentPlayoffs.value = { ...tournamentPlayoffs.value, repechage: [stage] }
  } else {
    const [top16, top8Names] = buildStage({ id: 'top16', title: '16 进 8 双败淘汰赛', target: 8 }, qualifiers)
    const [top8, top4Names] = buildStage({ id: 'top8', title: '8 进 4 双败淘汰赛', target: 4 }, top8Names)
    tournamentPlayoffs.value = { ...tournamentPlayoffs.value, finals: [top16, top8] }
    const semifinals = [tournamentMatch(top4Names[0], top4Names[3]), tournamentMatch(top4Names[1], top4Names[2])]
    for (const match of semifinals) match.winner = predictedWinner(match, tournamentPredictionMode.value)
    const finalists = semifinals.map(match => match.winner), losers = semifinals.map(match => match.winner === match.first ? match.second : match.first)
    const final = tournamentMatch(finalists[0], finalists[1], 5), bronze = tournamentMatch(losers[0], losers[1], 5)
    final.winner = predictedWinner(final, tournamentPredictionMode.value); bronze.winner = predictedWinner(bronze, tournamentPredictionMode.value)
    tournamentMedals.value = { semifinals, final, bronze }
  }
  saveTournament()
}
function tournamentDisplay(name) {
  const team = tournamentTeamMap.value.get(name)
  return team?.display_team || name
}
function buildPlaceholder(item, selectedName = null) {
  const selected = tournamentTeams.value.repechage.find(team => team.team === selectedName)
  if (selected) return { ...selected, team: item.team, display_team: selected.team, battle_name: selected.battle_name, tier: item.tier, placeholder: true }
  return { team: item.team, display_team: item.team, battle_name: '待定', tier: item.tier, placeholder: true, region: '待定', summary: { games: 0, win_rate: 50, region: '待定' }, scores: { firepower: 50, objective: 50, spatial: 50, defense: 50, resource: 50, adaptability: 50 }, strength_analysis: { result_score: 50 } }
}
function refreshFinalsPlaceholders() {
  const known = tournamentTeams.value.finals.filter(team => !team.placeholder)
  const placeholders = tournamentConfig.value.finals.teams.filter(team => team.placeholder).map((item, index) => buildPlaceholder(item, finalsQualifiers.value[index]))
  tournamentTeams.value = { ...tournamentTeams.value, finals: [...known, ...placeholders] }
}
function setFinalsQualifier(indexAt, value) {
  finalsQualifiers.value = finalsQualifiers.value.map((name, index) => index === indexAt ? (value || null) : name === value ? null : name)
  refreshFinalsPlaceholders()
  tournamentRounds.value = { ...tournamentRounds.value, finals: { A: [], B: [] } }; clearTournamentPostseason('finals'); saveTournament()
}
async function loadTournament() {
  if (tournamentConfig.value || tournamentBusy.value) return
  tournamentBusy.value = true
  try {
    const response = await fetchData('data/repechage.json')
    if (!response.ok) throw new Error('赛事模拟名单加载失败')
    tournamentConfig.value = await response.json()
    const loaded = {}
    for (const mode of ['repechage', 'finals']) {
      loaded[mode] = await Promise.all(tournamentConfig.value[mode].teams.map(async item => {
        if (item.placeholder) return buildPlaceholder(item)
        const listing = index.value.teams.find(team => team.team === item.team)
        if (!listing) throw new Error(`${item.team} 与战术数据库无法对齐`)
        return { ...listing, battle_name: item.battle_name, tier: item.tier }
      }))
    }
    tournamentTeams.value = loaded
    let restored = null
    try { restored = JSON.parse(localStorage.getItem('rmuc-tournament-pickem-3') || 'null') } catch { restored = null }
    if (restored?.groups?.repechage?.flat().length === 16 && restored?.groups?.finals?.flat().length === 32) {
      tournamentGroups.value = restored.groups; tournamentRounds.value = restored.rounds || tournamentRounds.value; finalsQualifiers.value = restored.finalsQualifiers || finalsQualifiers.value; tournamentPlayoffs.value = restored.playoffs || tournamentPlayoffs.value; tournamentMedals.value = restored.medals || tournamentMedals.value; tournamentPredictionMode.value = restored.predictionMode || 'random'
      refreshFinalsPlaceholders()
    } else { tournamentMode.value = 'repechage'; randomizeTournament(); tournamentMode.value = 'finals'; randomizeTournament(); tournamentMode.value = 'repechage' }
  } finally { tournamentBusy.value = false }
}
function switchTournament(mode) { tournamentMode.value = mode }
async function ensureRoleCatalog() {
  if (roleCatalog.value.roles.length) return
  const response = await fetchData('data/roles/index.json')
  roleCatalog.value = await response.json()
}
async function switchView(mode) {
  viewMode.value = mode; filtersOpen.value = false
  if (mode === 'repechage') await loadTournament()
  if (mode === 'role') {
    await ensureRoleCatalog()
    if (!roleIndex.value) await loadRoleIndex(selectedRoleSlug.value)
  }
  syncLocation()
}
function syncLocation() {
  const currentSlug = slug.value || ''
  const path = viewMode.value === 'team' ? `teams/${currentSlug}/${teamTab.value}` : viewMode.value === 'role' ? `roles/${selectedRoleSlug.value}/${roleTeam.value?.team_slug || ''}` : `pickem/${tournamentMode.value}`
  history.replaceState(null, '', `${location.pathname}${location.search}#/${path}`)
}
function toggleDensity() {
  density.value = density.value === 'comfortable' ? 'compact' : 'comfortable'
  localStorage.setItem('rmuc-density', density.value)
}
async function setTeamTab(tab) {
  teamTab.value = tab
  if (['tactics', 'matches', 'discipline', 'compare'].includes(tab)) await ensureTeamDetail()
  if (tab === 'tactics') {
    await loadTacticalProfile(slug.value)
    if (counterExecutorSlug.value && counterExecutorSlug.value !== slug.value) await loadCounterExecutor(counterExecutorSlug.value)
  }
  if (tab === 'map') await loadHeat()
  if (tab === 'overview') { await nextTick(); scheduleCharts() }
  syncLocation()
}
async function ensureTeamDetail() {
  if (!selected.value?.partial || detailPromise) return detailPromise
  const teamSlug = slug.value
  detailPromise = fetchData(resourcePath('team_detail', teamSlug) || `data/teams/${teamSlug}.json`).then(response => response.json()).then(detail => { selected.value = detail }).finally(() => { detailPromise = null })
  return detailPromise
}
async function fetchTacticalProfile(teamSlug) {
  if (!teamSlug) return null
  const path = resourcePath('team_tactics', teamSlug) || `data/v4/tactics/${teamSlug}.json`
  const response = await fetchData(path)
  const contentType = response.headers.get('content-type') || ''
  if (!contentType.includes('application/json')) {
    requestCache.delete(`${base}${path}?v=${dataRevision}`)
    throw new Error('战术画像返回格式错误，请重启开发服务后重试')
  }
  return response.json()
}
async function loadTacticalProfile(teamSlug) {
  if (!teamSlug || tacticalProfile.value?.slug === teamSlug || loadingTactics.value) return
  loadingTactics.value = true
  tacticalError.value = ''
  try {
    tacticalProfile.value = await fetchTacticalProfile(teamSlug)
    expandedPatterns.value = new Set()
    tacticPhase.value = 'all'
  } catch (loadError) {
    tacticalProfile.value = null
    tacticalError.value = loadError.message || '战术画像加载失败'
  } finally { loadingTactics.value = false }
}
async function loadCounterExecutor(teamSlug) {
  const requestId = ++counterRequestId
  counterExecutorProfile.value = null
  counterExecutorError.value = ''
  loadingCounterExecutor.value = Boolean(teamSlug && teamSlug !== slug.value)
  if (!teamSlug || teamSlug === slug.value) { loadingCounterExecutor.value = false; return }
  localStorage.setItem('rmuc-counter-executor', teamSlug)
  try {
    const profile = await fetchTacticalProfile(teamSlug)
    if (requestId === counterRequestId && counterExecutorSlug.value === teamSlug) counterExecutorProfile.value = profile
  } catch (loadError) {
    if (requestId === counterRequestId) counterExecutorError.value = loadError.message || '执行队伍画像加载失败'
  } finally {
    if (requestId === counterRequestId) loadingCounterExecutor.value = false
  }
}
async function loadHeat() {
  if (!selected.value || heat.value?.team === selected.value.team || loadingHeat.value) return
  loadingHeat.value = true
  try {
    const response = await fetchData(resourcePath('heatmap', slug.value) || `data/heatmaps/${slug.value}.json`)
    heat.value = await response.json()
  } finally { loadingHeat.value = false }
}
async function loadTeam(teamSlug) {
  teamController?.abort(); teamController = new AbortController()
  playing.value = false; gameData.value = null; damageEffects.value = []; shotEffects.value = []; activeGame.value = null; heat.value = null; tacticalProfile.value = null; tacticalError.value = ''; loadingTeam.value = true; filtersOpen.value = false
  try {
    const overviewPath = resourcePath('team_overview', teamSlug) || `data/teams/${teamSlug}.json`
    const teamRes = await fetchData(overviewPath, { signal: teamController.signal })
    if (!teamRes.ok) throw new Error('队伍细粒度数据加载失败')
    selected.value = await teamRes.json(); heatTo.value = selected.value.matches?.length ? Math.max(...selected.value.matches.map(m => m.duration_sec), 420) : 420
    expandedTactics.value = new Set()
    if (counterExecutorSlug.value === teamSlug) { counterExecutorSlug.value = ''; counterExecutorProfile.value = null; localStorage.removeItem('rmuc-counter-executor') }
    syncLocation()
    if (['tactics', 'matches', 'discipline', 'compare'].includes(teamTab.value)) await ensureTeamDetail()
    if (teamTab.value === 'tactics') await loadTacticalProfile(teamSlug)
    if (teamTab.value === 'map') await loadHeat()
    if (teamTab.value === 'overview') { await nextTick(); scheduleCharts() }
    await scrollSelectedTeam()
  } catch (loadError) {
    if (loadError.name !== 'AbortError') error.value = loadError.message
  } finally { loadingTeam.value = false }
}
async function loadGame(game) {
  playing.value = false; activeGame.value = game; loadingGame.value = true; gameError.value = ''; gameData.value = null
  try {
    const response = await fetchData(`data/games/${game.game_id}.json`); if (!response.ok) throw new Error('对局时间轴加载失败')
    gameData.value = normalizeReplayData(await response.json()); damageEffects.value = deriveDamageEffects(gameData.value); shotEffects.value = deriveShotEffects(gameData.value); time.value = 0
    visibleRobots.value = Object.fromEntries(gameData.value.robots.map((_, i) => [i, true])); selectedReplayRobot.value = null; replayEventFilter.value = '全部'; showLowConfidence.value = false
  } catch (loadError) {
    gameError.value = loadError.message || '对局时间轴加载失败'
  } finally { loadingGame.value = false }
}
async function openTacticalEvidence(gameId) {
  const match = selected.value?.matches?.find(item => item.game_id === gameId)
  if (!match) return
  teamTab.value = 'matches'
  await loadGame(match)
  syncLocation()
}
async function loadRoleIndex(roleSlug = selectedRoleSlug.value) {
  await ensureRoleCatalog()
  selectedRoleSlug.value = roleSlug; roleTeam.value = null; activeRoleGameId.value = null; roleTime.value = 0
  const response = await fetchData(`data/roles/${roleSlug}/index.json`)
  if (!response.ok) throw new Error('兵种汇总数据加载失败')
  roleIndex.value = await response.json()
  const validMetrics = Object.keys(roleMetrics).filter(key => roleIndex.value.teams.some(team => team.summary?.[key] !== null && team.summary?.[key] !== undefined && Number.isFinite(Number(team.summary[key]))))
  if (!validMetrics.includes(roleMetric.value)) roleMetric.value = validMetrics[0] || 'availability_pct'
  const first = roleIndex.value.teams.find(team => team.team === '广东工业大学') || roleIndex.value.teams[0]
  if (first) await loadRoleTeam(first.slug)
}
async function loadRoleTeam(teamSlug) {
  const response = await fetchData(`data/roles/${selectedRoleSlug.value}/teams/${teamSlug}.json`)
  if (!response.ok) throw new Error('兵种逐局数据加载失败')
  roleTeam.value = await response.json(); activeRoleGameId.value = roleTeam.value.games?.[0]?.game_id || null; roleTime.value = 0
  await scrollSelectedTeam()
}
function selectRoleGame(game) { activeRoleGameId.value = game.game_id; roleTime.value = 0 }
async function openTeamRole(roleSlug) {
  viewMode.value = 'role'; selectedRoleSlug.value = roleSlug
  await ensureRoleCatalog(); await loadRoleIndex(roleSlug)
  const match = roleIndex.value?.teams?.find(team => team.team === selected.value?.team)
  if (match) await loadRoleTeam(match.slug)
  syncLocation()
}
function togglePlay() { playing.value = !playing.value }
function tick(now) {
  if (!playing.value || !gameData.value) return
  if (!previousFrame) previousFrame = now
  const delta = Math.min(.1, (now - previousFrame) / 1000); previousFrame = now
  time.value += delta * speed.value
  if (time.value >= gameData.value.game.duration_sec) { time.value = gameData.value.game.duration_sec; playing.value = false; return }
  animationFrame = requestAnimationFrame(tick)
}
async function chartApi() {
  if (!chartApiPromise) chartApiPromise = import('./charts.js')
  return chartApiPromise
}
function scheduleCharts() {
  if (idleChart) {
    if ('cancelIdleCallback' in window) cancelIdleCallback(idleChart)
    else clearTimeout(idleChart)
  }
  const run = () => renderCharts()
  idleChart = 'requestIdleCallback' in window ? requestIdleCallback(run, { timeout: 1200 }) : setTimeout(run, 240)
}
async function renderCharts() {
  if (!selected.value) return
  const scoreNode = document.getElementById('score-chart'), damageNode = document.getElementById('damage-chart')
  if (!scoreNode || !damageNode) return
  const { init } = await chartApi()
  scoreChart?.dispose(); damageChart?.dispose()
  scoreChart = init(scoreNode); const keys = ['firepower','objective','spatial','defense','resource','adaptability']
  const labels = ['净战斗火力','目标转化','空间控制','防守韧性','资源转化','适应能力']
  const narrow = window.innerWidth < 600
  scoreChart.setOption({radar:{center:['50%','52%'],radius:narrow?'43%':'57%',indicator:labels.map((name,index)=>({name:`${name}\n${rankLabel(keys[index])}`,max:100})),axisName:{color:'#cbd5e1',fontSize:narrow?10:13},splitArea:{areaStyle:{color:['#13233a','#0e1a2d']}}},series:[{type:'radar',data:[{value:keys.map(k=>selected.value.scores[k])}],areaStyle:{color:'#22d3ee66'},lineStyle:{color:'#22d3ee'}}],textStyle:{color:'#cbd5e1'}})
  damageChart = init(damageNode); const damage = selected.value.damage_breakdown.slice(0,12)
  damageChart.setOption({grid:{left:narrow?112:120,right:25,top:20,bottom:30},xAxis:{type:'value',axisLabel:{color:'#94a3b8',fontSize:narrow?9:12,formatter:value=>value>=1000?`${Math.round(value/1000)}k`:value}},yAxis:{type:'category',data:damage.map(d=>`${d.target_type}·${d.source_type}`).reverse(),axisLabel:{color:'#cbd5e1',fontSize:narrow?10:12}},series:[{type:'bar',data:damage.map(d=>d.damage).reverse(),itemStyle:{color:'#f59e0b'}}],tooltip:{trigger:'axis'}})
}
watch(playing, value => {
  cancelAnimationFrame(animationFrame); previousFrame = 0
  if (value) animationFrame = requestAnimationFrame(tick)
})
watch(compareSlug, async value => {
  compareController?.abort(); compareController = new AbortController(); compareTeam.value = null
  if (!value) return
  try { compareTeam.value = await (await fetchData(`data/teams/${value}.json`, { signal: compareController.signal })).json() } catch (loadError) { if (loadError.name !== 'AbortError') error.value = loadError.message }
})
watch(counterExecutorSlug, async value => {
  await loadCounterExecutor(value)
})
watch([filtersOpen, methodologyOpen], values => document.documentElement.classList.toggle('drawer-lock', values.some(Boolean)))
onMounted(async () => {
  try {
    try { dataManifest.value = await (await fetchData('data/v4/manifest.json')).json() } catch { dataManifest.value = null }
    const teamResponse = await fetchData(resourcePath('catalog') || 'data/index.json'); index.value = await teamResponse.json()
    const hashParts = location.hash.replace(/^#\//, '').split('/'), requestedSlug = hashParts[0] === 'teams' ? hashParts[1] : null, requestedTab = hashParts[0] === 'teams' ? hashParts[2] : null
    if (teamTabs.some(([key]) => key === requestedTab)) teamTab.value = requestedTab
    const first = index.value.teams.find(team => team.slug === requestedSlug) || index.value.teams.find(team => team.team === '广东工业大学') || rankedTeams.value[0]
    if (first) await loadTeam(first.slug)
  } catch(e) { error.value=e.message }
})
onBeforeUnmount(() => { document.documentElement.classList.remove('drawer-lock'); cancelAnimationFrame(animationFrame); if ('cancelIdleCallback' in window) cancelIdleCallback(idleChart); else clearTimeout(idleChart); teamController?.abort(); compareController?.abort(); scoreChart?.dispose(); damageChart?.dispose() })
</script>

<template>
<div class="app" :data-density="density">
  <header class="topbar">
    <button class="brand-lockup" @click="switchView('team')"><span>RM</span><strong>战术情报库</strong><small>2026</small></button>
    <nav aria-label="主导航"><button :class="{active:viewMode==='team'}" @click="switchView('team')">队伍分析</button><button :class="{active:viewMode==='role'}" @click="switchView('role')">兵种数据</button><button :class="{active:viewMode==='repechage'}" @click="switchView('repechage')">赛事模拟</button></nav>
    <div class="top-actions"><span class="data-status">96 队 · 秒级数据</span><button class="density-toggle" @click="toggleDensity">{{density==='comfortable'?'切换紧凑':'切换舒适'}}</button><button ref="methodologyTrigger" class="methodology-trigger" @click="openMethodology">数据口径</button><button class="mobile-filter-button" @click="toggleFilters">筛选</button></div>
  </header>
  <button v-if="filtersOpen" class="aside-backdrop" aria-label="关闭筛选" @click="filtersOpen=false"></button>
  <div class="shell">
  <aside :class="{open:filtersOpen}"><div class="aside-title"><b>{{viewMode==='team'?'队伍检索':viewMode==='role'?'兵种检索':'赛事进度'}}</b><button @click="filtersOpen=false">关闭</button></div><template v-if="viewMode==='team'"><label class="field-label">搜索队伍<input v-model="query" placeholder="输入学校名称"></label><label class="field-label">赛区<select v-model="region"><option>全部</option><option>南部赛区</option><option>东部赛区</option><option>北部赛区</option></select></label><div class="filter-meta"><span>{{teams.length}} 支队伍</span><span>按综合强度排序</span></div><div ref="teamListNode" class="team-list"><button v-for="t in teams" :key="t.slug" :class="{active:selected?.team===t.team}" @click="loadTeam(t.slug)"><span>{{t.team}}</span><small>{{regionalRankLabel(t)}} · {{t.wins}}/{{t.games}} · {{t.region}}</small><em><template v-if="t.placement">{{t.placement.label}} · </template>强度 {{strengthGrade(teamStrength(t))}} {{teamStrength(t).toFixed(1)}}</em></button></div></template><template v-else-if="viewMode==='role'"><label class="field-label">兵种<select :value="selectedRoleSlug" @change="loadRoleIndex($event.target.value)"><option v-for="role in roleCatalog.roles" :key="role.role_slug" :value="role.role_slug">{{role.role}}</option></select></label><label class="field-label">排序指标<select v-model="roleMetric"><option v-for="([key,definition]) in availableRoleMetrics" :key="key" :value="key">{{definition.label}}</option></select></label><label class="field-label">搜索队伍<input v-model="roleQuery" placeholder="输入学校名称"></label><label class="field-label">赛区<select v-model="roleRegion"><option>全部</option><option>南部赛区</option><option>东部赛区</option><option>北部赛区</option></select></label><div class="team-list"><button v-for="t in roleTeams" :key="t.slug" :class="{active:roleTeam?.team===t.team}" @click="loadRoleTeam(t.slug)"><span>{{t.team}}</span><small>#{{t.factRank}} · {{t.region}}</small><em>{{roleMetrics[roleMetric].label}} {{roleValue(t.factValue,roleMetrics[roleMetric].suffix)}}</em></button></div></template><template v-else><div class="pick-sidebar"><b>赛事模拟</b><button :class="{active:tournamentMode==='repechage'}" @click="switchTournament('repechage')">复活赛 · 16 队</button><button :class="{active:tournamentMode==='finals'}" @click="switchTournament('finals')">全国赛 · 32 队</button><span v-for="board in tournamentBoards" :key="board.label">{{board.label}}组 · {{board.rounds.length}} / {{activeTournament?.swiss_rounds||0}} 轮</span><small>分组、赛果保存在当前浏览器</small></div></template></aside>
  <main v-if="viewMode==='repechage'" class="pickem-main">
    <p v-if="tournamentBusy && !tournamentConfig">正在加载赛事名单与胜率模型…</p>
    <template v-else-if="activeTournament">
      <div class="tournament-switch"><button :class="{active:tournamentMode==='repechage'}" @click="switchTournament('repechage')">复活赛</button><button :class="{active:tournamentMode==='finals'}" @click="switchTournament('finals')">全国赛</button></div>
      <header><div><p>{{activeTournament.dates}} · {{activeTournament.format}} · {{index.matchup_validation?.series?.samples||'—'}} 场系列赛回测</p><h1>{{activeTournament.title}}赛事模拟 <span class="trust-badge">模拟 · 非官方</span></h1></div><div class="tournament-actions"><button class="random-button primary" @click="simulateCompleteTournament">一键推演完整赛事</button><button class="random-button" :disabled="tournamentOddsBusy" @click="calculateTournamentOdds">{{tournamentOddsBusy?'正在模拟…':'运行 2,000 次概率模拟'}}</button><details class="tournament-more"><summary>更多操作</summary><div><label>预测模式<select v-model="tournamentPredictionMode" @change="saveTournament"><option value="random">概率模拟（可爆冷）</option><option value="favorite">最高概率路径</option></select></label><button class="random-button" @click="randomizeTournament">重新模拟抽签</button><button class="random-button secondary" @click="resetTournamentResults">重置赛果</button></div></details></div></header>
      <section v-if="tournamentMode==='finals'" class="panel qualifier-panel"><div class="section-head"><h2>填入 4 支复活赛晋级队</h2><span>未确定时可保留占位队</span></div><div class="qualifier-selects"><label v-for="(_,indexAt) in finalsQualifiers" :key="indexAt">晋级队 {{indexAt+1}}<select :value="finalsQualifiers[indexAt]||''" @change="setFinalsQualifier(indexAt,$event.target.value)"><option value="">待定</option><option v-for="team in tournamentTeams.repechage" :key="team.team" :value="team.team">{{team.team}} · {{team.battle_name}}</option></select></label></div></section>
      <section v-if="activeTournamentOdds.length" class="panel odds-panel"><div class="section-head"><h2>全赛事蒙特卡洛概率</h2><span>2,000 次 · 每场按显示胜率随机抽样</span></div><div class="odds-table"><div class="odds-row odds-head"><b>队伍</b><span>瑞士轮出线</span><span>{{tournamentMode==='repechage'?'全国赛资格':'八强'}}</span><span v-if="tournamentMode==='finals'">四强</span><span v-if="tournamentMode==='finals'">冠军</span></div><div v-for="row in activeTournamentOdds" :key="row.team" class="odds-row"><b>{{tournamentDisplay(row.team)}}</b><span>{{row.swissPct}}%</span><span>{{tournamentMode==='repechage'?row.qualifyPct:row.top8Pct}}%</span><span v-if="tournamentMode==='finals'">{{row.top4Pct}}%</span><strong v-if="tournamentMode==='finals'">{{row.championPct}}%</strong></div></div></section>
      <section class="pickem-grid">
        <article v-for="(board,groupIndex) in tournamentBoards" :key="board.label" class="panel pick-group swiss-board">
          <div class="section-head"><h2>{{board.label}} 组</h2><span>{{board.members.length}} 队 · {{activeTournament.swiss_rounds}} 轮</span></div>
          <div class="draw-list">
            <div v-for="team in board.members" :key="team.team" class="pick-team">
              <div class="pick-team-main"><b>{{tournamentDisplay(team.team)}}</b><small>{{team.battle_name}} · 第{{team.tier}}档 · {{team.placeholder?'资格占位':`全局 #${team.overall_rank}`}}</small><span>模型强度 <strong>{{teamStrength(team).toFixed(1)}}</strong> · {{board.standings.find(item=>item.team===team.team)?.wins||0}}–{{board.standings.find(item=>item.team===team.team)?.losses||0}} · {{board.standings.find(item=>item.team===team.team)?.status}}</span></div>
              <select :value="groupIndex" :aria-label="`${tournamentDisplay(team.team)}分组`" @change="moveTournamentTeam(team.team,$event.target.value)"><option v-for="(_,target) in tournamentLabels" :key="target" :value="target">{{tournamentLabels[target]}}组</option></select>
            </div>
          </div>
          <div class="round-actions"><button v-if="!board.rounds.length" @click="startSwissRound(board)">生成第 1 轮对阵</button><button v-else-if="board.rounds.length<activeTournament.swiss_rounds && board.rounds.at(-1).matches.every(match=>match.winner)" @click="startSwissRound(board)">生成第 {{board.rounds.length+1}} 轮对阵</button><button v-if="board.rounds.length<activeTournament.swiss_rounds || board.rounds.some(round=>round.matches.some(match=>!match.winner))" @click="autoSwissRound(board)">{{tournamentPredictionMode==='random'?'概率模拟本轮':'预测本轮热门胜出'}}</button></div>
          <div class="swiss-rounds">
            <section v-for="(round,roundIndex) in board.rounds" :key="round.round" class="swiss-round"><h3>第 {{round.round}} 轮</h3><div v-for="(match,matchIndex) in round.matches" :key="`${match.first}-${match.second}`" class="swiss-match"><button :class="{winner:match.winner===match.first}" @click="setSwissWinner(board.label,roundIndex,matchIndex,match.first)"><span>{{tournamentDisplay(match.first)}}</span><strong>{{match.firstPct}}%</strong></button><em>BO3</em><button :class="{winner:match.winner===match.second}" @click="setSwissWinner(board.label,roundIndex,matchIndex,match.second)"><strong>{{match.secondPct}}%</strong><span>{{tournamentDisplay(match.second)}}</span></button></div></section>
          </div>
          <details class="standings" open><summary>实时积分榜</summary><div v-for="(record,rankAt) in board.standings" :key="record.team" :class="['standing-row',record.status]"><b>#{{rankAt+1}} {{tournamentDisplay(record.team)}}</b><span>{{record.wins}}胜 {{record.losses}}负 · 对手分 {{record.opponentScore>0?'+':''}}{{record.opponentScore}}</span><em>{{record.status}}</em></div></details>
        </article>
      </section>
      <section class="postseason">
        <div class="stage-transition"><button v-if="tournamentSwissFinished && !activePlayoffStages.length" class="random-button" @click="initializePlayoffStage">生成{{tournamentMode==='repechage'?'全国赛名额争夺战':'16 进 8 双败赛'}}</button><button v-else-if="tournamentMode==='finals' && activePlayoffStages.length===1 && playoffFinished(activePlayoffStages[0])" class="random-button" @click="initializePlayoffStage">生成 8 进 4 双败赛</button><button v-else-if="tournamentMode==='finals' && activePlayoffStages.length===2 && playoffFinished(activePlayoffStages[1]) && !tournamentMedals.semifinals.length" class="random-button" @click="initializeMedals">生成半决赛</button></div>
        <article v-for="(stage,stageIndex) in activePlayoffStages" :key="stage.id" class="panel playoff-stage"><div class="section-head"><h2>{{stage.title}}</h2><span>BO3 · 两败淘汰 · {{stage.target}} 队晋级</span></div><div class="round-actions"><button v-if="!playoffFinished(stage) && (!stage.rounds.length || stage.rounds.at(-1).matches.every(match=>match.winner))" @click="startPlayoffRound(stageIndex)">生成第 {{stage.rounds.length+1}} 轮</button><button v-if="!playoffFinished(stage)" @click="autoPlayoffRound(stageIndex)">{{tournamentPredictionMode==='random'?'概率模拟本轮':'预测本轮热门胜出'}}</button></div><div class="playoff-round-grid"><section v-for="(round,roundIndex) in stage.rounds" :key="round.round" class="swiss-round"><h3>双败第 {{round.round}} 轮</h3><div v-for="(match,matchIndex) in round.matches" :key="`${match.first}-${match.second}`" class="swiss-match"><button :class="{winner:match.winner===match.first}" @click="setPlayoffWinner(stageIndex,roundIndex,matchIndex,match.first)"><span>{{tournamentDisplay(match.first)}}</span><strong>{{match.firstPct}}%</strong></button><em>BO3</em><button :class="{winner:match.winner===match.second}" @click="setPlayoffWinner(stageIndex,roundIndex,matchIndex,match.second)"><strong>{{match.secondPct}}%</strong><span>{{tournamentDisplay(match.second)}}</span></button></div></section></div><details class="standings" open><summary>双败实时状态</summary><div v-for="record in playoffStandings(stage)" :key="record.team" :class="['standing-row',record.status]"><b>{{tournamentDisplay(record.team)}}</b><span>{{record.wins}}胜 · {{record.losses}}负</span><em>{{record.status}}</em></div></details></article>
        <article v-if="tournamentMode==='finals' && tournamentMedals.semifinals.length" class="panel medal-stage"><div class="section-head"><h2>四强决赛阶段</h2><span>半决赛 BO3 · 季军赛/决赛 BO5</span></div><div class="round-actions"><button @click="autoMedals">{{tournamentPredictionMode==='random'?'概率模拟剩余奖牌赛':'预测热门赢得奖牌赛'}}</button></div><div class="medal-grid"><section><h3>半决赛</h3><div v-for="(match,indexAt) in tournamentMedals.semifinals" :key="indexAt" class="swiss-match"><button :class="{winner:match.winner===match.first}" @click="setMedalWinner('semifinals',indexAt,match.first)"><span>{{tournamentDisplay(match.first)}}</span><strong>{{match.firstPct}}%</strong></button><em>BO3</em><button :class="{winner:match.winner===match.second}" @click="setMedalWinner('semifinals',indexAt,match.second)"><strong>{{match.secondPct}}%</strong><span>{{tournamentDisplay(match.second)}}</span></button></div></section><section v-if="tournamentMedals.bronze"><h3>季军争夺战</h3><div class="swiss-match"><button :class="{winner:tournamentMedals.bronze.winner===tournamentMedals.bronze.first}" @click="setMedalWinner('bronze',0,tournamentMedals.bronze.first)"><span>{{tournamentDisplay(tournamentMedals.bronze.first)}}</span><strong>{{tournamentMedals.bronze.firstPct}}%</strong></button><em>BO5</em><button :class="{winner:tournamentMedals.bronze.winner===tournamentMedals.bronze.second}" @click="setMedalWinner('bronze',0,tournamentMedals.bronze.second)"><strong>{{tournamentMedals.bronze.secondPct}}%</strong><span>{{tournamentDisplay(tournamentMedals.bronze.second)}}</span></button></div></section><section v-if="tournamentMedals.final"><h3>冠军争夺战</h3><div class="swiss-match championship"><button :class="{winner:tournamentMedals.final.winner===tournamentMedals.final.first}" @click="setMedalWinner('final',0,tournamentMedals.final.first)"><span>{{tournamentDisplay(tournamentMedals.final.first)}}</span><strong>{{tournamentMedals.final.firstPct}}%</strong></button><em>BO5</em><button :class="{winner:tournamentMedals.final.winner===tournamentMedals.final.second}" @click="setMedalWinner('final',0,tournamentMedals.final.second)"><strong>{{tournamentMedals.final.secondPct}}%</strong><span>{{tournamentDisplay(tournamentMedals.final.second)}}</span></button></div><p v-if="tournamentMedals.final.winner" class="champion-result">🏆 模拟冠军：{{tournamentDisplay(tournamentMedals.final.winner)}}</p></section></div></article>
      </section>
    </template>
  </main>
  <main v-else-if="viewMode==='role' && roleTeam && roleIndex" class="role-main">
    <header><div><p>{{roleTeam.region}} · {{roleTeam.mode==='second'?'完整秒级状态':'完整事件记录'}}</p><h1>{{roleTeam.team}} · {{roleTeam.role}} <span class="trust-badge">伤害推定</span></h1></div><details class="export-menu"><summary>导出数据</summary><div><a :href="`${base}${roleIndex.downloads.csv_gz}`">CSV.gz</a><a :href="`${base}${roleIndex.downloads.json_gz}`">JSON.gz</a></div></details></header>
    <template v-if="roleTeam.mode==='second'">
      <section class="kpis"><article><span>推定场均伤害</span><strong>{{roleValue(roleTeam.summary.estimated_damage_per_game)}}</strong></article><article><span>推定基地伤害/局</span><strong>{{roleValue(roleTeam.summary.estimated_base_damage_per_game)}}</strong></article><article><span>推定前哨伤害/局</span><strong>{{roleValue(roleTeam.summary.estimated_outpost_damage_per_game)}}</strong></article><article><span>归因置信度</span><strong>{{roleValue(roleTeam.summary.estimated_damage_confidence_pct,'%')}}</strong></article></section>
      <details class="panel role-fact-details"><summary>查看全部事实指标</summary><div class="metric-pairs role-facts"><span>参赛覆盖<strong>{{roleTeam.summary.role_present_games}} / {{roleTeam.summary.games}} 局</strong></span><span>有效在场率<strong>{{roleValue(roleTeam.summary.availability_pct,'%')}}</strong></span><span>场均阵亡<strong>{{roleValue(roleTeam.summary.deaths_per_game)}}</strong></span><span>平均终局血量<strong>{{roleValue(roleTeam.summary.terminal_hp_pct,'%')}}</strong></span><span>场均里程<strong>{{roleValue(roleTeam.summary.distance_per_game_m,' m')}}</strong></span><span>推进纵深<strong>{{roleValue(roleTeam.summary.attack_depth_m,' m')}}</strong></span><span>前压在场<strong>{{roleValue(roleTeam.summary.forward_presence_pct,'%')}}</strong></span><span>场均发弹<strong>{{roleValue(roleTeam.summary.shots_per_game)}}</strong></span><span>推定机器人伤害/局<strong>{{roleValue(roleTeam.summary.estimated_robot_damage_per_game)}}</strong></span><span>高置信推定伤害<strong>{{roleValue(roleTeam.summary.high_confidence_estimated_damage)}}</strong></span><span>每存活分钟净承伤<strong>{{roleValue(roleTeam.summary.combat_damage_per_alive_min)}}</strong></span><span>定位覆盖<strong>{{roleValue(roleTeam.summary.position_coverage_pct,'%')}}</strong></span></div></details>
      <section class="panel"><div class="section-head"><h2>逐局兵种表现</h2><span>{{roleTeam.games.length}} 局</span></div><div class="role-game-table"><div class="role-game-head"><b>赛果 / 对手</b><span>阵营</span><span>推定伤害</span><span>置信度</span><span>基地</span><span>前哨</span><span>机器人</span></div><button v-for="game in roleTeam.games" :key="game.game_id" :class="{active:activeRoleGame?.game_id===game.game_id}" @click="selectRoleGame(game)"><b><em :class="game.won?'won':'lost'">{{game.won?'胜':'负'}}</em>{{game.opponent}}</b><span data-label="阵营">{{game.side}}方</span><span data-label="推定伤害">{{roleValue(game.summary.estimated_damage_dealt)}}</span><span data-label="置信度">{{roleValue(game.summary.estimated_damage_confidence_pct,'%')}}</span><span data-label="基地">{{roleValue(game.summary.estimated_base_damage)}}</span><span data-label="前哨">{{roleValue(game.summary.estimated_outpost_damage)}}</span><span data-label="机器人">{{roleValue(game.summary.estimated_robot_damage)}}</span></button></div></section>
      <section v-if="activeRoleGame" class="grid-two role-telemetry"><article class="panel"><div class="section-head"><h2>血量 / 热量 / 功率时间线</h2><span>{{fmtSecond(roleTime)}} / {{fmtSecond(activeRoleGame.duration_sec)}}</span></div><input class="scrubber" type="range" min="0" :max="activeRoleGame.duration_sec" step="1" v-model.number="roleTime"><svg class="role-line" viewBox="0 0 1000 220" preserveAspectRatio="none"><line x1="0" y1="210" x2="1000" y2="210"/><polyline :points="roleSeriesPoints('hpRatio')" class="hp-line"/><polyline :points="roleSeriesPoints('heatRatio')" class="heat-line"/><polyline :points="roleSeriesPoints('power')" class="power-line"/></svg><div class="role-line-legend"><span class="hp">血量 {{roleValue((roleCurrentFrame?.hpRatio||0)*100,'%')}}</span><span class="heat">热量 {{roleValue((roleCurrentFrame?.heatRatio||0)*100,'%')}}</span><span class="power">功率 {{roleValue(roleCurrentFrame?.power)}}</span></div></article><article class="panel"><div class="section-head"><h2>完整比赛轨迹</h2><span>官方坐标投影</span></div><svg class="field" viewBox="0 0 28 15"><image :href="`${base}maps/field-current.jpg`" width="28" height="15" preserveAspectRatio="none" opacity=".72"/><polyline :points="roleTrailPoints" fill="none" stroke="#f8d66d" stroke-width=".08"/><circle v-if="roleCurrentFrame?.valid" :cx="roleFramePoint(roleCurrentFrame)[0]" :cy="roleFramePoint(roleCurrentFrame)[1]" r=".2" fill="#22d3ee" stroke="white" stroke-width=".04"/></svg></article></section>
    </template>
    <template v-else><section class="kpis"><article><span>飞镖命中</span><strong>{{roleTeam.summary.hits}}</strong></article><article><span>累计伤害</span><strong>{{roleTeam.summary.damage}}</strong></article><article><span>命中覆盖</span><strong>{{roleValue(roleTeam.summary.hit_game_pct,'%')}}</strong></article><article><span>首命中中位</span><strong>{{roleTeam.summary.median_first_hit_sec==null?'—':fmtSecond(roleTeam.summary.median_first_hit_sec)}}</strong></article></section><section class="panel"><div class="section-head"><h2>逐局飞镖事件</h2><span>飞镖无连续状态，仅展示闸门与命中</span></div><div class="radar-events dart-events"><div><button v-for="game in roleTeam.games.filter(game=>game.events.length)" :key="game.game_id"><b>局 {{game.game_id}} · {{game.won?'胜':'负'}}</b><span>对手 {{game.opponent}} · {{game.side}}方</span><span>闸门 {{game.summary.gate_events}} · 命中 {{game.summary.hits}} · 伤害 {{game.summary.damage}}</span></button></div></div></section></template>
  </main>
  <main v-else-if="selected" :aria-busy="loadingTeam">
    <nav class="team-tabs" aria-label="队伍详情"><button v-for="([key,label]) in teamTabs" :key="key" :class="{active:teamTab===key}" @click="setTeamTab(key)">{{label}}</button></nav>
    <div v-if="loadingTeam" class="loading-bar"><span></span></div>
    <template v-if="teamTab==='overview'">
    <header><div><p>{{selected.summary.region}} <em v-if="selected.placement">{{selected.summary.region}}{{selected.placement.label}}</em></p><h1>{{selected.team}}</h1></div><div class="record"><strong>{{selected.summary.wins}}–{{selected.summary.games-selected.summary.wins}}</strong><span>胜率 {{selected.summary.win_rate.toFixed(1)}}% · {{regionalRankLabel(selected, true)}}</span></div></header>
    <section class="kpis"><article><span>场均输出</span><strong>{{selected.summary.avg_damage_dealt?.toFixed(0)}}</strong></article><article><span>场均基地伤害</span><strong>{{selected.summary.avg_base_damage?.toFixed(0)}}</strong></article><article><span>场均前哨伤害</span><strong>{{selected.summary.avg_outpost_damage?.toFixed(0)}}</strong></article><article><span>综合强度评级</span><strong class="strength-grade" :data-grade="grade">{{grade}} · {{strength.toFixed(1)}}</strong></article></section>
    <section class="grid-two"><article class="panel"><div class="section-head"><h2>战术分维度评分</h2><span>全局排名与证据强度</span></div><div id="score-chart" class="chart"></div><div class="mobile-dimension-list"><article v-for="dimension in dimensionCards" :key="dimension.key"><span>{{dimension.label}}</span><strong>{{show(dimension.score)}}</strong><small>{{rankLabel(dimension.key)}}</small><i><span :style="{width:`${dimension.score||0}%`}"></span></i></article></div></article><article class="panel"><div class="section-head"><h2>基地与其他目标伤害来源</h2><span>累计伤害</span></div><div id="damage-chart" class="chart"></div></article></section>
    </template>
    <section v-if="teamTab==='tactics'" class="panel">
      <div class="section-head tactic-section-head"><h2>高维战术解析 4.0</h2><button @click="toggleAllTactics">{{allTacticsExpanded?'收起全部':'展开全部'}}</button></div>
      <div class="insight-grid">
        <TacticDimensionCard v-for="card in tacticCards" :key="card.id" :card="card" :expanded="expandedTactics.has(card.id)" @toggle="toggleTactic(card.id)"/>
        <article class="insight-card"><h3>雷达反制 UAV</h3><div class="metric-pairs"><span>发起反制<strong>{{dimensions.radar?.counter_uses||0}} 次</strong></span><span>使用覆盖<strong>{{dimensions.radar?.counter_use_games||0}} 局 / {{show(dimensions.radar?.counter_use_game_pct,'%')}}</strong></span><span>中位触发<strong>{{dimensions.radar?.median_counter_sec==null?'—':fmtSecond(dimensions.radar.median_counter_sec)}}</strong></span><span>90 秒内使用<strong>{{show(dimensions.radar?.early_counter_pct,'%')}}</strong></span><span>己方空中被反制<strong>{{dimensions.radar?.countered_events||0}} 次</strong></span><span>涉及对局<strong>{{dimensions.radar?.countered_games||0}} 局</strong></span></div></article>
        <article class="insight-card strength-card">
          <h3>综合强度 4.0 · {{show(dimensions.strength?.score)}}</h3>
          <div class="metric-pairs"><span>六维战术<strong>{{show(dimensions.strength?.tactical_score)}}</strong></span><span>赛程校正赛果（独立证据）<strong>{{show(dimensions.strength?.result_score)}}</strong></span><span>原始胜率<strong>{{show(dimensions.strength?.raw_win_rate_pct,'%')}}</strong></span><span>对手校正参数<strong>{{show(dimensions.strength?.schedule_rating)}}</strong></span><span>赛程难度证据<strong>{{show(dimensions.opponentScore?.score)}} · 赛区第 {{show(dimensions.opponentScore?.region_rank)}}/{{show(dimensions.opponentScore?.region_size)}}</strong></span><span>对手去直接交手胜率<strong>{{show(dimensions.opponentScore?.opponent_win_rate_pct,'%')}}</strong></span><span>二阶对手胜率<strong>{{show(dimensions.opponentScore?.opponent_opponent_win_rate_pct,'%')}}</strong></span><span>数据置信度<strong>{{show(dimensions.confidence?.overall,'%')}}</strong></span></div>
          <details v-if="dimensions.opponentScore?.breakdown?.length" class="opponent-breakdown"><summary>逐个对手校正证据（{{dimensions.opponentScore.breakdown.length}}队）</summary><div><span v-for="opponent in dimensions.opponentScore.breakdown" :key="opponent.opponent"><b>{{opponent.opponent}}</b><small>交手 {{opponent.meetings}} 局 · 排除直接交手后 {{opponent.opponent_other_wins}}/{{opponent.opponent_other_games}} · 平滑胜率 {{opponent.adjusted_win_rate_pct}}% · 二阶 {{opponent.second_order_pct}}%</small></span></div><p>Bradley–Terry 赛果分独立展示；综合强度不重复叠加历史胜负或赛程难度。</p></details>
        </article>
      </div>
      <details v-if="dimensions.objective.outpostTimeline.length" class="radar-events outpost-events"><summary>展开逐局前哨击打时间线（{{dimensions.objective.outpostTimeline.length}} 局）</summary><div><button v-for="event in dimensions.objective.outpostTimeline" :key="event.gameId" @click="loadGame(selected.matches.find(match=>match.game_id===event.gameId))"><b>局 {{event.gameId}} · 首伤 {{fmtSecond(event.firstDamageSec)}}</b><span>{{event.won?'胜':'负'}} · {{event.side}}方 · 对手 {{event.opponent}}</span><span>累计前哨伤害 {{event.damage}} · {{event.destroySec==null?'未摧毁':'击毁 '+fmtSecond(event.destroySec)+' · 耗时 '+fmtSecond(event.killDurationSec)}}</span></button></div></details>
      <details v-if="dimensions.radar?.events?.length" class="radar-events"><summary>展开雷达事件时间线（{{dimensions.radar.events.length}} 条，含发起与被反制）</summary><div><button v-for="(event,i) in dimensions.radar.events" :key="event.game_id+'-'+event.second+'-'+event.role+'-'+i" @click="loadGame(selected.matches.find(match=>match.game_id===event.game_id))"><b>局 {{event.game_id}} · {{fmtSecond(event.second)}} · {{event.role}}</b><span>对手：{{event.opponent}}</span></button></div></details>
    </section>
    <section v-if="teamTab==='tactics'" class="panel tactical-mode-panel">
      <div class="section-head"><div><h2>分阶段打法</h2><span v-if="tacticalProfile">{{tacticalProfile.sample.games}}局 · {{tacticalProfile.sample.opponents}}个对手 · 17类打法</span></div><label class="insufficient-toggle"><input type="checkbox" v-model="includeInsufficientPatterns">显示样本不足</label></div>
      <div class="phase-tabs" role="tablist" aria-label="战术阶段"><button :class="{active:tacticPhase==='all'}" @click="tacticPhase='all'">全部</button><button v-for="phase in tacticalPhases" :key="phase.phase_id" :class="{active:tacticPhase===phase.phase_id}" @click="tacticPhase=phase.phase_id">{{phase.label}} <small>{{phase.patterns.filter(pattern=>includeInsufficientPatterns||pattern.classification!=='样本不足').length}}</small></button></div>
      <div v-if="loadingTactics" class="empty-state">正在整理各比赛阶段的打法…</div>
      <div v-else-if="tacticalError" class="empty-state load-error"><b>{{tacticalError}}</b><button @click="loadTacticalProfile(slug)">重新加载</button></div>
      <div v-else class="tactical-pattern-list"><TacticalPatternCard v-for="pattern in tacticalPatterns" :key="pattern.pattern_id" :pattern="pattern" :expanded="expandedPatterns.has(pattern.pattern_id)" @toggle="togglePattern(pattern.pattern_id)" @evidence="openTacticalEvidence"/><div v-if="!tacticalPatterns.length" class="empty-state">当前阶段没有达到展示门槛的打法。</div></div>
    </section>
    <section v-if="teamTab==='tactics'" class="panel counter-lab">
      <div class="section-head"><div><h2>对阵准备方案</h2><span>针对{{selected.team}}的常用打法</span></div><label>我方队伍<select v-model="counterExecutorSlug"><option value="">选择队伍</option><option v-for="team in index.teams.filter(team=>team.team!==selected.team)" :key="team.slug" :value="team.slug">{{team.team}}</option></select></label></div>
      <div v-if="!counterExecutorSlug" class="empty-state">选择我方队伍后，将按双方真实能力生成最多 3 条动作链方案。</div>
      <div v-else-if="loadingCounterExecutor" class="empty-state">正在匹配双方战术画像…</div>
      <div v-else-if="counterExecutorError" class="empty-state load-error"><b>{{counterExecutorError}}</b><button @click="loadCounterExecutor(counterExecutorSlug)">重新加载</button></div>
      <div v-else-if="!counterExecutorProfile" class="empty-state">尚未取得执行队伍战术画像。</div>
      <template v-else><div class="counter-matchup-head"><b>{{counterExecutor?.team}}</b><span>迎战</span><b>{{selected.team}}</b><small>处理顺位按基地与前哨站胜负影响、打法频率、出现时间和数据把握计算</small></div><div class="counter-plan-list"><CounterPlanCard v-for="(plan,indexAt) in counterPlans" :key="plan.id" :plan="plan" :index="indexAt" @evidence="openTacticalEvidence"/></div><div v-if="!counterPlans.length" class="empty-state">现有对局不足以形成可执行方案。</div></template>
    </section>
    <section v-if="teamTab==='map'" class="panel"><div class="section-head"><h2>秒级热力图</h2><span>{{heatView==='actual'?'实际阵营':'己方归一化'}}</span></div><div class="toolbar"><select v-model="heatView"><option value="actual">实际场地图</option><option value="canonical">己方归一化</option></select><select v-model="heatSide"><option>全部</option><option>红</option><option>蓝</option></select><select v-model="heatRobot"><option>全部</option><option>英雄</option><option>工程</option><option>步兵3</option><option>步兵4</option><option>空中</option><option>哨兵</option></select><label>从 <input type="number" v-model.number="heatFrom"></label><label>到 <input type="number" v-model.number="heatTo"></label><label>地图遮罩 <input type="range" v-model.number="heatMaskOpacity" min="0" max=".75" step=".05"></label></div><div class="heat-legend"><span>低</span><i></i><span>高</span><b>0.5m 网格</b><b>最高 {{maxHeat}} 车·秒</b></div><div v-if="loadingHeat" class="empty-state">正在加载该队地图数据…</div><HeatmapCanvas v-else-if="heat" :cells="renderedHeat" :image="`${base}maps/field-current.jpg`" :mask-opacity="heatMaskOpacity" :scale-x="heatPlacement.scaleX" :scale-y="heatPlacement.scaleY"/></section>
    <section v-if="teamTab==='matches'" class="panel"><div class="section-head"><h2>逐局时间轴</h2><span>{{selected.matches.length}} 局</span></div><div class="match-grid"><button v-for="m in selected.matches" :key="m.game_id" :class="{active:activeGame?.game_id===m.game_id}" @click="loadGame(m)"><b>{{m.won?'胜':'负'}} · {{m.opponent}}</b><span>{{m.rule_version}} · {{m.side}}方</span><small>局 {{m.game_id}} · {{fmtSecond(m.duration_sec)}}</small></button></div></section>
    <section v-if="teamTab==='matches' && loadingGame" class="panel empty-state">正在加载完整对局遥测…</section>
    <section v-if="teamTab==='matches' && gameError" class="panel empty-state load-error"><b>{{gameError}}</b><button @click="loadGame(activeGame)">重新加载</button></section>
    <section v-if="teamTab==='matches' && gameData" class="panel timeline">
      <div class="toolbar replay-toolbar"><button class="play" @click="togglePlay">{{playing?'暂停':'播放'}}</button><b>{{fmtSecond(time)}} / {{fmtSecond(gameData.game.duration_sec)}}</b><span class="replay-rate">原始 {{replayNativeHz}} Hz · 位置插值 ≤60 FPS</span><select v-model.number="speed"><option :value=".5">0.5×</option><option :value="1">1×</option><option :value="2">2×</option><option :value="4">4×</option></select><label>移动尾迹 <input type="number" v-model.number="tail" min="3" max="120"> 秒</label><select v-model="mapMode"><option value="raster">规则实场图</option><option value="vector">官方坐标简图</option></select><select v-model="routeView"><option value="actual">红左 / 蓝右</option><option value="own">己方视角</option></select></div>
      <div class="replay-scoreboard">
        <article v-for="side in ['红','蓝']" :key="side" :class="side==='红'?'red':'blue'"><header><b>{{side}}方 · {{sideTeam(side)}}</b><strong>{{gameData.game.winner===sideTeam(side)?'胜':'负'}}</strong></header><div><span>基地 <b>{{teamStatus[side]?.baseHp ?? '—'}} / {{teamStatus[side]?.baseMaxHp ?? '—'}}</b></span><span>前哨 <b>{{teamStatus[side]?.outpostHp ?? '—'}} / {{teamStatus[side]?.outpostMaxHp ?? '—'}}</b></span><span>经济 <b>{{teamStatus[side]?.remainingCoins ?? '—'}} / {{teamStatus[side]?.totalCoins ?? '—'}}</b></span></div></article>
      </div>
      <section class="engagement-console"><div class="section-head"><div><h3>关键战局切片</h3><span>{{keyEngagements.length}} 段 · 由裁判事件自动切分</span></div><b v-if="activeEngagement">当前：{{activeEngagement.type}}</b></div><div class="engagement-strip"><button v-for="segment in keyEngagements" :key="segment.id" :class="[{active:activeEngagement?.id===segment.id},segment.attacker_side==='红'?'red':'blue']" @click="seekEngagement(segment)"><span>{{fmtSecond(segment.start_sec)}}–{{fmtSecond(segment.end_sec)}}</span><b>{{segment.type}} · {{segment.attacker_side}}方</b><small>{{segment.damage}}伤害 · {{segment.hit_count}}次受击<span v-if="segment.deaths"> · {{segment.deaths}}次阵亡</span></small><small>{{segment.targets}}</small></button></div></section>
      <div class="replay-scrub"><input class="scrubber" type="range" min="0" :max="gameData.game.duration_sec" step=".05" v-model.number="time"><div class="event-markers"><button v-for="(event,indexAt) in filteredReplayEvents" :key="`${event.second}-${event.type}-${indexAt}`" :class="eventGroup(event)" :style="{left:`${100*event.second/gameData.game.duration_sec}%`}" :title="`${fmtSecond(event.second)} ${eventTitle(event)}`" @click="time=event.second"></button></div></div>
      <div class="damage-confidence-legend"><b>发弹方向 / 命中归因</b><span class="shot">实线短线：枪口位置、朝向与弹量事实</span><span class="high">高：唯一射手、时间与枪口方向吻合</span><span class="medium">中：兵种唯一或几何候选明显领先</span><label class="low"><input type="checkbox" v-model="showLowConfidence">显示低置信候选</label><strong>已归因 {{attributionCoverage.attributed}}/{{attributionCoverage.total}} · {{attributionCoverage.attributedPct}}% ｜ 高置信 {{attributionCoverage.highPct}}%</strong><small>完整连线是分级推定；撞击、判罚和飞镖不会伪造射手弹道</small></div>
      <div class="replay-workspace">
      <svg class="field replay-field" viewBox="0 0 28 15"><image :href="`${base}maps/${mapFile}`" width="28" height="15" preserveAspectRatio="none" opacity=".72" :transform="routeMapTransform()"/><polyline v-for="trailItem in trails" :key="trailItem.i" :points="trailItem.points.map(p=>frameXY(p).join(',')).join(' ')" fill="none" :stroke="colors[trailItem.i%colors.length]" stroke-width=".09"/>
        <g v-for="shot in activeShots" :key="shot.id" class="shot-effect"><line v-if="shot.yaw!=null" class="firing-ray" :x1="effectXY(shot)[0]" :y1="effectXY(shot)[1]" :x2="shotEndXY(shot)[0]" :y2="shotEndXY(shot)[1]"/><circle :cx="effectXY(shot)[0]" :cy="effectXY(shot)[1]" r=".19"/><text :x="effectXY(shot)[0]+.2" :y="effectXY(shot)[1]+.33">{{shot.shots42?'42mm ×'+shot.shots42:'17mm ×'+shot.shots17}}</text></g>
        <g v-for="effect in activeDamage" :key="effect.id" :class="['damage-effect',effect.confidence]">
          <line v-if="effect.kind==='projectile' && effect.source_x!=null && effect.source_y!=null" class="attributed-path" :x1="sourceXY(effect)[0]" :y1="sourceXY(effect)[1]" :x2="effectXY(effect)[0]" :y2="effectXY(effect)[1]"/>
          <circle class="impact-wave" :cx="effectXY(effect)[0]" :cy="effectXY(effect)[1]" r=".2"/><circle class="impact-core" :cx="effectXY(effect)[0]" :cy="effectXY(effect)[1]" r=".13"/><text :x="effectXY(effect)[0]+.18" :y="effectXY(effect)[1]-.22">-{{effect.damage}}</text>
        </g>
        <g v-for="facility in currentFacilities" :key="facility.side+facility.type" :class="['facility-marker',facility.side==='红'?'red':'blue']"><rect :x="effectXY(facility)[0]-.24" :y="effectXY(facility)[1]-.24" width=".48" height=".48" rx=".08"/><rect class="hp-track" :x="effectXY(facility)[0]-.38" :y="effectXY(facility)[1]+.3" width=".76" height=".08"/><rect class="hp-value" :x="effectXY(facility)[0]-.38" :y="effectXY(facility)[1]+.3" :width=".76*Math.max(0,Math.min(1,(facility.hp||0)/Math.max(1,facility.maxHp||1)))" height=".08"/><text :x="effectXY(facility)[0]+.3" :y="effectXY(facility)[1]" font-size=".28">{{facility.side}}{{facility.type}}</text></g>
        <g v-for="row in currentFrame" :key="row[0]" v-show="visibleRobots[row[0]]!==false" :class="['replay-robot',{selected:selectedReplayRobot===row[0]}]" @click="selectedReplayRobot=row[0]"><circle :cx="frameXY(row)[0]" :cy="frameXY(row)[1]" r=".19" :fill="colors[row[0]%colors.length]" stroke="white" stroke-width=".04"/><line v-if="row[12]!=null" class="robot-heading" :x1="frameXY(row)[0]" :y1="frameXY(row)[1]" :x2="shotEndXY({x:row[1],y:row[2],yaw:row[12]})[0]" :y2="shotEndXY({x:row[1],y:row[2],yaw:row[12]})[1]"/><rect class="hp-track" :x="frameXY(row)[0]-.28" :y="frameXY(row)[1]+.23" width=".56" height=".07"/><rect class="hp-value" :x="frameXY(row)[0]-.28" :y="frameXY(row)[1]+.23" :width=".56*Math.max(0,Math.min(1,row[3]/Math.max(1,row[4])))" height=".07"/><text :x="frameXY(row)[0]+.25" :y="frameXY(row)[1]" font-size=".32" fill="white">{{gameData.robots[row[0]].robot_type}}</text></g>
      </svg>
      <aside class="replay-telemetry"><template v-if="selectedReplayRow && selectedReplayMeta"><header><span>{{selectedReplayMeta.side}}方</span><h3>{{selectedReplayMeta.robot_type}}</h3><small>{{selectedReplayMeta.team}}</small></header><dl><div><dt>血量</dt><dd>{{selectedReplayRow[3]}} / {{selectedReplayRow[4]}}</dd></div><div><dt>底盘功率</dt><dd>{{selectedReplayRow[5]}}</dd></div><div><dt>17mm 热量</dt><dd>{{selectedReplayRow[6]}} / {{selectedReplayRow[13] ?? '—'}}</dd></div><div><dt>42mm 热量</dt><dd>{{selectedReplayRow[7]}} / {{selectedReplayRow[14] ?? '—'}}</dd></div><div><dt>本秒发弹</dt><dd>17mm {{selectedReplayRow[8]}} · 42mm {{selectedReplayRow[9]}}</dd></div><div><dt>高度 / 朝向</dt><dd>{{selectedReplayRow[11] ?? '—'}} m · {{selectedReplayRow[12] ?? '—'}}°</dd></div><div><dt>状态</dt><dd>{{selectedReplayRow[3]<=0?'战亡':selectedReplayRow[15]?'虚弱':'在场'}}</dd></div></dl></template><div v-else class="empty-state">点击地图中的机器人查看完整遥测</div></aside>
      </div>
      <div class="legend"><label v-for="(r,i) in gameData.robots" :key="i"><input type="checkbox" v-model="visibleRobots[i]"><i :style="{background:colors[i%colors.length]}"></i>{{r.side}}{{r.robot_type}} · {{r.team}}</label></div>
      <section class="assembly-console"><div class="section-head"><h3>科技核心装配</h3><span>完成点为事实 · 区间起点为推定</span></div><div class="assembly-sides"><article v-for="side in ['红','蓝']" :key="side" :class="side==='红'?'red':'blue'"><h4>{{side}}方 · {{sideTeam(side)}}</h4><div class="assembly-levels"><div v-for="rule in assemblyRules" :key="rule.level" :class="{completed:assemblyBySide[side][rule.level-1].events.length}"><header><b>{{rule.level}}级</b><span>{{fmtSecond(rule.unlock)}}后可选</span></header><template v-if="assemblyBySide[side][rule.level-1].events.length"><button v-for="event in assemblyBySide[side][rule.level-1].events" :key="event.second" @click="time=event.second"><b>{{fmtSecond(event.second)}} 完成</b><span>记录耗时 {{event.assembly_duration_sec}}秒</span><small>推定 {{fmtSecond(event.assembly_start_sec)}}–{{fmtSecond(event.second)}}</small></button></template><p v-else>{{rule.level===4?'当前数据未观测到四级装配成功':'本局未完成'}}</p><small>{{rule.benefit}}</small></div></div></article></div></section>
      <div class="event-filter"><b>事件轨道</b><button v-for="group in eventGroups" :key="group" :class="{active:replayEventFilter===group}" @click="replayEventFilter=group">{{group}}</button></div>
      <div class="replay-details"><div class="damage-feed"><h3>实际扣血与来源 <small>{{damageEffects.length}} 条</small></h3><article v-for="effect in recentDamage" :key="effect.id"><button @click="time=effect.second"><b>{{fmtSecond(effect.second)}} · {{effect.target_side}}{{effect.target_type}} -{{effect.damage}}</b><span :class="['confidence-chip',effect.confidence]">{{effect.kind==='projectile'?confidenceLabel(effect.confidence):effect.category}}</span><span>{{effect.shooter_type?`${effect.shooter_side}${effect.shooter_type} → `:''}}{{effect.category}}</span><small>{{effect.basis}}{{effect.angle_error==null?'':` · 枪口夹角 ${effect.angle_error}°`}}{{effect.attribution_score==null?'':` · 证据 ${effect.attribution_score}分`}}</small></button><details v-if="effect.candidates?.length"><summary>{{effect.candidates.length}} 个射手候选</summary><div class="candidate-table"><span v-for="candidate in effect.candidates" :key="candidate.robot_id" :class="candidate.verdict"><b>{{candidate.robot_type}} · {{candidate.evidence_score}}分</b><small>{{candidate.time_offset_sec===0?'同秒':'前1秒'}} {{candidate.same_second_shots||candidate.previous_second_shots}}发 · 距离 {{candidate.distance_m??'—'}}m · 枪口偏差 {{candidate.angle_error??'—'}}°</small><small>{{candidate.reason}}</small></span></div></details></article></div><div class="events"><button v-for="(event,indexAt) in shownEvents" :key="`${event.second}-${event.type}-${indexAt}`" @click="time=event.second"><b>{{fmtSecond(event.second)}} {{eventTitle(event)}}</b><span>{{event.team||event.side||''}}</span><small :class="['confidence-chip',event.confidence]">{{confidenceLabel(event.confidence)}}</small></button><p v-if="!shownEvents.length">当前时间前没有该类事件。</p></div></div>
    </section>
    <section v-if="teamTab==='roles'" class="panel role-launcher"><div class="section-head"><h2>各兵种比赛数据</h2><span>事实 / 推定分列</span></div><div class="role-shortcuts"><button v-for="([key,label]) in roleShortcuts" :key="key" @click="openTeamRole(key)"><b>{{label}}</b><span>查看 {{selected.team}} 的{{label}}数据</span></button></div></section>
    <section v-if="teamTab==='discipline'" class="panel"><div class="section-head"><h2>黄牌 / 红牌</h2><span class="trust-badge">仅推定</span></div><div class="penalty-table"><div v-for="p in selected.penalty_incidents" :key="`${p.game_id}-${p.second}`"><b>局 {{p.game_id}} · {{fmtSecond(p.second)}} · {{p.incident_type}}</b><span>{{p.offender_type||'对象未知'}} · 扣血 {{p.penalty_damage}} · {{p.confidence}}置信<span v-if="p.inferred_red"> · 推定红牌</span></span></div><p v-if="!selected.penalty_incidents.length">该队样本中无可识别判罚事件。</p></div></section>
    <section v-if="teamTab==='compare'" class="panel compare"><div class="section-head"><h2>双队对比与胜率</h2><span class="trust-badge">模型预测</span></div><div class="compare-controls"><select v-model="compareSlug"><option value="">选择另一支队伍</option><option v-for="t in index.teams.filter(t=>t.team!==selected.team)" :key="t.slug" :value="t.slug">{{t.team}}</option></select><select v-model="compareStage"><option>小组赛</option><option>淘汰赛</option></select></div><template v-if="compareTeam && matchup"><div class="prediction"><div><span>{{selected.team}} 模型胜率</span><strong>{{matchup.primaryPct}}%</strong><small>估计区间 {{matchup.interval[0]}}%–{{matchup.interval[1]}}%</small></div><div class="verdict"><span>对局判定</span><strong>{{matchup.verdict}}</strong><small>{{matchup.stage}} · 置信度：{{matchup.confidence}} · {{matchup.weightProfile}}{{matchup.resultWeight?' + 东部赛果 10%':''}} · 尺度 {{matchup.scale}}</small><small v-if="matchup.foldEcePct!=null">完整系列滚动校准误差 {{matchup.foldEcePct}}% · 区间下限 ±{{matchup.modelMargin}}%</small><small v-else>跨赛区无直接训练样本 · 区间下限 ±{{matchup.modelMargin}}%</small></div><div><span>{{compareTeam.team}} 模型胜率</span><strong>{{matchup.opponentPct}}%</strong><small v-if="matchup.h2hGames">历史交手 {{matchup.h2hGames}} 局：{{matchup.h2hWins}}胜{{matchup.h2hLosses}}负</small><small v-else>数据库中无直接交手</small></div></div><div class="comparison-table"><div class="comparison-row comparison-head"><b>同口径指标</b><b>{{selected.team}}</b><b>{{compareTeam.team}}</b><b>相对优势</b></div><div v-for="row in comparisonRows" :key="row.label" class="comparison-row"><span>{{row.label}}</span><strong>{{row.first}}</strong><strong>{{row.second}}</strong><em>{{row.leader}}</em></div></div></template><div v-else class="empty-state">选择另一支队伍后，将展示同颗粒度指标、优势来源与胜率区间。</div></section>
  </main><main v-else><p>{{error||'正在加载…'}}</p></main>
</div>
<MethodologyDrawer :open="methodologyOpen" :title="methodologyTitle" :sections="methodologySections" @close="closeMethodology"/>
</div>
</template>
