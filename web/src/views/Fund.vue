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
            <div><span>今日收益</span><b class="num" :class="tone(showDay)">{{ signed(showDay) }}</b></div>
            <div><span>今日收益率</span><b class="num" :class="tone(showDayPct)">{{ pct(showDayPct) }}</b></div>
            <div><span>持有收益</span><b class="num" :class="tone(h.hold)">{{ signed(h.hold) }}</b></div>
            <div><span>持有收益率</span><b class="num" :class="tone(h.hold_pct)">{{ pct(h.hold_pct) }}</b></div>
            <div><span>{{ h.otc ? '份额' : '股数' }}</span><b class="num">{{ qty(h.shares, h.unit) }}</b></div>
            <div><span>成本价</span><b class="num">{{ money(h.cost, 4) }}</b></div>
            <div><span>最新净值</span><b class="num">{{ money(h.nav_px, 4) }}</b></div>
            <div v-if="h.otc"><span>占账户</span><b class="num">{{ h.w_now }}%</b></div>
            <div v-else><span>场内市价</span><b class="num">{{ h.spot ? money(h.px, 3) : '—' }}</b></div>
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
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
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
const showDay = computed(() => h.value?.day)
const showDayPct = computed(() => h.value?.day_pct)

// 场内 ETF 多一个「市价走势」并默认打开（能变现的是市价，用户对着 App 看的就是这条）；
// 场外申购赎回都按净值成交，没有第二个价，has_price 为假时这个页签直接不出现
const modes = computed(() => d.value?.has_price
  ? ['市价走势', '净值走势', '累计盈亏'] : ['净值走势', '累计盈亏'])
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
const note = computed(() => sub.value === '累计盈亏'
  ? '累计盈亏 = 手上还拿着的浮盈 + 已经卖出落袋的实盈（买入算手续费、卖出扣手续费），所以卖掉之后曲线不会掉下来。上面的「持有收益」只算手上这一部分，两者差多少，就是已经卖掉的那部分赚到（或亏掉）的钱。图内也可切区间，拖动平移、⌘/Ctrl 滚轮缩放、双击复位。'
  : sub.value === '市价走势'
  ? '场内二级市场的收盘价，跟券商 App 的行情是同一条线；和「净值走势」的差就是折溢价。上面卡片的市值和收益率都按这条线算。图内可切区间与日/月/年线，拖动平移、⌘/Ctrl 滚轮缩放、双击复位。'
  : '图内可切区间与日/月/年线，拖动平移、⌘/Ctrl 滚轮缩放、双击复位；悬停或点一下净值线能看到每笔的份额与成交净值。')
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
