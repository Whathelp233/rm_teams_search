<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { init, use } from 'echarts/core'
import { BarChart, RadarChart } from 'echarts/charts'
import { GridComponent, RadarComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { aggregateHeatCells, densityOpacity, officialToMap, reliabilityTone, teamPerspectivePoint } from './domain.js'

use([BarChart, RadarChart, GridComponent, RadarComponent, TooltipComponent, CanvasRenderer])
const base = import.meta.env.BASE_URL
const index = ref({ teams: [] }), selected = ref(null), query = ref(''), region = ref('全部'), error = ref('')
const heat = ref(null), heatSide = ref('全部'), heatRobot = ref('全部'), heatView = ref('actual'), heatFrom = ref(0), heatTo = ref(420), heatMaskOpacity = ref(.34)
const gameData = ref(null), activeGame = ref(null), time = ref(0), playing = ref(false), speed = ref(1), tail = ref(20), mapMode = ref('raster'), routeView = ref('actual')
const visibleRobots = ref({}), compareSlug = ref(''), compareTeam = ref(null)
let scoreChart, damageChart, timer
const colors = ['#ff5268','#ff9e54','#ffd166','#9b7bff','#ef70cb','#ff355f','#48a8ff','#58d3ff','#41e1a6','#6f8dff','#61b8ff','#16c7e8']
const teams = computed(() => index.value.teams.filter(t => (region.value === '全部' || t.region === region.value) && (!query.value || t.team.includes(query.value))))
const slug = computed(() => index.value.teams.find(t => t.team === selected.value?.team)?.slug)
const reliability = computed(() => selected.value?.reliability)
const filteredHeat = computed(() => (heat.value?.cells || []).filter(c => (heatSide.value === '全部' || c[0] === heatSide.value) && (heatRobot.value === '全部' || c[1] === heatRobot.value) && c[2] >= heatFrom.value && c[2] <= heatTo.value))
const aggregatedHeat = computed(() => aggregateHeatCells(filteredHeat.value, heatXY, heatView.value === 'canonical'))
const maxHeat = computed(() => Math.max(1, ...aggregatedHeat.value.map(c => c.samples)))
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

function heatXY(cell) {
  let x = (cell[3] + .5) / 2, y = (cell[4] + .5) / 2
  if (heatView.value === 'canonical' && cell[0] === '蓝') return teamPerspectivePoint(x, y, '蓝')
  return officialToMap(x, y)
}
function frameXY(row) { return routeView.value === 'own' ? teamPerspectivePoint(row[1], row[2], activeGame.value?.side) : officialToMap(row[1], row[2]) }
function routeMapTransform() { return routeView.value === 'own' && activeGame.value?.side === '蓝' ? 'rotate(180 14 7.5)' : '' }
function heatOpacity(cell) {
  return densityOpacity(cell.samples, maxHeat.value)
}
function heatColor(cell) { return cell.side === '红' ? '#ff3b62' : cell.side === '蓝' ? '#00d9ff' : '#ffd166' }
function fmtSecond(value) { const v = Math.max(0, Math.round(value)); return `${Math.floor(v/60)}:${String(v%60).padStart(2,'0')}` }
async function loadTeam(teamSlug) {
  playing.value = false; gameData.value = null; activeGame.value = null
  const [teamRes, heatRes] = await Promise.all([fetch(`${base}data/teams/${teamSlug}.json`), fetch(`${base}data/heatmaps/${teamSlug}.json`)])
  if (!teamRes.ok || !heatRes.ok) throw new Error('队伍细粒度数据加载失败')
  selected.value = await teamRes.json(); heat.value = await heatRes.json(); heatTo.value = Math.max(...selected.value.matches.map(m => m.duration_sec), 420)
  await nextTick(); renderCharts()
}
async function loadGame(game) {
  playing.value = false; activeGame.value = game
  const response = await fetch(`${base}data/games/${game.game_id}.json`); if (!response.ok) throw new Error('对局时间轴加载失败')
  gameData.value = await response.json(); time.value = 0; visibleRobots.value = Object.fromEntries(gameData.value.robots.map((_, i) => [i, true]))
}
function togglePlay() { playing.value = !playing.value }
function tick() { if (!playing.value || !gameData.value) return; time.value += .1 * speed.value; if (time.value >= gameData.value.game.duration_sec) { time.value = gameData.value.game.duration_sec; playing.value = false } }
function renderCharts() {
  if (!selected.value) return
  scoreChart?.dispose(); damageChart?.dispose()
  scoreChart = init(document.getElementById('score-chart')); const keys = ['firepower','objective','spatial','defense','resource','adaptability']
  scoreChart.setOption({radar:{indicator:['火力','目标','空间','防守','资源','适应'].map(name=>({name,max:100})),splitArea:{areaStyle:{color:['#13233a','#0e1a2d']}}},series:[{type:'radar',data:[{value:keys.map(k=>selected.value.scores[k])}],areaStyle:{color:'#22d3ee66'},lineStyle:{color:'#22d3ee'}}],textStyle:{color:'#cbd5e1'}})
  damageChart = init(document.getElementById('damage-chart')); const damage = selected.value.damage_breakdown.slice(0,12)
  damageChart.setOption({grid:{left:120,right:25,top:20,bottom:30},xAxis:{type:'value',axisLabel:{color:'#94a3b8'}},yAxis:{type:'category',data:damage.map(d=>`${d.target_type}·${d.source_type}`).reverse(),axisLabel:{color:'#cbd5e1'}},series:[{type:'bar',data:damage.map(d=>d.damage).reverse(),itemStyle:{color:'#f59e0b'}}],tooltip:{trigger:'axis'}})
}
watch(compareSlug, async value => { compareTeam.value = value ? await (await fetch(`${base}data/teams/${value}.json`)).json() : null })
onMounted(async () => { timer = setInterval(tick, 100); try { index.value = await (await fetch(`${base}data/index.json`)).json(); const first=index.value.teams.find(t=>t.team==='华南农业大学')||index.value.teams[0]; if(first) await loadTeam(first.slug) } catch(e) { error.value=e.message } })
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
<div class="shell">
  <aside><div class="brand"><span>RMUC 2026</span><strong>战术情报库 v2</strong></div><input v-model="query" placeholder="搜索队伍"><select v-model="region"><option>全部</option><option>南部赛区</option><option>东部赛区</option><option>北部赛区</option></select><div class="team-list"><button v-for="t in teams" :key="t.slug" :class="{active:selected?.team===t.team}" @click="loadTeam(t.slug)"><span>{{t.team}}</span><small>{{t.wins}}/{{t.games}} · {{t.region}} · 稳定性 {{t.reliability?.grade||'—'}}</small></button></div></aside>
  <main v-if="selected">
    <div class="notice">仅使用规则手册实场图和通信协议 28×15m 官方坐标；行为树内部地图、区域 YAML 与 SCAU 叠加图不参与映射。</div>
    <header><div><p>{{selected.summary.region}} <em v-if="selected.champion">{{selected.champion}}</em></p><h1>{{selected.team}}</h1></div><div class="record"><strong>{{selected.summary.wins}}–{{selected.summary.games-selected.summary.wins}}</strong><span>胜率 {{selected.summary.win_rate.toFixed(1)}}%</span></div></header>
    <section class="kpis"><article><span>场均输出</span><strong>{{selected.summary.avg_damage_dealt?.toFixed(0)}}</strong></article><article><span>场均基地伤害</span><strong>{{selected.summary.avg_base_damage?.toFixed(0)}}</strong></article><article><span>场均前哨伤害</span><strong>{{selected.summary.avg_outpost_damage?.toFixed(0)}}</strong></article><article><span>机器可靠性</span><strong :class="`grade ${reliabilityTone(reliability?.grade)}`">{{reliability?.grade||'—'}}</strong></article></section>
    <section class="grid-two"><article class="panel"><h2>战术分维度评分</h2><div id="score-chart" class="chart"></div></article><article class="panel"><h2>基地与其他目标伤害来源</h2><div id="damage-chart" class="chart"></div></article></section>
    <section class="panel"><h2>机器可靠性（独立于战术评分）</h2><div class="reliability-grid"><div><b>开局完整率</b><strong>{{reliability?.start_complete_pct}}%</strong></div><div><b>在场时间率</b><strong>{{reliability?.availability_pct}}%</strong></div><div><b>高置信掉线局率</b><strong>{{reliability?.disconnect_game_pct}}%</strong></div><div><b>离线 / 恢复</b><strong>{{reliability?.offline_seconds}}s / {{reliability?.recoveries}}</strong></div></div><p class="method">每局前 10 秒和后 10 秒不计入可靠性统计。A：≥99% / ≥99.5% / ≤2%；B：≥97% / ≥98% / ≤5%；C：≥95% / ≥95% / ≤10%；D：≥90% / ≥90% / ≤20%。连续 ≥5 秒每秒约扣最大血量 5% 且 ±1 秒无受击才计入评级；2–4 秒只标记疑似。</p><div class="incident-list"><button v-for="e in selected.disconnect_episodes" :key="`${e.game_id}-${e.robot_id}-${e.start_sec}`" @click="loadGame(selected.matches.find(m=>m.game_id===e.game_id))"><b>局 {{e.game_id}} · {{e.robot_type}}</b><span>{{e.classification}} {{fmtSecond(e.start_sec)}}–{{fmtSecond(e.end_sec)}} · {{e.recovered?'已恢复':'未恢复'}} · {{e.included_in_reliability?'计入评级':'前/后10秒已排除'}}</span></button><p v-if="!selected.disconnect_episodes.length">未检测到高置信或疑似主控离线片段。</p></div></section>
    <section class="panel"><div class="section-head"><h2>秒级热力图</h2><span>真实红方 / 真实蓝方 / 己方归一化</span></div><div class="toolbar"><select v-model="heatView"><option value="actual">实际场地图</option><option value="canonical">己方归一化</option></select><select v-model="heatSide"><option>全部</option><option>红</option><option>蓝</option></select><select v-model="heatRobot"><option>全部</option><option>英雄</option><option>工程</option><option>步兵3</option><option>步兵4</option><option>空中</option><option>哨兵</option></select><label>从 <input type="number" v-model.number="heatFrom"></label><label>到 <input type="number" v-model.number="heatTo"></label><label>地图遮罩 <input type="range" v-model.number="heatMaskOpacity" min="0" max=".75" step=".05"></label></div><p class="method">颜色表示筛选范围内落在 0.5m 格子的累计在场秒数；先按格聚合，再使用对数色阶。最高密度 {{maxHeat}} 车·秒。地图采用“实场底图—热力层—设施轮廓遮罩”三层显示，可调遮罩强度。</p><svg class="field" viewBox="0 0 28 15"><image :href="`${base}maps/field-current.jpg`" width="28" height="15" preserveAspectRatio="none" opacity="1"/><rect v-for="c in aggregatedHeat" :key="`${c.side}-${c.x}-${c.y}`" :x="c.x-.25" :y="c.y-.25" width=".5" height=".5" :fill="heatColor(c)" :opacity="heatOpacity(c)"/><image class="map-mask" :href="`${base}maps/field-current.jpg`" width="28" height="15" preserveAspectRatio="none" :opacity="heatMaskOpacity"/></svg></section>
    <section class="panel"><div class="section-head"><h2>逐局时间轴</h2><span>1 Hz · 双方全车 · 速度 / 尾迹 / 事件</span></div><div class="match-grid"><button v-for="m in selected.matches" :key="m.game_id" :class="{active:activeGame?.game_id===m.game_id}" @click="loadGame(m)"><b>{{m.won?'胜':'负'}} · {{m.opponent}}</b><span>{{m.rule_version}} · {{m.side}}方</span><small>局 {{m.game_id}} · {{fmtSecond(m.duration_sec)}}</small></button></div></section>
    <section v-if="gameData" class="panel timeline"><div class="toolbar"><button class="play" @click="togglePlay">{{playing?'暂停':'播放'}}</button><b>{{fmtSecond(time)}} / {{fmtSecond(gameData.game.duration_sec)}}</b><select v-model.number="speed"><option :value=".5">0.5×</option><option :value="1">1×</option><option :value="2">2×</option><option :value="4">4×</option></select><label>尾迹 <input type="number" v-model.number="tail" min="3" max="120"> 秒</label><select v-model="mapMode"><option value="raster">规则实场图</option><option value="vector">官方坐标简图</option></select><select v-model="routeView"><option value="actual">全局实际阵营</option><option value="own">所选队伍己方视角（整场旋转）</option></select></div><p class="method">全局视图：红方位于地图左侧、蓝方位于右侧；己方视图会将地图和双方机器人整体旋转，不会把两队重叠。</p><input class="scrubber" type="range" min="0" :max="gameData.game.duration_sec" step="1" v-model.number="time"><svg class="field" viewBox="0 0 28 15"><image :href="`${base}maps/${mapFile}`" width="28" height="15" preserveAspectRatio="none" opacity=".72" :transform="routeMapTransform()"/><polyline v-for="trailItem in trails" :key="trailItem.i" :points="trailItem.points.map(p=>frameXY(p).join(',')).join(' ')" fill="none" :stroke="colors[trailItem.i%colors.length]" stroke-width=".09"/><g v-for="row in currentFrame" :key="row[0]" v-show="visibleRobots[row[0]]!==false"><circle :cx="frameXY(row)[0]" :cy="frameXY(row)[1]" r=".19" :fill="colors[row[0]%colors.length]" stroke="white" stroke-width=".04"/><text :x="frameXY(row)[0]+.25" :y="frameXY(row)[1]" font-size=".32" fill="white">{{gameData.robots[row[0]].robot_type}}</text></g></svg><div class="legend"><label v-for="(r,i) in gameData.robots" :key="i"><input type="checkbox" v-model="visibleRobots[i]"><i :style="{background:colors[i%colors.length]}"></i>{{r.side}}{{r.robot_type}} · {{r.team}}</label></div><div class="events"><button v-for="(e,i) in shownEvents.slice(-30)" :key="i" @click="time=e.second"><b>{{fmtSecond(e.second)}} {{e.type}}</b><span>{{e.team||e.detail||''}} · {{e.confidence}}</span></button></div></section>
    <section class="panel"><h2>黄牌 / 红牌推断</h2><p class="method">源数据只有“判罚扣血”，没有牌色字段。以下按同步扣血比例标注高/中置信黄牌、推定红牌或牌色未知，不强行归类。</p><div class="penalty-table"><div v-for="p in selected.penalty_incidents" :key="`${p.game_id}-${p.second}`"><b>局 {{p.game_id}} · {{fmtSecond(p.second)}} · {{p.incident_type}}</b><span>{{p.offender_type||'对象未知'}} · 扣血 {{p.penalty_damage}} · {{p.confidence}}置信<span v-if="p.inferred_red"> · 推定红牌</span></span></div><p v-if="!selected.penalty_incidents.length">该队样本中无可识别判罚事件。</p></div></section>
    <section class="panel"><h2>稳定战术与全队克制方案</h2><div class="patterns"><div v-for="p in selected.patterns" :key="p.pattern_id" :class="['pattern',p.classification]"><b>{{p.label}}</b><span>{{p.classification}} · {{(p.rate*100).toFixed(0)}}%</span><small>{{p.games_observed}} 局 / {{p.opponents}} 个对手</small></div></div><div class="counter" v-for="item in selected.counter_plan" :key="item.signal"><b>{{item.signal}}</b><p>{{item.action}}</p><small>退出：{{item.exit}}</small></div></section>
    <section class="panel compare"><h2>双队对比</h2><select v-model="compareSlug"><option value="">选择另一支队伍</option><option v-for="t in index.teams.filter(t=>t.team!==selected.team)" :value="t.slug">{{t.team}}</option></select><div v-if="compareTeam" class="compare-grid"><div><b>{{selected.team}}</b><span>火力 {{selected.scores.firepower}}</span><span>可靠性 {{selected.reliability?.grade}}</span></div><div><b>{{compareTeam.team}}</b><span>火力 {{compareTeam.scores.firepower}}</span><span>可靠性 {{compareTeam.reliability?.grade}}</span></div></div></section>
  </main><main v-else><p>{{error||'正在加载…'}}</p></main>
</div>
</template>
