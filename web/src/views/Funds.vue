<template>
  <div class="page no-tab">
    <SubBar title="基金检索" :fallback="`/a/${aid}/market`" />
    <div class="wrap">
      <!-- 视图切换：与 Python 版 segmented_control 同位置同语义，切换后下面整块替换、共用同一套卡片 -->
      <div class="mode-seg" role="group" aria-label="视图">
        <button v-for="m in modes" :key="m" type="button" :class="{ on: mode === m }" :aria-pressed="mode === m" @click="mode = m">{{ m }}</button>
      </div>

      <!-- ==================== 单只走势 ==================== -->
      <template v-if="mode === '单只走势'">
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
            <span v-for="r in recent" :key="r.code" class="chip" :class="{ on: r.code === code }" :title="r.name" @click="select(r)">{{ shortName(r.name) }}</span>
            <a class="clr" @click="clearRecent">清空</a>
          </div>

          <van-loading v-if="!d && !err" style="margin:30px 0" vertical>拉取净值…（第一次查要几秒）</van-loading>
          <p v-else-if="err" class="empty-tip">{{ err }}</p>
          <template v-else>
            <!-- 基金概览 -->
            <div class="card head">
              <!-- 后台还没返回 otc（旧接口/旧进程）就不显示，宁可少一个标签也别标错 -->
              <!-- 数据来源那句（「本地已是最新」）并进标题行右侧，别再单占一行 -->
              <div class="hn"><b>{{ d.name }}</b><span class="code num">{{ code }}</span><span v-if="d.otc != null" class="kind">{{ d.otc ? '场外' : '场内' }}</span><span class="srcline">{{ d.msg }}</span></div>
              <div class="g">
                <div><span>最新单位净值</span><b class="num">{{ last?.toFixed(4) }}</b></div>
                <div><span>单日</span><b class="num" :class="tone(dayPct)">{{ pctS(dayPct) }}</b></div>
                <div><span>截至</span><b class="num">{{ d.dates[d.dates.length - 1].replace(/-/g, '/') }}</b></div>
                <div><span>区间收益</span><b class="num" :class="tone(stat.ret)">{{ pctS(stat.ret) }}</b></div>
              </div>
              <!-- 基金档案 + 费率：两行文字，别再堆第二排数字（第一排净值已经够密了） -->
              <div class="meta-lines" v-if="d.meta">
                <p v-if="d.meta.profile"><span>档案</span>{{ d.meta.profile }}</p>
                <p v-if="d.meta.fee_desc"><span>费率</span>{{ d.meta.fee_desc }}</p>
              </div>
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
              <RangeBar :range="range" :period="period" :periods="periods"
                        @update:range="setRange" @update:period="p => period = p" />
              <div class="stat-row">
                <div><span>最大回撤</span><b class="num down">{{ stat.mdd?.toFixed(2) }}%</b></div>
                <div><span>年化</span><b class="num" :class="tone(stat.cagr)">{{ pctS(stat.cagr) }}</b></div>
                <div><span>年化波动</span><b class="num">{{ stat.vol?.toFixed(2) }}%</b></div>
                <div><span>数据点</span><b class="num">{{ visCount }}</b></div>
              </div>
              <p v-if="visCount < 2" class="sparse">当前区间按{{ period }}只有 {{ visCount }} 期数据，看走势请切到日线或月线</p>
              <div class="st sub">单位净值走势</div>
              <LineChart :dates="fullNav.dates" :values="fullNav.values" :labels="fullNav.labels" :height="220" unit=""
                         :window="win" :reset-key="resetKey" group="funds-single" :fmt-tip="i => tip(i, fullNav, 4, '', '单位净值')" />
              <div class="st sub">累计收益走势 <span>区间起点 = 0%，往左可拖出更早历史</span></div>
              <LineChart :dates="fullRet.dates" :values="fullRet.values" :labels="fullRet.labels" :height="170" unit="%" zero
                         :window="win" :reset-key="resetKey" group="funds-single" :fmt-tip="i => tip(i, fullRet, 2, '%', '累计收益')" />
              <div class="st sub">回撤曲线 <span>距区间内历史最高点</span></div>
              <LineChart :dates="fullDd.dates" :values="fullDd.values" :labels="fullDd.labels" :height="160" unit="%" zero
                         :window="win" :reset-key="resetKey" group="funds-single" :fmt-tip="i => tip(i, fullDd, 2, '%', '回撤')" />
              <p class="k">双指/滚轮滑动或按住拖动平移（可向左拖出区间外的历史）· ⌘/Ctrl + 滑动缩放 · 双击复位到当前区间；月/年线取每期最后一条真实记录</p>
            </div>

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
      </template>

      <!-- ==================== 多只对比（与单只共用同一套卡片 / chips / 图表区） ==================== -->
      <template v-else>
        <!-- 一张卡：搜索 + 已选。顶部已经有「单只走势 / 多只对比」切换，
             卡内再写标题 + 3/4 计数 + 口径说明就是纯占一行（用户 2026-11-08：和单只走势保持一致，这行去掉） -->
        <div class="card cmp">
          <van-search v-model="cq" placeholder="搜索并添加基金，最多对比 4 只" shape="round" class="sb cmp-sb" />
          <van-cell-group inset v-if="opts.length">
            <van-cell v-for="r in opts" :key="r.code" :title="r.name" :label="r.code" clickable @click="pick(r)">
              <template #value><van-icon name="plus" /></template>
            </van-cell>
          </van-cell-group>
          <div class="picked" v-if="picked.length">
            <!-- 只有 × 能删：整枚 chip 都绑 click 时，点名字（想看名字/误触）也会被删掉 -->
            <span v-for="p in picked" :key="p.code" class="chip on" :title="p.name">
              <span class="cn">{{ shortName(p.name) }}</span>
              <button type="button" class="x" :aria-label="`移除 ${p.name}`" @click="drop(p.code)">×</button>
            </span>
          </div>
          <!-- 只选了 1 只才提示；0 只时搜索框的 placeholder 已经说清了，不再多一行 -->
          <p class="cmp-empty" v-if="picked.length === 1">再选 1 只就能同图对比</p>
        </div>

        <div class="card" v-if="picked.length >= 2">
          <RangeBar :range="cmpRange" :period="cmpPeriod" :periods="periods"
                    @update:range="setCmpRange" @update:period="p => cmpPeriod = p" />
          <div class="st sub">相对起点涨跌幅 <span>区间首值 = 0%，往左可拖出更早历史</span></div>
          <MultiLine :series="cmpSeries" :height="240" :window="cmpWin" :reset-key="cmpReset" group="funds-cmp" />
          <div class="st sub">单期涨跌 <span>每{{ cmpPeriod === '日线' ? '日' : cmpPeriod === '月线' ? '月' : '年' }}相对上一期</span></div>
          <MultiLine :series="periodSeries" :height="170" :window="cmpWin" :reset-key="cmpReset" group="funds-cmp" />
          <div class="st sub">阶段表现 <span>各基金固定区间涨跌，与图表视窗无关</span></div>
          <div class="stage-tbl-wrap">
            <table class="stage-tbl">
              <thead><tr><th>基金</th><th v-for="k in cmpStageKeys" :key="k">{{ k }}</th></tr></thead>
              <tbody><tr v-for="row in cmpStageRows" :key="row.code">
                <td><span class="nm" :title="row.name">{{ row.name }}</span></td>
                <td v-for="(v, k) in row.vals" :key="k" class="num" :class="tone(v)">{{ pctS(v) }}</td>
              </tr></tbody>
            </table>
          </div>
        </div>
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
import RangeBar from '../components/RangeBar.vue'
import MultiLine from '../components/MultiLine.vue'
import { aggregate, sliceRange, rangeStartIndex, rangeReturn, RANGE_KEYS } from '../utils/series'
import { cumulativeReturn, drawdown, stats, calendarCells } from '../utils/fundSeries'
import { tipRows } from '../utils/chartTheme'
import { dateText } from '../utils/chartAxis'

