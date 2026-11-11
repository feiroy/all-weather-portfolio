<template>
  <div class="page no-tab">
    <SubBar title="策略回测" :fallback="`/a/${aid}/market`" />
    <div class="wrap">
      <div class="card ctl">
        <div class="row"><span class="lb">调仓节奏</span>
          <div class="chips"><span v-for="c in cads" :key="c.k" class="chip" :class="{ on: cad === c.k }" @click="cad = c.k">{{ c.t }}</span></div></div>
        <div class="row" v-if="cad !== 'mine'"><span class="lb">起点</span>
          <select v-model="start" class="yr">
            <option v-for="o in startOpts" :key="o.y" :value="o.v">{{ o.y }} 年起</option>
          </select>
          <span class="k">内置三策略与我的策略统一从这一天开始<template v-if="availYear > 2006">（数据实际从 {{ availText }} 起，再往前没有红利低波 ETF）</template></span></div>
        <p class="k" v-if="cad === 'mine'">从账户建立那天起，只在你实际有买卖的日子调仓，和「每月末调仓」对照 —— 看你的操作节奏有没有拖后腿</p>
        <p class="k" v-else-if="cad !== 'monthly'">虚线是同策略「每月末调仓」做对照；差值看下表「比月末」</p>
      </div>

      <!-- 我的策略：新增 / 编辑 / 删除，保存后与内置三策略统一对比 -->
      <div class="card mine">
        <div class="ct"><b>我的策略</b><button class="btn primary sm" @click="newStrategy">+ 新增策略</button></div>
        <p class="k" v-if="!strategies.length">还没有自定义策略。点「新增策略」自己选基金、配权重，保存后和内置三策略一起对比。</p>
        <div v-else class="slist">
          <div v-for="s in strategies" :key="s.id" class="srow">
            <i :style="{ background: customColor(s.id) }"></i>
            <div class="sinf"><b>{{ s.name }}</b><small class="num">{{ s.funds.length }} 只基金 · {{ methodLabel(s.method) || '固定权重' }} · {{ freqLabel(s.freq, s.method) }}</small></div>
            <a @click="editStrategy(s)">编辑</a>
            <a @click="delStrategy(s)">删除</a>
          </div>
        </div>
        <p class="k" v-if="cpLoading">正在计算我的策略…</p>
        <p class="warn" v-if="cpErr">{{ cpErr }}</p>
        <p class="k" v-if="startNote">注：{{ startNote }}</p>
      </div>

      <van-loading v-if="loading" class="ld" vertical>回测计算中…</van-loading>
      <p v-else-if="err" class="empty-tip">{{ err }}</p>
      <div v-else-if="d" class="cols2">
        <div class="metric-grid">
          <!-- 一个策略一张卡：里面按调仓节奏分行，同一策略的两种方式上下对齐，方便直接比 -->
          <div v-for="g in groups" :key="g.name" class="card scard">
            <div class="r1"><i :style="{ background: colorOf(g.name) }"></i><b>{{ g.name }}</b>
              <span class="k num" v-if="g.rows.length > 1">{{ g.rows.length }} 种节奏</span></div>
            <div class="mblock" v-for="r in g.rows" :key="r.name">
              <div class="vl" v-if="g.rows.length > 1">{{ freqOf(r.name) }}</div>
              <div class="mgrid">
                <div class="m"><i>年化</i><b class="num" :class="tone(r.cagr)">{{ pct(r.cagr) }}<sup v-if="r.short" class="ast">*</sup></b></div>
                <div class="m"><i>最大回撤</i><b class="num down">{{ r.mdd.toFixed(2) }}%</b></div>
                <div class="m"><i>波动</i><b class="num">{{ r.vol != null ? r.vol.toFixed(2) + '%' : '—' }}</b></div>
                <div class="m"><i>夏普</i><b class="num">{{ r.sharpe ?? '—' }}</b></div>
                <div class="m"><i>Calmar</i><b class="num">{{ r.calmar ?? '—' }}</b></div>
                <div class="m"><i>调仓</i><b class="num">{{ r.n }}<em> 次</em></b></div>
              </div>
            </div>
            <div class="spec" v-if="cardSpec[g.name]">
              <div class="sblock">
                <div class="sh"><span class="sk">持仓</span><span class="sn num">{{ cardSpec[g.name].assets.length }} 只</span></div>
                <div class="fchips">
                  <span v-for="(a, i) in cardSpec[g.name].assets" :key="i" class="fchip">{{ a.name }}<i v-if="a.code">{{ a.code }}</i></span>
                </div>
                <div class="sline"><span class="sk">加权</span>
                  <span class="sv"><span v-for="(seg, i) in cardSpec[g.name].logicSegs" :key="i" class="tseg">{{ seg }}</span></span>
                </div>
                <div class="sline" v-if="cardSpec[g.name].bucket">
                  <span class="sk">分桶</span>
                  <span class="sv" :class="{ bkwarn: cardSpec[g.name].bucket.warn }">{{ cardSpec[g.name].bucket.text }}</span>
                </div>
                <div class="sline"><span class="sk">趋势</span>
                  <span class="sv"><span v-for="(seg, i) in cardSpec[g.name].trend" :key="i" class="tseg">{{ seg }}</span></span>
                </div>
              </div>
              <button class="clone" v-if="cardSpec[g.name].builtin" @click="cloneSpec(g.name)">复刻为我的策略</button>
            </div>
            <div class="diff" v-if="g.vs != null">
              <span>年化比月末 <b :class="tone(g.vs)">{{ signed(g.vs) }}pp</b></span>
              <span v-if="g.vsMdd != null">回撤 <b :class="tone(g.vsMdd)">{{ signed(g.vsMdd) }}pp</b></span>
            </div>
          </div>
          <p class="k pad" v-if="anyShort">* 区间不足一年：年化按实际天数换算（仅供参考），夏普不显示</p>
        </div>
        <div class="card">
          <div class="ct"><b>区间涨跌 / 回撤</b><span class="k">基准 {{ (axis[baseIdx] || '').replace(/-/g, '/') }} = 0%；下方面板为距历史最高点的回撤</span></div>
          <!-- 与全站同一套区间控件（原来这页只有调仓节奏，没有时间区间） -->
          <RangeBar :range="range" :period="period" :periods="periods"
                    @update:range="setRange" @update:period="setPeriod" />
          <!-- 双面板共用一条时间轴：上面区间涨跌、下面回撤，拖拽缩放天然同步，只剩一份控件和一条状态行 -->
          <!-- 图例隐藏要往外传：在这张图上关掉一条策略，下面「单期收益」热力图与区间指标小表跟着不显示它 -->
          <MultiLine :series="curvesChg" :second="ddCurves" second-label="回撤"
                     :second-ratio="0.28" :height="400" :colors="colors"
                     :dashed="Object.keys(curvesAgg).filter(isBase)"
                     :window="win" :reset-key="resetKey" group="backtest"
                     :hidden-names="hiddenNames" @update:hidden-names="onLegendHidden" />
          <!-- 曲线下面这张小表：一行一个策略，数值右对齐，别再挤成一条会换行的长句 -->
          <!-- 表头写清口径：这些数都是「当前调仓节奏」的，月末只出现在最后两列的差里 -->
          <p class="rsum-cap">
            区间指标 · <b>{{ cadLabel }}</b>调仓口径<template v-if="rangeStats.some(t => t.cum != null)">（最后两列是与月末对照的差）</template>
          </p>
          <!-- 单节奏（月末）时「与月末的差」恒无值：整列都是「—」就整列去掉，
               别留两列破折号（CLAUDE.md 回测指标卡同一条规矩：单节奏不显示节奏列） -->
          <table class="rsum" v-if="rangeStats.length" :class="{ 'no-opt': !rangeStats.some(t => t.cum != null) }">
            <thead><tr>
              <th>策略</th><th>年化</th><th>最大回撤</th>
              <th class="opt">累计超额</th><th class="opt">比月末回撤</th>
            </tr></thead>
            <tbody>
              <tr v-for="t in rangeStats" :key="t.name">
                <td class="nm"><i :style="{ background: colorOf(t.name) }"></i>{{ t.name }}</td>
                <td class="num" :class="tone(t.ann)">{{ t.ann == null ? '—' : pct(t.ann) }}</td>
                <td class="num down">{{ t.mdd ? t.mdd.toFixed(2) + '%' : '0.00%' }}</td>
                <td class="num opt" :class="tone(t.cum)">{{ t.cum == null ? '—' : signed(t.cum) + 'pp' }}</td>
                <td class="num opt" :class="tone(t.vsMdd)">{{ t.vsMdd == null ? '—' : signed(t.vsMdd) + 'pp' }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="empty-tip">图例上的策略都被关掉了，点图表上方的图例恢复显示</p>
          <p class="rsum-note" v-if="rangeStats.some(t => t.cum != null)">累计超额 = 每期「{{ cadLabel }} − 月末」相加，和下面那行「区间累计」是同一个数；比月末回撤 = 区间最大回撤之差</p>
        </div>
        <div class="card">
          <!-- 不再单独给这图配「日/月/年」控件：跟着上面那套 区间 + 日线/月线/年线 走，全页一套控件 -->
          <div class="ct"><b>单期收益</b><span class="k">每期相对上一期 · 跟随上面的区间与粒度</span></div>
          <p v-if="!barPeriods" class="empty-tip">这个区间不够划分出一期，换个更长的区间试试</p>
          <p v-else-if="!barCount" class="empty-tip">图例上的策略都被关掉了，点上面那张图的图例恢复显示</p>
          <Heatmap v-else :series="barCurves" />
        </div>
        <div class="card" v-if="Object.keys(excessCurves).length">
          <!-- 「多调这几次值不值」：把每期（当前节奏 − 月末）累加起来画成线，在 0 上方就是赚的 -->
          <div class="ct"><b>多调这几次，值不值</b><span class="k">累计（当前节奏 − 月末收益）· 线在 0 上方 = 多调划算</span></div>
          <MultiLine :series="excessCurves" :height="220" :colors="excessColors"
                     :note="period === '日线' ? '日线颗粒度噪声大，切月线看趋势更清楚' : ''" />
          <p class="sum-excess">
            区间累计：
            <span v-for="t in excessTotals" :key="t.name" class="se">
              <i :style="{ background: colorOf(t.name) }"></i>{{ t.name }}
              <b class="num" :class="tone(t.v)">{{ t.v == null ? '—' : signed(t.v) + 'pp' }}</b>
            </span>
          </p>
        </div>

      </div>
    </div>
  </div>
</template>
<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showConfirmDialog } from 'vant'
import { get, post } from '../api'
import { signed, pct, tone } from '../fmt'
import { loadStrategies, saveStrategies } from '../strategyStore'
import { SERIES_COLORS } from '../utils/chartTheme'
import SubBar from '../components/SubBar.vue'
import MultiLine from '../components/MultiLine.vue'
import Heatmap from '../components/Heatmap.vue'
import RangeBar from '../components/RangeBar.vue'
import { aggregate, aggregateSeries, unionDates, windowForRange, rangeStartIndex, rebaseSeries } from '../utils/series'

