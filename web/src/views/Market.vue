<template>
  <div class="page">
    <div class="wrap">
      <div class="ptitle"><b>市场</b><span class="sub">所有账户共用</span><UpdateBtn class="m-only upd" /></div>
      <div class="grid">
        <router-link v-for="c in cards" :key="c.k" :to="`/a/${aid}/market/${c.k}`" class="mc"
                     :style="{ '--mk': c.mk, '--mk-bg': c.bg }">
          <i><van-icon :name="c.icon" /></i>
          <div class="mt"><b>{{ c.t }}</b><span>{{ c.d }}</span></div>
          <div class="mv" v-if="c.k === 'signals' && sig"><b class="num">{{ sig.rows.filter(r => r.on).length }}</b>/{{ sig.rows.length }} 生效</div>
          <div class="mv" v-else-if="c.k === 'valuation' && val && val.rows.length"><b class="num">{{ val.rows.filter(r => r.lv === '低估').length }}</b> 个低估</div>
          <van-icon name="arrow" class="go" v-else />
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
// 四个入口各一种颜色，避开红绿（那是涨跌的语义色）；顺序和 Streamlit 版一致
const cards = [
  { k: 'funds', icon: 'search', t: '基金检索', d: '搜任意基金，看走势、回撤、和别的基金对比', mk: '#1D4ED8', bg: '#EEF2FF' },
  { k: 'signals', icon: 'filter-o', t: '策略信号', d: '三个策略这一轮触发了哪些趋势过滤', mk: '#B45309', bg: '#FEF3C7' },
  { k: 'backtest', icon: 'chart-trending-o', t: '策略回测', d: '三个策略的历史回测、调仓节奏对比、自定义策略', mk: '#7C3AED', bg: '#F3E8FF' },
  { k: 'valuation', icon: 'bar-chart-o', t: '指数估值', d: '指数 PE / PB 分位，贵不贵', mk: '#0E7490', bg: '#CFFAFE' },
]
</script>
<style scoped>
.ptitle{ display:flex; align-items:baseline; gap:8px; padding:calc(14px + env(safe-area-inset-top)) 16px 2px; font-size:20px; }
.ptitle .sub{ font-size:12px; color:var(--muted); }
.upd{ margin-left:auto; align-self:center; }
.grid{ display:grid; gap:10px; padding:12px 12px 0; grid-template-columns:1fr; }
.mc{ display:flex; align-items:center; gap:10px; background:#fff; border-radius:14px; padding:12px 14px;
  text-decoration:none; color:var(--ink); border-left:3px solid var(--mk); }
.mc:active{ transform:scale(.99); }
.mc i{ width:38px; height:38px; border-radius:11px; display:grid; place-items:center; font-size:20px;
  flex:0 0 auto; background:var(--mk-bg); color:var(--mk); }
/* 名称 + 说明同一行；说明占剩余宽度，放不下就省略，不再另起一行 */
.mt{ flex:1; min-width:0; display:flex; align-items:baseline; gap:8px; }
.mt b{ flex:0 0 auto; font-size:15px; color:var(--mk); white-space:nowrap; }
.mt span{ flex:1 1 auto; min-width:0; font-size:12px; color:var(--mk); opacity:.78;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.mv{ font-size:12px; color:var(--sub); white-space:nowrap; flex:0 0 auto; } .mv b{ font-size:16px; color:var(--mk); }
.go{ color:#CBD5E1; font-size:14px; flex:0 0 auto; }
@media (min-width:900px){ .grid{ grid-template-columns:1fr 1fr; } .ptitle{ padding-top:16px; } }
</style>
