<template>
  <div class="page no-tab">
    <SubBar title="收益明细" :fallback="`/a/${aid}`" />
    <div class="wrap">
      <van-skeleton v-if="!d" title :row="10" style="padding:16px" />
      <van-empty v-else-if="!d.dates.length" description="还没有收益数据，先记一笔买入" />
      <div v-else class="cols2 even">
        <div>
          <!-- 走势 -->
          <div class="card">
            <div class="ch">
              <div><div class="k">{{ rangeK }}{{ unit === '%' ? '收益率' : '收益' }}</div>
                <b class="num big" :class="tone(segRet)">{{ unit === '%' ? pct(segRet) : signed(segRet) }}</b></div>
              <span class="seg2"><button :class="{ on: unit === '%' }" @click="unit = '%'">收益率</button>
                <button :class="{ on: unit === '¥' }" @click="unit = '¥'">金额</button></span>
            </div>
            <div class="chips rr"><span v-for="r in ranges" :key="r" class="chip" :class="{ on: rangeK === r }" @click="rangeK = r">{{ r }}</span></div>
            <LineChart :dates="seg.dates" :values="seg.values" :height="220" :unit="unit === '%' ? '%' : ''" zero
                       :fmt-tip="i => `${seg.dates[i]}<br/><b>${unit === '%' ? pct(seg.values[i]) : signed(seg.values[i]) + ' 元'}</b>`" />
            <p class="note">收益率 = 持有收益 ÷ 投入本金；区间收益从区间前一天收盘算起</p>
          </div>
        </div>
        <div>
          <!-- 收益日历 -->
          <div class="card cal">
            <div class="ch">
              <span class="seg2"><button v-for="m in ['日', '月', '年']" :key="m" :class="{ on: mode === m }" @click="mode = m">{{ m }}</button></span>
              <div class="nav" v-if="mode !== '年'">
                <van-icon name="arrow-left" @click="step(-1)" :class="{ dis: !canStep(-1) }" />
                <b class="num">{{ mode === '日' ? `${cur.y}年${cur.m}月` : `${cur.y}年` }}</b>
                <van-icon name="arrow" @click="step(1)" :class="{ dis: !canStep(1) }" />
              </div>
              <span class="seg2"><button :class="{ on: cu === '¥' }" @click="cu = '¥'">¥</button><button :class="{ on: cu === '%' }" @click="cu = '%'">%</button></span>
            </div>
            <div class="sumline" v-if="mode !== '年'">
              {{ mode === '日' ? '本月' : '本年' }}收益 <b class="num" :class="tone(curSum.v)">{{ signed(curSum.v) }}</b>
              <b class="num" :class="tone(curSum.p)">{{ pct(curSum.p) }}</b>
            </div>
            <template v-if="mode === '日'">
              <div class="wk"><span v-for="w in '一二三四五六日'" :key="w">{{ w }}</span></div>
              <div class="grid7">
                <div v-for="(c, k) in dayCells" :key="k" class="cell" :class="[c && c.v != null ? (c.v > 0 ? 'pos' : c.v < 0 ? 'neg' : '') : '', { sel: c && c.date === sel, empty: !c }]"
                     @click="c && c.v != null && (sel = c.date)">
                  <template v-if="c"><span class="dd">{{ c.d }}</span><span class="dv num">{{ c.v == null ? '' : cu === '¥' ? short(c.v) : pctS(c.p) }}</span></template>
                </div>
              </div>
            </template>
            <div v-else class="grid3">
              <div v-for="c in periodCells" :key="c.key" class="cell big" :class="c.v == null ? 'empty' : c.v > 0 ? 'pos' : c.v < 0 ? 'neg' : ''"
                   @click="c.v != null && drill(c)">
                <span class="dd">{{ c.label }}</span><span class="dv num">{{ c.v == null ? '—' : cu === '¥' ? signed(c.v, 0) : pct(c.p) }}</span>
              </div>
            </div>
          </div>
          <!-- 选中那天：每只基金赚了多少 -->
          <div class="card det" v-if="mode === '日' && sel && d.detail[sel]">
            <div class="ch"><b class="num">{{ sel.replace(/-/g, '/') }} 收益</b>
              <b class="num" :class="tone(selDay)">{{ signed(selDay) }}</b></div>
            <div v-for="r in d.detail[sel]" :key="r[0]" class="drow" @click="$router.push(`/a/${aid}/fund/${r[0]}`)">
              <div class="dn"><div>{{ d.funds[r[0]] || r[0] }}</div>
                <small>{{ r[0] }}<span v-if="r[4]" class="tag" :class="r[4] === '买入' ? 'buy' : 'sell'">{{ r[4] }}</span>
                  <span v-if="r[3]" class="tag gray">{{ r[3] }}</span></small></div>
              <div class="dv2"><b class="num" :class="tone(r[1])">{{ signed(r[1]) }}</b><small class="num" :class="tone(r[2])">{{ r[2] == null ? '—' : pct(r[2]) }}</small></div>
            </div>
            <p class="note">「待更新」= 场外基金当天净值还没出，按 0 计；出了以后点更新数据就会补上</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { get, peek, dataVer } from '../api'
