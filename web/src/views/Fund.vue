<template>
  <div class="page no-tab">
    <van-nav-bar class="subbar" title="基金详情" left-arrow @click-left="back" safe-area-inset-top />
    <div class="wrap">
      <van-skeleton v-if="!d" title :row="10" style="padding:16px" />
      <template v-else>
        <div class="card head">
          <!-- 名称从顶栏挪进卡片：顶栏只剩页面名，编号/类型才挂得上「标题旁边」，
               顶栏宽度有限、长基金名会被挤掉，放正文里也不会省掉任何信息 -->
          <div class="hrow">
            <h1 class="fname">{{ h.name }}</h1>
            <span class="code num">{{ h.code }}</span>
            <span class="kind">{{ h.otc ? '场外' : '场内' }}</span>
          </div>
          <div class="meta">
            <span v-if="h.slot" class="chipx">{{ h.slot }}</span>
            <!-- 目标与实际并排才看得出偏了多少，也避免「占账户」单独占一个胶囊、
               在手机上折行后只剩它一个孤零零挂在第二行 -->
            <span v-if="h.w_tgt != null" class="chipx">目标 {{ h.w_tgt.toFixed(1) }}%<template v-if="!h.otc"> · 实际 {{ h.w_now }}%</template></span>
            <!-- side/amount 是再平衡算出来的「这一轮该买卖多少」，没执行前台账里是查不到的，
                 所以写「建议」而不是「本轮」——后者会被读成已经成交 -->
            <span v-if="h.side" class="tag" :class="h.side === '买入' ? 'buy' : 'sell'">{{ h.liq ? '建议清仓' : '建议' + h.side }} ¥{{ money(h.amount, 0) }}</span>
            <span v-else-if="h.note" class="chipx">{{ h.note }}</span>
          </div>
          <!-- 场内市值按市价算，折溢价就用全站统一的徽标挂在数字边上 ——
               不另起一行写「净值口径 ¥21,912 / −125.78 / 差的就是折溢价」，
               那两个价格在下面栅格里并排摆着，多写一行只会把大数字挤散 -->
          <div class="mv num">¥{{ money(h.mv) }}<PremiumTag v-if="q && !h.otc" :q="q" class="mvpq" /></div>
          <div class="g">
            <!-- 今天净值还没出时 day/day_pct 是 0（不是「涨跌为零」），照原样写「+0.00」
                 就是在撒谎 —— 直接显示「待更新」（2026-11-18 用户要求） -->
            <div><span>今日收益</span><b class="num" :class="h.day_state ? 'pend' : tone(showDay)">{{ h.day_state || signed(showDay) }}</b></div>
            <div><span>今日收益率</span><b class="num" :class="h.day_state ? 'pend' : tone(showDayPct)">{{ h.day_state || pct(showDayPct) }}</b></div>
            <div><span>持有收益</span><b class="num" :class="tone(h.hold)">{{ signed(h.hold) }}</b></div>
            <div><span>持有收益率</span><b class="num" :class="tone(h.hold_pct)">{{ pct(h.hold_pct) }}</b></div>
            <div><span>{{ h.otc ? '份额' : '股数' }}</span><b class="num">{{ qty(h.shares, h.unit) }}</b></div>
            <div><span>成本价</span><b class="num">{{ money(h.cost, 4) }}</b></div>
            <!-- 净值日 / 行情时间必须钉在数字底下：场外当天净值 21:00 后才公布，
                 场内市价却是实时的，两个价不同日。只给数字不给日期，用户会觉得乱
                 （2026-11-17：「30 年国债 ETF 收益率是今天的，为啥数据展示还是 16 号」） -->
            <div><span>最新净值</span><b class="num">{{ money(h.nav_px, 4) }}</b><i class="qd num" v-if="navDay">{{ navDay }}</i></div>
            <div v-if="h.otc"><span>占账户</span><b class="num">{{ h.w_now }}%</b></div>
            <div v-else><span>场内市价</span><b class="num">{{ h.spot ? money(h.px, 3) : '—' }}</b><i class="qd num" v-if="h.quote_at">{{ h.quote_at }}</i></div>
          </div>
        </div>

        <!-- 与 Python 版持仓详情同源：子页签切「净值走势 / 累计盈亏」，两张图都是完整 iframe 组件，
             不是 ECharts 简版折线：三层柱面板、有界视窗拖动缩放、逐笔成交 tooltip 都在图内 -->
        <div class="card chart-card">
          <div class="mode-seg" role="group" aria-label="看这只基金的">
            <button v-for="m in modes" :key="m" type="button" :class="{ on: sub === m }"
                    :aria-pressed="sub === m" @click="sub = m">{{ m }}</button>
          </div>
          <div class="frame-box" :style="{ height: frameH + 'px' }">
            <iframe ref="frame" :src="chartSrc" class="chart-frame" frameborder="0" scrolling="no"
                    :title="`${h ? h.name : ''} ${sub}`" @load="onFrameLoad" />
            <div v-if="frameLoading" class="frame-mask">正在加载走势…</div>
          </div>
          <div class="chart-note">
            <b v-if="d?.nav_stale" class="stale-warn">净值只到 {{ (d.nav_last || '').replace(/-/g, '/') }}，后面的还没更新 —— 正在后台补，稍后刷新就有。</b>
            {{ note }}
          </div>
        </div>

        <!-- 每日明细：把收益日历里这只基金的每一格摊开。用户要「对照验证计算」，
             所以价格（净值 + 市价）、份额、收益、收益率、费用一字排开 —— 手算
             `份额 ×（今日价 − 昨日价）− 费用` 能直接对上，不用再去点收益日历。
             场内按市价、场外按净值（后端 px_kind 已标明），周/月/年按区间汇总。
             **和上面那张图无关，三个页签下都显示** —— 场内基金默认停在「市价走势」，
             只挂在「净值走势」下的话，30 年国债这类根本看不到（2026-11-17 用户：
             「每日盈亏所有基金都有吗，我怎么看的30年国债没有呢」）。 -->
        <div class="card day-card" v-if="daily.length">
          <div class="ch">
            <div class="st">{{ dpTitle }}</div>
            <div class="nav" v-if="dp === 'day'">
              <van-icon name="arrow-left" @click="calStep(-1)" :class="{ dis: !canCalStep(-1) }" />
              <b class="num">{{ calY }}年{{ calM }}月</b>
              <van-icon name="arrow" @click="calStep(1)" :class="{ dis: !canCalStep(1) }" />
            </div>
            <span class="seg2" role="group" aria-label="时间粒度">
              <button v-for="p in PERIODS" :key="p.k" :class="{ on: dp === p.k }"
                      :aria-pressed="dp === p.k" @click="setPeriod(p.k)">{{ p.t }}</button>
            </span>
          </div>
          <!-- 日：一个月一屏的日历，可左右翻月。逐日台账是只增不减的，平铺列表跑一年就是
               250 行；日历永远只有 5~6 行格子，翻月的成本是一下点击。点某天在下面看那天的
               明细（净值/市价/份额/收益/费用），核对用的字段一个不少。 -->
          <template v-if="dp === 'day'">
            <div class="wk"><span v-for="w in WEEK" :key="w">{{ w }}</span></div>
            <div class="grid7">
              <div v-for="(c, k) in calCells" :key="k" class="cell"
                   :class="[calCls(c), { empty: !c, sel: c && c.date === selDate }]"
                   @click="c && c.r && (selDate = c.date)">
                <template v-if="c"><span class="dd">{{ c.d }}</span><span class="dv num">{{ c.p == null ? '' : pct(c.p) }}</span></template>
              </div>
            </div>
            <div class="sel-day" v-if="selRow">
              <div class="l1">
                <span class="sd num">{{ selRow.label }}</span>
                <span v-if="selRow.act" class="mark">{{ selRow.act }}</span>
                <b class="num" :class="tone(selRow.pnl)">{{ selRow.state || signed(selRow.pnl) }}</b>
                <b class="num" :class="tone(selRow.pct)">{{ selRow.state ? '' : pct(selRow.pct) }}</b>
              </div>
              <div class="l2">
                <span>净值 <b class="num">{{ selRow.nav == null ? '—' : selRow.nav.toFixed(4) }}</b></span>
                <span>市价 <b class="num">{{ selRow.px == null ? '—' : selRow.px.toFixed(3) }}</b></span>
                <span>份额 <b class="num">{{ qty(selRow.shares, h.unit) }}</b></span>
                <span>费用 <b class="num">{{ selRow.fee ? money(selRow.fee) : '—' }}</b></span>
              </div>
            </div>
            <div class="cal-note" v-else>点日历里的某一天看当天明细</div>
          </template>
          <!-- 周 / 月 / 年：期数少，仍是表格式，一次 12 期、不够再往回翻 -->
          <table v-else class="day-list">
            <thead><tr>
              <th>期间</th>
              <th class="c-nv">净值</th>
              <th class="c-px">市价</th>
              <th class="c-sh">份额</th>
              <th>收益</th>
              <th>收益率</th>
              <th class="c-fee">费用</th>
            </tr></thead>
            <tbody>
              <tr v-for="r in dailyShown" :key="r.date">
                <td class="d">{{ r.label }}<span v-if="r.act" class="mark">{{ r.act }}</span></td>
                <td class="c-nv">{{ r.nav == null ? '—' : r.nav.toFixed(4) }}</td>
                <td class="c-px">{{ r.px == null ? '—' : r.px.toFixed(3) }}</td>
                <td class="c-sh">{{ qty(r.shares, h.unit) }}</td>
                <td :class="tone(r.pnl)">{{ r.state || signed(r.pnl) }}</td>
                <td :class="tone(r.pct)">{{ r.state ? '—' : pct(r.pct) }}</td>
                <td class="c-fee fee">{{ r.fee ? money(r.fee) : '—' }}</td>
              </tr>
            </tbody>
          </table>
          <div class="foot">
            <span class="fee-sum">累计费用 <b class="num">{{ money(feeTotal) }}</b><template v-if="feeKindText">（{{ feeKindText }}）</template></span>
            <button v-if="dp !== 'day' && daily.length > dailyShown.length" ref="moreRef"
                    type="button" class="more-btn" @click="morePeriod">
              看更早的 {{ Math.min(LIMIT, daily.length - dailyShown.length) }} 期
            </button>
          </div>
        </div>

        <div class="sec-t"><span>它的成交 · {{ d.trades.length }} 笔</span></div>
        <van-cell-group inset>
          <van-cell v-for="t in d.trades" :key="t.i">
            <template #title>
              <span class="tag" :class="t.side === '买入' ? 'buy' : 'sell'">{{ t.side }}</span>
              <span class="td num">{{ t.date.replace(/-/g, '/') }}</span>
            </template>
            <template #label><span class="num">{{ money(t.shares, h.otc ? 2 : 0) }} {{ h.unit }} × {{ money(t.nav, 4) }}</span></template>
            <template #value><b class="num" :class="t.side === '买入' ? 'up' : 'down'">¥{{ money(t.amount) }}</b></template>
          </van-cell>
          <van-empty v-if="!d.trades.length" image-size="60" description="还没有成交" />
        </van-cell-group>
        <div class="act">
          <van-button round block type="primary" icon="plus"
                      :to="{ path: `/a/${aid}/record`, query: { code } }">记一笔这只基金</van-button>
        </div>
      </template>
    </div>
  </div>
