<template>
  <div class="page">
    <van-pull-refresh v-model="refreshing" @refresh="load(true)" success-text="已更新">
      <div class="wrap">
        <div class="ptitle"><b>调仓</b><span class="tag gray m-only" v-if="d">跟随 {{ d.account.strategy_name }}</span></div>
        <van-skeleton v-if="!d" title :row="8" style="padding:16px" />
        <div v-else class="calc-page">
          <div class="verdict" :class="d.status.kind">
            <van-icon :name="d.status.kind === 'orders' ? 'bell' : d.status.kind === 'stuck' ? 'warning-o' : 'passed'" class="vi" />
            <div>
              <div class="vt">{{ title }}</div>
              <div class="vs" v-if="d.status.kind === 'orders'">
                卖出 <b class="num down">¥{{ money(d.sell, 0) }}</b>　买入 <b class="num up">¥{{ money(d.buy, 0) }}</b>
              </div>
              <div class="vs" v-else>{{ d.status.kind === 'stuck' ? '有位置偏离超过 0.5%，但缺口不够一手，先不动' : '每个位置都在目标 ±0.5% 以内，不折腾省手续费' }}</div>
            </div>
          </div>
          <div class="calc-sub">
            <span class="hint" v-if="d.orders.length">先卖后买；按支付宝里实际成交的金额，每做完一笔点「记一笔」</span>
            <router-link class="dca-link" :to="`/a/${aid}/dca`">有新钱怎么分 <van-icon name="arrow" /></router-link>
          </div>

          <template v-if="d.orders.length">
            <div class="sec-t"><span>要下的单 · {{ d.orders.length }} 笔</span>
              <span class="seg2"><button v-for="f in ['全部', '卖出', '买入']" :key="f" :class="{ on: filt === f }" @click="filt = f">{{ f }}</button></span>
            </div>
            <div class="orders-grid">
              <div v-for="o in shown" :key="o.code + o.side" class="ocard">
                <div class="o1">
                  <span class="tag" :class="o.side === '买入' ? 'buy' : 'sell'">{{ o.side }}</span>
                  <span v-if="o.liq" class="tag liq">清仓</span>
                  <b class="on" @click="$router.push(`/a/${aid}/fund/${o.code}`)">{{ o.name }}</b>
                  <span class="oa num" :class="o.side === '买入' ? 'up' : 'down'">¥{{ money(o.amount, 0) }}</span>
                </div>
                <div class="o2">
                  <span>{{ o.code }} · {{ o.otc ? '场外' : '场内' }} · {{ o.slot }}</span>
                  <!-- 溢价率只对场内成立：场外按净值申购，买不到「贵」也买不到「便宜」。
                       卖出单给了信息但不报警 —— 溢价卖出去是多卖钱 -->
                  <PremiumTag v-if="!o.otc" :q="o.quote" :calm="o.side !== '买入'" />
                </div>
                <!-- 记一笔原来单独占一行且靠右，左边整片空白（用户 2026-11-08「下面太空了」）：
                     现在并到「股数 × 价格 / 占比」这一行右侧，卡片少一行、不留空档。
                     图标统一用 plus，和交易流水页、基金详情页的「记一笔」一致（原来这里是 edit）。 -->
                <div class="o3">
                  <span class="num">≈ {{ money(o.qty, o.otc ? 2 : 0) }} {{ o.unit }} × {{ money(o.px, 4) }}</span>
                  <span class="num">占比 {{ o.w_now.toFixed(2) }}% → {{ o.w_tgt == null ? '—' : o.w_tgt.toFixed(2) + '%' }}</span>
                  <van-button class="ogo" size="small" round plain type="primary" icon="plus"
                              :to="{ path: `/a/${aid}/record`, query: { code: o.code, side: o.side, amount: Math.round(o.amount * 100) / 100 } }">记一笔</van-button>
                </div>
                <div class="note" v-if="o.note">{{ o.note }}</div>
                <div class="note prem" v-if="premWarn(o)">{{ premWarn(o) }}</div>
                <!-- 上面的「≈ 股数 × 价格」是按净值算的，场内实际按现价成交；
                     溢价/折价超过 2% 时两者差得明显，得说清差在哪 -->
                <div class="note calcn" v-else-if="pxNote(o)">{{ pxNote(o) }}</div>
              </div>
            </div>
          </template>

          <van-collapse v-model="basis" class="basis">
            <van-collapse-item name="s" title="各位置 · 现在 → 目标（判断依据）">
              <div class="card slots">
                <div v-for="s in d.slots" :key="s.slot" class="srow">
                  <div class="sl">{{ s.slot }}</div>
                  <div class="bar"><i class="now" :style="{ width: bw(s.now) }"></i><em :style="{ left: bw(s.tgt) }"></em></div>
                  <div class="sv num">{{ s.now.toFixed(1) }} → {{ s.tgt.toFixed(1) }}%</div>
                  <div class="sd num" :class="Math.abs(s.dev) >= 0.5 ? (s.dev > 0 ? 'over' : 'under') : ''">{{ signed(s.dev, 1) }}</div>
                </div>
                <div class="legend"><span><i class="now"></i>现在</span><span><em></em>目标</span>偏离 ≥ 0.5pp 才下单</div>
              </div>
            </van-collapse-item>
            <van-collapse-item v-if="d.hold.length" name="h" :title="`不用动 · ${d.hold.length} 只`">
              <van-cell-group>
                <van-cell v-for="h in d.hold" :key="h.code + h.slot" is-link :to="`/a/${aid}/fund/${h.code}`">
                  <template #title><div class="hn">{{ h.name }}</div><div class="hs">{{ h.slot }}<template v-if="h.note"> · {{ h.note }}</template></div></template>
                  <template #value><div class="num hv">¥{{ money(h.mv, 0) }}</div><div class="num hs">{{ h.w_now.toFixed(2) }}%</div></template>
                </van-cell>
              </van-cell-group>
            </van-collapse-item>
          </van-collapse>

          <template v-if="d.other.length">
            <div class="sec-t"><span>不在选基配置里的持仓</span></div>
            <van-cell-group inset>
              <van-cell v-for="o in d.other" :key="o.code" :title="o.name" :label="o.code" :value="`¥${money(o.mv, 0)}`" />
            </van-cell-group>
            <p class="hint">这些不参与调仓计算；想纳入就去「选基配置」把它挂到某个位置</p>
          </template>
        </div>
      </div>
    </van-pull-refresh>
    <TabBar :aid="aid" active="calc" />
  </div>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { get, peek, dataVer } from '../api'
