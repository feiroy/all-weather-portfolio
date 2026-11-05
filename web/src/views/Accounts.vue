<template>
  <div class="page no-tab">
    <div class="wrap">
      <div class="brand"><img src="/icon.svg" alt="" /><span>全天候再平衡</span>
        <UpdateBtn class="upd" /></div>
      <div class="sec-t"><span>选择账户</span></div>
      <van-skeleton v-if="!list" :row="4" style="padding:16px" />
      <div v-else class="grid">
        <div v-for="a in list" :key="a.id" class="acard" :class="{ last: a.id === last }" @click="$router.push(`/a/${a.id}`)">
          <template v-if="a.error"><div class="row1"><b>{{ a.name || a.id }}</b></div><div class="st err">打不开：{{ a.error }}</div></template>
          <template v-else>
            <div class="row1"><b>{{ a.name }}</b><span class="tag" :class="a.kind === '模拟' ? 'sim' : 'real'">{{ a.kind }}</span>
              <span v-if="a.id === last" class="tag gray">上次用</span>
              <van-icon name="arrow" class="go" /></div>
            <div class="st">跟随 {{ a.strategy_name }} · {{ a.n_trades }} 笔</div>
            <div class="amt num">¥{{ money(a.total) }}</div>
            <div class="pnl num"><span :class="tone(a.pnl)">{{ signed(a.pnl) }}</span>
              <span :class="tone(a.pnl_pct)">{{ pct(a.pnl_pct) }}</span><small>持有收益</small></div>
          </template>
        </div>
        <div class="acard add" @click="openNew"><van-icon name="plus" /><span>新建账户</span><small>模拟盘试策略 / 再开一个实盘</small></div>
      </div>
      <template v-if="trash.length">
        <div class="sec-t"><span>回收站 · {{ trash.length }}</span></div>
        <van-cell-group inset>
          <van-cell v-for="t in trash" :key="t.file" :title="t.name" :label="`${t.kind} · ${t.deleted || ''} 删除`">
            <template #value>
              <a class="lk" @click="restore(t)">恢复</a><a class="lk red" @click="purge(t)">彻底删除</a>
            </template>
          </van-cell>
        </van-cell-group>
      </template>
    </div>

    <!-- 新建账户 -->
    <van-popup v-model:show="showNew" position="bottom" round closeable :style="{ maxHeight: '90vh' }">
      <div class="pop">
        <h4>新建账户</h4>
        <van-cell-group inset>
          <van-field v-model="f.name" label="名字" placeholder="比如 模拟-风险平价" maxlength="20" :label-width="76" />
          <van-cell title="类型"><template #value><span class="seg2"><button v-for="k in ['模拟', '实盘']" :key="k" :class="{ on: f.kind === k }" @click="f.kind = k">{{ k }}</button></span></template></van-cell>
          <van-cell title="跟随策略" :value="stgName(f.strategy)" is-link @click="showStg = true" />
          <van-cell title="选基配置" :value="f.from ? `抄「${list.find(a => a.id === f.from)?.name}」` : '项目默认'" is-link @click="showFrom = true" />
          <van-cell v-if="f.from" title="连交易记录一起复制" center>
            <template #right-icon><van-switch v-model="f.copy_trades" size="20px" /></template>
          </van-cell>
          <template v-if="!f.copy_trades || !f.from">
            <van-field v-model="f.capital" label="起始资金" type="number" placeholder="0 = 之后用「转入」记" :label-width="76">
              <template #extra><span class="ex">元</span></template></van-field>
            <van-field :model-value="f.created" label="建立日期" readonly is-link :label-width="76" @click="showDate = true" />
          </template>
        </van-cell-group>
        <p class="tip" v-if="f.from && f.copy_trades">复制后两个账户各记各的，互不影响 —— 适合「如果当时换个策略会怎样」</p>
        <div class="btn-row"><van-button round block type="primary" :loading="saving" @click="create">创建并进入</van-button></div>
      </div>
    </van-popup>
    <van-action-sheet v-model:show="showFrom" :actions="fromActs" cancel-text="取消" close-on-click-action
                      description="新账户每个位置买哪几只基金" @select="x => { f.from = x.value; if (!x.value) f.copy_trades = false }" />
    <van-popup v-model:show="showStg" position="bottom" round>
      <van-picker title="跟随策略" :columns="stgCols" @confirm="({ selectedValues }) => { f.strategy = selectedValues[0]; showStg = false }" @cancel="showStg = false" />
    </van-popup>
    <van-popup v-model:show="showDate" position="bottom" round>
      <van-date-picker title="建立日期" v-model="dateParts" :max-date="new Date()" :min-date="new Date(2015, 0, 1)"
                       @confirm="({ selectedValues }) => { f.created = selectedValues.join('-'); showDate = false }" @cancel="showDate = false" />
    </van-popup>
  </div>
