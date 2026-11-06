// 单只基金净值序列的派生指标：累计收益、回撤、区间统计、收益日历。
// 输入都是 /api/market/fund/{code} 返回的全量日频净值（按日期升序、已复权）。

const pad = n => String(n).padStart(2, '0')

// 相对区间起点的累计收益率（%），区间首点为 0
export function cumulativeReturn(values) {
  const base = values?.[0]
  if (!base) return []
  return values.map(v => (v / base - 1) * 100)
}

// 距历史最高点的回撤（%），恒 ≤ 0
export function drawdown(values) {
  let peak = -Infinity
  return (values || []).map(v => {
    peak = Math.max(peak, v)
    return peak > 0 ? (v / peak - 1) * 100 : 0
  })
}

// 区间统计：涨跌、最大回撤、年化（按真实日历跨度，点数很少时也不会失真）、年化波动
export function stats(values, dates) {
  const v = (values || []).filter(x => x != null && Number.isFinite(+x))
  if (v.length < 2 || !v[0]) return { ret: null, mdd: 0, cagr: null, vol: null }
  const n = v.length - 1
  const ret = (v[n] / v[0] - 1) * 100
  const mdd = Math.min(...drawdown(v))
  const rs = []
  for (let i = 1; i < v.length; i++) if (v[i - 1]) rs.push(v[i] / v[i - 1] - 1)
  const mean = rs.length ? rs.reduce((a, b) => a + b, 0) / rs.length : 0
  const varc = rs.length ? rs.reduce((a, b) => a + (b - mean) ** 2, 0) / rs.length : 0
  let years = null
  if (dates?.length > 1) {
    const days = (new Date(dates[dates.length - 1]) - new Date(dates[0])) / 86400000
    years = days / 365
  }
  return {
    ret,
    mdd,
    cagr: years > 0.02 ? (Math.pow(v[n] / v[0], 1 / years) - 1) * 100 : null,
    vol: Math.sqrt(varc * 252) * 100,
  }
}

// 收益日历：日 = 当月每日涨跌，月 = 当年每月涨跌，年 = 各年涨跌。
// 每期涨跌 = 该期最后一条净值 / 上一期最后一条净值 - 1（保留期首相对上期末）。
export function calendarCells(dates, values, mode, y, m) {
  if (!dates?.length) return { cells: [], months: [] }
  const months = [...new Set(dates.map(d => d.slice(0, 7)))]
  const keyOf = d => (mode === '月' ? d.slice(0, 7) : d.slice(0, 4))
  // 每期最后一条真实记录的索引
  const lastOf = {}
  dates.forEach((d, i) => { lastOf[keyOf(d)] = i })
  const keys = Object.keys(lastOf).sort()
  const prev = {}
  keys.forEach((k, i) => { prev[k] = i > 0 ? lastOf[keys[i - 1]] : null })

  if (mode === '日') {
    const first = new Date(y, m - 1, 1), n = new Date(y, m, 0).getDate()
    const lead = (first.getDay() + 6) % 7
    const cells = Array(lead).fill(null)
    for (let k = 1; k <= n; k++) {
      const date = `${y}-${pad(m)}-${pad(k)}`
      const i = dates.findIndex(d => d >= date)
      const exact = i >= 0 && dates[i] === date ? i : -1
      const p = exact > 0 && values[exact - 1] ? (values[exact] / values[exact - 1] - 1) * 100 : null
      cells.push({ d: k, date, p, v: p })
    }
    return { cells, months }
  }
  if (mode === '月') {
    return {
      months,
      cells: Array.from({ length: 12 }, (_, k) => {
        const key = `${y}-${pad(k + 1)}`
        const i = lastOf[key]
        const j = prev[key]
        const p = i != null && j != null && values[j] ? (values[i] / values[j] - 1) * 100 : null
        return { label: `${k + 1}月`, p, v: p }
      }),
    }
  }
  return {
    months,
    cells: keys.map(k => {
      const i = lastOf[k], j = prev[k]
      const p = j != null && values[j] ? (values[i] / values[j] - 1) * 100 : null
      return { label: `${k}年`, p, v: p }
    }),
  }
}