</template>
<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showFailToast } from 'vant'
import { get, peek } from '../api'
import { money, signed, pct, tone, qty } from '../fmt'
import PremiumTag from '../components/PremiumTag.vue'

const route = useRoute(), router = useRouter()
const aid = route.params.aid, code = route.params.code
const url = `/api/acct/${aid}/holding/${code}`
const d = ref(peek(url) || null)
get(url).then(x => { d.value = x }).catch(e => showFailToast(e.message))
const h = computed(() => d.value?.holding)
const back = () => (window.history.state?.back ? router.back() : router.replace(`/a/${aid}`))

// 市值 / 收益 / 收益率都是后端算好的：场内按市价、场外按净值（Portfolio.px_now），
// 前端不再自己算一遍 —— 两处各算一份，迟早会对不上。
// 这里只用 q 拿折溢价徽标（那是「现价 vs 净值」的关系，后端不返回）。
const q = ref(null)
get(`/api/market/premium?codes=${code}`)
  .then(r => { q.value = (r.rows || [])[0] || null })
  .catch(() => { /* 拿不到行情就不显示徽标，数字不受影响 */ })
// 今日盈亏由后端从收益日历里取（市值变化 − 当日净流入），当天建仓的也有数，
// 前端不再需要「今天刚买入 → 显示 —」那套特殊处理
// 每日明细：收益日历里这只基金每一期的原始数据，按日期正序（和图同方向）。
// 价格给两个：净值（场外按它算收益）和市价（场内按它算）—— 用户核对时要拿市价×份额。
// 周/月/年由后端按 `period` 聚合：收益、费用求和，收益率用期初投入的钱重算。
const PERIODS = [{ k: 'day', t: '日' }, { k: 'week', t: '周' }, { k: 'month', t: '月' }, { k: 'year', t: '年' }]
const dp = ref('day')
// 标题跟着粒度走：「每日收益」切到月要变「每月收益」，否则一眼看不出表里是什么周期
const dpTitle = computed(() => ({ day: '每日收益', week: '每周收益', month: '每月收益', year: '每年收益' }[dp.value]))
const daily = ref([])
const feeTotal = ref(0)
const feeKind = ref({})
// 周/月/年一次给多少期（日视图是日历，用不到这个窗口）
const LIMIT = 12
const pages = ref(1)
const dailyShown = computed(() => daily.value.slice(-LIMIT * pages.value))
const moreRef = ref(null)

