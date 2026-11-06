<template><div ref="el" class="aw-chart" :style="{ height: height + 'px' }"></div></template>
<script setup>
// 多条折线同图（对比 / 回测 / 信号页）：各条日期可以不一样，按日期并集对齐；颜色避开红绿
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { attachWheel } from '../utils/chartWheel'
echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, DataZoomComponent, CanvasRenderer])

const props = defineProps({
  series: Object,            // { 名字: { dates:[], ret:[] } }
  height: { type: Number, default: 240 },
  unit: { type: String, default: '%' },
  colors: { type: Array, default: () => ['#1E40AF', '#F59E0B', '#8B5CF6', '#0EA5E9', '#64748B', '#EC4899'] },
  dashed: { type: Array, default: () => [] },   // 哪几条画虚线（比如「月末」对照）
})
const el = ref(null)
let chart = null

function option() {
  const names = Object.keys(props.series || {})
  const all = [...new Set(names.flatMap(n => props.series[n].dates))].sort()
  const one = all.length < 2
  const series = names.map((n, i) => {
    const m = new Map(props.series[n].dates.map((d, k) => [d, props.series[n].ret[k]]))
    let last = null
    const data = all.map(d => { if (m.has(d)) last = m.get(d); return d < props.series[n].dates[0] ? null : last })
    return {
      name: n, type: 'line', data, showSymbol: one, symbolSize: 8, connectNulls: true,
      lineStyle: { width: i === 0 ? 2.2 : 1.6, color: props.colors[i % props.colors.length], type: props.dashed.includes(n) ? 'dashed' : 'solid' },
      itemStyle: { color: props.colors[i % props.colors.length] },
      markLine: i === 0 ? { silent: true, symbol: 'none', label: { show: false }, lineStyle: { color: '#CBD5E1', type: 'solid', width: 1 }, data: [{ yAxis: 0 }] } : undefined,
    }
  })
  const long = all.length > 400
  return {
    animation: false,
    legend: { top: 0, left: 0, itemWidth: 14, itemHeight: 3, icon: 'rect', textStyle: { fontSize: 11, color: '#4B5563' } },
    grid: { left: 46, right: 10, top: names.length > 3 ? 48 : 30, bottom: 46 },
    dataZoom: [
      { type: 'inside', xAxisIndex: 0, zoomOnMouseWheel: false, moveOnMouseWheel: false, moveOnMouseMove: true },
      { type: 'slider', xAxisIndex: 0, height: 16, bottom: 6, borderColor: 'transparent',
        backgroundColor: '#F1F2F4', fillerColor: 'rgba(30,64,175,.10)', handleSize: 0, showDetail: false, brushSelect: false },
    ],
    tooltip: {
      trigger: 'axis', confine: true, backgroundColor: 'rgba(17,24,39,.9)', borderWidth: 0, textStyle: { color: '#fff', fontSize: 12 },
      valueFormatter: v => v == null ? '—' : `${v >= 0 ? '+' : ''}${(+v).toFixed(2)}${props.unit}`,
    },
    xAxis: {
      type: 'category', data: all, boundaryGap: false, axisTick: { show: false },
      axisLine: { lineStyle: { color: '#E5E7EB' } },
      axisLabel: { color: '#9CA3AF', fontSize: 10, hideOverlap: true, formatter: s => long ? s.slice(0, 7).replace('-', '/') : s.slice(5).replace('-', '/') },
    },
    yAxis: {
      type: 'value', scale: true, splitNumber: 4,
      axisLabel: { color: '#9CA3AF', fontSize: 10, formatter: x => `${+x.toFixed(2)}${props.unit}` },
      splitLine: { lineStyle: { color: '#F0F1F3', type: 'dashed' } },
    },
    series,
  }
}
onMounted(() => {
  chart = echarts.init(el.value, null, { renderer: 'canvas' })
  chart.setOption(option())
  el.value.__awChart = chart
  detachWheel = attachWheel(chart, el.value)
  el.value.addEventListener('dblclick', onDbl)
  window.addEventListener('resize', resize)
})
const onDbl = () => chart && chart.dispatchAction({ type: 'dataZoom', start: 0, end: 100 })
const resize = () => chart && chart.resize()
let detachWheel = null
watch(() => props.series, () => chart && chart.setOption(option(), true))
onBeforeUnmount(() => {
  el.value?.removeEventListener('dblclick', onDbl)
  detachWheel && detachWheel()
  window.removeEventListener('resize', resize)
  chart && chart.dispose()
})
</script>
