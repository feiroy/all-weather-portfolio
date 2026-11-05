<template>
  <div class="page no-tab">
    <SubBar title="持仓体检" :fallback="`/a/${aid}`" />
    <div class="wrap narrow">
      <van-skeleton v-if="!d" title :row="8" style="padding:16px" />
      <van-empty v-else-if="!d.items.length" description="还没有持仓，买进以后再来体检" />
      <template v-else>
        <div class="score" :class="d.bad.length ? 'warn' : 'ok'">
          <van-icon :name="d.bad.length ? 'warning-o' : 'passed'" class="si" />
          <div><div class="st">{{ d.bad.length ? `${d.bad.length} 项需要留意` : '各项都正常' }}</div>
            <div class="ss">共 {{ d.items.length }} 项 · 按 {{ d.days }} 个交易日的账户数据</div></div>
        </div>
        <div v-for="it in sorted" :key="it.label" class="card item" :class="{ bad: it.bad }">
          <div class="i1"><b>{{ it.label }}</b><span class="tag" :class="it.bad ? 'warnt' : 'okt'">{{ it.over }}</span></div>
          <div class="i2"><span>现在 <b class="num">{{ it.now }}</b></span><span>警戒线 <b class="num">{{ it.line }}</b></span></div>
          <div class="i3">{{ it.why }}</div>
        </div>
      </template>
    </div>
  </div>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { get, peek, dataVer } from '../api'
import SubBar from '../components/SubBar.vue'
const aid = useRoute().params.aid
const url = `/api/acct/${aid}/health`
const d = ref(peek(url) || null)
const load = async (fresh = false) => { d.value = await get(url, { fresh }) }
load(); watch(dataVer, () => load(true))
const sorted = computed(() => [...d.value.items].sort((a, b) => b.bad - a.bad))
</script>
<style scoped>
.narrow{ max-width:640px !important; }
.score{ display:flex; gap:12px; align-items:center; margin:12px 12px 0; padding:16px; border-radius:16px; }
.score.ok{ background:#E8F7EE; } .score.warn{ background:#FFFBEB; }
.si{ font-size:30px; } .ok .si{ color:var(--down); } .warn .si{ color:#B45309; }
.st{ font-size:17px; font-weight:650; } .ss{ font-size:12.5px; color:var(--sub); margin-top:3px; }
.item.bad{ box-shadow:inset 3px 0 0 #F59E0B; }
.i1{ display:flex; justify-content:space-between; align-items:center; font-size:15px; }
.tag.warnt{ color:#B45309; background:#FEF3C7; } .tag.okt{ color:var(--down); background:#E8F7EE; }
.i2{ display:flex; gap:18px; font-size:12.5px; color:var(--muted); margin-top:8px; flex-wrap:wrap; }
.i2 b{ color:var(--ink); font-weight:600; }
.i3{ font-size:12.5px; color:var(--sub); margin-top:6px; line-height:1.6; }
</style>