// ---- 日视图：一个月一屏的日历 ----
// 逐日台账只增不减，平铺列表跑一年 250 行；日历永远只有 5~6 行格子。
// 格子的收益率直接用后端给的 pct（市值变化 − 净流入 算出来的），**不是**净值比值——
// 账户口径要扣掉买入卖出，用净值相除会把建仓当天的成本算成收益。
const WEEK = ['一', '二', '三', '四', '五', '六', '日']
const pad2 = n => String(n).padStart(2, '0')
const dayMap = computed(() => Object.fromEntries(daily.value.map(r => [r.date, r])))
/** 有数据的月份（升序），翻月的边界靠它判断：没持仓的月份不给翻，免得翻到一片空白 */
const calMonths = computed(() => [...new Set(daily.value.map(r => String(r.date).slice(0, 7)))].sort())
const lastCal = computed(() => calMonths.value[calMonths.value.length - 1] || '')
const calY = ref(+String(lastCal.value).slice(0, 4) || new Date().getFullYear())
const calM = ref(+String(lastCal.value).slice(5, 7) || new Date().getMonth() + 1)
const selDate = ref('')
const calCells = computed(() => {
  const y = calY.value, m = calM.value
  const n = new Date(y, m, 0).getDate()
  const lead = (new Date(y, m - 1, 1).getDay() + 6) % 7    // 周一开头
  const cells = Array(lead).fill(null)
  const by = dayMap.value
  for (let k = 1; k <= n; k++) {
    const date = `${y}-${pad2(m)}-${pad2(k)}`
    const r = by[date]
    cells.push({ d: k, date, r, p: r && !r.state ? r.pct : null })
  }
  return cells
})
// 没数据的日子（周末 / 还没持有）不铺底色，只有真实涨跌才上色，免得一整屏灰块
const calCls = c => !c ? '' : c.p == null ? 'nodata' : c.p > 0 ? 'pos' : c.p < 0 ? 'neg' : 'flat'
const selRow = computed(() => (selDate.value ? dayMap.value[selDate.value] : null))
function shiftMonth(k) {
  const t = new Date(calY.value, calM.value - 1 + k, 1)
  return `${t.getFullYear()}-${pad2(t.getMonth() + 1)}`
}
const canCalStep = k => calMonths.value.includes(shiftMonth(k))
function calStep(k) {
  if (!canCalStep(k)) return
  const t = new Date(calY.value, calM.value - 1 + k, 1)
  calY.value = t.getFullYear()
  calM.value = t.getMonth() + 1
  pickDefaultDay()          // 翻到哪个月就选那个月最后一条记录，下面的明细跟着走
}
/** 切到这个月时默认选中当月最后一条有数据的记录（通常就是今天），下面直接给明细 */
function pickDefaultDay() {
  const pre = `${calY.value}-${pad2(calM.value)}`
  const inMonth = daily.value.filter(r => String(r.date).startsWith(pre))
  selDate.value = inMonth.length ? inMonth[inMonth.length - 1].date : ''
}

