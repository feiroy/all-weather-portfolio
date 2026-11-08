<template>
  <div class="page no-tab">
    <SubBar :title="isEdit ? '编辑策略' : '新增策略'" :fallback="backTo" />
    <div class="wrap">
      <!-- 基本信息 -->
      <div class="card">
        <div class="ct"><b>基本信息</b><span class="k">保存后自动加入回测对比</span></div>
        <div class="fld">
          <span class="lb">策略名</span>
          <input v-model="name" class="nm" maxlength="16" placeholder="例如 我的稳健组合" />
        </div>
        <div class="fld">
          <span class="lb">加权方式</span>
          <div class="chips in"><span v-for="m in methods" :key="m.k" class="chip" :class="{ on: method === m.k }" @click="method = m.k">{{ m.t }}</span></div>
        </div>
        <div class="fld">
          <span class="lb">再平衡</span>
          <div class="chips in"><span v-for="f in freqs" :key="f.k" class="chip" :class="{ on: freq === f.k }" @click="freq = f.k">{{ f.t }}</span></div>
        </div>
        <template v-if="method !== 'fixed'">
          <div class="fld">
            <span class="lb">加权窗口</span>
            <div class="nums">
              <input type="number" min="5" max="250" step="5" v-model.number="window" /><span>交易日</span>
            </div>
            <span class="k">算权重用的历史长度，内置三策略都是 20</span>
          </div>
          <div class="fld">
            <span class="lb">单只上限</span>
            <div class="nums">
              <input type="number" min="5" max="100" step="5" v-model.number="maxW" /><span>%</span>
            </div>
            <span class="k">超出部分按比例分给其他资产，防止单一资产吃掉全部仓位</span>
          </div>
        </template>
        <div class="fld">
          <span class="lb">现金比例</span>
          <div class="chips in"><span v-for="c in cashes" :key="c.k" class="chip" :class="{ on: cash === c.k }" @click="cash = c.k">{{ c.t }}</span></div>
        </div>
        <template v-if="method !== 'fixed'">
          <div class="fld">
            <span class="lb">波动上限</span>
            <div class="nums">
              <input type="number" min="0" max="60" step="1" v-model.number="volCap" /><span>%</span>
            </div>
            <span class="k">组合年化波动超过它就等比降敞口，0 = 不限（风险平价内置 9%）</span>
          </div>
          <div class="fld col">
            <span class="lb">趋势过滤</span>
            <div class="tlist">
              <div class="trow" v-for="r in rows" :key="r.key">
                <span class="tn">{{ r.name }}</span>
                <input type="number" min="0" max="250" step="5" v-model.number="r.trend" />
                <span class="tu">{{ r.trend > 0 ? `日均线（跌破转避风港）` : '不启用' }}</span>
              </div>
              <p class="k" v-if="!rows.length">先添加基金，再给每只单独设均线窗口（0 = 不启用）。任意基金都能设，包括新加的行业/科技 ETF。</p>
            </div>
            <div class="fld" v-if="rows.length">
              <span class="lb">避风港</span>
              <select v-model="safeAsset" class="bksel">
                <option v-for="r in rows" :key="r.key" :value="r.key">{{ shortName(r.name) }}</option>
              </select>
              <span class="k">跌破均线时权重转给它。内置策略是城投债 ETF，也可以选持仓里任意一只债基</span>
            </div>
            <p class="twarn" v-if="trendWithoutSafe">避风港得是持仓里权重大于 0 的一只：请在「避风港」里选一只（默认城投债 ETF 511220），或把所有均线窗口设为 0</p>
          </div>
        </template>
        <p class="k">起点由「策略回测」页统一设置，所有策略在同一区间里对比。</p>
      </div>

      <!-- 基金与权重 -->
      <div class="card">
        <div class="ct"><b>基金与权重</b><span class="k num">{{ rows.length }} 只 · 合计 {{ total.toFixed(1) }}%</span></div>
        <p class="k">点基金名可以换成别的基金；「×」删掉这一只；权重按合计自动归一。</p>
        <div v-for="(r, i) in rows" :key="r.key" class="frow">
          <div class="fmain">
            <div class="finf" @click="startReplace(i)">
              <b>{{ r.name }} <van-icon name="exchange" class="sw" /></b>
              <small class="num">{{ r.code }} · 数据自 {{ r.from || '—' }}<template v-if="r.src === '基金净值'"> · 真实净值</template></small>
            </div>
            <div class="wbar"><i :style="{ width: pctOf(r.key) + '%' }"></i></div>
            <div class="win"><input type="number" min="0" max="100" step="1" v-model.number="r.weight" /><span>%</span></div>
            <span class="drop" @click="dropRow(i)">×</span>
          </div>
          <div class="fbk" v-if="method === 'risk_parity'">
            <span class="lb">分桶</span>
            <select v-model="r.bucket" class="bksel" :class="{ miss: !r.bucket }">
              <option value="">未分组</option>
              <option v-for="b in bucketOptions" :key="b" :value="b">{{ b }}</option>
            </select>
            <span class="k">{{ r.bucket ? '与同桶基金共分这一桶的额度' : '保存前要选一个桶' }}</span>
          </div>
        </div>
        <p class="k" v-if="method === 'risk_parity'">分桶按当前持仓保存：增 / 换 / 删基金都在这里重新选桶，不再沿用复刻时的旧结构。</p>
        <p v-if="!rows.length" class="empty-tip">还没有基金，从下面添加或选一个常用资产</p>

        <!-- 添加 / 替换基金 -->
        <div class="add">
          <div class="add-h">
            <b>{{ replaceIdx === null ? '添加基金' : `替换第 ${replaceIdx + 1} 只` }}</b>
            <a v-if="replaceIdx !== null" @click="cancelReplace">取消替换</a>
          </div>
          <van-search v-model="q" placeholder="搜基金名称或 6 位代码" shape="round" class="sb" />
          <van-cell-group inset v-if="options.length">
            <van-cell v-for="o in options" :key="o.key" :title="o.name"
                      :label="`${o.code}${o.from ? ' · 数据自 ' + o.from : ''}`" clickable @click="choose(o)">
              <template #value><van-icon name="plus" /></template>
            </van-cell>
          </van-cell-group>
          <p v-else-if="q.trim()" class="empty-tip">没找到，直接输 6 位代码也能加</p>
          <div class="quick" v-if="!q.trim() && replaceIdx === null">
            <span class="k">常用资产</span>
            <span v-for="o in quick" :key="o.key" class="chip" @click="choose(o)">+ {{ shortName(o.name) }}</span>
          </div>
        </div>
      </div>

      <!-- 保存 -->
      <div class="card foot">
        <p :class="{ warn: total <= 0 }">合计 {{ total.toFixed(1) }}% · 保存后按合计归一到 100%</p>
        <p v-if="err" class="warn">{{ err }}</p>
        <p v-if="hint" class="note">{{ hint }}</p>
        <div class="btns">
          <button class="btn" @click="cancel">取消</button>
          <button class="btn primary" :disabled="!rows.length || total <= 0" @click="save">保存策略</button>
        </div>
      </div>
    </div>
  </div>
