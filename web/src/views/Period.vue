<template>
  <div class="page no-tab">
    <SubBar title="收益明细" :fallback="`/a/${aid}`" />
    <div class="wrap">
      <van-skeleton v-if="!d" title :row="10" style="padding:16px" />
      <van-empty v-else-if="!d.dates.length" description="还没有收益数据，先记一笔买入" />
      <template v-else>
        <!-- 曲线和日历同属一张卡：不存在「上下两张卡不一样宽」，也不用往两侧塞东西 -->
        <div class="card trend">
          <div class="ch">
            <!-- 不再放「收益率/金额」开关：曲线固定看收益率，tooltip 里同时给收益率和收益金额 -->
            <div><div class="k">{{ rangeK }}收益率</div>
              <b class="num big" :class="tone(segRet)">{{ pct(segRet) }}</b></div>
          </div>
          <RangeBar :range="rangeK" :period="period" :periods="periods"
                    @update:range="setRange" @update:period="p => period = p" />
          <p v-if="visCount < 2" class="sparse">{{ period }}在{{ rangeK }}只有 {{ visCount }} 期数据（账户 {{ firstYear }} 年建立），看走势请切到月线或日线</p>
          <LineChart :dates="chart.dates" :values="chart.values" :labels="chart.labels" :height="220" unit="%" zero
                     :window="win" :reset-key="resetKey"
                     :fmt-tip="i => tipRows(dateText(chart.dates[i]), [
                       ['收益率', pct(chart.values[i])],
                       ['收益金额', pnlOf(chart.dates[i]) == null ? '—' : signed(pnlOf(chart.dates[i]), 0) + ' 元'],
                     ])" />
          <p class="note">收益率 = 持有收益 ÷ 投入本金；区间收益从区间基准日收盘算起。滑动或按住拖动平移（可向左拖出区间外的历史），⌘/Ctrl + 滑动缩放，双击复位到当前区间</p>

          <div class="trend-div"></div>

          <div class="cal">
            <div class="cal-inner">
              <div class="ch">
                <span class="seg2"><button v-for="m in ['日', '月', '年']" :key="m" :class="{ on: mode === m }" @click="mode = m">{{ m }}</button></span>
                <div class="nav" v-if="mode !== '年'">
                  <van-icon name="arrow-left" @click="step(-1)" :class="{ dis: !canStep(-1) }" />
                  <b class="num">{{ mode === '日' ? `${cur.y}年${cur.m}月` : `${cur.y}年` }}</b>
                  <van-icon name="arrow" @click="step(1)" :class="{ dis: !canStep(1) }" />
                </div>
                <span class="seg2"><button :class="{ on: cu === '¥' }" @click="cu = '¥'">¥</button><button :class="{ on: cu === '%' }" @click="cu = '%'">%</button></span>
              </div>
              <div class="sumline">
                {{ mode === '日' ? '本月' : mode === '年' ? cur.y + '年' : '本年' }}收益 <b class="num" :class="tone(curSum.v)">{{ signed(curSum.v) }}</b>
                <b class="num" :class="tone(curSum.p)">{{ pct(curSum.p) }}</b>
              </div>
              <p v-if="mode !== '日'" class="cal-note">账户自 {{ firstDate }} 起有数据，更早的期间显示「—」；点有数据的格子可下钻</p>
              <template v-if="mode === '日'">
                <div class="wk"><span v-for="w in '一二三四五六日'" :key="w">{{ w }}</span></div>
                <div class="grid7">
                  <div v-for="(c, k) in dayCells" :key="k" class="cell" :class="[c ? (c.v == null ? 'none' : c.v > 0 ? 'pos' : c.v < 0 ? 'neg' : '') : '', { sel: c && c.date === sel, empty: !c }]"
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
              <p class="cal-tip" v-if="mode === '日'">点日历里任意一天，下面展开每只基金各赚多少</p>
            </div>
          </div>
        </div>
        <!-- 选中那天：每只基金赚了多少（点选后才出现，单独一张卡） -->
        <div class="card det" v-if="sel && d.detail[sel]">
          <div class="ch"><b class="num">{{ sel.replace(/-/g, '/') }} 收益</b>
            <div class="dv2">
              <b class="num" :class="tone(selDay)">{{ signed(selDay) }}</b>
              <small class="num" :class="tone(selPct)">{{ selPct == null ? '—' : pct(selPct) }}</small>
            </div></div>
          <p v-if="mode !== '日'" class="det-note">这是上面所选那天的每只基金明细；切回「日」点日历格子可换一天</p>
          <div v-for="r in d.detail[sel]" :key="r[0]" class="drow" @click="$router.push(`/a/${aid}/fund/${r[0]}`)">
            <div class="dn"><div>{{ d.funds[r[0]] || r[0] }}</div>
              <small>{{ r[0] }}<span v-if="r[4]" class="tag" :class="r[4] === '买入' ? 'buy' : 'sell'">{{ r[4] }}</span>
                <span v-if="r[3]" class="tag gray">{{ r[3] }}</span></small></div>
            <div class="dv2"><b class="num" :class="tone(r[1])">{{ signed(r[1]) }}</b><small class="num" :class="tone(r[2])">{{ r[2] == null ? '—' : pct(r[2]) }}</small></div>
          </div>
          <p class="note">「待更新」= 场外基金当天净值还没出，按 0 计；出了以后点更新数据就会补上</p>
        </div>
      </template>
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
import RangeBar from '../components/RangeBar.vue'
import { tipRows } from '../utils/chartTheme'
import { dateText } from '../utils/chartAxis'
import { aggregate, rangeStartIndex, RANGE_KEYS } from '../utils/series'

