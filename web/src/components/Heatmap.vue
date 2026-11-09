<template>
  <div class="aw-chart-box">
    <div ref="el" class="aw-chart" :style="{ height: h + 'px' }"></div>
    <div v-if="tip" class="row-tip" :style="{ top: tip.y + 'px' }">{{ tip.text }}</div>
    <ChartState :note="note" :range="span" />
  </div>
</template>
<script setup>
// 单期收益热力图：行 = 策略，列 = 期间，颜色 = 该期涨跌（红涨绿跌）。
// 比 3 组并排柱形好读：一眼看出哪几个月谁在挨打，不需要逐个比高度。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { HeatmapChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, VisualMapComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import ChartState from './ChartState.vue'
import { axisLabel, rangeText } from '../utils/chartAxis'
import { CHART, TIP_BASE, tipRows } from '../utils/chartTheme'
import { attachWheel } from '../utils/chartWheel'

echarts.use([HeatmapChart, GridComponent, TooltipComponent, VisualMapComponent, DataZoomComponent, CanvasRenderer])

const props = defineProps({
  series: Object,                       // { 策略名: { dates:[], labels:[], ret:[] } }
  rowHeight: { type: Number, default: 30 },
})
const el = ref(null)
const span = ref('')
const tip = ref(null)
let chart = null

// 文本量宽（canvas 一次性初始化，避免每帧新建）
let _mctx = null
function textWidth(text, size) {
  if (!_mctx) { try { _mctx = document.createElement('canvas').getContext('2d') } catch { return text.length * size } }
  _mctx.font = `${size}px -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif`
  return _mctx.measureText(text).width
}

const names = computed(() => Object.keys(props.series || {}))
const labels = computed(() => props.series[names.value[0]]?.labels || [])
const dates = computed(() => props.series[names.value[0]]?.dates || [])
const h = computed(() => Math.max(90, names.value.length * props.rowHeight + 52))
const note = ref('')

// 颜色：以绝对值最大值为对称端点，0 落在近白的中点，涨红跌绿（中国习惯）
const maxAbs = computed(() => {
  let m = 0
  for (const n of names.value) for (const v of props.series[n].ret || []) if (v != null) m = Math.max(m, Math.abs(v))
  return m || 1
})

// 目标格子宽度：「09/18」在 9px 下约 22px 宽，两侧各留 6px 才不会和邻格粘成一串
// （26px 时实测标签首尾相接，看起来像「09/1809/21」）。日线近1年 = 243 列，
// 硬塞进 760px 只有 3px/格，肉眼只能看到一条彩色条纹（2026-11-09 验收发现）。
// 这里沿用全站时间轴那套：给全量数据，窗口只决定初始可见列，左右拖动能看到更早的期间。
// 手机窄屏放不下日期标签，格子收到 22px、靠 tooltip 读值。
const win = ref({ start: 0, end: 100 })

function winOf(plotW, n, wide) {
  const cell = wide ? 34 : 22
  const vis = Math.max(6, Math.min(n, Math.floor(plotW / cell)))
  return { vis, start: n > vis ? +((1 - vis / n) * 100).toFixed(2) : 0, more: n > vis }
}

function build() {
  const ns = names.value
  const xs = labels.value
  const cells = []
  for (let y = 0; y < ns.length; y++) {
    const s = props.series[ns[y]]
    const m = new Map(s.dates.map((d, k) => [d, s.ret[k]]))
    for (let x = 0; x < xs.length; x++) {
      const v = m.get(dates.value[x])
      if (v == null) continue
      const dark = Math.abs(v) / maxAbs.value > 0.55
      cells.push({
        value: [x, y, +v.toFixed(2)],
        label: { color: dark ? '#fff' : '#475569' },
      })
    }
  }
  const boxW = el.value?.clientWidth || 320
  const nameW = boxW >= 560 ? 104 : 78
  const plotW = boxW - (nameW + 10) - 30
  const { vis, start, more } = winOf(plotW, xs.length, boxW >= 560)
  // 格子窄到放不下「+1.4」时不要写字，否则文字会压到隔壁格子（手机 14 列时约 14px）
  const cellW = plotW / Math.max(1, vis)
  const labelsOff = vis > 40 || cellW < 26     // 放不下「+1.4」就不写字
  const cellsTight = cellW < 9                 // 格子只剩几像素时连描边也去掉
  // **不抽稀**：可见的每一列都标日期。放不下完整日期时退成「09/30」（年份由下方状态行给），
  // 再放不下就整行不画（此时靠 tooltip 读值）
  const plainFits = vis * 40 <= plotW
  const shortFits = vis * 24 <= plotW
  const shortLabel = v => {
    const t = axisLabel(v)
    return /^\d{4}\//.test(t) ? t.slice(5) : t      // 2026/09/30 → 09/30；「2026年10月」保持原样
  }
  const labelCfg = plainFits
    ? { color: CHART.axisText, fontSize: 9, interval: 0, formatter: axisLabel }
    : shortFits
      ? { color: CHART.axisText, fontSize: 9, interval: 0, formatter: shortLabel }
      : { show: false }
  // 行名：一个名字一行、超宽就省略号（换行会把行高撑开、还占掉格子的宽度）；
  // 完整名字靠悬停提示（见 onMounted 里的 zr mousemove）
  const wrapName = v => String(v)
  const labelY = {
    color: CHART.axisText, fontSize: 11, align: 'left', margin: nameW + 6,
    width: nameW, overflow: 'truncate', formatter: wrapName,
  }
  note.value = more ? `每列 ${vis} 期 · 左右拖动看更早` : ''
  win.value = { start, end: 100 }
  return {
    animation: false,
    grid: { left: nameW + 10, right: 30, top: 6, bottom: 26 },
    tooltip: {
      ...TIP_BASE,
      formatter: p => {
        const xi = p.value[0]
        return tipRows(String(xs[xi] ?? ''), ns.map((n, i) => {
          const s = props.series[n]
          const m = new Map(s.dates.map((d, k) => [d, s.ret[k]]))
          const v = m.get(dates.value[xi])
          return [`${dot(i)}${n}`, v == null ? '—' : `${v > 0 ? '+' : ''}${(+v).toFixed(2)}%`]
        }))
      },
    },
    xAxis: {
      type: 'category', data: xs, splitArea: { show: false }, axisTick: { show: false },
      axisLine: { lineStyle: { color: CHART.axisLine } },
      axisLabel: labelCfg,
    },
    yAxis: {
      type: 'category', data: ns, inverse: true, axisTick: { show: false },
      axisLine: { show: false },
      // align:left 让所有行名从同一 x 起排（默认右对齐会让短名字看起来「前面多空格」）
      axisLabel: labelY,
      splitArea: { show: false },
    },
    visualMap: {
      show: false, min: -maxAbs.value, max: maxAbs.value, calculable: false,
      inRange: { color: ['#16703B', '#F7F9F8', '#C52828'] },   // 跌绿 → 近白 → 涨红
    },
    // 与全站时间轴同一套：只留 inside（禁止 slider 滑块条），拖动平移 + 双击复位由 attachWheel 接管
    dataZoom: [{
      type: 'inside', xAxisIndex: 0, start, end: 100,
      zoomOnMouseWheel: false, moveOnMouseWheel: false, moveOnMouseMove: false,
    }],
    series: [{
      type: 'heatmap', data: cells,
      itemStyle: { borderWidth: cellsTight ? 0 : 1, borderColor: '#fff', borderRadius: cellsTight ? 0 : 3 },
      label: { show: !labelsOff, fontSize: 10, formatter: p => `${p.value[2] > 0 ? '+' : ''}${p.value[2].toFixed(1)}` },
      emphasis: { itemStyle: { borderColor: CHART.axisText, borderWidth: 1 } },
    }],
  }
}
const dot = i => `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;background:${['#1E40AF', '#F59E0B', '#8B5CF6', '#0EA5E9'][i % 4]}"></span>`

