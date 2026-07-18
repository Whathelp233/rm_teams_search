<script setup>
defineProps({ plan: { type: Object, required: true }, index: { type: Number, required: true } })
defineEmits(['evidence'])
</script>

<template>
  <article class="counter-plan-card">
    <header>
      <span>优先级 {{index + 1}} · {{plan.priority}}</span>
      <b>{{plan.title}}</b>
      <em>置信 {{plan.confidence}}</em>
    </header>
    <div class="counter-threat">
      <span>目标威胁<strong>{{plan.threat.label}}</strong></span>
      <span>发生率<strong>{{plan.threat.ratePct}}% · {{plan.threat.observed}}/{{plan.threat.eligible}} 局</strong></span>
      <span>典型触发<strong>{{plan.threat.timing}} · {{plan.threat.timingRange}}</strong></span>
      <span>执行兵种<strong>{{plan.roles.join(' / ')}}</strong></span>
      <span>执行区域<strong>{{plan.zone}}</strong></span>
      <span>我方能力匹配<strong>{{plan.matchup.executorCapability}} / 100</strong></span>
    </div>
    <ol class="counter-actions"><li v-for="action in plan.actions" :key="action">{{action}}</li></ol>
    <div class="counter-contract">
      <span><b>成功</b>{{plan.success}}</span>
      <span><b>退出</b>{{plan.exit}}</span>
      <span><b>回退</b>{{plan.fallback}}</span>
      <span><b>风险</b>{{plan.risk}}</span>
    </div>
    <details v-if="plan.evidence.length" class="counter-evidence"><summary>查看 {{plan.evidence.length}} 局威胁证据 · {{plan.matchup.response}}</summary><button v-for="game in plan.evidence" :key="game.game_id" @click="$emit('evidence',game.game_id)">{{game.won?'胜':'负'}} · {{game.opponent}} · {{game.side}}方</button></details>
  </article>
</template>

