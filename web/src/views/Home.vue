<template>
  <div class="page">
    <van-pull-refresh v-model="refreshing" @refresh="load(true)" success-text="已更新">
      <div class="wrap">
        <!-- 顶栏：账户名（点了回账户列表）· 类型 · 跟随策略 -->
        <div class="top" v-if="d">
          <div class="acct" @click="$router.push('/')">
            <b>{{ d.account.name }}</b><van-icon name="arrow-down" />
          </div>
          <span class="tag" :class="d.account.kind === '模拟' ? 'sim' : 'real'">{{ d.account.kind }}</span>
          <span class="tag gray">{{ d.account.strategy_name }}</span>
        </div>
        <van-skeleton v-if="!d" title :row="8" style="padding:20px 16px" />
        <template v-else>
          <div class="cols">
            <div class="col">
              <!-- 资产卡 -->
              <div class="hero">
                <div class="k">总金额（元）<span class="asof">净值 {{ d.summary.asof.slice(5).replace('-', '/') }}</span></div>
                <div class="total num">{{ money(d.summary.total) }}</div>
                <div class="grid3">
                  <div><div class="k">今日收益</div>
                    <div class="v num" :class="toneD(d.summary.today)">{{ signed(d.summary.today) }}</div>
                    <div class="s num" :class="toneD(d.summary.today_pct)">{{ pct(d.summary.today_pct) }}</div></div>
                  <div><div class="k">持有收益</div>
                    <div class="v num" :class="toneD(d.summary.pnl)">{{ signed(d.summary.pnl) }}</div>
                    <div class="s num" :class="toneD(d.summary.pnl_pct)">{{ pct(d.summary.pnl_pct) }}</div></div>
                  <div><div class="k">持有基金</div><div class="v num">{{ d.holdings.filter(h => h.held).length }} 只</div>
                    <div class="s" v-if="d.summary.cash >= 1">现金 ¥{{ money(d.summary.cash, 0) }}</div></div>
                </div>
                <div class="month" v-if="d.month.dates.length > 1">
                  <div class="mh"><span>近一个月</span>
                    <b class="num" :class="toneD(last(d.month.ret))">{{ pct(last(d.month.ret)) }}</b>
                    <span class="num">{{ signed(last(d.month.money), 0) }} 元</span></div>
                  <LineChart :dates="d.month.dates" :values="d.month.ret" :height="130" dark zero
                             :fmt-tip="i => `${d.month.dates[i]}<br/><b>${pct(d.month.ret[i])}</b>　${signed(d.month.money[i], 0)} 元`" />
                </div>
              </div>
              <!-- 这一轮要不要动手 -->
              <van-cell-group inset class="status">
                <van-cell is-link :to="`/a/${aid}/calc`" :title="statusTitle" :label="statusLabel">
                  <template #icon><van-icon :name="d.status.kind === 'orders' ? 'bell' : 'passed'" class="si" :class="d.status.kind" /></template>
                </van-cell>
              </van-cell-group>
            </div>
            <div class="col">
              <!-- 持仓 -->
              <div class="sec-t"><span>我的基金 · {{ d.holdings.length }} 只</span><span>金额 / 持有收益</span></div>
              <van-cell-group inset>
                <van-cell v-for="h in d.holdings" :key="h.code" is-link :to="`/a/${aid}/fund/${h.code}`" class="fund">
                  <template #title>
                    <div class="fn">{{ h.name }}</div>
                    <div class="fs">{{ h.code }} · {{ h.otc ? '场外' : '场内' }} · {{ h.slot }}
                      <span v-if="h.why" class="tag gray">{{ h.why }}</span></div>
                  </template>
                  <template #value>
                    <div class="fv num">{{ money(h.mv, 0) }}</div>
                    <div class="fp num" :class="tone(h.hold)">{{ h.held ? signed(h.hold, 0) + ' · ' + pct(h.hold_pct) : '未持有' }}</div>
                  </template>
                </van-cell>
              </van-cell-group>
            </div>
          </div>
        </template>
      </div>
    </van-pull-refresh>
    <TabBar :aid="aid" active="home" />
  </div>
