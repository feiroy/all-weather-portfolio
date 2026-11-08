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
          <span class="lb">再平衡</span>
          <div class="chips in"><span v-for="f in freqs" :key="f.k" class="chip" :class="{ on: freq === f.k }" @click="freq = f.k">{{ f.t }}</span></div>
        </div>
        <p class="k">起点由「策略回测」页统一设置，所有策略在同一区间里对比。</p>
      </div>

      <!-- 基金与权重 -->
      <div class="card">
        <div class="ct"><b>基金与权重</b><span class="k num">{{ rows.length }} 只 · 合计 {{ total.toFixed(1) }}%</span></div>
        <p class="k">点基金名可以换成别的基金；「×」删掉这一只；权重按合计自动归一。</p>
        <div v-for="(r, i) in rows" :key="r.key" class="frow">
          <div class="finf" @click="startReplace(i)">
            <b>{{ r.name }} <van-icon name="exchange" class="sw" /></b>
            <small class="num">{{ r.code }} · 数据自 {{ r.from || '—' }}<template v-if="r.src === '基金净值'"> · 真实净值</template></small>
          </div>
          <div class="wbar"><i :style="{ width: pctOf(r.key) + '%' }"></i></div>
          <div class="win"><input type="number" min="0" max="100" step="1" v-model.number="r.weight" /><span>%</span></div>
          <span class="drop" @click="dropRow(i)">×</span>
        </div>
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
        <p v-if="hint" class="warn">{{ hint }}</p>
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

const freqs = [{ k: 'M', t: '每月' }, { k: 'Q', t: '每季' }, { k: 'N', t: '不再平衡' }]
const name = ref('我的组合'), freq = ref('M'), rows = ref([])
const pool = ref({ assets: [], funds: [] })
const q = ref(''), remote = ref([]), replaceIdx = ref(null), hint = ref('')

// 去掉括号说明和 ETF 后缀，保留完整主体，不要硬截成「沪深 300 E」这种半截名
const shortName = n => (n || '').replace(/（.*?）/g, '').replace(/\s*ETF\s*$/, '').trim() || n
const allPool = computed(() => [...(pool.value.assets || []), ...(pool.value.funds || [])])
const quick = computed(() => (pool.value.assets || []).slice(0, 9))
const poolCodes = computed(() => new Set(allPool.value.map(o => o.code)))
const total = computed(() => rows.value.reduce((s, r) => s + (Number(r.weight) || 0), 0))
const pctOf = k => total.value > 0
  ? Math.max(0, Math.min(100, (Number(rows.value.find(r => r.key === k)?.weight) || 0) / total.value * 100)) : 0

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
  if (isEdit) {
    const s = loadStrategies().find(x => x.id === editId)
    if (s) {
      name.value = s.name; freq.value = s.freq || 'M'
      rows.value = (s.funds || []).map(f => ({ ...f }))
    } else hint.value = '这条策略已经不存在了，将作为新策略保存'
  }
})

function startReplace(i) { replaceIdx.value = i; q.value = ''; remote.value = []; hint.value = '' }
function cancelReplace() { replaceIdx.value = null; q.value = '' }
function dropRow(i) { rows.value.splice(i, 1); hint.value = '' }

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
  if (replaceIdx.value !== null) {
    const i = replaceIdx.value, old = rows.value[i]
    if (rows.value.some((r, j) => r.key === item.key && j !== i)) return showFailToast('已经有这只基金了')
    rows.value[i] = { ...item, weight: old?.weight ?? 20 }
    replaceIdx.value = null
  } else {
    if (rows.value.some(r => r.key === item.key)) return showFailToast('已经加过了')
    rows.value.push({ ...item, weight: 20 })
  }
  q.value = ''; remote.value = []; hint.value = ''
}

function cancel() { router.push(backTo) }
function save() {
  const n = name.value.trim()
  if (!n) { hint.value = '先给策略起个名字'; return }
  const funds = rows.value.filter(r => Number(r.weight) > 0)
  if (!funds.length) { hint.value = '至少给一只基金大于 0 的权重'; return }
  const list = loadStrategies()
  if (list.some(s => s.name === n && s.id !== editId)) { hint.value = '已经有同名策略了，换个名字'; return }
  const rec = { id: editId || 's' + Date.now(), name: n, freq: freq.value, funds: funds.map(f => ({ ...f })) }
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
.frow{ display:flex; align-items:center; gap:8px; padding:9px 0; border-bottom:1px solid var(--line); }
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
.btns{ display:flex; gap:10px; }
.btn{ flex:1; border:1px solid var(--line); background:#fff; color:var(--sub); border-radius:10px; padding:10px 12px; font-size:13.5px; cursor:pointer; }
.btn.primary{ background:var(--brand); border-color:var(--brand); color:#fff; font-weight:600; }
.btn:disabled{ opacity:.5; cursor:default; }
@media (max-width:620px){
  .wbar{ display:none; }
  .finf b{ font-size:12.5px; }
}
</style>