import { money, signed, pct, tone } from '../fmt'
import SubBar from '../components/SubBar.vue'
import LineChart from '../components/LineChart.vue'

const aid = useRoute().params.aid
const url = `/api/acct/${aid}/period`
const d = ref(peek(url) || null)
const load = async (fresh = false) => { d.value = await get(url, { fresh }) }
load(); watch(dataVer, () => load(true))

// ---------- 走势
const unit = ref('%'), rangeK = ref('全部')
const ranges = ['近1月', '近3月', '今年', '全部']
const seg = computed(() => {
  const x = d.value
  const last = x.dates[x.dates.length - 1]
  let s = x.dates[0]
  if (rangeK.value === '今年') s = last.slice(0, 4) + '-01-01'
  else if (rangeK.value !== '全部') {
    const t = new Date(last); t.setMonth(t.getMonth() - (rangeK.value === '近1月' ? 1 : 3)); s = t.toISOString().slice(0, 10)
  }
  // 区间从「起点前一天」算起：第一个点是 0
  let i0 = x.dates.findIndex(v => v >= s); i0 = Math.max(0, i0 - 1)
  const n0 = x.nav[i0], p0 = x.pnl[i0]
  const dates = x.dates.slice(i0)
  const values = unit.value === '%' ? x.nav.slice(i0).map(v => (v / n0 - 1) * 100) : x.pnl.slice(i0).map(v => v - p0)
  if (rangeK.value === '全部') return { dates, values: unit.value === '%' ? x.nav.map(v => (v - 1) * 100) : x.pnl }
  return { dates, values }
})
const segRet = computed(() => seg.value.values[seg.value.values.length - 1])