const aid = useRoute().params.aid
const router = useRouter()
const cads = [{ k: 'monthly', t: '每月末' }, { k: 'biweekly', t: '每两周' }, { k: 'weekly', t: '每周' }, { k: 'mine', t: '我的操作日' }]
// 起点选项按「数据真实可用起点」生成：V7 把红利低波 ETF（512890，2013-12 成立）加进三个
// 内置策略后，策略窗口（pipeline.strategy_window = 它用到的资产全部有收益那天）就落到 2013-12，
// 再摆一串 2006~2012 的选项等于骗人 —— 选了后端照样从 2013 出数（2026-11-09 验收实测三种起点
// 年化/回撤完全相同、n 都是 155 期）。这里等接口回来用曲线首日裁剪，并把实际起点写在旁边。
const cad = ref(sessionStorage.getItem('aw-bt-cad') || 'monthly'), start = ref(sessionStorage.getItem('aw-bt-start2') || '2006-01-01')
const d = ref(null), loading = ref(false), err = ref('')
const availStart = computed(() => {
  let s = ''
  for (const c of Object.values(d.value?.curves || {})) {
    const f = c?.dates?.[0]
    if (f && (!s || f < s)) s = f
  }
  return s
})
const availYear = computed(() => (availStart.value ? +availStart.value.slice(0, 4) : 2006))
const availText = computed(() => (availStart.value ? availStart.value.replace(/-/g, '/') : ''))
const startOpts = computed(() => {
  const y0 = availYear.value
  const n = new Date().getFullYear() - y0 + 1
  return Array.from({ length: n }, (_, i) => ({ y: y0 + i, v: `${y0 + i}-01-01` }))
})
// 只在第一次拿到真实起点时把「早于数据的起点」对齐一次。
// 不能写成「start < 曲线首日就改」：曲线首日本来就等于请求起点 + 1 个交易日（首行收益被丢），
// 逐日比较会一天一天往后追，直接打成无限请求（2026-11-09 实测 start 从 2013-12 一路跳到 2014-03）。
// 对齐到「年首」而不是曲线首日，否则 select 的值和选项对不上（选项是 y-01-01），下拉会显示空白。
let snapped = false
watch(availStart, v => {
  if (snapped || !v) return
  if (v.slice(0, 4) > start.value.slice(0, 4)) { start.value = `${v.slice(0, 4)}-01-01`; snapped = true }
})
// 连续切起点 / 调仓节奏时，只认最后一次请求的结果，避免旧响应回来覆盖新区间
let btSeq = 0
watch([cad, start], async () => {
  const seq = ++btSeq
  sessionStorage.setItem('aw-bt-cad', cad.value); sessionStorage.setItem('aw-bt-start2', start.value)
  loading.value = true; err.value = ''
  try {
    const r = await get(`/api/market/backtest?start=${start.value}&cadence=${cad.value}&acct=${aid}`)
    if (seq !== btSeq) return
    d.value = r
  } catch (e) {
    if (seq !== btSeq) return
    err.value = e.message; d.value = null
  } finally {
    if (seq === btSeq) loading.value = false
  }
}, { immediate: true })

