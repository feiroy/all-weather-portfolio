<template>
  <div class="page no-tab">
    <van-nav-bar :title="h ? h.name : '基金详情'" left-arrow @click-left="back" safe-area-inset-top />
    <div class="wrap">
      <van-skeleton v-if="!d" title :row="10" style="padding:16px" />
      <template v-else>
        <div class="card head">
          <div class="sub">{{ h.code }} · {{ h.otc ? '场外 · 按份额' : '场内 · 按股' }} · {{ h.slot }}
            <span v-if="h.side" class="tag" :class="h.side === '买入' ? 'buy' : 'sell'">本轮{{ h.side }} ¥{{ money(h.amount, 0) }}</span></div>
          <div class="sub">占账户 {{ h.w_now }}%{{ h.w_tgt == null ? '' : ` · 目标 ${h.w_tgt.toFixed(1)}%` }}</div>
          <div class="mv num">¥{{ money(h.mv) }}</div>
          <div class="g">
            <div><span>今日收益</span><b class="num" :class="tone(h.day)">{{ signed(h.day) }}</b></div>
            <div><span>持有收益</span><b class="num" :class="tone(h.hold)">{{ signed(h.hold) }}</b></div>
            <div><span>持有收益率</span><b class="num" :class="tone(h.hold_pct)">{{ pct(h.hold_pct) }}</b></div>
            <div><span>{{ h.otc ? '份额' : '股数' }}</span><b class="num">{{ money(h.shares, h.otc ? 2 : 0) }}</b></div>
            <div><span>成本价</span><b class="num">{{ money(h.cost, 4) }}</b></div>
            <div><span>最新净值</span><b class="num">{{ money(h.px, 4) }}</b></div>
          </div>
        </div>

        <div class="card">
          <div class="ct"><b>净值走势</b>
            <span class="rg num" :class="tone(rangeRet)">{{ pct(rangeRet) }}</span></div>
          <van-tabs v-model:active="range" type="card" shrink class="rtabs">
            <van-tab v-for="r in ranges" :key="r.k" :title="r.k" :name="r.k" />
          </van-tabs>
          <div class="chips rr"><span class="seg2"><button v-for="p in periods" :key="p" :class="{ on: period === p }" @click="period = p">{{ p }}</button></span>
            <span class="hint">滑动/拖动平移 · ⌘/Ctrl 缩放 · 双击复位</span></div>
          <LineChart :dates="chart.dates" :values="chart.values" :labels="chart.labels" :height="220" unit="" :marks="segMarks"
                     :reset-key="range + period"
                     :fmt-tip="i => `${chart.dates[i].replace(/-/g, '/')}<br/>净值 <b>${chart.values[i].toFixed(4)}</b>`" />
          <div class="legend"><span><i class="b">B</i>买入</span><span><i class="s">S</i>卖出</span>月/年线的买卖点落在该期最后一条记录</div>
        </div>

        <div class="sec-t"><span>它的成交 · {{ d.trades.length }} 笔</span></div>
        <van-cell-group inset>
          <van-cell v-for="t in d.trades" :key="t.i">
            <template #title>
              <span class="tag" :class="t.side === '买入' ? 'buy' : 'sell'">{{ t.side }}</span>
              <span class="td num">{{ t.date.replace(/-/g, '/') }}</span>
            </template>
            <template #label><span class="num">{{ money(t.shares, h.otc ? 2 : 0) }} {{ h.unit }} × {{ money(t.nav, 4) }}</span></template>
            <template #value><b class="num" :class="t.side === '买入' ? 'up' : 'down'">{{ t.side === '买入' ? '-' : '+' }}¥{{ money(t.amount) }}</b></template>
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
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showFailToast } from 'vant'
import { get, peek } from '../api'
import { money, signed, pct, tone } from '../fmt'
import LineChart from '../components/LineChart.vue'
import { aggregate } from '../utils/series'

const route = useRoute(), router = useRouter()
const aid = route.params.aid, code = route.params.code
const url = `/api/acct/${aid}/holding/${code}`
const d = ref(peek(url) || null)
get(url).then(x => { d.value = x }).catch(e => showFailToast(e.message))
const h = computed(() => d.value?.holding)
const back = () => (window.history.state?.back ? router.back() : router.replace(`/a/${aid}`))

const ranges = [{ k: '近1月', m: 1 }, { k: '近3月', m: 3 }, { k: '近6月', m: 6 }, { k: '近1年', m: 12 }, { k: '近3年', m: 36 }, { k: '全部', m: 0 }]
const range = ref('近6月')
const seg = computed(() => {
  const n = d.value?.nav
  if (!n || !n.dates.length) return { dates: [], values: [] }
  const m = ranges.find(r => r.k === range.value).m
  if (!m) return n
  const end = new Date(n.dates[n.dates.length - 1]); end.setMonth(end.getMonth() - m)
  const s = end.toISOString().slice(0, 10)
  const i = Math.max(0, n.dates.findIndex(x => x >= s))
  return { dates: n.dates.slice(i), values: n.values.slice(i) }
})
const rangeRet = computed(() => { const v = seg.value.values; return v.length > 1 ? (v[v.length - 1] / v[0] - 1) * 100 : null })
const periods = ['日线', '月线', '年线'], period = ref('日线')
const chart = computed(() => aggregate(seg.value.dates, seg.value.values,
  period.value === '日线' ? '日' : period.value === '月线' ? '月' : '年'))
const segMarks = computed(() => {
  const s = chart.value
  if (!d.value || !s.dates.length) return []
  return d.value.trades.filter(t => t.date >= s.dates[0]).map(t => {
    const i = s.dates.findIndex(x => x >= t.date)
    return i < 0 ? null : { date: s.labels[i] || s.dates[i], value: s.values[i], side: t.side }
  }).filter(Boolean)
})
</script>
<style scoped>
.head .sub{ font-size:12.5px; color:var(--muted); display:flex; gap:6px; align-items:center; flex-wrap:wrap; margin-bottom:2px; }
.head .mv{ font-size:28px; font-weight:700; margin:6px 0 12px; letter-spacing:-.5px; }
.g{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px 8px; border-top:1px solid var(--line); padding-top:12px; }
.g span{ display:block; font-size:12px; color:var(--muted); }
.g b{ display:block; font-size:14px; font-weight:600; margin-top:3px; }
.ct{ display:flex; justify-content:space-between; align-items:baseline; font-size:15px; }
.rg{ font-size:14px; font-weight:600; }
.rtabs{ margin:10px -4px 4px; }
.rtabs :deep(.van-tabs__nav--card){ margin:0; border-radius:8px; overflow:hidden; }
.rr{ padding:0 4px 4px; align-items:center; gap:10px; }
.rr .hint{ font-size:11.5px; color:var(--muted); }
.legend{ display:flex; gap:12px; font-size:11.5px; color:var(--muted); margin-top:4px; }
.legend i{ display:inline-block; width:14px; height:14px; border-radius:7px; color:#fff; font-style:normal; font-size:9px; text-align:center; line-height:14px; margin-right:3px; }
.legend i.b{ background:#E23B3B } .legend i.s{ background:#16A34A }
.td{ margin-left:8px; font-size:14px; }
.act{ margin:18px 16px 0; }
</style>
