<template>
  <!-- 手机底部导航；电脑上隐藏（顶部导航在 App.vue） -->
  <van-tabbar :model-value="active" fixed placeholder safe-area-inset-bottom class="m-only">
    <van-tabbar-item v-for="t in tabsOf(aid)" :key="t.k" :name="t.k" :icon="t.icon" :to="t.to" replace>{{ t.label }}</van-tabbar-item>
  </van-tabbar>
</template>
<script setup>
import { tabsOf } from './tabs'
defineProps({ aid: String, active: String })
</script>
