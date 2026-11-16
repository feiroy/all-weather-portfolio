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
// 份额 / 股数：场外固定 2 位；场内本来整手，用 0 位即可 —— 但真出现小数就别藏。
// 按金额反推股数会得到 199.8003 这种，一律 0 位会显示成「200」，看着像整手，
// 对账时却跟券商差 0.2 股（2026-11-16 用户就以为已经改成了 200 股）。
export const qty = (v, unit) => money(v, unit === '股' ? (Number.isInteger(Number(v)) ? 0 : 2) : 2)