// ---- 我的策略：多条自定义策略并入同一套指标卡 / 曲线 / 月年表 ----
const strategies = ref(loadStrategies()), customs = ref([])
const cpLoading = ref(false), cpErr = ref('')
const freqLabel = (f, method) => {
  const fixed = { M: '每月再平衡', Q: '每季再平衡', N: '不再平衡' }
  const dyn = { M: '每月', B: '每两周', W: '每周' }
  return (method && method !== 'fixed' ? dyn[f] : fixed[f]) || '每月再平衡'
}
const methodLabel = m => ({ fixed: '固定权重', inverse_vol: '逆波动率', risk_parity: '风险平价' })[m] || ''
const CUSTOM_PAL = ['#0EA5E9', '#DB2777', '#059669', '#D97706', '#7C3AED', '#0891B2']
const customColor = id => CUSTOM_PAL[Math.max(0, strategies.value.findIndex(s => s.id === id)) % CUSTOM_PAL.length]

let cpSeq = 0
async function refreshCustoms() {
  const seq = ++cpSeq
  const list = loadStrategies()
  strategies.value = list
  if (!list.length) { customs.value = []; cpErr.value = ''; cpLoading.value = false; return }
  cpLoading.value = true; cpErr.value = ''
  try {
    const rs = await Promise.all(list.map(async s => {
      try {
        const r = await post('/api/market/custom-backtest', {
          funds: s.funds.map(f => ({ key: f.key, weight: f.weight, name: f.name, code: f.code })),
          start: start.value, freq: s.freq || 'M', name: s.name,
          // 策略工厂参数：加权方式 / 窗口 / 上限 / 现金 / 三组趋势过滤窗口
          method: s.method || 'fixed', window: s.window ?? 20,
          max_w: s.max_w ?? 0.25, min_w: s.min_w ?? 0.02, cash_ratio: s.cash_ratio ?? 0,
          target_vol: s.target_vol ?? null,
          trend_map: s.trend_map || null,     // 逐资产窗口：{资产key: SMA 天数}
          rp_buckets: s.rp_buckets || null,   // 仅风险平价复刻时带分桶结构
          safe_asset: s.safe_asset || 'credit' // 趋势过滤的避风港（默认城投债）
        })
        return { id: s.id, name: s.name, r }
      } catch (e) { return { id: s.id, name: s.name, err: e.message } }
    }))
    if (seq !== cpSeq) return
    const out = [], errs = []
    for (const x of rs) {
      if (x.err) { errs.push(`${x.name}：${x.err}`); continue }
      const r = x.r, row = r.rows[r.rows.length - 1]
      out.push({ id: x.id, name: x.name, row, curve: r.curves[x.name],
                 periods: r.periods, startActual: r.start_actual,
                 bucketInfo: r.bucket_info || null })   // 实际生效的分桶，卡片按它显示，不再照抄配置
    }
    customs.value = out
    cpErr.value = errs.join('；')
  } finally {
    if (seq === cpSeq) cpLoading.value = false
  }
}
onMounted(refreshCustoms)
// 切起点时先撤掉旧区间的自定义曲线，否则旧日期会把 x 轴并集拉回旧年份，看着像没切
watch(start, () => { customs.value = []; refreshCustoms() })