// ---------- 日历
const mode = ref('日'), cu = ref('¥')
const lastD = computed(() => d.value.dates[d.value.dates.length - 1])
const cur = ref({ y: 0, m: 0 })
const sel = ref('')
watch(d, x => {
  if (!x || !x.dates.length || cur.value.y) return
  const l = x.dates[x.dates.length - 1]
  cur.value = { y: +l.slice(0, 4), m: +l.slice(5, 7) }
  sel.value = l
}, { immediate: true })
// 每天：收益 ¥ 和 收益率（相对本金的指数，当日涨跌）
const byDay = computed(() => {
  const m = new Map(), x = d.value
  x.dates.forEach((dt, i) => m.set(dt, { v: x.day[i], p: i ? (x.nav[i] / x.nav[i - 1] - 1) * 100 : null, i }))
  return m
})
// 期间（月 / 年）：¥ = 当期每天收益之和；% = 期末指数 ÷ 上期末指数 − 1（保留期首相对上期末的涨跌）
function periodStat(prefix) {
  const x = d.value
  const idx = x.dates.map((dt, i) => (dt.startsWith(prefix) ? i : -1)).filter(i => i >= 0)
  if (!idx.length) return { v: null, p: null }
  const a = idx[0], b = idx[idx.length - 1]
  const base = a > 0 ? x.nav[a - 1] : x.nav[a]
  const v = idx.reduce((s, i) => s + (x.day[i] || 0), 0)
  return { v, p: (x.nav[b] / base - 1) * 100 }
}
const pad = n => String(n).padStart(2, '0')
const dayCells = computed(() => {
  const { y, m } = cur.value
  const first = new Date(y, m - 1, 1), n = new Date(y, m, 0).getDate()
  const lead = (first.getDay() + 6) % 7
  const out = Array(lead).fill(null)
  for (let k = 1; k <= n; k++) {
    const date = `${y}-${pad(m)}-${pad(k)}`, s = byDay.value.get(date)
    out.push({ d: k, date, v: s ? s.v : null, p: s ? s.p : null })
  }
  return out
})
const periodCells = computed(() => {
  const x = d.value
  if (mode.value === '月') return Array.from({ length: 12 }, (_, k) => ({ key: k, label: `${k + 1}月`, y: cur.value.y, m: k + 1, ...periodStat(`${cur.value.y}-${pad(k + 1)}`) }))
  const ys = [...new Set(x.dates.map(v => +v.slice(0, 4)))]
  return ys.map(y => ({ key: y, label: `${y}年`, y, ...periodStat(String(y)) }))
})
const curSum = computed(() => periodStat(mode.value === '日' ? `${cur.value.y}-${pad(cur.value.m)}` : String(cur.value.y)))
const months = computed(() => [...new Set(d.value.dates.map(v => v.slice(0, 7)))])
function canStep(k) {
  const { y, m } = cur.value
  if (mode.value === '日') { const t = new Date(y, m - 1 + k, 1); const key = `${t.getFullYear()}-${pad(t.getMonth() + 1)}`; return months.value.includes(key) }
  return months.value.some(v => +v.slice(0, 4) === y + k)
}
function step(k) {
  if (!canStep(k)) return
  const { y, m } = cur.value
  if (mode.value === '日') { const t = new Date(y, m - 1 + k, 1); cur.value = { y: t.getFullYear(), m: t.getMonth() + 1 } }
  else cur.value = { y: y + k, m }
}
function drill(c) { if (mode.value === '年') { cur.value = { y: c.y, m: cur.value.m }; mode.value = '月' } else { cur.value = { y: c.y, m: c.m }; mode.value = '日' } }
const selDay = computed(() => byDay.value.get(sel.value)?.v)
const short = v => { const a = Math.abs(v); const s = a >= 10000 ? (a / 10000).toFixed(1) + '万' : a >= 1000 ? Math.round(a) : a.toFixed(a >= 100 ? 0 : 1); return (v > 0 ? '+' : v < 0 ? '-' : '') + s }
const pctS = p => (p == null ? '' : (p > 0 ? '+' : '') + p.toFixed(2) + '%')
void money
</script>
<style scoped>
.ch{ display:flex; justify-content:space-between; align-items:center; gap:8px; }
.k{ font-size:12px; color:var(--muted); }
.big{ font-size:24px; font-weight:700; }
.rr{ padding:10px 0 4px; }
.note{ font-size:11.5px; color:var(--muted); margin:6px 0 0; line-height:1.6; }
.nav{ display:flex; align-items:center; gap:4px; font-size:14.5px; white-space:nowrap; }
.nav .van-icon{ cursor:pointer; padding:4px; } .nav .dis{ opacity:.25; cursor:default; }
.sumline{ font-size:12.5px; color:var(--sub); margin:10px 0 4px; display:flex; gap:10px; align-items:baseline; }
.sumline b{ font-size:14px; }
.wk{ display:grid; grid-template-columns:repeat(7,1fr); font-size:11px; color:var(--muted); text-align:center; margin:8px 0 4px; }
.grid7{ display:grid; grid-template-columns:repeat(7,1fr); gap:4px; }
.grid3{ display:grid; grid-template-columns:repeat(3,1fr); gap:6px; margin-top:10px; }
.cell{ border-radius:8px; background:#F7F8FA; min-height:46px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:2px; cursor:pointer; border:1.5px solid transparent; }
.cell.big{ min-height:58px; }
.cell.empty{ background:transparent; cursor:default; }
.cell.pos{ background:#FDECEC; } .cell.pos .dv{ color:var(--up); }
.cell.neg{ background:#E7F6EC; } .cell.neg .dv{ color:var(--down); }
.cell.sel{ border-color:var(--brand); }
.dd{ font-size:11.5px; color:var(--sub); } .dv{ font-size:11px; font-weight:600; }
.cell.big .dd{ font-size:12.5px; } .cell.big .dv{ font-size:13px; }
.det .ch{ padding-bottom:8px; border-bottom:1px solid var(--line); font-size:15px; }
.drow{ display:flex; justify-content:space-between; align-items:center; padding:10px 0; border-bottom:1px solid var(--line); cursor:pointer; }
.drow:last-of-type{ border-bottom:0; }
.dn{ min-width:0; font-size:14px; } .dn small{ display:flex; gap:4px; align-items:center; font-size:11.5px; color:var(--muted); margin-top:2px; }
.dv2{ text-align:right; } .dv2 b{ display:block; font-size:14.5px; } .dv2 small{ font-size:12px; }
</style>
