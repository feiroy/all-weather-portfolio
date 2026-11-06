<template>
  <div class="page no-tab">
    <SubBar title="指数估值" :fallback="`/a/${aid}/market`" />
    <div class="wrap">
      <van-skeleton v-if="!d" :row="10" style="padding:16px" />
      <van-empty v-else-if="!d.rows.length" description="还没有估值数据，点「更新数据」拉一次" />
      <template v-else>
        <div class="toolbar">
          <div class="chips f">
            <span v-for="m in mkts" :key="m" class="chip" :class="{ on: mkt === m }" @click="mkt = m">{{ m }}</span>
          </div>
          <div class="chips f">
            <span v-for="l in lvs" :key="l" class="chip" :class="{ on: lv === l }" @click="lv = l">{{ l }}<template v-if="l !== '全部'"> {{ d.rows.filter(r => r.lv === l && (mkt === '全部' || r.mkt === mkt)).length }}</template></span>
          </div>
          <van-search v-model="kw" placeholder="指数名称或代码" shape="round" class="sb" />
        </div>
        <div class="meta">数据日 {{ d.date?.replace(/-/g, '/') }} · 百分位为近 10 年 · 共 {{ rows.length }} 个指数</div>

        <!-- 完整估值表：与 Python 版同口径，列内进度条 + 评分徽章 + 表头排序 -->
        <div class="tbl-wrap">
          <table class="vt">
            <thead><tr>
              <th class="l c-nm" @click="sortBy('name')">指数 <i class="ar">{{ ar('name') }}</i></th>
              <th class="c-lv">估值</th>
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
              <tr v-for="r in rows" :key="r.code" @click="open(r)">
                <td class="c-nm"><b>{{ r.name }}</b><small class="num">{{ r.code }} · {{ r.mkt }}</small></td>
                <td class="c-lv"><span class="tag" :class="lvCls(r.lv)">{{ r.lv }}</span></td>
                <td class="r num o2">{{ num(r.pe, 2) }}</td>
                <td class="r c-pct"><div class="pc"><span class="bar"><i :style="bar(r.pep, pctColor(r.pep))"></i></span><b class="num" :class="pc(r.pep)">{{ pnum(r.pep) }}</b></div></td>
                <td class="r num o2">{{ num(r.pb, 2) }}</td>
                <td class="r c-pct pbp"><div class="pc"><span class="bar"><i :style="bar(r.pbp, pctColor(r.pbp))"></i></span><b class="num" :class="pc(r.pbp)">{{ pnum(r.pbp) }}</b></div></td>
                <td class="r num o1">{{ r.dy == null ? '—' : r.dy.toFixed(2) + '%' }}</td>
                <td class="r num o1">{{ r.roe == null ? '—' : r.roe.toFixed(1) + '%' }}</td>
                <td class="r c-dd"><div class="dd"><span class="bar"><i :style="{ width: Math.min(100, r.dd || 0) + '%' }"></i></span><b class="num">{{ r.dd == null ? '—' : '-' + r.dd + '%' }}</b></div></td>
                <td class="l c-sc"><span class="sc" :class="scCls(r.sc)"><b class="num">{{ r.sc ?? '—' }}</b><span class="rt-txt">{{ r.rt }}</span></span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="foot">
          <span>点表头排序 · 点行查看 PE / PB 历史</span>
          <span>评分 = 估值分（0~12，PE/PB 分位取较高者，越低越高分）+ 回撤分（0~8，近 10 年回撤 × 16）· 只作参考，不参与调仓计算</span>
        </div>
      </template>
    </div>
    <van-popup v-model:show="show" position="bottom" round closeable :style="{ maxHeight: '86vh' }">
      <div class="pop" v-if="cur">
        <h4>{{ cur.name }} <span class="tag" :class="lvCls(cur.lv)">{{ cur.lv }}</span></h4>
        <div class="pg">
          <div><span>PE</span><b class="num">{{ cur.pe ?? '—' }}</b><small>{{ cur.pep == null ? '' : `分位 ${cur.pep}%` }}</small></div>
          <div><span>PB</span><b class="num">{{ cur.pb ?? '—' }}</b><small>{{ cur.pbp == null ? '' : `分位 ${cur.pbp}%` }}</small></div>
          <div><span>ROE</span><b class="num">{{ cur.roe ?? '—' }}%</b></div>
          <div><span>距 10 年高点</span><b class="num">{{ cur.dd == null ? '—' : '-' + cur.dd + '%' }}</b></div>
        </div>
        <span class="seg2"><button :class="{ on: hk === 'pe' }" @click="hk = 'pe'">PE 历史</button><button :class="{ on: hk === 'pb' }" @click="hk = 'pb'">PB 历史</button></span>
        <van-loading v-if="!hist" style="margin:30px 0" />
        <LineChart v-else-if="histSeg.dates.length" :dates="histSeg.dates" :values="histSeg.values" :height="220" unit="" :zoom="false"
                   :fmt-tip="i => `${histSeg.dates[i].replace(/-/g, '/')}<br/>${hk.toUpperCase()} <b>${histSeg.values[i]}</b>`" />
        <p v-else class="empty-tip">没有{{ hk.toUpperCase() }}历史</p>
      </div>
    </van-popup>
  </div>
