<script setup>
import { nextTick, ref, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '数据口径' },
  sections: { type: Array, default: () => [] },
})
const emit = defineEmits(['close'])
const closeButton = ref(null)
const drawer = ref(null)

watch(() => props.open, async open => {
  if (open) {
    await nextTick()
    closeButton.value?.focus()
  }
})

function trapFocus(event) {
  const focusable = [...(drawer.value?.querySelectorAll('button,a,input,select,textarea,[tabindex]:not([tabindex="-1"])') || [])].filter(node => !node.disabled)
  if (!focusable.length) return
  const first = focusable[0], last = focusable.at(-1)
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="methodology-layer" @keydown.esc="emit('close')">
      <button class="methodology-backdrop" aria-label="关闭数据口径" @click="emit('close')"></button>
      <aside ref="drawer" class="methodology-drawer" role="dialog" aria-modal="true" aria-labelledby="methodology-title" @keydown.tab="trapFocus">
        <header><div><span>METHOD</span><h2 id="methodology-title">{{title}}</h2></div><button ref="closeButton" @click="emit('close')">关闭</button></header>
        <section v-for="section in sections" :key="section.title">
          <h3>{{section.title}}</h3>
          <p v-for="item in section.items" :key="item">{{item}}</p>
        </section>
      </aside>
    </div>
  </Teleport>
</template>