function newStrategy() { router.push(`/a/${aid}/market/strategy-new`) }
// ---- 内置策略的持仓与设置：让用户照着抄参数 ----
const specMap = computed(() => d.value?.specs || {})
const baseName = n => String(n).replace(/ · (双周|每周|月末|我的操作日)$/, '')
const specOf = n => specMap.value[baseName(n)]
const shortName = n => String(n || '').replace(/（.*?）/g, '').replace(/\s*ETF\s*$/, '').trim()
// 返回分段的数组：模板用 .tseg（inline-block + nowrap）渲染，
// 折行时整段一起换，不会把「波动≤9%」从中间劈成两行（2026-11-09 截图验收发现）
const logicLine = sp => {
  const m = sp.method_key === 'risk_parity' ? '分层RP(4桶)' : '逆波动率'
  const parts = [m, `${sp.window}日`, `≤${Math.round(sp.max_w * 100)}%`]
  if (sp.target_vol) parts.push(`波动≤${Math.round(sp.target_vol * 100)}%`)
  return parts
}
// 分段之间挂「·」，但把分隔符并进前一段（.tseg 是 nowrap），折行时不会单独落一个点
const joinSegs = parts => parts.map((p, i) => (i < parts.length - 1 ? `${p} ·` : p))
const trendSegs = sp => {
  const t = sp.trend || {}
  const out = []
  if (t.commodity) out.push(`有色${t.commodity}`)
  if (t.ene) out.push(`能化${t.ene}`)
  if (t.gold) out.push(`黄金${t.gold}`)
  if (t.equity?.length) {
    const short = { hs300: '沪深300', us_sp500: '标普', divlow: '红利低波' }
    const win = [...new Set(t.equity.map(e => e.window))]
    if (win.length === 1) out.push(`权益${win[0]}`)
    else t.equity.forEach(e => out.push(`${short[e.key] || assetName(e.key)}${e.window}`))
  }
  // 趋势过滤必然有个避风港承接权重（内置三策略都是城投债 ETF）
  return out.length ? [...out, '避风港 城投债'] : ['不做趋势过滤']
}
const assetName = k => ({ hs300: '沪深300', us_sp500: '标普500', credit: '城投债', bond_10y: '10年国债',
  bond_30y: '30年国债', gold: '黄金', nonferr: '有色', ene: '能化', divlow: '红利低波' }[k] || k)
const bucketText = bks => bks ? `${Object.keys(bks).length} 桶 · ` +
  Object.entries(bks).map(([b, ks]) => `${b}${ks.length}`).join(' / ') : ''
// 卡片上的「持仓 + 参数」：内置策略来自接口 specs，自定义策略从策略对象 + 实际回测结果现拼（两边同一版式）
const cardSpec = computed(() => {
  const m = {}
  for (const [n, sp] of Object.entries(specMap.value)) {
    const segs = logicLine(sp)
    m[n] = { assets: sp.assets.map(a => ({ name: shortName(a.name), code: a.code })),
             logicSegs: joinSegs(segs), logic: segs.join(' · '), trend: trendSegs(sp),
             bucket: sp.rp_buckets ? { text: bucketText(sp.rp_buckets), warn: false } : null,
             builtin: true }
  }
  for (const s of strategies.value) {
    const run = customs.value.find(c => c.name === s.name)
    if (m[s.name] || !run) continue
    const bi = run.bucketInfo || null
    // 分桶以接口回传的「实际生效结构」为准：改过持仓后可能已经退化，不能再按 s.rp_buckets 显示
    const method = s.method === 'risk_parity'
      ? (bi?.mode === 'fallback' ? '风险平价(每资产一桶)'
         : `分层风险平价(${bi ? bi.count : (s.rp_buckets ? Object.keys(s.rp_buckets).length : 1)}桶)`)
      : s.method === 'fixed' ? '固定权重' : '逆波动率'
    const parts = [method]
    if (s.method !== 'fixed') parts.push(`${s.window ?? 20}日`)
    parts.push(`≤${Math.round((s.max_w ?? 0.25) * 100)}%`)
    if (s.cash_ratio) parts.push(`现金${Math.round(s.cash_ratio * 100)}%`)
    if (s.target_vol) parts.push(`波动≤${Math.round(s.target_vol * 100)}%`)
    const fname = k => s.funds.find(f => f.key === k)?.name || assetName(k)
    const trend = Object.entries(s.trend_map || {}).map(([k, w]) => `${fname(k)}${w}`)
    if (trend.length) trend.push(`避风港 ${shortName(fname(s.safe_asset || 'credit'))}`)
    const bucket = bi ? { text: bi.mode === 'fallback'
        ? `已退化为 ${bi.count} 桶（每资产一桶），与配置的分桶不一致`
        : bucketText(bi.buckets), warn: bi.mode === 'fallback' } : null
    m[s.name] = { assets: s.funds.map(f => ({ name: f.name || assetName(f.key), code: /^\d{6}$/.test(f.key) ? f.key : (f.code || '') })),
                  logicSegs: joinSegs(parts), logic: parts.join(' · '), bucket,
                  trend: trend.length ? trend : ['不做趋势过滤'], builtin: false }
  }
  return m
})
function cloneSpec(n) {
  const sp = specOf(n)
  if (!sp) return
  const w = Math.round(1000 / sp.assets.length) / 10
  // 逐资产窗口：能化/有色/黄金走各自字段，权益走 equity 列表，最终合成一个 {资产key: 窗口}
  const tmap = {}
  const t = sp.trend || {}
  if (t.commodity) tmap.nonferr = t.commodity
  if (t.ene) tmap.ene = t.ene
  if (t.gold) tmap.gold = t.gold
  ;(t.equity || []).forEach(e => { if (e.window) tmap[e.key] = e.window })
  const bucketOf = {}
  Object.entries(sp.rp_buckets || {}).forEach(([b, ks]) => (ks || []).forEach(k => { bucketOf[k] = b }))
  const tpl = {
    name: baseName(n) + ' 副本',
    method: sp.method_key, window: sp.window,
    max_w: sp.max_w, min_w: sp.min_w, cash_ratio: 0,
    target_vol: sp.target_vol || null,
    trend_map: tmap,
    rp_buckets: sp.rp_buckets || null,
    safe_asset: sp.safe_asset || 'credit',   // 内置策略的避风港是城投债
    freq: 'M',
    funds: sp.assets.map(a => ({ key: a.key, code: a.code, name: a.name, weight: w,
                                 trend: tmap[a.key] || 0, bucket: bucketOf[a.key] || '' })),
    note: '已按内置策略逐项填好：加权方式、窗口、上限、每只基金的均线窗口、波动上限' +
      (sp.rp_buckets ? '、分桶结构' : '') + '。增 / 换 / 删基金后请确认每只基金的桶，保存时按当前持仓重新生成分桶。'
  }
  sessionStorage.setItem('aw-strategy-tpl', JSON.stringify(tpl))
  router.push({ path: `/a/${aid}/market/strategy-new`, query: { tpl: '1' } })
}
function editStrategy(s) { router.push({ path: `/a/${aid}/market/strategy-new`, query: { edit: s.id } }) }
async function delStrategy(s) {
  try { await showConfirmDialog({ title: '删除策略', message: `确定删除「${s.name}」吗？` }) }
  catch { return }
  saveStrategies(loadStrategies().filter(x => x.id !== s.id))
  refreshCustoms()
}
const startNote = computed(() => {
  const diff = customs.value.filter(c => c.startActual && c.startActual !== start.value)
  if (!diff.length) return ''
  return diff.map(c => `「${c.name}」因所选基金成立较晚，实际从 ${c.startActual} 开始`).join('；') +
    '。内置三策略也按同一区间计算，保证可比。'
})

