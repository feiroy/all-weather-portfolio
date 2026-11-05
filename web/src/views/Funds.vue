<template>
  <div class="page no-tab">
    <SubBar title="基金检索" :fallback="`/a/${aid}/market`" />
    <div class="wrap narrow">
      <div class="seg2 mode">
        <button :class="{ on: mode === 'one' }" @click="mode = 'one'">单只走势</button>
        <button :class="{ on: mode === 'cmp' }" @click="mode = 'cmp'">多只对比</button>
      </div>

      <template v-if="mode === 'one'">
        <van-search v-model="q" placeholder="基金名称或 6 位代码，比如 沪深300 / 000961" shape="round" class="sb" />
        <van-loading v-if="loading" style="margin:24px 0" vertical>查找中…</van-loading>
        <van-cell-group inset v-else-if="rows.length">
          <van-cell v-for="r in rows" :key="r.code" :title="r.name" :label="r.code" is-link
                    :to="`/a/${aid}/market/fund/${r.code}`">
            <template #value><span class="src">{{ r.src }}</span></template>
          </van-cell>
        </van-cell-group>
        <p v-else-if="q.trim()" class="empty-tip">没找到。试试换个关键词，或直接输入 6 位代码</p>
        <template v-else>
          <div class="card def">
            <div class="dh"><b>默认关注</b><span>点下面的资产可切换</span></div>
            <div class="chips defs">
              <span v-for="f in favs" :key="f.code" class="chip" :class="{ on: defCode === f.code }" @click="defCode = f.code">{{ f.short }}</span>
            </div>
            <div class="dn">{{ defInfo?.name || '加载中…' }} <small class="num">{{ defCode }}</small></div>
            <div class="dv">
              <div><span>最新单位净值</span><b class="num">{{ defInfo?.last?.toFixed(4) ?? '—' }}</b></div>
              <div><span>单日</span><b class="num" :class="tone(defInfo?.day)">{{ pct(defInfo?.day) }}</b></div>
              <div><span>截至</span><b class="num">{{ defInfo?.asof?.replace(/-/g, '/') ?? '—' }}</b></div>
            </div>
            <div class="chips rr">
              <span v-for="r in defRanges" :key="r.k" class="chip" :class="{ on: defRange === r.k }" @click="defRange = r.k">{{ r.k }} {{ defRet(r.m) }}</span>
            </div>
            <LineChart :dates="defSeg.dates" :values="defSeg.values" :height="170" unit=""
                       :fmt-tip="i => `${defSeg.dates[i]}<br/>净值 <b>${defSeg.values[i]?.toFixed(4)}</b>`" />
            <router-link class="goto" :to="`/a/${aid}/market/fund/${defCode}`">查看完整走势 <van-icon name="arrow" /></router-link>
          </div>
          <template v-if="recent.length">
            <div class="sec-t"><span>最近看过</span><a class="clr" @click="clear">清空</a></div>
            <div class="chips"><router-link v-for="r in recent" :key="r.code" class="chip" :to="`/a/${aid}/market/fund/${r.code}`">{{ r.name }}</router-link></div>
          </template>
        </template>
      </template>

      <template v-else>
        <div class="card cmp">
          <div class="ct"><b>已选 {{ picked.length }} / 4 只</b><a v-if="picked.length" @click="clearPicked">清空</a></div>
          <div class="chips picked" v-if="picked.length">
            <span v-for="p in picked" :key="p.code" class="chip on" @click="drop(p.code)">{{ p.name }} ×</span>
          </div>
          <van-search v-model="cq" placeholder="搜索基金加入对比（最多 4 只）" shape="round" />
          <van-cell-group inset v-if="opts.length">
            <van-cell v-for="r in opts" :key="r.code" :title="r.name" :label="r.code" clickable @click="pick(r)">
              <template #value><van-icon name="plus" /></template>
            </van-cell>
          </van-cell-group>
          <div class="chips rr" v-if="picked.length >= 2">
            <span v-for="r in ranges" :key="r.k" class="chip" :class="{ on: range === r.k }" @click="range = r.k">{{ r.k }}</span>
          </div>
          <MultiLine v-if="picked.length >= 2 && Object.keys(cmpSeries).length >= 2" :series="cmpSeries" :height="260" />
          <p v-else class="empty-tip">再选 {{ Math.max(0, 2 - picked.length) }} 只就能同图对比（按区间起点归一到 0%）</p>
        </div>
      </template>
    </div>
  </div>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { showFailToast } from 'vant'
