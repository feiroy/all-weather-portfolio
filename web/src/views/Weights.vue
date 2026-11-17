<template>
  <div class="page no-tab">
    <SubBar title="选基配置" :fallback="`/a/${aid}`" />
    <div class="wrap">
      <van-skeleton v-if="!d" title :row="10" style="padding:16px" />
      <div v-else class="sel-page">
        <!-- 策略是账户属性，在入口页账户卡片上换；这一页只管选基金 -->
        <div class="card cur">
          <div class="cl">当前跟随 <b>{{ d.account.strategy_name }}</b></div>
          <p>策略决定每个资产该占多少；这一页只管<b>每个位置用哪只基金去买</b>。要换策略，到入口页账户卡片上点「换策略」，会先给预览再确认。</p>
          <router-link to="/" class="go">去账户页 <van-icon name="arrow" /></router-link>
        </div>

        <!-- 目标权重拿谁的净值算：内置策略原来是拿项目默认的 8 只 ETF 算的，
             换成场外联接以后波动率、均线都变了，权重当然不一样。这里把口径摊开。 -->
        <div class="card basis">
          <div class="cl" v-if="isCustom">自定义策略的权重，本来就是按<b>策略里那几只基金</b>算的</div>
          <div class="cl" v-else>目标权重是按<b>{{ basisTitle }}</b>算的</div>
          <ul v-if="!isCustom && subUsed.length" class="bl">
            <li v-for="u in subUsed" :key="u.slot">
              <b>{{ u.label }}</b><span :title="u.codes.join(' / ')">{{ codeText(u) }}</span>
              <small>{{ fmtDay(u.since) }} 起</small>
            </li>
          </ul>
          <p v-if="!isCustom && !subUsed.length" class="bn">你还没换过基金，权重就是项目默认那几只算的。</p>
          <p v-if="subSkipped.length" class="warn">
            这几个位置仍按项目默认标的算：{{ subSkipped.map(x => x.label + '（' + x.why + '）').join('；') }}
          </p>
          <p v-if="!isCustom" class="bn">换基金以后波动率和均线都变了，风险平价 / 逆波动率分给它的钱也会跟着变 —— 这是算对了，不是 bug。</p>
        </div>

        <template v-if="!isCustom">
          <div class="sec-t"><span>目标权重 · 按我的基金 vs 项目默认</span><span>{{ d.account.strategy_name }}</span></div>
          <div class="card diff">
            <div class="dh"><span>资产</span><span>我的基金</span><span>项目默认</span><span>差</span></div>
            <div v-for="r in wDiff" :key="r.asset" class="dr">
              <span class="dn">{{ r.name }}<small v-if="r.mine">{{ r.mine }}</small></span>
              <span>{{ r.mine_w == null ? '—' : r.mine_w.toFixed(2) + '%' }}</span>
              <span class="muted">{{ r.base_w == null ? '—' : r.base_w.toFixed(2) + '%' }}</span>
              <span :class="['dv', r.d > 0.005 ? 'up' : r.d < -0.005 ? 'down' : '']">
                {{ r.d == null ? '—' : (r.d > 0 ? '+' : '') + r.d.toFixed(2) + 'pp' }}
              </span>
            </div>
          </div>
        </template>

        <div class="sec-t"><span>我的位置 · 每个位置买哪几只</span><span>{{ d.slots.length }} 个位置</span></div>
        <div class="slot-grid">
          <div v-for="s in d.slots" :key="s.slot" class="card slot" :class="{ off: !s.on }">
            <div class="s1"><b>{{ s.label }}</b>
              <van-switch :model-value="s.on" size="20px" @update:model-value="v => op(s, { op: 'toggle', on: v })" /></div>
            <template v-if="s.on">
              <div v-for="f in s.funds" :key="f.code" class="fr">
                <div class="fn"><div>{{ f.name }}</div>
                  <small>{{ f.code }}</small>
                  <!-- 场内才有溢价：现价单独一行，徽标不跟代码挤在一起被省略号吃掉 -->
                  <small v-if="f.unit === '股' && pq[f.code]?.ok" class="qx">
                    现价 {{ pq[f.code].price }} <PremiumTag :q="pq[f.code]" />
                  </small></div>
                <span class="seg2 u"><button :class="{ on: f.unit === '股' }" @click="op(s, { op: 'unit', code: f.code, unit: '股' })">场内</button>
                  <button :class="{ on: f.unit !== '股' }" @click="op(s, { op: 'unit', code: f.code, unit: '份额' })">场外</button></span>
                <input v-if="s.funds.length > 1" class="sh num" type="number" :value="Math.round(f.share * 100)" @change="e => setShare(s, f, e.target.value)" /><span v-if="s.funds.length > 1" class="pc">%</span>
                <van-icon name="cross" class="rm" @click="remove(s, f)" />
              </div>
              <div class="s3">
                <a @click="openAdd(s)"><van-icon name="plus" /> 加一只</a>
                <a @click="reset(s)">恢复默认</a>
              </div>
            </template>
            <p v-else class="offt">关掉的位置不买；它的目标权重按同桶分给别的位置</p>
          </div>
        </div>
        <p class="empty-tip">一个位置挂多只时按占比分钱（会自动归一）；场内按股一手 100 股，场外按金额申购</p>
      </div>
    </div>
    <van-popup v-model:show="addShow" position="bottom" round closeable :style="{ height: '70vh' }">
      <div class="pop">
        <h4>给「{{ addSlot?.label }}」加一只</h4>
        <van-search v-model="aq" placeholder="名称或 6 位代码" shape="round" />
        <van-cell-group>
          <van-cell v-for="r in aRows" :key="r.code" :title="r.name" :label="r.code + ' · ' + r.src" clickable @click="add(r)" />
        </van-cell-group>
      </div>
    </van-popup>
  </div>