const feeKindText = computed(() =>
  Object.entries(feeKind.value).map(([k, v]) => `${k} ${money(v)}`).join(' · '))

function loadDaily() {
  get(`/api/acct/${aid}/holding/${encodeURIComponent(code)}/daily?period=${dp.value}`)
    .then(r => {
      daily.value = r.rows || []
      feeTotal.value = r.fee_total || 0
      feeKind.value = r.fee_kind || {}
      pages.value = 1
      // 日历停在最后一条数据所在的月份
      const last = daily.value[daily.value.length - 1]
      if (last) {
        calY.value = +String(last.date).slice(0, 4)
        calM.value = +String(last.date).slice(5, 7)
      }
      pickDefaultDay()
    })
    .catch(() => { /* 明细拿不到不影响其它内容 */ })
}
loadDaily()
function setPeriod(k) {
  if (dp.value === k) return
  dp.value = k
  loadDaily()
}
/** 周/月/年「看更早」：新行插在上方，同样要按按钮的 rect.top 还原，否则视线会跳。 */
function morePeriod() {
  const el = moreRef.value
  const y = el ? el.getBoundingClientRect().top : 0
  pages.value++
  nextTick(() => {
    const dy = el ? el.getBoundingClientRect().top - y : 0
    if (dy) window.scrollBy(0, dy)
  })
}

