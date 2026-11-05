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
</style>
