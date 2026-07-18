<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { init, use } from 'echarts/core'
import { BarChart, RadarChart } from 'echarts/charts'
import { GridComponent, RadarComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { aggregateHeatCells, densityOpacity, matchupEstimate, officialToMap, rankRoleTeams, rankTeamsByStrength, rasterMapCenter, rasterMapPlacement, rasterMapPoint, roleFrameSeries, roleMetrics, strengthGrade, summarizeDimensions, swissNextPairings, swissStandings, teamPerspectivePoint, teamStrength } from './domain.js'

use([BarChart, RadarChart, GridComponent, RadarComponent, TooltipComponent, CanvasRenderer])
const base = import.meta.env.BASE_URL
const dataRevision = 'score-3.9.0-role-data-1.1.0-tournament-2.0.0'
const index = ref({ teams: [] }), selected = ref(null), query = ref(''), region = ref('全部'), error = ref('')
const heat = ref(null), heatSide = ref('全部'), heatRobot = ref('全部'), heatView = ref('actual'), heatFrom = ref(0), heatTo = ref(420), heatMaskOpacity = ref(.34)
const gameData = ref(null), activeGame = ref(null), time = ref(0), playing = ref(false), speed = ref(1), tail = ref(20), mapMode = ref('raster'), routeView = ref('actual')
const visibleRobots = ref({}), compareSlug = ref(''), compareTeam = ref(null)
const viewMode = ref('team'), roleCatalog = ref({ roles: [] }), selectedRoleSlug = ref('hero'), roleIndex = ref(null), roleTeam = ref(null)
const roleRegion = ref('全部'), roleQuery = ref(''), roleMetric = ref('availability_pct'), activeRoleGameId = ref(null), roleTime = ref(0)
const tournamentConfig = ref(null), tournamentMode = ref('repechage'), tournamentTeams = ref({ repechage: [], finals: [] }), tournamentGroups = ref({ repechage: [[], []], finals: [[], []] }), tournamentRounds = ref({ repechage: { A: [], B: [] }, finals: { A: [], B: [] } }), finalsQualifiers = ref([null, null, null, null]), tournamentBusy = ref(false)
const tournamentLabels = ['A', 'B']
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
  const evidence = selected.value?.dimension_confidence?.[dimension]
  const ranking = rank ? (rank <= 20 ? `TOP ${rank}` : `第 ${rank}/96`) : '—'
  return evidence == null ? ranking : `${ranking} · 证据 ${Math.round(evidence)}%`
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
function fetchData(path) { return fetch(`${base}${path}?v=${dataRevision}`, { cache: 'no-store' }) }
function saveTournament() {
  localStorage.setItem('rmuc-tournament-pickem-2', JSON.stringify({ groups: tournamentGroups.value, rounds: tournamentRounds.value, finalsQualifiers: finalsQualifiers.value }))
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
  const groupRounds = tournamentRounds.value[mode][group].map((round, index) => index !== roundIndex ? round : { ...round, matches: round.matches.map((match, matchAt) => matchAt === matchIndex ? { ...match, winner } : match) })
  tournamentRounds.value = { ...tournamentRounds.value, [mode]: { ...tournamentRounds.value[mode], [group]: groupRounds } }; saveTournament()
}
function autoSwissRound(board) {
  let rounds = tournamentRounds.value[tournamentMode.value][board.label]
  if (!rounds.length || rounds.at(-1).matches.every(match => match.winner)) startSwissRound({ ...board, rounds })
  rounds = tournamentRounds.value[tournamentMode.value][board.label]
  if (!rounds.length || rounds.at(-1).matches.every(match => match.winner)) return
  const index = rounds.length - 1
  rounds[index].matches.forEach((match, matchIndex) => setSwissWinner(board.label, index, matchIndex, match.firstPct >= match.secondPct ? match.first : match.second))
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
  tournamentRounds.value = { ...tournamentRounds.value, finals: { A: [], B: [] } }; saveTournament()
}
async function loadTournament() {
  if (tournamentConfig.value || tournamentBusy.value) return
  tournamentBusy.value = true
  try {
    const response = await fetchData('data/repechage.json')
    if (!response.ok) throw new Error('赛事竞猜名单加载失败')
    tournamentConfig.value = await response.json()
    const loaded = {}
    for (const mode of ['repechage', 'finals']) {
      loaded[mode] = await Promise.all(tournamentConfig.value[mode].teams.map(async item => {
        if (item.placeholder) return buildPlaceholder(item)
        const listing = index.value.teams.find(team => team.team === item.team)
        if (!listing) throw new Error(`${item.team} 与战术数据库无法对齐`)
        return { ...await (await fetchData(`data/teams/${listing.slug}.json`)).json(), battle_name: item.battle_name, tier: item.tier }
      }))
    }
    tournamentTeams.value = loaded
    let restored = null
    try { restored = JSON.parse(localStorage.getItem('rmuc-tournament-pickem-2') || 'null') } catch { restored = null }
    if (restored?.groups?.repechage?.flat().length === 16 && restored?.groups?.finals?.flat().length === 32) {
      tournamentGroups.value = restored.groups; tournamentRounds.value = restored.rounds || tournamentRounds.value; finalsQualifiers.value = restored.finalsQualifiers || finalsQualifiers.value
      refreshFinalsPlaceholders()
    } else { tournamentMode.value = 'repechage'; randomizeTournament(); tournamentMode.value = 'finals'; randomizeTournament(); tournamentMode.value = 'repechage' }
  } finally { tournamentBusy.value = false }
}
function switchTournament(mode) { tournamentMode.value = mode }
function switchView(mode) { viewMode.value = mode; if (mode === 'repechage') loadTournament() }
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
async function loadRoleIndex(roleSlug = selectedRoleSlug.value) {
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
}
function selectRoleGame(game) { activeRoleGameId.value = game.game_id; roleTime.value = 0 }
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
onMounted(async () => { timer = setInterval(tick, 100); try { const [teamResponse, roleResponse] = await Promise.all([fetchData('data/index.json'), fetchData('data/roles/index.json')]); index.value = await teamResponse.json(); roleCatalog.value = await roleResponse.json(); const first=index.value.teams.find(t=>t.team==='广东工业大学')||rankedTeams.value[0]; if(first) await loadTeam(first.slug); await loadRoleIndex(selectedRoleSlug.value) } catch(e) { error.value=e.message } })
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
<div class="shell">
  <aside><div class="brand"><span>RMUC 2026</span><strong>战术情报库 v3</strong></div><div class="view-tabs"><button :class="{active:viewMode==='team'}" @click="switchView('team')">队伍</button><button :class="{active:viewMode==='role'}" @click="switchView('role')">兵种</button><button :class="{active:viewMode==='repechage'}" @click="switchView('repechage')">赛事竞猜</button></div><template v-if="viewMode==='team'"><input v-model="query" placeholder="搜索队伍"><select v-model="region"><option>全部</option><option>南部赛区</option><option>东部赛区</option><option>北部赛区</option></select><div class="team-list"><button v-for="t in teams" :key="t.slug" :class="{active:selected?.team===t.team}" @click="loadTeam(t.slug)"><span>{{t.team}}</span><small>#{{t.strengthRank}} · {{t.wins}}/{{t.games}} · {{t.region}}<template v-if="t.placement"> · {{t.placement.label}}</template> · 强度 {{strengthGrade(teamStrength(t))}}</small></button></div></template><template v-else-if="viewMode==='role'"><select :value="selectedRoleSlug" @change="loadRoleIndex($event.target.value)"><option v-for="role in roleCatalog.roles" :key="role.role_slug" :value="role.role_slug">{{role.role}}</option></select><select v-model="roleMetric"><option v-for="([key,definition]) in availableRoleMetrics" :key="key" :value="key">按{{definition.label}}排序</option></select><input v-model="roleQuery" placeholder="搜索队伍"><select v-model="roleRegion"><option>全部</option><option>南部赛区</option><option>东部赛区</option><option>北部赛区</option></select><div class="team-list"><button v-for="t in roleTeams" :key="t.slug" :class="{active:roleTeam?.team===t.team}" @click="loadRoleTeam(t.slug)"><span>{{t.team}}</span><small>#{{t.factRank}} · {{roleMetrics[roleMetric].label}} {{roleValue(t.factValue,roleMetrics[roleMetric].suffix)}} · {{t.region}}</small></button></div></template><template v-else><div class="pick-sidebar"><b>赛事 Pick'Em</b><button :class="{active:tournamentMode==='repechage'}" @click="switchTournament('repechage')">复活赛 · 16 队</button><button :class="{active:tournamentMode==='finals'}" @click="switchTournament('finals')">全国赛 · 32 队</button><span v-for="board in tournamentBoards" :key="board.label">{{board.label}}组 · {{board.rounds.length}} / {{activeTournament?.swiss_rounds||0}} 轮</span><small>分组、赛果保存在当前浏览器</small></div></template></aside>
  <main v-if="viewMode==='repechage'" class="pickem-main">
    <p v-if="tournamentBusy && !tournamentConfig">正在加载赛事名单与胜率模型…</p>
    <template v-else-if="activeTournament">
      <div class="tournament-switch"><button :class="{active:tournamentMode==='repechage'}" @click="switchTournament('repechage')">复活赛</button><button :class="{active:tournamentMode==='finals'}" @click="switchTournament('finals')">全国赛</button></div>
      <div class="notice">{{activeTournament.draw_note}}</div>
      <header><div><p>{{activeTournament.dates}} · {{activeTournament.format}}</p><h1>{{activeTournament.title}} Major Pick'Em</h1></div><div class="tournament-actions"><button class="random-button" @click="randomizeTournament">重新模拟抽签</button><button class="random-button secondary" @click="resetTournamentResults">重置赛果</button></div></header>
      <section v-if="tournamentMode==='finals'" class="panel qualifier-panel"><div class="section-head"><h2>填入 4 支复活赛晋级队</h2><span>未确定时可保留占位队</span></div><div class="qualifier-selects"><label v-for="(_,indexAt) in finalsQualifiers" :key="indexAt">晋级队 {{indexAt+1}}<select :value="finalsQualifiers[indexAt]||''" @change="setFinalsQualifier(indexAt,$event.target.value)"><option value="">待定</option><option v-for="team in tournamentTeams.repechage" :key="team.team" :value="team.team">{{team.team}} · {{team.battle_name}}</option></select></label></div></section>
      <section class="pickem-grid">
        <article v-for="(board,groupIndex) in tournamentBoards" :key="board.label" class="panel pick-group swiss-board">
          <div class="section-head"><h2>{{board.label}} 组</h2><span>{{board.members.length}} 队 · {{activeTournament.swiss_rounds}} 轮</span></div>
          <div class="draw-list">
            <div v-for="team in board.members" :key="team.team" class="pick-team">
              <div class="pick-team-main"><b>{{tournamentDisplay(team.team)}}</b><small>{{team.battle_name}} · 第{{team.tier}}档 · {{team.placeholder?'资格占位':`全局 #${team.overall_rank}`}}</small><span>模型强度 <strong>{{teamStrength(team).toFixed(1)}}</strong> · {{board.standings.find(item=>item.team===team.team)?.wins||0}}–{{board.standings.find(item=>item.team===team.team)?.losses||0}} · {{board.standings.find(item=>item.team===team.team)?.status}}</span></div>
              <select :value="groupIndex" :aria-label="`${tournamentDisplay(team.team)}分组`" @change="moveTournamentTeam(team.team,$event.target.value)"><option v-for="(_,target) in tournamentLabels" :key="target" :value="target">{{tournamentLabels[target]}}组</option></select>
            </div>
          </div>
          <div class="round-actions"><button v-if="!board.rounds.length" @click="startSwissRound(board)">生成第 1 轮对阵</button><button v-else-if="board.rounds.length<activeTournament.swiss_rounds && board.rounds.at(-1).matches.every(match=>match.winner)" @click="startSwissRound(board)">生成第 {{board.rounds.length+1}} 轮对阵</button><button v-if="board.rounds.length<activeTournament.swiss_rounds || board.rounds.some(round=>round.matches.some(match=>!match.winner))" @click="autoSwissRound(board)">模型自动推演本轮</button></div>
          <div class="swiss-rounds">
            <section v-for="(round,roundIndex) in board.rounds" :key="round.round" class="swiss-round"><h3>第 {{round.round}} 轮</h3><div v-for="(match,matchIndex) in round.matches" :key="`${match.first}-${match.second}`" class="swiss-match"><button :class="{winner:match.winner===match.first}" @click="setSwissWinner(board.label,roundIndex,matchIndex,match.first)"><span>{{tournamentDisplay(match.first)}}</span><strong>{{match.firstPct}}%</strong></button><em>BO3</em><button :class="{winner:match.winner===match.second}" @click="setSwissWinner(board.label,roundIndex,matchIndex,match.second)"><strong>{{match.secondPct}}%</strong><span>{{tournamentDisplay(match.second)}}</span></button></div></section>
          </div>
          <details class="standings" open><summary>实时积分榜</summary><div v-for="(record,rankAt) in board.standings" :key="record.team" :class="['standing-row',record.status]"><b>#{{rankAt+1}} {{tournamentDisplay(record.team)}}</b><span>{{record.wins}}胜 {{record.losses}}负 · 对手分 {{record.opponentScore>0?'+':''}}{{record.opponentScore}}</span><em>{{record.status}}</em></div></details>
        </article>
      </section>
      <p class="method">赛制门槛来自全国总决赛参赛手册 V2.1.0：复活赛 A/B 各 8 队进行 3 轮瑞士轮，累计 2 负淘汰，其余队进入 4 个全国赛名额的后续争夺；全国赛 A/B 各 16 队进行 5 轮瑞士轮，3 胜晋级、3 负淘汰。模拟首轮按抽签序号高低位配对，后续按胜负、手册定义的对手分排序，优先相邻战绩且避免重复交手；尚无官方基地净血量与全队伤害同分数据时，以模型强度处理排序冲突。页面胜率与自动赛果是战术数据库模型估计，不是官方赛果。</p>
    </template>
  </main>
  <main v-else-if="viewMode==='role' && roleTeam && roleIndex" class="role-main">
    <div class="notice">造成伤害是兵种级推定：42mm 按兵种唯一性归因，17mm 按同秒/前 1 秒发弹份额分配；不是射手身份或命中率。原始秒级数据完整保留。</div>
    <header><div><p>{{roleTeam.region}} · {{roleTeam.mode==='second'?'完整秒级状态':'完整事件记录'}}</p><h1>{{roleTeam.team}} · {{roleTeam.role}}</h1></div><div class="role-downloads"><a :href="`${base}${roleIndex.downloads.csv_gz}`">下载 CSV.gz</a><a :href="`${base}${roleIndex.downloads.json_gz}`">下载 JSON.gz</a></div></header>
    <template v-if="roleTeam.mode==='second'">
      <section class="kpis"><article><span>推定场均伤害</span><strong>{{roleValue(roleTeam.summary.estimated_damage_per_game)}}</strong></article><article><span>推定基地伤害/局</span><strong>{{roleValue(roleTeam.summary.estimated_base_damage_per_game)}}</strong></article><article><span>推定前哨伤害/局</span><strong>{{roleValue(roleTeam.summary.estimated_outpost_damage_per_game)}}</strong></article><article><span>归因置信度</span><strong>{{roleValue(roleTeam.summary.estimated_damage_confidence_pct,'%')}}</strong></article></section>
      <section class="panel"><div class="section-head"><h2>兵种事实与推定画像</h2><span>逐指标排名，不合成兵种总分</span></div><div class="metric-pairs role-facts"><span>参赛覆盖<strong>{{roleTeam.summary.role_present_games}} / {{roleTeam.summary.games}} 局</strong></span><span>有效在场率<strong>{{roleValue(roleTeam.summary.availability_pct,'%')}}</strong></span><span>场均阵亡<strong>{{roleValue(roleTeam.summary.deaths_per_game)}}</strong></span><span>平均终局血量<strong>{{roleValue(roleTeam.summary.terminal_hp_pct,'%')}}</strong></span><span>场均里程<strong>{{roleValue(roleTeam.summary.distance_per_game_m,' m')}}</strong></span><span>推进纵深<strong>{{roleValue(roleTeam.summary.attack_depth_m,' m')}}</strong></span><span>前压在场<strong>{{roleValue(roleTeam.summary.forward_presence_pct,'%')}}</strong></span><span>场均发弹<strong>{{roleValue(roleTeam.summary.shots_per_game)}}</strong></span><span>推定机器人伤害/局<strong>{{roleValue(roleTeam.summary.estimated_robot_damage_per_game)}}</strong></span><span>高置信推定伤害<strong>{{roleValue(roleTeam.summary.high_confidence_estimated_damage)}}</strong></span><span>每存活分钟净承伤<strong>{{roleValue(roleTeam.summary.combat_damage_per_alive_min)}}</strong></span><span>定位覆盖<strong>{{roleValue(roleTeam.summary.position_coverage_pct,'%')}}</strong></span></div></section>
      <section class="panel"><div class="section-head"><h2>逐局兵种表现</h2><span>{{roleTeam.games.length}} 个有效兵种对局</span></div><div class="match-grid"><button v-for="game in roleTeam.games" :key="game.game_id" :class="{active:activeRoleGame?.game_id===game.game_id}" @click="selectRoleGame(game)"><b>{{game.won?'胜':'负'}} · {{game.opponent}}</b><span>{{game.side}}方 · 推定伤害 {{roleValue(game.summary.estimated_damage_dealt)}} · 置信 {{roleValue(game.summary.estimated_damage_confidence_pct,'%')}}</span><small>基地 {{roleValue(game.summary.estimated_base_damage)}} · 前哨 {{roleValue(game.summary.estimated_outpost_damage)}} · 机器人 {{roleValue(game.summary.estimated_robot_damage)}}</small></button></div></section>
      <section v-if="activeRoleGame" class="grid-two role-telemetry"><article class="panel"><div class="section-head"><h2>血量 / 热量 / 功率时间线</h2><span>{{fmtSecond(roleTime)}} / {{fmtSecond(activeRoleGame.duration_sec)}}</span></div><input class="scrubber" type="range" min="0" :max="activeRoleGame.duration_sec" step="1" v-model.number="roleTime"><svg class="role-line" viewBox="0 0 1000 220" preserveAspectRatio="none"><line x1="0" y1="210" x2="1000" y2="210"/><polyline :points="roleSeriesPoints('hpRatio')" class="hp-line"/><polyline :points="roleSeriesPoints('heatRatio')" class="heat-line"/><polyline :points="roleSeriesPoints('power')" class="power-line"/></svg><div class="role-line-legend"><span class="hp">血量 {{roleValue((roleCurrentFrame?.hpRatio||0)*100,'%')}}</span><span class="heat">热量 {{roleValue((roleCurrentFrame?.heatRatio||0)*100,'%')}}</span><span class="power">功率 {{roleValue(roleCurrentFrame?.power)}}</span></div></article><article class="panel"><div class="section-head"><h2>完整比赛轨迹</h2><span>官方坐标投影</span></div><svg class="field" viewBox="0 0 28 15"><image :href="`${base}maps/field-current.jpg`" width="28" height="15" preserveAspectRatio="none" opacity=".72"/><polyline :points="roleTrailPoints" fill="none" stroke="#f8d66d" stroke-width=".08"/><circle v-if="roleCurrentFrame?.valid" :cx="roleFramePoint(roleCurrentFrame)[0]" :cy="roleFramePoint(roleCurrentFrame)[1]" r=".2" fill="#22d3ee" stroke="white" stroke-width=".04"/></svg></article></section>
    </template>
    <template v-else><section class="kpis"><article><span>飞镖命中</span><strong>{{roleTeam.summary.hits}}</strong></article><article><span>累计伤害</span><strong>{{roleTeam.summary.damage}}</strong></article><article><span>命中覆盖</span><strong>{{roleValue(roleTeam.summary.hit_game_pct,'%')}}</strong></article><article><span>首命中中位</span><strong>{{roleTeam.summary.median_first_hit_sec==null?'—':fmtSecond(roleTeam.summary.median_first_hit_sec)}}</strong></article></section><section class="panel"><div class="section-head"><h2>逐局飞镖事件</h2><span>飞镖无连续状态，仅展示闸门与命中</span></div><div class="radar-events dart-events"><div><button v-for="game in roleTeam.games.filter(game=>game.events.length)" :key="game.game_id"><b>局 {{game.game_id}} · {{game.won?'胜':'负'}}</b><span>对手 {{game.opponent}} · {{game.side}}方</span><span>闸门 {{game.summary.gate_events}} · 命中 {{game.summary.hits}} · 伤害 {{game.summary.damage}}</span></button></div></div></section></template>
    <section class="panel"><h2>口径限制</h2><p v-for="item in roleTeam.limitations" :key="item" class="method">{{item}}</p></section>
  </main>
  <main v-else-if="selected">
    <div class="notice">仅使用规则手册实场图和通信协议 28×15m 官方坐标；行为树内部地图、区域 YAML 与 SCAU 叠加图不参与映射。</div>
    <header><div><p>{{selected.summary.region}} <em v-if="selected.placement">{{selected.summary.region}}{{selected.placement.label}}</em></p><h1>{{selected.team}}</h1></div><div class="record"><strong>{{selected.summary.wins}}–{{selected.summary.games-selected.summary.wins}}</strong><span>胜率 {{selected.summary.win_rate.toFixed(1)}}% · 全局 #{{selected.overall_rank}}</span></div></header>
    <section class="kpis"><article><span>场均输出</span><strong>{{selected.summary.avg_damage_dealt?.toFixed(0)}}</strong></article><article><span>场均基地伤害</span><strong>{{selected.summary.avg_base_damage?.toFixed(0)}}</strong></article><article><span>场均前哨伤害</span><strong>{{selected.summary.avg_outpost_damage?.toFixed(0)}}</strong></article><article><span>综合强度评级</span><strong class="strength-grade" :data-grade="grade">{{grade}} · {{strength.toFixed(1)}}</strong></article></section>
    <section class="grid-two"><article class="panel"><h2>战术分维度评分</h2><div id="score-chart" class="chart"></div></article><article class="panel"><h2>基地与其他目标伤害来源</h2><div id="damage-chart" class="chart"></div></article></section>
    <section class="panel">
      <div class="section-head"><h2>高维战术解析 3.9</h2><span>逐局净事实 · 条件校正 · 时间回测</span></div>
      <p class="method coverage-note"><b>规则权重：</b>依据比赛规则 V2.0.1 第 5.8 节，基地/前哨、攻击伤害与剩余血量对应的直接胜负维度合计 74%；空间、资源与适应是促成维度。判罚、撞击和定位覆盖不进入战术得分。</p>
      <div class="evidence-grid"><span>火力<strong>{{show(selected.dimension_confidence?.firepower,'%')}}</strong></span><span>目标<strong>{{show(selected.dimension_confidence?.objective,'%')}}</strong></span><span>空间<strong>{{show(selected.dimension_confidence?.spatial,'%')}}</strong></span><span>防守<strong>{{show(selected.dimension_confidence?.defense,'%')}}</strong></span><span>资源<strong>{{show(selected.dimension_confidence?.resource,'%')}}</strong></span><span>适应<strong>{{show(selected.dimension_confidence?.adaptability,'%')}}</strong></span></div>
      <div class="insight-grid">
        <article class="insight-card"><h3>净战斗火力 · {{show(dimensions.analysis.firepower?.score)}}</h3><div class="metric-pairs"><span>对手校正净输出 · 35%<strong>{{show(dimensions.analysis.firepower?.components?.clean_output)}}</strong></span><span>机器人命中效率 · 15%<strong>{{show(dimensions.analysis.firepower?.components?.accuracy)}}</strong></span><span>阵亡转化 · 25%<strong>{{show(dimensions.analysis.firepower?.components?.kill_conversion)}}</strong></span><span>持续施压 · 25%<strong>{{show(dimensions.analysis.firepower?.components?.pressure_uptime)}}</strong></span><span>净输出相对预期<strong>{{show(dimensions.analysis.firepower?.raw?.clean_output,'×')}}</strong></span><span>机器人命中率<strong>{{show(Math.round((dimensions.analysis.firepower?.raw?.accuracy||0)*1000)/10,'%')}}</strong></span></div></article>
        <article class="insight-card"><h3>目标转化 · {{show(dimensions.analysis.objective?.score)}}</h3><div class="metric-pairs"><span>前哨施压 · 10%<strong>{{show(dimensions.analysis.objective?.components?.outpost_pressure)}}</strong></span><span>前哨转化 · 25%<strong>{{show(dimensions.analysis.objective?.components?.outpost_conversion)}}</strong></span><span>基地施压 · 15%<strong>{{show(dimensions.analysis.objective?.components?.base_pressure)}}</strong></span><span>基地转化 · 35%<strong>{{show(dimensions.analysis.objective?.components?.base_conversion)}}</strong></span><span>战略工具 · 15%<strong>{{show(dimensions.analysis.objective?.components?.strategic_tools)}}</strong></span><span>首伤前哨中位<strong>{{dimensions.objective.firstOutpostSec==null?'—':fmtSecond(dimensions.objective.firstOutpostSec)}}</strong></span><span>中位击毁耗时<strong>{{dimensions.objective.medianOutpostKillSec==null?'—':fmtSecond(dimensions.objective.medianOutpostKillSec)}}</strong></span><span>有效击毁样本<strong>{{dimensions.objective.outpostKillGames}} 局</strong></span></div></article>
        <article class="insight-card"><h3>空间控制 · {{show(dimensions.analysis.spatial?.score)}}</h3><div class="metric-pairs"><span>相对领土纵深 · 25%<strong>{{show(dimensions.analysis.spatial?.components?.relative_territory)}}</strong></span><span>前压在场 · 30%<strong>{{show(dimensions.analysis.spatial?.components?.forward_presence)}}</strong></span><span>中区相对控制 · 35%<strong>{{show(dimensions.analysis.spatial?.components?.neutral_control)}}</strong></span><span>场地覆盖 · 10%<strong>{{show(dimensions.analysis.spatial?.components?.field_coverage)}}</strong></span><span>相对推进纵深<strong>{{show(dimensions.analysis.spatial?.raw?.relative_territory,' m')}}</strong></span><span>前压车秒占比<strong>{{show(Math.round((dimensions.analysis.spatial?.raw?.forward_presence||0)*1000)/10,'%')}}</strong></span><span>定位覆盖（仅置信度）<strong>{{show(dimensions.confidence?.position_coverage_pct,'%')}}</strong></span></div></article>
        <article class="insight-card defense-card"><h3>防守韧性 · {{show(dimensions.analysis.defense?.score)}}</h3><div class="metric-pairs"><span>校正伤害交换 · 35%<strong>{{show(dimensions.analysis.defense?.components?.trade_resilience)}}</strong></span><span>机器人韧性 · 25%<strong>{{show(dimensions.analysis.defense?.components?.mobile_resilience)}}</strong></span><span>前哨拒止 · 15%<strong>{{show(dimensions.analysis.defense?.components?.outpost_denial)}}</strong></span><span>基地拒止 · 15%<strong>{{show(dimensions.analysis.defense?.components?.base_denial)}}</strong></span><span>整体防守下限 · 10%<strong>{{show(dimensions.analysis.defense?.components?.collapse_resistance)}}</strong></span><span>结构口径<strong>存活时长 · 终局血量 · 对手火力抑制</strong></span><span>已排除噪声<strong>判罚 {{show(dimensions.analysis.defense?.excluded?.penalty_damage)}} · 撞击 {{show(dimensions.analysis.defense?.excluded?.collision_damage)}}</strong></span></div></article>
        <article class="insight-card"><h3>资源转化 · {{show(dimensions.analysis.resource?.score)}}</h3><div class="metric-pairs"><span>经济获取 · 40%<strong>{{show(dimensions.analysis.resource?.components?.acquisition)}}</strong></span><span>经济使用 · 5%<strong>{{show(dimensions.analysis.resource?.components?.utilization)}}</strong></span><span>战斗转化 · 10%<strong>{{show(dimensions.analysis.resource?.components?.combat_conversion)}}</strong></span><span>目标转化 · 25%<strong>{{show(dimensions.analysis.resource?.components?.objective_conversion)}}</strong></span><span>热控效率 · 20%<strong>{{show(dimensions.analysis.resource?.components?.thermal_efficiency)}}</strong></span><span>经济使用率<strong>{{show(Math.round((dimensions.analysis.resource?.raw?.utilization||0)*1000)/10,'%')}}</strong></span></div></article>
        <article class="insight-card"><h3>适应能力 · {{show(dimensions.analysis.adaptability?.score)}}</h3><div class="metric-pairs"><span>红蓝方迁移 · 10%<strong>{{show(dimensions.analysis.adaptability?.components?.side_transfer)}}</strong></span><span>跨对手下限 · 10%<strong>{{show(dimensions.analysis.adaptability?.components?.opponent_robustness)}}</strong></span><span>强敌超预期 · 20%<strong>{{show(dimensions.analysis.adaptability?.components?.strong_opponent_residual)}}</strong></span><span>局内失守后调整 · 30%<strong>{{show(dimensions.analysis.adaptability?.components?.setback_adjustment)}}</strong></span><span>败局后再战调整 · 30%<strong>{{show(dimensions.analysis.adaptability?.components?.rematch_adjustment)}}</strong></span><span>缺失条件样本<strong>只回归中性，不加减分</strong></span></div></article>
        <article class="insight-card"><h3>雷达反制 UAV</h3><div class="metric-pairs"><span>发起反制<strong>{{dimensions.radar?.counter_uses||0}} 次</strong></span><span>使用覆盖<strong>{{dimensions.radar?.counter_use_games||0}} 局 / {{show(dimensions.radar?.counter_use_game_pct,'%')}}</strong></span><span>中位触发<strong>{{dimensions.radar?.median_counter_sec==null?'—':fmtSecond(dimensions.radar.median_counter_sec)}}</strong></span><span>90 秒内使用<strong>{{show(dimensions.radar?.early_counter_pct,'%')}}</strong></span><span>己方空中被反制<strong>{{dimensions.radar?.countered_events||0}} 次</strong></span><span>涉及对局<strong>{{dimensions.radar?.countered_games||0}} 局</strong></span></div></article>
        <article class="insight-card strength-card"><h3>综合强度 3.9 · {{show(dimensions.strength?.score)}}</h3><div class="metric-pairs"><span>六维战术 · 90%<strong>{{show(dimensions.strength?.tactical_score)}}</strong></span><span>赛程校正赛果 · 10%<strong>{{show(dimensions.strength?.result_score)}}</strong></span><span>规则直接胜负维度<strong>74% · 目标50 / 火力15 / 防守9</strong></span><span>促成维度<strong>26% · 资源14 / 空间11 / 适应1</strong></span><span>赛程强度参数<strong>{{show(dimensions.strength?.schedule_rating)}}</strong></span><span>透明对手分（不重复计分）<strong>{{show(dimensions.opponentScore?.score)}} · 赛区第 {{show(dimensions.opponentScore?.region_rank)}}/{{show(dimensions.opponentScore?.region_size)}}</strong></span><span>对手去直接交手胜率<strong>{{show(dimensions.opponentScore?.opponent_win_rate_pct,'%')}}</strong></span><span>二阶对手胜率<strong>{{show(dimensions.opponentScore?.opponent_opponent_win_rate_pct,'%')}}</strong></span><span>不同对手数<strong>{{show(dimensions.opponentScore?.unique_opponents)}} 个</strong></span><span>数据置信度（不计分）<strong>{{show(dimensions.confidence?.overall,'%')}}</strong></span><span>验证方式<strong>滚动时间回测 · 分箱校准</strong></span></div></article>
      </div>
      <details v-if="dimensions.objective.outpostTimeline.length" class="radar-events outpost-events"><summary>展开逐局前哨击打时间线（{{dimensions.objective.outpostTimeline.length}} 局）</summary><div><button v-for="event in dimensions.objective.outpostTimeline" :key="event.gameId" @click="loadGame(selected.matches.find(match=>match.game_id===event.gameId))"><b>局 {{event.gameId}} · 首伤 {{fmtSecond(event.firstDamageSec)}}</b><span>{{event.won?'胜':'负'}} · {{event.side}}方 · 对手 {{event.opponent}}</span><span>累计前哨伤害 {{event.damage}} · {{event.destroySec==null?'未摧毁':'击毁 '+fmtSecond(event.destroySec)+' · 耗时 '+fmtSecond(event.killDurationSec)}}</span></button></div></details>
      <details v-if="dimensions.radar?.events?.length" class="radar-events"><summary>展开雷达事件时间线（{{dimensions.radar.events.length}} 条，含发起与被反制）</summary><div><button v-for="(event,i) in dimensions.radar.events" :key="event.game_id+'-'+event.second+'-'+event.role+'-'+i" @click="loadGame(selected.matches.find(match=>match.game_id===event.game_id))"><b>局 {{event.game_id}} · {{fmtSecond(event.second)}} · {{event.role}}</b><span>对手：{{event.opponent}}</span></button></div></details>
    </section>
    <section class="panel"><div class="section-head"><h2>秒级热力图</h2><span>真实红方 / 真实蓝方 / 己方归一化</span></div><div class="toolbar"><select v-model="heatView"><option value="actual">实际场地图</option><option value="canonical">己方归一化</option></select><select v-model="heatSide"><option>全部</option><option>红</option><option>蓝</option></select><select v-model="heatRobot"><option>全部</option><option>英雄</option><option>工程</option><option>步兵3</option><option>步兵4</option><option>空中</option><option>哨兵</option></select><label>从 <input type="number" v-model.number="heatFrom"></label><label>到 <input type="number" v-model.number="heatTo"></label><label>地图遮罩 <input type="range" v-model.number="heatMaskOpacity" min="0" max=".75" step=".05"></label></div><p class="method">颜色表示筛选范围内落在 0.5m 格子的累计在场秒数；先按格聚合，再使用对数色阶。最高密度 {{maxHeat}} 车·秒。官方 28×15m 坐标投影到实场图内墙 ROI，外部围挡仅作背景。</p><svg class="field" viewBox="0 0 28 15"><image :href="`${base}maps/field-current.jpg`" width="28" height="15" preserveAspectRatio="none" opacity="1"/><rect v-for="c in aggregatedHeat" :key="`${c.side}-${c.x}-${c.y}`" :x="c.x-.25*heatPlacement.scaleX" :y="c.y-.25*heatPlacement.scaleY" :width=".5*heatPlacement.scaleX" :height=".5*heatPlacement.scaleY" :fill="heatColor(c)" :opacity="heatOpacity(c)"/><image class="map-mask" :href="`${base}maps/field-current.jpg`" width="28" height="15" preserveAspectRatio="none" :opacity="heatMaskOpacity"/></svg></section>
    <section class="panel"><div class="section-head"><h2>逐局时间轴</h2><span>1 Hz · 双方全车 · 速度 / 尾迹 / 事件</span></div><div class="match-grid"><button v-for="m in selected.matches" :key="m.game_id" :class="{active:activeGame?.game_id===m.game_id}" @click="loadGame(m)"><b>{{m.won?'胜':'负'}} · {{m.opponent}}</b><span>{{m.rule_version}} · {{m.side}}方</span><small>局 {{m.game_id}} · {{fmtSecond(m.duration_sec)}}</small></button></div></section>
    <section v-if="gameData" class="panel timeline"><div class="toolbar"><button class="play" @click="togglePlay">{{playing?'暂停':'播放'}}</button><b>{{fmtSecond(time)}} / {{fmtSecond(gameData.game.duration_sec)}}</b><select v-model.number="speed"><option :value=".5">0.5×</option><option :value="1">1×</option><option :value="2">2×</option><option :value="4">4×</option></select><label>尾迹 <input type="number" v-model.number="tail" min="3" max="120"> 秒</label><select v-model="mapMode"><option value="raster">规则实场图</option><option value="vector">官方坐标简图</option></select><select v-model="routeView"><option value="actual">全局实际阵营</option><option value="own">所选队伍己方视角（整场旋转）</option></select></div><p class="method">全局视图：红方位于地图左侧、蓝方位于右侧；己方视图会将地图和双方机器人整体旋转，不会把两队重叠。</p><input class="scrubber" type="range" min="0" :max="gameData.game.duration_sec" step="1" v-model.number="time"><svg class="field" viewBox="0 0 28 15"><image :href="`${base}maps/${mapFile}`" width="28" height="15" preserveAspectRatio="none" opacity=".72" :transform="routeMapTransform()"/><polyline v-for="trailItem in trails" :key="trailItem.i" :points="trailItem.points.map(p=>frameXY(p).join(',')).join(' ')" fill="none" :stroke="colors[trailItem.i%colors.length]" stroke-width=".09"/><g v-for="row in currentFrame" :key="row[0]" v-show="visibleRobots[row[0]]!==false"><circle :cx="frameXY(row)[0]" :cy="frameXY(row)[1]" r=".19" :fill="colors[row[0]%colors.length]" stroke="white" stroke-width=".04"/><text :x="frameXY(row)[0]+.25" :y="frameXY(row)[1]" font-size=".32" fill="white">{{gameData.robots[row[0]].robot_type}}</text></g></svg><div class="legend"><label v-for="(r,i) in gameData.robots" :key="i"><input type="checkbox" v-model="visibleRobots[i]"><i :style="{background:colors[i%colors.length]}"></i>{{r.side}}{{r.robot_type}} · {{r.team}}</label></div><div class="events"><button v-for="(e,i) in shownEvents.slice(-30)" :key="i" @click="time=e.second"><b>{{fmtSecond(e.second)}} {{e.type}}</b><span>{{e.team||e.detail||''}} · {{e.confidence}}</span></button></div></section>
    <section class="panel"><h2>黄牌 / 红牌推断</h2><p class="method">源数据只有“判罚扣血”，没有牌色字段。以下按同步扣血比例标注高/中置信黄牌、推定红牌或牌色未知，不强行归类。</p><div class="penalty-table"><div v-for="p in selected.penalty_incidents" :key="`${p.game_id}-${p.second}`"><b>局 {{p.game_id}} · {{fmtSecond(p.second)}} · {{p.incident_type}}</b><span>{{p.offender_type||'对象未知'}} · 扣血 {{p.penalty_damage}} · {{p.confidence}}置信<span v-if="p.inferred_red"> · 推定红牌</span></span></div><p v-if="!selected.penalty_incidents.length">该队样本中无可识别判罚事件。</p></div></section>
    <section class="panel"><h2>稳定战术与全队克制方案</h2><div class="patterns"><div v-for="p in selected.patterns" :key="p.pattern_id" :class="['pattern',p.classification]"><b>{{p.label}}</b><span>{{p.classification}} · {{(p.rate*100).toFixed(0)}}%</span><small>{{p.games_observed}} 局 / {{p.opponents}} 个对手</small></div></div><div class="counter" v-for="item in selected.counter_plan" :key="item.signal"><b>{{item.signal}}</b><p>{{item.action}}</p><small>退出：{{item.exit}}</small></div></section>
    <section class="panel compare"><div class="section-head"><h2>双队同口径对比与胜率判定</h2><span>区域赛样本模型，不代表确定赛果</span></div><select v-model="compareSlug"><option value="">选择另一支队伍</option><option v-for="t in index.teams.filter(t=>t.team!==selected.team)" :value="t.slug">{{t.team}}</option></select><template v-if="compareTeam && matchup"><div class="prediction"><div><span>{{selected.team}} 模型胜率</span><strong>{{matchup.primaryPct}}%</strong><small>估计区间 {{matchup.interval[0]}}%–{{matchup.interval[1]}}%</small></div><div class="verdict"><span>对局判定</span><strong>{{matchup.verdict}}</strong><small>置信度：{{matchup.confidence}} · 综合强度 {{matchup.primaryStrength}} : {{matchup.opponentStrength}}</small></div><div><span>{{compareTeam.team}} 模型胜率</span><strong>{{matchup.opponentPct}}%</strong><small v-if="matchup.h2hGames">历史交手 {{matchup.h2hGames}} 局：{{matchup.h2hWins}}胜{{matchup.h2hLosses}}负（仅作背景）</small><small v-else>数据库中无直接交手</small></div></div><div class="comparison-table"><div class="comparison-row comparison-head"><b>同口径指标</b><b>{{selected.team}}</b><b>{{compareTeam.team}}</b><b>相对优势</b></div><div v-for="row in comparisonRows" :key="row.label" class="comparison-row"><span>{{row.label}}</span><strong>{{row.first}}</strong><strong>{{row.second}}</strong><em>{{row.leader}}</em></div></div><p class="method">模型综合强度由统一尺度的六维战术评分 90%、正则化 Bradley–Terry 赛程校正赛果 10% 构成。透明对手分先剔除双方直接交手，再按一阶对手胜率 75% 与二阶对手胜率 25% 计算，用于解释赛程；它不再叠加进综合强度，因为滚动回测显示这会重复计算赛程并降低准确率。直接交手记录也只作背景。数据覆盖单独形成置信度，不参与得分。</p></template></section>
  </main><main v-else><p>{{error||'正在加载…'}}</p></main>
</div>
</template>
