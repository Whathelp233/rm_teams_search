<script setup>
import { tacticClock } from '../tactics.js'

defineProps({ pattern: { type: Object, required: true }, expanded: { type: Boolean, default: false } })
defineEmits(['toggle', 'evidence'])
const pct = value => value == null ? '—' : `${(Number(value) * 100).toFixed(1)}%`
</script>

<template>
  <article class="tactical-pattern" :data-confidence="pattern.confidence">
    <button class="pattern-summary" :aria-expanded="expanded" @click="$emit('toggle')">
      <span><b>{{pattern.label}}</b><em>{{pattern.classification}} · 证据{{pattern.confidence}}</em></span>
      <strong>{{pct(pattern.rate)}}</strong>
      <small>{{pattern.observed}}/{{pattern.eligible}} 局 · {{pattern.opponents}} 个对手</small>
      <i>{{expanded ? '收起' : '详情'}}</i>
    </button>
    <div class="pattern-facts">
      <span>中位触发<strong>{{tacticClock(pattern.timing.median)}}</strong></span>
      <span>时间区间<strong>{{tacticClock(pattern.timing.p25)}}–{{tacticClock(pattern.timing.p75)}}</strong></span>
      <span>主要兵种<strong>{{pattern.roles.join(' / ') || '队伍级'}}</strong></span>
      <span>主要区域<strong>{{pattern.zones.join(' / ') || '全场事件'}}</strong></span>
    </div>
    <div v-if="expanded" class="pattern-expanded">
      <ol class="chain-steps"><li v-for="step in pattern.steps" :key="step">{{step}}</li></ol>
      <div class="pattern-splits">
        <span>红方<strong>{{pattern.side_split['红'].observed}}/{{pattern.side_split['红'].eligible}} · {{pct(pattern.side_split['红'].rate)}}</strong></span>
        <span>蓝方<strong>{{pattern.side_split['蓝'].observed}}/{{pattern.side_split['蓝'].eligible}} · {{pct(pattern.side_split['蓝'].rate)}}</strong></span>
        <span>出现时胜率<strong>{{pattern.association.with_win_pct==null?'—':pattern.association.with_win_pct+'%'}}</strong></span>
        <span>胜率关联差<strong>{{pattern.association.win_delta_pp==null?'—':(pattern.association.win_delta_pp>0?'+':'')+pattern.association.win_delta_pp+'pp'}}</strong></span>
        <span>前哨伤害中位<strong>{{pattern.association.median_outpost_damage??'—'}}</strong></span>
        <span>基地伤害中位<strong>{{pattern.association.median_base_damage??'—'}}</strong></span>
      </div>
      <div v-if="pattern.evidence.length" class="pattern-evidence">
        <b>证据局</b>
        <button v-for="game in pattern.evidence" :key="game.game_id" @click="$emit('evidence',game.game_id)">
          <span>{{game.won?'胜':'负'}} · {{game.opponent}}</span><small>{{game.side}}方 · {{tacticClock(game.timing)}}</small>
        </button>
      </div>
      <small class="association-note">胜率与伤害为历史关联，不表示该动作链产生因果增益。</small>
    </div>
  </article>
</template>

