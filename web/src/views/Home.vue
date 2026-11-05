<template>
  <div class="page">
    <van-pull-refresh v-model="refreshing" @refresh="load(true)" success-text="已更新">
      <div class="wrap">
        <!-- 顶栏：账户名（点了回账户列表）· 策略名淡灰小字 · 一个更新图标 -->
        <div class="top" v-if="d">
          <div class="acct" @click="$router.push('/')">
            <b>{{ d.account.name }}</b><van-icon name="arrow-down" />
          </div>
          <span v-if="d.account.kind === '模拟'" class="tag sim">模拟</span>
          <span class="strat">{{ d.account.strategy_name }}</span>
          <UpdateBtn class="m-only upd" compact />
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
              <!-- 宏观季节：头卡下方一行小卡 -->
              <MacroSeason />
              <!-- 快捷入口：收益 / 对比 / 体检 / 选基 -->
              <div class="quick">
                <router-link v-for="q in quick" :key="q.to" :to="`/a/${aid}/${q.to}`">
                  <i :style="{ background: q.bg, color: q.c }"><van-icon :name="q.icon" /></i><span>{{ q.t }}</span>
                </router-link>
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
import { get, peek, dataVer } from '../api'
import { money, signed, pct, tone } from '../fmt'
import TabBar from '../components/TabBar.vue'
import LineChart from '../components/LineChart.vue'
import MacroSeason from '../components/MacroSeason.vue'
import UpdateBtn from '../components/UpdateBtn.vue'

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
watch(dataVer, () => load(true))
const quick = [
  { t: '收益明细', to: 'period', icon: 'calendar-o', bg: '#FEECEC', c: '#E23B3B' },
  { t: '和基准比', to: 'compare', icon: 'chart-trending-o', bg: '#EEF2FF', c: '#1E40AF' },
  { t: '持仓体检', to: 'health', icon: 'shield-o', bg: '#E8F7EE', c: '#16A34A' },
  { t: '选基配置', to: 'weights', icon: 'apps-o', bg: '#FEF3C7', c: '#B45309' },
]
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
.acct{ display:flex; align-items:center; gap:4px; font-size:18px; margin-right:2px; white-space:nowrap; cursor:pointer; }
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
.upd{ margin-left:auto; }
.strat{ font-size:12px; color:var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.quick{ display:grid; grid-template-columns:repeat(4,1fr); margin:12px 12px 0; background:#fff; border-radius:14px; padding:14px 4px 10px; }
.quick a{ display:flex; flex-direction:column; align-items:center; gap:6px; font-size:12.5px; color:var(--sub); text-decoration:none; }
.quick i{ width:38px; height:38px; border-radius:12px; display:grid; place-items:center; font-size:20px; }
.si{ font-size:20px; margin-right:10px; align-self:center; color:var(--muted); }
.si.orders{ color:var(--brand); }
.fund :deep(.van-cell__title){ flex:1.6; min-width:0; }
.fn{ font-size:15px; font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.fs{ font-size:12px; color:var(--muted); margin-top:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.fv{ font-size:15px; color:var(--ink); font-weight:600; }
.fp{ font-size:12px; margin-top:2px; }
.cols{ display:block; }
@media (min-width:900px){
  /* 顶部导航已经有账户名和切换入口，资产页这行在电脑上重复，隐藏 */
  .top{ display:none; }
  .cols{ max-width:960px; margin:0 auto; padding-top:12px; }
  .cols .col:last-child .sec-t{ margin-top:16px; }
  /* 持仓列表桌面两列，长列表不拖成一整条 */
  .cols .col:last-child :deep(.van-cell-group){ display:grid; grid-template-columns:1fr 1fr; gap:0 10px; }
}
</style>
