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
          <span class="strat" title="策略在入口页的账户卡片上更换">跟随 {{ d.account.strategy_name }}</span>
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
                  <!-- 账户不存钱，钱都在基金里，所以不显示现金 -->
                  <div><div class="k">持有基金</div><div class="v num">{{ d.holdings.filter(h => h.held).length }} 只</div></div>
                </div>
                <div class="month" v-if="d.month.dates.length > 1">
                  <div class="mh"><span>近一个月</span>
                    <b class="num" :class="toneD(last(d.month.ret))">{{ pct(last(d.month.ret)) }}</b>
                    <span class="num">{{ signed(last(d.month.money), 0) }} 元</span></div>
                  <LineChart :dates="d.month.dates" :values="d.month.ret" :height="130" zero :zoom="false"
                             :fmt-tip="i => tipRows(dateText(d.month.dates[i]), [['收益率', pct(d.month.ret[i])], ['收益', signed(d.month.money[i], 0) + ' 元']])" />
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
              <!-- 持仓体检有异常：在首页直接提醒，不用点进体检页才发现 -->
              <router-link v-if="d.health_warn?.n" :to="`/a/${aid}/health`" class="health-warn">
                <van-icon name="warning-o" class="hw-i" />
                <div class="hw-t">
                  <b>持仓体检：{{ d.health_warn.n }} 项需要留意</b>
                  <span>{{ d.health_warn.items.map(i => `${i.label} ${i.over}`).join(' · ') }}</span>
                </div>
                <van-icon name="arrow" class="hw-go" />
              </router-link>
              <!-- 这一轮要不要动手 -->
              <van-cell-group inset class="status" :class="d.status.kind">
                <van-cell is-link :to="`/a/${aid}/calc`" :title="statusTitle" :label="statusLabel">
                  <template #icon><van-icon :name="d.status.kind === 'orders' ? 'bell' : 'passed'" class="si" :class="d.status.kind" /></template>
                </van-cell>
              </van-cell-group>
            </div>
            <div class="col">
              <!-- 持仓 -->
              <div class="sec-t"><span>我的基金 · {{ d.holdings.length }} 只</span><span>市值 / 收益（收益率）</span></div>
              <van-cell-group inset>
                <van-cell v-for="h in d.holdings" :key="h.code" is-link :to="`/a/${aid}/fund/${h.code}`" class="fund">
                  <template #title>
                    <div class="fn">{{ h.name }}</div>
                    <div class="fs">{{ h.code }} · {{ h.otc ? '场外' : '场内' }} · {{ h.slot }}
                      <span v-if="h.why" class="tag gray">{{ h.why }}</span></div>
                  </template>
                  <template #value>
                    <!-- 两行各带小字标签（用户 2026-11-08：「收益和收益率没任何提示就放个数，纯靠猜含义」）。
                         收益率用括号挂在金额后面，读作「收益 -72（-1.34%）」，不再是两个裸数字并排。
                         用两列 grid 而不是两个 flex 行：标签左列对齐、数值右列右对齐。 -->
                    <div class="fv2">
                      <span class="fv2k">市值</span>
                      <span class="fv2v num">{{ money(h.mv, 0) }}</span>
                      <span class="fv2k">收益</span>
                      <span v-if="h.held" class="fv2v num hold" :class="tone(h.hold)">{{ signed(h.hold, 0) }}<small>({{ pct(h.hold_pct) }})</small></span>
                      <span v-else class="fv2v nil">未持有</span>
                    </div>
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
import { tipRows } from '../utils/chartTheme'
import { dateText } from '../utils/chartAxis'
import MacroSeason from '../components/MacroSeason.vue'
import UpdateBtn from '../components/UpdateBtn.vue'

