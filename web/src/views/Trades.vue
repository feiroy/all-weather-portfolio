<template>
  <div class="page">
    <div class="wrap">
      <div class="ptitle"><b>交易记录</b>
        <div class="acts">
          <van-button size="small" round plain icon="down" @click="showExport = true">导出报告</van-button>
          <van-button size="small" round type="primary" icon="plus" :to="`/a/${aid}/record`">记一笔</van-button>
        </div></div>
      <van-skeleton v-if="!d" :row="8" style="padding:16px" />
      <template v-else>
        <div class="sum">
          <div><span>买入</span><b class="num up">¥{{ money(tot.buy, 0) }}</b><small>{{ tot.nb }} 笔</small></div>
          <div><span>卖出</span><b class="num down">¥{{ money(tot.sell, 0) }}</b><small>{{ tot.ns }} 笔</small></div>
          <div><span>转入</span><b class="num">¥{{ money(tot.inn, 0) }}</b><small>{{ tot.ni }} 笔</small></div>
        </div>
        <div class="card exec" v-if="plan.length">
          <div class="ch"><b>本轮执行进度</b><span class="num">{{ matched }} / {{ plan.length }} 笔</span></div>
          <div class="bar"><i :style="{ width: (plan.length ? matched / plan.length * 100 : 0) + '%' }"></i></div>
          <p>按「基金 + 买卖方向」把最近 7 天的实际记录和当前调仓清单对照；金额以支付宝实际成交为准</p>
        </div>
        <div class="chips filt">
          <span class="chip" :class="{ on: !code }" @click="code = ''">全部</span>
          <span class="chip" :class="{ on: code === '$' }" @click="code = '$'">资金进出</span>
          <span v-for="c in d.codes" :key="c.code" class="chip" :class="{ on: code === c.code }" @click="code = c.code">{{ short(c.name) }}</span>
        </div>
        <template v-for="g in groups" :key="g.date">
          <div class="sec-t"><span class="num">{{ g.date.replace(/-/g, '/') }} {{ wk(g.date) }}</span>
            <span class="num">{{ g.rows.length }} 笔</span></div>
          <van-cell-group inset>
            <van-swipe-cell v-for="t in g.rows" :key="t.i">
              <van-cell is-link @click="edit(t)" class="trow">
                <template #title>
                  <div class="t1"><span class="tag" :class="cls(t.side)">{{ t.side }}</span>
                    <span v-if="t.close" class="tag liq">清仓</span>
                    <span class="tn">{{ t.name || '资金' }}</span></div>
                  <div class="t2 num" v-if="t.code">{{ t.code }} · {{ money(t.shares, t.unit === '股' ? 0 : 2) }} {{ t.unit }} × {{ money(t.nav, 4) }}<template v-if="t.fee"> · 费 {{ money(t.fee) }}</template></div>
                  <div class="t2" v-else>{{ t.side === '转入' ? '钱进账户（计入本金）' : '钱出账户' }}</div>
                </template>
                <template #value><b class="num ta" :class="{ 买入: 'up', 卖出: 'down' }[t.side] || ''">{{ sign(t.side) }}¥{{ money(t.amount) }}</b></template>
              </van-cell>
              <template #right><van-button square type="danger" text="删除" class="del" @click="remove(t)" /></template>
            </van-swipe-cell>
          </van-cell-group>
        </template>
        <van-empty v-if="!groups.length" image-size="80" description="还没有记录，点右上角「记一笔」" />
        <p class="empty-tip" v-else>左滑一笔可删除，点开可修改</p>
      </template>
    </div>
    <van-action-sheet v-model:show="showExport" :actions="exportActs" cancel-text="取消"
                      description="导出当前账户的汇总、持仓、流水和每日收益" close-on-click-action @select="doExport" />
    <TabBar :aid="aid" active="trades" />
  </div>
</template>
<script setup>
defineOptions({ name: 'Trades' })
import { computed, ref, onActivated, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showConfirmDialog, showSuccessToast, showFailToast } from 'vant'
import { get, peek, del, dataVer } from '../api'
import { money } from '../fmt'
import TabBar from '../components/TabBar.vue'