</template>
<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showFailToast } from 'vant'
import { get } from '../api'
import { loadStrategies, saveStrategies } from '../strategyStore'
import SubBar from '../components/SubBar.vue'

const route = useRoute(), router = useRouter()
const aid = route.params.aid
const backTo = `/a/${aid}/market/backtest`
const editId = route.query.edit || ''
const isEdit = !!editId

const methods = [{ k: 'fixed', t: '固定权重' }, { k: 'inverse_vol', t: '逆波动率' }, { k: 'risk_parity', t: '风险平价' }]
const freqsAll = [{ k: 'M', t: '每月' }, { k: 'B', t: '每两周' }, { k: 'W', t: '每周' }]
const freqsFixed = [{ k: 'M', t: '每月' }, { k: 'Q', t: '每季' }, { k: 'N', t: '不再平衡' }]
const cashes = [{ k: 0, t: '满仓' }, { k: 0.15, t: '留 15%' }, { k: 0.3, t: '留 30%' }]
const name = ref('我的组合'), freq = ref('M'), rows = ref([])
const method = ref('fixed'), window = ref(20), maxW = ref(25), cash = ref(0)
const volCap = ref(0)          // 波动率上限（%），0 = 不限；风险平价为 9
const safeAsset = ref('credit') // 趋势过滤避风港：跌破均线时权重转给它（内置=城投债）
const freqs = computed(() => method.value === 'fixed' ? freqsFixed : freqsAll)
const pool = ref({ assets: [], funds: [] })
const q = ref(''), remote = ref([]), replaceIdx = ref(null), hint = ref(''), err = ref('')
// {桶名: [资产key]} → {资产key: 桶名}，用于把复刻/旧策略的分桶回填成每只基金的下拉值
const bucketsFromTpl = rp => {
  const m = {}
  Object.entries(rp || {}).forEach(([b, ks]) => (ks || []).forEach(k => { m[k] = b }))
  return m
}