const route = useRoute()
const aid = computed(() => route.params.aid)
const url = () => `/api/acct/${aid.value}/home`
const d = ref(peek(url()) || null)
const refreshing = ref(false)
const last = a => a[a.length - 1]
const toneD = v => tone(v)   // 涨红跌绿由 .hero 内的样式统一控制
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
.top{ display:flex; align-items:center; gap:8px; padding:calc(24px + env(safe-area-inset-top)) 16px 10px; }
.acct{ display:flex; align-items:center; gap:4px; font-size:21px; font-weight:650; margin-right:2px; white-space:nowrap; cursor:pointer; }
.acct .van-icon{ font-size:13px; color:var(--muted); }
/* 头卡与全站卡片统一白底，靠大字号金额建立主次，不用深色块压住首屏 */
.hero{ margin:10px 12px 0; padding:18px 18px 10px; border-radius:18px; color:var(--ink);
  background:#fff; border:1px solid var(--line); }
.hero .k{ font-size:12px; color:var(--muted); }
.hero .asof{ float:right; color:var(--muted); }
.total{ font-size:34px; font-weight:700; letter-spacing:-1px; margin:4px 0 12px; color:var(--ink); }
/* KPI 行统一：**等分列 + 每格居中**（用户 2026-11-08 两轮反馈后的结论）。
   左对齐 → 最后一格右边空 240px；两端贴边 → 三块散在 0 / 45% / 88%，最后一块贴死右边缘也很怪。
   等分列 + 居中：三块落在 1/6、1/2、5/6，左右留白对称。 */
.grid3{ display:grid; grid-template-columns:repeat(3,1fr); gap:14px; padding-top:12px; border-top:1px solid var(--line); }
.grid3 > div{ min-width:0; text-align:center; }
.grid3 .v{ font-size:16px; font-weight:650; margin-top:3px; color:var(--ink); }
.grid3 .s{ font-size:12px; color:var(--muted); margin-top:1px; }
/* 白底上必须明确的涨红跌绿；提高特异性覆盖 .grid3 .v 的 --ink */
.hero .grid3 .v.up, .hero .grid3 .s.up, .hero .mh b.up{ color:var(--up) }
.hero .grid3 .v.down, .hero .grid3 .s.down, .hero .mh b.down{ color:var(--down) }
.month{ margin-top:14px; padding-top:10px; border-top:1px solid var(--line); }
.mh{ display:flex; gap:8px; align-items:baseline; font-size:12px; }
.mh span{ color:var(--muted); } .mh b{ font-size:15px; }
/* 提醒要显眼（用户 2026-11-07：白底弱化太多）：浅琥珀底 + 整圈描边 + 3px 左条，
   标题用深琥珀上色和图标成一套；圆角/外边距仍与「该动手了」对齐，不显得外挂 */
.health-warn{ display:flex; align-items:center; gap:10px; margin:12px 12px 0; padding:11px 14px;
  background:#FFF7E6; border:1px solid #FDE68A; border-left:3px solid #F59E0B;
  border-radius:14px; text-decoration:none; }
.health-warn .hw-t b{ color:#B45309; }   /* 比 .hw-t b 更具体，否则被后定义的 ink 色覆盖 */
.hw-i{ font-size:19px; color:#D97706; flex:0 0 auto; }
.hw-t{ min-width:0; flex:1; }
.hw-t b{ display:block; font-size:13.5px; color:var(--ink); }
.hw-t span{ display:block; font-size:11.5px; color:var(--sub); margin-top:2px;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.hw-go{ color:#D97706; flex:0 0 auto; }
/* 与体检卡同一套强度：浅底 + 整圈描边 + 3px 左条 + 标题上色。
   要动手 = 品牌蓝（--brand-soft 浅蓝底）；不用动 = 白卡无色条（透明占位，避免高度跳动） */
.status{ margin-top:12px !important; border-left:3px solid transparent; }
.status.orders{ background:var(--brand-soft); border:1px solid #C7D2FE; border-left:3px solid var(--brand); }
.status.orders :deep(.van-cell){ background:transparent; }
.status.orders :deep(.van-cell__title){ color:#1E3A8A; font-weight:600; }
.status.orders :deep(.van-cell__label){ color:#475569; }
.status.orders :deep(.si){ color:var(--brand); }
.upd{ margin-left:auto; }
.strat{ font-size:12px; color:var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.quick{ display:grid; grid-template-columns:repeat(4,1fr); margin:12px 12px 0; background:#fff; border-radius:14px; padding:14px 4px 10px; }
.quick a{ display:flex; flex-direction:column; align-items:center; gap:6px; font-size:12.5px; color:var(--sub); text-decoration:none; }
.quick i{ width:38px; height:38px; border-radius:12px; display:grid; place-items:center; font-size:20px; }
.si{ font-size:20px; margin-right:10px; align-self:center; color:var(--muted); }
.si.orders{ color:var(--brand); }
.fund :deep(.van-cell__title){ flex:1 1 auto; min-width:0; }
.fn{ font-size:15px; font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.fs{ font-size:12px; color:var(--muted); margin-top:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
/* 数值块：两列 grid（标签 / 数值），标签左列对齐、数值右列右对齐；
   两行分别是「市值」「收益（收益率）」。原来只放「-72 -1.34%」两个裸数字，
   用户 2026-11-08 反馈「纯靠猜含义」。 */
.fv2{ display:grid; grid-template-columns:auto 1fr; align-items:baseline;
  column-gap:8px; row-gap:1px; line-height:1.3; }
/* 列宽写死给同一值：每行都至少 132px，跨行才会右对齐（由窄变宽时不会各自缩成一团） */
.fund :deep(.van-cell__value){ flex:0 0 auto; min-width:132px; }
.fv2 > *{ white-space:nowrap; }   /* 绝不让「市值」「收益」竖排成一字一行 */
.fv2k{ font-size:11px; line-height:1.3; color:var(--muted); font-weight:400; letter-spacing:.02em; text-align:left; }
.fv2v{ font-size:15px; line-height:1.3; font-weight:600; color:var(--ink); font-variant-numeric:tabular-nums;
  letter-spacing:-.2px; text-align:right; }
/* 收益比市值轻一档：字号降一级，但仍比小字标签重，视线先看市值再看收益 */
.fv2v.hold{ font-size:13px; }
.fv2v small{ font-size:11px; font-weight:400; margin-left:4px; opacity:.75; }
.fv2v.nil{ font-size:12px; font-weight:400; color:var(--muted); letter-spacing:0; }
/* 涨红跌绿写在同一条上，避免被全局 .up/.down 的先后顺序影响 */
.fv2v.up{ color:var(--up); } .fv2v.down{ color:var(--down); }
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