const showDay = computed(() => h.value?.day)
const showDayPct = computed(() => h.value?.day_pct)
// 净值日（11/16）—— 「最新净值」那格底下的日期。行情时间是后端给的 quote_at，
// 就是这份估值算价时用的那一份行情的时间，不是「现在几点」。
const navDay = computed(() => {
  const s = d.value?.nav_last || ''
  return s ? s.replace(/-/g, '/').slice(5) : ''
})

// 场内 ETF 多一个「市价走势」并默认打开（能变现的是市价，用户对着 App 看的就是这条）；
// 场外申购赎回都按净值成交，没有第二个价，has_price 为假时这个页签直接不出现。
// 「累计盈亏」一直在：没卖出过时数值和「持有收益」相同，但它画的是**这条曲线怎么走过来的**，
// 不是重复一个数。2026-11-17 我按「没卖出就藏起来」处理过一版，用户当场问「怎么累计收入
// 都没了」—— 用户问「这个是干啥的」是要解释，不是要删。
const modes = computed(() => (d.value?.has_price
  ? ['市价走势', '净值走势', '累计盈亏'] : ['净值走势', '累计盈亏']))
const sub = ref('净值走势')
watch(() => d.value?.has_price, v => { sub.value = v ? '市价走势' : '净值走势' }, { immediate: true })
const viewOf = m => (m === '累计盈亏' ? 'pnl' : m === '市价走势' ? 'price' : 'trade')
const chartSrc = computed(() =>
  `/api/acct/${aid}/holding/${encodeURIComponent(code)}/chart?view=${viewOf(sub.value)}`)

