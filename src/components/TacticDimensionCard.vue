<script setup>
defineProps({
  card: { type: Object, required: true },
  expanded: { type: Boolean, default: false },
})
defineEmits(['toggle'])
</script>

<template>
  <article class="insight-card tactic-dimension-card" :data-dimension="card.id">
    <header class="tactic-card-head">
      <div><span>{{card.label}}</span><strong>{{card.score}}</strong></div>
      <div class="tactic-badges"><span>{{card.rank}}</span><span>证据 {{card.confidence}}</span></div>
    </header>
    <div class="fact-grid tactic-primary-facts">
      <span v-for="item in card.primaryFacts" :key="item.label">
        {{item.label}}<strong>{{item.value}}</strong><em v-if="item.meta">{{item.meta}}</em>
      </span>
    </div>
    <button class="tactic-details-toggle" :aria-expanded="expanded" @click="$emit('toggle')">
      {{expanded ? '收起详情' : '展开详情'}}
    </button>
    <div v-if="expanded" class="tactic-expanded">
      <section>
        <b>评分构成</b>
        <div class="metric-pairs score-components">
          <span v-for="item in card.components" :key="item.label">
            {{item.label}} · {{item.weight}}<strong>{{item.value}}</strong>
          </span>
        </div>
      </section>
      <section v-if="card.secondaryFacts.length">
        <b>更多实值</b>
        <div class="fact-grid">
          <span v-for="item in card.secondaryFacts" :key="item.label">
            {{item.label}}<strong>{{item.value}}</strong><em v-if="item.meta">{{item.meta}}</em>
          </span>
        </div>
      </section>
      <small>{{card.sample}}</small>
    </div>
  </article>
</template>