// 同一策略同色：对照组（月末）用虚线；自定义策略按保存顺序取色
const PAL = { 保守增强: SERIES_COLORS[0], 风险平价: SERIES_COLORS[1], V3c: SERIES_COLORS[2] }
const colorOf = n => {
  const c = customs.value.find(x => x.name === n)
  return c ? customColor(c.id) : (Object.entries(PAL).find(([k]) => n.includes(k))?.[1] || SERIES_COLORS[4])
}
const isBase = n => cad.value !== 'monthly' && n.endsWith('· 月末')
const allRows = computed(() => [...(d.value?.rows || []), ...customs.value.map(c => c.row)])
// 按策略分组：同一策略的「当前节奏 / 月末」放进同一张卡，上下两行直接比
const groups = computed(() => {
  const m = new Map()
  for (const r of allRows.value) {
    const base = r.name.replace(/ · [^·]+$/, '')
    if (!m.has(base)) m.set(base, [])
    m.get(base).push(r)
  }
  return [...m.entries()].map(([name, rows]) => ({
    name,
    rows: [...rows].sort((a, b) => (isBase(a.name) ? 1 : 0) - (isBase(b.name) ? 1 : 0)),
    vs: rows.find(r => r.vs != null)?.vs ?? null,
    vsMdd: rows.find(r => r.vs_mdd != null)?.vs_mdd ?? null,
  }))
})
const freqOf = n => (n.includes(' · ') ? n.split(' · ').pop() : '')
// 当前调仓节奏的中文名（表头要用它说清「这是哪种节奏的年化」）
const cadLabel = computed(() => ({ monthly: '月末', biweekly: '双周', weekly: '每周', mine: '我的操作日' }[cad.value] || '当前节奏'))
const anyShort = computed(() => allRows.value.some(r => r.short))
const allCurves = computed(() => ({ ...(d.value?.curves || {}),
  ...Object.fromEntries(customs.value.map(c => [c.name, c.curve])) }))