</template>
<script setup>
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { get, peek } from '../api'
import SubBar from '../components/SubBar.vue'
import LineChart from '../components/LineChart.vue'
const aid = useRoute().params.aid
const d = ref(peek('/api/market/valuation') || null)
get('/api/market/valuation').then(x => { d.value = x })
const mkts = ['全部', 'A股', '港股', '海外', '中概'], lvs = ['全部', '低估', '适中', '高估']
const mkt = ref('全部'), lv = ref('全部'), kw = ref('')
// 默认按评分从高到低；同分按 PE 百分位低在前（与 Python 版一致）
const sortKey = ref('sc'), sortDir = ref(-1)
const DESC_FIRST = new Set(['sc', 'dd', 'dy', 'roe'])
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
    if (k === 'name') return sortDir.value * String(x.name || '').localeCompare(String(y.name || ''), 'zh-CN')
    const vx = x[k] == null ? -Infinity : +x[k], vy = y[k] == null ? -Infinity : +y[k]
    const c = (vx - vy) * sortDir.value
    return c || ((x.pep ?? 101) - (y.pep ?? 101))
  })
  return a
})
const lvCls = l => (l === '低估' ? 'sell' : l === '高估' ? 'buy' : 'gray')
const num = (v, n) => v == null ? '—' : (+v).toFixed(n)
const pnum = p => p == null ? '—' : p.toFixed(0) + '%'
const pc = p => (p == null ? '' : p < 30 ? 'down' : p > 70 ? 'up' : '')
const pctColor = p => p == null ? '#CBD5E1' : p < 30 ? '#16703B' : p > 70 ? '#C52828' : '#94A3B8'
const bar = (p, color) => ({ width: Math.max(0, Math.min(100, p || 0)) + '%', background: color })
const scCls = s => s == null ? 'r2' : s >= 18 ? 'r0' : s >= 14 ? 'r1' : s >= 10 ? 'r2' : s >= 6 ? 'r3' : 'r4'
const show = ref(false), cur = ref(null), hist = ref(null), hk = ref('pe')
async function open(r) {
  cur.value = r; hist.value = null; show.value = true; hk.value = r.pe ? 'pe' : 'pb'
  hist.value = await get(`/api/market/valuation/${r.code}`)
}
const histSeg = computed(() => {
  const h = hist.value
  if (!h) return { dates: [], values: [] }
  const ix = h[hk.value].map((v, i) => (v == null ? -1 : i)).filter(i => i >= 0)
  return { dates: ix.map(i => h.dates[i]), values: ix.map(i => h[hk.value][i]) }
})
</script>
<style scoped>
.toolbar{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; padding:10px 12px 0; }
.f{ margin:0; }
.sb{ flex:1 1 200px; min-width:160px; background:transparent; padding:0; }
.meta{ font-size:12px; color:var(--muted); padding:10px 12px 8px; }
.tbl-wrap{ overflow-x:auto; background:#fff; border:1px solid var(--line); border-radius:12px; margin:0 12px; }
.vt{ width:100%; min-width:900px; border-collapse:collapse; font-size:12.5px; table-layout:fixed; }
.vt th, .vt td{ padding:9px 8px; border-bottom:1px solid var(--line); white-space:nowrap; }
.vt th:first-child, .vt td:first-child{ padding-left:14px; }
.vt thead th{ position:sticky; top:0; z-index:1; background:#fff; font-size:11.5px; font-weight:500; color:var(--muted); cursor:pointer; user-select:none; }
.vt thead th:hover{ color:var(--brand); }
.vt tbody tr:last-child td{ border-bottom:0; }
.vt tbody tr:hover{ background:#F8FAFC; cursor:pointer; }
.vt .r{ text-align:right; } .vt .l{ text-align:left; }
.ar{ font-style:normal; color:var(--brand); }
.c-nm{ width:15%; } .c-lv{ width:7%; } .c-pe, .c-pb{ width:7%; } .c-pct{ width:12.5%; }
.c-dy{ width:7.5%; } .c-roe{ width:7%; } .c-dd{ width:12.5%; } .c-sc{ width:12%; }
.c-nm b, .c-nm small{ display:block; overflow:hidden; text-overflow:ellipsis; }
.c-nm b{ font-size:13.5px; font-weight:550; color:var(--ink); }
.c-nm small{ font-size:11px; color:var(--muted); margin-top:2px; }
.pc, .dd{ display:flex; align-items:center; justify-content:flex-end; gap:8px; }
.pc .bar, .dd .bar{ flex:0 1 64px; min-width:24px; height:6px; border-radius:999px; background:#EEF2F7; overflow:hidden; }
.pc .bar i, .dd .bar i{ display:block; height:100%; border-radius:999px; }
.dd .bar i{ background:#16703B; }
.pc b, .dd b{ font-weight:600; min-width:48px; text-align:right; color:#334155; }
.pc b.down{ color:var(--down); } .pc b.up{ color:var(--up); }
.sc{ display:inline-flex; align-items:center; gap:6px; border-radius:999px; padding:2px 10px 2px 4px; font-size:12px; font-weight:600; border:1px solid transparent; }
.sc b{ display:inline-flex; align-items:center; justify-content:center; min-width:24px; height:20px; border-radius:999px; font-size:12px; color:#fff; }
.sc.r0{ background:#F0FDF4; color:#166534; border-color:#BBF7D0; } .sc.r0 b{ background:#16703B; }
.sc.r1{ background:#F7FEE7; color:#3F6212; border-color:#D9F99D; } .sc.r1 b{ background:#65A30D; }
.sc.r2{ background:#F8FAFC; color:#475569; border-color:#E2E8F0; } .sc.r2 b{ background:#94A3B8; }
.sc.r3{ background:#FFFBEB; color:#92400E; border-color:#FDE68A; } .sc.r3 b{ background:#D97706; }
.sc.r4{ background:#FEF2F2; color:#991B1B; border-color:#FECACA; } .sc.r4 b{ background:#C52828; }
.foot{ display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; font-size:11.5px; color:var(--muted); line-height:1.6; padding:10px 12px 4px; }
.pop{ padding:18px 16px 28px; max-width:720px; margin:0 auto; }
.pop h4{ margin:0 0 12px; font-size:17px; display:flex; align-items:center; gap:8px; }
.pg{ display:grid; grid-template-columns:repeat(4,1fr); gap:6px; margin-bottom:14px; }
.pg span{ display:block; font-size:11.5px; color:var(--muted); } .pg b{ display:block; font-size:16px; margin-top:2px; } .pg small{ font-size:11px; color:var(--muted); }
/* 窄屏逐级收缩：先去 PE/PB 原值，再去股息率/ROE 与估值标签、PB 分位 */
@media (max-width:900px){
  .vt{ min-width:0; } .o2{ display:none; }
  .c-nm{ width:24%; } .c-pct, .c-dd{ width:15%; } .c-sc{ width:18%; }
}
@media (max-width:620px){
  .o1, .c-lv, .pbp{ display:none; }
  .vt th, .vt td{ padding:8px 4px; }
  .c-nm{ width:34%; } .c-pct{ width:18%; } .c-dd{ width:32%; } .c-sc{ width:16%; }
  .rt-txt{ display:none; }              /* 窄屏只留评分数字，避免徽章被裁 */
  .sc{ padding:2px 4px; }
  .pc .bar, .dd .bar{ flex-basis:22px; min-width:14px; }
  .pc b, .dd b{ min-width:42px; font-size:11.5px; }
  .foot span:last-child{ display:none; }
}
</style>
