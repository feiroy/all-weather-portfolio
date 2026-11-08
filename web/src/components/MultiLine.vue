<template>
  <div class="aw-chart-box">
    <div ref="el" class="aw-chart" :style="{ height: height + 'px' }"></div>
    <ChartState :note="note || sparse" :range="visRange" />
  </div>
</template>
<script setup>
// 多条折线同图（对比 / 回测 / 信号页）：各条日期可以不一样，按日期并集对齐；颜色避开红绿
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { attachWheel } from '../utils/chartWheel'
import ChartState from './ChartState.vue'
import { axisLabel, rangeText, decimalsFor, decimalsOf, pctText } from '../utils/chartAxis'
import { CHART, TIP_BASE, SERIES_COLORS, dotSize, tipRows } from '../utils/chartTheme'
import { joinGroup, leaveGroup, syncGroup } from '../utils/chartGroup'
echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, DataZoomComponent, CanvasRenderer])

const props = defineProps({
  series: Object,            // { 名字: { dates:[], ret:[] } }
  height: { type: Number, default: 240 },
  unit: { type: String, default: '%' },
  colors: { type: Array, default: () => SERIES_COLORS },
  dashed: { type: Array, default: () => [] },   // 哪几条画虚线（比如「月末」对照）
  note: { type: String, default: '' },          // 状态行左侧说明
  // 可见窗口 [起, 止]（并集日期轴上的下标）。传了它 = 数据给全历史、由窗口决定看哪段，
  // 于是可以像单线图 / iframe 图表那样往左右拖出初始区间；不传 = 老行为（整条即全部）。
  window: { type: Array, default: null },
  resetKey: { type: [String, Number], default: 0 },
  group: { type: String, default: '' },         // 同 group 的多张图，平移/缩放联动
  kind: { type: String, default: 'line' },      // 'line' | 'bar'：柱形只换 series type，配色/坐标/tooltip/状态行全部复用
  // 下方面板（如回撤）：与上方面板共用 x 轴与缩放，独立 y 轴；不传就是原来的单面板
  second: { type: Object, default: null },
  secondRatio: { type: Number, default: 0.3 },  // 下方面板占绘图区高度的比例
  secondLabel: { type: String, default: '' },   // 下方面板左上角的说明（如「回撤」）
})
const el = ref(null)
const visRange = ref('')
// 聚合后只剩 1 期（比如建仓两个月的账户切「年线」）：折线画不出来，状态行要说明白
const sparse = computed(() => (axisDatesRaw().length < 2 ? `当前周期只有 ${axisDatesRaw().length} 期数据，切到日线 / 月线看走势` : ''))
let chart = null

// 所有线共用的日期轴（并集升序）——MultiLine 内部 option / 状态行 / 窗口换算都用它
const axisDatesRaw = () => [...new Set([
  ...Object.keys(props.series || {}).flatMap(n => props.series[n].dates),
  ...Object.keys(props.second || {}).flatMap(n => props.second[n].dates),
])].sort()
// 有没有下方面板
const hasSecond = () => !!props.second && Object.keys(props.second).length > 0
const axisDates = () => axisDatesRaw()
// 窗口下标 → dataZoom 百分比（ECharts 只认百分比）
function winPct() {
  const n = axisDates().length
  const w = props.window
  if (!w || n < 2) return { start: 0, end: 100 }
  const i0 = Math.max(0, Math.min(n - 1, Math.round(w[0] ?? 0)))
  const i1 = Math.max(i0, Math.min(n - 1, Math.round(w[1] ?? n - 1)))
  return { start: i0 / (n - 1) * 100, end: i1 / (n - 1) * 100 }
}

