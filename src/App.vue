<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { init, use } from 'echarts/core'
import { BarChart, RadarChart } from 'echarts/charts'
import { GridComponent, RadarComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { aggregateHeatCells, densityOpacity, matchupEstimate, officialToMap, rankTeamsByStrength, rasterMapCenter, rasterMapPlacement, rasterMapPoint, strengthGrade, summarizeDimensions, teamPerspectivePoint, teamStrength } from './domain.js'

use([BarChart, RadarChart, GridComponent, RadarComponent, TooltipComponent, CanvasRenderer])
const base = import.meta.env.BASE_URL
const dataRevision = 'score-3.4.0'
const index = ref({ teams: [] }), selected = ref(null), query = ref(''), region = ref('全部'), error = ref('')
const heat = ref(null), heatSide = ref('全部'), heatRobot = ref('全部'), heatView = ref('actual'), heatFrom = ref(0), heatTo = ref(420), heatMaskOpacity = ref(.34)
const gameData = ref(null), activeGame = ref(null), time = ref(0), playing = ref(false), speed = ref(1), tail = ref(20), mapMode = ref('raster'), routeView = ref('actual')
const visibleRobots = ref({}), compareSlug = ref(''), compareTeam = ref(null)
let scoreChart, damageChart, timer
const colors = ['#ff5268','#ff9e54','#ffd166','#9b7bff','#ef70cb','#ff355f','#48a8ff','#58d3ff','#41e1a6','#6f8dff','#61b8ff','#16c7e8']
const rankedTeams = computed(() => rankTeamsByStrength(index.value.teams))
const teams = computed(() => rankedTeams.value.filter(t => (region.value === '全部' || t.region === region.value) && (!query.value || t.team.includes(query.value))))
const slug = computed(() => index.value.teams.find(t => t.team === selected.value?.team)?.slug)
const strength = computed(() => teamStrength(selected.value))
const grade = computed(() => strengthGrade(strength.value))
const dimensions = computed(() => summarizeDimensions(selected.value))
const filteredHeat = computed(() => (heat.value?.cells || []).filter(c => (heatSide.value === '全部' || c[0] === heatSide.value) && (heatRobot.value === '全部' || c[1] === heatRobot.value) && c[2] >= heatFrom.value && c[2] <= heatTo.value))
const aggregatedHeat = computed(() => aggregateHeatCells(filteredHeat.value, heatXY, heatView.value === 'canonical'))
const maxHeat = computed(() => Math.max(1, ...aggregatedHeat.value.map(c => c.samples)))
const headToHead = computed(() => compareTeam.value ? selected.value.matches.filter(match => match.opponent === compareTeam.value.team) : [])
const matchup = computed(() => compareTeam.value ? matchupEstimate(selected.value, compareTeam.value, headToHead.value) : null)
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
const shownEvents = computed(() => (gameData.value?.events || []).filter(e => e.second <= time.value))
const currentFrame = computed(() => {
  const frames = gameData.value?.frames || []; let found = []
  for (const frame of frames) { if (frame[0] > time.value) break; found = frame[1] }
  return found
})
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
function rankLabel(dimension) {
  const rank = selected.value?.dimension_ranks?.[dimension]
  return rank ? (rank <= 20 ? `TOP ${rank}` : `第 ${rank}/96`) : '—'
}
function fetchData(path) { return fetch(`${base}${path}?v=${dataRevision}`, { cache: 'no-store' }) }
async function loadTeam(teamSlug) {
  playing.value = false; gameData.value = null; activeGame.value = null
  const [teamRes, heatRes] = await Promise.all([fetchData(`data/teams/${teamSlug}.json`), fetchData(`data/heatmaps/${teamSlug}.json`)])
  if (!teamRes.ok || !heatRes.ok) throw new Error('队伍细粒度数据加载失败')
  selected.value = await teamRes.json(); heat.value = await heatRes.json(); heatTo.value = Math.max(...selected.value.matches.map(m => m.duration_sec), 420)
  await nextTick(); renderCharts()
}
async function loadGame(game) {
  playing.value = false; activeGame.value = game
  const response = await fetchData(`data/games/${game.game_id}.json`); if (!response.ok) throw new Error('对局时间轴加载失败')
  gameData.value = await response.json(); time.value = 0; visibleRobots.value = Object.fromEntries(gameData.value.robots.map((_, i) => [i, true]))
}
function togglePlay() { playing.value = !playing.value }
function tick() { if (!playing.value || !gameData.value) return; time.value += .1 * speed.value; if (time.value >= gameData.value.game.duration_sec) { time.value = gameData.value.game.duration_sec; playing.value = false } }
function renderCharts() {
  if (!selected.value) return
  scoreChart?.dispose(); damageChart?.dispose()
  scoreChart = init(document.getElementById('score-chart')); const keys = ['firepower','objective','spatial','defense','resource','adaptability']
  const labels = ['净战斗火力','目标转化','空间控制','防守韧性','资源转化','适应能力']
  scoreChart.setOption({radar:{center:['50%','52%'],radius:'57%',indicator:labels.map((name,index)=>({name:`${name}\n${rankLabel(keys[index])}`,max:100})),axisName:{color:'#cbd5e1',fontSize:13},splitArea:{areaStyle:{color:['#13233a','#0e1a2d']}}},series:[{type:'radar',data:[{value:keys.map(k=>selected.value.scores[k])}],areaStyle:{color:'#22d3ee66'},lineStyle:{color:'#22d3ee'}}],textStyle:{color:'#cbd5e1'}})
  damageChart = init(document.getElementById('damage-chart')); const damage = selected.value.damage_breakdown.slice(0,12)
  damageChart.setOption({grid:{left:120,right:25,top:20,bottom:30},xAxis:{type:'value',axisLabel:{color:'#94a3b8'}},yAxis:{type:'category',data:damage.map(d=>`${d.target_type}·${d.source_type}`).reverse(),axisLabel:{color:'#cbd5e1'}},series:[{type:'bar',data:damage.map(d=>d.damage).reverse(),itemStyle:{color:'#f59e0b'}}],tooltip:{trigger:'axis'}})
}
watch(compareSlug, async value => { compareTeam.value = value ? await (await fetchData(`data/teams/${value}.json`)).json() : null })
onMounted(async () => { timer = setInterval(tick, 100); try { index.value = await (await fetchData('data/index.json')).json(); const first=index.value.teams.find(t=>t.team==='广东工业大学')||rankedTeams.value[0]; if(first) await loadTeam(first.slug) } catch(e) { error.value=e.message } })
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
<div class="shell">
  <aside><div class="brand"><span>RMUC 2026</span><strong>战术情报库 v3</strong></div><input v-model="query" placeholder="搜索队伍"><select v-model="region"><option>全部</option><option>南部赛区</option><option>东部赛区</option><option>北部赛区</option></select><div class="team-list"><button v-for="t in teams" :key="t.slug" :class="{active:selected?.team===t.team}" @click="loadTeam(t.slug)"><span>{{t.team}}</span><small>#{{t.strengthRank}} · {{t.wins}}/{{t.games}} · {{t.region}}<template v-if="t.placement"> · {{t.placement.label}}</template> · 强度 {{strengthGrade(teamStrength(t))}}</small></button></div></aside>
  <main v-if="selected">
    <div class="notice">仅使用规则手册实场图和通信协议 28×15m 官方坐标；行为树内部地图、区域 YAML 与 SCAU 叠加图不参与映射。</div>
    <header><div><p>{{selected.summary.region}} <em v-if="selected.placement">{{selected.summary.region}}{{selected.placement.label}}</em></p><h1>{{selected.team}}</h1></div><div class="record"><strong>{{selected.summary.wins}}–{{selected.summary.games-selected.summary.wins}}</strong><span>胜率 {{selected.summary.win_rate.toFixed(1)}}% · 全局 #{{selected.overall_rank}}</span></div></header>
    <section class="kpis"><article><span>场均输出</span><strong>{{selected.summary.avg_damage_dealt?.toFixed(0)}}</strong></article><article><span>场均基地伤害</span><strong>{{selected.summary.avg_base_damage?.toFixed(0)}}</strong></article><article><span>场均前哨伤害</span><strong>{{selected.summary.avg_outpost_damage?.toFixed(0)}}</strong></article><article><span>综合强度评级</span><strong class="strength-grade" :data-grade="grade">{{grade}} · {{strength.toFixed(1)}}</strong></article></section>
    <section class="grid-two"><article class="panel"><h2>战术分维度评分</h2><div id="score-chart" class="chart"></div></article><article class="panel"><h2>基地与其他目标伤害来源</h2><div id="damage-chart" class="chart"></div></article></section>
    <section class="panel">
      <div class="section-head"><h2>高维战术解析 3.4</h2><span>逐局净事实 · 条件校正 · 时间回测</span></div>
      <p class="method coverage-note"><b>评分边界：</b>判罚、撞击和定位覆盖不进入战术得分；雷达仅使用原始库可验证的反制事件。每项同时展示分项得分、原始事实和有效样本。</p>
      <div class="insight-grid">
        <article class="insight-card"><h3>净战斗火力 · {{show(dimensions.analysis.firepower?.score)}}</h3><div class="metric-pairs"><span>对手校正净输出 · 30%<strong>{{show(dimensions.analysis.firepower?.components?.clean_output)}}</strong></span><span>机器人命中效率 · 25%<strong>{{show(dimensions.analysis.firepower?.components?.accuracy)}}</strong></span><span>阵亡转化 · 25%<strong>{{show(dimensions.analysis.firepower?.components?.kill_conversion)}}</strong></span><span>持续施压 · 20%<strong>{{show(dimensions.analysis.firepower?.components?.pressure_uptime)}}</strong></span><span>净输出相对预期<strong>{{show(dimensions.analysis.firepower?.raw?.clean_output,'×')}}</strong></span><span>机器人命中率<strong>{{show(Math.round((dimensions.analysis.firepower?.raw?.accuracy||0)*1000)/10,'%')}}</strong></span></div></article>
        <article class="insight-card"><h3>目标转化 · {{show(dimensions.analysis.objective?.score)}}</h3><div class="metric-pairs"><span>前哨施压 · 15%<strong>{{show(dimensions.analysis.objective?.components?.outpost_pressure)}}</strong></span><span>前哨转化 · 25%<strong>{{show(dimensions.analysis.objective?.components?.outpost_conversion)}}</strong></span><span>基地施压 · 15%<strong>{{show(dimensions.analysis.objective?.components?.base_pressure)}}</strong></span><span>基地转化 · 25%<strong>{{show(dimensions.analysis.objective?.components?.base_conversion)}}</strong></span><span>战略工具 · 20%<strong>{{show(dimensions.analysis.objective?.components?.strategic_tools)}}</strong></span><span>首伤前哨中位<strong>{{dimensions.objective.firstOutpostSec==null?'—':fmtSecond(dimensions.objective.firstOutpostSec)}}</strong></span><span>中位击毁耗时<strong>{{dimensions.objective.medianOutpostKillSec==null?'—':fmtSecond(dimensions.objective.medianOutpostKillSec)}}</strong></span><span>有效击毁样本<strong>{{dimensions.objective.outpostKillGames}} 局</strong></span></div></article>
        <article class="insight-card"><h3>空间控制 · {{show(dimensions.analysis.spatial?.score)}}</h3><div class="metric-pairs"><span>相对领土纵深 · 30%<strong>{{show(dimensions.analysis.spatial?.components?.relative_territory)}}</strong></span><span>前压在场 · 25%<strong>{{show(dimensions.analysis.spatial?.components?.forward_presence)}}</strong></span><span>中区相对控制 · 20%<strong>{{show(dimensions.analysis.spatial?.components?.neutral_control)}}</strong></span><span>场地覆盖 · 25%<strong>{{show(dimensions.analysis.spatial?.components?.field_coverage)}}</strong></span><span>相对推进纵深<strong>{{show(dimensions.analysis.spatial?.raw?.relative_territory,' m')}}</strong></span><span>前压车秒占比<strong>{{show(Math.round((dimensions.analysis.spatial?.raw?.forward_presence||0)*1000)/10,'%')}}</strong></span><span>定位覆盖（仅置信度）<strong>{{show(dimensions.confidence?.position_coverage_pct,'%')}}</strong></span></div></article>
        <article class="insight-card defense-card"><h3>防守韧性 · {{show(dimensions.analysis.defense?.score)}}</h3><div class="metric-pairs"><span>校正伤害交换 · 25%<strong>{{show(dimensions.analysis.defense?.components?.trade_resilience)}}</strong></span><span>机器人韧性 · 20%<strong>{{show(dimensions.analysis.defense?.components?.mobile_resilience)}}</strong></span><span>前哨拒止 · 20%<strong>{{show(dimensions.analysis.defense?.components?.outpost_denial)}}</strong></span><span>基地拒止 · 25%<strong>{{show(dimensions.analysis.defense?.components?.base_denial)}}</strong></span><span>整体防守下限 · 10%<strong>{{show(dimensions.analysis.defense?.components?.collapse_resistance)}}</strong></span><span>聚合口径<strong>典型表现 70% · 下四分位 30%</strong></span><span>已排除噪声<strong>判罚 {{show(dimensions.analysis.defense?.excluded?.penalty_damage)}} · 撞击 {{show(dimensions.analysis.defense?.excluded?.collision_damage)}}</strong></span></div></article>
        <article class="insight-card"><h3>资源转化 · {{show(dimensions.analysis.resource?.score)}}</h3><div class="metric-pairs"><span>经济获取 · 25%<strong>{{show(dimensions.analysis.resource?.components?.acquisition)}}</strong></span><span>经济使用 · 20%<strong>{{show(dimensions.analysis.resource?.components?.utilization)}}</strong></span><span>战斗转化 · 20%<strong>{{show(dimensions.analysis.resource?.components?.combat_conversion)}}</strong></span><span>目标转化 · 15%<strong>{{show(dimensions.analysis.resource?.components?.objective_conversion)}}</strong></span><span>热控效率 · 20%<strong>{{show(dimensions.analysis.resource?.components?.thermal_efficiency)}}</strong></span><span>经济使用率<strong>{{show(Math.round((dimensions.analysis.resource?.raw?.utilization||0)*1000)/10,'%')}}</strong></span></div></article>
        <article class="insight-card"><h3>适应能力 · {{show(dimensions.analysis.adaptability?.score)}}</h3><div class="metric-pairs"><span>红蓝方迁移 · 25%<strong>{{show(dimensions.analysis.adaptability?.components?.side_transfer)}}</strong></span><span>跨对手下限 · 20%<strong>{{show(dimensions.analysis.adaptability?.components?.opponent_robustness)}}</strong></span><span>强敌超预期 · 25%<strong>{{show(dimensions.analysis.adaptability?.components?.strong_opponent_residual)}}</strong></span><span>局内失守后调整 · 20%<strong>{{show(dimensions.analysis.adaptability?.components?.setback_adjustment)}}</strong></span><span>败局后再战调整 · 10%<strong>{{show(dimensions.analysis.adaptability?.components?.rematch_adjustment)}}</strong></span><span>缺失条件样本<strong>只回归中性，不加减分</strong></span></div></article>
        <article class="insight-card"><h3>雷达反制 UAV</h3><div class="metric-pairs"><span>发起反制<strong>{{dimensions.radar?.counter_uses||0}} 次</strong></span><span>使用覆盖<strong>{{dimensions.radar?.counter_use_games||0}} 局 / {{show(dimensions.radar?.counter_use_game_pct,'%')}}</strong></span><span>中位触发<strong>{{dimensions.radar?.median_counter_sec==null?'—':fmtSecond(dimensions.radar.median_counter_sec)}}</strong></span><span>90 秒内使用<strong>{{show(dimensions.radar?.early_counter_pct,'%')}}</strong></span><span>己方空中被反制<strong>{{dimensions.radar?.countered_events||0}} 次</strong></span><span>涉及对局<strong>{{dimensions.radar?.countered_games||0}} 局</strong></span></div></article>
        <article class="insight-card strength-card"><h3>综合强度 3.4 · {{show(dimensions.strength?.score)}}</h3><div class="metric-pairs"><span>六维战术 · 90%<strong>{{show(dimensions.strength?.tactical_score)}}</strong></span><span>赛程校正赛果 · 10%<strong>{{show(dimensions.strength?.result_score)}}</strong></span><span>赛程强度参数<strong>{{show(dimensions.strength?.schedule_rating)}}</strong></span><span>数据置信度（不计分）<strong>{{show(dimensions.confidence?.overall,'%')}}</strong></span><span>有效对局<strong>{{dimensions.confidence?.games||0}} 局</strong></span><span>验证方式<strong>滚动时间回测 · 分箱校准</strong></span></div></article>
      </div>
      <details v-if="dimensions.objective.outpostTimeline.length" class="radar-events outpost-events"><summary>展开逐局前哨击打时间线（{{dimensions.objective.outpostTimeline.length}} 局）</summary><div><button v-for="event in dimensions.objective.outpostTimeline" :key="event.gameId" @click="loadGame(selected.matches.find(match=>match.game_id===event.gameId))"><b>局 {{event.gameId}} · 首伤 {{fmtSecond(event.firstDamageSec)}}</b><span>{{event.won?'胜':'负'}} · {{event.side}}方 · 对手 {{event.opponent}}</span><span>累计前哨伤害 {{event.damage}} · {{event.destroySec==null?'未摧毁':'击毁 '+fmtSecond(event.destroySec)+' · 耗时 '+fmtSecond(event.killDurationSec)}}</span></button></div></details>
      <details v-if="dimensions.radar?.events?.length" class="radar-events"><summary>展开雷达事件时间线（{{dimensions.radar.events.length}} 条，含发起与被反制）</summary><div><button v-for="(event,i) in dimensions.radar.events" :key="event.game_id+'-'+event.second+'-'+event.role+'-'+i" @click="loadGame(selected.matches.find(match=>match.game_id===event.game_id))"><b>局 {{event.game_id}} · {{fmtSecond(event.second)}} · {{event.role}}</b><span>对手：{{event.opponent}}</span></button></div></details>
    </section>
    <section class="panel"><div class="section-head"><h2>秒级热力图</h2><span>真实红方 / 真实蓝方 / 己方归一化</span></div><div class="toolbar"><select v-model="heatView"><option value="actual">实际场地图</option><option value="canonical">己方归一化</option></select><select v-model="heatSide"><option>全部</option><option>红</option><option>蓝</option></select><select v-model="heatRobot"><option>全部</option><option>英雄</option><option>工程</option><option>步兵3</option><option>步兵4</option><option>空中</option><option>哨兵</option></select><label>从 <input type="number" v-model.number="heatFrom"></label><label>到 <input type="number" v-model.number="heatTo"></label><label>地图遮罩 <input type="range" v-model.number="heatMaskOpacity" min="0" max=".75" step=".05"></label></div><p class="method">颜色表示筛选范围内落在 0.5m 格子的累计在场秒数；先按格聚合，再使用对数色阶。最高密度 {{maxHeat}} 车·秒。官方 28×15m 坐标投影到实场图内墙 ROI，外部围挡仅作背景。</p><svg class="field" viewBox="0 0 28 15"><image :href="`${base}maps/field-current.jpg`" width="28" height="15" preserveAspectRatio="none" opacity="1"/><rect v-for="c in aggregatedHeat" :key="`${c.side}-${c.x}-${c.y}`" :x="c.x-.25*heatPlacement.scaleX" :y="c.y-.25*heatPlacement.scaleY" :width=".5*heatPlacement.scaleX" :height=".5*heatPlacement.scaleY" :fill="heatColor(c)" :opacity="heatOpacity(c)"/><image class="map-mask" :href="`${base}maps/field-current.jpg`" width="28" height="15" preserveAspectRatio="none" :opacity="heatMaskOpacity"/></svg></section>
    <section class="panel"><div class="section-head"><h2>逐局时间轴</h2><span>1 Hz · 双方全车 · 速度 / 尾迹 / 事件</span></div><div class="match-grid"><button v-for="m in selected.matches" :key="m.game_id" :class="{active:activeGame?.game_id===m.game_id}" @click="loadGame(m)"><b>{{m.won?'胜':'负'}} · {{m.opponent}}</b><span>{{m.rule_version}} · {{m.side}}方</span><small>局 {{m.game_id}} · {{fmtSecond(m.duration_sec)}}</small></button></div></section>
    <section v-if="gameData" class="panel timeline"><div class="toolbar"><button class="play" @click="togglePlay">{{playing?'暂停':'播放'}}</button><b>{{fmtSecond(time)}} / {{fmtSecond(gameData.game.duration_sec)}}</b><select v-model.number="speed"><option :value=".5">0.5×</option><option :value="1">1×</option><option :value="2">2×</option><option :value="4">4×</option></select><label>尾迹 <input type="number" v-model.number="tail" min="3" max="120"> 秒</label><select v-model="mapMode"><option value="raster">规则实场图</option><option value="vector">官方坐标简图</option></select><select v-model="routeView"><option value="actual">全局实际阵营</option><option value="own">所选队伍己方视角（整场旋转）</option></select></div><p class="method">全局视图：红方位于地图左侧、蓝方位于右侧；己方视图会将地图和双方机器人整体旋转，不会把两队重叠。</p><input class="scrubber" type="range" min="0" :max="gameData.game.duration_sec" step="1" v-model.number="time"><svg class="field" viewBox="0 0 28 15"><image :href="`${base}maps/${mapFile}`" width="28" height="15" preserveAspectRatio="none" opacity=".72" :transform="routeMapTransform()"/><polyline v-for="trailItem in trails" :key="trailItem.i" :points="trailItem.points.map(p=>frameXY(p).join(',')).join(' ')" fill="none" :stroke="colors[trailItem.i%colors.length]" stroke-width=".09"/><g v-for="row in currentFrame" :key="row[0]" v-show="visibleRobots[row[0]]!==false"><circle :cx="frameXY(row)[0]" :cy="frameXY(row)[1]" r=".19" :fill="colors[row[0]%colors.length]" stroke="white" stroke-width=".04"/><text :x="frameXY(row)[0]+.25" :y="frameXY(row)[1]" font-size=".32" fill="white">{{gameData.robots[row[0]].robot_type}}</text></g></svg><div class="legend"><label v-for="(r,i) in gameData.robots" :key="i"><input type="checkbox" v-model="visibleRobots[i]"><i :style="{background:colors[i%colors.length]}"></i>{{r.side}}{{r.robot_type}} · {{r.team}}</label></div><div class="events"><button v-for="(e,i) in shownEvents.slice(-30)" :key="i" @click="time=e.second"><b>{{fmtSecond(e.second)}} {{e.type}}</b><span>{{e.team||e.detail||''}} · {{e.confidence}}</span></button></div></section>
    <section class="panel"><h2>黄牌 / 红牌推断</h2><p class="method">源数据只有“判罚扣血”，没有牌色字段。以下按同步扣血比例标注高/中置信黄牌、推定红牌或牌色未知，不强行归类。</p><div class="penalty-table"><div v-for="p in selected.penalty_incidents" :key="`${p.game_id}-${p.second}`"><b>局 {{p.game_id}} · {{fmtSecond(p.second)}} · {{p.incident_type}}</b><span>{{p.offender_type||'对象未知'}} · 扣血 {{p.penalty_damage}} · {{p.confidence}}置信<span v-if="p.inferred_red"> · 推定红牌</span></span></div><p v-if="!selected.penalty_incidents.length">该队样本中无可识别判罚事件。</p></div></section>
    <section class="panel"><h2>稳定战术与全队克制方案</h2><div class="patterns"><div v-for="p in selected.patterns" :key="p.pattern_id" :class="['pattern',p.classification]"><b>{{p.label}}</b><span>{{p.classification}} · {{(p.rate*100).toFixed(0)}}%</span><small>{{p.games_observed}} 局 / {{p.opponents}} 个对手</small></div></div><div class="counter" v-for="item in selected.counter_plan" :key="item.signal"><b>{{item.signal}}</b><p>{{item.action}}</p><small>退出：{{item.exit}}</small></div></section>
    <section class="panel compare"><div class="section-head"><h2>双队同口径对比与胜率判定</h2><span>区域赛样本模型，不代表确定赛果</span></div><select v-model="compareSlug"><option value="">选择另一支队伍</option><option v-for="t in index.teams.filter(t=>t.team!==selected.team)" :value="t.slug">{{t.team}}</option></select><template v-if="compareTeam && matchup"><div class="prediction"><div><span>{{selected.team}} 模型胜率</span><strong>{{matchup.primaryPct}}%</strong><small>估计区间 {{matchup.interval[0]}}%–{{matchup.interval[1]}}%</small></div><div class="verdict"><span>对局判定</span><strong>{{matchup.verdict}}</strong><small>置信度：{{matchup.confidence}} · 综合强度 {{matchup.primaryStrength}} : {{matchup.opponentStrength}}</small></div><div><span>{{compareTeam.team}} 模型胜率</span><strong>{{matchup.opponentPct}}%</strong><small v-if="matchup.h2hGames">历史交手 {{matchup.h2hGames}} 局：{{matchup.h2hWins}}胜{{matchup.h2hLosses}}负</small><small v-else>数据库中无直接交手</small></div></div><div class="comparison-table"><div class="comparison-row comparison-head"><b>同口径指标</b><b>{{selected.team}}</b><b>{{compareTeam.team}}</b><b>相对优势</b></div><div v-for="row in comparisonRows" :key="row.label" class="comparison-row"><span>{{row.label}}</span><strong>{{row.first}}</strong><strong>{{row.second}}</strong><em>{{row.leader}}</em></div></div><p class="method">模型综合强度由统一尺度的六维战术评分 75%、正则化 Bradley–Terry 赛程校正赛果 25% 构成；有直接交手时最多以 30% 权重平滑校正。数据覆盖单独形成置信度，不参与得分；对手强弱、临场阵容和地图策略仍会造成偏差。</p></template></section>
  </main><main v-else><p>{{error||'正在加载…'}}</p></main>
</div>
</template>