import { money, signed } from '../fmt'
import PremiumTag from '../components/PremiumTag.vue'
import TabBar from '../components/TabBar.vue'

const route = useRoute()
const aid = route.params.aid
const url = `/api/acct/${aid}/calc`
const d = ref(peek(url) || null)
const refreshing = ref(false)
const filt = ref('全部')
const basis = ref([])   // 依据 / 不用动 默认收起
async function load(fresh = false) { try { d.value = await get(url, { fresh }) } finally { refreshing.value = false } }
load(); watch(dataVer, () => load(true))
const title = computed(() => {
  const s = d.value.status
  return s.kind === 'orders' ? `该动手了 · ${s.n} 笔${s.liq ? `（含 ${s.liq} 笔清仓）` : ''}` : s.kind === 'stuck' ? '偏离超标，但这一轮买不进' : '这一轮不用动'
})
const shown = computed(() => {
  const o = [...d.value.orders].sort((a, b) => (a.side === b.side ? b.amount - a.amount : a.side === '卖出' ? -1 : 1))
  return filt.value === '全部' ? o : o.filter(x => x.side === filt.value)
})
const maxW = computed(() => Math.max(10, ...d.value.slots.flatMap(s => [s.now, s.tgt])) * 1.08)
const bw = v => `${Math.min(100, (v / maxW.value) * 100)}%`
// 溢价只在「买入 + 明显偏高」时多说一句。卖出去是按现价成交，溢价高反而占便宜，不提醒。
function premWarn(o) {
  const q = o.quote
  if (!q || !q.ok || o.side !== '买入') return ''
  const p = (q.premium * 100).toFixed(1)
  if (q.level === 'block') return `溢价 ${p}% 已经很高：按高于净值 ${p}% 的价格买，多付的这部分要等溢价回落才拿得回来`
  if (q.level === 'high') return `溢价 ${p}% 偏高，能等就等回落到 2% 以内，或换跟踪同一指数的场外那只`
  return ''
}
// 「≈ 股数 × 价格」里的价格是净值；场内实际按现价成交，偏 2% 以上就该说明差多少
function pxNote(o) {
  const q = o.quote
  if (!q || !q.ok || Math.abs(q.premium) < 0.02) return ''
  const p = (Math.abs(q.premium) * 100).toFixed(1)
  return o.side === '买入'
    ? `上面按净值 ${q.nav} 估的股数偏多：实际按现价 ${q.price} 成交，买得到的少约 ${p}%`
    : `实际按现价 ${q.price} 成交，到手比上面按净值 ${q.nav} 算的多约 ${p}%`
}
</script>
<style scoped>
.ptitle b{ font-size:24px; font-weight:700; color:var(--ink); letter-spacing:-.3px; line-height:1.25; }
.ptitle{ display:flex; align-items:center; gap:8px; padding:calc(26px + env(safe-area-inset-top)) 16px 14px; font-size:20px; }
/* 桌面改为纵向单主列：结论 → 执行清单 → 依据（默认收起），限宽居中建立主次 */
.calc-page{ max-width:960px; margin:0 auto; }
.calc-page .sec-t{ margin:18px 12px 8px; }
.calc-page .verdict{ margin:12px 12px 0; }
.calc-sub{ display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap;
  margin:8px 14px 0; }
