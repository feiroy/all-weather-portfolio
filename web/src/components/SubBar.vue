<template>
  <van-nav-bar :title="title" left-arrow @click-left="back" safe-area-inset-top class="subbar">
    <template #right><slot name="right" /></template>
  </van-nav-bar>
</template>
<script setup>
// 二级页面的顶栏：有上一页就退回去，直接打开的（刷新 / 分享的链接）就回到 fallback
import { useRouter } from 'vue-router'
const props = defineProps({ title: String, fallback: { type: String, default: '/' } })
const router = useRouter()
const back = () => (window.history.state?.back ? router.back() : router.replace(props.fallback))
</script>
<style scoped>
.subbar{ position:sticky; top:0; z-index:20; }
/* 手机端返回栏别贴屏幕顶；标题放大，和正文拉开层级 */
@media (max-width:899px){
  .subbar{ padding-top:calc(12px + env(safe-area-inset-top)); }
}
.subbar :deep(.van-nav-bar__title){ font-size:17px; font-weight:650; color:var(--ink, #111827); }
</style>
