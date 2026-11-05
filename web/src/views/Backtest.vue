<template>
  <div class="page no-tab">
    <SubBar title="策略回测" :fallback="`/a/${aid}/market`" />
    <div class="wrap">
      <div class="card ctl">
        <div class="row"><span class="lb">调仓节奏</span>
          <div class="chips"><span v-for="c in cads" :key="c.k" class="chip" :class="{ on: cad === c.k }" @click="cad = c.k">{{ c.t }}</span></div></div>
        <div class="row" v-if="cad !== 'mine'"><span class="lb">起点</span>
          <div class="chips"><span v-for="s in starts" :key="s" class="chip" :class="{ on: start === s }" @click="start = s">{{ s.slice(0, 4) }} 年起</span></div></div>
        <p class="k" v-if="cad === 'mine'">从账户建立那天起，只在你实际有买卖的日子调仓，和「每月末调仓」对照 —— 看你的操作节奏有没有拖后腿</p>
        <p class="k" v-else-if="cad !== 'monthly'">虚线是同策略「每月末调仓」做对照；差值看下表「比月末」</p>
      </div>
      <van-loading v-if="loading" class="ld" vertical>回测计算中…</van-loading>
      <p v-else-if="err" class="empty-tip">{{ err }}</p>
      <div v-else-if="d" class="cols2">
        <div>
          <div v-for="r in d.rows" :key="r.name" class="card rcard" :class="{ base: isBase(r.name) }">
            <div class="r1"><i :style="{ background: colorOf(r.name) }"></i><b>{{ r.name }}</b><span class="k num">调仓 {{ r.n }} 次</span></div>
            <div class="r2">
              <div><span>{{ r.short ? '区间收益' : '年化' }}</span><b class="num" :class="tone(r.short ? r.ret : r.cagr)">{{ pct(r.short ? r.ret : r.cagr) }}</b></div>
              <div><span>最大回撤</span><b class="num down">{{ r.mdd.toFixed(2) }}%</b></div>
              <div><span>{{ r.short ? '波动' : '夏普' }}</span><b class="num">{{ r.short ? r.vol.toFixed(2) + '%' : (r.sharpe ?? '—') }}</b></div>
              <div v-if="r.vs != null"><span>比月末</span><b class="num" :class="tone(r.vs)">{{ signed(r.vs) }}pp</b></div>
            </div>
          </div>
          <p class="k pad" v-if="d.rows.some(r => r.short)">不满一年：只看区间收益和波动，年化和夏普没有意义</p>
        </div>
        <div class="card">
          <div class="ct"><b>累计收益</b><span class="k">{{ cad === 'mine' ? '账户建立起' : start.slice(0, 4) + ' 年起' }}</span></div>
          <MultiLine :series="d.curves" :height="320" :colors="colors" :dashed="Object.keys(d.curves).filter(isBase)" />
        </div>
      </div>
    </div>
  </div>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { get } from '../api'
import { signed, pct, tone } from '../fmt'
import SubBar from '../components/SubBar.vue'
import MultiLine from '../components/MultiLine.vue'
const aid = useRoute().params.aid
const cads = [{ k: 'monthly', t: '每月末' }, { k: 'biweekly', t: '每两周' }, { k: 'weekly', t: '每周' }, { k: 'mine', t: '我的操作日' }]
const starts = ['2015-01-01', '2018-01-01', '2020-01-01', '2023-01-01']
const cad = ref(sessionStorage.getItem('aw-bt-cad') || 'monthly'), start = ref(sessionStorage.getItem('aw-bt-start') || '2015-01-01')
const d = ref(null), loading = ref(false), err = ref('')
watch([cad, start], async () => {
  sessionStorage.setItem('aw-bt-cad', cad.value); sessionStorage.setItem('aw-bt-start', start.value)
  loading.value = true; err.value = ''
  try { d.value = await get(`/api/market/backtest?start=${start.value}&cadence=${cad.value}&acct=${aid}`) }
  catch (e) { err.value = e.message; d.value = null }
  finally { loading.value = false }
}, { immediate: true })
// 同一策略同色：对照组（月末）用虚线
const PAL = { 保守增强: '#1E40AF', 风险平价: '#F59E0B', V3c: '#8B5CF6' }
const colorOf = n => Object.entries(PAL).find(([k]) => n.includes(k))?.[1] || '#64748B'
const isBase = n => cad.value !== 'monthly' && n.endsWith('· 月末')
const colors = computed(() => Object.keys(d.value?.curves || {}).map(colorOf))
</script>
<style scoped>
.ctl .row{ display:flex; align-items:center; gap:8px; margin-bottom:8px; }
.ctl .chips{ padding:0; }
.lb{ font-size:12.5px; color:var(--muted); flex:0 0 56px; }
.k{ font-size:12px; color:var(--muted); line-height:1.6; margin:0; }
.pad{ margin:8px 18px; }
.ld{ margin:40px 0; }
.rcard{ padding:12px 14px; }
.rcard.base{ background:#FAFAFB; }
.r1{ display:flex; align-items:center; gap:8px; font-size:14.5px; }
.r1 i{ width:10px; height:10px; border-radius:5px; } .r1 .k{ margin-left:auto; }
.r2{ display:grid; grid-template-columns:repeat(4,1fr); gap:6px; margin-top:10px; }
.r2 span{ display:block; font-size:11.5px; color:var(--muted); } .r2 b{ display:block; font-size:15px; margin-top:2px; }
.ct{ display:flex; justify-content:space-between; align-items:baseline; font-size:15px; margin-bottom:8px; }
</style>
