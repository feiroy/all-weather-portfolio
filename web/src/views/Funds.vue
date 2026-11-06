<template>
  <div class="page no-tab">
    <SubBar title="基金检索" :fallback="`/a/${aid}/market`" />
    <div class="wrap">
      <!-- 搜索：输入时只显示结果，选定后回到下面的完整走势，全都在这一页 -->
      <van-search v-model="q" placeholder="基金名称或 6 位代码，比如 沪深300 / 000961" shape="round" class="sb" />
      <van-cell-group inset v-if="q.trim() && rows.length">
        <van-cell v-for="r in rows" :key="r.code" :title="r.name" :label="r.code" clickable @click="select(r)">
          <template #value><span class="src">{{ r.src }}</span></template>
        </van-cell>
      </van-cell-group>
      <p v-else-if="q.trim()" class="empty-tip">没找到。试试换个关键词，或直接输入 6 位代码</p>

      <template v-if="!q.trim()">
        <div class="recent" v-if="recent.length">
          <span class="rl">最近看过</span>
          <span v-for="r in recent" :key="r.code" class="chip" :class="{ on: r.code === code }" @click="select(r)">{{ shortName(r.name) }}</span>
          <a class="clr" @click="clearRecent">清空</a>
        </div>

        <van-loading v-if="!d && !err" style="margin:30px 0" vertical>拉取净值…（第一次查要几秒）</van-loading>
        <p v-else-if="err" class="empty-tip">{{ err }}</p>
        <template v-else>
          <!-- 基金概览 -->
          <div class="card head">
            <div class="hn"><b>{{ d.name }}</b><span class="num">{{ code }}</span></div>
            <div class="g">
              <div><span>最新单位净值</span><b class="num">{{ last?.toFixed(4) }}</b></div>
              <div><span>单日</span><b class="num" :class="tone(dayPct)">{{ pctS(dayPct) }}</b></div>
              <div><span>截至</span><b class="num">{{ d.dates[d.dates.length - 1].replace(/-/g, '/') }}</b></div>
              <div><span>区间收益</span><b class="num" :class="tone(stat.ret)">{{ pctS(stat.ret) }}</b></div>
            </div>
            <p class="src-line">{{ d.msg }}</p>
          </div>

          <!-- 阶段表现：固定区间，不受下面图表拖动影响 -->
          <div class="card">
            <div class="st">阶段表现 <span>基准日净值 → 最新净值，同支付宝历史业绩口径</span></div>
            <div class="stage-grid">
              <div v-for="s in stageRows" :key="s.k"><span>{{ s.k }}</span><b class="num" :class="tone(s.ret)">{{ pctS(s.ret) }}</b></div>
            </div>
          </div>

          <!-- 三张走势图 + 区间统计 -->
          <div class="card">
            <div class="chips rr">
              <span v-for="r in ranges" :key="r" class="chip" :class="{ on: range === r }" @click="range = r">{{ r }}</span>
              <span class="seg2 per"><button v-for="p in periods" :key="p" :class="{ on: period === p }" @click="period = p">{{ p }}</button></span>
            </div>
            <div class="stat-row">
              <div><span>最大回撤</span><b class="num down">{{ stat.mdd?.toFixed(2) }}%</b></div>
              <div><span>年化</span><b class="num" :class="tone(stat.cagr)">{{ pctS(stat.cagr) }}</b></div>
              <div><span>年化波动</span><b class="num">{{ stat.vol?.toFixed(2) }}%</b></div>
              <div><span>数据点</span><b class="num">{{ chart.dates.length }}</b></div>
            </div>
            <p v-if="chart.dates.length < 2" class="sparse">当前区间按{{ period }}只有 {{ chart.dates.length }} 期数据，看走势请切到日线或月线</p>
            <div class="st sub">单位净值走势</div>
            <LineChart :dates="chart.dates" :values="chart.values" :labels="chart.labels" :height="220" unit=""
                       :reset-key="range + period" :fmt-tip="i => tip(i, chart, 4, '')" />
            <div class="st sub">累计收益走势 <span>区间起点 = 0%</span></div>
            <LineChart :dates="retChart.dates" :values="retChart.values" :labels="retChart.labels" :height="170" unit="%" zero
                       :reset-key="range + period" :fmt-tip="i => tip(i, retChart, 2, '%')" />
            <div class="st sub">回撤曲线 <span>距区间内历史最高点</span></div>
            <LineChart :dates="ddChart.dates" :values="ddChart.values" :labels="ddChart.labels" :height="160" unit="%" zero
                       :reset-key="range + period" :fmt-tip="i => tip(i, ddChart, 2, '%')" />
            <p class="k">双指/滚轮滑动或按住拖动平移 · ⌘/Ctrl + 滑动缩放 · 双击复位；月/年线取每期最后一条真实记录</p>
          </div>

        <!-- 多只对比：紧跟三张走势图，默认展开；与单只走势同页，不做二级菜单 -->
        <van-collapse v-model="cmpOpen" class="cmpbox">
          <van-collapse-item title="多只基金同图对比" name="c">
            <div class="cmp">
              <div class="chips picked" v-if="picked.length">
                <span v-for="p in picked" :key="p.code" class="chip on" @click="drop(p.code)">{{ shortName(p.name) }} ×</span>
              </div>
              <van-search v-model="cq" placeholder="搜索基金加入对比（最多 4 只）" shape="round" />
              <van-cell-group inset v-if="opts.length">
                <van-cell v-for="r in opts" :key="r.code" :title="r.name" :label="r.code" clickable @click="pick(r)">
                  <template #value><van-icon name="plus" /></template>
                </van-cell>
              </van-cell-group>
              <template v-if="picked.length >= 2">
                <div class="chips rr">
                  <span v-for="r in cmpRanges" :key="r.k" class="chip" :class="{ on: cmpRange === r.k }" @click="cmpRange = r.k">{{ r.k }}</span>
                  <span class="seg2 per"><button v-for="p in periods" :key="p" :class="{ on: cmpPeriod === p }" @click="cmpPeriod = p">{{ p }}</button></span>
                </div>
                <div class="st sub">相对起点涨跌幅 <span>区间首值 = 0%</span></div>
                <MultiLine :series="cmpSeries" :height="240" />
                <div class="st sub">单期涨跌 <span>每{{ cmpPeriod === '日线' ? '日' : cmpPeriod === '月线' ? '月' : '年' }}相对上一期</span></div>
                <MultiLine :series="periodSeries" :height="170" />
                <div class="st sub">阶段表现 <span>各基金固定区间涨跌，与图表视窗无关</span></div>
                <div class="stage-tbl-wrap">
                  <table class="stage-tbl">
                    <thead><tr><th>基金</th><th v-for="k in cmpStageKeys" :key="k">{{ k }}</th></tr></thead>
                    <tbody><tr v-for="row in cmpStageRows" :key="row.name">
                      <td>{{ row.name }}</td>
                      <td v-for="(v, k) in row.vals" :key="k" class="num" :class="tone(v)">{{ pctS(v) }}</td>
                    </tr></tbody>
                  </table>
                </div>
              </template>
              <p v-else class="empty-tip">再选 {{ Math.max(0, 2 - picked.length) }} 只就能同图对比（最多 4 只）</p>
            </div>
          </van-collapse-item>
        </van-collapse>
          <!-- 收益日历：日 / 月 / 年 三期涨跌 -->
          <div class="card cal">
            <div class="ch">
              <span class="seg2"><button v-for="m in ['日','月','年']" :key="m" :class="{ on: calMode === m }" @click="calMode = m">{{ m }}</button></span>
              <div class="nav" v-if="calMode !== '年'">
                <van-icon name="arrow-left" @click="calStep(-1)" :class="{ dis: !canCalStep(-1) }" />
                <b class="num">{{ calMode === '日' ? `${calY}年${calM}月` : `${calY}年` }}</b>
                <van-icon name="arrow" @click="calStep(1)" :class="{ dis: !canCalStep(1) }" />
              </div>
              <span class="cl">涨红跌绿 · 每期最后一条净值</span>
            </div>
            <div class="wk" v-if="calMode === '日'"><span v-for="w in '一二三四五六日'" :key="w">{{ w }}</span></div>
            <div class="grid7" v-if="calMode === '日'">
              <div v-for="(c, k) in cal.cells" :key="k" class="cell" :class="[cellCls(c), { empty: !c }]">
                <template v-if="c"><span class="dd">{{ c.d }}</span><span class="dv num">{{ c.p == null ? '' : pctS(c.p) }}</span></template>
              </div>
            </div>
            <div class="grid3" v-else>
              <div v-for="(c, k) in cal.cells" :key="k" class="cell big" :class="cellCls(c)">
                <span class="dd">{{ c.label }}</span><span class="dv num">{{ c.p == null ? '—' : pctS(c.p) }}</span>
              </div>
            </div>
          </div>
        </template>

      </template>
    </div>
  </div>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showFailToast } from 'vant'