const route = useRoute(), router = useRouter()
const aid = route.params.aid
const modes = ['单只走势', '多只对比'], mode = ref('单只走势')
const code = ref(route.query.code || '510300')
const d = ref(null), err = ref('')
const q = ref(''), rows = ref([])
const recent = ref(JSON.parse(localStorage.getItem('aw-recent-funds') || '[]'))
// 只去掉括号备注，不做字符硬截（slice(0,8) 会截出「天弘沪深300E」这种半截名，且与图例全名不一致）；
// 窄容器由 CSS ellipsis 处理，title 保留完整名称
const shortName = n => (n || '').replace(/[（(][^）)]*[）)]/g, '').trim() || n
const pctS = v => v == null ? '—' : (v > 0 ? '+' : '') + v.toFixed(2) + '%'
const tip = (i, s, digits, unit, label) => tipRows(dateText(s.dates[i]), [[label, s.values[i].toFixed(digits) + unit]])

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

// 区间 / 周期：三张图共用同一段**全历史**数据，区间只决定初始视窗（与基金详情 iframe 图表同逻辑）
const ranges = RANGE_KEYS
const range = ref('近1月')
const periods = ['日线', '月线', '年线'], period = ref('日线')
const pchar = computed(() => period.value === '日线' ? '日' : period.value === '月线' ? '月' : '年')
// 点同一个区间也要复位视窗（拖走以后再点一次当前区间，range 没变不会触发 watch，所以要 bump）
const bump = ref(0)
const setRange = r => { range.value = r; bump.value++ }
const resetKey = computed(() => `${range.value}|${period.value}|${bump.value}`)
const seg = computed(() => d.value ? sliceRange(d.value.dates, d.value.values, range.value) : { dates: [], values: [] })
const agg = (dates, values) => aggregate(dates, values, pchar.value)
const EMPTY = { dates: [], values: [], labels: [] }
// 累计收益 / 回撤的锚点 = 区间起点下标：往左拖到更早历史时口径不变，默认视窗与原来完全一致
const baseIdx = computed(() => d.value ? rangeStartIndex(d.value.dates, range.value) : 0)
const fullNav = computed(() => d.value ? agg(d.value.dates, d.value.values) : EMPTY)
const fullRet = computed(() => d.value ? agg(d.value.dates, cumulativeReturn(d.value.values, baseIdx.value)) : EMPTY)
const fullDd = computed(() => d.value ? agg(d.value.dates, drawdown(d.value.values, baseIdx.value)) : EMPTY)
// 可见窗口（聚合后的下标，含首尾）：右端固定到最新，左端落在区间起点那条记录上
const win = computed(() => {
  const a = fullNav.value
  if (!d.value || !a.dates.length) return null
  const anchor = d.value.dates[baseIdx.value]
  const i = a.dates.findIndex(x => x >= anchor)
  return [Math.max(0, i), a.dates.length - 1]
})
const visCount = computed(() => (win.value ? win.value[1] - win.value[0] + 1 : 0))
const stat = computed(() => stats(seg.value.values, seg.value.dates))
const last = computed(() => d.value?.values?.[d.value.values.length - 1])
const dayPct = computed(() => {
  const v = d.value?.values
  return v?.length > 1 && v[v.length - 2] ? (v[v.length - 1] / v[v.length - 2] - 1) * 100 : null
})
// 阶段表现：固定区间，与图表视窗无关（区间标签与曲线用同一份 RANGE_KEYS）
const stages = RANGE_KEYS
// 费率文案：场内 ETF 是佣金（万 1.5），场外是申购费 + 持有期满后的赎回费
const buyFeeText = computed(() => {
  const m = d.value?.meta
  if (!m) return '—'
  if (m.exchange) return '万1.5'      // 场内佣金万 1.5（‰ 那个字符很多字体没有，会显示成别的符号）
  return m.buy_rate == null ? '—' : `${(m.buy_rate * 100).toFixed(2)}%`
})
const sellFeeText = computed(() => {
  const m = d.value?.meta
  if (!m) return '—'
  if (m.exchange) return '万1.5'
  const list = m.redeem || []
  if (!list.length) return '—'
  const open = list.filter(x => x.max_days == null).pop() || list[0]
  return `${(open.rate * 100).toFixed(2)}%`
})
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

