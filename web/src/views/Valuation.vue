<template>
  <div class="page no-tab">
    <SubBar title="指数估值" :fallback="`/a/${aid}/market`" />
    <div class="wrap">
      <van-skeleton v-if="!d" :row="10" style="padding:16px" />
      <van-empty v-else-if="!d.rows.length" description="还没有估值数据，点「更新数据」拉一次" />
      <template v-else>
        <!-- 标题已由顶部 SubBar 提供，这里只留数据日与口径，避免「指数估值」重复出现 -->
        <div class="heading">
          <span class="hint">数据日 {{ dateText }} · 百分位为近 10 年</span>
        </div>

        <!-- 筛选：市场是一排下划线 tab（导航语义），估值档收成一个下拉，搜索在右侧 -->
        <div class="controls">
          <div class="seg2" role="group" aria-label="市场">
            <button v-for="m in mkts" :key="m" type="button" :class="{ on: mkt === m }" :aria-pressed="mkt === m" @click="mkt = m">{{ m }}</button>
          </div>
          <div class="filters">
            <input v-model="kw" class="q" placeholder="搜索指数名称或代码" autocomplete="off" />
            <label class="lv-pick">
              <select v-model="lv" aria-label="估值档">
                <option value="全部">全部估值</option>
                <option v-for="l in lvs.slice(1)" :key="l" :value="l">{{ l }}</option>
              </select>
              <span class="caret">▾</span>
            </label>
          </div>
        </div>

        <!-- 完整估值表：与 Python 版同口径，列内进度条 + 评分徽章 + 表头排序 + 选中行高亮 -->
        <div class="tbl-wrap">
          <table class="vt">
            <thead><tr>
              <th class="l c-nm" @click="sortBy('name')">指数 <i class="ar">{{ ar('name') }}</i></th>
              <th class="l c-lv" @click="sortBy('lvn')">估值 <i class="ar">{{ ar('lvn') }}</i></th>
              <th class="r c-pe o2" @click="sortBy('pe')">PE <i class="ar">{{ ar('pe') }}</i></th>
              <th class="r c-pct" @click="sortBy('pep')">PE 百分位 <i class="ar">{{ ar('pep') }}</i></th>
              <th class="r c-pb o2" @click="sortBy('pb')">PB <i class="ar">{{ ar('pb') }}</i></th>
              <th class="r c-pct pbp" @click="sortBy('pbp')">PB 百分位 <i class="ar">{{ ar('pbp') }}</i></th>
              <th class="r c-dy o1" @click="sortBy('dy')">股息率 <i class="ar">{{ ar('dy') }}</i></th>
              <th class="r c-roe o1" @click="sortBy('roe')">ROE <i class="ar">{{ ar('roe') }}</i></th>
              <th class="r c-dd" title="当前点位距近 10 年最高点的跌幅" @click="sortBy('dd')">当前回撤 <i class="ar">{{ ar('dd') }}</i></th>
              <th class="l c-sc" title="评分 = 估值分(0~12) + 回撤分(0~8)，满分 20" @click="sortBy('sc')">评分 <i class="ar">{{ ar('sc') }}</i></th>
            </tr></thead>
            <tbody>
              <tr v-for="r in rows" :key="r.code" :class="{ sel: r.code === sel }" @click="picked = r.code">
                <td class="c-nm"><b>{{ r.name }}<span v-if="r.mine" class="mine" :title="`对应本策略资产：${r.mine}`">策略资产</span></b><small class="num">{{ r.code }} · {{ r.mkt }}</small></td>
                <td class="c-lv"><span class="tag" :class="lvCls(r.lv)">{{ r.lv }}</span></td>
                <td class="r num o2">{{ num(r.pe, 2) }}</td>
                <td class="r c-pct"><div class="pc"><span class="bar"><i :style="bar(r.pep, pctColor(r.pep))"></i></span><b class="num" :style="{ color: pctText(r.pep) }">{{ pnum(r.pep) }}</b></div></td>
                <td class="r num o2">{{ num(r.pb, 2) }}</td>
                <td class="r c-pct pbp"><div class="pc"><span class="bar"><i :style="bar(r.pbp, pctColor(r.pbp))"></i></span><b class="num" :style="{ color: pctText(r.pbp) }">{{ pnum(r.pbp) }}</b></div></td>
                <td class="r num o1">{{ num(r.dy, 2, '%') }}</td>
                <td class="r num o1">{{ num(r.roe, 1, '%') }}</td>
                <td class="r c-dd"><div class="dd"><span class="bar"><i :style="{ width: Math.min(100, (r.dd || 0) * 2) + '%' }"></i></span><b class="num">{{ r.dd == null ? '—' : '-' + num(r.dd, 1, '%') }}</b></div></td>
                <td class="l c-sc"><span class="sc" :class="scCls(r.sc)" :title="`估值分 ${r.vs ?? 0}/12 + 回撤分 ${r.ps ?? 0}/8${r.dd == null ? '（缺回撤数据）' : ''}`"><b class="num">{{ r.sc ?? '—' }}</b><span class="rt-txt">{{ r.rt }}</span></span></td>
              </tr>
              <tr v-if="!rows.length"><td colspan="10" class="empty">没有符合条件的指数</td></tr>
            </tbody>
          </table>
        </div>
        <div class="foot">
          <span>共 <b>{{ rows.length }}</b> 个指数 · 低估 <b class="g">{{ nLow }}</b> · 适中 <b>{{ nMid }}</b> · 高估 <b class="r">{{ nHigh }}</b></span>
          <span>评分 = 估值分（0~12，PE/PB 百分位取较高者，越低越高分）+ 回撤分（0~8，近 10 年回撤 × 16）· 点击表头排序 · 点击行查看估值走势</span>
        </div>

        <!-- 详情：选中指数的近 10 年 PE / PB 走势（内嵌在表格下方，不再是弹层） -->
        <div class="detail" v-if="cur">
          <div class="d-head">
            <div class="d-title">{{ cur.name }}<small>{{ cur.code }} · {{ cur.mkt }} · 估值走势<span v-if="!picked">（默认显示列表第一行，点击任意行切换）</span></small></div>
            <!-- 区间按钮与全站统一（原来这是「下划线红字」的第二套样式，同一排按钮两种样子） -->
            <RangeBar :range="vr" @update:range="setVr" />
          </div>
          <div class="d-kpi">
            <div><small>估值</small><b><span class="tag" :class="lvCls(cur.lv)">{{ cur.lv }}</span></b></div>
            <div><small>PE</small><b class="num">{{ num(cur.pe, 2) }}</b></div>
            <div><small>PE 百分位</small><b class="num" :style="{ color: pctText(cur.pep) }">{{ pnum(cur.pep, 1) }}</b></div>
            <div><small>PB</small><b class="num">{{ num(cur.pb, 2) }}</b></div>
            <div><small>PB 百分位</small><b class="num" :style="{ color: pctText(cur.pbp) }">{{ pnum(cur.pbp, 1) }}</b></div>
            <div><small>股息率</small><b class="num">{{ num(cur.dy, 2, '%') }}</b></div>
            <div><small>ROE</small><b class="num">{{ num(cur.roe, 1, '%') }}</b></div>
            <div><small>当前回撤</small><b class="num">{{ cur.dd == null ? '—' : '-' + num(cur.dd, 1, '%') }}</b></div>
            <div><small>评分</small><b><span class="sc" :class="scCls(cur.sc)"><b class="num">{{ cur.sc }}</b><span class="rt-txt">{{ cur.rt }}</span></span></b></div>
          </div>
          <van-loading v-if="histLoading" class="chart-load" />
          <ValuationChart v-else-if="hist && hist.dates && hist.dates.length" :hist="hist" :range="vr" />
          <p v-else class="empty-tip">该指数暂无估值历史</p>
          <div class="amp-row">虚线为该指数近 10 年 30% / 50% / 70% 分位；悬停查看当期数值。</div>
        </div>
      </template>
    </div>
  </div>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { get, peek } from '../api'