// 去掉括号说明和 ETF 后缀，保留完整主体，不要硬截成「沪深 300 E」这种半截名
const shortName = n => (n || '').replace(/（.*?）/g, '').replace(/\s*ETF\s*$/, '').trim() || n
const allPool = computed(() => [...(pool.value.assets || []), ...(pool.value.funds || [])])
const quick = computed(() => (pool.value.assets || []).slice(0, 12))   // 别把后加的资产（红利低波等）截掉
const poolCodes = computed(() => new Set(allPool.value.map(o => o.code)))
const total = computed(() => rows.value.reduce((s, r) => s + (Number(r.weight) || 0), 0))
const pctOf = k => total.value > 0
  ? Math.max(0, Math.min(100, (Number(rows.value.find(r => r.key === k)?.weight) || 0) / total.value * 100)) : 0
// 分桶选项来自后端 config.V3B_RP_BUCKETS（单一事实源），资产 key 与 6 位代码都能查默认桶
const bucketOptions = computed(() => pool.value.buckets || [])
const bucketOfKey = k => (pool.value.asset_bucket || {})[k] || ''
// 避风港由用户在「避风港」下拉里选定（默认 credit）。用户可能用 6 位代码把城投债加进来
// （key=511220），后端会归一化成 credit，所以前端要按 key 与 code 双认；权重 0 等于没持有。
const safeCode = computed(() => (pool.value.assets || []).find(a => a.key === safeAsset.value)?.code || '')
const isSafeAsset = r => (r.key === safeAsset.value || (!!safeCode.value && r.code === safeCode.value))
  && Number(r.weight) > 0
const trendWithoutSafe = computed(() => method.value !== 'fixed'
  && rows.value.some(r => Number(r.trend) > 0)
  && !rows.value.some(isSafeAsset))

// 本地候选（长历史策略资产 + 已缓存基金）优先，远程名录补充；6 位代码未命中时允许直接拉取
const options = computed(() => {
  const s = q.value.trim()
  if (!s) return []
  const local = allPool.value.filter(o => (o.name || '').includes(s) || (o.code || '').includes(s)).slice(0, 12)
  const rem = remote.value.filter(r => !poolCodes.value.has(r.code))
    .slice(0, 8).map(r => ({ key: r.code, code: r.code, name: r.name, from: '', src: '基金净值', needFetch: true }))
  const out = [...local, ...rem]
  if (/^\d{6}$/.test(s) && !out.some(o => o.code === s)) {
    out.push({ key: s, code: s, name: `代码 ${s} · 点此拉取`, from: '', src: '待拉取', needFetch: true })
  }
  return out
})

let t = null
watch(q, v => {
  clearTimeout(t)
  const s = v.trim()
  if (!s) { remote.value = []; return }
  t = setTimeout(async () => {
    try { remote.value = (await get(`/api/market/fund-search?q=${encodeURIComponent(s)}`)).rows || [] }
    catch { remote.value = [] }
  }, 300)
})

onMounted(async () => {
  try { pool.value = await get('/api/market/strategy-funds') }
  catch (e) { hint.value = `候选基金加载失败：${e.message}` }
  // 从回测页「复刻为我的策略」进来：把内置策略的持仓与参数逐项填好，再按需改
  if (route.query.tpl === '1') {
    try {
      const t = JSON.parse(sessionStorage.getItem('aw-strategy-tpl') || 'null')
      if (t) {
        name.value = t.name || name.value
        method.value = t.method || 'fixed'
        window.value = t.window ?? 20
        maxW.value = Math.round((t.max_w ?? 0.25) * 100)
        cash.value = t.cash_ratio || 0
        volCap.value = t.target_vol ? Math.round(t.target_vol * 100) : 0
        safeAsset.value = t.safe_asset || 'credit'
        freq.value = t.freq || 'M'
        const bmap = bucketsFromTpl(t.rp_buckets)
        rows.value = (t.funds || []).map(f => ({ ...f, trend: f.trend || 0,
          bucket: f.bucket || bmap[f.key] || bucketOfKey(f.key) || '' }))
        if (t.note) hint.value = t.note
      }
    } catch (e) { console.warn('模板解析失败', e) }
    sessionStorage.removeItem('aw-strategy-tpl')
  }
  if (isEdit) {
    const s = loadStrategies().find(x => x.id === editId)
    if (s) {
      name.value = s.name; freq.value = s.freq || 'M'
      method.value = s.method || 'fixed'
      window.value = s.window ?? 20; maxW.value = s.max_w != null ? Math.round(s.max_w * 100) : 25
      cash.value = s.cash_ratio || 0
      volCap.value = s.target_vol ? Math.round(s.target_vol * 100) : 0
      safeAsset.value = s.safe_asset || 'credit'
      const bmap = bucketsFromTpl(s.rp_buckets)
      rows.value = (s.funds || []).map(f => ({ ...f,
        bucket: f.bucket || bmap[f.key] || bucketOfKey(f.key) || '' }))
    } else hint.value = '这条策略已经不存在了，将作为新策略保存'
  }
})