import { get } from '../api'
import { tone } from '../fmt'
import SubBar from '../components/SubBar.vue'
import LineChart from '../components/LineChart.vue'
import MultiLine from '../components/MultiLine.vue'
import { aggregate, sliceRange, rangeReturn } from '../utils/series'
import { cumulativeReturn, drawdown, stats, calendarCells } from '../utils/fundSeries'

const route = useRoute(), router = useRouter()
const aid = route.params.aid
const code = ref(route.query.code || '510300')
const d = ref(null), err = ref('')
const q = ref(''), rows = ref([])
const recent = ref(JSON.parse(localStorage.getItem('aw-recent-funds') || '[]'))
const shortName = n => (n || '').replace(/ETF.*$/, 'ETF').slice(0, 8) || n
const pctS = v => v == null ? '—' : (v > 0 ? '+' : '') + v.toFixed(2) + '%'
const tip = (i, s, digits, unit) => `${s.dates[i].replace(/-/g, '/')}<br/><b>${s.values[i].toFixed(digits)}${unit}</b>`

async function loadFund(c) {
  d.value = null; err.value = ''
  try {
    const x = await get(`/api/market/fund/${c}`)
    d.value = x
    const rc = recent.value.filter(r => r.code !== c)
    recent.value = [{ code: c, name: x.name }, ...rc].slice(0, 12)
    localStorage.setItem('aw-recent-funds', JSON.stringify(recent.value))
  } catch (e) { err.value = e.message }
}
loadFund(code.value)
function select(r) {
  q.value = ''; rows.value = []
  code.value = r.code
  router.replace({ query: { ...route.query, code: r.code } })
  loadFund(r.code)
}
function clearRecent() { recent.value = []; localStorage.removeItem('aw-recent-funds') }
let t = null
watch(q, v => {
  clearTimeout(t)
  if (!v.trim()) { rows.value = []; return }
  t = setTimeout(async () => {
    const r = (await get(`/api/market/fund-search?q=${encodeURIComponent(v.trim())}`)).rows
    rows.value = r.length || !/^\d{6}$/.test(v.trim()) ? r : [{ code: v.trim(), name: `代码 ${v.trim()}`, src: '直接查' }]
  }, 300)
})