</template>
<script setup>
defineOptions({ name: 'Accounts' })
import { computed, reactive, ref, onActivated, watch } from 'vue'
import { useRouter } from 'vue-router'
import { showConfirmDialog, showSuccessToast, showFailToast } from 'vant'
import { get, peek, post, del, dataVer } from '../api'
import { money, signed, pct, tone } from '../fmt'
import UpdateBtn from '../components/UpdateBtn.vue'
const router = useRouter()
const c0 = peek('/api/accounts')
const list = ref(c0?.accounts || null), trash = ref(c0?.trash || []), asof = ref(c0?.asof || '')
const last = ref(localStorage.getItem('aw-last') || '')
const load = async (fresh = false) => {
  const r = await get('/api/accounts', { fresh })
  list.value = r.accounts; trash.value = r.trash; asof.value = r.asof
  last.value = localStorage.getItem('aw-last') || ''
}
load(); onActivated(() => load()); watch(dataVer, () => load(true))

const STG = [{ text: 'V3-B 保守增强', value: 'B-Con' }, { text: 'V3-B 风险平价', value: 'B-RP' }, { text: 'V3c 多元', value: 'V3c' }]
const stgCols = STG, stgName = k => STG.find(s => s.value === k)?.text
const today = new Date().toISOString().slice(0, 10)
const f = reactive({ name: '', kind: '模拟', strategy: 'B-Con', from: '', copy_trades: false, capital: '', created: today })
const dateParts = ref(today.split('-'))
const showFrom = ref(false)
const fromActs = computed(() => [{ name: '项目默认', subname: '每个位置一只默认 ETF', value: '' }, ...(list.value || []).map(a => ({ name: `抄「${a.name}」`, subname: '同样的基金和占比', value: a.id }))])
const showNew = ref(false), showStg = ref(false), showDate = ref(false), saving = ref(false)
function openNew() { Object.assign(f, { name: '', kind: '模拟', strategy: 'B-Con', from: '', copy_trades: false, capital: '', created: today }); showNew.value = true }
async function create() {
  if (!f.name.trim()) return showFailToast('起个名字')
  saving.value = true
  try {
    const r = await post('/api/accounts', { ...f, name: f.name.trim(), capital: +f.capital || 0 })
    showNew.value = false
    router.push(`/a/${r.id}`)
  } catch (e) { showFailToast(e.message) } finally { saving.value = false }
}
async function restore(t) {
  try { await post(`/api/trash/${t.file}/restore`, {}); showSuccessToast('已恢复'); load(true) } catch (e) { showFailToast(e.message) }
}
async function purge(t) {
  try { await showConfirmDialog({ title: `彻底删除「${t.name}」？`, message: '删了就找不回来了（git 历史里还有）', confirmButtonColor: '#E23B3B', confirmButtonText: '彻底删除' }) } catch { return }
  try { await del(`/api/trash/${t.file}`); load(true) } catch (e) { showFailToast(e.message) }
}
</script>
<style scoped>
.brand{ display:flex; align-items:center; gap:10px; padding:calc(18px + env(safe-area-inset-top)) 18px 4px; font-size:20px; font-weight:700; }
.brand img{ width:34px; height:34px; }
.upd{ margin-left:auto; font-weight:400; }
.grid{ display:grid; gap:12px; padding:0 12px; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); }
.acard{ background:#fff; border-radius:16px; padding:16px; cursor:pointer; border:1.5px solid transparent; }
.acard.last{ border-color:#C7D2FE; }
.acard:active{ transform:scale(.99); }
.row1{ display:flex; align-items:center; gap:8px; font-size:16px; }
.row1 .go{ margin-left:auto; color:var(--muted); }
.st{ font-size:12.5px; color:var(--muted); margin-top:4px; } .st.err{ color:var(--up); }
.amt{ font-size:26px; font-weight:700; margin-top:12px; letter-spacing:-.5px; }
.pnl{ display:flex; gap:10px; align-items:baseline; font-size:14px; font-weight:600; margin-top:2px; }
.pnl small{ color:var(--muted); font-weight:400; font-size:12px; }
.add{ display:flex; flex-direction:column; align-items:center; justify-content:center; gap:4px; border:1.5px dashed #D1D5DB; background:transparent; color:var(--sub); min-height:120px; }
.add .van-icon{ font-size:24px; color:var(--brand); } .add span{ font-size:15px; font-weight:600; } .add small{ font-size:12px; color:var(--muted); }
.lk{ color:var(--brand); margin-left:14px; font-size:13px; cursor:pointer; } .lk.red{ color:var(--up); }
.pop{ padding:18px 0 24px; max-width:560px; margin:0 auto; }
.pop h4{ margin:0 18px 12px; font-size:17px; }
.pop .seg2{ flex-wrap:wrap; justify-content:flex-end; }
.ex{ color:var(--muted); font-size:13px; margin-left:6px; }
.tip{ font-size:12px; color:var(--muted); margin:10px 18px 0; }
</style>