import { get } from '../api'
import { pct, tone } from '../fmt'
import LineChart from '../components/LineChart.vue'
import SubBar from '../components/SubBar.vue'
import MultiLine from '../components/MultiLine.vue'
const aid = useRoute().params.aid
const mode = ref('one')
const q = ref(''), rows = ref([]), loading = ref(false)
const recent = ref(JSON.parse(localStorage.getItem('aw-recent-funds') || '[]'))
let t = null
watch(q, v => {
  clearTimeout(t)
  if (!v.trim()) { rows.value = []; return }
  t = setTimeout(async () => {
    loading.value = true
    try {
      const r = (await get(`/api/market/fund-search?q=${encodeURIComponent(v.trim())}`)).rows
      rows.value = r.length || !/^\d{6}$/.test(v.trim()) ? r : [{ code: v.trim(), name: `代码 ${v.trim()}`, src: '直接查' }]
    } finally { loading.value = false }
  }, 300)
}, { immediate: true })
const clear = () => { localStorage.removeItem('aw-recent-funds'); recent.value = [] }

// 默认关注：打开检索页就显示沪深300 ETF，可一键切到其它主要资产
const favs = [
  { code: '510300', short: '沪深300' }, { code: '513500', short: '标普500' },
  { code: '518850', short: '黄金' }, { code: '511260', short: '10年国债' },
  { code: '511130', short: '30年国债' }, { code: '159980', short: '有色' },
  { code: '501018', short: '原油' }, { code: '511220', short: '城投债' },
]
const defCode = ref('510300')
const defData = ref(null), defRange = ref('近1年')
const defRanges = [{ k: '近1月', m: 1 }, { k: '近3月', m: 3 }, { k: '近1年', m: 12 }, { k: '近3年', m: 36 }, { k: '全部', m: 0 }]
watch(defCode, async c => {
  localStorage.setItem('aw-def-fund', c)
  defData.value = null
  try { defData.value = await get(`/api/market/fund/${c}`) } catch { /* 拉不到就留空 */ }
}, { immediate: true })
const defInfo = computed(() => {
  const n = defData.value
  if (!n?.values?.length) return null
  const v = n.values, last = v[v.length - 1], prev = v[v.length - 2]
  return { name: n.name, last, day: prev ? (last / prev - 1) * 100 : null, asof: n.dates[n.dates.length - 1] }
})
function segOf(m) {
  const n = defData.value
  if (!n?.dates?.length) return { dates: [], values: [] }
  if (!m) return n
  const end = new Date(n.dates[n.dates.length - 1]); end.setMonth(end.getMonth() - m)
  const i = Math.max(0, n.dates.findIndex(x => x >= end.toISOString().slice(0, 10)))
  return { dates: n.dates.slice(i), values: n.values.slice(i) }
}
const defSeg = computed(() => segOf(defRanges.find(r => r.k === defRange.value).m))
function defRet(m) {
  const v = segOf(m).values
  return v.length > 1 && v[0] ? pct((v[v.length - 1] / v[0] - 1) * 100) : ''
}

