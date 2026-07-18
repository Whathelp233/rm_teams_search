<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  cells: { type: Array, default: () => [] },
  image: { type: String, required: true },
  maskOpacity: { type: Number, default: .34 },
  scaleX: { type: Number, default: 1 },
  scaleY: { type: Number, default: 1 },
})

const canvas = ref(null)
let observer, image

function heatColor(side, opacity) {
  if (side === '红') return `rgba(255,59,98,${opacity})`
  if (side === '蓝') return `rgba(0,217,255,${opacity})`
  return `rgba(255,209,102,${opacity})`
}

async function draw() {
  await nextTick()
  const node = canvas.value
  if (!node) return
  const bounds = node.getBoundingClientRect(), ratio = Math.min(2, window.devicePixelRatio || 1)
  const width = Math.max(1, Math.round(bounds.width * ratio)), height = Math.max(1, Math.round(bounds.height * ratio))
  if (node.width !== width || node.height !== height) { node.width = width; node.height = height }
  const context = node.getContext('2d'); context.clearRect(0, 0, width, height)
  if (!image || !image.complete) {
    image = new Image(); image.decoding = 'async'; image.src = props.image
    try { await image.decode() } catch { return }
  }
  context.drawImage(image, 0, 0, width, height)
  for (const cell of props.cells) {
    context.fillStyle = heatColor(cell.side, cell.opacity)
    context.fillRect((cell.x - .25 * props.scaleX) / 28 * width, (cell.y - .25 * props.scaleY) / 15 * height, .5 * props.scaleX / 28 * width + 1, .5 * props.scaleY / 15 * height + 1)
  }
  if (props.maskOpacity > 0) {
    context.globalAlpha = props.maskOpacity; context.globalCompositeOperation = 'multiply'
    context.drawImage(image, 0, 0, width, height)
    context.globalAlpha = 1; context.globalCompositeOperation = 'source-over'
  }
}

watch(() => [props.cells, props.image, props.maskOpacity, props.scaleX, props.scaleY], () => draw(), { deep: true })
onMounted(() => { observer = new ResizeObserver(draw); observer.observe(canvas.value); draw() })
onBeforeUnmount(() => observer?.disconnect())
</script>

<template><canvas ref="canvas" class="field heatmap-canvas" aria-label="队伍秒级热力图"></canvas></template>
