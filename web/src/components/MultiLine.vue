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
import { GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, DataZoomComponent, GraphicComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { attachWheel } from '../utils/chartWheel'
import ChartState from './ChartState.vue'
import { axisLabel, rangeText, decimalsFor, decimalsOf, pctText } from '../utils/chartAxis'
import { CHART, TIP_BASE, SERIES_COLORS, dotSize, tipRows } from '../utils/chartTheme'
import { joinGroup, leaveGroup, syncGroup } from '../utils/chartGroup'
// GraphicComponent 别漏：三层联动图每个 grid 左上角的小标题是 graphic 文本，
// 少了它 ECharts 会静默忽略 graphic 选项（面板没名字，用户就看不出每层画的是什么）
echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, DataZoomComponent, GraphicComponent, CanvasRenderer])

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
  // 下方面板的单位（默认跟主图一致）：主图画净值（unit=''）时，副图画回撤要用 '%'
  secondUnit: { type: String, default: '' },
  secondRatio: { type: Number, default: 0.3 },  // 下方面板占绘图区高度的比例
  secondLabel: { type: String, default: '' },   // 下方面板左上角的说明（如「回撤」）
  // 通用多面板（基金详情页）：一个图里叠 N 个 grid，共用时间轴 / 缩放 / tooltip / 状态行。
  // 每项 { key, label, unit, tipUnit?, decimals?, ratio, color?, zeroLine?, series:{名字:{dates,ret}} }
  // 后续 MACD / 神奇九转就是往这个数组里加一项：MACD 用多序列 + bar，九转在净值面板挂 markPoint。
  // 传了 panels 就忽略 series / second（panels[0] 即主面板）；不传则完全走原来的单/双面板逻辑。
  panels: { type: Array, default: null },
  // 图例受控（可选）：传了数组 = 把「图例上关掉了哪几条」这份状态同步给父组件，
  // 父组件据此让同页其它卡片（如单期收益热力图 / 区间指标小表）一起隐藏；不传 = 老行为，纯内部状态。
  // 数组里除策略名还会带「N 回撤」（下方面板的联动隐藏），父组件按自己的名字取交集即可。
  hiddenNames: { type: Array, default: null },
})
const emit = defineEmits(['update:hiddenNames'])
const el = ref(null)
const visRange = ref('')
// 聚合后只剩 1 期（比如建仓两个月的账户切「年线」）：折线画不出来，状态行要说明白
const sparse = computed(() => (axisDatesRaw().length < 2 ? `当前周期只有 ${axisDatesRaw().length} 期数据，切到日线 / 月线看走势` : ''))
let chart = null

// 通用多面板：每个面板可以有 1~N 条序列（MACD 未来就是 3 条）
const usePanels = () => Array.isArray(props.panels) && props.panels.length > 0
const panelList = () => (usePanels() ? props.panels : [])
const panelSeries = p => p.series || {}
const panelNames = () => [...new Set(panelList().flatMap(p => Object.keys(panelSeries(p))))]
// 每层只有一条线时（单只基金），面板标题就是名字，再画图例是重复信息；有多条线（对比）才要图例
const panelLegend = () => panelList().some(p => Object.keys(panelSeries(p)).length > 1)
const multiPanel = () => (usePanels() ? panelList().length > 1 : hasSecond())