</template>
<script setup>
import { ref, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { showConfirmDialog, showSuccessToast, showFailToast } from 'vant'
import { get, peek, post, dataVer } from '../api'
import { money } from '../fmt'
import SubBar from '../components/SubBar.vue'
import PremiumTag from '../components/PremiumTag.vue'
const aid = useRoute().params.aid
const url = `/api/acct/${aid}/weights`
const d = ref(peek(url) || null)

// 当前策略的目标权重是拿哪些基金算的 / 跟项目默认标的差多少。
// 自定义策略的权重本来就是按策略里那几只基金算的，不涉及适配，两栏都不显示。
const isCustom = computed(() => String(d.value?.account?.strategy || '').startsWith('custom:'))
const subUsed = computed(() => d.value?.sub?.used || [])
const subSkipped = computed(() => (d.value?.sub?.skipped || []).filter(x => x.kind !== 'default'))
const basisTitle = computed(() => (subUsed.value.length ? '你实际持有的基金' : '项目默认标的'))
const fmtDay = s => (s || '').replace(/-/g, '/')
// 一个位置挂很多只时（有的人一个位置塞了 8 只），列表里只列前两只 + 共几只，全量放 title
const codeText = u => {
  const cs = u.codes || []
  return cs.length > 3 ? `${cs.slice(0, 2).join(' / ')} 等 ${cs.length} 只` : cs.join(' / ')
}
const wDiff = computed(() => {
  const stg = d.value?.account?.strategy || 'B-Con'
  return (d.value?.rows || []).map(r => {
    const mine_w = r.w?.[stg] ?? null, base_w = r.base?.[stg] ?? null
    return { asset: r.asset, name: r.name, mine: r.mine, mine_w, base_w,
             d: mine_w == null || base_w == null ? null : mine_w - base_w }
  }).filter(r => r.mine_w != null || r.base_w != null)
})
// 场内那几只的现价与溢价率（场外按净值申购，没有溢价）。取不到就整块不显示。
const pq = ref({})
async function loadPrem() {
  const codes = (d.value?.slots || []).filter(s => s.on)
    .flatMap(s => (s.funds || []).filter(f => f.unit === '股').map(f => f.code))
  if (!codes.length) return
  try {
    const r = await get(`/api/market/premium?codes=${[...new Set(codes)].join(',')}`)
    pq.value = Object.fromEntries((r.rows || []).map(x => [x.code, x]))
  } catch { /* 行情拿不到不影响配置页 */ }
}
const load = async (fresh = false) => { d.value = await get(url, { fresh }); loadPrem() }
load(); watch(dataVer, () => load(true))
async function op(s, body) {
  try { await post(`/api/acct/${aid}/holdings`, { slot: s.slot, ...body }); await load(true) } catch (e) { showFailToast(e.message) }
}
function setShare(s, f, v) {
  const shares = Object.fromEntries(s.funds.map(x => [x.code, x.code === f.code ? Math.max(0, +v || 0) : Math.round(x.share * 100)]))
  op(s, { op: 'shares', shares })
}
async function remove(s, f) {
  try { await showConfirmDialog({ title: `从「${s.label}」拿掉？`, message: `${f.name}（${f.code}）\n已有的持仓和记录不受影响，只是之后调仓不再算它` }) } catch { return }
  op(s, { op: 'remove', code: f.code })
}
async function reset(s) {
  try { await showConfirmDialog({ title: `「${s.label}」恢复默认？`, message: '换回项目默认的那一只 ETF' }) } catch { return }
  op(s, { op: 'reset' })
}
const addShow = ref(false), addSlot = ref(null), aq = ref(''), aRows = ref([])
function openAdd(s) { addSlot.value = s; aq.value = ''; aRows.value = []; addShow.value = true }
let t = null
watch(aq, v => {
  clearTimeout(t)
  if (!v.trim()) { aRows.value = []; return }
  t = setTimeout(async () => {
    const r = (await get(`/api/market/fund-search?q=${encodeURIComponent(v.trim())}`)).rows
    aRows.value = r.length || !/^\d{6}$/.test(v.trim()) ? r : [{ code: v.trim(), name: `代码 ${v.trim()}`, src: '直接加' }]
  }, 300)
})
async function add(r) {
  addShow.value = false
  await op(addSlot.value, { op: 'add', code: r.code })
  showSuccessToast(`已加 ${r.name}`)
}
</script>
<style scoped>
.stg{ display:grid; gap:8px; padding:0 12px; }
.sc{ display:flex; gap:10px; align-items:flex-start; background:#fff; border-radius:14px; padding:12px 14px; cursor:pointer; border:1.5px solid transparent; }
.sc.on{ border-color:var(--brand); background:var(--brand-soft); }
.sc .van-icon{ font-size:20px; color:var(--muted); margin-top:1px; } .sc.on .van-icon{ color:var(--brand); }
.sc b{ display:block; font-size:15px; } .sc small{ font-size:12px; color:var(--muted); }
.wt{ padding:8px 12px; }
.wh, .wr{ display:grid; grid-template-columns:1fr 62px 62px 62px; gap:4px; align-items:center; }
@media (max-width:480px){
  .wh, .wr{ grid-template-columns:repeat(3,1fr); }
  .wh span:first-child{ display:none; }
  .wr .wn{ grid-column:1 / -1; display:flex; gap:8px; align-items:baseline; margin-bottom:4px; }
  .wh, .wv{ text-align:center !important; }
}
.wh{ font-size:11.5px; color:var(--muted); padding:4px 0 8px; border-bottom:1px solid var(--line); text-align:right; }
.wh span:first-child{ text-align:left; }
.wr{ padding:8px 0; border-bottom:1px solid var(--line); } .wr:last-child{ border-bottom:0; }
.wn b{ display:block; font-size:13.5px; font-weight:550; } .wn small{ font-size:11px; color:var(--muted); } .wn small.miss{ color:#B45309; }
.wv{ text-align:right; font-size:13.5px; color:var(--sub); } .wv em{ font-style:normal; color:#CBD5E1; }
.wv small{ display:block; font-size:10.5px; } .wv small.z{ color:#B45309; } .wv small.p{ color:var(--brand); }
.me{ color:var(--brand) !important; font-weight:600; }
.slot{ padding:12px 14px; } .slot.off{ opacity:.75; }
.s1{ display:flex; justify-content:space-between; align-items:center; font-size:15px; }
.fr{ display:flex; align-items:center; gap:8px; padding:9px 0; border-top:1px solid var(--line); margin-top:8px; }
.fn{ flex:1; min-width:0; font-size:13.5px; } .fn div{ white-space:nowrap; overflow:hidden; text-overflow:ellipsis; } .fn small{ display:block; font-size:11.5px; color:var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
/* 现价 + 溢价徽标：单独一行，flex 排，徽标不被截断 */
.fn .qx{ display:flex; align-items:center; gap:5px; margin-top:2px; }
.u button{ padding:3px 8px; font-size:11.5px; }
.sh{ width:40px; border:1px solid var(--line); border-radius:6px; padding:3px 4px; text-align:right; font-size:13px; }
.pc{ font-size:12px; color:var(--muted); margin-left:-4px; }
.rm{ color:var(--muted); font-size:16px; cursor:pointer; padding:4px; }
.s3{ display:flex; gap:18px; font-size:13px; margin-top:6px; } .s3 a{ color:var(--brand); cursor:pointer; display:flex; align-items:center; gap:3px; }
.s3 a:last-child{ color:var(--muted); margin-left:auto; }
.offt{ font-size:12px; color:var(--muted); margin:8px 0 0; }
.pop{ padding:18px 4px; } .pop h4{ margin:0 12px 6px; font-size:16px; }

@media (min-width:900px){
  .stg{ grid-template-columns:repeat(3,1fr); }
}

.sel-page{ max-width:960px; margin:0 auto; }
.cur{ padding:14px 16px; }
.cur .cl{ font-size:15px; } .cur .cl b{ color:var(--brand); }
.cur p{ font-size:12.5px; color:var(--sub); line-height:1.7; margin:6px 0 0; }
.cur .go{ display:inline-flex; align-items:center; gap:3px; font-size:12.5px; color:var(--brand); margin-top:8px; text-decoration:none; }
/* 权重口径卡片：换了哪几只基金、哪几只没换成 */
.basis{ padding:14px 16px; }
.basis .cl{ font-size:14px; } .basis .cl b{ color:var(--brand); }
.basis .bl{ list-style:none; margin:8px 0 0; padding:0; }
.basis .bl li{ display:flex; align-items:baseline; gap:6px; flex-wrap:wrap; padding:5px 0; border-top:1px solid var(--line); font-size:12.5px; }
.basis .bl li b{ font-weight:550; }
.basis .bl li span{ color:var(--sub); }
.basis .bl li small{ margin-left:auto; color:var(--muted); font-size:11.5px; }
.basis .bn{ font-size:12px; color:var(--muted); line-height:1.7; margin:8px 0 0; }
.basis .warn{ font-size:12px; color:#B45309; line-height:1.7; margin:8px 0 0; }
/* 权重对照：数值不加红绿（红绿是涨跌语义，权重差不是涨跌）。
   列宽必须 minmax(0,1fr)：1fr 的最小宽度是内容宽度，资产全称一长整张表就横向溢出，
   手机上「差」那一列直接被挤出屏幕（2026-11-17 截图验证）。 */
.diff{ padding:10px 14px; }
.dh, .dr{ display:grid; grid-template-columns:minmax(0,1.5fr) minmax(0,1fr) minmax(0,1fr) minmax(0,0.9fr); gap:6px; align-items:baseline; }
.dh{ font-size:11.5px; color:var(--muted); padding:4px 0 8px; border-bottom:1px solid var(--line); text-align:right; }
.dh span:first-child{ text-align:left; }
.dr{ padding:7px 0; border-bottom:1px solid var(--line); font-size:13px; text-align:right; }
.dr:last-child{ border-bottom:0; }
.dr > span{ min-width:0; overflow-wrap:anywhere; }
.dr .dn{ text-align:left; font-size:12.5px; } .dr .dn small{ display:block; font-size:11px; color:var(--muted); }
.dr .muted{ color:var(--muted); }
.dr .dv{ color:var(--muted); } .dr .dv.up{ color:var(--brand); font-weight:600; } .dr .dv.down{ color:var(--sub); }
/* 双列时同一行两张卡等高（2026-11-14 用户「页面咋空隙不一样大」）：原来 align-items:start，
   场内卡多一行「现价 / 溢价」、关掉的卡只有一行说明，矮的那张下面空出一截，看起来卡间距忽大忽小。
   现在 stretch 等高，操作行 margin-top:auto 贴底，左右两张的「加一只」在同一水平线上。 */
@media (min-width:900px){
  .slot-grid{ display:grid; grid-template-columns:1fr 1fr; gap:10px; padding:0 12px; align-items:stretch; }
  .slot-grid .card{ margin:0; display:flex; flex-direction:column; }
  .slot-grid .card .s3{ margin-top:auto; padding-top:6px; }
}
</style>
