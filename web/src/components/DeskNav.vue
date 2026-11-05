<template>
  <!-- 电脑：顶部导航（品牌 · 当前账户 · 四个页签 · 更新数据）；二级页面也在，跟着所属页签高亮 -->
  <header class="topnav">
    <!-- 第一行：身份 + 全局工具；第二行：主导航。两组分开，不再全挤在一行 -->
    <div class="in first">
      <router-link to="/" class="brand"><img src="/icon.svg" alt="" />全天候再平衡</router-link>
      <div class="tools">
        <UpdateBtn class="u" label />
        <router-link to="/" class="acct" v-if="acct" title="切换账户">
          {{ acct.name }}<span v-if="acct.kind === '模拟'" class="tag sim">模拟</span>
          <van-icon name="exchange" />
        </router-link>
      </div>
    </div>
    <nav class="in second">
      <router-link v-for="t in tabs" :key="t.k" :to="t.to" :class="{ on: active === t.k }">
        <van-icon :name="t.icon" />{{ t.label }}
      </router-link>
    </nav>
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
.topnav{ position:fixed; top:0; left:0; right:0; z-index:50; background:rgba(255,255,255,.94);
  backdrop-filter:saturate(1.6) blur(10px); border-bottom:1px solid var(--line); }
.in{ max-width:1080px; margin:0 auto; padding:0 16px; box-sizing:border-box; }
.first{ height:50px; display:flex; align-items:center; }
.brand{ display:flex; align-items:center; gap:8px; font-weight:700; font-size:16px; color:var(--ink); text-decoration:none; }
.brand img{ width:26px; height:26px; }
.tools{ margin-left:auto; display:flex; align-items:center; gap:14px; }
.acct{ display:flex; align-items:center; gap:6px; font-size:13px; color:var(--sub); text-decoration:none;
  padding-left:14px; border-left:1px solid var(--line); }
.acct:hover{ color:var(--brand); }
.acct .van-icon{ color:var(--muted); font-size:12px; }
.second{ height:42px; display:flex; align-items:stretch; justify-content:center; gap:4px;
  border-top:1px solid var(--line); max-width:960px; }
.second a{ display:flex; align-items:center; justify-content:center; gap:6px; min-width:116px;
  padding:0 14px; font-size:14px; color:var(--sub); text-decoration:none; border-bottom:2px solid transparent; }
.second a:hover{ color:var(--brand); }
.second a.on{ color:var(--brand); border-bottom-color:var(--brand); font-weight:600; }
</style>
