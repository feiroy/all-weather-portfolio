// 时间轴：日 / 月 / 年线的聚合与区间截取。
// 口径与 Streamlit 版 _trend_aggregate 一致：月/年线只取该期最后一条**真实记录**，
// 不伪造期末日期（未结束的期间按最新数据算）。

// 区间标签：全站唯一一份，顺序 / 文案与 Python 版 iframe 图表 _TREND_RANGES 完全一致。
// 任何「有时间段类型」的曲线都必须用这一份，禁止各页面自己写数组（历史上写成了「今年」、
// 少了「近6月 / 近3年 / 近5年」，同一个按钮在不同页面跳出来的区间长度都不一样）。
export const RANGE_KEYS = ['近1月', '近3月', '近6月', '近1年', '近3年', '近5年', '今年来', '全部']

const RANGE_SPAN = {
  '近1月': ['months', 1], '近3月': ['months', 3], '近6月': ['months', 6],
  '近1年': ['years', 1], '近3年': ['years', 3], '近5年': ['years', 5],
  '今年来': ['ytd', 0], '全部': ['all', 0],
}

export function aggregate(dates, values, period = '日') {
  if (!dates?.length) return { dates: [], values: [], labels: [] }
  if (period === '日') return { dates: [...dates], values: [...values], labels: [...dates] }
  const keyOf = d => (period === '月' ? d.slice(0, 7) : d.slice(0, 4))
  const out = { dates: [], values: [], labels: [] }
  for (let i = 0; i < dates.length; i++) {
    const k = keyOf(dates[i])
    const next = i + 1 < dates.length ? keyOf(dates[i + 1]) : null
    if (k === next) continue                 // 还不是这一期最后一条
    const [y, m] = dates[i].split('-')
    out.dates.push(dates[i])                 // 真实记录日期，给 tooltip 用
    out.values.push(values[i])
    out.labels.push(period === '月' ? `${y}年${+m}月` : `${y}年`)
  }
  return out
}

// 往前推 N 个自然月，日期溢出时收到当月最后一天（3/31 往前一月 = 2/28，9/30 往前一月 = 8/30）。
// 不用 Date.setMonth：它会溢出成 3/3，而且 toISOString 在 UTC+8 下还会整体差一天。
function minusMonths(iso, m) {
  const [y, mo, d] = iso.split('-').map(Number)
  const t = new Date(y, mo - 1 - m, 1)
  const y2 = t.getFullYear(), m2 = t.getMonth() + 1
  const dim = new Date(y2, m2, 0).getDate()
  return `${y2}-${String(m2).padStart(2, '0')}-${String(Math.min(d, dim)).padStart(2, '0')}`
}

// 区间基准条目下标（含该条）——与 iframe 图表 _trend_window_start 同口径：
// 近N月/年 = 截止日往前推 N 个自然月/年那天（或之前最近一个交易日）；
// 今年来 = 去年最后一个交易日（不是今年第一天，否则漏掉第一天涨跌）；全部 = 0。
// 返回的下标同时用作「累计收益 = 0%」的锚点，所以曲线平移回更早历史时口径不变。
export function rangeStartIndex(dates, rangeKey) {
  const n = dates?.length || 0
  if (!n) return 0
  const [kind, amount] = RANGE_SPAN[rangeKey] || ['all', 0]
  if (kind === 'all') return 0
  const end = dates[n - 1]
  let target
  if (kind === 'ytd') target = `${end.slice(0, 4)}-01-01`
  else if (kind === 'months') target = minusMonths(end, amount)
  else target = minusMonths(end, amount * 12)
  // 最后一个 <= target 的记录；数据不够长就从头开始
  let i = dates.findIndex(d => d > target)
  if (i < 0) i = n - 1
  return Math.max(0, i - 1)
}

export function sliceRange(dates, values, rangeKey) {
  if (!dates?.length) return { dates: [], values: [] }
  const i = rangeStartIndex(dates, rangeKey)
  return { dates: dates.slice(i), values: values.slice(i) }
}

// 区间内首值 → 末值的涨跌幅（%）；空序列返回 null
export function rangeReturn(values) {
  const v = (values || []).filter(x => x != null && Number.isFinite(+x))
  return v.length > 1 && +v[0] ? (+v[v.length - 1] / +v[0] - 1) * 100 : null
}

// ---------------------------------------------------------------- 多序列（对比 / 回测）
// 日期并集升序：多折线图的横轴口径，窗口下标也必须按这条轴算，否则 dataZoom 百分比会错位。
export function unionDates(series) {
  return [...new Set(Object.values(series || {}).flatMap(s => s?.dates || []))].sort()
}

// 每条线各自按日/月/年聚合（月、年只取该期最后一条真实记录），保持 { 名字: {dates, ret, labels} }
export function aggregateSeries(series, period = '日') {
  const p = period === '月线' ? '月' : period === '年线' ? '年' : '日'
  const out = {}
  for (const [k, s] of Object.entries(series || {})) {
    const a = aggregate(s.dates || [], s.ret || [], p)
    out[k] = { dates: a.dates, ret: a.values, labels: a.labels }
  }
  return out
}

// 以「基准下标」为 0%：换区间后曲线要能直接读出「这段时间涨跌多少」，
// 否则 Y 轴还是从 2019 年起的累计收益（79%~110%），区间内的差别被压成几条平行线。
// 注意换算用 (1+r_t)/(1+r_b)-1，不能直接相减：79.30% → 87.43% 的真实涨幅是 +4.53%，
// 相减会得到 8.13pp，差一倍。
export function rebaseSeries(series, axis, baseIdx) {
  const ax = axis || []
  if (!ax.length) return series || {}
  const bi = Math.max(0, Math.min(ax.length - 1, Math.round(baseIdx || 0)))
  const out = {}
  for (const [k, s] of Object.entries(series || {})) {
    const m = new Map(s.dates.map((d, i) => [d, s.ret[i]]))
    let base = null
    for (let i = ax.indexOf(ax[bi]); i >= 0; i--) {
      const v = m.get(ax[i])
      if (v != null && Number.isFinite(+v)) { base = +v; break }
    }
    if (base == null || Math.abs(1 + base / 100) < 1e-9) { out[k] = s; continue }
    out[k] = { dates: s.dates, labels: s.labels,
      ret: s.ret.map(v => (v == null || !Number.isFinite(+v)) ? v : ((1 + v / 100) / (1 + base / 100) - 1) * 100) }
  }
  return out
}

// 统一区间 → 多折线图的可见窗口 [起, 止]（并集日期轴上的下标）
export function windowForRange(dates, rangeKey) {
  const n = (dates || []).length
  if (n < 2) return [0, Math.max(0, n - 1)]
  return [rangeStartIndex(dates, rangeKey), n - 1]
}
