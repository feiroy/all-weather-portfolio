// 数字格式：0 不写正负号；涨红跌绿（A 股习惯）
export const money = (v, d = 2) => v == null ? '—'
  : Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d })
export const signed = (v, d = 2) => {
  if (v == null) return '—'
  if (Math.abs(v) < 0.5 * 10 ** -d) return (0).toFixed(d)
  return (v > 0 ? '+' : '') + money(v, d)
}
export const pct = (v, d = 2) => v == null ? '—' : signed(v, d) + '%'
export const tone = (v) => v == null || Math.abs(v) < 1e-9 ? '' : v > 0 ? 'up' : 'down'
