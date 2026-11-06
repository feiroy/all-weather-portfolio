<template>
  <div class="page no-tab">
    <SubBar title="策略回测" :fallback="`/a/${aid}/market`" />
    <div class="wrap">
      <div class="card ctl">
        <div class="row"><span class="lb">调仓节奏</span>
          <div class="chips"><span v-for="c in cads" :key="c.k" class="chip" :class="{ on: cad === c.k }" @click="cad = c.k">{{ c.t }}</span></div></div>
        <div class="row" v-if="cad !== 'mine'"><span class="lb">起点</span>
          <div class="chips"><span v-for="s in starts" :key="s" class="chip" :class="{ on: start === s }" @click="start = s">{{ s.slice(0, 4) }} 年起</span></div></div>
        <p class="k" v-if="cad === 'mine'">从账户建立那天起，只在你实际有买卖的日子调仓，和「每月末调仓」对照 —— 看你的操作节奏有没有拖后腿</p>
        <p class="k" v-else-if="cad !== 'monthly'">虚线是同策略「每月末调仓」做对照；差值看下表「比月末」</p>
      </div>
      <van-loading v-if="loading" class="ld" vertical>回测计算中…</van-loading>
      <p v-else-if="err" class="empty-tip">{{ err }}</p>
      <div v-else-if="d" class="cols2">
        <div class="metric-grid">
          <div v-for="r in allRows" :key="r.name" class="card rcard" :class="{ base: isBase(r.name) }">
            <div class="r1"><i :style="{ background: colorOf(r.name) }"></i><b>{{ r.name }}</b><span class="k num">调仓 {{ r.n }} 次</span></div>
            <div class="r2">
              <div><span>{{ r.short ? '区间收益' : '年化' }}</span><b class="num" :class="tone(r.short ? r.ret : r.cagr)">{{ pct(r.short ? r.ret : r.cagr) }}</b></div>
              <div><span>最大回撤</span><b class="num down">{{ r.mdd.toFixed(2) }}%</b></div>
              <div><span>{{ r.short ? '波动' : '夏普' }}</span><b class="num">{{ r.short ? r.vol.toFixed(2) + '%' : (r.sharpe ?? '—') }}</b></div>
              <div v-if="r.vs != null"><span>比月末</span><b class="num" :class="tone(r.vs)">{{ signed(r.vs) }}pp</b></div>
            </div>
          </div>
          <p class="k pad" v-if="allRows.some(r => r.short)">不满一年：只看区间收益和波动，年化和夏普没有意义</p>
        </div>
        <div class="card">
          <div class="ct"><b>累计收益</b><span class="k">{{ cad === 'mine' ? '账户建立起' : start.slice(0, 4) + ' 年起' }}</span></div>
          <MultiLine :series="allCurves" :height="320" :colors="colors" :dashed="Object.keys(allCurves).filter(isBase)" />
        </div>
        <van-collapse v-model="showMore" class="more">
          <van-collapse-item name="p" title="月 / 年收益（月末调仓基准）">
            <span class="seg2 pt"><button v-for="p in [['monthly','月度'],['yearly','年度']]" :key="p[0]"
              :class="{ on: pk === p[0] }" @click="pk = p[0]">{{ p[1] }}</button></span>
            <div class="ptab" v-if="shownPeriods.length">
              <div class="ph" :style="gridCols"><span>期间</span><span v-for="s in baseNames" :key="s">{{ s.replace(' · 月末', '') }}</span></div>
              <div v-for="r in shownPeriods" :key="r.k" class="pr" :style="gridCols">
                <span class="num">{{ r.k }}</span>
                <span v-for="x in shownPeriodsRow(r)" :key="x.k" class="num" :class="tone(x.v)">{{ x.v == null ? '—' : pct(x.v) }}</span>
              </div>
            </div>
            <p v-else class="empty-tip">切换一下调仓节奏就能看到对照数据</p>
          </van-collapse-item>
          <van-collapse-item name="g" title="调频影响（相对月末调仓）" v-if="d.gaps?.length">
            <div v-for="g in d.gaps" :key="g.name" class="grow">
              <b>{{ g.name }}</b>
              <span>年化 {{ pct(g.cagr) }} <em :class="tone(g.vs)">{{ signed(g.vs) }}pp</em></span>
              <span>回撤 {{ g.mdd.toFixed(2) }}% <em :class="tone(g.vs_mdd)">{{ signed(g.vs_mdd) }}pp</em></span>
            </div>
            <p class="empty-tip">差值 = 当前节奏 − 月末调仓；绝对值与差值并列，避免只看差多少却不知道原本多少</p>
          </van-collapse-item>
        </van-collapse>
      </div>
      <!-- 策略工厂 · 自定义权重：选基金、填百分比，与内置三策略同起点对比 -->
      <div class="card cp">
        <div class="ct"><b>策略工厂 · 自定义权重</b><span class="k">内置三策略 + 你的组合，同起点对比</span></div>
        <div class="cp-row">
          <span class="lb">策略名</span>
          <input v-model="cpName" class="nm" placeholder="我的组合" maxlength="16" />
          <span class="lb">起点</span>
          <div class="chips"><span v-for="s in starts" :key="s" class="chip" :class="{ on: cpStart === s }" @click="cpStart = s">{{ s.slice(0, 4) }} 年起</span></div>
          <span class="lb">再平衡</span>
          <div class="chips"><span v-for="f in cpFreqs" :key="f.k" class="chip" :class="{ on: cpFreq === f.k }" @click="cpFreq = f.k">{{ f.t }}</span></div>
        </div>
        <div class="cp-w">
          <div v-for="a in cpAssets" :key="a.asset" class="wi">
            <div class="wn"><b>{{ a.name }}</b><small class="num">{{ a.code }}</small></div>
            <div class="wbar"><i :style="{ width: wPct(a.asset) + '%' }"></i></div>
            <div class="win"><input type="number" min="0" max="100" step="1" v-model.number="cpW[a.asset]" /><span>%</span></div>
          </div>
        </div>
        <div class="cp-foot">
          <span :class="{ warn: cpTotal <= 0 }">合计 {{ cpTotal.toFixed(1) }}% · 按合计自动归一到 100%</span>
          <button class="btn" @click="saveCp">保存为我的策略</button>
          <button class="btn primary" :disabled="cpLoading || cpTotal <= 0" @click="runCp">运行对比</button>
        </div>
        <div v-if="cpSavedList.length" class="cp-saved">
          <span class="k">已保存</span>
          <span v-for="n in cpSavedList" :key="n" class="chip" @click="loadCp(n)">{{ n }}<i @click.stop="delCp(n)">×</i></span>
        </div>
        <van-loading v-if="cpLoading" class="ld" vertical>回测计算中…</van-loading>
        <p v-else-if="cpErr" class="empty-tip">{{ cpErr }}</p>
        <div v-else-if="cpRes" class="cp-added">
          <van-icon name="passed" /> 已把「{{ cpRes.name }}」加入上方的指标卡和累计收益曲线，可回到上面看对比。
          <a @click="clearCp">移除</a>
        </div>
      </div>
    </div>
  </div>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { get, post } from '../api'
