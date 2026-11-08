<template>
  <!-- 复刻 Python 版指数估值详情图：上下两个面板分别画 PE / PB，
       30%/50%/70% 分位虚线按全历史计算，悬停显示当期数值及其分位。 -->
  <div ref="el" class="vchart-wrap">
    <svg ref="svgEl" :width="W" :height="H" :viewBox="`0 0 ${W} ${H}`" role="img" aria-label="估值走势"
         @pointerdown="onDown" @pointerup="onUp" @pointercancel="onUp"
         @pointermove="onMove" @pointerleave="onLeave" @dblclick="onDbl">
      <g v-for="p in panes" :key="p.key">
        <text :x="L" :y="p.top - 8" font-size="12" :fill="CHART.axisText">{{ p.lab }}</text>
        <template v-if="p.empty">
          <text :x="L + PW / 2" :y="p.top + PH / 2" text-anchor="middle" font-size="12" :fill="CHART.axisMuted">无{{ p.lab }}数据</text>
        </template>
        <template v-else>
          <line v-for="(gy, j) in p.grid" :key="'g' + j" :x1="L" :y1="gy" :x2="W - R" :y2="gy" :stroke="CHART.grid" />
          <line v-for="(b, j) in p.bandLines" :key="'b' + j" :x1="L" :y1="b.y" :x2="W - R" :y2="b.y"
                :stroke="b.color" stroke-dasharray="4 4" opacity=".7" />
          <text v-for="(t, j) in p.bandTags" :key="'bt' + j" :x="W - R + 8" :y="t.y" font-size="10" :fill="t.color">{{ t.text }}</text>
          <polyline :points="p.points" fill="none" :stroke="CHART.line" :stroke-width="CHART.lineWidth"
                    stroke-linejoin="round" stroke-linecap="round" />
          <!-- 每个真实数据点都画圆点，半径随步长自适应，与 iframe 图同规则（原来只画末点 r=4 带白描边） -->
          <circle v-for="(d, j) in p.dots" :key="'d' + j" :cx="d.x" :cy="d.y" :r="dotR" :fill="CHART.line" />
          <text v-for="(t, j) in p.yTicks" :key="'y' + j" :x="L - 8" :y="t.y" text-anchor="end" font-size="10" :fill="CHART.axisText">{{ t.label }}</text>
        </template>
      </g>
      <text v-for="(t, j) in xTicks" :key="'x' + j" :x="t.x" :y="H - 8" :text-anchor="t.anchor" font-size="10" :fill="CHART.axisText">{{ t.label }}</text>
      <line v-if="hover" :x1="hover.x" :y1="T" :x2="hover.x" :y2="H - B" :stroke="CHART.axisMuted" stroke-dasharray="4 4" />
    </svg>
    <div v-if="tip" class="vtip" :style="tipStyle">
      <b>{{ tip.date }}</b>
      <div v-if="tip.pe" class="tip-row"><span class="tip-label">PE</span><span v-html="tip.pe" /></div>
      <div v-if="tip.pb" class="tip-row"><span class="tip-label">PB</span><span v-html="tip.pb" /></div>
    </div>
    <ChartState :note="view ? '自选区间 · 双击复位' : ''" :range="visRange" />
  </div>
</template>
<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import ChartState from './ChartState.vue'
import { rangeText } from '../utils/chartAxis'
import { CHART, dotRadius } from '../utils/chartTheme'
import { rangeStartIndex } from '../utils/series'
const props = defineProps({ hist: Object, range: { type: String, default: '全部' } })
const el = ref(null), svgEl = ref(null), W = ref(720), hover = ref(null)
const L = 56, R = 84, T = 26, B = 30, GAP = 34
const H = computed(() => W.value < 500 ? 320 : 380)
const PW = computed(() => W.value - L - R)
const PH = computed(() => (H.value - T - B - GAP) / 2)
const ok = v => v !== null && v !== undefined && Number.isFinite(v)
const dates = computed(() => (props.hist?.dates || []).map(s => String(s).replace(/-/g, '/')))