// 图例隐藏（在上面「区间涨跌 / 回撤」图上点掉一条策略）要联动到本页其它读数卡：
// 用户关掉一条 = 「这条我不想看」，那么下面的「单期收益」热力图和区间指标小表就不该还挂着它。
// 状态由 MultiLine 受控传回（它在自己内部维护隐藏集合，包括联动的「N 回撤」）。
const hiddenNames = ref([])
const onLegendHidden = v => { hiddenNames.value = Array.isArray(v) ? v : [] }
const hiddenSet = computed(() => new Set(hiddenNames.value))
// 调仓节奏（或起点）一变，曲线名字换了一批（「· 月末」→「· 双周」），旧的隐藏名单要清掉，
// 否则新名字一个都没被隐藏、图例却还记着上一批，看着像没生效。
watch([cad, start], () => { hiddenNames.value = [] })
const colors = computed(() => Object.keys(curvesAgg.value).map(n => colorOf(n)))
// 时间区间：全站统一 8 档 + 日/月/年线；回测曲线从所选起点起（默认 2006 = 最长可信历史），默认「近1年」
const periods = ['日线', '月线', '年线']
const range = ref('近1年'), period = ref('日线'), bump = ref(0)
const curvesAgg = computed(() => aggregateSeries(allCurves.value, period.value))
const axis = computed(() => unionDates(curvesAgg.value))
const baseIdx = computed(() => rangeStartIndex(axis.value, range.value))
// 曲线以「区间基准日」为 0%：选近1月/今年来才看得出这段时间各策略涨跌差别，
// 否则 Y 轴还是 2019 年起的累计收益（79%~110%），几条线挤成平行线看不出谁猛
const curvesChg = computed(() => rebaseSeries(curvesAgg.value, axis.value, baseIdx.value))
// 回撤 = 相对「历史最高点」的跌幅（水下曲线，越跌越负）。
// 不从区间基准日算：那样往左拖出区间后下方面板会整片空掉，而且最大值要跟卡片的最大回撤对得上。
const ddCurves = computed(() => {
  const ax = axis.value
  const out = {}
  for (const [n, s] of Object.entries(curvesAgg.value)) {
    const m = new Map(s.dates.map((d, i) => [d, s.ret[i]]))
    let peak = 0
    out[n] = { dates: ax.slice(), ret: ax.map(d => {
      const v = m.get(d)
      if (v == null) return null
      const g = 1 + v / 100
      peak = Math.max(peak, g)
      return Math.round((g / peak - 1) * 10000) / 100
    }) }
  }
  return out
})
const win = computed(() => windowForRange(axis.value, range.value))
// 单期收益柱：把区间内的曲线按 日/月/年 取期末值，再算「本期 / 上期 - 1」
// 粒度直接跟页面的「日线/月线/年线」，不再单独一套开关
const barUnit = computed(() => period.value.replace('线', ''))
// 期数只由「区间 + 粒度」决定，与显示哪几条策略无关：全隐藏时不能误报「区间不够划分出一期」
const barPeriods = computed(() => aggregate(axis.value.slice(baseIdx.value), [], barUnit.value).labels.length)
const barCurves = computed(() => {
  const ax = axis.value, b = baseIdx.value
  const out = {}
  for (const [n, s] of Object.entries(curvesAgg.value)) {
    if (hiddenSet.value.has(n)) continue
    const m = new Map(s.dates.map((d, i) => [d, s.ret[i]]))
    const ds = [], vs = []
    for (let i = b; i < ax.length; i++) { const v = m.get(ax[i]); if (v != null) { ds.push(ax[i]); vs.push(v) } }
    const agg = aggregate(ds, vs, barUnit.value)
    const baseVal = m.get(ax[b])              // 区间基准日 = 0%，和上面图表同一口径
    const chg = agg.values.map((v, i) => {
      const prev = i === 0 ? baseVal : agg.values[i - 1]
      if (prev == null || v == null) return null
      return Math.round(((1 + v / 100) / (1 + prev / 100) - 1) * 10000) / 100
    })
    // 真实日期给排序/窗口用，「2026年10月」这种标签只给横轴显示用
    out[n] = { dates: agg.dates, labels: agg.labels, ret: chg }
  }
  return out
})
const barCount = computed(() => Object.keys(barCurves.value).length)   // 热力图里有几条策略（全被图例关掉时是 0）

