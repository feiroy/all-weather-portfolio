<template>
  <div class="page no-tab">
    <SubBar title="和基准比" :fallback="`/a/${aid}`" />
    <div class="wrap">
      <van-skeleton v-if="!d" title :row="8" style="padding:16px" />
      <van-empty v-else-if="!Object.keys(d.curves).length" description="记录还太少，过几天再来比" />
      <div v-else class="cols2">
        <div>
          <div class="card">
            <div class="k">我的账户 · 持有收益率</div>
            <b class="num big" :class="tone(d.mine)">{{ pct(d.mine) }}</b>
            <div class="gaps">
              <div v-for="(v, k) in d.gap" :key="k" class="gap">
                <span>比{{ k }}</span><b class="num" :class="tone(v)">{{ v == null ? '—' : signed(v) + 'pp' }}</b>
                <small>{{ explain[k] }}</small>
              </div>
            </div>
          </div>
        </div>
        <div class="card">
          <div class="ct"><b>区间涨跌</b><span class="k">基准 {{ (axis[baseIdx] || '').replace(/-/g, '/') }} = 0%，按同样的入金节奏折算</span></div>
          <!-- 区间 / 周期与其他曲线同一套控件（用户 2026-11-08：这页原来完全没有时间区间） -->
          <RangeBar :range="range" :period="period" :periods="periods"
                    @update:range="setRange" @update:period="setPeriod" />
          <MultiLine :series="curvesChg" :height="300" :dashed="['默认基金 · 我的操作日', '策略理论']"
                     :window="win" :reset-key="resetKey" group="compare" />
        </div>
          <div class="card read">
            <b>三条线分别在说什么</b>
            <p><i class="dot" style="background:#1E40AF"></i><b>我的账户 · 真实结果</b>：你实际买的基金（不少是场外联接）、实际下单日期、实际费用。</p>
            <p><i class="dot" style="background:#F59E0B"></i><b>默认基金 · 我的操作日</b>：换成项目默认 9 只 ETF，用<b>当期建议权重</b>，但调仓日按你真实的成交日（09/04 建仓、10/26 加仓）。它和「我的账户」的差 = <b>纯选基差异</b>（费率 / 跟踪误差 / T+1 净值）。</p>
            <p><i class="dot" style="background:#8B5CF6"></i><b>策略理论 · 标准执行</b>：同样的基金和权重，调仓日换成<b>每月最后一个交易日</b>，也就是全量回测净值 <code>output/nv_curves.csv</code>。它和上一行的差 = <b>纯下单时点差异</b>。<b>你以后按月末照建议调权，走的就是这条线</b>。</p>
            <div class="chain">
              <span>我的账户</span><em>选基 / 费用 →</em><span>默认基金·我的操作日</span><em>下单时点 →</em><span>策略理论</span>
            </div>
            <p class="note">三条线都用你账户<b>真实的入金节奏</b>折算（同一笔钱、同一天进场）；差别只有三件事：买什么、哪天调仓、费多少。</p>
            <div class="faq">
              <b>三个常见疑问</b>
              <p><b>Q：策略理论用的是哪的基金？</b><br/>就是项目默认那 9 只（<code>510300 / 513500 / 511220 / 511360 / 511260 / 511130 / 518850 / 159980 / 159981 / 512890</code>）。回测输入 <code>load_panel()</code> 里，ETF 上市后是这些基金的真实净值（实测与 <code>data/*.csv</code> 逐点一致）；只有 ETF 上市前的历史段才用指数/沪铜/伦敦金×汇率/WTI×汇率拼接，30 年国债 2024-03 前用 10 年国债 ×3 久期合成，合成段还扣了年化安全扣减。回测从 2013-12 起（红利低波代理起点），那几年 30Y / 有色 / 能化 / 红利低波等还没上市，用的是代理序列 —— 这是回测的近似，不是凭空造数。</p>
              <p><b>Q：如何操作才能对应它？</b><br/>照「调仓」页每月给出的目标权重买这 9 只，在当月最后一个交易日再平衡（<code>python -m allweather.rebalance</code>）。权重必须按月<b>重算</b>，不是固定一套比例——这是这条曲线唯一的执行要求。另外回测不计申赎费 / 管理费 / 滑点，实盘会有损耗。</p>
              <p><b>Q：那回测指标是不是假的？</b><br/>不是。<code>perf_metrics()</code> 直接吃 <code>nv_curves.csv</code> 那条净值，实测用曲线重算的 CAGR / 最大回撤 / Sharpe 与报告数字<b>逐位一致（差值 0）</b>。页面是直接读那条净值，不是拿指标结论反推；只做了两件事：回测截止日后用末期权重延长到最新行情日、再按你的入金节奏折算。报告里的年化是「2015 起一次性满仓」口径，页面是「按实际入金节奏」，数字不能直接对照。</p>
            </div>
            <p class="note" v-if="d.theory && d.theory.backtest_end"><b>口径</b>：全量回测净值只跑到 <b>{{ d.theory.backtest_end }}</b><template v-if="d.theory.tracked">，之后按回测最后一期目标权重固定持有（不再动态调权）跟随行情到 <b>{{ d.theory.asof }}</b>；延长段是固定权重跟踪，不是重跑回测</template>。若不延长，过期段会被当作净值不变，之后新入金的收益全被算成 0，曲线就会贴着 0%。</p>
            <p class="note">运行不满一年，差距在 ±1pp 以内都算正常波动。</p>
          </div>
      </div>
    </div>
  </div>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { get, peek, dataVer } from '../api'
import { signed, pct, tone } from '../fmt'
import SubBar from '../components/SubBar.vue'
import MultiLine from '../components/MultiLine.vue'
import RangeBar from '../components/RangeBar.vue'
import { aggregateSeries, unionDates, windowForRange, rangeStartIndex, rebaseSeries } from '../utils/series'
const aid = useRoute().params.aid
const url = `/api/acct/${aid}/compare`
const d = ref(peek(url) || null)
const load = async (fresh = false) => { d.value = await get(url, { fresh }) }
load(); watch(dataVer, () => load(true))

// 时间区间：全站统一 8 档 + 日/月/年线。账户从建仓日起算，默认看「全部」（建仓以来）。
const periods = ['日线', '月线', '年线']
const range = ref('全部'), period = ref('日线'), bump = ref(0)
const curvesAgg = computed(() => aggregateSeries(d.value?.curves || {}, period.value))
const axis = computed(() => unionDates(curvesAgg.value))
const baseIdx = computed(() => rangeStartIndex(axis.value, range.value))
// 以区间基准日为 0%（默认「全部」时基准就是建仓日，与原来完全一致）
const curvesChg = computed(() => rebaseSeries(curvesAgg.value, axis.value, baseIdx.value))
const win = computed(() => windowForRange(axis.value, range.value))
// 点已选中的同一档也要复位到该区间起点（图可能被拖走）
const resetKey = computed(() => `${range.value}|${period.value}|${bump.value}`)
const setRange = r => { if (range.value === r) bump.value++; else range.value = r }
const setPeriod = p => { if (period.value === p) bump.value++; else period.value = p }
const explain = { '默认基金 · 我的操作日': '纯选基差异（费率 / 跟踪误差）', 策略理论: '选基 + 下单时点合计' }
</script>
<style scoped>
.k{ font-size:12px; color:var(--muted); }
.big{ font-size:28px; font-weight:700; display:block; margin:4px 0 10px; }
.gaps{ display:grid; grid-template-columns:1fr 1fr; gap:10px; border-top:1px solid var(--line); padding-top:12px; }
.gap span{ display:block; font-size:12px; color:var(--muted); } .gap b{ display:block; font-size:17px; margin:3px 0 2px; }
.gap small{ font-size:11px; color:var(--muted); }
.read{ font-size:13px; color:var(--sub); line-height:1.7; }
.read p{ margin:8px 0 0; } .read p b{ color:var(--ink); font-weight:600; }
.read .note{ font-size:12px; color:var(--muted); }
.read code{ font-size:11.5px; padding:1px 5px; background:var(--bg); border:1px solid var(--line); border-radius:4px; color:var(--brand); }
.faq{ margin-top:12px; padding:10px 12px; background:var(--bg); border:1px solid var(--line); border-radius:10px; font-size:12px; line-height:1.65; }
.faq>b{ display:block; margin-bottom:4px; color:var(--ink); }
.read .faq p{ margin:6px 0 0; }
.faq p b{ color:var(--ink); }
.chain{ display:flex; flex-wrap:wrap; align-items:center; gap:6px; margin-top:12px; padding:10px 12px; background:var(--bg); border-radius:10px; font-size:12px; }
.chain span{ padding:3px 8px; background:var(--card); border:1px solid var(--line); border-radius:6px; color:var(--sub); }
.chain em{ font-style:normal; color:var(--muted); }
.dot{ display:inline-block; width:8px; height:8px; border-radius:4px; margin-right:6px; }
.ct{ display:flex; justify-content:space-between; align-items:baseline; margin-bottom:8px; font-size:15px; }
</style>