const route = useRoute(), router = useRouter()
const aid = route.params.aid
const url = `/api/acct/${aid}/trades`
const d = ref(peek(url) || null)
const plan = ref([])
get(`/api/acct/${aid}/calc`).then(x => { plan.value = x.orders || [] }).catch(() => {})
const weekAgo = new Date(Date.now() - 7 * 864e5).toISOString().slice(0, 10)
const matched = computed(() => {
  const rows = (d.value?.rows || []).filter(t => t.date >= weekAgo)
  return plan.value.filter(o => rows.some(t => t.code === o.code && t.side === o.side)).length
})
const showExport = ref(false)
const exportActs = [{ name: 'Markdown 报告' }, { name: 'Excel 报告' }]
function doExport(x) { window.location.href = `/api/acct/${aid}/export?fmt=${x.name.includes('Excel') ? 'xlsx' : 'md'}` }
const code = ref('')
const load = async (fresh = false) => { d.value = await get(url, { fresh }) }
load(); onActivated(() => load()); watch(dataVer, () => load(true))

const rows = computed(() => (d.value?.rows || []).filter(t => !code.value ? true : code.value === '$' ? !t.code : t.code === code.value))
const groups = computed(() => {
  const m = new Map()
  for (const t of rows.value) { if (!m.has(t.date)) m.set(t.date, []); m.get(t.date).push(t) }
  return [...m].map(([date, rows]) => ({ date, rows }))
})
const tot = computed(() => {
  const r = rows.value, s = side => r.filter(t => t.side === side)
  return { buy: s('买入').reduce((a, t) => a + t.amount, 0), nb: s('买入').length,
           sell: s('卖出').reduce((a, t) => a + t.amount, 0), ns: s('卖出').length,
           inn: s('转入').reduce((a, t) => a + t.amount, 0) - s('转出').reduce((a, t) => a + t.amount, 0), ni: s('转入').length + s('转出').length }
})
const cls = s => (s === '买入' ? 'buy' : s === '卖出' ? 'sell' : 'gray')
const sign = s => (s === '买入' || s === '转出' ? '-' : '+')
const short = n => (n.length > 9 ? n.slice(0, 9) + '…' : n)
const wk = s => '周' + '日一二三四五六'[new Date(s).getDay()]
const edit = t => router.push({ path: `/a/${aid}/record`, query: { edit: t.i } })
async function remove(t) {
  try {
    await showConfirmDialog({ title: '删除这一笔？', message: `${t.date} ${t.side} ${t.name || ''} ¥${money(t.amount)}\n删了持仓和收益会按剩下的记录重算`, confirmButtonColor: '#E23B3B' })
  } catch { return }
  try { await del(`${url}/${t.i}`); showSuccessToast('已删除'); load(true) } catch (e) { showFailToast(e.message) }
}
</script>
<style scoped>
.acts{ margin-left:auto; display:flex; gap:8px; }
.exec{ padding:12px 14px; }
.exec .ch{ display:flex; justify-content:space-between; font-size:14px; } .exec .ch span{ color:var(--brand); }
.exec .bar{ height:6px; border-radius:3px; background:#F1F2F4; margin:10px 0 6px; overflow:hidden; }
.exec .bar i{ display:block; height:100%; background:var(--brand); border-radius:3px; }
.exec p{ font-size:11.5px; color:var(--muted); line-height:1.6; margin:0; }
.ptitle{ display:flex; align-items:center; gap:8px; padding:calc(14px + env(safe-area-inset-top)) 16px 2px; font-size:20px; }
.add{ margin-left:auto; }
.sum{ display:grid; grid-template-columns:repeat(3,1fr); margin:12px 12px 0; background:#fff; border-radius:14px; padding:12px 8px; text-align:center; }
.sum span{ display:block; font-size:12px; color:var(--muted); } .sum b{ display:block; font-size:16px; margin-top:4px; }
.sum small{ font-size:11px; color:var(--muted); }
.filt{ margin-top:12px; }
.t1{ display:flex; align-items:center; gap:6px; }
.tn{ font-size:14.5px; font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.t2{ font-size:12px; color:var(--muted); margin-top:3px; }
.trow :deep(.van-cell__title){ flex:1.8; min-width:0; }
.ta{ font-size:15px; } .ta.gray{ color:var(--ink); }
.tag.liq{ color:#fff; background:#16A34A; }
.del{ height:100%; }
@media (min-width:900px){ .ptitle{ padding-top:16px; } }
</style>