</template>
<script setup>
defineOptions({ name: 'Home' })
import { computed, ref, onActivated, watch } from 'vue'
import { useRoute } from 'vue-router'
import { get, peek } from '../api'
import { money, signed, pct, tone } from '../fmt'
import TabBar from '../components/TabBar.vue'
import LineChart from '../components/LineChart.vue'

const route = useRoute()
const aid = computed(() => route.params.aid)
const url = () => `/api/acct/${aid.value}/home`
const d = ref(peek(url()) || null)
const refreshing = ref(false)
const last = a => a[a.length - 1]
const toneD = v => tone(v)   // 蓝底上的颜色在样式里换浅色
async function load(fresh = false) {
  try { d.value = await get(url(), { fresh }) } finally { refreshing.value = false }
}
load(); onActivated(() => load()); watch(aid, () => { d.value = peek(url()) || null; load() })
const statusTitle = computed(() => {
  const s = d.value?.status
  if (!s) return ''
  return s.kind === 'orders' ? `该动手了 · ${s.n} 笔要下${s.liq ? `（含 ${s.liq} 笔清仓）` : ''}`
    : s.kind === 'stuck' ? `偏离超标，但这一轮买不进` : '这一轮不用动'
})
const statusLabel = computed(() => {
  const s = d.value?.status
  if (!s) return ''
  return s.kind === 'orders' ? `买入 ¥${money(s.buy, 0)} · 卖出 ¥${money(s.sell, 0)}`
    : s.kind === 'stuck' ? `${s.n} 个位置超过 0.5%，一手就顶掉整个缺口` : '仓位都在目标附近，不折腾省手续费'
})
</script>
<style scoped>
.top{ display:flex; align-items:center; gap:8px; padding:calc(12px + env(safe-area-inset-top)) 16px 4px; }
.acct{ display:flex; align-items:center; gap:4px; font-size:18px; margin-right:2px; }
.acct .van-icon{ font-size:13px; color:var(--muted); }
.hero{ margin:10px 12px 0; padding:18px 18px 10px; border-radius:18px; color:#fff;
  background:linear-gradient(135deg,#1E3A8A 0%,#1E40AF 55%,#3B82F6 100%); box-shadow:0 8px 24px rgba(30,64,175,.22); }
.hero .k{ font-size:12px; opacity:.78; }
.hero .asof{ float:right; opacity:.85; }
.total{ font-size:34px; font-weight:700; letter-spacing:-1px; margin:4px 0 12px; }
.grid3{ display:grid; grid-template-columns:repeat(3,1fr); gap:6px; padding-top:12px; border-top:1px solid rgba(255,255,255,.18); }
.grid3 .v{ font-size:16px; font-weight:650; margin-top:3px; }
.grid3 .s{ font-size:12px; opacity:.85; margin-top:1px; }
.hero .up{ color:#FCA5A5 } .hero .down{ color:#86EFAC }
.month{ margin-top:14px; padding-top:10px; border-top:1px solid rgba(255,255,255,.18); }
.mh{ display:flex; gap:8px; align-items:baseline; font-size:12px; }
.mh span{ opacity:.8 } .mh b{ font-size:15px; }
.status{ margin-top:12px !important; }
.si{ font-size:20px; margin-right:10px; align-self:center; color:var(--muted); }
.si.orders{ color:var(--brand); }
.fund :deep(.van-cell__title){ flex:1.6; min-width:0; }
.fn{ font-size:15px; font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.fs{ font-size:12px; color:var(--muted); margin-top:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.fv{ font-size:15px; color:var(--ink); font-weight:600; }
.fp{ font-size:12px; margin-top:2px; }
.cols{ display:block; }
@media (min-width:900px){
  .cols{ display:grid; grid-template-columns:420px 1fr; gap:4px; align-items:start; }
  .cols .col:last-child .sec-t{ margin-top:10px; }
}
</style>