const frame = ref(null), frameLoading = ref(true), frameH = ref(700)
const onFrameLoad = () => {
  const el = frame.value
  if (!el || el.getAttribute('src') !== chartSrc.value) return   // 快速切换时忽略旧 iframe 的 load
  frameLoading.value = false
}
// iframe 内 ResizeObserver 上报 #wrap 的真实内容底部：直接采用，可增可减。
// 旧逻辑用 Math.max 只扩不缩，从「净值走势」切到内容更少的「累计盈亏」时会留下多余空白。
const onMsg = e => {
  if (!frame.value || e.source !== frame.value.contentWindow) return
  const v = Number(e.data?.__awFrameHeight)
  if (v >= 200) frameH.value = Math.ceil(v) + 8   // 过滤 DOM 未铺开时的瞬时过小值
}
onMounted(() => window.addEventListener('message', onMsg))
onBeforeUnmount(() => window.removeEventListener('message', onMsg))
watch(sub, () => {
  frameH.value = sub.value === '累计盈亏' ? 620 : 700
  frameLoading.value = true
})
// 每张图一句「这是什么」，不写操作提示（拖动/缩放图内自带）。原来累计盈亏那句
// 有 100 多字，用户 2026-11-17 说「加这么多备注依然很难理解」，压到一句。
const note = computed(() => sub.value === '累计盈亏'
  ? '这只基金一共赚了多少：手上浮盈 + 已经卖掉落袋的（都扣了手续费）。没卖过时和「持有收益」是同一个数，卖出后曲线不会掉下来。'
  : sub.value === '市价走势'
  ? '场内收盘价，和券商 App 是同一条线；和「净值走势」的差就是折溢价，上面卡片的市值和收益率都按这条算。'
  : '单位净值，场外申赎成交用的就是这个数。悬停在买卖点上能看份额和成交净值。')
</script>
<style scoped>
/* 顶栏标题与其它二级页（SubBar）同字号同字重 */
.subbar :deep(.van-nav-bar__title){ font-size:17px; font-weight:650; color:var(--ink); }
/* 主标题 + 编号/类型徽标同排：名称可换行，徽标不缩，窄屏徽标整体落到第二行 */
.hrow{ display:flex; align-items:baseline; gap:7px; flex-wrap:wrap; }
.fname{ font-size:17px; font-weight:650; line-height:1.35; margin:0; letter-spacing:-.2px; color:var(--ink); min-width:0; }
.code{ flex:none; font-size:11.5px; font-weight:600; line-height:18px; padding:0 7px; border-radius:6px;
  color:var(--brand); background:var(--brand-soft); letter-spacing:.3px; }