// 多只对比：每只单独取净值，按所选区间起点归一到 0%
const picked = ref(JSON.parse(localStorage.getItem('aw-cmp') || '[]'))
const navs = ref({}), cq = ref(''), opts = ref([]), range = ref('近1年')
const ranges = [{ k: '近1月', m: 1 }, { k: '近3月', m: 3 }, { k: '近1年', m: 12 }, { k: '近3年', m: 36 }, { k: '全部', m: 0 }]
let t2 = null
watch(cq, v => {
  clearTimeout(t2)
  if (!v.trim()) { opts.value = []; return }
  t2 = setTimeout(async () => {
    const r = (await get(`/api/market/fund-search?q=${encodeURIComponent(v.trim())}`)).rows
    opts.value = r.length || !/^\d{6}$/.test(v.trim()) ? r : [{ code: v.trim(), name: `代码 ${v.trim()}`, src: '直接加' }]
  }, 300)
})
watch(picked, v => localStorage.setItem('aw-cmp', JSON.stringify(v)), { deep: true })
async function pick(r) {
  if (picked.value.length >= 4) return showFailToast('最多对比 4 只')
  if (picked.value.some(p => p.code === r.code)) return
  picked.value = [...picked.value, { code: r.code, name: r.name }]
  opts.value = []; cq.value = ''
  try { const d = await get(`/api/market/fund/${r.code}`); navs.value = { ...navs.value, [r.code]: d } }
  catch (e) { showFailToast(e.message) }
}
function drop(code) { picked.value = picked.value.filter(p => p.code !== code) }
function clearPicked() { picked.value = []; navs.value = {} }
// 已选但本会话还没取过净值的，补取
watch(picked, async v => {
  for (const p of v) if (!navs.value[p.code]) {
    try { const d = await get(`/api/market/fund/${p.code}`); navs.value = { ...navs.value, [p.code]: d } } catch { /* 拉不到就不画这一条 */ }
  }
}, { immediate: true })
const cmpSeries = computed(() => {
  const out = {}
  for (const p of picked.value) {
    const n = navs.value[p.code]
    if (!n || !n.dates?.length) continue
    const m = ranges.find(r => r.k === range.value).m
    let i0 = 0
    if (m) {
      const end = new Date(n.dates[n.dates.length - 1]); end.setMonth(end.getMonth() - m)
      const s = end.toISOString().slice(0, 10)
      i0 = Math.max(0, n.dates.findIndex(x => x >= s))
    }
    const dates = n.dates.slice(i0), vals = n.values.slice(i0)
    if (vals.length < 2 || !vals[0]) continue
    out[p.name] = { dates, ret: vals.map(v => +((v / vals[0] - 1) * 100).toFixed(3)) }
  }
  return out
})
</script>
<style scoped>
.narrow{ max-width:960px !important; }
.mode{ display:flex; margin:12px 12px 0; width:fit-content; }
.sb{ background:transparent; padding:10px 12px; }
.src{ font-size:12px; color:var(--muted); }
.clr{ color:var(--brand); cursor:pointer; }
.chips{ flex-wrap:wrap; } .chips a{ text-decoration:none; }
.cmp{ padding:12px 0; }
.ct{ display:flex; justify-content:space-between; align-items:baseline; padding:0 14px; font-size:15px; }
.ct a{ font-size:12.5px; color:var(--brand); cursor:pointer; }
.picked, .rr{ padding:10px 12px 0; }
.def{ padding:14px 16px 12px; }
.dh{ display:flex; justify-content:space-between; align-items:baseline; font-size:14px; }
.dh span{ font-size:11.5px; color:var(--muted); }
.defs{ padding:10px 0 0; flex-wrap:wrap; }
.dn{ font-size:15px; font-weight:600; margin-top:12px; }
.dn small{ font-size:12px; color:var(--muted); font-weight:400; margin-left:6px; }
.dv{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-top:8px; }
.dv span{ display:block; font-size:11.5px; color:var(--muted); }
.dv b{ display:block; font-size:16px; margin-top:2px; }
.def .rr{ padding:10px 0 4px; flex-wrap:wrap; }
.def .rr .chip{ font-size:11.5px; }
.goto{ display:inline-flex; align-items:center; gap:3px; margin-top:10px; font-size:13px; color:var(--brand); text-decoration:none; }
</style>
