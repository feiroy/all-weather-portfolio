// 曲线日期标签 / 可见区间的统一口径。
// 与 allweather/chart_html.py::_period_label 同规则（CLAUDE.md「H5 图表曲线规范」）：
//   日 = 2026/09/24      月 = 2026年9月      年 = 2026年
// 禁止再出现「09/30」这种砍掉年份的简写：横轴必须能直接读出是哪一年的哪一天。

const DMY = /^(\d{4})-(\d{2})-(\d{2})$/
const SLASH = /^(\d{4})\/(\d{2})\/(\d{2})$/

/** 任意一个横轴值 → 统一展示标签。已是「2026年10月」「2026年」这类期间标签时原样返回。 */
export function axisLabel(s) {
  if (typeof s !== 'string') return s
  if (DMY.test(s)) return s.replace(/-/g, '/')          // 2026-09-30 → 2026/09/30
  if (SLASH.test(s)) return s
  return s                                               // 2026年10月 / 2026年：本就是 Python 口径
}

/** 横轴值 → 真实日期文本（给状态行用）；期间标签原样返回。 */
export const dateText = s => axisLabel(s)

/** 可见区间文本：起 — 止，与 iframe 图表的 #range 完全一致。 */
export function rangeText(a, b) {
  if (!a && !b) return ''
  if (!b || a === b) return dateText(a)
  return `${dateText(a)} — ${dateText(b)}`
}

// ---------------------------------------------------------------- 数值精度
// 坐标刻度和 tooltip 如果一律 toFixed(2)，小幅波动会被整体抹成「0% / ±0.00」：
// 「和基准比」里三条线明明差 \(0.1\)pp，tooltip 却三行都是 -0.00%/+0.00%（用户 2026-11-08 反馈
// 「值都一样，曲线却不相同」）。这里按**可见数值的跨度**决定小数位，并对接近 0 的点再补两位。
const finite = arr => (arr || []).filter(v => v != null && Number.isFinite(+v)).map(Number)

/** 可见数值列表 → 需要的最大小数位（2~4）。跨度为 0 时退回看绝对值量级。 */
export function decimalsFor(values) {
  const v = finite(values)
  if (!v.length) return 2
  const span = Math.max(...v) - Math.min(...v)
  const mag = span > 0 ? span : Math.max(...v.map(Math.abs))
  if (!(mag > 0)) return 2
  if (mag >= 20) return 0          // 跨度几十个百分点（回测累计收益）→ 180% 比 180.00% 干净
  if (mag >= 5) return 1
  if (mag >= 1) return 2
  if (mag >= 0.1) return 3
  return 4
}

/** 单个数值：小数位不少于 d；|v| 小于 10^-d 时自动补到 4 位，避免一串 ±0.00。 */
export function decimalsOf(v, d = 2) {
  const base = Math.max(2, d)            // tooltip 至少两位小数，别跟着刻度一起变整数
  if (v == null || !Number.isFinite(+v)) return base
  const a = Math.abs(+v)
  if (+v !== 0 && a < Math.pow(10, -base)) return 4
  return base
}

/** 百分比文本：固定 d 位，不用 toFixed 的「-0.00」负零（读起来像 bug） */
export function pctText(v, d = 2) {
  if (v == null || !Number.isFinite(+v)) return '—'
  const s = (+v).toFixed(d)
  const signed = /^-0\.?0*$/.test(s) ? s.slice(1) : s     // -0.00 → 0.00
  return `${signed}%`
}

