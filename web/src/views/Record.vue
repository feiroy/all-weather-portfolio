<template>
  <div class="page no-tab">
    <van-nav-bar title="记一笔" left-arrow @click-left="back" safe-area-inset-top />
    <div class="wrap">
      <van-skeleton v-if="!opt" :row="6" style="padding:16px" />
      <template v-else>
        <div class="seg">
          <button :class="{ on: side === '买入', buy: true }" @click="side = '买入'">买入</button>
          <button :class="{ on: side === '卖出', sell: true }" @click="side = '卖出'">卖出</button>
        </div>
        <van-cell-group inset>
          <van-field :model-value="fund ? fund.name : ''" label="基金" placeholder="选一只基金" readonly is-link
                     @click="showFund = true" :label-width="72">
            <template #extra v-if="fund"><span class="ex">{{ fund.code }}</span></template>
          </van-field>
          <van-field :model-value="date" label="日期" readonly is-link @click="showDate = true" :label-width="72" />
          <van-field v-model="amount" label="金额" type="number" placeholder="0.00" :label-width="72" clearable>
            <template #extra><span class="ex">元</span></template>
          </van-field>
          <van-field v-model="nav" :label="`单价`" type="number" :placeholder="navHint" :label-width="72"
                     @update:model-value="navTouched = true">
            <template #extra><span class="ex">元/{{ fund?.unit || '份' }}</span></template>
          </van-field>
          <van-field v-model="fee" label="手续费" type="number" placeholder="0.00" :label-width="72">
            <template #extra><span class="ex">元</span></template>
          </van-field>
        </van-cell-group>

        <div class="preview" v-if="fund">
          <div>{{ fund.unit === '股' ? '场内 · 按股成交，100 股一手' : '场外 · 按份额申购，一天一个净值' }}</div>
          <div v-if="shares > 0">≈ <b class="num">{{ money(shares, fund.unit === '股' ? 0 : 2) }}</b> {{ fund.unit }}
            ，现金 ¥{{ money(opt.cash, 0) }} → <b class="num" :class="{ down: cashAfter < -1 }">¥{{ money(cashAfter, 0) }}</b></div>
          <div v-if="side === '卖出' && held != null">到这天持有 {{ money(held, fund.unit === '股' ? 0 : 2) }} {{ fund.unit }}
            <a @click="sellAll" v-if="held > 0 && Number(nav) > 0">全部卖出</a></div>
          <div class="warn" v-if="lotWarn">{{ lotWarn }}</div>
          <div class="warn" v-if="cashAfter < -1">记完现金会变成负的 —— 账户里没有这么多现金</div>
        </div>
        <p class="tip" v-if="fromCalc">从「调仓」带过来的，按支付宝里实际成交的改一下再存</p>

        <div class="act"><van-button round block type="primary" :loading="saving" @click="save">保存这一笔</van-button></div>
      </template>
    </div>

    <van-popup v-model:show="showFund" position="bottom" round>
      <van-picker title="选择基金" :columns="fundCols" @confirm="pickFund" @cancel="showFund = false" />
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
import { showSuccessToast, showFailToast } from 'vant'
import { get, post } from '../api'
import { money } from '../fmt'

const route = useRoute(), router = useRouter()
const aid = route.params.aid
const q = route.query
const opt = ref(null)
const side = ref(q.side === '卖出' ? '卖出' : '买入')
const fund = ref(null)
const amount = ref(q.amount ? String(q.amount) : '')
const nav = ref(''), navHint = ref('选好基金和日期后自动带出'), navTouched = ref(false)
const fee = ref('')
const held = ref(null)
const fromCalc = !!q.amount
const showFund = ref(false), showDate = ref(false)
const today = new Date(), minDate = new Date(2015, 0, 1)
const date = ref('')
const dateParts = ref([])
const saving = ref(false)

get(`/api/acct/${aid}/record-options`).then(o => {
  opt.value = o
  date.value = o.asof
  dateParts.value = o.asof.split('-')
  fund.value = o.funds.find(f => f.code === q.code) || o.funds[0] || null
})
const fundCols = computed(() => (opt.value?.funds || []).map(f => ({ text: `${f.name}　${f.code}`, value: f.code })))
function pickFund({ selectedValues }) { fund.value = opt.value.funds.find(f => f.code === selectedValues[0]); showFund.value = false }
function pickDate({ selectedValues }) { date.value = selectedValues.join('-'); showDate.value = false }

// 基金或日期一变就去取那天的净值（用户手改过单价就不覆盖）
watch([fund, date], async () => {
  if (!fund.value || !date.value) return
  const r = await get(`/api/acct/${aid}/nav/${fund.value.code}?date=${date.value}`, { fresh: true })
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
const back = () => (window.history.state?.back ? router.back() : router.replace(`/a/${aid}`))

async function save() {
  if (!fund.value) return showFailToast('先选基金')
  saving.value = true
  try {
    await post(`/api/acct/${aid}/trades`, { side: side.value, code: fund.value.code, slot: fund.value.slot,
      date: date.value, amount: +amount.value, nav: +nav.value, fee: +fee.value || 0 })
    showSuccessToast(`已记录 ${side.value} ¥${money(+amount.value)}`)
    back()
  } catch (e) {
    showFailToast({ message: e.message, duration: 3500 })
  } finally { saving.value = false }
}
</script>
<style scoped>
.seg{ display:flex; gap:10px; margin:12px 16px; }
.seg button{ flex:1; height:42px; border-radius:12px; border:1px solid var(--line); background:#fff; font-size:15px; font-weight:600; color:var(--sub); }
.seg button.on.buy{ background:#FEECEC; border-color:#FBC4C4; color:var(--up); }
.seg button.on.sell{ background:#E8F7EE; border-color:#B7E6C9; color:var(--down); }
.ex{ color:var(--muted); font-size:13px; margin-left:6px; }
.preview{ margin:12px 18px 0; font-size:12.5px; color:var(--sub); line-height:1.8; }
.preview a{ color:var(--brand); margin-left:8px; }
.warn{ color:#B45309; }
.tip{ font-size:12px; color:var(--muted); margin:10px 18px 0; }
.act{ margin:22px 16px 0; }
</style>