// 可见窗口 → 状态行文本：把 dataZoom 百分比换算回真实日期（与 LineChart / iframe 同一口径）
function syncSpan() {
  if (!chart) return
  const d = dates.value
  if (!d.length) { span.value = ''; return }
  const dz = (chart.getOption().dataZoom || [])[0] || {}
  const i = Math.max(0, Math.round((dz.start ?? 0) / 100 * (d.length - 1)))
  const j = Math.min(d.length - 1, Math.round((dz.end ?? 100) / 100 * (d.length - 1)))
  span.value = rangeText(d[i], d[j])
}
// 双击复位：回到当前区间算出来的初始窗口（不是全量 —— 全量是一堵条纹墙）
function reset() { if (chart) chart.dispatchAction({ type: 'dataZoom', ...win.value }) }
const onDbl = () => reset()
// 行名被省略号截断：用容器上的 DOM mousemove 判断指针是否落在最左那条行名带里
// （zr 的 mousemove 在真实鼠标下收不到、axisLabel.triggerEvent 也被 tooltip 吃掉，DOM 事件最稳）
function onHover(e) {
  const names = Object.keys(props.series || {})
  const r = el.value?.getBoundingClientRect()
  if (!r || !names.length) { tip.value = null; return }
  const nameWNow = r.width >= 560 ? 104 : 78
  if (e.clientX - r.left > nameWNow + 4) { tip.value = null; return }
  const gridTop = 6, gridBottom = 26
  const rowH = (r.height - gridTop - gridBottom) / names.length
  const i = Math.floor((e.clientY - r.top - gridTop) / rowH)
  tip.value = names[i] ? { text: names[i], y: Math.max(0, e.clientY - r.top - 13) } : null
}
const onLeave = () => { tip.value = null }

let detachWheel = null
onMounted(() => {
  chart = echarts.init(el.value, null, { renderer: 'canvas' })
  chart.setOption(build(), true)
  el.value.__awChart = chart      // 与 MultiLine 一致，便于调试/自动化断言
  el.value.addEventListener('mousemove', onHover)
  el.value.addEventListener('mouseleave', onLeave)
  el.value.addEventListener('dblclick', onDbl)
  chart.on('dataZoom', syncSpan)
  detachWheel = attachWheel(chart, el.value)
  syncSpan()
  window.addEventListener('resize', resize)
})
function resize() { if (chart) { chart.resize(); chart.setOption(build(), true); syncSpan() } }
watch(() => props.series, () => { if (chart) { chart.setOption(build(), true); syncSpan() } })
onBeforeUnmount(() => {
  el.value?.removeEventListener('mousemove', onHover)
  el.value?.removeEventListener('mouseleave', onLeave)
  el.value?.removeEventListener('dblclick', onDbl)
  detachWheel && detachWheel()
  window.removeEventListener('resize', resize)
  chart && chart.dispose()
})
</script>

<style scoped>
.aw-chart-box{ position:relative; }
.row-tip{ position:absolute; left:2px; padding:2px 7px; border-radius:6px; background:#fff; color:#0F172A;
  font-size:11.5px; white-space:nowrap; border:1px solid #E2E8F0; box-shadow:0 4px 16px rgba(15,23,42,.16);
  pointer-events:none; z-index:5; }
</style>

<style scoped>
.aw-chart-box{ position:relative; }
</style>