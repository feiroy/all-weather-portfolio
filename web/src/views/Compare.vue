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
          <div class="card read">
            <b>怎么看</b>
            <p><i class="dot" style="background:#F59E0B"></i><b>项目默认基金</b>：同样的入金时间和金额，按策略目标权重买项目默认的那几只 ETF。我的账户跑输它 → 多半是<b>选的基金</b>或<b>没及时调仓</b>拖了后腿。</p>
            <p><i class="dot" style="background:#8B5CF6"></i><b>策略理论</b>：回测引擎里这个策略的净值曲线，按同样的入金节奏折算。和它的差距是<b>执行 + 跟踪误差</b>的总和。</p>
            <p>运行不满一年，差距在 ±1pp 以内都算正常波动。</p>
          </div>
        </div>
        <div class="card">
          <div class="ct"><b>收益率走势</b><span class="k">按同样的入金节奏折算</span></div>
          <MultiLine :series="d.curves" :height="300" :colors="['#1E40AF', '#F59E0B', '#8B5CF6']" :dashed="['策略理论']" />
        </div>
      </div>
    </div>
  </div>
</template>
<script setup>
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { get, peek, dataVer } from '../api'
import { signed, pct, tone } from '../fmt'
import SubBar from '../components/SubBar.vue'
import MultiLine from '../components/MultiLine.vue'
const aid = useRoute().params.aid
const url = `/api/acct/${aid}/compare`
const d = ref(peek(url) || null)
const load = async (fresh = false) => { d.value = await get(url, { fresh }) }
load(); watch(dataVer, () => load(true))
const explain = { 项目默认基金: '选基 + 调仓执行的差距', 策略理论: '和回测里的策略比' }
</script>
<style scoped>
.k{ font-size:12px; color:var(--muted); }
.big{ font-size:28px; font-weight:700; display:block; margin:4px 0 10px; }
.gaps{ display:grid; grid-template-columns:1fr 1fr; gap:10px; border-top:1px solid var(--line); padding-top:12px; }
.gap span{ display:block; font-size:12px; color:var(--muted); } .gap b{ display:block; font-size:17px; margin:3px 0 2px; }
.gap small{ font-size:11px; color:var(--muted); }
.read{ font-size:13px; color:var(--sub); line-height:1.7; }
.read p{ margin:8px 0 0; } .read p b{ color:var(--ink); font-weight:600; }
.dot{ display:inline-block; width:8px; height:8px; border-radius:4px; margin-right:6px; }
.ct{ display:flex; justify-content:space-between; align-items:baseline; margin-bottom:8px; font-size:15px; }
</style>