const aid = useRoute().params.aid
const url = `/api/acct/${aid}/period`
const d = ref(peek(url) || null)
const load = async (fresh = false) => { d.value = await get(url, { fresh }) }
load(); watch(dataVer, () => load(true))

// ---------- 走势
// 数据给全历史、区间只决定初始视窗：和基金详情 iframe 图表一样，往左能拖出区间外的历史
const rangeK = ref('近1月')
const ranges = RANGE_KEYS
const periods = ['日线', '月线', '年线'], period = ref('日线')
const pchar = computed(() => period.value === '日线' ? '日' : period.value === '月线' ? '月' : '年')
// 点同一个区间也要复位视窗（拖走后再点当前区间，rangeK 没变不会触发 watch，所以要 bump）
const bump = ref(0)
const setRange = k => { rangeK.value = k; bump.value++ }
const resetKey = computed(() => `${rangeK.value}|${period.value}|${bump.value}`)
// 区间起点 = 基准条目（今年来 = 去年最后一个交易日），收益率和收益金额都以它为 0
const baseIdx = computed(() => d.value ? rangeStartIndex(d.value.dates, rangeK.value) : 0)
const chart = computed(() => {
  const x = d.value
  if (!x) return { dates: [], values: [], labels: [] }
  const nav0 = x.nav[baseIdx.value]
  return aggregate(x.dates, x.nav.map(v => (v / nav0 - 1) * 100), pchar.value)
})
// tooltip 第二行：这一天相对区间基准日的累计盈亏金额
const pnlOf = (dt) => {
  const x = d.value
  if (!x) return null
  const i = x.dates.indexOf(dt)
  return i < 0 ? null : x.pnl[i] - x.pnl[baseIdx.value]
}

// 可见窗口（聚合后的下标，含首尾）：右端固定到最新，左端落在区间基准那条记录上
const win = computed(() => {
  const a = chart.value
  if (!d.value || !a.dates.length) return null
  const i = a.dates.findIndex(v => v >= d.value.dates[baseIdx.value])
  return [Math.max(0, i), a.dates.length - 1]
})
const visCount = computed(() => (win.value ? win.value[1] - win.value[0] + 1 : 0))
const segRet = computed(() => chart.value.values[chart.value.values.length - 1])
const firstYear = computed(() => d.value?.dates?.[0]?.slice(0, 4) || '')
const firstDate = computed(() => d.value?.dates?.[0]?.replace(/-/g, '/') || '')

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
// 选中那天的收益率：账户净值相对前一交易日的涨跌，与每只基金那行的 % 同一口径
const selPct = computed(() => byDay.value.get(sel.value)?.p)
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
.sparse{ font-size:12px; color:#92400E; background:#FFFBEB; border-radius:8px;
  padding:7px 10px; margin:0 0 8px; line-height:1.6; }
.cal-note, .det-note{ font-size:11.5px; color:var(--muted); line-height:1.6; margin:2px 0 6px; }
.det-note{ margin-top:8px; }
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
/* 有日期但那天没有净值：压淡底色，别让空格子铺满后抢走有收益那几天的注意力 */
.cell.none{ background:#FCFCFD; }
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

/* 曲线与日历在同一张卡里；日历是卡内一个居中的浅灰内嵌模块，不加任何两侧内容 */
.trend-div{ height:1px; background:var(--line); margin:16px 0 14px; }
.cal-tip{ font-size:11.5px; color:var(--muted); text-align:center; line-height:1.6; margin:12px 0 0; }
@media (min-width:900px){
  /* 日历铺满整张卡；格子变宽后同步加高、放大字号，避免变成一排扁横条 */
  .cal-inner{ max-width:none; margin:0; background:transparent; border:0; padding:0; }
  .cal .sumline{ justify-content:center; }
  .cal .wk{ font-size:12px; margin:10px 0 6px; }
  .cal .grid7{ gap:8px; }
  .cal .grid3{ gap:10px; }
  .cal .cell{ min-height:78px; border-radius:10px; gap:6px; }
  .cal .cell.big{ min-height:88px; }
  .cal .dd{ font-size:13px; } .cal .dv{ font-size:14px; }
  .cal .cell.big .dd{ font-size:14px; } .cal .cell.big .dv{ font-size:16px; }
}
</style>