function startReplace(i) { replaceIdx.value = i; q.value = ''; remote.value = []; hint.value = '' }
function cancelReplace() { replaceIdx.value = null; q.value = '' }
function dropRow(i) { rows.value.splice(i, 1); hint.value = ''; err.value = '' }

async function choose(o) {
  const item = { ...o }
  if (item.needFetch) {
    try {
      const x = await get(`/api/market/fund/${item.code}`)
      item.name = x.name || item.name
      item.from = x.dates?.[0] || ''
      item.src = '基金净值'
    } catch (e) { showFailToast(`拉取 ${item.code} 失败：${e.message}`); return }
  }
  delete item.needFetch
  // 新基金优先用它自己的默认桶；6 位代码查不到时，替换场景沿用旧桶、新增场景留空让用户选
  const bk = item.bucket || bucketOfKey(item.key) || ''
  if (replaceIdx.value !== null) {
    const i = replaceIdx.value, old = rows.value[i]
    if (rows.value.some((r, j) => r.key === item.key && j !== i)) return showFailToast('已经有这只基金了')
    rows.value[i] = { ...item, weight: old?.weight ?? 20, trend: old?.trend ?? 0,
                      bucket: bk || old?.bucket || '' }
    replaceIdx.value = null
  } else {
    if (rows.value.some(r => r.key === item.key)) return showFailToast('已经加过了')
    rows.value.push({ ...item, weight: 20, trend: item.trend || 0, bucket: bk })
  }
  q.value = ''; remote.value = []; hint.value = ''
}

