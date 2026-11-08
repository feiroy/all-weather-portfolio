// 曲线图统一设计 token —— 基准是 Python 版 iframe 图表
// （allweather/chart_html.py 与 streamlit_app/app.py 逐字节同源）。
// CLAUDE.md「H5 图表曲线规范」：所有曲线只画折线，统一设计风格以 iframe 图表为准。
// 任何曲线组件（ECharts canvas 或手写 SVG）都必须引用这里，不许各自硬编码颜色/线型。
export const CHART = {
  line: '#1E40AF',        // 主走势 / 净值折线（深蓝，2026-11-07 用户要求改回：亮蓝不够明显）
  lineWidth: 2,
  grid: '#EEF2F7',        // 细网格：实线
  axisLine: '#E2E8F0',    // 坐标轴线
  axisText: '#475569',    // 坐标文字
  axisMuted: '#94A3B8',   // 次级文字 / 悬停引导线
  zero: '#CBD5E1',        // 零轴：虚线
  up: '#C52828',          // 涨 / 买入（中国习惯涨红）
  down: '#16703B',        // 跌 / 卖出（跌绿）
  tipBg: '#fff',          // tooltip：白色卡片，与 iframe 版一致
  tipInk: '#0F172A',
  tipLine: '#E2E8F0',
  tipShadow: '0 4px 16px rgba(15,23,42,.16)',
}

// 多序列对比：第一条用主深蓝，其余避开红绿（涨红跌绿只用于柱 / 买卖标记，不用于折线）
export const SERIES_COLORS = ['#1E40AF', '#F59E0B', '#8B5CF6', '#0EA5E9', '#64748B', '#EC4899']

// 数据点圆点半径：与 iframe 买卖点图逐条同规则 r = clamp(step * 0.12, 1, 3.5)，
// step = 绘图区宽度 / 可见点数。点稀疏时点大、密集时自动缩到 1px，不会糊成一片。
// 所有曲线都必须「每个真实数据点画一个圆点」，禁止只在末点 / 点少时才画（CLAUDE.md「数据点标记」）。
export const dotRadius = (plotW, count) =>
  Math.min(3.5, Math.max(1, (plotW || 320) / Math.max(1, count) * 0.12))

// ECharts 的 symbolSize 是直径，SVG 的 r 是半径
export const dotSize = (plotW, count) => 2 * dotRadius(plotW, count)

// ECharts 的 tooltip 统一白底配置（深色 tooltip 是旧 H5 自造风格，与 iframe 版不一致）
export const TIP_BASE = {
  confine: true,
  backgroundColor: CHART.tipBg,
  borderColor: CHART.tipLine,
  borderWidth: 1,
  textStyle: { color: CHART.tipInk, fontSize: 12 },
  extraCssText: `box-shadow:${CHART.tipShadow};border-radius:8px;`,
}

// 统一的 tooltip 内容：第一行日期，下面每项「文字描述 + 数值」竖排两行（标签左、数值右对齐）。
// 不再用「0.08%　-407 元」这种靠空格并排的写法 —— 数字一长就挤在一起，也看不出哪个是率哪个是额。
// 例：tipRows('2026/10/27', [['收益率', '-0.08%'], ['收益', '-407 元']])
export function tipRows(title, rows) {
  const one = ([k, v]) =>
    `<div style="display:flex;justify-content:space-between;gap:16px;line-height:1.65">` +
    `<span style="color:${CHART.axisText};font-size:11.5px">${k}</span>` +
    `<b style="font-variant-numeric:tabular-nums">${v}</b></div>`
  const body = (rows || [])
    .filter(r => r && r[1] != null && r[1] !== '')
    .map(one)
    .join('')
  return `<div style="min-width:120px">` +
    `<div style="color:${CHART.axisMuted};font-size:11px;margin-bottom:3px;font-variant-numeric:tabular-nums">${title}</div>` +
    body + `</div>`
}
