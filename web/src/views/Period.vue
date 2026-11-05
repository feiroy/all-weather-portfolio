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
            <div class="chips rr"><span v-for="r in ranges" :key="r" class="chip" :class="{ on: rangeK === r }" @click="rangeK = r">{{ r }}</span>
              <span class="seg2 per"><button v-for="p in periods" :key="p" :class="{ on: period === p }" @click="period = p">{{ p }}</button></span></div>
            <LineChart :dates="chart.dates" :values="chart.values" :labels="chart.labels" :height="220" :unit="unit === '%' ? '%' : ''" zero
                       :reset-key="rangeK + unit + period"
                       :fmt-tip="i => `${chart.dates[i].replace(/-/g, '/')}<br/><b>${unit === '%' ? pct(chart.values[i]) : signed(chart.values[i]) + ' 元'}</b>`" />
            <p class="note">收益率 = 持有收益 ÷ 投入本金；区间收益从区间前一天收盘算起。拖动平移、滚轮缩放、双击复位</p>
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
            <div class="cal-body" :class="{ 'with-side': mode === '日' }">
              <!-- 桌面：左侧填本月涨跌天数，避免日历缩在 460px 中间、两边大片留白 -->
              <div class="cal-side" v-if="mode === '日'">
                <div class="sh">本月交易日</div>
                <div class="srow"><span>上涨</span><b class="num up">{{ dayStat.up }} 天</b></div>
                <div class="srow"><span>下跌</span><b class="num down">{{ dayStat.down }} 天</b></div>
                <div class="srow"><span>持平</span><b class="num">{{ dayStat.flat }} 天</b></div>
                <div class="sbar"><i class="u" :style="{ width: dayStat.upPct + '%' }"></i><i class="d" :style="{ width: dayStat.downPct + '%' }"></i></div>
                <p class="sn">按账户口径的每日涨跌，不是单只基金</p>
              </div>
              <div class="cal-mid">
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
              <!-- 桌面：右侧填单日极值，同时告诉用户点格子能看明细 -->
              <div class="cal-side" v-if="mode === '日'">
                <div class="sh">单日波动</div>
                <div class="srow"><span>最好</span><b class="num" :class="tone(dayStat.best?.p)">{{ dayStat.best ? pctS(dayStat.best.p) : '—' }}</b></div>
                <div class="srow"><span>最差</span><b class="num" :class="tone(dayStat.worst?.p)">{{ dayStat.worst ? pctS(dayStat.worst.p) : '—' }}</b></div>
                <div class="srow"><span>最好那天</span><b class="num">{{ dayStat.best?.date?.slice(5).replace('-', '/') || '—' }}</b></div>
                <p class="sn">点日历里任意一天，下面展开每只基金各赚多少</p>
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
import { aggregate } from '../utils/series'

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
const periods = ['日线', '月线', '年线'], period = ref('日线')
const chart = computed(() => aggregate(seg.value.dates, seg.value.values,
  period.value === '日线' ? '日' : period.value === '月线' ? '月' : '年'))

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
// 日历两侧的月度概览：涨跌天数 + 单日极值（只统计有数据的交易日）
const dayStat = computed(() => {
  const cs = dayCells.value.filter(c => c && c.v != null)
  const up = cs.filter(c => c.v > 0), down = cs.filter(c => c.v < 0)
  const ext = (cmp, init) => cs.reduce((m, c) => m == null || cmp(c.p ?? 0, m.p ?? 0) ? c : m, init)
  return {
    up: up.length, down: down.length, flat: cs.length - up.length - down.length,
    upPct: cs.length ? up.length / cs.length * 100 : 0,
    downPct: cs.length ? down.length / cs.length * 100 : 0,
    best: ext((a, b) => a > b, null), worst: ext((a, b) => a < b, null),
  }
})
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
.rr{ padding:10px 0 4px; flex-wrap:wrap; align-items:center; }
.per{ margin-left:auto; }
.note{ font-size:11.5px; color:var(--muted); margin:6px 0 0; line-height:1.6; }
.nav{ display:flex; align-items:center; gap:4px; font-size:14.5px; white-space:nowrap; }
.cal .ch{ flex-wrap:wrap; row-gap:8px; }
/* 窄屏（≤400）：月份切换单独占一行居中，两个切换按钮在下一行左右排 */
@media (max-width:400px){ .cal .ch .nav{ order:-1; flex-basis:100%; justify-content:center; } }
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

/* 桌面：日历卡外框与上方曲线卡同宽（936），两侧留白用月度概览填上，不再让日历孤零零居中 */
.cal-side{ display:none; }
@media (min-width:900px){
  .cal .sumline{ justify-content:center; }
  .cal-body.with-side{ display:grid; grid-template-columns:1fr 460px 1fr; gap:16px; align-items:start; }
  .cal-body:not(.with-side){ max-width:460px; margin:0 auto; }
  .cal-side{ display:block; background:#F8FAFC; border-radius:10px; padding:12px 14px; }
  .cal-side .sh{ font-size:12px; color:var(--muted); margin-bottom:8px; }
  .cal-side .srow{ display:flex; justify-content:space-between; align-items:baseline; padding:5px 0; font-size:12.5px; color:var(--sub); }
  .cal-side .srow b{ font-size:15px; }
  .cal-side .sbar{ display:flex; height:6px; border-radius:3px; overflow:hidden; background:#E9EBEF; margin-top:10px; }
  .cal-side .sbar i{ display:block; height:100%; }
  .cal-side .sbar .u{ background:var(--up); } .cal-side .sbar .d{ background:var(--down); }
  .cal-side .sn{ font-size:11px; color:var(--muted); line-height:1.6; margin:10px 0 0; }
}
</style>
