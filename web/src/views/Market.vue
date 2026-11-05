<template>
  <div class="page">
    <div class="wrap">
      <div class="ptitle"><b>市场</b><span class="sub">所有账户共用</span><UpdateBtn class="m-only upd" /></div>
      <div class="grid">
        <router-link :to="`/a/${aid}/market/signals`" class="mc">
          <i style="background:#EEF2FF;color:#1E40AF"><van-icon name="filter-o" /></i>
          <div class="mt"><b>策略信号</b><span>趋势过滤现在开了哪几个</span></div>
          <div class="mv" v-if="sig"><b class="num">{{ sig.rows.filter(r => r.on).length }}</b>/{{ sig.rows.length }} 生效</div>
        </router-link>
        <router-link :to="`/a/${aid}/market/backtest`" class="mc">
          <i style="background:#FEF3C7;color:#B45309"><van-icon name="chart-trending-o" /></i>
          <div class="mt"><b>策略回测</b><span>三个策略同起点比，支持周 / 双周 / 我的操作日</span></div>
        </router-link>
        <router-link :to="`/a/${aid}/market/valuation`" class="mc">
          <i style="background:#E8F7EE;color:#16A34A"><van-icon name="bar-chart-o" /></i>
          <div class="mt"><b>指数估值</b><span>PE / PB 历史分位，按低估到高估排</span></div>
          <div class="mv" v-if="val && val.rows.length"><b class="num">{{ val.rows.filter(r => r.lv === '低估').length }}</b> 个低估</div>
        </router-link>
        <router-link :to="`/a/${aid}/market/funds`" class="mc">
          <i style="background:#FDECEC;color:#E23B3B"><van-icon name="search" /></i>
          <div class="mt"><b>基金检索</b><span>按名称或代码查任意一只基金的净值走势</span></div>
        </router-link>
      </div>

      <template v-if="sig">
        <div class="sec-t"><span>三个策略 · 近半年</span><span class="num">截至 {{ sig.asof.replace(/-/g, '/') }}</span></div>
        <div class="card"><MultiLine :series="sig.curves" :height="220" /></div>
      </template>
    </div>
    <TabBar :aid="aid" active="market" />
  </div>
</template>
<script setup>
defineOptions({ name: 'Market' })
import { ref, onActivated, watch } from 'vue'
import { useRoute } from 'vue-router'
import { get, peek, dataVer } from '../api'
import TabBar from '../components/TabBar.vue'
import UpdateBtn from '../components/UpdateBtn.vue'
import MultiLine from '../components/MultiLine.vue'
const aid = useRoute().params.aid
const sig = ref(peek('/api/market/signals') || null), val = ref(peek('/api/market/valuation') || null)
const load = async (fresh = false) => {
  get('/api/market/signals', { fresh }).then(x => { sig.value = x })
  get('/api/market/valuation', { fresh }).then(x => { val.value = x })
}
load(); onActivated(() => load()); watch(dataVer, () => load(true))
</script>
<style scoped>
.ptitle{ display:flex; align-items:baseline; gap:8px; padding:calc(14px + env(safe-area-inset-top)) 16px 2px; font-size:20px; }
.ptitle .sub{ font-size:12px; color:var(--muted); }
.upd{ margin-left:auto; align-self:center; }
.grid{ display:grid; gap:10px; padding:12px 12px 0; grid-template-columns:1fr; }
.mc{ display:flex; align-items:center; gap:12px; background:#fff; border-radius:14px; padding:14px; text-decoration:none; color:var(--ink); }
.mc:active{ transform:scale(.99); }
.mc i{ width:42px; height:42px; border-radius:12px; display:grid; place-items:center; font-size:22px; flex:0 0 auto; }
.mt{ flex:1; min-width:0; } .mt b{ display:block; font-size:15.5px; } .mt span{ display:block; font-size:12px; color:var(--muted); margin-top:3px; }
.mv{ font-size:12px; color:var(--sub); white-space:nowrap; } .mv b{ font-size:17px; color:var(--brand); }
@media (min-width:900px){ .grid{ grid-template-columns:1fr 1fr; } .ptitle{ padding-top:16px; } }
</style>
