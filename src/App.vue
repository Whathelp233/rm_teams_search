<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { init, use } from 'echarts/core'
import { BarChart, RadarChart } from 'echarts/charts'
import { GridComponent, RadarComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([BarChart, RadarChart, GridComponent, RadarComponent, TooltipComponent, CanvasRenderer])

const index = ref({ teams: [] })
const query = ref('')
const region = ref('全部')
const selected = ref(null)
const compareSlug = ref('')
const compareTeam = ref(null)
const activeGame = ref(null)
const routes = ref(null)
const error = ref('')
let scoreChart
let damageChart
const base = import.meta.env.BASE_URL

const teams = computed(() => index.value.teams.filter(t =>
  (region.value === '全部' || t.region === region.value) &&
  (!query.value || t.team.includes(query.value))
))
const teamBySlug = computed(() => Object.fromEntries(index.value.teams.map(t => [t.slug, t])))
const headToHead = computed(() => compareTeam.value ? selected.value.matches.filter(m => m.opponent === compareTeam.value.team) : [])

async function loadTeam(slug) {
  error.value = ''
  const response = await fetch(`${base}data/teams/${slug}.json`)
  if (!response.ok) throw new Error(`队伍数据加载失败: ${response.status}`)
  selected.value = await response.json()
  activeGame.value = null
  routes.value = null
  await nextTick()
  renderCharts()
}

async function loadCompare() {
  if (!compareSlug.value) { compareTeam.value = null; return }
  compareTeam.value = await (await fetch(`${base}data/teams/${compareSlug.value}.json`)).json()
}

async function loadRoutes(game) {
  activeGame.value = game
  const slug = index.value.teams.find(t => t.team === selected.value.team)?.slug
  const response = await fetch(`${base}data/routes/${slug}/${game.game_id}.json`)
  if (!response.ok) throw new Error(`路线数据加载失败: ${response.status}`)
  routes.value = await response.json()
}

function renderCharts() {
  if (!selected.value) return
  scoreChart?.dispose(); damageChart?.dispose()
  scoreChart = init(document.getElementById('score-chart'))
  const labels = ['火力', '目标', '空间', '防守', '资源', '适应']
  const keys = ['firepower', 'objective', 'spatial', 'defense', 'resource', 'adaptability']
  scoreChart.setOption({
    radar: { indicator: labels.map(name => ({ name, max: 100 })), splitArea: { areaStyle: { color: ['#13233a', '#0e1a2d'] } } },
    series: [{ type: 'radar', data: [{ value: keys.map(k => selected.value.scores[k]), name: selected.value.team }], areaStyle: { color: '#22d3ee66' }, lineStyle: { color: '#22d3ee' } }],
    textStyle: { color: '#cbd5e1' }
  })
  damageChart = init(document.getElementById('damage-chart'))
  const damage = selected.value.damage_breakdown.slice(0, 12)
  damageChart.setOption({
    grid: { left: 120, right: 25, top: 20, bottom: 30 },
    xAxis: { type: 'value', axisLabel: { color: '#94a3b8' } },
    yAxis: { type: 'category', data: damage.map(d => `${d.target_type}·${d.source_type}`).reverse(), axisLabel: { color: '#cbd5e1' } },
    series: [{ type: 'bar', data: damage.map(d => d.damage).reverse(), itemStyle: { color: '#f59e0b' } }],
    tooltip: { trigger: 'axis' }
  })
}

function routePoints(points) {
  return points.map(p => `${(p[1] / 28 * 100).toFixed(2)},${(100 - p[2] / 15 * 100).toFixed(2)}`).join(' ')
}

const routeColors = ['#22d3ee','#f59e0b','#a78bfa','#34d399','#fb7185','#60a5fa','#f97316']

onMounted(async () => {
  try {
    index.value = await (await fetch(`${base}data/index.json`)).json()
    const pilot = index.value.teams.find(t => t.team === '华南农业大学') || index.value.teams[0]
    if (pilot) await loadTeam(pilot.slug)
  } catch (e) { error.value = e.message }
})

watch(compareSlug, loadCompare)
</script>

<template>
  <div class="shell">
    <aside>
      <div class="brand"><span>RMUC 2026</span><strong>战术情报库</strong></div>
      <input v-model="query" placeholder="搜索队伍" />
      <select v-model="region"><option>全部</option><option>南部赛区</option><option>东部赛区</option><option>北部赛区</option></select>
      <div class="team-list">
        <button v-for="team in teams" :key="team.slug" :class="{active:selected?.team===team.team}" @click="loadTeam(team.slug)">
          <span>{{ team.team }}</span><small>{{ team.wins }}/{{ team.games }} · {{ team.region }}</small>
        </button>
      </div>
    </aside>
    <main v-if="selected">
      <div class="notice">空间统计仅采用通信协议官方坐标和规则手册 28×15m 场地；内部行为树地图与 SCAU 叠加图已排除。</div>
      <header>
        <div><p>{{ selected.summary.region }} <em v-if="selected.champion">{{ selected.champion }}</em></p><h1>{{ selected.team }}</h1></div>
        <div class="record"><strong>{{ selected.summary.wins }}–{{ selected.summary.games-selected.summary.wins }}</strong><span>胜率 {{ selected.summary.win_rate.toFixed(1) }}%</span></div>
      </header>
      <section class="kpis">
        <article><span>场均输出</span><strong>{{ selected.summary.avg_damage_dealt?.toFixed(0) }}</strong></article>
        <article><span>场均基地伤害</span><strong>{{ selected.summary.avg_base_damage?.toFixed(0) }}</strong></article>
        <article><span>场均前哨伤害</span><strong>{{ selected.summary.avg_outpost_damage?.toFixed(0) }}</strong></article>
        <article><span>检测命中/发弹</span><strong>{{ ((selected.summary.shot_accuracy||0)*100).toFixed(1) }}%</strong></article>
      </section>
      <section class="grid-two">
        <article class="panel"><h2>分维度评分</h2><div id="score-chart" class="chart"></div></article>
        <article class="panel"><h2>主要伤害来源</h2><div id="damage-chart" class="chart"></div></article>
      </section>
      <section class="panel">
        <h2>稳定战术与观察</h2>
        <div class="patterns"><div v-for="p in selected.patterns" :key="p.pattern_id" :class="['pattern',p.classification]">
          <b>{{ p.label }}</b><span>{{ p.classification }} · {{ (p.rate*100).toFixed(0) }}%</span><small>{{ p.games_observed }} 局 / {{ p.opponents }} 个对手</small>
        </div></div>
      </section>
      <section class="panel">
        <h2>全队克制方案</h2>
        <div class="counter" v-for="item in selected.counter_plan" :key="item.signal"><b>{{ item.signal }}</b><p>{{ item.action }}</p><small>退出：{{ item.exit }}</small></div>
      </section>
      <section class="panel">
        <div class="section-head"><h2>官方坐标热力图</h2><span>红蓝统一为己方视角</span></div>
        <img class="heatmap" :src="`${base}heatmaps/${index.teams.find(t=>t.team===selected.team)?.slug}-heatmap.svg`" />
      </section>
      <section class="panel">
        <div class="section-head"><h2>全部逐局</h2><span>点击查看2秒采样路线</span></div>
        <div class="match-grid"><button v-for="m in selected.matches" :key="m.game_id" @click="loadRoutes(m)">
          <b>{{ m.won ? '胜' : '负' }} · {{ m.opponent }}</b><span>{{ m.rule_version }} · {{ m.side }}方</span><small>输出 {{ m.damage_dealt.toFixed(0) }} / 基地 {{ m.base_damage.toFixed(0) }}</small>
        </button></div>
      </section>
      <section v-if="routes" class="panel">
        <h2>局 {{ activeGame.game_id }} 路线 · {{ activeGame.opponent }}</h2>
        <svg class="route-map" viewBox="0 0 100 100" preserveAspectRatio="none">
          <rect width="100" height="100" fill="#0e1a2d" stroke="#94a3b8" />
          <polyline v-for="(points,key,i) in routes.routes" :key="key" :points="routePoints(points)" fill="none" :stroke="routeColors[i%routeColors.length]" stroke-width="0.45" vector-effect="non-scaling-stroke" />
        </svg>
        <div class="legend"><span v-for="(_,key,i) in routes.routes" :key="key"><i :style="{background:routeColors[i%routeColors.length]}"></i>{{ key }}</span></div>
      </section>
      <section class="panel compare">
        <h2>双队对比</h2>
        <select v-model="compareSlug"><option value="">选择另一支队伍</option><option v-for="t in index.teams.filter(t=>t.team!==selected.team)" :value="t.slug">{{ t.team }}</option></select>
        <p v-if="compareTeam" class="compare-status">{{ headToHead.length ? `数据库中有 ${headToHead.length} 局历史交手` : '数据库中无历史交手：以下仅为模型对比，不代表实战结论' }}</p>
        <div v-if="compareTeam" class="compare-grid"><div><b>{{ selected.team }}</b><span>火力 {{ selected.scores.firepower }}</span><span>目标 {{ selected.scores.objective }}</span><span>防守 {{ selected.scores.defense }}</span></div><div><b>{{ compareTeam.team }}</b><span>火力 {{ compareTeam.scores.firepower }}</span><span>目标 {{ compareTeam.scores.objective }}</span><span>防守 {{ compareTeam.scores.defense }}</span></div></div>
      </section>
    </main>
    <main v-else><p>{{ error || '正在加载…' }}</p></main>
  </div>
</template>