// 可见数据的数值精度：刻度与 tooltip 共用，避免「三条线差 0.1pp，tooltip 三行都是 ±0.00」
// 以及「Y 轴一列全是 0%」（用户 2026-11-08 截图里的正是这种）。
function visValues(src = props.series) {
  const all = axisDates()
  const w = props.window
  const i0 = w ? Math.max(0, Math.round(w[0] ?? 0)) : 0
  const i1 = w ? Math.min(all.length - 1, Math.round(w[1] ?? all.length - 1)) : all.length - 1
  const out = []
  for (const n of Object.keys(src || {})) {
    const m = new Map(src[n].dates.map((d, k) => [d, src[n].ret[k]]))
    for (let i = i0; i <= i1; i++) { const v = m.get(all[i]); if (v != null) out.push(v) }
  }
  return out
}
let curDec = 2          // 当前小数位（setOption 前先给 2）
let curDec2 = 2         // 下方面板（回撤）自己的小数位
function calcDec() {
  curDec = decimalsFor(visValues())
  if (hasSecond()) curDec2 = decimalsFor(visValues(props.second))
}

// 数据点圆点直径：与 iframe 图同规则，随可见点数自适应（见 chartTheme.dotRadius）
const GRID_L = 46, GRID_R = 34
let curDot = 4
function calcDot() {
  const n = axisDates().length
  let span = 1
  // 首次在 setOption 之前就会调用，那时 getOption() 还没有 dataZoom，必须容错
  if (chart) {
    const dz = ((chart.getOption() || {}).dataZoom || [])[0]
    if (dz) span = ((dz.end ?? 100) - (dz.start ?? 0)) / 100
  }
  const visible = Math.max(1, Math.round(n * (span > 0 ? span : 1)))
  curDot = dotSize((el.value?.clientWidth || 320) - GRID_L - GRID_R, visible)
}

// 图例可能在窄屏换成 2~3 行，grid.top 必须按实际行数留高度，
// 否则 Y 轴最上面那个刻度会压在图例文字上（手机上实测「5%」盖住第三只基金名字）。
const measureCtx = (() => {
  try { return document.createElement('canvas').getContext('2d') } catch { return null }
})()
function legendRows(names, avail) {
  if (!measureCtx || !names.length) return 1
  measureCtx.font = '11px -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif'
  const icon = 14 + 5, gap = 10          // 与 option 里的 itemWidth / itemGap 对应
  let used = 0, rows = 1
  for (const n of names) {
    const w = icon + measureCtx.measureText(n).width
    if (used > 0 && used + gap + w > avail) { rows++; used = w }
    else used += (used ? gap : 0) + w
  }
  return rows
}
function gridTop() {
  return 15 + legendRows(Object.keys(props.series || {}), (el.value?.clientWidth || 320) - 10) * 15
}

// 布局：单面板时就是原来那个 grid 对象；双面板时返回 [上, 下] 两个 grid，
// 上/下共用左右边距与 x 轴，中间留 28px 放「回撤」这类小标题
function gridConf() {
  const top = gridTop()
  if (!hasSecond()) return { left: GRID_L, right: GRID_R, top, bottom: 26 }
  const axisH = 26, gap = 30, H = props.height
  const avail = Math.max(80, H - top - axisH - gap)
  const h2 = Math.round(avail * Math.min(0.6, Math.max(0.15, props.secondRatio)))
  const h1 = avail - h2
  return [
    { left: GRID_L, right: GRID_R, top, height: h1 },
    { left: GRID_L, right: GRID_R, top: top + h1 + gap, height: h2 },
  ]
}

