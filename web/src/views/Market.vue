<template>
  <div class="page">
    <div class="wrap">
      <div class="ptitle"><b>市场</b><span class="sub">所有账户共用</span><UpdateBtn class="m-only upd" /></div>
      <div class="grid">
        <router-link v-for="c in cards" :key="c.k" :to="`/a/${aid}/market/${c.k}`" class="mc"
                     :style="{ '--mk-bg': c.bg }">
          <i><van-icon :name="c.icon" /></i>
          <div class="mt"><b>{{ c.t }}</b><span>
            <em v-if="c.k === 'signals' && sig" class="st num">{{ sig.rows.filter(r => r.on).length }}/{{ sig.rows.length }} 生效</em>
            <em v-else-if="c.k === 'valuation' && val && val.rows.length" class="st num">{{ val.rows.filter(r => r.lv === '低估').length }} 个低估</em>
            {{ c.d }}</span></div>
          <van-icon name="arrow" class="go" />
        </router-link>
      </div>
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
const aid = useRoute().params.aid
const sig = ref(peek('/api/market/signals') || null), val = ref(peek('/api/market/valuation') || null)
const load = async (fresh = false) => {
  get('/api/market/signals', { fresh }).then(x => { sig.value = x })
  get('/api/market/valuation', { fresh }).then(x => { val.value = x })
}
load(); onActivated(() => load()); watch(dataVer, () => load(true))
// 四个入口各一种颜色，避开红绿（那是涨跌的语义色）；顺序和 Streamlit 版一致
const cards = [
  { k: 'funds', icon: 'search', t: '基金检索', d: '搜任意基金，看走势、回撤、和别的基金对比', bg: '#EEF2FF' },
  { k: 'signals', icon: 'filter-o', t: '策略信号', d: '三个策略这一轮触发了哪些趋势过滤', bg: '#FEF3C7' },
  { k: 'backtest', icon: 'chart-trending-o', t: '策略回测', d: '三个策略的历史回测、调仓节奏对比、自定义策略', bg: '#F3E8FF' },
  { k: 'valuation', icon: 'bar-chart-o', t: '指数估值', d: '指数 PE / PB 分位，贵不贵', bg: '#CFFAFE' },
]
</script>
<style scoped>
.ptitle{ display:flex; align-items:baseline; gap:8px; padding:calc(14px + env(safe-area-inset-top)) 16px 2px; font-size:20px; }
.ptitle .sub{ font-size:12px; color:var(--muted); }
.upd{ margin-left:auto; align-self:center; }
.grid{ display:grid; gap:10px; padding:12px 12px 0; grid-template-columns:minmax(0,1fr); }
.mc{ display:flex; align-items:center; gap:10px; background:#fff; border-radius:14px; padding:12px 14px;
  text-decoration:none; color:var(--ink); border-left:1px solid var(--line); min-width:0; }
.mc:active{ transform:scale(.99); }
.mc i{ width:38px; height:38px; border-radius:11px; display:grid; place-items:center; font-size:20px;
  flex:0 0 auto; background:var(--mk-bg); color:var(--sub); }
/* 名称 + 说明同一行；说明占剩余宽度，放不下就省略，不再另起一行 */
.mt{ flex:1; min-width:0; display:flex; align-items:baseline; gap:8px; }
.mt b{ flex:0 0 auto; font-size:15px; color:var(--ink); white-space:nowrap; }
.mt span{ flex:1 1 auto; min-width:0; font-size:12px; color:var(--muted);
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
/* 实时状态并入描述行，放在最前面；四张卡右端统一为箭头 */
.mt em.st{ color:var(--brand); font-style:normal; font-weight:600; margin-right:6px; }
.mv{ font-size:12px; color:var(--sub); white-space:nowrap; flex:0 0 auto; } .mv b{ font-size:16px; color:var(--brand); }
.go{ color:#CBD5E1; font-size:14px; flex:0 0 auto; }
@media (min-width:900px){ .grid{ grid-template-columns:repeat(2,minmax(0,1fr)); } .ptitle{ padding-top:16px; } }
</style>