import { signed, pct, tone } from '../fmt'
import SubBar from '../components/SubBar.vue'
import MultiLine from '../components/MultiLine.vue'
const aid = useRoute().params.aid
const cads = [{ k: 'monthly', t: '每月末' }, { k: 'biweekly', t: '每两周' }, { k: 'weekly', t: '每周' }, { k: 'mine', t: '我的操作日' }]
const starts = ['2015-01-01', '2018-01-01', '2020-01-01', '2023-01-01']
const cad = ref(sessionStorage.getItem('aw-bt-cad') || 'monthly'), start = ref(sessionStorage.getItem('aw-bt-start') || '2015-01-01')
const d = ref(null), loading = ref(false), err = ref('')
watch([cad, start], async () => {
  sessionStorage.setItem('aw-bt-cad', cad.value); sessionStorage.setItem('aw-bt-start', start.value)
  loading.value = true; err.value = ''
  try { d.value = await get(`/api/market/backtest?start=${start.value}&cadence=${cad.value}&acct=${aid}`) }
  catch (e) { err.value = e.message; d.value = null }
  finally { loading.value = false }
}, { immediate: true })
// 同一策略同色：对照组（月末）用虚线
const PAL = { 保守增强: '#1E40AF', 风险平价: '#F59E0B', V3c: '#8B5CF6' }
const colorOf = n => Object.entries(PAL).find(([k]) => n.includes(k))?.[1] || '#64748B'
const isBase = n => cad.value !== 'monthly' && n.endsWith('· 月末')
const custom = ref(null)   // 自定义策略：只把「多出来的那一条」并进主视图，不再另起一套图/卡
const allRows = computed(() => [...(d.value?.rows || []), ...(custom.value ? [custom.value.row] : [])])
const allCurves = computed(() => ({ ...(d.value?.curves || {}),
  ...(custom.value ? { [custom.value.name]: custom.value.curve } : {}) }))
