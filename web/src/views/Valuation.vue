<template>
  <div class="page no-tab">
    <SubBar title="指数估值" :fallback="`/a/${aid}/market`" />
    <div class="wrap">
      <van-skeleton v-if="!d" :row="10" style="padding:16px" />
      <van-empty v-else-if="!d.rows.length" description="还没有估值数据，点「更新数据」拉一次" />
      <template v-else>
        <div class="chips f"><span v-for="m in mkts" :key="m" class="chip" :class="{ on: mkt === m }" @click="mkt = m">{{ m }}</span></div>
        <div class="chips f"><span v-for="l in lvs" :key="l" class="chip" :class="{ on: lv === l }" @click="lv = l">{{ l }}<template v-if="l !== '全部'"> {{ d.rows.filter(r => r.lv === l && (mkt === '全部' || r.mkt === mkt)).length }}</template></span></div>
        <div class="chips f"><span class="chip static">排序</span><span v-for="s in sorts" :key="s.k" class="chip" :class="{ on: sort === s.k }" @click="sort = s.k">{{ s.t }}</span></div>
        <div class="sec-t"><span>{{ rows.length }} 个指数 · 数据日 {{ d.date?.replace(/-/g, '/') }}</span><span>PE 分位 / PB 分位</span></div>
        <van-cell-group inset>
          <van-cell v-for="r in rows" :key="r.code" is-link @click="open(r)">
            <template #title>
              <div class="n1"><b>{{ r.name }}</b><span class="tag" :class="lvCls(r.lv)">{{ r.lv }}</span></div>
              <div class="n2 num">{{ r.mkt }} · 评分 {{ r.sc ?? '—' }}/20 · 距 10 年高点 {{ r.dd == null ? '—' : '-' + r.dd + '%' }}</div>
            </template>
            <template #value>
              <div class="pv num"><b :class="pc(r.pep)">{{ r.pep == null ? '—' : r.pep.toFixed(0) + '%' }}</b> / <b :class="pc(r.pbp)">{{ r.pbp == null ? '—' : r.pbp.toFixed(0) + '%' }}</b></div>
              <div class="n2">{{ r.rt }}</div>
            </template>
          </van-cell>
        </van-cell-group>
        <p class="empty-tip">分位 = 当前估值在近 10 年里的位置，越低越便宜。只作参考，不参与全天候的调仓计算</p>
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
        <LineChart v-else-if="histSeg.dates.length" :dates="histSeg.dates" :values="histSeg.values" :height="220" unit=""
                   :fmt-tip="i => `${histSeg.dates[i]}<br/>${hk.toUpperCase()} <b>${histSeg.values[i]}</b>`" />
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
const mkt = ref('全部'), lv = ref('全部')
const sorts = [{ k: 'default', t: '默认' }, { k: 'score', t: '评分高' }, { k: 'pep', t: 'PE 分位低' },
               { k: 'dd', t: '回撤深' }, { k: 'name', t: '名称' }]
const sort = ref('default')
const ORD = { 低估: 0, 适中: 1, 高估: 2 }
const rows = computed(() => d.value.rows.filter(r => (mkt.value === '全部' || r.mkt === mkt.value) && (lv.value === '全部' || r.lv === lv.value))
  .sort((a, b) => {
    if (sort.value === 'score') return (b.sc ?? 0) - (a.sc ?? 0)
    if (sort.value === 'pep') return (a.pep ?? a.pbp ?? 999) - (b.pep ?? b.pbp ?? 999)
    if (sort.value === 'dd') return (b.dd ?? 0) - (a.dd ?? 0)
    if (sort.value === 'name') return a.name.localeCompare(b.name, 'zh-CN')
    return (ORD[a.lv] - ORD[b.lv]) || ((a.pep ?? a.pbp ?? 50) - (b.pep ?? b.pbp ?? 50))
  }))
const lvCls = l => (l === '低估' ? 'sell' : l === '高估' ? 'buy' : 'gray')
const pc = p => (p == null ? '' : p < 30 ? 'down' : p > 70 ? 'up' : '')
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
.f{ margin-top:10px; }
.chip.static{ background:transparent; border:0; color:var(--muted); cursor:default; }
.n1{ display:flex; align-items:center; gap:6px; font-size:14.5px; } .n1 b{ font-weight:550; }
.n2{ font-size:11.5px; color:var(--muted); margin-top:3px; }
.pv{ font-size:14px; color:var(--muted); } .pv b{ color:var(--ink); }
.pv b.down{ color:var(--down); } .pv b.up{ color:var(--up); }
.pop{ padding:18px 16px 28px; max-width:720px; margin:0 auto; }
.pop h4{ margin:0 0 12px; font-size:17px; display:flex; align-items:center; gap:8px; }
.pg{ display:grid; grid-template-columns:repeat(4,1fr); gap:6px; margin-bottom:14px; }
.pg span{ display:block; font-size:11.5px; color:var(--muted); } .pg b{ display:block; font-size:16px; margin-top:2px; } .pg small{ font-size:11px; color:var(--muted); }
</style>
