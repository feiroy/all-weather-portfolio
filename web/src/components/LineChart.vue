<template><div ref="el" :style="{ height: height + 'px' }"></div></template>
<script setup>
// 一条折线（ECharts，按需引入）：带坐标轴、手指按住看数、可选买卖点标记、可选缩放
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, MarkPointComponent, MarkLineComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
echarts.use([LineChart, GridComponent, TooltipComponent, MarkPointComponent, MarkLineComponent, DataZoomComponent, CanvasRenderer])

const props = defineProps({
  dates: Array, values: Array, height: { type: Number, default: 180 },
  unit: { type: String, default: '%' }, dark: Boolean, marks: { type: Array, default: () => [] },
  zero: Boolean, fmtTip: Function,
})
const el = ref(null)
let chart = null

function option() {
  const v = props.values || []
  const up = v.length ? v[v.length - 1] >= (props.zero ? 0 : v[0]) : true
  const col = props.dark ? (up ? '#FCA5A5' : '#86EFAC') : (up ? '#E23B3B' : '#16A34A')
  const axisCol = props.dark ? 'rgba(255,255,255,.55)' : '#9CA3AF'
  const gridCol = props.dark ? 'rgba(255,255,255,.12)' : '#F0F1F3'
  const marks = props.marks.map(m => ({
    coord: [m.date, m.value], value: m.side === '买入' ? 'B' : 'S',
    itemStyle: { color: m.side === '买入' ? '#E23B3B' : '#16A34A' },
  }))
  return {
    animation: false,
    grid: { left: 44, right: 10, top: 12, bottom: 24 },
    tooltip: {
      trigger: 'axis', confine: true, backgroundColor: 'rgba(17,24,39,.9)', borderWidth: 0,
      textStyle: { color: '#fff', fontSize: 12 },
      axisPointer: { type: 'line', lineStyle: { color: axisCol, type: 'dashed' } },
      formatter: ps => {
        const p = ps[0]
        return props.fmtTip ? props.fmtTip(p.dataIndex) : `${p.axisValue}<br/><b>${(+p.data).toFixed(2)}${props.unit}</b>`
      },
    },
    xAxis: {
      type: 'category', data: props.dates, boundaryGap: false,
      axisLine: { lineStyle: { color: gridCol } }, axisTick: { show: false },
      axisLabel: { color: axisCol, fontSize: 10, hideOverlap: true, formatter: s => s.slice(5).replace('-', '/') },
    },
    yAxis: {
      type: 'value', scale: !props.zero, splitNumber: 4,
      axisLabel: { color: axisCol, fontSize: 10, formatter: x => props.unit === '%' ? `${+x.toFixed(2)}%` : x.toFixed(3) },
      splitLine: { lineStyle: { color: gridCol, type: 'dashed' } },
    },
    series: [{
      type: 'line', data: v, showSymbol: false, smooth: 0.2, lineStyle: { color: col, width: 2 },
      areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: col + '55' }, { offset: 1, color: col + '00' }]) },
      markPoint: marks.length ? { symbol: 'pin', symbolSize: 26, label: { color: '#fff', fontSize: 10 }, data: marks } : undefined,
      markLine: props.zero ? { silent: true, symbol: 'none', label: { show: false }, lineStyle: { color: axisCol, type: 'solid', width: 1 }, data: [{ yAxis: 0 }] } : undefined,
    }],
  }
}
onMounted(() => {
  chart = echarts.init(el.value, null, { renderer: 'canvas' })
  chart.setOption(option())
  window.addEventListener('resize', resize)
})
const resize = () => chart && chart.resize()
watch(() => [props.dates, props.values, props.marks], () => chart && chart.setOption(option(), true))
onBeforeUnmount(() => { window.removeEventListener('resize', resize); chart && chart.dispose() })
</script>
