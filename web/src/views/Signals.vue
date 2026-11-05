<template>
  <div class="page no-tab">
    <SubBar title="策略信号" :fallback="`/a/${aid}/market`" />
    <div class="wrap">
      <van-skeleton v-if="!d" title :row="8" style="padding:16px" />
      <div v-else class="cols2 even">
        <div>
          <div class="card">
            <div class="ct"><b>趋势过滤</b><span class="k num">截至 {{ d.asof.replace(/-/g, '/') }}</span></div>
            <p class="k">价格跌破均线 → 这个资产的目标权重清零，钱按同桶分给别的资产；涨回均线上方再恢复</p>
            <div class="mx">
              <div class="mh"><span></span><span v-for="s in d.strategies" :key="s.key">{{ s.name.replace('V3-B ', '') }}</span></div>
              <div v-for="r in d.rows" :key="r.name" class="mr">
                <div class="mn"><i :class="r.on ? 'on' : 'off'"></i><div><b>{{ r.name }}</b><small>{{ r.desc }} · {{ r.on ? '生效中' : '未触发' }}</small></div></div>
                <span v-for="s in d.strategies" :key="s.key" class="mc">
                  <template v-if="r.applies[s.key]"><van-tag :type="r.on ? 'warning' : 'default'" round>{{ r.on ? '→ 0' : '看着' }}</van-tag></template>
                  <template v-else><em>不用</em></template>
                </span>
              </div>
            </div>
          </div>
        </div>
        <div class="card">
          <div class="ct"><b>三个策略 · 近半年</b><span class="k">回测净值，含趋势过滤</span></div>
          <MultiLine :series="d.curves" :height="260" />
        </div>
      </div>
    </div>
  </div>
</template>
<script setup>
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { get, peek, dataVer } from '../api'
import SubBar from '../components/SubBar.vue'
import MultiLine from '../components/MultiLine.vue'
const aid = useRoute().params.aid
const url = '/api/market/signals'
const d = ref(peek(url) || null)
const load = async (fresh = false) => { d.value = await get(url, { fresh }) }
load(); watch(dataVer, () => load(true))
</script>
<style scoped>
.ct{ display:flex; justify-content:space-between; align-items:baseline; font-size:15px; margin-bottom:6px; }
.k{ font-size:12px; color:var(--muted); line-height:1.6; margin:0; }
.mx{ margin-top:10px; }
.mh, .mr{ display:grid; grid-template-columns:1fr 64px 64px 64px; align-items:center; gap:4px; }
@media (max-width:480px){
  .mh, .mr{ grid-template-columns:repeat(3,1fr); }
  .mh span:first-child{ display:none; }
  .mr .mn{ grid-column:1 / -1; margin-bottom:6px; }
}
.mh{ font-size:11.5px; color:var(--muted); text-align:center; padding-bottom:6px; border-bottom:1px solid var(--line); }
.mr{ padding:10px 0; border-bottom:1px solid var(--line); }
.mr:last-child{ border-bottom:0; }
.mn{ display:flex; gap:8px; align-items:flex-start; min-width:0; }
.mn i{ width:8px; height:8px; border-radius:4px; margin-top:6px; flex:0 0 auto; }
.mn i.on{ background:#F59E0B; } .mn i.off{ background:#CBD5E1; }
.mn b{ display:block; font-size:13.5px; font-weight:550; } .mn small{ font-size:11.5px; color:var(--muted); }
.mc{ text-align:center; } .mc em{ font-style:normal; font-size:11.5px; color:#CBD5E1; }
</style>