// 视窗：默认由父页面区间按钮决定；手动左右拖动 / 水平滚轮 / Ctrl 缩放后进入自定视窗，双击复位。
// 与 iframe 图表、ECharts 曲线同一套时间轴交互规则（CLAUDE.md「时间轴平移交互规范」）。
const view = ref(null)
// 区间起点与走势图同一套口径（series.rangeStartIndex，8 个区间同一份定义）；
// 分位线仍按全历史算
const baseGeo = computed(() => {
  const n = dates.value.length
  const i0 = n ? rangeStartIndex(dates.value.map(s => s.replace(/\//g, '-')), props.range) : 0
  return { i0, n: Math.max(1, n - i0) }
})
const geo = computed(() => view.value || baseGeo.value)
watch(() => props.range, () => { view.value = null })
const setView = (i0, n) => {
  const total = dates.value.length
  const nn = Math.max(2, Math.min(total, n))
  view.value = { i0: Math.max(0, Math.min(total - nn, Math.round(i0))), n: nn }
}
const pan = d => setView(geo.value.i0 + d, geo.value.n)
const zoom = f => {
  const g = geo.value, nn = Math.round(g.n * f)
  setView(g.i0 + g.n / 2 - nn / 2, nn)
}
const x = i => L + (i - geo.value.i0 + .5) * PW.value / (geo.value.n || 1)
const q = (arr, p) => {
  const v = arr.filter(ok).slice().sort((a, b) => a - b)
  if (!v.length) return null
  const k = (v.length - 1) * p, f = Math.floor(k)
  return v[f] + (v[Math.min(f + 1, v.length - 1)] - v[f]) * (k - f)
}
const pctAt = (arr, v) => { const a = arr.filter(ok); return a.length ? a.filter(t => t < v).length / a.length * 100 : null }

const panes = computed(() => {
  if (!props.hist) return []
  const { i0, n } = geo.value
  const iEnd = Math.min(dates.value.length, i0 + n)   // 缩放后只画视窗内的点，不越界画到图外
  return ['pe', 'pb'].map((k, ix) => {
    const lab = k.toUpperCase(), top = T + ix * (PH.value + GAP), arr = props.hist[k] || []
    const vis = arr.slice(i0, iEnd).filter(ok)
    if (!vis.length) return { key: k, lab, top, empty: true }
    const bands = [.3, .5, .7].map(p => q(arr, p)).filter(ok)
    let lo = Math.min(...vis, ...bands), hi = Math.max(...vis, ...bands)
    const pad = (hi - lo) * .1 || hi * .05 || 1
    lo -= pad; hi += pad
    const y = v => top + (hi - v) * PH.value / (hi - lo)
    const grid = [], yTicks = []
    for (let j = 0; j <= 3; j++) {
      const v = lo + (hi - lo) * j / 3
      grid.push(y(v)); yTicks.push({ y: y(v) + 4, label: v.toFixed(k === 'pb' ? 2 : 1) })
    }
    const BC = [CHART.down, CHART.axisMuted, CHART.up], BL = ['30%', '50%', '70%']
    const ys = bands.map(b => y(b))
    const tags = [2, 1, 0].map(j => ({ j, y: ys[j] }))
    for (let t = 1; t < tags.length; t++) tags[t].y = Math.max(tags[t].y, tags[t - 1].y + 13)
    for (let t = tags.length - 2; t >= 0; t--) tags[t].y = Math.min(tags[t].y, tags[t + 1].y - 13)
    const bandLines = bands.map((b, j) => ({ y: ys[j], color: BC[j] }))
    const bandTags = tags.map(({ j, y: ly }) => ({ y: ly + 3.5, color: BC[j], text: `${BL[j]} ${bands[j].toFixed(k === 'pb' ? 2 : 1)}` }))
    const pts = [], dots = []
    for (let i = i0; i < iEnd; i++) {
      if (!ok(arr[i])) continue
      const px = x(i), py = y(arr[i])
      pts.push(`${px},${py}`)
      dots.push({ x: px.toFixed(1), y: py.toFixed(1) })
    }
    return { key: k, lab, top, empty: false, grid, yTicks, bandLines, bandTags, points: pts.join(' '), dots }
  })
})

// 数据点圆点半径：与 iframe / ECharts 图同规则
const dotR = computed(() => dotRadius(PW.value, geo.value.n).toFixed(1))

// 可见区间文本：与 iframe / ECharts 图的状态行同口径
const visRange = computed(() => {
  const d = dates.value, { i0, n } = geo.value
  if (!d.length) return ''
  return rangeText(d[i0], d[Math.min(d.length - 1, i0 + n - 1)])
})

const xTicks = computed(() => {
  const d = dates.value, { i0, n } = geo.value
  if (!d.length) return []
  const slots = Math.max(2, Math.floor(PW.value / 96)), xs = []
  for (let t = 0; t <= slots; t++) xs.push(Math.round(i0 + (n - 1) * t / slots))
  return [...new Set(xs)].map((i, t, arr) => ({
    x: t === 0 ? L : (t === arr.length - 1 ? W.value - R : x(i)),
    label: d[i], anchor: t === 0 ? 'start' : (t === arr.length - 1 ? 'end' : 'middle'),
  }))
})

let drag = null
function onDown(e) {
  if (e.button !== 0) return
  drag = { x: e.clientX, i0: geo.value.i0, n: geo.value.n, step: PW.value / (geo.value.n || 1) }
  svgEl.value?.setPointerCapture?.(e.pointerId)
}
function onUp(e) {
  if (!drag) return
  if (svgEl.value?.hasPointerCapture?.(e.pointerId)) svgEl.value.releasePointerCapture(e.pointerId)
  drag = null
}
function onMove(e) {
  const svg = svgEl.value
  if (!svg || !dates.value.length) return
  if (drag) {
    const shift = Math.round(-(e.clientX - drag.x) / (drag.step || 1))
    setView(drag.i0 + shift, drag.n)
    return
  }
  const bx = svg.getBoundingClientRect(), px = (e.clientX - bx.left) * W.value / (bx.width || W.value)
  if (px < L || px > W.value - R) { onLeave(); return }
  const { i0, n } = geo.value
  const i = Math.min(dates.value.length - 1, Math.max(i0, Math.floor(i0 + (px - L) * n / (PW.value || 1))))
  hover.value = { i, x: x(i) }
}
const onLeave = () => { hover.value = null; drag = null }
function onWheel(e) {
  const dx = e.deltaX || 0, dy = e.deltaY || 0
  if (e.ctrlKey || e.metaKey) {
    e.preventDefault()
    zoom(dy > 0 ? 1.15 : 0.87)
    return
  }
  // 上下滑动页面不平移时间轴，也不 preventDefault（页面正常滚动）
  if (Math.abs(dx) <= Math.abs(dy) || Math.abs(dx) < 1) return
  e.preventDefault()
  pan(Math.sign(dx) * Math.max(1, Math.round(geo.value.n * 0.05)))
}
const onDbl = () => { view.value = null }
const tip = computed(() => {
  if (!hover.value || !props.hist) return null
  const i = hover.value.i
  const row = (k, dec) => ok(props.hist[k]?.[i])
    ? `<b>${props.hist[k][i].toFixed(dec)}（${pctAt(props.hist[k], props.hist[k][i]).toFixed(0)}%分位）</b>` : ''
  return { date: dates.value[i], pe: row('pe', 2), pb: row('pb', 2) }
})
const tipStyle = computed(() => {
  const svg = svgEl.value, box = el.value
  if (!hover.value || !svg || !box) return {}
  const bx = svg.getBoundingClientRect(), wb = box.getBoundingClientRect()
  const sx = bx.left - wb.left + hover.value.x * bx.width / W.value
  const tw = 190
  return { left: Math.min(Math.max(4, sx + 12), Math.max(4, wb.width - tw - 4)) + 'px' }
})

let ro = null
onMounted(() => {
  const measure = () => {
    const w = Math.round(el.value?.getBoundingClientRect().width || 0)
    if (w > 0 && Math.abs(w - W.value) > 1) W.value = Math.max(320, w)
  }
  measure()
  ro = new ResizeObserver(measure)
  ro.observe(el.value)
  svgEl.value?.addEventListener('wheel', onWheel, { passive: false })
})
onBeforeUnmount(() => {
  ro && ro.disconnect()
  svgEl.value?.removeEventListener('wheel', onWheel)
})
</script>
<style scoped>
.vchart-wrap{ position:relative; width:100%; }
/* 只作用于主图 svg：状态行里的日历图标也是 svg，用直接子选择器把它排除掉 */
.vchart-wrap > svg{ display:block; max-width:100%; touch-action:pan-y; }
.vtip{ position:absolute; top:10px; width:190px; box-sizing:border-box; pointer-events:none; background:#fff; color:#0F172A;
  border:1px solid #E2E8F0; font-size:12px; line-height:1.8; padding:8px 12px; border-radius:8px;
  box-shadow:0 4px 16px rgba(15,23,42,.16); font-variant-numeric:tabular-nums; z-index:5; }
.tip-row{ display:flex; justify-content:space-between; gap:12px; }
.tip-label{ color:#475569; }
</style>
