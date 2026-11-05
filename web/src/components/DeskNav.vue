<template>
  <!-- 电脑：顶部导航（品牌 · 当前账户 · 四个页签 · 更新数据）；二级页面也在，跟着所属页签高亮 -->
  <header class="topnav">
    <div class="in">
      <router-link to="/" class="brand"><img src="/icon.svg" alt="" />全天候再平衡</router-link>
      <router-link to="/" class="acct" v-if="acct" title="切换账户">
        {{ acct.name }}<span v-if="acct.kind === '模拟'" class="tag sim">模拟</span>
        <van-icon name="exchange" />
      </router-link>
      <nav>
        <router-link v-for="t in tabs" :key="t.k" :to="t.to" :class="{ on: active === t.k }">
          <van-icon :name="t.icon" />{{ t.label }}
        </router-link>
      </nav>
      <UpdateBtn class="u" compact />
    </div>
  </header>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { get, peek, dataVer } from '../api'
import UpdateBtn from './UpdateBtn.vue'
import { tabsOf } from './tabs'
const props = defineProps({ aid: String, active: String })
const tabs = computed(() => tabsOf(props.aid))
const acct = ref(null)
const pick = l => l?.accounts?.find(a => a.id === props.aid) || null
watch(() => [props.aid, dataVer.value], async () => {
  acct.value = pick(peek('/api/accounts')) || acct.value
  try { acct.value = pick(await get('/api/accounts')) } catch { /* 顶栏拿不到账户名不影响页面 */ }
}, { immediate: true })
</script>
<style scoped>
.topnav{ position:fixed; top:0; left:0; right:0; z-index:50; background:rgba(255,255,255,.92);
  backdrop-filter:saturate(1.6) blur(10px); border-bottom:1px solid var(--line); }
.in{ max-width:1080px; margin:0 auto; height:56px; display:flex; align-items:center; gap:18px; padding:0 16px; box-sizing:border-box; }
.brand{ display:flex; align-items:center; gap:8px; font-weight:700; font-size:16px; color:var(--ink); text-decoration:none; }
.brand img{ width:26px; height:26px; }
.acct{ display:flex; align-items:center; gap:6px; font-size:13.5px; color:var(--sub); text-decoration:none;
  padding:4px 10px; border-radius:16px; background:#F3F4F6; }
.acct .van-icon{ color:var(--muted); font-size:12px; }
nav{ display:flex; gap:4px; margin-left:8px; }
nav a{ display:flex; align-items:center; gap:5px; padding:7px 14px; border-radius:10px; font-size:14.5px; color:var(--sub); text-decoration:none; }
nav a:hover{ background:#F3F4F6; }
nav a.on{ color:var(--brand); background:var(--brand-soft); font-weight:600; }
.u{ margin-left:auto; }
</style>