const colors = computed(() => Object.keys(allCurves.value).map(n => n === custom.value?.name ? '#0EA5E9' : colorOf(n)))
const showMore = ref([]), pk = ref('monthly')
const baseNames = computed(() => {
  const a = Object.keys(d.value?.periods?.monthly?.[0]?.v || {})
  const names = a.length ? a : Object.keys(d.value?.periods?.yearly?.[0]?.v || {})
  return custom.value ? [...names, custom.value.name] : names
})
const shownPeriods = computed(() => d.value?.periods?.[pk.value] || [])
const gridCols = computed(() => ({ gridTemplateColumns: `1fr repeat(${baseNames.value.length}, minmax(0,1fr))` }))
// 月/年表里补上自定义策略那一列（值来自 custom-backtest 的 periods）
function shownPeriodsRow(r) {
  return baseNames.value.map(k => ({
    k, v: r.v[k] ?? custom.value?.periods?.[pk.value]?.find(x => x.k === r.k)?.v?.[custom.value.name] ?? null
  }))
}

// ---- 策略工厂 · 自定义权重 ----
const cpAssets = ref([]), cpW = ref({}), cpName = ref('我的组合')
const cpStart = ref('2015-01-01'), cpFreq = ref('M')
const cpFreqs = [{ k: 'M', t: '每月' }, { k: 'Q', t: '每季' }, { k: 'N', t: '不再平衡' }]
const cpLoading = ref(false), cpErr = ref(''), cpRes = ref(null)
const cpColors = ['#1E40AF', '#F59E0B', '#8B5CF6', '#0EA5E9']
get(`/api/acct/${aid}/weights`).then(x => {
  cpAssets.value = (x.rows || []).map(r => ({ asset: r.asset, name: r.name, code: r.code }))
  const n = cpAssets.value.length, base = +(100 / n).toFixed(1)
  cpW.value = Object.fromEntries(cpAssets.value.map((a, i) =>
    [a.asset, i === n - 1 ? +(100 - base * (n - 1)).toFixed(1) : base]))
})
const cpTotal = computed(() => Object.values(cpW.value).reduce((s, v) => s + (Number(v) || 0), 0))
const wPct = k => cpTotal.value > 0 ? Math.max(0, Math.min(100, (Number(cpW.value[k]) || 0) / cpTotal.value * 100)) : 0
const CP_KEY = 'aw-cp-saved'
const cpSaved = ref(JSON.parse(localStorage.getItem(CP_KEY) || '{}'))
const cpSavedList = computed(() => Object.keys(cpSaved.value))
function saveCp() {
  const n = (cpName.value || '').trim()
  if (!n) { cpErr.value = '先给策略起个名字'; return }
  if (cpTotal.value <= 0) { cpErr.value = '权重合计必须大于 0'; return }
  cpSaved.value = { ...cpSaved.value, [n]: { weights: { ...cpW.value }, start: cpStart.value, freq: cpFreq.value } }
  localStorage.setItem(CP_KEY, JSON.stringify(cpSaved.value))
  cpErr.value = ''
}
function loadCp(n) {
  const c = cpSaved.value[n]; if (!c) return
  cpW.value = { ...c.weights }; cpStart.value = c.start; cpFreq.value = c.freq; cpName.value = n
}
function delCp(n) {
  const o = { ...cpSaved.value }; delete o[n]
  cpSaved.value = o; localStorage.setItem(CP_KEY, JSON.stringify(o))
}
async function runCp() {
  cpLoading.value = true; cpErr.value = ''
  try {
    const r = await post('/api/market/custom-backtest', {
      weights: cpW.value, start: cpStart.value, freq: cpFreq.value, name: cpName.value.trim() || '我的组合'
    })
    const name = r.rows[r.rows.length - 1].name
    custom.value = { name, row: r.rows[r.rows.length - 1], curve: r.curves[name], periods: r.periods }
    cpRes.value = { name }
  } catch (e) { cpErr.value = e.message; cpRes.value = null }
  finally { cpLoading.value = false }
}
function clearCp() { custom.value = null; cpRes.value = null }
</script>
<style scoped>
.ctl .row{ display:flex; align-items:center; gap:8px; margin-bottom:8px; }
.ctl .chips{ padding:0; }
.lb{ font-size:12.5px; color:var(--muted); flex:0 0 56px; }
.k{ font-size:12px; color:var(--muted); line-height:1.6; margin:0; }
.pad{ margin:8px 18px; }
.ld{ margin:40px 0; }
.rcard{ padding:12px 14px; }
.rcard.base{ background:#FAFAFB; }
.r1{ display:flex; align-items:center; gap:8px; font-size:14.5px; }
.r1 i{ width:10px; height:10px; border-radius:5px; } .r1 .k{ margin-left:auto; }
.r2{ display:grid; grid-template-columns:repeat(4,1fr); gap:6px; margin-top:10px; }
.r2 span{ display:block; font-size:11.5px; color:var(--muted); } .r2 b{ display:block; font-size:15px; margin-top:2px; }
.ct{ display:flex; justify-content:space-between; align-items:baseline; font-size:15px; margin-bottom:8px; }
.more{ margin:16px 12px 0; border-radius:12px; overflow:hidden; }
.more :deep(.van-collapse-item__content){ padding:10px 12px; }
.pt{ margin-bottom:8px; }
.ptab{ font-size:12.5px; }
.ph, .pr{ display:grid; grid-template-columns:1fr repeat(3,minmax(0,1fr)); gap:4px; padding:6px 0; border-bottom:1px solid var(--line); }
.ph{ color:var(--muted); font-size:11.5px; }
.ph span:not(:first-child), .pr span:not(:first-child){ text-align:right; }
.grow{ display:flex; flex-wrap:wrap; gap:6px 14px; padding:8px 0; border-bottom:1px solid var(--line); font-size:12.5px; }
.grow b{ flex:0 0 100%; } .grow em{ font-style:normal; margin-left:4px; }

@media (min-width:900px){
  .metric-grid{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; padding:0 12px; }
  .metric-grid .card{ margin:0; }
  .metric-grid + .k{ grid-column:1/-1; }
}

/* 策略工厂 */
.cp{ margin-top:16px; padding:14px 16px; }
.cp .ct{ display:flex; justify-content:space-between; align-items:baseline; gap:10px; flex-wrap:wrap; }
.cp .ct.sub{ margin:16px 0 6px; font-size:13px; }
.cp-row{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-top:10px; }
.cp-row .lb{ flex:0 0 auto; }
.cp-row .chips{ padding:0; }
.cp-row .nm{ width:120px; border:1px solid var(--line); border-radius:8px; padding:5px 8px; font-size:13px; }
.cp-w{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px 16px; margin-top:14px; }
.wi{ display:flex; align-items:center; gap:8px; min-width:0; }
.wn{ flex:1 1 auto; min-width:0; }
.wn b{ display:block; font-size:12.5px; font-weight:500; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.wn small{ font-size:11px; color:var(--muted); }
.wbar{ flex:0 0 54px; height:6px; border-radius:3px; background:#EEF2F7; overflow:hidden; }
.wbar i{ display:block; height:100%; background:var(--brand); border-radius:3px; }
.win{ flex:0 0 62px; display:flex; align-items:center; gap:2px; }
.win input{ width:46px; border:1px solid var(--line); border-radius:7px; padding:4px 5px; font-size:12.5px; text-align:right; }
.cp-foot{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-top:14px; }
.cp-foot span{ font-size:12px; color:var(--muted); margin-right:auto; }
.cp-foot span.warn{ color:var(--up); }
.btn{ border:1px solid var(--line); background:#fff; color:var(--sub); border-radius:9px; padding:7px 12px; font-size:12.5px; cursor:pointer; }
.btn.primary{ background:var(--brand); border-color:var(--brand); color:#fff; }
.btn:disabled{ opacity:.5; cursor:default; }
.cp-saved{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-top:10px; }
.cp-saved .chip i{ font-style:normal; margin-left:6px; color:var(--muted); }
.cp-added{ display:flex; align-items:center; gap:7px; flex-wrap:wrap; margin-top:12px; padding:9px 11px;
  background:var(--brand-soft); border-radius:9px; font-size:12.5px; color:var(--brand); }
.cp-added a{ margin-left:auto; color:var(--brand); cursor:pointer; text-decoration:underline; }
.cp-note{ margin-top:10px; }
@media (max-width:620px){ .cp-w{ grid-template-columns:1fr; } }
</style>