// 区间 / 周期：主图、累计收益、回撤共用同一段数据
const ranges = ['近1月', '近3月', '近6月', '近1年', '近3年', '近5年', '今年', '全部']
const range = ref('近1年')
const periods = ['日线', '月线', '年线'], period = ref('日线')
const pchar = computed(() => period.value === '日线' ? '日' : period.value === '月线' ? '月' : '年')
const seg = computed(() => d.value ? sliceRange(d.value.dates, d.value.values, range.value) : { dates: [], values: [] })
const agg = (dates, values) => aggregate(dates, values, pchar.value)
const chart = computed(() => agg(seg.value.dates, seg.value.values))
const retChart = computed(() => agg(seg.value.dates, cumulativeReturn(seg.value.values)))
const ddChart = computed(() => agg(seg.value.dates, drawdown(seg.value.values)))
const stat = computed(() => stats(seg.value.values, seg.value.dates))
const last = computed(() => d.value?.values?.[d.value.values.length - 1])
const dayPct = computed(() => {
  const v = d.value?.values
  return v?.length > 1 && v[v.length - 2] ? (v[v.length - 1] / v[v.length - 2] - 1) * 100 : null
})
// 阶段表现：固定区间，与图表视窗无关
const stages = ['近1月', '近3月', '近6月', '近1年', '近3年', '今年', '全部']
const stageRows = computed(() => stages.map(k => {
  const s = d.value ? sliceRange(d.value.dates, d.value.values, k) : { values: [] }
  return { k, ret: rangeReturn(s.values) }
}))