// 多只对比：与单只共用同一套卡片 / chips / 图表区，只是叠加多条线
const picked = ref(JSON.parse(localStorage.getItem('aw-cmp') || '[]'))
const navs = ref({}), cq = ref(''), opts = ref([]), cmpRange = ref('近1月')
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
const cmpBump = ref(0)
const setCmpRange = k => { cmpRange.value = k; cmpBump.value++ }
const cmpReset = computed(() => `${cmpRange.value}|${cmpPeriod.value}|${cmpBump.value}`)
// 每只基金都给全历史（按周期聚合）+ 以区间起点为锚的累计涨跌 + 单期涨跌；
// 区间只决定视窗，所以能像单只走势那样往左拖出更早历史
const cmpFull = computed(() => {
  const out = {}
  for (const p of picked.value) {
    const n = navs.value[p.code]
    if (!n?.dates?.length) continue
    const b = rangeStartIndex(n.dates, cmpRange.value)
    if (!n.values[b]) continue
    const pa = aggregate(n.dates, n.values, cmpChar.value)
    const ra = aggregate(n.dates, cumulativeReturn(n.values, b), cmpChar.value)
    // base 记的是「区间基准日」本身（不是全历史第一天），窗口左端要用它
    out[p.name] = { dates: ra.dates, ret: ra.values, nav: pa.values, base: n.dates[b] }
  }
  return out
})
// 相对起点涨跌幅
const cmpSeries = computed(() => {
  const out = {}
  for (const [k, v] of Object.entries(cmpFull.value)) out[k] = { dates: v.dates, ret: v.ret }
  return out
})
// 单期涨跌：净值先按周期聚合，再算相邻两期涨跌（保留期首相对上期末）
const periodSeries = computed(() => {
  const out = {}
  for (const [k, v] of Object.entries(cmpFull.value)) {
    out[k] = {
      dates: v.dates,
      ret: v.nav.map((x, i) => i && v.nav[i - 1] ? (x / v.nav[i - 1] - 1) * 100 : 0),
    }
  }
  return out
})
// 可见窗口（并集日期轴上的下标）：左端 = 各基金区间基准日里最晚的那天，保证每只都从自己的基准日开始
const cmpWin = computed(() => {
  const all = [...new Set(Object.values(cmpSeries.value).flatMap(s => s.dates))].sort()
  if (!all.length) return null
  const anchors = Object.values(cmpFull.value).map(v => v.base).sort()
  const i = all.findIndex(d => d >= anchors[anchors.length - 1])
  return [Math.max(0, i), all.length - 1]
})
const cmpStageKeys = RANGE_KEYS
const cmpStageRows = computed(() => picked.value.map(p => {
  const n = navs.value[p.code]
  const vals = {}
  for (const k of cmpStageKeys) {
    const s = n?.dates?.length ? sliceRange(n.dates, n.values, k) : { values: [] }
    vals[k] = rangeReturn(s.values)
  }
  return { code: p.code, name: p.name, vals }
}))
</script>
<style scoped>
/* 视图切换的视觉定义在 style.css 的 .mode-seg（与 .seg2 同一套），这里只管外边距 */
.mode-seg{ margin:12px 12px 4px; }
/* 搜索框：白底 + 边框 + 加深 placeholder，别和页面背景糊在一起 */
.sb{ background:transparent; padding:10px 12px 4px; }
.sb :deep(.van-search__content){ background:#fff; border:1px solid #D5DCE6; box-shadow:0 1px 2px rgba(15,23,42,.04); }
.sb :deep(.van-field__control){ color:var(--ink); font-size:14px; }
.sb :deep(.van-field__control::placeholder){ color:#64748B; -webkit-text-fill-color:#64748B; }
.sb :deep(.van-search__content .van-icon){ color:#64748B; }
.cmp-sb{ padding:0 0 4px; }
.src{ font-size:12px; color:var(--muted); }
.recent{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; padding:4px 12px 0; }
.recent .rl{ font-size:12px; color:var(--muted); }
.clr{ color:var(--brand); font-size:12px; cursor:pointer; margin-left:auto; }
.hn{ display:flex; align-items:baseline; gap:7px; font-size:16px; flex-wrap:wrap; }
.hn span{ font-size:12px; color:var(--muted); font-weight:400; }
/* 编号 + 场内/场外：和基金详情页（Fund.vue）同一套徽标，编号品牌蓝底、类型灰底 */
.hn .code{ font-size:11.5px; font-weight:600; line-height:18px; padding:0 7px; border-radius:6px;
  color:var(--brand); background:var(--brand-soft); letter-spacing:.3px; }
.hn .kind{ font-size:11.5px; font-weight:500; line-height:18px; padding:0 7px; border-radius:6px;
  color:#475569; background:#F1F3F6; }
.meta-lines{ margin-top:12px; padding-top:11px; border-top:1px solid var(--line); }
.meta-lines p{ display:flex; gap:8px; margin:0 0 5px; font-size:11.5px; line-height:1.55; color:var(--sub); }
.meta-lines p:last-child{ margin-bottom:0; }
.meta-lines span{ flex:0 0 auto; color:var(--muted); }
.g{ display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin-top:10px; }
.g > div{ min-width:0; text-align:center; }
.g span{ display:block; font-size:11.5px; color:var(--muted); }
.g b{ display:block; font-size:17px; margin-top:3px; }
/* 基金概览标题行：名称 + 编号 + 场内场外，右侧跟一句数据来源（不再单占一行） */
.hn .srcline{ margin-left:auto; font-weight:400; }
/* 多只对比：卡片开头直接是搜索框 + 已选 chips，与单只走势页一致（不再有标题/计数行） */
.cmp-empty{ font-size:12px; color:var(--muted); margin:2px 0 0; }
.st{ font-size:13px; font-weight:600; display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }
.st span{ font-size:11.5px; font-weight:400; color:var(--muted); }
.st.sub{ margin:14px 0 6px; font-weight:500; }
.stage-grid{ display:grid; grid-template-columns:repeat(8,1fr); column-gap:8px; row-gap:6px; margin-top:10px; }
.stage-grid > div{ min-width:0; text-align:center; }
.stage-grid span{ display:block; font-size:11.5px; color:var(--muted); }
.stage-grid b{ display:block; font-size:14px; margin-top:3px; }
.rr{ padding:0 0 6px; flex-wrap:wrap; align-items:center; }
.per{ margin-left:auto; }
.stat-row{ display:grid; grid-template-columns:repeat(4,1fr); gap:8px; padding:10px 0 4px; border-bottom:1px solid var(--line); }
.stat-row > div{ min-width:0; text-align:center; }
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
.picked{ display:flex; flex-wrap:wrap; gap:8px; padding:6px 0 0; }
/* 名称不硬截：窄处用省略号，title 保留全名（避免「天弘沪深300E」这类半截名） */
.recent .chip{ max-width:170px; overflow:hidden; text-overflow:ellipsis; }
/* 已选 chip 只是标签，点名字不做事；删除只认 ×（按钮，热区比字形大） */
.picked .chip{ display:inline-flex; align-items:center; gap:5px; max-width:210px; cursor:default; }
.picked .chip .cn{ min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.picked .chip .x{ flex:0 0 auto; display:inline-flex; align-items:center; justify-content:center;
  width:18px; height:18px; margin-right:-3px; padding:0; border:0; border-radius:50%;
  background:transparent; color:var(--muted); font:inherit; font-size:14px; line-height:1; cursor:pointer; }
.picked .chip .x:hover{ background:rgba(15,23,42,.08); color:var(--ink); }
.picked .chip .x:focus-visible{ outline:2px solid var(--brand); outline-offset:1px; }
.stage-tbl td:first-child .nm{ display:inline-block; max-width:170px; vertical-align:bottom;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.stage-tbl-wrap{ overflow-x:auto; margin-top:8px; }
.stage-tbl{ width:100%; min-width:720px; border-collapse:collapse; font-size:12px; }
.stage-tbl th, .stage-tbl td{ padding:7px 8px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }
.stage-tbl th:first-child, .stage-tbl td:first-child{ text-align:left; padding-left:2px; }
.stage-tbl th{ font-size:11px; color:var(--muted); font-weight:500; }
.stage-tbl td:first-child{ color:var(--ink); }
@media (max-width:700px){
  /* 窄屏来源那句换到名称下面，当小注处理（别做成右对齐的孤字） */
  .hn .srcline{ margin-left:0; flex-basis:100%; font-size:11px; color:#94A3B8; margin-top:2px; }
  .g, .stat-row{ grid-template-columns:repeat(2,1fr); }
  .stage-grid{ grid-template-columns:repeat(4,1fr); }
  .cell{ min-height:44px; } .dv{ font-size:10px; }
}
</style>