// 所有线共用的日期轴（并集升序）——MultiLine 内部 option / 状态行 / 窗口换算都用它
const axisDatesRaw = () => [...new Set([
  ...Object.keys(props.series || {}).flatMap(n => props.series[n].dates),
  ...Object.keys(props.second || {}).flatMap(n => props.second[n].dates),
  ...panelList().flatMap(p => Object.values(panelSeries(p)).flatMap(s => s.dates || [])),
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
    // 隐藏序列不参与精度/值域判断，否则隐掉一条极端曲线后刻度小数位仍按它算
    if (hidden.value.has(n)) continue
    const m = new Map(src[n].dates.map((d, k) => [d, src[n].ret[k]]))
    for (let i = i0; i <= i1; i++) { const v = m.get(all[i]); if (v != null) out.push(v) }
  }
  return out
}
let curDec = 2          // 当前小数位（setOption 前先给 2）
let curDec2 = 2         // 下方面板（回撤）自己的小数位
let curDecs = []        // 通用多面板：每个面板坐标轴的小数位（按可见跨度自适应，刻度不必 4.5000 这么长）
function calcDec() {
  curDec = decimalsFor(visValues())
  if (hasSecond()) curDec2 = decimalsFor(visValues(props.second))
  if (usePanels()) curDecs = panelList().map(p => decimalsFor(visValues(panelSeries(p))))
}

// 数据点圆点直径：与 iframe 图同规则，随可见点数自适应（见 chartTheme.dotRadius）
const GRID_L = 46, GRID_R = 34
let curDot = 4
function calcDot() {
  const n = axisDates().length
  // 首次在 setOption 之前就会调用，那时还没有 dataZoom：用即将生效的窗口（winPct）算，
  // 否则会按「全历史 3000+ 点」算出 1px 半径，首屏近1月 23 个点也画成看不见的小点
  const w = winPct()
  let span = (w.end - w.start) / 100
  if (chart) {
    const dz = ((chart.getOption() || {}).dataZoom || [])[0]
    if (dz && dz.start != null) span = ((dz.end ?? 100) - (dz.start ?? 0)) / 100
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
  if (usePanels()) {
    // 多面板：首个 grid 上方放一行面板标题；有图例（对比）再按图例行数加高
    return 24 + (panelLegend() ? legendRows(panelNames(), (el.value?.clientWidth || 320) - 10) * 15 + 4 : 0)
  }
  return 15 + legendRows(Object.keys(props.series || {}), (el.value?.clientWidth || 320) - 10) * 15
}

// 通用多面板的布局：按 ratio 分配绘图区高度，面板之间留 30px 放各自的标题，
// 只有最下面那个 grid 显示横轴日期（上面几个共用同一条时间轴，不重复画刻度）
function panelGrids() {
  const ps = panelList(), top = gridTop()
  const axisH = 26, gap = 30, H = props.height
  const avail = Math.max(120, H - top - axisH - gap * (ps.length - 1))
  const weights = ps.map(p => p.ratio > 0 ? p.ratio : 1)
  const sum = weights.reduce((a, b) => a + b, 0)
  let y = top
  return ps.map((p, i) => {
    const h = Math.round(avail * weights[i] / sum)
    const g = { left: GRID_L, right: GRID_R, top: y, height: h }
    y += h + gap
    return g
  })
}
// 每个面板左上角的小标题（graphic 绝对像素定位，resize 时按新 grid 重算）
function panelsGraphic(gc) {
  return gc.map((g, i) => ({
    // 标题从绘图区左缘起、整行落在两层之间的空白里：x 上避开左侧 Y 刻度，y 上避开上一层最底那个刻度
    type: 'text', left: g.left, top: g.top - 19, silent: true,
    style: { text: panelList()[i].label || '', fill: CHART.axisText,
      font: '600 11px -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif' },
  }))
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

// 通用多面板 option：一个 ECharts 实例里叠 N 个 grid，共用一条 x 轴 / 一次缩放 / 一个 tooltip /
// 一条状态行。与 iframe 三层图（净值 / 累计 / 柱）同构；基金详情页的净值主图永远在 panels[0]。
function panelsOption() {
  const ps = panelList(), all = axisDates(), gc = panelGrids()
  const labelOf = new Map()
  for (const p of ps) for (const s of Object.values(panelSeries(p))) {
    if (s.labels && s.labels.length === s.dates.length) s.dates.forEach((d, i) => labelOf.set(d, s.labels[i]))
  }
  const xLabels = all.map(d => labelOf.get(d) || d)
  const dot = c => `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;background:${c}"></span>`
  const fmtPanel = (v, d, unit) => {
    if (v == null) return '—'
    return `${unit === '%' && +v > 0 ? '+' : ''}${(+v).toFixed(decimalsOf(v, d))}${unit}`
  }
  const series = [], rowsByPanel = []
  ps.forEach((p, pi) => {
    const rows = []
    Object.entries(panelSeries(p)).forEach(([n, s], k) => {
      if (!s.dates?.length) return
      const m = new Map(s.dates.map((d, i) => [d, s.ret[i]]))
      const col = s.color || p.color || props.colors[k % props.colors.length]
      const isBar = (s.kind || p.kind || 'line') === 'bar'
      let last = null
      const data = all.map(d => { if (m.has(d)) last = m.get(d); return d < s.dates[0] ? null : last })
      const dec = p.decimals ?? curDecs[pi] ?? 2   // tooltip：面板指定位数优先（净值 4 位）
      series.push({
        name: n, type: isBar ? 'bar' : 'line', data, xAxisIndex: pi, yAxisIndex: pi,
        showSymbol: !isBar, symbol: 'circle', symbolSize: () => curDot,
        connectNulls: true, smooth: false,
        ...(isBar ? { barMaxWidth: 14, barGap: '8%', barCategoryGap: '34%' } : {
          lineStyle: { width: pi === 0 && k === 0 ? CHART.lineWidth : 1.6, color: col,
            type: props.dashed.includes(n) ? 'dashed' : 'solid', cap: 'round', join: 'round' },
        }),
        itemStyle: { color: col },
        // 零轴虚线：区间涨跌 / 回撤这类以 0 为分界的面板才画，净值面板不画。
        // 面板自带 markPoint / markLine 时优先用自带的 —— 神奇九转的 1~9 数字标记就挂在这里。
        markLine: s.markLine || (p.zeroLine && k === 0 ? { silent: true, symbol: 'none', label: { show: false },
          lineStyle: { color: CHART.zero, type: 'dashed', width: 1 }, data: [{ yAxis: 0 }] } : undefined),
        markPoint: s.markPoint || undefined,
      })
      rows.push({ name: n, map: m, color: col, unit: p.tipUnit ?? p.unit ?? '%', dec })
    })
    rowsByPanel.push({ label: p.label || '', rows })
  })
  const axisFmt = (x, i) => {
    const u = ps[i].unit ?? '%'
    return u === '%' ? pctText(x, curDecs[i] ?? 2) : `${(+x).toFixed(curDecs[i] ?? 2)}${u}`
  }
  return {
    animation: false,
    legend: { show: panelLegend(), top: 0, left: 0, itemWidth: 14, itemHeight: 3, icon: 'rect', data: panelNames(),
      textStyle: { fontSize: 11, color: CHART.axisText } },
    grid: gc,
    graphic: panelsGraphic(gc),
    // 只有一套时间轴交互：inside + 拖动/水平滚轮/⌘缩放/双击复位，不挂 slider 滑块
    dataZoom: [{ type: 'inside', xAxisIndex: ps.map((_, i) => i),
      zoomOnMouseWheel: false, moveOnMouseWheel: false, moveOnMouseMove: true, ...winPct() }],
    tooltip: {
      trigger: 'axis', ...TIP_BASE,
      axisPointer: { type: 'line', lineStyle: { color: CHART.axisMuted, type: 'dashed' }, link: [{ xAxisIndex: 'all' }] },
      // 悬停一次就同时读到三层的值：日期 → 单位净值 → 区间涨跌 → 回撤（tipRows 统一两列结构）
      formatter: pp => {
        const label = pp[0]?.axisValue
        const i = xLabels.findIndex(x => x === label)
        if (i < 0) return ''
        const rows = []
        // 每层一条线：一行一个值；每层多条线（对比）：先一行层名做小标题，下面逐只基金
        rowsByPanel.forEach(({ label: pl, rows: list }) => {
          if (list.length > 1) rows.push([`<b style="color:${CHART.tipInk}">${pl}</b>`, ' '])
          list.forEach(r => rows.push([dot(r.color) + r.name, fmtPanel(r.map.get(all[i]), r.dec, r.unit)]))
        })
        return tipRows(axisLabel(label), rows)
      },
    },
    xAxis: gc.map((g, i) => ({
      type: 'category', data: xLabels, boundaryGap: false, gridIndex: i,
      axisTick: { show: false }, axisLine: { lineStyle: { color: CHART.axisLine } },
      // 只有最下面那个面板画日期，上面两个共用同一条时间轴、不重复刻度
      axisLabel: i === gc.length - 1
        ? { color: CHART.axisText, fontSize: 10, hideOverlap: true, formatter: axisLabel }
        : { show: false },
    })),
    yAxis: gc.map((g, i) => ({
      type: 'value', scale: true, splitNumber: i === 0 ? 3 : 2, gridIndex: i,
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: CHART.axisText, fontSize: 10, formatter: x => axisFmt(x, i) },
      splitLine: { lineStyle: { color: CHART.grid, type: 'solid' } },
    })),
    series,
  }
}

function option() {
  if (usePanels()) return panelsOption()
  const allNames = Object.keys(props.series || {})
  // 图例项必须始终有对应 series 才能再次点击恢复：ECharts 对「legend.data 里存在、series 里不存在」
  // 的名字会渲染成不可选状态，隐藏后用户就再也点不回来了（2026-11-08 用户反馈）。
  // 所以隐藏 = 保留 series + data 置空，而不是从 series 里删掉；顺带颜色按全量序号固定，
  // 隐藏几条之后剩下的线也不会串色。
  const names = allNames
  const visibleNames = allNames.filter(n => !hidden.value.has(n))
  const firstVisible = visibleNames[0] || allNames[0]
  const colOf = n => props.colors[Math.max(0, allNames.indexOf(n)) % props.colors.length]
  const all = axisDates()
  // 横轴展示用标签：柱形图按「2026年10月」这种期间标签显示，但排序/窗口仍用真实日期，
  // 否则字符串排序会把「2026年10月」排到「2026年7月」前面。用全量序列取标签，
  // 隐藏策略不会让横轴日期忽然变一套写法。
  const labelOf = new Map()
  for (const n of names) {
    const s = props.series[n]
    if (s.labels && s.labels.length === s.dates.length) s.dates.forEach((d, i) => labelOf.set(d, s.labels[i]))
  }
  const one = all.length < 2
  const series = names.map((n, i) => {
    const m = new Map(props.series[n].dates.map((d, k) => [d, props.series[n].ret[k]]))
    let last = null
    const data = hidden.value.has(n)
      ? all.map(() => null)
      : all.map(d => { if (m.has(d)) last = m.get(d); return d < props.series[n].dates[0] ? null : last })
    const col = colOf(n)
    const isBar = props.kind === 'bar'
    return {
      // smooth 显式 false：CLAUDE.md 硬约束，所有曲线只画折线，不允许平滑
      // showSymbol 恒 true + symbol:'circle'（默认 'emptyCircle' 是空心白底，与 iframe 的实心蓝不一致）
      name: n, type: isBar ? 'bar' : 'line', data,
      showSymbol: !isBar, symbol: 'circle',
      symbolSize: () => curDot, connectNulls: true, smooth: false,
      ...(isBar ? { barMaxWidth: 14, barGap: '8%', barCategoryGap: '34%' } : {}),
      lineStyle: isBar ? undefined : { width: n === firstVisible ? CHART.lineWidth : 1.6, color: col,
                   type: props.dashed.includes(n) ? 'dashed' : 'solid', cap: 'round', join: 'round' },
      itemStyle: { color: col },
      // 零轴虚线挂在第一条「可见」线上，第一条被隐藏时基准线不能跟着消失
      markLine: n === firstVisible ? { silent: true, symbol: 'none', label: { show: false },
        lineStyle: { color: CHART.zero, type: 'dashed', width: 1 }, data: [{ yAxis: 0 }] } : undefined,
    }
  })
  const twoPanel = hasSecond()
  const gc = gridConf()
  const secNames = Object.keys(props.second || {}).filter(n => !hidden.value.has(n))
  const secSeries = secNames.map((n, i) => {
    const src = props.second[n]
    const m = new Map(src.dates.map((d, k) => [d, src.ret[k]]))
    let last = null
    const data = all.map(d => { if (m.has(d)) last = m.get(d); return d < src.dates[0] ? null : last })
    const col = colOf(n)
    return {
      name: n + ' 回撤', type: 'line', data, xAxisIndex: 1, yAxisIndex: 1,
      showSymbol: true, symbol: 'circle', symbolSize: () => curDot, connectNulls: true, smooth: false,
      lineStyle: { width: 1.6, color: col, type: props.dashed.includes(n) ? 'dashed' : 'solid', cap: 'round', join: 'round' },
      itemStyle: { color: col },
    }
  })
  // 双面板 tooltip：一次把所有面板的值都列出来（涨跌 + 该时点回撤），不用按面板分别悬停
  // maps 按全量名单建（隐藏只是不显示，不能让下标/名字对不上导致悬浮卡死），
  // formatter 里只按 visibleNames / secNames 输出行。
  const maps = Object.fromEntries(allNames.map(n => [n, new Map(props.series[n].dates.map((d, k) => [d, props.series[n].ret[k]]))]))
  const secMaps = Object.fromEntries(secNames.map(n => [n, new Map(props.second[n].dates.map((d, k) => [d, props.second[n].ret[k]]))]))
  const dot = c => `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;background:${c}"></span>`
  const fmt = (v, d, unit = props.unit) => v == null ? '—' : `${v > 0 && unit === '%' ? '+' : ''}${(+v).toFixed(d)}${unit}`

  return {
    animation: false,
    legend: { top: 0, left: 0, itemWidth: 14, itemHeight: 3, icon: 'rect', data: allNames,
      selected: Object.fromEntries(allNames.map(n => [n, !hidden.value.has(n)])),
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
        const label = ps[0]?.axisValue
        if (label == null) return ''       // 全部策略都被隐藏时不画空壳提示框
        if (!twoPanel) {
          // 隐藏序列仍留在 option.series 里（为了图例可恢复），tooltip 要按隐藏名单过滤，
          // 否则会多出一行「—」占位置
          return tipRows(
            axisLabel(label),
            ps.filter(p => !hidden.value.has(p.seriesName)).map(p => {
              const v = p.value
              if (v == null) return [`${p.marker}${p.seriesName}`, '—']
              return [`${p.marker}${p.seriesName}`, fmt(v, decimalsOf(v, curDec))]
            }),
          )
        }
        const i = all.findIndex(d => (labelOf.get(d) || d) === label)
        const d = i >= 0 ? all[i] : null
        const rows = []
        visibleNames.forEach(n => { const v = d == null ? null : maps[n].get(d); rows.push([dot(colOf(n)) + n, fmt(v, decimalsOf(v, curDec))]) })
        secNames.forEach(n => { const v = d == null ? null : secMaps[n].get(d); rows.push([dot(colOf(n)) + n + ' 回撤', fmt(v, decimalsOf(v, curDec2))]) })
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
          formatter: x => (props.secondUnit === '%' ? pctText(x, curDec2) : `${(+x).toFixed(curDec2)}${props.secondUnit}`) },
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
// 圆点大小变了要推回图表：symbolSize 回调只在渲染时取值，dataZoom 之后才重算的 curDot 不会自动生效
function applyDot() {
  if (!chart) return
  const prev = curDot
  calcDot()
  if (Math.abs(prev - curDot) < 0.05) return
  const n = ((chart.getOption() || {}).series || []).length
  if (n) chart.setOption({ series: Array.from({ length: n }, () => ({ symbolSize: curDot })) })
}
const onZoom = () => {
  applyDot(); syncRange()
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
  if (!chart || !multiPanel()) return
  // 只接管绘图区（图例区仍要让 ECharts 收点击），并且必须拦住 zrender 自己的 mousedown，
  // 否则它在每次 mousemove 按自己的（失效的）拖拽状态把窗口拉回原位
  const r = el.value.getBoundingClientRect()
  const g = usePanels() ? panelGrids() : gridConf()
  const top = (Array.isArray(g) ? g[0] : g)?.top || 0
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

// 图例隐藏要联动到下方面板：主图线叫 N，回撤线叫 N 回撤，ECharts 图例只认主图名字，
// 不处理的话「隐藏某个策略」后主图没了、回撤面板还留着那条线，tooltip 也还在报数。
const hidden = ref(new Set())
onMounted(() => {
  chart = echarts.init(el.value, null, { renderer: 'canvas' })
  calcDot(); calcDec()
  chart.setOption(option())
  chart.on('legendselectchanged', e => {
    let changed = false
    for (const [n, on] of Object.entries(e.selected || {})) {
      for (const key of new Set([n, `${n} 回撤`])) {
        const was = hidden.value.has(key)
        if (!on && !was) { hidden.value.add(key); changed = true }
        else if (on && was) { hidden.value.delete(key); changed = true }
      }
    }
    if (!changed) return
    calcDot(); calcDec(); chart.setOption(option(), true); syncRange()
    // 受控模式：把最新隐藏集合发给父组件（数组拷贝，避免父组件拿到会被就地改动的 Set）
    if (props.hiddenNames) emit('update:hiddenNames', [...hidden.value])
  })
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
  chart.setOption(usePanels()
    ? (() => { const gc = panelGrids(); return { grid: gc, graphic: panelsGraphic(gc) } })()
    : { grid: gridConf() })
}
let detachWheel = null
watch(() => props.series, () => { if (chart) { calcDot(); calcDec(); chart.setOption(option(), true); syncRange() } })
// 受控图例：父组件换了一批策略（调仓节奏 / 起点变了）会把它清空，这里要跟着把内部隐藏集合同步过来，
// 否则新的一批曲线会「看着显示、状态里却算隐藏」。父组件原样回传我们 emit 出去的值时内容相同，直接跳过。
watch(() => props.hiddenNames, v => {
  if (!Array.isArray(v) || !chart) return
  const next = new Set(v)
  if (next.size === hidden.value.size && [...next].every(n => hidden.value.has(n))) return
  hidden.value = next
  calcDot(); calcDec(); chart.setOption(option(), true); syncRange()
})
// 下方面板可能比上方面板晚一步到（两个 computed 各自触发），必须单独监听，
// 否则首帧按空面板算出的 grid / 精度会一直留着
watch(() => props.second, () => { if (chart) { calcDot(); calcDec(); chart.setOption(option(), true); syncRange() } })
// 通用多面板：panels 是 computed 出来的数组，内部序列变化也要重画（含 grid / 标题 / 精度）
watch(() => props.panels, () => { if (chart && usePanels()) { calcDot(); calcDec(); chart.setOption(option(), true); syncRange() } }, { deep: true })
watch(() => props.resetKey, () => { if (chart) { reset(); calcDot(); syncRange() } })
watch(() => props.window, () => {
  if (!chart) return
  // 换区间 = 可见数据的量级变了 → 精度要跟着变，否则又会退回「一列 0%」
  calcDec()
  const o = option()
  chart.setOption({ series: o.series, yAxis: o.yAxis })
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