// 收益日历
const lastDate = computed(() => d.value?.dates?.[d.value.dates.length - 1] || '')
const calY = ref(+lastDate.value.slice(0, 4) || new Date().getFullYear())
const calM = ref(+lastDate.value.slice(5, 7) || new Date().getMonth() + 1)
watch(lastDate, v => { calY.value = +v.slice(0, 4); calM.value = +v.slice(5, 7) })
const calMode = ref('日')
const cal = computed(() => d.value ? calendarCells(d.value.dates, d.value.values, calMode.value, calY.value, calM.value) : { cells: [], months: [] })
function canCalStep(k) {
  if (!d.value) return false
  const ms = cal.value.months
  if (calMode.value === '日') {
    const t = new Date(calY.value, calM.value - 1 + k, 1)
    return ms.includes(`${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}`)
  }
  return ms.some(m => +m.slice(0, 4) === calY.value + k)
}
function calStep(k) {
  if (!canCalStep(k)) return
  if (calMode.value === '日') {
    const t = new Date(calY.value, calM.value - 1 + k, 1)
    calY.value = t.getFullYear(); calM.value = t.getMonth() + 1
  } else calY.value += k
}
const cellCls = c => !c || c.p == null ? '' : c.p > 0 ? 'pos' : c.p < 0 ? 'neg' : ''

// 多只对比（默认展开，位置紧跟三张走势图）
const cmpOpen = ref(['c'])
const picked = ref(JSON.parse(localStorage.getItem('aw-cmp') || '[]'))
const navs = ref({}), cq = ref(''), opts = ref([]), cmpRange = ref('近1年')
const cmpRanges = [{ k: '近1月', m: 1 }, { k: '近3月', m: 3 }, { k: '近1年', m: 12 }, { k: '近3年', m: 36 }, { k: '全部', m: 0 }]
let t2 = null
watch(cq, v => {
  clearTimeout(t2)
  if (!v.trim()) { opts.value = []; return }
  t2 = setTimeout(async () => {
    const r = (await get(`/api/market/fund-search?q=${encodeURIComponent(v.trim())}`)).rows
    opts.value = r.length || !/^\d{6}$/.test(v.trim()) ? r : [{ code: v.trim(), name: `代码 ${v.trim()}`, src: '直接加' }]
  }, 300)
})
watch(picked, async v => {
  localStorage.setItem('aw-cmp', JSON.stringify(v))
  for (const p of v) if (!navs.value[p.code]) {
    try { const x = await get(`/api/market/fund/${p.code}`); navs.value = { ...navs.value, [p.code]: x } } catch { /* 拉不到就不画 */ }
  }
}, { immediate: true, deep: true })
async function pick(r) {
  if (picked.value.length >= 4) return showFailToast('最多对比 4 只')
  if (picked.value.some(p => p.code === r.code)) return
  picked.value = [...picked.value, { code: r.code, name: r.name }]
  opts.value = []; cq.value = ''
}
function drop(c) { picked.value = picked.value.filter(p => p.code !== c) }
const cmpPeriod = ref('日线')
const cmpChar = computed(() => cmpPeriod.value === '日线' ? '日' : cmpPeriod.value === '月线' ? '月' : '年')
const cmpSeg = p => {
  const n = navs.value[p.code]
  if (!n?.dates?.length) return null
  const s = sliceRange(n.dates, n.values, cmpRange.value)
  if (s.values.length < 2 || !s.values[0]) return null
  return s
}
// 相对起点涨跌幅：按当前周期取每期最后一条
const cmpSeries = computed(() => {
  const out = {}
  for (const p of picked.value) {
    const s = cmpSeg(p)
    if (!s) continue
    const a = aggregate(s.dates, cumulativeReturn(s.values), cmpChar.value)
    out[p.name] = { dates: a.dates, ret: a.values }
  }
  return out
})
// 单期涨跌：净值先按周期聚合，再算相邻两期涨跌（保留期首相对上期末）
const periodSeries = computed(() => {
  const out = {}
  for (const p of picked.value) {
    const s = cmpSeg(p)
    if (!s) continue
    const a = aggregate(s.dates, s.values, cmpChar.value)
    out[p.name] = {
      dates: a.dates,
      ret: a.values.map((v, i) => i && a.values[i - 1] ? (v / a.values[i - 1] - 1) * 100 : 0),
    }
  }
  return out
})
const cmpStageKeys = ['近1月', '近3月', '近6月', '近1年', '近3年', '今年', '全部']
const cmpStageRows = computed(() => picked.value.map(p => {
  const n = navs.value[p.code]
  const vals = {}
  for (const k of cmpStageKeys) {
    const s = n?.dates?.length ? sliceRange(n.dates, n.values, k) : { values: [] }
    vals[k] = rangeReturn(s.values)
  }
  return { name: shortName(p.name), vals }
}))
</script>
<style scoped>
.sb{ background:transparent; padding:10px 12px; }
.src{ font-size:12px; color:var(--muted); }
.recent{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; padding:2px 12px 10px; }
.recent .rl{ font-size:12px; color:var(--muted); }
.clr{ color:var(--brand); font-size:12px; cursor:pointer; margin-left:auto; }
.hn{ display:flex; align-items:baseline; gap:8px; font-size:16px; }
.hn span{ font-size:12px; color:var(--muted); font-weight:400; }
.g{ display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin-top:10px; }
.g span{ display:block; font-size:11.5px; color:var(--muted); }
.g b{ display:block; font-size:17px; margin-top:3px; }
.src-line{ font-size:11.5px; color:var(--muted); margin:10px 0 0; }
.st{ font-size:13px; font-weight:600; display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }
.st span{ font-size:11.5px; font-weight:400; color:var(--muted); }
.st.sub{ margin:14px 0 6px; font-weight:500; }
.stage-grid{ display:grid; grid-template-columns:repeat(7,1fr); gap:6px; margin-top:10px; }
.stage-grid span{ display:block; font-size:11.5px; color:var(--muted); }
.stage-grid b{ display:block; font-size:14px; margin-top:3px; }
.rr{ padding:0 0 6px; flex-wrap:wrap; align-items:center; }
.per{ margin-left:auto; }
.stat-row{ display:grid; grid-template-columns:repeat(4,1fr); gap:8px; padding:10px 0 4px; border-bottom:1px solid var(--line); }
.stat-row span{ display:block; font-size:11.5px; color:var(--muted); }
.stat-row b{ display:block; font-size:15px; margin-top:2px; }
.k{ font-size:11.5px; color:var(--muted); margin:10px 0 0; line-height:1.6; }
.sparse{ font-size:12px; color:#92400E; background:#FFFBEB; border-radius:8px;
  padding:7px 10px; margin:8px 0; line-height:1.6; }