import SubBar from '../components/SubBar.vue'
import ValuationChart from '../components/ValuationChart.vue'
import { RANGE_KEYS } from '../utils/series'
import RangeBar from '../components/RangeBar.vue'
const aid = useRoute().params.aid
const d = ref(peek('/api/market/valuation') || null)
get('/api/market/valuation').then(x => { d.value = x })
const mkts = ['全部', 'A股', '港股', '中概', '海外'], lvs = ['全部', '低估', '适中', '高估']
const vranges = RANGE_KEYS
const mkt = ref('全部'), lv = ref('全部'), kw = ref(''), vr = ref('近1月')
const setVr = x => { vr.value = x }
const dateText = computed(() => d.value?.date?.replace(/-/g, '/') || '—')
// 默认按评分从高到低；同分按 PE 百分位低在前（与 Python 版一致）
const sortKey = ref('sc'), sortDir = ref(-1)
const DESC_FIRST = new Set(['sc', 'dd', 'dy', 'roe'])
const LVN = { '低估': 0, '适中': 1, '高估': 2 }
function sortBy(k) {
  if (sortKey.value === k) sortDir.value *= -1
  else { sortKey.value = k; sortDir.value = DESC_FIRST.has(k) ? -1 : 1 }
}
const ar = k => sortKey.value !== k ? '' : sortDir.value < 0 ? '↓' : '↑'
const rows = computed(() => {
  if (!d.value) return []
  const q = kw.value.trim().toLowerCase()
  const a = d.value.rows.filter(r =>
    (mkt.value === '全部' || r.mkt === mkt.value) &&
    (lv.value === '全部' || r.lv === lv.value) &&
    (!q || r.name.toLowerCase().includes(q) || r.code.toLowerCase().includes(q)))
  a.sort((x, y) => {
    const k = sortKey.value
    const vx = k === 'name' ? String(x.name || '') : (k === 'lvn' ? (LVN[x.lv] ?? 1) : (x[k] == null ? -Infinity : +x[k]))
    const vy = k === 'name' ? String(y.name || '') : (k === 'lvn' ? (LVN[y.lv] ?? 1) : (y[k] == null ? -Infinity : +y[k]))
    const c = (typeof vx === 'string' ? vx.localeCompare(vy, 'zh-CN') : vx - vy) * sortDir.value
    return c || ((x.pep ?? 101) - (y.pep ?? 101))
  })
  return a
})
const cnt = lv => rows.value.filter(r => r.lv === lv).length
const nLow = computed(() => cnt('低估')), nMid = computed(() => cnt('适中')), nHigh = computed(() => cnt('高估'))
const lvCls = l => (l === '低估' ? 'sell' : l === '高估' ? 'buy' : 'gray')
const num = (v, n, u = '') => v == null ? '—' : (+v).toFixed(n) + u
const pnum = (p, n = 0) => p == null ? '—' : p.toFixed(n) + '%'
const pctColor = p => p == null ? '#CBD5E1' : p < 30 ? '#16703B' : p > 70 ? '#C52828' : '#94A3B8'
const pctText = p => p == null ? '#94A3B8' : p < 30 ? '#16703B' : p > 70 ? '#C52828' : '#334155'
const bar = (p, color) => ({ width: Math.max(2, Math.min(100, p || 0)) + '%', background: color })
const scCls = s => s == null ? 'r2' : s >= 18 ? 'r0' : s >= 14 ? 'r1' : s >= 10 ? 'r2' : s >= 6 ? 'r3' : 'r4'
// 选中行：默认列表第一行；排序 / 筛选后若已点选的行不在列表里，回退第一行（与 Python 版一致）
const picked = ref(null)
const sel = computed(() => {
  if (!rows.value.length) return null
  if (picked.value && rows.value.some(r => r.code === picked.value)) return picked.value
  return rows.value[0].code
})
const cur = computed(() => rows.value.find(r => r.code === sel.value) || null)
const hist = ref(null), histLoading = ref(false)
let hseq = 0
watch(sel, async code => {
  if (!code) { hist.value = null; return }
  const my = ++hseq
  hist.value = null; histLoading.value = true
  try {
    const x = await get(`/api/market/valuation/${encodeURIComponent(code)}`)
    if (my === hseq) hist.value = x
  } catch {
    if (my === hseq) hist.value = { dates: [], pe: [], pb: [] }
  } finally {
    if (my === hseq) histLoading.value = false
  }
}, { immediate: true })
</script>
<style scoped>
.heading{ display:flex; align-items:center; justify-content:flex-end; gap:12px; padding:14px 12px 4px; }
.hint{ font-size:12px; color:var(--muted); white-space:nowrap; }
/* 筛选：市场是 .seg2 分段控件（和周期/单位同一套，不再是红色下划线 tab），估值档收成下拉，搜索在右侧 */
.controls{ display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; padding:6px 12px 0; }
.filters{ display:flex; align-items:center; gap:8px; }
.q{ font:inherit; font-size:13px; border:1px solid #E2E8F0; border-radius:12px; padding:7px 12px; min-height:36px; width:190px;
  color:#0F172A; background:#fff; box-sizing:border-box; }
.q:focus{ outline:none; border-color:#3B82F6; box-shadow:0 0 0 3px rgba(59,130,246,.12); }
.q::placeholder{ color:#94A3B8; }
.lv-pick{ position:relative; display:inline-flex; align-items:center; }
.lv-pick select{ appearance:none; -webkit-appearance:none; font:inherit; font-size:13px; border:1px solid #E2E8F0; border-radius:12px;
  padding:7px 28px 7px 12px; min-height:36px; background:#fff; color:var(--sub); cursor:pointer; box-sizing:border-box; }
.lv-pick .caret{ position:absolute; right:11px; pointer-events:none; font-size:11px; color:var(--muted); }
/* 与 Python 版一致：表格限高内部滚动 + 表头吸顶，详情曲线紧跟在表格下方，不被 63 行推到页底 */
.tbl-wrap{ overflow:auto; max-height:520px; background:#fff; border:1px solid var(--line); border-radius:12px; margin:12px 12px 0; }
.vt{ width:100%; min-width:900px; border-collapse:collapse; font-size:12.5px; table-layout:fixed; font-variant-numeric:tabular-nums; }
.vt th, .vt td{ padding:9px 8px; height:46px; border-bottom:1px solid var(--line); white-space:nowrap; }
.vt th:first-child, .vt td:first-child{ padding-left:14px; }
.vt thead th{ position:sticky; top:0; z-index:1; background:#fff; font-size:11.5px; font-weight:500; color:var(--muted); cursor:pointer; user-select:none; }
.vt thead th:hover{ color:var(--brand); }
.vt tbody tr:last-child td{ border-bottom:0; }
.vt tbody tr{ cursor:pointer; }
.vt tbody tr:hover{ background:#F8FAFC; }
.vt tbody tr.sel{ background:#EFF6FF; }
.vt tbody tr.sel td:first-child{ box-shadow:inset 3px 0 0 #3B82F6; }
.vt .r{ text-align:right; } .vt .l{ text-align:left; }
.ar{ font-style:normal; color:#C52828; }
.c-nm{ width:15%; } .c-lv{ width:7%; } .c-pe, .c-pb{ width:7%; } .c-pct{ width:12.5%; }
.c-dy{ width:7.5%; } .c-roe{ width:7%; } .c-dd{ width:12.5%; } .c-sc{ width:12%; }
.c-nm b, .c-nm small{ display:block; overflow:hidden; text-overflow:ellipsis; }
.c-nm b{ font-size:13.5px; font-weight:550; color:var(--ink); }
.c-nm small{ font-size:11px; color:var(--muted); margin-top:2px; }
.mine{ font-size:10px; font-weight:500; color:#1E40AF; background:#DBEAFE; border-radius:999px; padding:1px 6px; margin-left:6px; vertical-align:1px; }
.vt .empty{ text-align:center; color:var(--muted); padding:32px; }
.pc, .dd{ display:flex; align-items:center; justify-content:flex-end; gap:8px; }
.pc .bar, .dd .bar{ flex:0 1 64px; min-width:24px; height:6px; border-radius:999px; background:#EEF2F7; overflow:hidden; }
.pc .bar i, .dd .bar i{ display:block; height:100%; border-radius:999px; }
.dd .bar i{ background:#16703B; }
.pc b, .dd b{ font-weight:600; min-width:48px; text-align:right; color:#334155; }
.sc{ display:inline-flex; align-items:center; gap:6px; border-radius:999px; padding:2px 10px 2px 4px; font-size:12px; font-weight:600; border:1px solid transparent; }
.sc b{ display:inline-flex; align-items:center; justify-content:center; min-width:24px; height:20px; border-radius:999px; font-size:12px; color:#fff; }
.sc.r0{ background:#F0FDF4; color:#166534; border-color:#BBF7D0; } .sc.r0 b{ background:#16703B; }
.sc.r1{ background:#F7FEE7; color:#3F6212; border-color:#D9F99D; } .sc.r1 b{ background:#65A30D; }
.sc.r2{ background:#F8FAFC; color:#475569; border-color:#E2E8F0; } .sc.r2 b{ background:#94A3B8; }
.sc.r3{ background:#FFFBEB; color:#92400E; border-color:#FDE68A; } .sc.r3 b{ background:#D97706; }
.sc.r4{ background:#FEF2F2; color:#991B1B; border-color:#FECACA; } .sc.r4 b{ background:#C52828; }
.foot{ display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; font-size:11.5px; color:var(--muted); line-height:1.6; padding:10px 12px 4px; }
.foot b{ color:#475569; font-weight:600; } .foot b.g{ color:#16703B; } .foot b.r{ color:#C52828; }
/* 详情：内嵌在表格下方，9 格 KPI + 双面板 PE/PB 曲线 */
/* 图表区必须是白卡片：和其他页的曲线卡一样（原来只有一条 border-top，图表直接铺在灰底上，
   用户 2026-11-08：「这个为啥没有白色背景，其他曲线都有的」） */
.detail{ background:var(--card); border-radius:14px; margin:12px 12px 0; padding:14px 16px 10px; }
.d-head{ display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; }
.d-title{ font-size:16px; font-weight:650; color:#0F172A; }
.d-title small{ font-size:12px; color:#94A3B8; font-weight:400; margin-left:8px; }
.seg{ display:flex; gap:2px; border-bottom:1px solid var(--line); }
.seg button{ font:inherit; font-size:13px; border:0; border-bottom:2px solid transparent; background:transparent; color:#475569;
  padding:8px 12px; margin-bottom:-1px; cursor:pointer; white-space:nowrap; }
.seg button:hover{ color:#0F172A; }
.seg button.on{ color:#C52828; font-weight:600; border-bottom-color:#C52828; }
/* 9 项固定 9 等分（窄屏 3×3）：flex 自动换行会排成 8+1，「评分」孤零零占一行还留一大片空白 */
.d-kpi{ display:grid; grid-template-columns:repeat(9,1fr); gap:1px; background:#EEF2F7; margin-top:14px;
  border:1px solid #EEF2F7; border-radius:12px; overflow:hidden; }
.d-kpi>div{ padding:10px 8px; background:#fff; min-width:0; box-sizing:border-box; }
@media (max-width:520px){ .d-kpi{ grid-template-columns:repeat(3,1fr); } }
.d-kpi small{ display:block; font-size:11.5px; color:#475569; white-space:nowrap; }
.d-kpi>div>b{ display:block; font-size:17px; font-weight:600; color:#0F172A; font-variant-numeric:tabular-nums; margin-top:4px; line-height:1.4; white-space:nowrap; }
.d-kpi .sc{ font-size:12px; vertical-align:2px; }
.chart-load{ margin:30px 0; }
.empty-tip{ text-align:center; color:var(--muted); padding:28px 0; font-size:13px; }
.amp-row{ font-size:11.5px; color:#94A3B8; padding:6px 2px 0; }
/* 窄屏逐级收缩：先去 PE/PB 原值，再去股息率/ROE 与估值标签、PB 分位 */
@media (max-width:900px){
  .heading{ padding-top:10px; }
  .vt{ min-width:0; } .o2{ display:none; }
  .c-nm{ width:24%; } .c-pct, .c-dd{ width:15%; } .c-sc{ width:18%; }
}
@media (max-width:620px){
  .controls{ flex-direction:column; align-items:stretch; gap:8px; }
  .seg2{ flex-wrap:wrap; row-gap:2px; }
  .seg2 button{ flex:1 0 auto; padding:6px 8px; text-align:center; }
  .filters{ width:100%; } .q{ flex:1; width:auto; min-width:0; }
  .o1, .c-lv, .pbp{ display:none; }
  .tbl-wrap{ max-height:340px; }
  .vt th, .vt td{ padding:8px 4px; }
  .c-nm{ width:34%; } .c-pct{ width:18%; } .c-dd{ width:32%; } .c-sc{ width:16%; }
  .rt-txt{ display:none; }
  .sc{ padding:2px 4px; }
  .pc .bar, .dd .bar{ flex-basis:22px; min-width:14px; }
  .pc b, .dd b{ min-width:42px; font-size:11.5px; }
  .foot span:last-child{ display:none; }
  .d-title small{ display:block; margin:4px 0 0; }
  /* 8 个区间标签窄屏一行放不下：允许换行，别让「全部」被裁到屏幕外 */
  .seg{ flex-wrap:wrap; row-gap:2px; width:100%; }
  .seg button{ padding:8px 7px; font-size:12px; }
  .d-kpi>div{ flex:1 1 33%; padding:9px 8px; box-sizing:border-box; }
  .d-kpi>div>b{ font-size:15px; }
}
</style>
