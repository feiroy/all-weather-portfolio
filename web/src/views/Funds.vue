<template>
  <div class="page no-tab">
    <SubBar title="基金检索" :fallback="`/a/${aid}/market`" />
    <div class="wrap">
      <!-- 视图切换：单只 / 对比，切换后下面整块替换、共用同一套卡片 -->
      <div class="mode-seg" role="group" aria-label="视图">
        <button v-for="m in modes" :key="m" type="button" :class="{ on: mode === m }" :aria-pressed="mode === m" @click="mode = m">{{ m }}</button>
      </div>

      <!-- ==================== 单只走势 ====================
           页面骨架（2026-11-08 重排，原则：一屏一个重点、能不写的字都不写）：
             ① 头卡：名称 + 大号净值 + 当日涨跌 + 一排短标签（类型/规模/风险/费率）
             ② 净值走势：区间控件 + 三层联动图 + 一行区间指标
             ③ 阶段涨幅  ④ 收益日历  ⑤ 基金档案（长文本全部收在这里）
           卡片只留标题，不写灰色副标题；口径靠控件本身和数值标签说清楚。 -->
      <template v-if="mode === '单只走势'">
        <van-search v-model="q" placeholder="搜索基金名称或 6 位代码" shape="round" class="sb" />
        <van-cell-group inset v-if="q.trim() && rows.length">
          <van-cell v-for="r in rows" :key="r.code" :title="r.name" :label="r.code" clickable @click="select(r)">
            <template #value><span class="src">{{ r.src }}</span></template>
          </van-cell>
        </van-cell-group>
        <p v-else-if="q.trim()" class="empty-tip">没找到。试试换个关键词，或直接输入 6 位代码</p>

        <template v-if="!q.trim()">
          <div class="recent" v-if="recent.length > 1">
            <span v-for="r in recent" :key="r.code" class="chip" :class="{ on: r.code === code }" :title="r.name" @click="select(r)">{{ shortName(r.name) }}</span>
            <a class="clr" @click="clearRecent">清空</a>
          </div>

          <van-loading v-if="!d && !err" style="margin:30px 0" vertical>拉取净值…（第一次查要几秒）</van-loading>
          <p v-else-if="err" class="empty-tip">{{ err }}</p>
          <template v-else>
            <!-- ① 头卡：净值是唯一的大字 -->
            <div class="card hero">
              <div class="hn">
                <b class="fname" :title="d.name">{{ d.name }}</b>
                <span class="code num">{{ code }}</span>
                <span v-if="d.otc != null" class="kind">{{ d.otc ? '场外' : '场内' }}</span>
              </div>
              <div class="navline">
                <b class="navv num">{{ last?.toFixed(4) }}</b>
                <span class="chg num" :class="tone(dayPct)">{{ pctS(dayPct) }}</span>
                <span class="asof num">{{ lastDate.replace(/-/g, '/') }} 单位净值</span>
              </div>
              <div class="tags" v-if="tags.length">
                <span v-for="t in tags" :key="t">{{ t }}</span>
              </div>
              <!-- 只有拉取失败（用的是旧缓存）才提示，「本地已是最新」这种正常状态不占位置 -->
              <p v-if="d.ok === false && d.msg" class="warn">{{ d.msg }}</p>
            </div>

            <!-- ② 净值走势：页面的主体 -->
            <div class="card">
              <div class="st">净值走势</div>
              <RangeBar :range="range" :period="period" :periods="periods"
                        @update:range="setRange" @update:period="p => period = p" />
              <p v-if="visCount < 2" class="sparse">当前区间按{{ period }}只有 {{ visCount }} 期数据，看走势请切到日线或月线</p>
              <!-- panels[0] = 单位净值（主图）；后续 MACD 加一个面板、九转在净值面板挂标记 -->
              <MultiLine :panels="fundPanels" :height="380" group="funds-single"
                         :window="win" :reset-key="resetKey" />
              <div class="kpi4">
                <div><span>{{ range }}涨跌</span><b class="num" :class="tone(stat.ret)">{{ pctS(stat.ret) }}</b></div>
                <div><span>最大回撤</span><b class="num" :class="tone(stat.mdd)">{{ stat.mdd == null ? '—' : stat.mdd.toFixed(2) + '%' }}</b></div>
                <div><span>年化</span><b class="num" :class="tone(stat.cagr)">{{ pctS(stat.cagr) }}</b></div>
                <div><span>波动率</span><b class="num">{{ stat.vol == null ? '—' : stat.vol.toFixed(2) + '%' }}</b></div>
              </div>
            </div>

            <!-- ③ 阶段涨幅：固定区间，与图表视窗无关 -->
            <div class="card">
              <div class="st">阶段涨幅</div>
              <div class="stage-grid">
                <div v-for="s in stageRows" :key="s.k"><span>{{ s.k }}</span><b class="num" :class="tone(s.ret)">{{ pctS(s.ret) }}</b></div>
              </div>
            </div>

            <!-- ④ 收益日历：标题和控件同一行 -->
            <div class="card cal">
              <div class="ch">
                <div class="st">收益日历</div>
                <div class="nav" v-if="calMode !== '年'">
                  <van-icon name="arrow-left" @click="calStep(-1)" :class="{ dis: !canCalStep(-1) }" />
                  <b class="num">{{ calMode === '日' ? `${calY}年${calM}月` : `${calY}年` }}</b>
                  <van-icon name="arrow" @click="calStep(1)" :class="{ dis: !canCalStep(1) }" />
                </div>
                <span class="seg2"><button v-for="m in ['日','月','年']" :key="m" :class="{ on: calMode === m }" @click="calMode = m">{{ m }}</button></span>
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

            <!-- ⑤ 基金档案：长文本（经理/公司/完整费率）全部收在最后，键值两列对齐 -->
            <div class="card" v-if="profileRows.length">
              <div class="st">基金档案</div>
              <dl class="kv">
                <template v-for="r in profileRows" :key="r[0]">
                  <dt>{{ r[0] }}</dt><dd :class="{ wide: r[2] }">{{ r[1] }}</dd>
                </template>
              </dl>
            </div>
          </template>
        </template>
      </template>

      <!-- ==================== 多只对比：同一套版式语言（选基金 → 一张联动图 → 阶段涨幅表） ==================== -->
      <template v-else>
        <div class="card cmp">
          <van-search v-model="cq" placeholder="搜索并添加基金，最多 4 只" shape="round" class="sb cmp-sb" />
          <van-cell-group inset v-if="opts.length">
            <van-cell v-for="r in opts" :key="r.code" :title="r.name" :label="r.code" clickable @click="pick(r)">
              <template #value><van-icon name="plus" /></template>
            </van-cell>
          </van-cell-group>
          <div class="picked" v-if="picked.length">
            <!-- 只有 × 能删：整枚 chip 都绑 click 时，点名字也会被删掉 -->
            <span v-for="p in picked" :key="p.code" class="chip on" :title="p.name">
              <span class="cn">{{ shortName(p.name) }}</span>
              <button type="button" class="x" :aria-label="`移除 ${p.name}`" @click="drop(p.code)">×</button>
            </span>
          </div>
          <p class="cmp-empty" v-if="picked.length === 0">
            搜索基金名称或 6 位代码，点结果加入（最多 4 只）。
            <button type="button" class="cmp-add" @click="pick({ code, name: d?.name || code })">
              加入当前这只
            </button>
          </p>
          <p class="cmp-empty" v-if="picked.length === 1">再选 1 只就能同图对比</p>
        </div>

        <template v-if="picked.length >= 2">
          <div class="card">
            <div class="st">走势对比</div>
            <RangeBar :range="cmpRange" :period="cmpPeriod" :periods="periods"
                      @update:range="setCmpRange" @update:period="p => cmpPeriod = p" />
            <MultiLine :panels="cmpPanels" :height="360" :window="cmpWin" :reset-key="cmpReset" group="funds-cmp" />
          </div>
          <div class="card">
            <div class="st">阶段涨幅</div>
            <div class="stage-tbl-wrap">
              <table class="stage-tbl">
                <thead><tr><th>基金</th><th v-for="k in cmpStageKeys" :key="k">{{ k }}</th></tr></thead>
                <tbody><tr v-for="row in cmpStageRows" :key="row.code">
                  <td><span class="nm" :title="row.name">{{ shortName(row.name) }}</span></td>
                  <td v-for="(v, k) in row.vals" :key="k" class="num" :class="tone(v)">{{ pctS(v) }}</td>
                </tr></tbody>
              </table>
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
import RangeBar from '../components/RangeBar.vue'
import MultiLine from '../components/MultiLine.vue'
import { aggregate, sliceRange, rangeStartIndex, rangeReturn, RANGE_KEYS } from '../utils/series'
import { cumulativeReturn, drawdown, stats, calendarCells } from '../utils/fundSeries'
import { CHART, SERIES_COLORS } from '../utils/chartTheme'

