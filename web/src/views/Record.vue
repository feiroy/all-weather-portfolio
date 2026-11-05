<template>
  <div class="page no-tab">
    <SubBar :title="editIdx == null ? '记一笔' : '改这一笔'" :fallback="`/a/${aid}/trades`" />
    <div class="wrap narrow">
      <van-skeleton v-if="!opt" :row="6" style="padding:16px" />
      <template v-else>
        <div class="seg">
          <button :class="{ on: side === '买入', buy: true }" @click="side = '买入'">买入</button>
          <button :class="{ on: side === '卖出', sell: true }" @click="side = '卖出'">卖出</button>
          <button :class="{ on: isMoney, money: true }" @click="side = '转入'">资金进出</button>
        </div>
        <van-cell-group inset>
          <van-field v-if="isMoney" label="方向" :label-width="72">
            <template #input>
              <span class="seg2"><button :class="{ on: side === '转入' }" @click="side = '转入'">转入</button>
                <button :class="{ on: side === '转出' }" @click="side = '转出'">转出</button></span>
            </template>
          </van-field>
          <van-field v-else :model-value="fund ? fund.name : ''" label="基金" placeholder="选一只基金" readonly is-link
                     @click="showFund = true" :label-width="72">
            <template #extra v-if="fund"><span class="ex">{{ fund.code }}</span></template>
          </van-field>
          <van-field :model-value="date" label="日期" readonly is-link @click="showDate = true" :label-width="72" />
          <van-field v-model="amount" label="金额" type="number" placeholder="0.00" :label-width="72" clearable>
            <template #extra><span class="ex">元</span></template>
          </van-field>
          <template v-if="!isMoney">
            <van-field v-model="nav" label="单价" type="number" :placeholder="navHint" :label-width="72"
                       @update:model-value="navTouched = true">
              <template #extra><span class="ex">元/{{ fund?.unit || '份' }}</span></template>
            </van-field>
            <van-field v-model="fee" label="手续费" type="number" placeholder="0.00" :label-width="72">
              <template #extra><span class="ex">元</span></template>
            </van-field>
          </template>
        </van-cell-group>

        <div class="preview" v-if="isMoney">
          {{ side === '转入' ? '钱进账户，计入本金；之后用「买入」把钱买成基金' : '钱从账户里拿走，本金相应减少' }}
        </div>
        <div class="preview" v-else-if="fund">
          <div>{{ fund.unit === '股' ? '场内 · 按股成交，100 股一手' : '场外 · 按份额申购，一天一个净值' }}</div>
          <div v-if="shares > 0">≈ <b class="num">{{ money(shares, fund.unit === '股' ? 0 : 2) }}</b> {{ fund.unit }}
            <template v-if="editIdx == null">，现金 ¥{{ money(opt.cash, 0) }} → <b class="num" :class="{ down: cashAfter < -1 }">¥{{ money(cashAfter, 0) }}</b></template></div>
          <div v-if="side === '卖出' && held != null">到这天持有 {{ money(held, fund.unit === '股' ? 0 : 2) }} {{ fund.unit }}
            <a @click="sellAll" v-if="held > 0 && Number(nav) > 0">全部卖出</a></div>
          <div class="warn" v-if="lotWarn">{{ lotWarn }}</div>
          <div class="warn" v-if="editIdx == null && cashAfter < -1">记完现金是负的 —— 账户里没这么多钱，先在「资金进出」记一笔转入，本金才对得上</div>
        </div>
        <p class="tip" v-if="fromCalc">从「调仓」带过来的金额，按支付宝里实际成交的改一下再存</p>

        <div class="btn-row">
          <van-button v-if="editIdx != null" round plain type="danger" @click="remove">删除</van-button>
          <van-button round type="primary" :loading="saving" @click="save">{{ editIdx == null ? '保存这一笔' : '保存修改' }}</van-button>
        </div>
      </template>
    </div>

    <van-popup v-model:show="showFund" position="bottom" round>
      <van-picker title="选择基金" :columns="fundCols" :model-value="fund ? [fund.code] : []" @confirm="pickFund" @cancel="showFund = false" />
    </van-popup>
    <van-popup v-model:show="showDate" position="bottom" round>
      <van-date-picker title="成交日期" v-model="dateParts" :max-date="today" :min-date="minDate"
                       @confirm="pickDate" @cancel="showDate = false" />
    </van-popup>
  </div>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showSuccessToast, showFailToast, showConfirmDialog } from 'vant'
import { get, post, put, del } from '../api'
import { money } from '../fmt'
import SubBar from '../components/SubBar.vue'

const route = useRoute(), router = useRouter()
const aid = route.params.aid
const q = route.query
const editIdx = q.edit != null ? Number(q.edit) : null
const opt = ref(null)
const side = ref(q.side === '卖出' ? '卖出' : '买入')
const isMoney = computed(() => side.value === '转入' || side.value === '转出')
const fund = ref(null)
const amount = ref(q.amount ? String(q.amount) : '')
const nav = ref(''), navHint = ref('选好基金和日期后自动带出'), navTouched = ref(false)
const fee = ref('')
const held = ref(null)
const fromCalc = !!q.amount
const showFund = ref(false), showDate = ref(false)
const today = new Date(), minDate = new Date(2015, 0, 1)
const date = ref(''), dateParts = ref([])
const saving = ref(false)

