<template>
  <div class="aw-chart-box">
    <div ref="el" class="aw-chart" :style="{ height: h + 'px' }"></div>
    <div v-if="tip" class="row-tip" :style="{ top: tip.y + 'px' }">{{ tip.text }}</div>
    <ChartState :note="dense ? '日线粒度格子太密，切月线更好读' : ''" :range="span" />
  </div>
</template>
<script setup>
// 单期收益热力图：行 = 策略，列 = 期间，颜色 = 该期涨跌（红涨绿跌）。
// 比 3 组并排柱形好读：一眼看出哪几个月谁在挨打，不需要逐个比高度。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { HeatmapChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import ChartState from './ChartState.vue'
import { axisLabel, rangeText } from '../utils/chartAxis'
import { CHART, TIP_BASE, tipRows } from '../utils/chartTheme'

echarts.use([HeatmapChart, GridComponent, TooltipComponent, VisualMapComponent, CanvasRenderer])

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

// 颜色：以绝对值最大值为对称端点，0 落在近白的中点，涨红跌绿（中国习惯）
// 列太多（日线长区间）时格子只剩几像素，提示换粒度
const dense = computed(() => labels.value.length > 120)

const maxAbs = computed(() => {
  let m = 0
  for (const n of names.value) for (const v of props.series[n].ret || []) if (v != null) m = Math.max(m, Math.abs(v))
  return m || 1
})

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
  // 格子窄到放不下「+1.4」时不要写字，否则文字会压到隔壁格子（手机 14 列时约 14px）
  // 行名只占窄窄一条（右侧格子才是重点）：桌面 104、手机 78，放不下就省略号，鼠标悬停看全名
  const boxW = el.value?.clientWidth || 320
  const nameW = boxW >= 560 ? 104 : 78
  const plotW = boxW - (nameW + 10) - 30
  const cellW = plotW / Math.max(1, xs.length)
  const labelsOff = xs.length > 40 || cellW < 26     // 放不下「+1.4」就不写字
  const cellsTight = xs.length > 120 || cellW < 9     // 格子只剩几像素时连描边也去掉
  // **不抽稀**：每列都标日期。放不下横向就竖排（比斜排好读、也不会被左边缘裁掉），
  // 竖排都放不下说明格子只有几像素，这时整行不画，看 tooltip 更靠谱
  // 每列都标，从不跳列。放不下完整日期时退成「09/30」（年份由上方状态行给），再放不下就整行不画
  const plainFits = xs.length * 40 <= plotW
  const shortFits = xs.length * 24 <= plotW
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
    series: [{
      type: 'heatmap', data: cells,
      itemStyle: { borderWidth: cellsTight ? 0 : 1, borderColor: '#fff', borderRadius: cellsTight ? 0 : 3 },
      label: { show: !labelsOff, fontSize: 10, formatter: p => `${p.value[2] > 0 ? '+' : ''}${p.value[2].toFixed(1)}` },
      emphasis: { itemStyle: { borderColor: CHART.axisText, borderWidth: 1 } },
    }],
  }
}
const dot = i => `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;background:${['#1E40AF', '#F59E0B', '#8B5CF6', '#0EA5E9'][i % 4]}"></span>`

function syncSpan() {
  const d = dates.value
  span.value = d.length ? rangeText(d[0], d[d.length - 1]) : ''
}
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

onMounted(() => {
  chart = echarts.init(el.value, null, { renderer: 'canvas' })
  chart.setOption(build())
  el.value.__awChart = chart      // 与 MultiLine 一致，便于调试/自动化断言
  el.value.addEventListener('mousemove', onHover)
  el.value.addEventListener('mouseleave', onLeave)
  syncSpan()
  window.addEventListener('resize', resize)
})
function resize() { if (chart) { chart.resize(); chart.setOption(build(), true); syncSpan() } }
watch(() => props.series, () => { if (chart) { chart.setOption(build(), true); syncSpan() } })
onBeforeUnmount(() => {
  el.value?.removeEventListener('mousemove', onHover)
  el.value?.removeEventListener('mouseleave', onLeave)
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