.calc-sub .hint{ margin:0; display:block; }
.dca-link{ color:var(--brand); font-size:13px; display:inline-flex; align-items:center; gap:3px;
  text-decoration:none; white-space:nowrap; margin-left:auto; }
.orders-grid{ display:grid; grid-template-columns:1fr; gap:10px; padding:0 12px; }
.orders-grid .ocard{ margin:0; }
.basis{ margin:18px 12px 0; border-radius:12px; overflow:hidden; }
.basis :deep(.van-collapse-item__title){ font-size:13px; color:var(--sub); }
.basis :deep(.van-collapse-item__content){ padding:4px 0 8px; }
.basis .card{ margin:0 8px; }
@media (min-width:900px){
  .orders-grid{ grid-template-columns:1fr 1fr; gap:12px; }
  .calc-page .verdict{ padding:20px 24px; }
  .calc-page .verdict .vt{ font-size:19px; }
}
.verdict{ display:flex; gap:12px; align-items:center; margin:12px 12px 0; padding:16px; border-radius:16px; background:#fff; }
.verdict.orders{ background:linear-gradient(135deg,#1E3A8A,#1E40AF 60%,#3B82F6); color:#fff; }
.verdict.orders .up{ color:#FCA5A5 } .verdict.orders .down{ color:#86EFAC }
.verdict.stuck{ background:#FFFBEB; }
.vi{ font-size:28px; } .verdict.calm .vi{ color:var(--down); } .verdict.stuck .vi{ color:#B45309; }
.vt{ font-size:17px; font-weight:650; } .vs{ font-size:13px; margin-top:4px; opacity:.9; } .vs b{ font-size:15px; }
.hint{ font-size:12px; color:var(--muted); margin:8px 18px 0; line-height:1.6; }
.mt{ margin-top:12px !important; }
.slots{ padding:12px 14px; }
.srow{ display:grid; grid-template-columns:100px 1fr 92px 38px; gap:8px; align-items:center; padding:6px 0; font-size:12.5px; }
@media (max-width:420px){
  .srow{ grid-template-columns:1fr auto 38px; grid-template-areas:"l v d" "b b b"; row-gap:5px; padding:7px 0; }
  .srow .sl{ grid-area:l; } .srow .sv{ grid-area:v; } .srow .sd{ grid-area:d; } .srow .bar{ grid-area:b; }
}
.sl{ color:var(--sub); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.bar{ position:relative; height:8px; background:#F1F2F4; border-radius:4px; }
.bar .now{ position:absolute; left:0; top:0; bottom:0; background:#93C5FD; border-radius:4px; }
.bar em, .legend em{ position:absolute; top:-3px; width:2px; height:14px; background:var(--brand); border-radius:1px; }
.sv{ color:var(--sub); text-align:right; } .sd{ text-align:right; color:var(--muted); }
.sd.over{ color:var(--down); font-weight:600; } .sd.under{ color:var(--up); font-weight:600; }
.legend{ display:flex; gap:14px; font-size:11px; color:var(--muted); margin-top:8px; align-items:center; }
.legend span{ display:flex; align-items:center; gap:4px; position:relative; }
.legend i.now{ width:14px; height:8px; background:#93C5FD; border-radius:3px; display:inline-block; }
.legend em{ position:relative; top:0; height:10px; display:inline-block; }
.ocard{ background:#fff; border-radius:14px; margin:0 12px 10px; padding:12px 14px; }
.o1{ display:flex; align-items:center; gap:6px; }
.on{ flex:1; min-width:0; font-size:15px; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; cursor:pointer; }
.oa{ font-size:17px; font-weight:700; }
.tag.liq{ color:#fff; background:#16A34A; }
.o2{ font-size:12px; color:var(--muted); margin-top:4px; display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
.o3{ display:flex; align-items:center; font-size:12.5px; color:var(--sub);
  margin-top:6px; gap:6px 12px; flex-wrap:wrap; }
/* 占比推到右边、紧挨「记一笔」，右边缘和上面的金额对齐；股数那半段占剩下的宽度 */
.o3 .num:nth-child(2){ margin-left:auto; }
.ogo{ flex:0 0 auto; min-width:82px; }
.note{ font-size:12px; color:#B45309; margin-top:4px; }
.note.calcn{ color:var(--muted); }
.hn{ font-size:14.5px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.hs{ font-size:12px; color:var(--muted); margin-top:2px; }
.hv{ color:var(--ink); font-weight:600; }
@media (min-width:900px){ .ptitle{ padding-top:16px; } }
</style>