function option() {
  const names = Object.keys(props.series || {})
  const all = axisDates()
  // 横轴展示用标签：柱形图按「2026年10月」这种期间标签显示，但排序/窗口仍用真实日期，
  // 否则字符串排序会把「2026年10月」排到「2026年7月」前面
  const labelOf = new Map()
  for (const n of names) {
    const s = props.series[n]
    if (s.labels && s.labels.length === s.dates.length) s.dates.forEach((d, i) => labelOf.set(d, s.labels[i]))
  }
  const one = all.length < 2
  const series = names.map((n, i) => {
    const m = new Map(props.series[n].dates.map((d, k) => [d, props.series[n].ret[k]]))
    let last = null
    const data = all.map(d => { if (m.has(d)) last = m.get(d); return d < props.series[n].dates[0] ? null : last })
    const col = props.colors[i % props.colors.length]
    const isBar = props.kind === 'bar'
    return {
      // smooth 显式 false：CLAUDE.md 硬约束，所有曲线只画折线，不允许平滑
      // showSymbol 恒 true + symbol:'circle'（默认 'emptyCircle' 是空心白底，与 iframe 的实心蓝不一致）
      name: n, type: isBar ? 'bar' : 'line', data,
      showSymbol: !isBar, symbol: 'circle',
      symbolSize: () => curDot, connectNulls: true, smooth: false,
      ...(isBar ? { barMaxWidth: 14, barGap: '8%', barCategoryGap: '34%' } : {}),
      lineStyle: isBar ? undefined : { width: i === 0 ? CHART.lineWidth : 1.6, color: col,
                   type: props.dashed.includes(n) ? 'dashed' : 'solid', cap: 'round', join: 'round' },
      itemStyle: { color: col },
      markLine: i === 0 ? { silent: true, symbol: 'none', label: { show: false },
        lineStyle: { color: CHART.zero, type: 'dashed', width: 1 }, data: [{ yAxis: 0 }] } : undefined,
    }
  })
  const twoPanel = hasSecond()
  const gc = gridConf()
  const secNames = Object.keys(props.second || {})
  const secSeries = secNames.map((n, i) => {
    const src = props.second[n]
    const m = new Map(src.dates.map((d, k) => [d, src.ret[k]]))
    let last = null
    const data = all.map(d => { if (m.has(d)) last = m.get(d); return d < src.dates[0] ? null : last })
    const col = props.colors[i % props.colors.length]
    return {
      name: n + ' 回撤', type: 'line', data, xAxisIndex: 1, yAxisIndex: 1,
      showSymbol: true, symbol: 'circle', symbolSize: () => curDot, connectNulls: true, smooth: false,
      lineStyle: { width: 1.6, color: col, type: props.dashed.includes(n) ? 'dashed' : 'solid', cap: 'round', join: 'round' },
      itemStyle: { color: col },
    }
  })
  // 双面板 tooltip：一次把所有面板的值都列出来（涨跌 + 该时点回撤），不用按面板分别悬停
  const maps = names.map(n => new Map(props.series[n].dates.map((d, k) => [d, props.series[n].ret[k]])))
  const secMaps = secNames.map(n => new Map(props.second[n].dates.map((d, k) => [d, props.second[n].ret[k]])))
  const dot = c => `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;background:${c}"></span>`
  const fmt = (v, d) => v == null ? '—' : `${v > 0 ? '+' : ''}${(+v).toFixed(d)}${props.unit}`

  return {
    animation: false,
    legend: { top: 0, left: 0, itemWidth: 14, itemHeight: 3, icon: 'rect', data: names,
      textStyle: { fontSize: 11, color: CHART.axisText } },
    // right 要给足：横轴用完整日期 2026/09/30，居中对齐时最后一格会右溢出被裁
    grid: gc,
    graphic: undefined,
    // 左右滑动方式与 iframe / SVG 图一致：拖动 + 水平滚轮 + ⌘滚轮缩放 + 双击复位，不挂 slider 滑块
    // window 模式下 dataZoom 就是「可见窗口」，用户能往左拖出初始区间看更早历史
    dataZoom: [
      { type: 'inside', xAxisIndex: twoPanel ? [0, 1] : 0, zoomOnMouseWheel: false, moveOnMouseWheel: false, moveOnMouseMove: true, ...winPct() },
    ],
    tooltip: {
      trigger: 'axis', ...TIP_BASE,
      axisPointer: { type: 'line', lineStyle: { color: CHART.axisMuted, type: 'dashed' }, link: [{ xAxisIndex: 'all' }] },
      // 与单线图同一套内容结构：日期一行，下面每项「文字描述 + 数值」竖排（chartTheme.tipRows）
      formatter: ps => {
        if (!twoPanel) {
          return tipRows(
            axisLabel(ps[0].axisValue),
            ps.map(p => {
              const v = p.value
              if (v == null) return [`${p.marker}${p.seriesName}`, '—']
              return [`${p.marker}${p.seriesName}`, fmt(v, decimalsOf(v, curDec))]
            }),
          )
        }
        const label = ps[0].axisValue
        const i = all.findIndex(d => (labelOf.get(d) || d) === label)
        const rows = []
        names.forEach((n, k) => rows.push([dot(props.colors[k % props.colors.length]) + n, fmt(maps[k].get(all[i]), decimalsOf(maps[k].get(all[i]), curDec))]))
        secNames.forEach((n, k) => rows.push([dot(props.colors[k % props.colors.length]) + n + ' 回撤', fmt(maps && secMaps[k].get(all[i]), decimalsOf(secMaps[k].get(all[i]), curDec2))]))
        return tipRows(axisLabel(label), rows)
      },
    },
    // 注意 gridIndex：ECharts 轴的 gridIndex 默认永远是 0，两个面板必须显式写 1，
    // 否则下方面板的轴挂在上方 grid 上，线会画到上面去（而且值域对不上，看着像没画）
    xAxis: twoPanel ? [
      { type: 'category', data: all.map(d => labelOf.get(d) || d), boundaryGap: false, axisTick: { show: false }, gridIndex: 0,
        axisLine: { lineStyle: { color: CHART.axisLine } }, axisLabel: { show: false } },
      { type: 'category', data: all.map(d => labelOf.get(d) || d), boundaryGap: false, axisTick: { show: false }, gridIndex: 1,
        axisLine: { lineStyle: { color: CHART.axisLine } },
        // 日期统一口径（chartAxis.axisLabel）：始终 2026/09/30，不因序列长短换成 2015/01 或 09/30
        axisLabel: { color: CHART.axisText, fontSize: 10, hideOverlap: true, formatter: axisLabel } },
    ] : {
      type: 'category', data: all.map(d => labelOf.get(d) || d),
      boundaryGap: props.kind === 'bar', axisTick: { show: false },
      axisLine: { lineStyle: { color: CHART.axisLine } },
      axisLabel: { color: CHART.axisText, fontSize: 10, hideOverlap: true, formatter: axisLabel },
    },
    yAxis: twoPanel ? [
      { type: 'value', scale: true, splitNumber: 3, axisLine: { show: false }, axisTick: { show: false }, gridIndex: 0,
        axisLabel: { color: CHART.axisText, fontSize: 10,
          formatter: x => (props.unit === '%' ? pctText(x, curDec) : `${(+x).toFixed(curDec)}${props.unit}`) },
        splitLine: { lineStyle: { color: CHART.grid, type: 'solid' } } },
      { type: 'value', scale: true, splitNumber: 2, axisLine: { show: false }, axisTick: { show: false }, gridIndex: 1,
        name: props.secondLabel, nameLocation: 'end', nameGap: 9,
        nameTextStyle: { fontSize: 11, color: CHART.axisText, align: 'left' },
        axisLabel: { color: CHART.axisText, fontSize: 10,
          formatter: x => (props.unit === '%' ? pctText(x, curDec2) : `${(+x).toFixed(curDec2)}${props.unit}`) },
        splitLine: { lineStyle: { color: CHART.grid, type: 'solid' } } },
    ] : {
      type: 'value', scale: true, splitNumber: 4,
      axisLabel: { color: CHART.axisText, fontSize: 10,
        formatter: x => (props.unit === '%' ? pctText(x, curDec) : `${(+x).toFixed(curDec)}${props.unit}`) },
      splitLine: { lineStyle: { color: CHART.grid, type: 'solid' } },
    },
    series: twoPanel
      ? [...series.map(x => ({ ...x, xAxisIndex: 0, yAxisIndex: 0 })), ...secSeries]
      : series,
  }
}

