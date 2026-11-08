<template>
  <div class="aw-chart-box">
    <div ref="el" class="aw-chart" :style="{ height: height + 'px' }"></div>
    <!-- 状态行所有曲线都挂（含不可滑动的概览小图）：起止日期本身就是有用信息，
         且全站展示效果必须一致（CLAUDE.md「左右滑动与状态行」） -->
    <ChartState :note="note" :range="visRange" />
  </div>
</template>
<script setup>
// 一条折线（ECharts，按需引入）：坐标轴 + 手指按住看数 + 买卖点 + 拖动平移 / 滚轮缩放 / 双击复位
// labels：月线 / 年线时传中文期间标签（2026年10月 / 2026年），日线时省略
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import ChartState from './ChartState.vue'
import { axisLabel, rangeText, decimalsFor, decimalsOf, pctText } from '../utils/chartAxis'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, MarkPointComponent, MarkLineComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { attachWheel } from '../utils/chartWheel'
import { CHART, TIP_BASE, dotSize } from '../utils/chartTheme'
import { joinGroup, leaveGroup, syncGroup } from '../utils/chartGroup'
echarts.use([LineChart, GridComponent, TooltipComponent, MarkPointComponent, MarkLineComponent, DataZoomComponent, CanvasRenderer])

const props = defineProps({
  dates: Array, values: Array, height: { type: Number, default: 180 },
  unit: { type: String, default: '%' }, dark: Boolean, marks: { type: Array, default: () => [] },
  zero: Boolean, fmtTip: Function,
  labels: { type: Array, default: null },   // 月/年线的显示标签
  zoom: { type: Boolean, default: true },   // 拖动 / 滚轮缩放 / 双击复位
  resetKey: { type: [String, Number], default: 0 },  // 变化即把视窗复位到全区间
  note: { type: String, default: '' },      // 状态行左侧说明
  // 可见窗口 [起, 止]（数据下标）。传了它 = 数据给全历史、由窗口决定看哪段，
  // 于是可以像 iframe 图表那样往左右拖出区间外的历史；不传 = 老行为（整条即全部）。
  window: { type: Array, default: null },
  group: { type: String, default: '' },     // 同一 group 的多张图，平移/缩放联动
})
const el = ref(null)
const visRange = ref('')
let chart = null, detachWheel = null
const axis = () => props.labels?.length ? props.labels : (props.dates || [])
// 窗口下标 → dataZoom 百分比（ECharts 只认百分比）
function winPct() {
  const n = (props.values || []).length
  const w = props.window
  if (!w || n < 2) return { start: 0, end: 100 }
  const i0 = Math.max(0, Math.min(n - 1, Math.round(w[0] ?? 0)))
  const i1 = Math.max(i0, Math.min(n - 1, Math.round(w[1] ?? n - 1)))
  return { start: i0 / (n - 1) * 100, end: i1 / (n - 1) * 100 }
}

// 数据点圆点直径：与 iframe 图同规则，随「可见点数」自适应。
// 存成闭包变量而不是在 symbolSize 回调里现算——回调对每个点都会调一次，不能放 getOption()。
const GRID_L = 44, GRID_R = 34
let curDot = 4
function calcDot() {
  const n = (props.values || []).length
  let span = 1
  // 首次在 setOption 之前就会调用，那时 getOption() 还没有 dataZoom，必须容错
  if (chart && props.zoom) {
    const dz = ((chart.getOption() || {}).dataZoom || [])[0]
    if (dz) span = ((dz.end ?? 100) - (dz.start ?? 0)) / 100
  }
  const visible = Math.max(1, Math.round(n * (span > 0 ? span : 1)))
  curDot = dotSize((el.value?.clientWidth || 320) - GRID_L - GRID_R, visible)
}

// 可见数值的小数位：刻度与默认 tooltip 共用（同 MultiLine，避免一列 0% / ±0.00）
function visValues() {
  const v = (props.values || []).slice()
  const w = props.window
  if (!w || v.length < 2) return v.filter(x => x != null)
  const i0 = Math.max(0, Math.round(w[0] ?? 0)), i1 = Math.min(v.length - 1, Math.round(w[1] ?? v.length - 1))
  return v.slice(i0, i1 + 1).filter(x => x != null)
}
let curDec = 2

