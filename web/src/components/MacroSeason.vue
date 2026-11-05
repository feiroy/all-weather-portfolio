<template>
  <!-- 资产页头卡下：一行紧凑的宏观季节，点开才展开四象限（数据来自 /api/market/signals） -->
  <div v-if="m" class="mc-bar" @click="show = true">
    <span class="ic" :style="{ color: m.color, background: m.color + '1A' }"><van-icon name="chart-trending-o" /></span>
    <span class="t">宏观季节</span>
    <b :style="{ color: m.color }">{{ m.current }}</b>
    <span class="ax num">{{ m.axis }}</span>
    <span class="a">对应 {{ m.assets }}</span>
    <van-icon name="arrow" class="go" />
  </div>
  <van-popup v-model:show="show" position="bottom" round closeable :style="{ maxHeight: '80vh' }">
    <div class="pop">
      <h4>宏观季节</h4>
      <p class="sub">增长看沪深300 是否站上 120 日均线，通胀看黄金是否站上 75 日均线；这是调仓前的宏观背景。</p>
      <div class="grid">
        <div v-for="q in m.quadrants" :key="q.label" class="q" :class="{ on: q.label === m.current }"
             :style="{ '--q': q.color }">
          <b>{{ q.label }}</b><small>{{ q.sub }}</small><span>{{ q.assets }}</span>
        </div>
      </div>
      <p class="note">当前：<b :style="{ color: m.color }">{{ m.current }}</b>（{{ m.axis }}）。
        具体买卖仍看「调仓」页的清单。</p>
    </div>
  </van-popup>
</template>
<script setup>
import { computed, ref } from 'vue'
import { get, peek } from '../api'
const d = ref(peek('/api/market/signals') || null)
get('/api/market/signals').then(x => { d.value = x })
const m = computed(() => d.value?.macro || null)
const show = ref(false)
</script>
<style scoped>
.mc-bar{ display:flex; align-items:center; gap:9px; margin:10px 12px 0; padding:10px 12px;
  background:#fff; border:1px solid var(--line); border-radius:14px; min-width:0; cursor:pointer; }
.ic{ width:30px; height:30px; border-radius:9px; display:grid; place-items:center; flex:0 0 auto; font-size:17px; }
.t{ font-size:12.5px; color:var(--muted); white-space:nowrap; }
.mc-bar b{ font-size:16px; font-weight:700; white-space:nowrap; }
.ax{ font-size:12px; color:var(--sub); white-space:nowrap; }
.a{ font-size:12px; color:var(--muted); margin-left:auto; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; }
.go{ color:#CBD5E1; flex:0 0 auto; }
.pop{ padding:18px 16px 26px; max-width:520px; margin:0 auto; }
.pop h4{ margin:0 0 4px; font-size:17px; }
.sub{ font-size:12.5px; color:var(--muted); line-height:1.6; margin:0 0 12px; }
.grid{ display:grid; grid-template-columns:1fr 1fr; gap:9px; }
.q{ border:1px solid var(--line); border-radius:11px; padding:11px; display:flex; flex-direction:column; gap:3px; }
.q.on{ border:2px solid var(--q); background:#F8FAFC; }
.q b{ font-size:15px; color:var(--q); } .q small{ font-size:11.5px; color:var(--muted); }
.q span{ font-size:12px; color:var(--sub); }
.note{ font-size:12px; color:var(--sub); line-height:1.7; margin:14px 0 0; }
@media (max-width:420px){
  .mc-bar{ flex-wrap:wrap; }
  .a{ margin-left:0; width:calc(100% - 30px); }
  .go{ position:absolute; right:26px; bottom:14px; }
  .mc-bar{ position:relative; }
  .grid{ grid-template-columns:1fr; }
}
</style>