// 可见区间 → 状态行文本，口径与 iframe 的 #range 一致
function syncRange() {
  const all = axisDates()
  if (!chart || !all.length) { visRange.value = ''; return }
  const dz = (chart.getOption().dataZoom || [])[0] || {}
  const s = dz.start ?? 0, e = dz.end ?? 100
  const i = Math.max(0, Math.round(s / 100 * (all.length - 1)))
  const j = Math.min(all.length - 1, Math.round(e / 100 * (all.length - 1)))
  visRange.value = rangeText(all[i], all[j])
}
// 缩放 / 平移后同组（同一页共用一个时间轴）的图一起走
const onZoom = () => {
  calcDot(); syncRange()
  syncGroup(props.group, chart, ((chart.getOption() || {}).dataZoom || [])[0])
}
// 双面板（多个 grid）时 ECharts 自带的 moveOnMouseMove 拖不动（实测 dataZoom 不变），
// 这里自己接管水平拖动：按下记位置，移动时按绘图区宽度换算成 dataZoom 平移
let panFrom = null
const plotWidth = () => {
  try { return chart.getModel().getComponent('grid', 0).coordinateSystem.getRect().width } catch { return 600 }
}
function dzState() {
  const d = ((chart && chart.getOption()) || {}).dataZoom || []
  const x = d[0] || {}
  return { start: x.start ?? 0, end: x.end ?? 100 }
}
function onPanDown(e) {
  if (!chart || !hasSecond()) return
  // 只接管绘图区（图例区仍要让 ECharts 收点击），并且必须拦住 zrender 自己的 mousedown，
  // 否则它在每次 mousemove 按自己的（失效的）拖拽状态把窗口拉回原位
  const r = el.value.getBoundingClientRect()
  const top = (gridConf()[0] || {}).top || 0
  if (e.clientY - r.top < top - 4) return
  e.stopPropagation()
  panFrom = { x: e.clientX, dz: dzState() }
}
function onPanMove(e) {
  if (!panFrom || !chart) return
  const dx = e.clientX - panFrom.x
  if (!dx) return
  const span = panFrom.dz.end - panFrom.dz.start
  const shift = -(dx / plotWidth()) * 100
  let start = Math.max(0, Math.min(100 - span, panFrom.dz.start + shift))
  chart.dispatchAction({ type: 'dataZoom', start, end: start + span })
}
const onPanUp = () => { panFrom = null }