const route = useRoute(), router = useRouter()
const aid = route.params.aid
const modes = ['单只走势', '多只对比'], mode = ref('单只走势')
const code = ref(route.query.code || '510300')
const d = ref(null), err = ref('')
const q = ref(''), rows = ref([])
const recent = ref(JSON.parse(localStorage.getItem('aw-recent-funds') || '[]'))
// 只去掉括号备注，不做字符硬截；窄容器由 CSS ellipsis 处理，title 保留完整名称
const shortName = n => (n || '').replace(/[（(][^）)]*[）)]/g, '').trim() || n
const pctS = v => v == null ? '—' : (v > 0 ? '+' : '') + v.toFixed(2) + '%'

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
function clearRecent() { recent.value = recent.value.filter(r => r.code === code.value); localStorage.setItem('aw-recent-funds', JSON.stringify(recent.value)) }
let t = null
watch(q, v => {
  clearTimeout(t)
  if (!v.trim()) { rows.value = []; return }
  t = setTimeout(async () => {
    const r = (await get(`/api/market/fund-search?q=${encodeURIComponent(v.trim())}`)).rows
    rows.value = r.length || !/^\d{6}$/.test(v.trim()) ? r : [{ code: v.trim(), name: `代码 ${v.trim()}`, src: '直接查' }]
  }, 300)
})

