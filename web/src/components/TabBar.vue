<template>
  <van-tabbar :model-value="active" fixed placeholder safe-area-inset-bottom>
    <van-tabbar-item name="home" icon="balance-o" :to="`/a/${aid}`" replace>资产</van-tabbar-item>
    <van-tabbar-item name="calc" icon="exchange" :to="`/a/${aid}/calc`" replace>调仓</van-tabbar-item>
    <van-tabbar-item name="trades" icon="orders-o" :to="`/a/${aid}/trades`" replace>记录</van-tabbar-item>
    <van-tabbar-item name="market" icon="chart-trending-o" :to="`/a/${aid}/market`" replace>市场</van-tabbar-item>
  </van-tabbar>
</template>
<script setup>
defineProps({ aid: String, active: String })
</script>