onMounted(() => {
  chart = echarts.init(el.value, null, { renderer: 'canvas' })
  calcDot(); calcDec()
  chart.setOption(option())
  el.value.__awChart = chart
  detachWheel = attachWheel(chart, el.value)
  el.value.addEventListener('dblclick', onDbl)
  chart.on('dataZoom', onZoom)
  el.value.addEventListener('mousedown', onPanDown, true)   // 捕获阶段：zrender 会吃掉 canvas 上的 mousedown
  window.addEventListener('mousemove', onPanMove)
  window.addEventListener('mouseup', onPanUp)
  syncRange()
  joinGroup(props.group, chart)
  window.addEventListener('resize', resize)
})
// 双击复位：回到「当前区间」的初始窗口（不回全区间，否则多只对比会缩成整段历史看不清）
const reset = () => chart && chart.dispatchAction({ type: 'dataZoom', ...winPct() })
const onDbl = () => reset()
const resize = () => {
  if (!chart) return
  calcDot(); chart.resize()
  chart.setOption({ grid: gridConf() })
}
let detachWheel = null
watch(() => props.series, () => { if (chart) { calcDot(); calcDec(); chart.setOption(option(), true); syncRange() } })
// 下方面板可能比上方面板晚一步到（两个 computed 各自触发），必须单独监听，
// 否则首帧按空面板算出的 grid / 精度会一直留着
watch(() => props.second, () => { if (chart) { calcDot(); calcDec(); chart.setOption(option(), true); syncRange() } })
// 下方面板可能比上方面板晚一步到（两个 computed 各自触发），必须单独监听，
// 否则首帧按空面板算出的 grid / 精度会一直留着
watch(() => props.second, () => { if (chart) { calcDot(); calcDec(); chart.setOption(option(), true); syncRange() } })
watch(() => props.resetKey, () => { if (chart) { reset(); calcDot(); syncRange() } })
watch(() => props.window, () => {
  if (!chart) return
  // 换区间 = 可见数据的量级变了 → 精度要跟着变，否则又会退回「一列 0%」
  calcDec(); chart.setOption({ series: option().series, yAxis: option().yAxis })
  reset(); calcDot(); syncRange()
})
onBeforeUnmount(() => {
  el.value?.removeEventListener('dblclick', onDbl)
  el.value?.removeEventListener('mousedown', onPanDown, true)
  window.removeEventListener('mousemove', onPanMove)
  window.removeEventListener('mouseup', onPanUp)
  detachWheel && detachWheel()
  window.removeEventListener('resize', resize)
  leaveGroup(props.group, chart)
  chart && chart.dispose()
})
</script>
