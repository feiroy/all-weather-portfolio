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
        <div class="sec-t"><span>我的位置 · 每个位置买哪几只</span><span>{{ d.slots.length }} 个位置</span></div>
        <div class="slot-grid">
          <div v-for="s in d.slots" :key="s.slot" class="card slot" :class="{ off: !s.on }">
            <div class="s1"><b>{{ s.label }}</b>
              <van-switch :model-value="s.on" size="20px" @update:model-value="v => op(s, { op: 'toggle', on: v })" /></div>
            <template v-if="s.on">
              <div v-for="f in s.funds" :key="f.code" class="fr">
                <div class="fn"><div>{{ f.name }}</div><small>{{ f.code }}</small></div>
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
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { showConfirmDialog, showSuccessToast, showFailToast } from 'vant'
import { get, peek, post, dataVer } from '../api'
import { money } from '../fmt'
import SubBar from '../components/SubBar.vue'
const aid = useRoute().params.aid
const url = `/api/acct/${aid}/weights`
const d = ref(peek(url) || null)
const load = async (fresh = false) => { d.value = await get(url, { fresh }) }
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
.fn{ flex:1; min-width:0; font-size:13.5px; } .fn div{ white-space:nowrap; overflow:hidden; text-overflow:ellipsis; } .fn small{ font-size:11.5px; color:var(--muted); }
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
  .slot-grid{ display:grid; grid-template-columns:1fr 1fr; gap:10px; padding:0 12px; align-items:start; }
  .slot-grid .card{ margin:0; }
}

.sel-page{ max-width:960px; margin:0 auto; }
.cur{ padding:14px 16px; }
.cur .cl{ font-size:15px; } .cur .cl b{ color:var(--brand); }
.cur p{ font-size:12.5px; color:var(--sub); line-height:1.7; margin:6px 0 0; }
.cur .go{ display:inline-flex; align-items:center; gap:3px; font-size:12.5px; color:var(--brand); margin-top:8px; text-decoration:none; }
@media (min-width:900px){
  .slot-grid{ display:grid; grid-template-columns:1fr 1fr; gap:10px; padding:0 12px; align-items:start; }
  .slot-grid .card{ margin:0; }
}
</style>