function option() {
  const v = props.values || []
  const one = v.length < 2          // 按年/月聚合后可能只剩 1 期：折线画不出来，必须把点画出来
  // 硬约束：主走势折线统一深蓝 CHART.line（#1E40AF，以 Python 版 iframe 图表为准）；
  // 涨红跌绿只用于买卖点标记 / 柱，不再拿整条折线的颜色表达涨跌。
  const col = props.dark ? '#93C5FD' : CHART.line
  const axisCol = props.dark ? 'rgba(255,255,255,.55)' : CHART.axisText
  const gridCol = props.dark ? 'rgba(255,255,255,.12)' : CHART.grid
  const marks = props.marks.map(m => ({
    coord: [m.date, m.value], value: m.side === '买入' ? 'B' : 'S',
    itemStyle: { color: m.side === '买入' ? CHART.up : CHART.down },
  }))
  // 日期统一口径（chartAxis.axisLabel）：日 2026/09/30、月 2026年10月、年 2026年；不砍年份
  return {
    animation: false,
    // right 要给足：横轴用完整日期 2026/09/30（约 58px），居中对齐时最后一格会右溢出，10px 会被裁掉
    grid: { left: 44, right: 34, top: 12, bottom: 24 },
    tooltip: {
      trigger: 'axis', ...TIP_BASE,
      axisPointer: { type: 'line', lineStyle: { color: CHART.axisMuted, type: 'dashed' } },
      formatter: ps => {
        const p = ps[0]
        if (props.fmtTip) return props.fmtTip(p.dataIndex)
        const d = decimalsOf(p.data, curDec)
        return `${p.axisValue}<br/><b>${(+p.data).toFixed(d)}${props.unit}</b>`
      },
    },
    xAxis: {
      type: 'category', data: axis(), boundaryGap: false,
      axisLine: { lineStyle: { color: CHART.axisLine } }, axisTick: { show: false },
      axisLabel: { color: axisCol, fontSize: 10, hideOverlap: true, formatter: axisLabel },
    },
    yAxis: {
      type: 'value', scale: !props.zero && !one, splitNumber: 4,
      axisLabel: { color: axisCol, fontSize: 10,
        formatter: x => props.unit === '%' ? pctText(x, curDec) : (+x).toFixed(curDec) },
      splitLine: { lineStyle: { color: gridCol, type: 'solid' } },
    },
    // 左右滑动方式与 iframe / SVG 图一致：拖动平移 + 水平滚轮 + ⌘滚轮缩放 + 双击复位。
    // 不挂 slider 滑块条——那是本组件独有的第二套交互，与其他曲线不一致。
    // window 模式（数据给全历史）下 dataZoom 就是「可见窗口」本身，
    // 用户往左拖能拖出初始区间、看到更早历史——这是基金详情 iframe 图表同样的行为。
    dataZoom: props.zoom ? [
      { type: 'inside', xAxisIndex: 0, zoomOnMouseWheel: false, moveOnMouseWheel: false,
        moveOnMouseMove: true, ...winPct() },
    ] : undefined,
    // 硬约束（CLAUDE.md「H5 图表曲线规范」）：只画折线，smooth 显式 false；
    // 颜色 / 线宽 / 网格 / 零轴全部取自 chartTheme，与 Python 版 iframe 图表同一套设计。
    series: [{
      // showSymbol 恒 true：每个真实数据点都画圆点，与 iframe 图一致（原来 showSymbol:one 等于不画）。
      // symbol 必须显式写 'circle'：ECharts 默认是 'emptyCircle'（空心白底），而 iframe 图是实心蓝。
      type: 'line', data: v, showSymbol: true, symbol: 'circle', symbolSize: () => curDot, smooth: false,
      lineStyle: { color: col, width: CHART.lineWidth, cap: 'round', join: 'round' },
      itemStyle: { color: col },
      markPoint: marks.length ? { symbol: 'pin', symbolSize: 26, label: { color: '#fff', fontSize: 10 }, data: marks } : undefined,
      markLine: props.zero ? { silent: true, symbol: 'none', label: { show: false },
        lineStyle: { color: CHART.zero, type: 'dashed', width: 1 }, data: [{ yAxis: 0 }] } : undefined,
    }],
  }
}
// 双击复位：回到「当前区间」的初始窗口，与 iframe 图表的 dblclick（回最近一次预设区间）一致；
// 老行为（不传 window）才回全区间。
function reset() {
  if (chart && props.zoom) chart.dispatchAction({ type: 'dataZoom', ...winPct() })
}
function onDbl() { reset() }
// 可见区间 → 状态行文本：把 dataZoom 的百分比换算回真实日期，口径与 iframe 的 #range 一致
function syncRange() {
  if (!chart) return
  const a = axis()
  if (!a.length) { visRange.value = ''; return }
  // 不可滑动（zoom=false）时就是全量范围
  const dz = props.zoom ? ((chart.getOption().dataZoom || [])[0] || {}) : {}
  const s = dz.start ?? 0, e = dz.end ?? 100
  const i = Math.max(0, Math.round(s / 100 * (a.length - 1)))
  const j = Math.min(a.length - 1, Math.round(e / 100 * (a.length - 1)))
  visRange.value = rangeText(a[i], a[j])
}
// 缩放 / 平移后圆点大小与状态行都要跟着变；同组（同一页共用一个时间轴）的图一起走
const onZoom = () => {
  calcDot(); syncRange()
  const dz = ((chart.getOption() || {}).dataZoom || [])[0]
  syncGroup(props.group, chart, dz)
}
onMounted(() => {
  chart = echarts.init(el.value, null, { renderer: 'canvas' })
  calcDot(); curDec = decimalsFor(visValues())
  chart.setOption(option())
  el.value.__awChart = chart            // 便于调试 / 自动化校验视窗状态
  detachWheel = attachWheel(chart, el.value, () => props.zoom)
  el.value.addEventListener('dblclick', onDbl)
  chart.on('dataZoom', onZoom)
  syncRange()
  joinGroup(props.group, chart)
  window.addEventListener('resize', resize)
})
const resize = () => { if (chart) { calcDot(); chart.resize() } }
watch(() => [props.dates, props.values, props.marks, props.labels], () => {
  if (chart) { calcDot(); curDec = decimalsFor(visValues()); chart.setOption(option(), true); syncRange() }
})
watch(() => props.resetKey, () => { if (chart) { reset(); calcDot(); syncRange() } })
// 父级换了区间 → 窗口下标变了，直接把视窗挪过去（不重建 series，避免闪一下）
watch(() => props.window, () => {
  if (!chart) return
  // 换区间 → 可见数据量级变了，刻度/tooltip 精度跟着变（否则近1月的小波动会全变 0.00）
  curDec = decimalsFor(visValues())
  chart.setOption({ yAxis: option().yAxis })
  reset(); calcDot(); syncRange()
})
onBeforeUnmount(() => {
  el.value?.removeEventListener('dblclick', onDbl)
  detachWheel && detachWheel()
  window.removeEventListener('resize', resize)
  leaveGroup(props.group, chart)
  chart && chart.dispose()
})
</script>
