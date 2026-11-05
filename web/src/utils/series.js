// 时间轴：日 / 月 / 年线的聚合与区间截取。
// 口径与 Streamlit 版 _trend_aggregate 一致：月/年线只取该期最后一条**真实记录**，
// 不伪造期末日期（未结束的期间按最新数据算）。

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

export function sliceRange(dates, values, rangeKey) {
  if (!dates?.length) return { dates: [], values: [] }
  const R = {
    '近1月': 1, '近3月': 3, '近6月': 6, '近1年': 12,
    '近3年': 36, '近5年': 60, '全部': 0,
  }
  if (rangeKey === '今年' || rangeKey === '今年来') {
    const i = Math.max(0, dates.findIndex(d => d >= `${dates[dates.length - 1].slice(0, 4)}-01-01`))
    return { dates: dates.slice(i), values: values.slice(i) }
  }
  const m = R[rangeKey] ?? 0
  if (!m) return { dates: [...dates], values: [...values] }
  const end = new Date(dates[dates.length - 1])
  end.setMonth(end.getMonth() - m)
  // 起点取「那天之前最近一条真实记录」，与支付宝历史业绩口径一致
  const s = end.toISOString().slice(0, 10)
  let i = dates.findIndex(d => d >= s)
  i = Math.max(0, i < 0 ? dates.length - 1 : i - 1)
  return { dates: dates.slice(i), values: values.slice(i) }
}

// 区间内首值 → 末值的涨跌幅（%）；空序列返回 null
export function rangeReturn(values) {
  const v = (values || []).filter(x => x != null && Number.isFinite(+x))
  return v.length > 1 && +v[0] ? (+v[v.length - 1] / +v[0] - 1) * 100 : null
}
