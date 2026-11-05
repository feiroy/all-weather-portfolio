<template>
  <!-- 资产页头卡下方：一行克制小卡，不抢总金额的位置 -->
  <div v-if="m" class="macro-mini">
    <span class="mm-dot" :style="{ background: m.color }"></span>
    <span class="mm-k">宏观季节</span>
    <b :style="{ color: m.color }">{{ m.current }}</b>
    <span class="mm-ax num">{{ m.axis }}</span>
    <span class="mm-a">对应 {{ m.assets }}</span>
    <span class="sb-quad">
      <i v-for="q in m.quadrants" :key="q.label"
         :class="{ on: q.label === m.current }" :style="{ '--qi': q.color }"
         :title="`${q.label} · ${q.sub} · ${q.assets}`">{{ short[q.label] }}</i>
    </span>
  </div>
</template>
<script setup>
import { computed, ref } from 'vue'
import { get, peek } from '../api'
const d = ref(peek('/api/market/signals') || null)
get('/api/market/signals').then(x => { d.value = x })
const m = computed(() => d.value?.macro || null)
const short = { 复苏: '复', 过热: '过', 滞胀: '滞', 衰退: '衰' }
</script>
<style scoped>
.macro-mini{ display:flex; align-items:center; gap:9px; margin:10px 12px 14px; padding:8px 14px;
  background:#fff; border:1px solid var(--line); border-radius:10px; min-width:0; }
.mm-dot{ width:7px; height:7px; border-radius:50%; flex:0 0 auto; }
.mm-k{ font-size:12px; color:var(--muted); white-space:nowrap; }
.macro-mini b{ font-size:14px; font-weight:600; white-space:nowrap; }
.mm-ax{ font-size:12px; color:var(--sub); white-space:nowrap; }
.mm-a{ font-size:12px; color:var(--muted); margin-left:auto; min-width:0; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; }
@media (min-width:900px){ .sb-quad{ margin-left:14px; } }
.sb-quad{ display:grid; grid-template-columns:repeat(2,17px); grid-template-rows:repeat(2,17px);
  gap:2px; flex:0 0 auto; }
.sb-quad i{ display:grid; place-items:center; font-size:10px; font-style:normal; border-radius:3px;
  background:#F8FAFC; color:#94A3B8; border:1px solid #E2E8F0; }
.sb-quad i.on{ background:var(--qi); border-color:var(--qi); color:#fff; font-weight:600; }
@media (max-width:420px){
  .macro-mini{ gap:7px; padding:7px 10px; }
  .mm-a{ display:none; }
  .sb-quad{ margin-left:auto; }
}
</style>