// 相对月末的超额：同一策略「当前节奏」与「月末」两条曲线，按同一批期间算收益再相减（同策略同色）
const pairs = computed(() => {
  const names = Object.keys(curvesAgg.value)
  const strip = n => n.replace(/ · [^·]+$/, '')
  return names.filter(n => n.includes(' · ') && !isBase(n)).map(n => {
    const base = names.find(x => isBase(x) && strip(x) === strip(n))
    return base ? { name: n, base } : null
  }).filter(Boolean)
})
const excessCurves = computed(() => {
  const ax = axis.value, b = baseIdx.value, unit = barUnit.value
  const periodRet = s => {
    const m = new Map(s.dates.map((d, i) => [d, s.ret[i]]))
    const ds = [], vs = []
    for (let i = b; i < ax.length; i++) { const v = m.get(ax[i]); if (v != null) { ds.push(ax[i]); vs.push(v) } }
    const agg = aggregate(ds, vs, unit)
    const baseVal = m.get(ax[b])
    return { dates: agg.dates, labels: agg.labels,
      ret: agg.values.map((v, i) => {
        const prev = i === 0 ? baseVal : agg.values[i - 1]
        if (prev == null || v == null) return null
        return ((1 + v / 100) / (1 + prev / 100) - 1) * 100
      }) }
  }
  const skip = 0
  const out = {}
  for (const { name, base } of pairs.value) {
    const a = periodRet(curvesAgg.value[name]), c = periodRet(curvesAgg.value[base])
    // 逐期差值累加成「累计超额」：线在 0 上方 = 这段时间多调是赚的，一路往下 = 白折腾
    let acc = 0
    const ret = a.ret.map((v, i) => {
      if (v == null || c.ret[i] == null) return null
      acc += (v - c.ret[i])
      return Math.round(acc * 100) / 100
    })
    out[name.replace(/ · [^·]+$/, '')] = { dates: a.dates.slice(skip), labels: a.labels.slice(skip), ret: ret.slice(skip) }
  }
  return out
})
const excessColors = computed(() => Object.keys(excessCurves.value).map(n => colorOf(n)))
// 所选区间的年化（按区间内的交易日折算），给「区间涨跌」卡片下面直接读数用
// 所选区间的两个数：年化（按真实交易日数折算）与区间最大回撤（区间内从高点的最深跌幅）
const rangeStats = computed(() => {
  const ax = axis.value, b = baseIdx.value
  const raw = unionDates(allCurves.value)
  const i0 = raw.indexOf(ax[b]), i1 = raw.indexOf(ax[ax.length - 1])
  const days = i1 - i0
  if (days < 1) return []
  // 先把所有曲线的区间指标都算出来，再给「当前节奏」配上它自己的月末对照算差
  const one = (n) => {
    const s = curvesAgg.value[n]
    const m = new Map(s.dates.map((d, i) => [d, s.ret[i]]))
    const v0 = m.get(ax[b]), v1 = m.get(ax[ax.length - 1])
    // 区间内最大回撤：只看 base..end 这段，峰值也从 base 起算
    let peak = v0 == null ? null : 1 + v0 / 100
    let mdd = 0
    for (let i = b; i < ax.length; i++) {
      const v = m.get(ax[i])
      if (v == null) continue
      const g = 1 + v / 100
      if (peak == null || g > peak) peak = g
      if (peak > 0) mdd = Math.min(mdd, g / peak - 1)
    }
    const ann = (v0 == null || v1 == null) ? null : (Math.pow((1 + v1 / 100) / (1 + v0 / 100), 252 / days) - 1) * 100
    return { ann, mdd: mdd * 100 }
  }
  const all = {}
  for (const n of Object.keys(curvesAgg.value)) all[n] = one(n)
  const strip = n => n.replace(/ · [^·]+$/, '')
  return Object.keys(curvesAgg.value)
    .filter(n => !isBase(n) && !hiddenSet.value.has(n))
    .map(n => {
      const base = Object.keys(all).find(x => isBase(x) && strip(x) === strip(n))
      const b0 = base ? all[base] : null
      return { name: strip(n), ...all[n],
        // 累计超额直接复用下方「区间累计」那组数（excessTotals），两边永远同一个值
        cum: excessTotals.value.find(x => x.name === strip(n))?.v ?? null,
        vsMdd: b0 ? all[n].mdd - b0.mdd : null }
    })
})
// 每条线的终点值（全区间累计超额），卡片底部直接给数字，不用去读坐标轴
const excessTotals = computed(() => Object.keys(excessCurves.value).map(n => {
  const arr = excessCurves.value[n].ret.filter(v => v != null)
  return { name: n, v: arr.length ? arr[arr.length - 1] : null }
}))
const resetKey = computed(() => `${range.value}|${period.value}|${bump.value}`)
const setRange = r => { if (range.value === r) bump.value++; else range.value = r }
const setPeriod = p => { if (period.value === p) bump.value++; else period.value = p }
const showMore = ref([])
</script>
<style scoped>
.ctl .row{ display:flex; align-items:center; gap:8px; margin-bottom:8px; }
.ctl .chips{ padding:0; }
.lb{ font-size:12.5px; color:var(--muted); flex:0 0 56px; }
.k{ font-size:12px; color:var(--muted); line-height:1.6; margin:0; }
.pad{ margin:8px 18px; }
.ld{ margin:40px 0; }
.yr{ border:1px solid var(--line); border-radius:9px; padding:6px 10px; font-size:13px; color:var(--ink); background:#fff; }
.warn{ font-size:12px; color:var(--up); line-height:1.6; margin:8px 0 0; }
.rcard{ padding:12px 14px; }
.rcard.base{ background:#FAFAFB; }
.r1{ display:flex; align-items:center; gap:8px; font-size:14.5px; }
.r1 i{ width:10px; height:10px; border-radius:5px; } .r1 .k{ margin-left:auto; }
/* 3~4 项：等分列 + 居中；用 auto-fit 而不是写死 4 列，只有 3 项时不会空出一整列 */
.r2{ display:grid; grid-template-columns:repeat(auto-fit,minmax(0,1fr)); gap:8px 14px; margin-top:10px; }
.r2 > div{ min-width:0; text-align:center; }
.r2 span{ display:block; font-size:11.5px; color:var(--muted); } .r2 b{ display:block; font-size:15px; margin-top:2px; }
.ct{ display:flex; justify-content:space-between; align-items:baseline; font-size:15px; margin-bottom:8px; gap:2px 10px; }
/* 窄屏右侧说明太长会把「区间涨跌」挤成两行，标题不许断行 */
.ct > b{ white-space:nowrap; }
.st-sub{ display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; margin:14px 0 6px; font-size:13px; font-weight:500; }
.st-sub span{ font-size:11.5px; font-weight:400; color:var(--muted); }
.more{ margin:16px 12px 0; border-radius:12px; overflow:hidden; }
.more :deep(.van-collapse-item__content){ padding:10px 12px; }
.pt{ margin-bottom:8px; }
.ptab{ font-size:12.5px; overflow-x:auto; }
.ph, .pr{ display:grid; grid-template-columns:1fr repeat(3,minmax(0,1fr)); gap:4px; padding:6px 0; border-bottom:1px solid var(--line); min-width:480px; }
.ph{ color:var(--muted); font-size:11.5px; }
.ph span:not(:first-child), .pr span:not(:first-child){ text-align:right; }
.grow{ display:flex; flex-wrap:wrap; gap:6px 14px; padding:8px 0; border-bottom:1px solid var(--line); font-size:12.5px; }
.grow b{ flex:0 0 100%; } .grow em{ font-style:normal; margin-left:4px; }

/* 指标：3×2 等宽网格 —— 跨卡片同一位置对齐 */
.mblock{ margin-top:2px; }
.mblock + .mblock{ margin-top:10px; padding-top:10px; border-top:1px dashed var(--line); }
.mblock .vl{ font-size:10.5px; color:#94A3B8; margin-bottom:4px; }
.mgrid{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:9px 6px;
  padding:2px 0 10px; border-bottom:1px solid var(--line); }
.mgrid .m{ min-width:0; }
.mgrid .m i{ display:block; font-style:normal; font-size:10px; color:#94A3B8; margin-bottom:3px; white-space:nowrap; }
.mgrid .m b{ display:block; font-size:15px; font-weight:600; line-height:1.25; letter-spacing:-.2px;
  font-variant-numeric:tabular-nums; }
.mgrid .m b em{ font-style:normal; font-size:10px; font-weight:400; color:#94A3B8; }
/* 持仓 / 参数 */
.scard{ display:flex; flex-direction:column; }
.spec{ margin-top:10px; }
.sblock{ background:#F8FAFC; border:1px solid #EEF2F7; border-radius:10px; padding:9px 10px 10px; }
.sblock .sh{ display:flex; align-items:baseline; justify-content:space-between; margin-bottom:6px; }
.sblock .sk{ font-size:10.5px; color:#94A3B8; letter-spacing:.2px; }
.sblock .sn{ font-size:10.5px; color:#94A3B8; }
.fchips{ display:flex; flex-wrap:wrap; gap:4px; margin-bottom:8px; }
.fchip{ display:inline-flex; align-items:baseline; gap:3px; padding:2px 6px; border-radius:6px;
  background:#fff; border:1px solid #E8EEF5; color:#475569; font-size:10.5px; line-height:1.5; white-space:nowrap; }
.fchip i{ font-style:normal; font-size:9.5px; color:#94A3B8; }
.sline{ display:flex; gap:7px; font-size:11px; line-height:1.55; color:#64748B; }
.sline + .sline{ margin-top:3px; }
.sline .sk{ flex:0 0 24px; color:#94A3B8; }
.sline .sv{ flex:1 1 auto; min-width:0; }
.sline .sv.bkwarn{ color:var(--up); }
.sline .tseg{ display:inline-block; white-space:nowrap; margin-right:6px; font-variant-numeric:tabular-nums; }
/* 按钮贴底：三张卡片内容长短不一时，按钮仍在同一水平线 */
.scard .spec{ margin-top:auto; padding-top:10px; }
.clone{ display:block; width:100%; margin-top:9px; padding:7px 0; border:1px solid #DBEAFE; border-radius:8px;
  background:#EFF6FF; color:#2563EB; font-size:11.5px; font-weight:600; cursor:pointer; }
.clone:active{ background:#DBEAFE; }
@media (max-width:420px){
  .mgrid{ gap:8px 4px; }
  .mgrid .m b{ font-size:13.5px; }
  .fchip{ font-size:10px; padding:1px 5px; }
}
/* 我的策略 */
.mine .ct{ align-items:center; }
.btn.sm{ border:1px solid var(--brand); background:var(--brand); color:#fff; border-radius:9px;
  padding:7px 12px; font-size:12.5px; font-weight:600; cursor:pointer; }
.slist{ margin-top:6px; }
.srow{ display:flex; align-items:center; gap:9px; padding:9px 0; border-bottom:1px solid var(--line); }
.srow:last-child{ border-bottom:0; }
.srow i{ flex:0 0 9px; width:9px; height:9px; border-radius:5px; }
.sinf{ flex:1 1 auto; min-width:0; }
.sinf b{ display:block; font-size:13.5px; font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.sinf small{ display:block; font-size:11px; color:var(--muted); margin-top:2px; }
.srow a{ flex:0 0 auto; font-size:12px; color:var(--brand); cursor:pointer; padding:4px 2px; }

/* 策略卡：一个策略一张，内部用两行表格对齐两种节奏 */
.mtab{ width:100%; border-collapse:collapse; font-size:12px; margin-top:10px; font-variant-numeric:tabular-nums; }
.mtab th{ font-weight:400; font-size:11px; color:var(--muted); text-align:right; padding:0 5px 6px; }
.mtab .ast{ color:var(--muted); font-size:9px; vertical-align:super; }
.mtab th:first-child{ text-align:left; }
.mtab td{ text-align:right; padding:7px 5px; border-top:1px solid var(--line); }
.mtab td:first-child{ text-align:left; color:var(--sub); font-size:11.5px; white-space:nowrap; }
.diff{ display:flex; gap:12px; margin-top:7px; font-size:11.5px; color:var(--muted); }
.rsum{ width:100%; border-collapse:collapse; margin-top:10px; padding-top:9px; border-top:1px dashed var(--line); font-size:12px; font-variant-numeric:tabular-nums; }
.rsum th{ font-weight:400; font-size:11px; color:var(--muted); text-align:right; padding:0 0 4px; }
.rsum th:first-child{ text-align:left; }
.rsum td{ padding:3px 0; text-align:right; }
.rsum td.nm{ text-align:left; color:var(--sub); font-size:11.5px; display:flex; align-items:center; gap:6px; }
.rsum td.nm i{ width:8px; height:8px; border-radius:50%; flex:0 0 auto; }
.rsum-cap{ margin:10px 0 0; padding-top:9px; border-top:1px dashed var(--line); font-size:11.5px; color:var(--muted); }
.rsum-cap b{ color:var(--sub); font-weight:600; }
.rsum{ margin-top:4px; border-top:0; padding-top:0; }
.rsum-note{ margin:6px 0 0; font-size:11px; color:var(--muted); }
@media (max-width:560px){ .rsum .opt{ display:none; } }
.rsum.no-opt .opt{ display:none; }
.sum-excess{ display:flex; flex-wrap:wrap; align-items:baseline; gap:4px 14px; margin:8px 0 0; font-size:11.5px; color:var(--muted); }
.sum-excess .se{ display:inline-flex; align-items:center; gap:5px; }
.sum-excess .se i{ width:8px; height:8px; border-radius:50%; display:inline-block; }
.sum-excess .se b{ font-size:12px; }
.sum-excess .se{ display:inline-flex; align-items:center; gap:5px; }
.sum-excess .se i{ width:8px; height:8px; border-radius:50%; display:inline-block; }
.sum-excess .se b{ font-size:12px; }
.diff b{ font-variant-numeric:tabular-nums; }
/* 策略卡栅格：任何宽度都用同一套规则，每张卡至少 300px 宽——
   卡内是 4~5 列表格，窄于 300 就会挤成一团（用户 2026-11-08：「怎么还粘着呢」）。
   auto-fit 会自动从 3 列降到 2 列、1 列，不再靠断点猜。 */
/* 注意 margin-top：卡片自己 margin:0 了，栅格再不给上边距，就会和上面「我的策略」卡片贴死 */
.metric-grid{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:12px; padding:0 12px; margin-top:12px; }
.metric-grid .card{ margin:0; }
.metric-grid > .k.pad{ grid-column:1/-1; }   /* 说明文字要横跨整行，别被挤成一列 */
@media (max-width:620px){
  .ctl .row{ flex-wrap:wrap; }
  .ctl .row .k{ flex:0 0 100%; }
}
</style>
