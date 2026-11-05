<template>
  <div class="page">
    <div class="wrap">
      <van-nav-bar :title="title" safe-area-inset-top />
      <van-empty image="search" :description="`「${title}」在原型里还没做`">
        <van-button round type="primary" :href="oldUrl" target="_blank">先去旧版看</van-button>
      </van-empty>
      <p class="tip">原型只做了：资产首页、基金详情、记一笔。觉得手感对了再把其余页面搬过来。</p>
    </div>
    <TabBar :aid="aid" :active="route.params.tab" />
  </div>
</template>
<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import TabBar from '../components/TabBar.vue'
const route = useRoute()
const aid = computed(() => route.params.aid)
const title = computed(() => ({ calc: '调仓', trades: '记录', market: '市场' })[route.params.tab])
const oldUrl = computed(() => `${location.protocol}//${location.hostname}:8501/${route.params.tab}?acct=${aid.value}`)
</script>
<style scoped>.tip{ font-size:12px; color:var(--muted); text-align:center; margin:0 24px; }</style>