// 区间 / 周期：图表用**全历史**数据，区间只决定初始视窗（与基金详情 iframe 图表同逻辑）
const range = ref('近1月')
const periods = ['日线', '月线', '年线'], period = ref('日线')
const pchar = computed(() => period.value === '日线' ? '日' : period.value === '月线' ? '月' : '年')
// 点同一个区间也要复位视窗（range 没变不会触发 watch，所以要 bump）
const bump = ref(0)
const setRange = r => { range.value = r; bump.value++ }
const resetKey = computed(() => `${range.value}|${period.value}|${bump.value}`)
const seg = computed(() => d.value ? sliceRange(d.value.dates, d.value.values, range.value) : { dates: [], values: [] })
const agg = (dates, values) => aggregate(dates, values, pchar.value)
const EMPTY = { dates: [], values: [], labels: [] }
// 区间涨跌 / 回撤的锚点 = 区间起点下标：往左拖到更早历史时口径不变
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
// 一个图三层联动：单位净值（主面板）/ 区间涨跌 / 回撤，共用 x 轴、缩放、tooltip、状态行。
// 面板数组就是技术指标的扩展位：MACD 加一个多序列 + 柱的面板，神奇九转在净值面板挂数字标记。
const one = (x, name) => (x?.dates?.length ? { [name]: { dates: x.dates, ret: x.values } } : {})
const fundPanels = computed(() => [
  { key: 'nav', label: '单位净值', unit: '', tipUnit: ' 元', decimals: 4, ratio: 0.54,
    color: CHART.line, series: one(fullNav.value, '单位净值') },
  { key: 'ret', label: '区间涨跌', unit: '%', ratio: 0.23, zeroLine: true,
    color: SERIES_COLORS[1], series: one(fullRet.value, '区间涨跌') },
  { key: 'dd', label: '回撤', unit: '%', ratio: 0.23, zeroLine: true,
    color: SERIES_COLORS[2], series: one(fullDd.value, '回撤') },
])
const stat = computed(() => stats(seg.value.values, seg.value.dates))
const last = computed(() => d.value?.values?.[d.value.values.length - 1])
const lastDate = computed(() => d.value?.dates?.[d.value.dates.length - 1] || '')
const dayPct = computed(() => {
  const v = d.value?.values
  return v?.length > 1 && v[v.length - 2] ? (v[v.length - 1] / v[v.length - 2] - 1) * 100 : null
})
// 头卡短标签：只放「选基金时一眼要看的」——类型 / 规模 / 风险 / 交易费；长句放基金档案
const feeShort = computed(() => {
  const m = d.value?.meta
  if (!m) return ''
  if (m.exchange) return '佣金 万1.5'
  return m.buy_rate == null ? '' : `申购费 ${(m.buy_rate * 100).toFixed(2)}%`
})
const tags = computed(() => {
  const m = d.value?.meta || {}
  return [m.type, m.size_text && `规模 ${m.size_text}`, m.risk && `${m.risk}风险`, feeShort.value].filter(Boolean)
})
// 基金档案：键值对，第三项 true = 占满整行（费率说明较长）
const profileRows = computed(() => {
  const m = d.value?.meta || {}
  return [
    ['类型', m.type], ['成立日期', m.inception && m.inception.replace(/-/g, '/')],
    ['基金规模', m.size_text], ['风险等级', m.risk],
    ['基金经理', m.manager], ['基金公司', m.company],
    ['交易费用', m.fee_desc, true],
  ].filter(r => r[1])
})
const stageRows = computed(() => RANGE_KEYS.map(k => {
  const s = d.value ? sliceRange(d.value.dates, d.value.values, k) : { values: [] }
  return { k, ret: rangeReturn(s.values) }
}))

