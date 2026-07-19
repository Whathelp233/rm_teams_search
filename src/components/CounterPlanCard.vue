<script setup>
defineProps({ plan: { type: Object, required: true }, index: { type: Number, required: true } })
defineEmits(['evidence'])
</script>

<template>
  <article class="counter-plan-card">
    <header>
      <span>赛前处理顺位 {{index + 1}} · {{plan.priority}}</span>
      <b>{{plan.title}}</b>
      <em>数据把握 {{plan.confidence}}</em>
    </header>
    <div class="counter-threat">
      <span>对方常用打法<strong>{{plan.threat.label}}</strong></span>
      <span>历史采用频率<strong>{{plan.threat.ratePct}}% · {{plan.threat.observed}}/{{plan.threat.eligible}}局</strong></span>
      <span>通常出现时间<strong>{{plan.threat.timing}} · 常见{{plan.threat.timingRange}}</strong></span>
      <span>我方执行兵种<strong>{{plan.roles.join(' / ')}}</strong></span>
      <span>我方任务位置<strong>{{plan.zone}}</strong></span>
      <span>当前阵容执行能力<strong>{{plan.matchup.executorCapability}} / 100</strong></span>
    </div>
    <b class="counter-order-title">临场指令</b>
    <ol class="counter-actions"><li v-for="action in plan.actions" :key="action">{{action}}</li></ol>
    <div class="counter-contract">
      <span><b>达成标志</b>{{plan.success}}</span>
      <span><b>停止条件</b>{{plan.exit}}</span>
      <span><b>未奏效时</b>{{plan.fallback}}</span>
      <span><b>主要风险</b>{{plan.risk}}</span>
    </div>
    <details v-if="plan.evidence.length" class="counter-evidence"><summary>查看对方采用该打法的{{plan.evidence.length}}局 · {{plan.matchup.response}}</summary><button v-for="game in plan.evidence" :key="game.game_id" @click="$emit('evidence',game.game_id)">{{game.won?'胜':'负'}} · {{game.opponent}} · {{game.side}}方</button></details>
  </article>
</template>