.ch{ display:flex; align-items:center; justify-content:space-between; gap:8px; flex-wrap:wrap; }
.cl{ font-size:11.5px; color:var(--muted); }
.nav{ display:flex; align-items:center; gap:6px; font-size:14px; }
.nav .van-icon{ cursor:pointer; padding:4px; } .nav .dis{ opacity:.25; cursor:default; }
.wk{ display:grid; grid-template-columns:repeat(7,1fr); font-size:11px; color:var(--muted); text-align:center; margin:10px 0 4px; }
.grid7{ display:grid; grid-template-columns:repeat(7,1fr); gap:6px; }
.grid3{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-top:10px; }
.cell{ border-radius:9px; background:#F7F8FA; min-height:52px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:3px; }
.cell.big{ min-height:62px; }
.cell.empty{ background:transparent; }
.cell.pos{ background:#FDECEC; } .cell.pos .dv{ color:var(--up); }
.cell.neg{ background:#E7F6EC; } .cell.neg .dv{ color:var(--down); }
.dd{ font-size:11.5px; color:var(--sub); } .dv{ font-size:11.5px; font-weight:600; }
.cell.big .dd{ font-size:12.5px; } .cell.big .dv{ font-size:13px; }
.cmpbox{ margin:16px 12px 0; border-radius:12px; overflow:hidden; }
.cmp .st{ font-size:13px; font-weight:600; display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }
.cmp .st span{ font-size:11.5px; font-weight:400; color:var(--muted); }
.cmp .st.sub{ margin:14px 0 6px; font-weight:500; }
.stage-tbl-wrap{ overflow-x:auto; margin-top:8px; }
.stage-tbl{ width:100%; min-width:640px; border-collapse:collapse; font-size:12px; }
.stage-tbl th, .stage-tbl td{ padding:7px 8px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }
.stage-tbl th:first-child, .stage-tbl td:first-child{ text-align:left; padding-left:2px; }
.stage-tbl th{ font-size:11px; color:var(--muted); font-weight:500; }
.stage-tbl td:first-child{ color:var(--ink); }
.cmpbox :deep(.van-collapse-item__content){ padding:8px 12px 14px; }
.picked{ padding:4px 0 8px; flex-wrap:wrap; }
.cmp .rr{ padding:8px 0; }
@media (max-width:700px){
  .g, .stat-row{ grid-template-columns:repeat(2,1fr); }
  .stage-grid{ grid-template-columns:repeat(4,1fr); }
  .cell{ min-height:44px; } .dv{ font-size:10px; }
}
</style>
