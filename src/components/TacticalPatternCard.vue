<script setup>
import { tacticClock } from '../tactics.js'

defineProps({ pattern: { type: Object, required: true }, expanded: { type: Boolean, default: false } })
defineEmits(['toggle', 'evidence'])
const pct = value => value == null ? '—' : `${(Number(value) * 100).toFixed(1)}%`
</script>

<template>
  <article class="tactical-pattern" :data-confidence="pattern.confidence">
    <button class="pattern-summary" :aria-expanded="expanded" @click="$emit('toggle')">
      <span><b>{{pattern.label}}</b><em>{{pattern.classification}} · 数据把握{{pattern.confidence}}</em></span>
      <strong>{{pct(pattern.rate)}}</strong>
      <small>{{pattern.observed}}/{{pattern.eligible}} 局采用 · 覆盖{{pattern.opponents}}个对手</small>
      <i>{{expanded ? '收起' : '展开打法'}}</i>
    </button>
    <div class="pattern-facts">
      <span>通常形成于<strong>{{tacticClock(pattern.timing.median)}}</strong></span>
      <span>常见比赛窗口<strong>{{tacticClock(pattern.timing.p25)}}–{{tacticClock(pattern.timing.p75)}}</strong></span>
      <span>执行兵种<strong>{{pattern.roles.join(' / ') || '全队协同'}}</strong></span>
      <span>争夺位置<strong>{{pattern.zones.join(' / ') || '全场目标'}}</strong></span>
    </div>
    <div v-if="expanded" class="pattern-expanded">
      <b class="chain-title">场上执行顺序</b>
      <ol class="chain-steps"><li v-for="step in pattern.steps" :key="step">{{step}}</li></ol>
      <div class="pattern-splits">
        <span>作为红方采用<strong>{{pattern.side_split['红'].observed}}/{{pattern.side_split['红'].eligible}}局 · {{pct(pattern.side_split['红'].rate)}}</strong></span>
        <span>作为蓝方采用<strong>{{pattern.side_split['蓝'].observed}}/{{pattern.side_split['蓝'].eligible}}局 · {{pct(pattern.side_split['蓝'].rate)}}</strong></span>
        <span>采用该打法的历史胜率<strong>{{pattern.association.with_win_pct==null?'—':pattern.association.with_win_pct+'%'}}</strong></span>
        <span>相对未采用局胜率差<strong>{{pattern.association.win_delta_pp==null?'—':(pattern.association.win_delta_pp>0?'+':'')+pattern.association.win_delta_pp+'pp'}}</strong></span>
        <span>前哨站伤害中位数<strong>{{pattern.association.median_outpost_damage??'—'}}</strong></span>
        <span>基地伤害中位数<strong>{{pattern.association.median_base_damage??'—'}}</strong></span>
      </div>
      <div v-if="pattern.evidence.length" class="pattern-evidence">
        <b>出现该打法的对局</b>
        <button v-for="game in pattern.evidence" :key="game.game_id" @click="$emit('evidence',game.game_id)">
          <span>{{game.won?'胜':'负'}} · {{game.opponent}}</span><small>{{game.side}}方 · {{tacticClock(game.timing)}}</small>
        </button>
      </div>
      <small class="association-note">历史胜率用于判断打法结果，不等同于该打法单独决定胜负。</small>
    </div>
  </article>
</template>
