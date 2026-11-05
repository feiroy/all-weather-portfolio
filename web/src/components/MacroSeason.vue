<template>
  <!-- 资产页蓝色头卡上方：通栏彩色横幅，一眼看到当前宏观象限 -->
  <div v-if="m" class="season-banner" :style="{ '--sc': m.color, '--sbg': m.color + '12' }">
    <span class="sb-mark"><van-icon name="chart-trending-o" /></span>
    <span class="sb-txt">
      <span class="sb-k">宏观季节</span>
      <b>{{ m.current }}</b>
      <span class="sb-ax num">{{ m.axis }}</span>
      <span class="sb-a">对应 {{ m.assets }}</span>
    </span>
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
.season-banner{ display:flex; align-items:center; gap:14px; padding:10px 16px; margin:12px 12px 0;
  background:var(--sbg); border-left:4px solid var(--sc); border-radius:12px; min-width:0; }
.sb-mark{ width:36px; height:36px; border-radius:10px; background:var(--sc); color:#fff;
  display:grid; place-items:center; flex:0 0 auto; font-size:20px; }
.sb-txt{ display:flex; align-items:baseline; gap:10px; min-width:0; flex:1; flex-wrap:wrap; }
.sb-k{ font-size:12px; color:var(--sub); }
.sb-txt b{ font-size:19px; font-weight:650; color:var(--sc); letter-spacing:-.3px; }
.sb-ax{ font-size:12.5px; color:var(--sub); white-space:nowrap; }
.sb-a{ font-size:12.5px; color:var(--muted); margin-left:auto; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; }
.sb-quad{ display:grid; grid-template-columns:repeat(2,20px); grid-template-rows:repeat(2,20px);
  gap:3px; flex:0 0 auto; }
.sb-quad i{ display:grid; place-items:center; font-size:11px; font-style:normal; border-radius:4px;
  background:#fff; color:#94A3B8; border:1px solid #E2E8F0; }
.sb-quad i.on{ background:var(--qi); border-color:var(--qi); color:#fff; font-weight:600; }
@media (max-width:420px){
  .season-banner{ gap:10px; padding:9px 12px; }
  .sb-a{ margin-left:0; width:100%; }
  .sb-quad{ grid-template-columns:repeat(2,18px); grid-template-rows:repeat(2,18px); }
}
</style>