async function init() {
  const o = await get(`/api/acct/${aid}/record-options`, { fresh: true })
  let funds = o.funds
  if (editIdx != null) {
    const tr = await get(`/api/acct/${aid}/trades`, { fresh: true })
    const t = tr.rows.find(r => r.i === editIdx)
    if (!t) { showFailToast('这一笔不存在了'); return router.replace(`/a/${aid}/trades`) }
    side.value = t.side
    // 基金已经从选基配置里拿掉了也能改：临时补一项
    if (t.code && !funds.find(f => f.code === t.code)) funds = [...funds, { code: t.code, name: t.name, slot: '', unit: t.unit || '份' }]
    fund.value = funds.find(f => f.code === t.code) || null
    amount.value = String(t.amount)
    if (t.code) { nav.value = String(t.nav); navTouched.value = true }
    fee.value = t.fee ? String(t.fee) : ''
    date.value = t.date
  } else {
    fund.value = funds.find(f => f.code === q.code) || funds[0] || null
    date.value = o.asof
  }
  dateParts.value = date.value.split('-')
  opt.value = { ...o, funds }
}
init()
const fundCols = computed(() => (opt.value?.funds || []).map(f => ({ text: `${f.name}　${f.code}`, value: f.code })))
function pickFund({ selectedValues }) { fund.value = opt.value.funds.find(f => f.code === selectedValues[0]); navTouched.value = false; showFund.value = false }
function pickDate({ selectedValues }) { date.value = selectedValues.join('-'); showDate.value = false }

// 基金或日期一变就去取那天的净值（用户手改过单价就不覆盖）；改单笔时，持有数不算它自己
watch([fund, date], async () => {
  if (!fund.value || !date.value || isMoney.value) return
  const skip = editIdx != null ? `&skip=${editIdx}` : ''
  const r = await get(`/api/acct/${aid}/nav/${fund.value.code}?date=${date.value}${skip}`, { fresh: true })
  held.value = r.held
  if (r.nav) { navHint.value = String(r.nav); if (!navTouched.value) nav.value = String(r.nav) }
  else navHint.value = '这天没有净值，手工填成交价'
})
const shares = computed(() => {
  const a = +amount.value || 0, n = +nav.value || 0, f = +fee.value || 0
  if (n <= 0) return 0
  return side.value === '买入' ? (a - f) / n : (a + f) / n
})
const cashAfter = computed(() => (opt.value?.cash || 0) + (side.value === '卖出' ? 1 : -1) * (+amount.value || 0))
const lotWarn = computed(() => {
  if (!fund.value || fund.value.unit !== '股' || side.value !== '买入' || shares.value <= 0) return ''
  if (Math.abs(Math.round(shares.value) - shares.value) <= 0.01) return ''
  const near = Math.round(shares.value / 100) * 100
  return near <= 0 ? '场内买入按整手 100 股，这个金额不够一手' : `场内买入按整手 100 股；就近是 ${near} 股 ≈ ¥${money(near * nav.value)}`
})
function sellAll() { amount.value = (held.value * nav.value - (+fee.value || 0)).toFixed(2) }
const back = () => (window.history.state?.back ? router.back() : router.replace(`/a/${aid}/trades`))

async function save() {
  if (!isMoney.value && !fund.value) return showFailToast('先选基金')
  const b = { side: side.value, code: isMoney.value ? '' : fund.value.code, slot: isMoney.value ? '' : fund.value.slot,
              date: date.value, amount: +amount.value, nav: isMoney.value ? 1 : +nav.value, fee: isMoney.value ? 0 : +fee.value || 0 }
  saving.value = true
  try {
    if (editIdx == null) await post(`/api/acct/${aid}/trades`, b)
    else await put(`/api/acct/${aid}/trades/${editIdx}`, b)
    showSuccessToast(editIdx == null ? `已记录 ${side.value} ¥${money(+amount.value)}` : '已修改')
    back()
  } catch (e) {
    showFailToast({ message: e.message, duration: 3500 })
  } finally { saving.value = false }
}
async function remove() {
  try { await showConfirmDialog({ title: '删除这一笔？', message: '删了持仓和收益会按剩下的记录重算', confirmButtonColor: '#E23B3B' }) } catch { return }
  try { await del(`/api/acct/${aid}/trades/${editIdx}`); showSuccessToast('已删除'); back() } catch (e) { showFailToast(e.message) }
}
</script>
<style scoped>
.narrow{ max-width:960px !important; }
.seg{ display:flex; gap:10px; margin:12px 16px; }
.seg button{ flex:1; height:42px; border-radius:12px; border:1px solid var(--line); background:#fff; font-size:15px; font-weight:600; color:var(--sub); cursor:pointer; }
.seg button.on.buy{ background:#FEECEC; border-color:#FBC4C4; color:var(--up); }
.seg button.on.sell{ background:#E8F7EE; border-color:#B7E6C9; color:var(--down); }
.seg button.on.money{ background:var(--brand-soft); border-color:#C7D2FE; color:var(--brand); }
.ex{ color:var(--muted); font-size:13px; margin-left:6px; }
.preview{ margin:12px 18px 0; font-size:12.5px; color:var(--sub); line-height:1.8; }
.preview a{ color:var(--brand); margin-left:8px; cursor:pointer; }
.warn{ color:#B45309; }
.tip{ font-size:12px; color:var(--muted); margin:10px 18px 0; }
</style>