.kind{ flex:none; font-size:11.5px; font-weight:500; line-height:18px; padding:0 7px; border-radius:6px;
  color:#475569; background:#F1F3F6; }
/* 次要事实排一行：分类 / 目标 / 本轮动作。一律用等距小胶囊，不再靠「·」串起来 */
.meta{ display:flex; align-items:center; gap:6px; flex-wrap:wrap; margin-top:9px; }
.chipx{ font-size:11.5px; line-height:18px; padding:0 7px; border-radius:6px; color:var(--sub); background:#F6F7F9; white-space:nowrap; }
.head .mv{ font-size:28px; font-weight:700; margin:12px 0 12px; letter-spacing:-.5px; }
/* 指标栅格：4 等分列 + 每格居中（与首页资产卡同一套，见 CLAUDE.md「KPI 行对齐」） */
.g{ display:grid; grid-template-columns:repeat(4,1fr); column-gap:10px; row-gap:12px;
  border-top:1px solid var(--line); padding-top:12px; }
.g > div{ min-width:0; text-align:center; }
@media (max-width:420px){ .g span{ font-size:11px; } .g b{ font-size:13.5px; } }
.g span{ display:block; font-size:12px; color:var(--muted); }
.g b{ display:block; font-size:14px; font-weight:600; margin-top:3px; }
/* 「待更新」是状态不是数字：不上涨跌色，压成次要灰，避免被当成 +0.00 的收益 */
.g b.pend{ color:var(--muted); font-weight:500; }
/* 净值日 / 行情时间：格子底下一行更小的灰字，把「两个价不同日」写清楚 */
.g .qd{ display:block; margin-top:1px; font-size:10.5px; font-style:normal; line-height:1.3;
  color:var(--muted); opacity:.9; letter-spacing:-.2px; white-space:nowrap; }
/* 折溢价徽标跟在市值大数字后面：28px 字配 11px 胶囊，靠 vertical-align 对上基线 */
.mvpq{ margin-left:8px; vertical-align:7px; }
/* 当天买入这类一句话说明：小而轻，别把卡片写成说明书 */
/* 电脑端卡片 936 宽，若照手机顺序竖排，右半边整片留白 → 标题块和市值左右分列，
   指标栅格仍横跨整行；手机不参与（900 以下沿用上面的纵向顺序） */
@media (min-width:900px){
  .head{ display:grid; grid-template-columns:1fr auto; column-gap:32px; align-items:start; }
  .hrow{ grid-column:1; grid-row:1; }
  .meta{ grid-column:1; grid-row:2; }
  .head .mv{ grid-column:2; grid-row:1 / span 2; align-self:center; margin:0; font-size:32px; text-align:right; }
  .g{ grid-column:1 / -1; grid-row:3; margin-top:16px; }
}
.chart-card{ padding-bottom:6px; }
/* 每日明细：日期左对齐、数字右对齐，每行压薄 —— 几十行要能一眼扫完。
   7 列只在宽屏全开；手机收起「净值 / 份额」（那是核对用的辅助列，收益和市价才是主数），
   剩下 5 列在 375px 下放得下。日期严格写 2026/11/16，不简写。 */
.day-card{ padding-bottom:8px; }
/* 这一行现在有「标题 + 月份翻页 + 日/月/年」三段：标题不许被压缩换行，翻页和分段靠 auto 外距推到右边 */
.day-card .ch{ display:flex; align-items:center; gap:8px; margin-bottom:10px; }
.day-card .ch .st{ flex:none; white-space:nowrap; font-size:14px; font-weight:600; color:var(--ink); }
.day-list{ width:100%; border-collapse:collapse; font-size:12.5px; }
.day-list th{ padding:0 0 6px; font-size:11px; font-weight:500; color:var(--muted); text-align:right; white-space:nowrap; }
.day-list th:first-child{ text-align:left; }
.day-list td{ padding:6px 0; border-bottom:1px solid var(--line); text-align:right;
  font-weight:600; font-variant-numeric:tabular-nums; white-space:nowrap; }
.day-list td.d{ text-align:left; font-weight:400; color:var(--muted); }
.day-list tr:last-child td{ border-bottom:none; }
.day-list .mark{ margin-left:5px; padding:0 4px; border-radius:4px; font-size:10px; font-weight:500;
  color:var(--brand); background:var(--brand-soft); }
.day-list td.fee{ color:var(--muted); font-weight:400; }
/* 日视图日历：与「市场 · 基金详情」的收益日历同一套视觉（周一起头的 7 列网格）。
   这一行有三段：标题 / 月份翻页 / 日周月年。翻页靠 margin-left:auto 顶到右边，
   但两个 auto 会平分剩余空间（月份跑到标题旁边、按钮单飞），所以「有 nav 时的 seg2」
   必须写在后面并改成固定间距。 */
.day-card .ch .nav{ display:flex; align-items:center; gap:2px; margin-left:auto; font-size:12.5px; }
.day-card .ch .seg2{ margin-left:auto; }
.day-card .ch .nav + .seg2{ margin-left:8px; }
.day-card .ch .nav b{ font-weight:600; color:var(--ink); white-space:nowrap; text-align:center; }
.day-card .ch .nav :deep(.van-icon){ cursor:pointer; padding:4px; color:var(--muted); font-size:13px; }
.day-card .ch .nav :deep(.dis){ opacity:.25; cursor:default; }
.wk{ display:grid; grid-template-columns:repeat(7,1fr); margin:0 0 4px; font-size:11px; color:var(--muted); text-align:center; }
.grid7{ display:grid; grid-template-columns:repeat(7,1fr); gap:6px; }
/* 没数据的日子（周末 / 还没到 / 未持有）不铺底色，只有真实涨跌才上色，免得一整屏灰块 */
.cell{ display:flex; flex-direction:column; align-items:center; justify-content:center; gap:3px;
  min-height:46px; border-radius:9px; background:transparent; cursor:default; }
.cell.empty{ background:transparent; cursor:default; }
.cell.pos{ background:#FDECEC; cursor:pointer; } .cell.neg{ background:#E7F6EC; cursor:pointer; }
.cell.flat{ background:#F4F6F9; cursor:pointer; }
.cell.pos .dv{ color:var(--up); } .cell.neg .dv{ color:var(--down); }
.cell.nodata .dd{ color:#B6BFCC; }
.cell.sel{ box-shadow:inset 0 0 0 1.5px var(--brand); }
.dd{ font-size:11.5px; color:var(--sub); } .dv{ font-size:11.5px; font-weight:600; }
/* 选中那天的明细：一行日期+收益+收益率，一行核对用的净值/市价/份额/费用 */
.sel-day{ margin-top:10px; padding:9px 11px; border-radius:12px; background:#F7F8FA; }
.sel-day .l1{ display:flex; align-items:baseline; gap:8px; font-size:12.5px; }
.sel-day .l1 .sd{ color:var(--muted); }
.sel-day .l1 b{ margin-left:auto; font-weight:600; }
.sel-day .l1 b + b{ margin-left:8px; }
.sel-day .mark{ padding:0 4px; border-radius:4px; font-size:10px; font-weight:500;
  color:var(--brand); background:var(--brand-soft); }
.sel-day .l2{ display:flex; flex-wrap:wrap; gap:4px 14px; margin-top:6px; font-size:11.5px; color:var(--muted); }
.sel-day .l2 b{ color:var(--ink); font-weight:600; font-variant-numeric:tabular-nums; }
.cal-note{ margin-top:10px; font-size:11.5px; color:var(--muted); }
.day-card .foot{ display:flex; align-items:center; justify-content:space-between; gap:10px;
  margin:10px 0 2px; font-size:11.5px; color:var(--muted); }
.day-card .fee-sum b{ color:var(--ink); font-weight:600; }
.day-card .more-btn{ border:0; background:none; padding:4px 0; font-size:12px; color:var(--brand); cursor:pointer; }
@media (max-width: 700px){
  /* 7 列的表在手机容易被内容撑宽（实测过：某一行 colspan 的 max-content 会被整串算进
     第一列，表格撑到 411px 而卡片只有 366px → 整页横向溢出 49px）。周/月/年这张表
     改用 fixed，忽略内容宽度、按表头百分比分。 */
  .day-list{ table-layout:fixed; }
  .day-list .c-nv, .day-list .c-sh, .day-list .c-fee{ display:none; }
  /* 4 个可见列必须写满 100%：fixed 布局下没写宽度的列会和「已被 display:none 的列」
     平分剩余空间，实测收益/收益率只剩 32px，数字直接压在一起。 */
  .day-list th:first-child{ width:34%; }
  .day-list .c-px{ width:18%; }
  .day-list th:nth-child(5), .day-list th:nth-child(6){ width:24%; }
  .day-list .mark{ display:block; margin:1px 0 0; padding:0 3px; width:fit-content; }
  /* 日历格子在小屏更窄：日期 + 收益率两行还要塞得进 44px 高 */
  .cell{ min-height:44px; border-radius:8px; }
  .grid7{ gap:4px; }
  .dd, .dv{ font-size:11px; }
  /* 标题 + 月份 + 日周月年 一行放不下 390：按钮和月份各收一圈内边距，别让「月」被挤到下一行 */
  .day-card .ch .seg2 button{ padding:4px 9px; font-size:12px; }
  .day-card .ch .nav b{ font-size:11.5px; }
  .day-card .ch .nav :deep(.van-icon){ padding:2px; }
}
/* 视觉定义在 style.css 的 .mode-seg（与 .seg2 同一套），这里只管外边距 */
.mode-seg{ margin:2px 0 4px; }
.frame-box{ position:relative; width:100%; margin:6px 0 0; transition:height .15s ease; }
.chart-frame{ display:block; width:100%; height:100%; border:0; background:#fff; }
.frame-mask{ position:absolute; inset:0; display:flex; align-items:center; justify-content:center;
  background:#fff; color:var(--muted); font-size:13px; }
.chart-note{ margin:8px 0 4px; font-size:11.5px; line-height:1.65; color:var(--muted); }
/* 净值断档是「数据没到」，不是走平 —— 这句要能被看见，别混进说明小字里 */
.stale-warn{ display:block; font-weight:650; color:#B45309; }
.td{ margin-left:8px; font-size:14px; }
.act{ margin:18px 16px 0; }
</style>
