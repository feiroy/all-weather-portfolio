<template>
  <div class="page no-tab">
    <div class="wrap">
      <div class="brand"><img src="/icon.svg" alt="" /><span>全天候再平衡</span></div>
      <div class="sec-t"><span>选择账户</span></div>
      <van-skeleton v-if="!list" :row="4" style="padding:16px" />
      <div v-else class="grid">
        <div v-for="a in list" :key="a.id" class="acard" @click="$router.push(`/a/${a.id}`)">
          <div class="row1"><b>{{ a.name }}</b><span class="tag" :class="a.kind === '模拟' ? 'sim' : 'real'">{{ a.kind }}</span>
            <van-icon name="arrow" class="go" /></div>
          <div class="st">跟随 {{ a.strategy_name }} · {{ a.n_trades }} 笔</div>
          <div class="amt num">¥{{ money(a.total) }}</div>
          <div class="pnl num"><span :class="tone(a.pnl)">{{ signed(a.pnl) }}</span>
            <span :class="tone(a.pnl_pct)">{{ pct(a.pnl_pct) }}</span><small>持有收益</small></div>
        </div>
      </div>
      <p class="tip">新建、删除账户暂时在旧版里操作（原型只做了资产 / 基金详情 / 记一笔）</p>
    </div>
  </div>
</template>
<script setup>
defineOptions({ name: 'Accounts' })
import { ref, onActivated } from 'vue'
import { get, peek } from '../api'
import { money, signed, pct, tone } from '../fmt'
const list = ref(peek('/api/accounts')?.accounts || null)
const load = async () => { list.value = (await get('/api/accounts')).accounts }
load(); onActivated(load)
</script>
<style scoped>
.brand{ display:flex; align-items:center; gap:10px; padding:calc(18px + env(safe-area-inset-top)) 18px 4px; font-size:20px; font-weight:700; }
.brand img{ width:34px; height:34px; }
.grid{ display:grid; gap:12px; padding:0 12px; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); }
.acard{ background:#fff; border-radius:16px; padding:16px; }
.acard:active{ transform:scale(.99); }
.row1{ display:flex; align-items:center; gap:8px; font-size:16px; }
.row1 .go{ margin-left:auto; color:var(--muted); }
.st{ font-size:12.5px; color:var(--muted); margin-top:4px; }
.amt{ font-size:26px; font-weight:700; margin-top:12px; letter-spacing:-.5px; }
.pnl{ display:flex; gap:10px; align-items:baseline; font-size:14px; font-weight:600; margin-top:2px; }
.pnl small{ color:var(--muted); font-weight:400; font-size:12px; }
.tip{ font-size:12px; color:var(--muted); text-align:center; margin:24px 16px; }
</style>