watch(method, m => {
  const ok = (m === 'fixed' ? freqsFixed : freqsAll).map(f => f.k)
  if (!ok.includes(freq.value)) freq.value = 'M'
})
function cancel() { router.push(backTo) }
function save() {
  const n = name.value.trim()
  if (!n) { err.value = '先给策略起个名字'; return }
  const funds = rows.value.filter(r => Number(r.weight) > 0)
  if (!funds.length) { err.value = '至少给一只基金大于 0 的权重'; return }
  const list = loadStrategies()
  if (list.some(s => s.name === n && s.id !== editId)) { err.value = '已经有同名策略了，换个名字'; return }
  const trend_map = {}
  funds.forEach(f => { if (Number(f.trend) > 0) trend_map[f.key] = Number(f.trend) })
  // 趋势过滤必须有避风港承接权重：默认城投债 ETF，也可以在「避风港」里选持仓中的任意一只
  if (method.value !== 'fixed' && Object.keys(trend_map).length && !funds.some(isSafeAsset)) {
    err.value = '趋势过滤的「避风港」得是持仓里权重大于 0 的一只：请在「避风港」下拉里选好，或把所有均线窗口设为 0'
    return
  }
  // 分桶按「当前持仓 + 每只基金选的桶」现生成，不再沿用复刻时的静态快照
  let rp_buckets = null
  if (method.value === 'risk_parity') {
    if (!bucketOptions.value.length) { err.value = '分桶选项没加载出来，刷新页面重试'; return }
    const miss = funds.filter(f => !f.bucket)
    if (miss.length) {
      err.value = `这些基金还没选分桶：${miss.map(f => shortName(f.name || f.key)).join('、')}`
      return
    }
    rp_buckets = {}
    for (const b of bucketOptions.value) {
      const ks = funds.filter(f => f.bucket === b).map(f => f.key)
      if (ks.length) rp_buckets[b] = ks
    }
  }
  const rec = { id: editId || 's' + Date.now(), name: n, freq: freq.value, method: method.value,
                window: Number(window.value) || 20, max_w: (Number(maxW.value) || 25) / 100,
                cash_ratio: Number(cash.value) || 0,
                target_vol: Number(volCap.value) ? Number(volCap.value) / 100 : null,
                trend_map, rp_buckets, safe_asset: safeAsset.value,
                funds: funds.map(f => ({ ...f })) }
  if (editId) {
    const i = list.findIndex(s => s.id === editId)
    if (i >= 0) list[i] = rec; else list.push(rec)
  } else list.push(rec)
  saveStrategies(list)
  router.push(backTo)
}
</script>
<style scoped>
.ct{ display:flex; justify-content:space-between; align-items:baseline; gap:10px; flex-wrap:wrap; font-size:15px; margin-bottom:10px; }
.k{ font-size:12px; color:var(--muted); line-height:1.6; margin:0; }
.fld{ display:flex; align-items:center; gap:10px; margin-top:10px; }
.fld .lb{ flex:0 0 56px; font-size:12.5px; color:var(--muted); }
.fld .nm{ flex:1 1 auto; min-width:0; border:1px solid var(--line); border-radius:9px; padding:8px 10px; font-size:13.5px; }
.chips.in{ padding:0; flex-wrap:wrap; }
.fld.col{ display:block; }
.fld.col .lb{ display:block; margin-bottom:6px; }
.tlist{ margin-top:2px; }
.trow{ display:flex; align-items:center; gap:8px; padding:5px 0; border-bottom:1px dashed #EEF2F7; }
.trow:last-child{ border-bottom:0; }
.trow .tn{ flex:1 1 auto; min-width:0; font-size:12px; color:var(--sub); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.trow input{ flex:0 0 58px; border:1px solid var(--line); border-radius:7px; padding:5px 6px; font-size:12.5px; text-align:right; }
.trow .tu{ flex:0 0 132px; font-size:10.5px; color:#94A3B8; text-align:right; }
.nums{ display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
.nums input{ width:56px; border:1px solid var(--line); border-radius:7px; padding:5px 6px; font-size:12.5px; text-align:right; }
.nums span{ font-size:11.5px; color:var(--muted); margin-right:4px; }
.frow{ padding:9px 0; border-bottom:1px solid var(--line); }
.fmain{ display:flex; align-items:center; gap:8px; }
.fbk{ display:flex; align-items:center; gap:8px; margin-top:7px; }
.fbk .lb{ flex:0 0 32px; font-size:11.5px; color:var(--muted); }
.bksel{ flex:0 0 118px; min-width:0; border:1px solid var(--line); border-radius:7px; padding:5px 6px; font-size:12px; background:#fff; color:var(--sub); }
.bksel.miss{ border-color:var(--up); color:var(--up); }
.fbk .k{ font-size:10.5px; }
.twarn{ font-size:11.5px; color:var(--up); margin:8px 0 0; }
.finf{ flex:1 1 auto; min-width:0; cursor:pointer; }
.finf b{ display:block; font-size:13px; font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.finf .sw{ font-size:11px; color:var(--muted); margin-left:2px; }
.finf small{ display:block; font-size:11px; color:var(--muted); margin-top:2px; }
.wbar{ flex:0 0 48px; height:6px; border-radius:3px; background:#EEF2F7; overflow:hidden; }
.wbar i{ display:block; height:100%; background:var(--brand); border-radius:3px; }
.win{ flex:0 0 62px; display:flex; align-items:center; gap:2px; }
.win input{ width:46px; border:1px solid var(--line); border-radius:7px; padding:5px; font-size:12.5px; text-align:right; }
.drop{ flex:0 0 20px; text-align:center; color:var(--muted); font-size:18px; cursor:pointer; }
.add{ margin-top:14px; }
.add-h{ display:flex; justify-content:space-between; align-items:baseline; font-size:13px; margin-bottom:2px; }
.add-h a{ color:var(--brand); font-size:12px; cursor:pointer; }
.sb{ background:transparent; padding:6px 0; }
.quick{ display:flex; flex-wrap:wrap; align-items:center; gap:7px; margin-top:8px; }
.quick .k{ flex:0 0 100%; }
.foot p{ font-size:12.5px; color:var(--muted); margin:0 0 12px; }
.foot p.warn{ color:var(--up); }
.foot p.note{ color:#2563EB; background:#EFF6FF; border-radius:8px; padding:8px 10px; }
.btns{ display:flex; gap:10px; }
.btn{ flex:1; border:1px solid var(--line); background:#fff; color:var(--sub); border-radius:10px; padding:10px 12px; font-size:13.5px; cursor:pointer; }
.btn.primary{ background:var(--brand); border-color:var(--brand); color:#fff; font-weight:600; }
.btn:disabled{ opacity:.5; cursor:default; }
@media (max-width:620px){
  .wbar{ display:none; }
  .finf b{ font-size:12.5px; }
  .bksel{ flex:1 1 auto; }
  .fbk .k{ display:none; }
}
</style>