// 收益日历
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
const cellCls = c => !c ? '' : c.p == null ? 'nodata' : c.p > 0 ? 'pos' : c.p < 0 ? 'neg' : 'flat'

// 多只对比：与单只同一套版式——一张联动图（区间涨跌 + 回撤）+ 阶段涨幅表
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
// 每只基金：全历史 + 以区间起点为锚的涨跌 / 回撤；区间只决定视窗，能往左拖出更早历史
const cmpFull = computed(() => {
  const out = {}
  for (const p of picked.value) {
    const n = navs.value[p.code]
    if (!n?.dates?.length) continue
    const b = rangeStartIndex(n.dates, cmpRange.value)
    if (!n.values[b]) continue
    const ra = aggregate(n.dates, cumulativeReturn(n.values, b), cmpChar.value)
    const da = aggregate(n.dates, drawdown(n.values, b), cmpChar.value)
    // base 记的是「区间基准日」本身，窗口左端要用它
    out[shortName(p.name)] = { dates: ra.dates, ret: ra.values, dd: da.values, base: n.dates[b] }
  }
  return out
})
const cmpPanels = computed(() => {
  const ret = {}, dd = {}
  for (const [k, v] of Object.entries(cmpFull.value)) {
    ret[k] = { dates: v.dates, ret: v.ret }
    dd[k] = { dates: v.dates, ret: v.dd }
  }
  return [
    { key: 'ret', label: '区间涨跌', unit: '%', ratio: 0.62, zeroLine: true, series: ret },
    { key: 'dd', label: '回撤', unit: '%', ratio: 0.38, zeroLine: true, series: dd },
  ]
})
// 可见窗口：左端 = 各基金区间基准日里最晚的那天，保证每只都从自己的基准日开始
const cmpWin = computed(() => {
  const all = [...new Set(Object.values(cmpFull.value).flatMap(s => s.dates))].sort()
  if (!all.length) return null
  const anchors = Object.values(cmpFull.value).map(v => v.base).sort()
  const i = all.findIndex(x => x >= anchors[anchors.length - 1])
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
.sb{ background:transparent; padding:8px 12px 2px; }
.sb :deep(.van-search__content){ background:#fff; border:1px solid #D5DCE6; box-shadow:0 1px 2px rgba(15,23,42,.04); }
.sb :deep(.van-field__control){ color:var(--ink); font-size:14px; }
.sb :deep(.van-field__control::placeholder){ color:#64748B; -webkit-text-fill-color:#64748B; }
.sb :deep(.van-search__content .van-icon){ color:#64748B; }
.cmp-sb{ padding:0 0 4px; }
.src{ font-size:12px; color:var(--muted); }
/* 最近看过：一行横滑，不换行占两三行 */
.recent{ display:flex; align-items:center; gap:8px; padding:6px 12px 0; overflow-x:auto; scrollbar-width:none; }
.recent::-webkit-scrollbar{ display:none; }
.recent .chip{ flex:0 0 auto; max-width:170px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.clr{ flex:0 0 auto; color:var(--muted); font-size:12px; cursor:pointer; margin-left:auto; padding-left:4px; }

/* ① 头卡 */
.hn{ display:flex; align-items:center; gap:7px; min-width:0; }
.fname{ font-size:16px; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.hn .code{ flex:0 0 auto; font-size:11.5px; font-weight:600; line-height:18px; padding:0 7px; border-radius:6px;
  color:var(--brand); background:var(--brand-soft); letter-spacing:.3px; }
.hn .kind{ flex:0 0 auto; font-size:11.5px; font-weight:500; line-height:18px; padding:0 7px; border-radius:6px;
  color:#475569; background:#F1F3F6; }
.navline{ display:flex; align-items:baseline; gap:10px; margin-top:10px; flex-wrap:wrap; }
.navv{ font-size:30px; font-weight:700; line-height:1.1; letter-spacing:-.5px; }
.chg{ font-size:16px; font-weight:600; }
.asof{ font-size:12px; color:var(--muted); margin-left:auto; }
.tags{ display:flex; flex-wrap:wrap; gap:6px; margin-top:12px; }
.tags span{ font-size:11.5px; color:#475569; background:#F4F6F9; border-radius:6px; padding:3px 8px; line-height:1.4; }
.warn{ margin:10px 0 0; font-size:12px; color:#92400E; background:#FFFBEB; border-radius:8px; padding:6px 10px; }

/* 卡片标题：只有一个词，不带副标题 */
.st{ font-size:14px; font-weight:600; color:var(--ink); margin-bottom:10px; }

/* ② 图下一行区间指标：等分列 + 居中（CLAUDE.md「KPI 行对齐」） */
.kpi4{ display:grid; grid-template-columns:repeat(4,1fr); gap:8px; padding-top:12px; margin-top:6px; border-top:1px solid var(--line); }
.kpi4 > div{ min-width:0; text-align:center; }
.kpi4 span{ display:block; font-size:11.5px; color:var(--muted); white-space:nowrap; }
.kpi4 b{ display:block; font-size:15px; margin-top:3px; }
.sparse{ font-size:12px; color:#92400E; background:#FFFBEB; border-radius:8px; padding:7px 10px; margin:8px 0; line-height:1.6; }

/* ③ 阶段涨幅 */
.stage-grid{ display:grid; grid-template-columns:repeat(8,1fr); column-gap:8px; row-gap:12px; }
.stage-grid > div{ min-width:0; text-align:center; }
.stage-grid span{ display:block; font-size:11.5px; color:var(--muted); }
.stage-grid b{ display:block; font-size:14px; margin-top:3px; }

/* ④ 收益日历：标题 + 月份翻页 + 日/月/年 同一行 */
.ch{ display:flex; align-items:center; gap:10px; margin-bottom:10px; }
.ch .st{ margin:0; }
.ch .seg2{ margin-left:auto; }
.nav{ display:flex; align-items:center; gap:4px; font-size:13px; margin-left:auto; }
.nav + .seg2{ margin-left:8px; }
.nav .van-icon{ cursor:pointer; padding:4px; } .nav .dis{ opacity:.25; cursor:default; }
.wk{ display:grid; grid-template-columns:repeat(7,1fr); font-size:11px; color:var(--muted); text-align:center; margin:0 0 4px; }
.grid7{ display:grid; grid-template-columns:repeat(7,1fr); gap:6px; }
.grid3{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; }
/* 没数据的日子（周末 / 还没到）不铺底色，只有真实涨跌才上色，免得一整屏灰块 */
.cell{ border-radius:9px; background:transparent; min-height:44px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:3px; }
.cell.big{ min-height:58px; }
.cell.empty{ background:transparent; }
.cell.flat{ background:#F4F6F9; }
.cell.nodata .dd{ color:#B6BFCC; }
.cell.pos{ background:#FDECEC; } .cell.pos .dv{ color:var(--up); }
.cell.neg{ background:#E7F6EC; } .cell.neg .dv{ color:var(--down); }
.dd{ font-size:11.5px; color:var(--sub); } .dv{ font-size:11.5px; font-weight:600; }
.cell.big .dd{ font-size:12.5px; } .cell.big .dv{ font-size:13px; }

/* ⑤ 基金档案：标签列固定宽、值左对齐，两组并排；费率占整行 */
.kv{ display:grid; grid-template-columns:64px 1fr 64px 1fr; column-gap:12px; row-gap:9px; margin:0; font-size:12.5px; line-height:1.5; }
.kv dt{ color:var(--muted); }
.kv dd{ margin:0; color:var(--ink); min-width:0; }
.kv dd.wide{ grid-column:2 / -1; }

/* 多只对比 */
.cmp-empty{ font-size:12px; color:var(--muted); margin:2px 0 0; line-height:1.7; }
.cmp-add{ margin-left:2px; padding:0; border:0; background:none; color:var(--brand); font-size:12px;
  font-weight:600; text-decoration:underline; text-underline-offset:2px; cursor:pointer; }
.picked{ display:flex; flex-wrap:wrap; gap:8px; padding:6px 0 0; }
.picked .chip{ display:inline-flex; align-items:center; gap:5px; max-width:210px; cursor:default; }
.picked .chip .cn{ min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.picked .chip .x{ flex:0 0 auto; display:inline-flex; align-items:center; justify-content:center;
  width:18px; height:18px; margin-right:-3px; padding:0; border:0; border-radius:50%;
  background:transparent; color:var(--muted); font:inherit; font-size:14px; line-height:1; cursor:pointer; }
.picked .chip .x:hover{ background:rgba(15,23,42,.08); color:var(--ink); }
.picked .chip .x:focus-visible{ outline:2px solid var(--brand); outline-offset:1px; }
.stage-tbl td:first-child .nm{ display:inline-block; max-width:150px; vertical-align:bottom;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.stage-tbl-wrap{ overflow-x:auto; }
.stage-tbl{ width:100%; min-width:720px; border-collapse:collapse; font-size:12px; }
.stage-tbl th, .stage-tbl td{ padding:7px 8px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }
.stage-tbl th:first-child, .stage-tbl td:first-child{ text-align:left; padding-left:2px; }
.stage-tbl th{ font-size:11px; color:var(--muted); font-weight:500; }
.stage-tbl td:first-child{ color:var(--ink); }

@media (max-width:700px){
  .navv{ font-size:28px; }
  .stage-grid{ grid-template-columns:repeat(4,1fr); }
  .kv{ grid-template-columns:64px 1fr; }
  .kv dd.wide{ grid-column:2; }
  .cell{ min-height:42px; } .dv{ font-size:10px; }
}
@media (max-width:400px){
  .kpi4 b{ font-size:14px; }
  .kpi4 span{ font-size:11px; }
}
</style>
