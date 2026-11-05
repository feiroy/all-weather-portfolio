<template>
  <DeskNav v-if="route.params.aid" class="d-only" :aid="route.params.aid" :active="route.meta.tab" />
  <router-view v-slot="{ Component, route: r }">
    <div class="view-stack" :class="{ 'has-desk': !!r.params.aid }">
      <transition :name="r.meta.transition === 'none' ? '' : r.meta.transition">
        <keep-alive :include="['Home', 'Accounts', 'Trades', 'Market']">
          <component :is="Component" :key="r.meta.keep ? r.name + (r.params.aid || '') : r.fullPath" />
        </keep-alive>
      </transition>
    </div>
  </router-view>
</template>
<script setup>
import { useRoute, useRouter } from 'vue-router'
import { setLoginHandler } from './api'
import DeskNav from './components/DeskNav.vue'
const route = useRoute(), router = useRouter()
// 接口说要登录（设了密码、cookie 过期）→ 去登录页，登完回来
setLoginHandler(() => { if (route.name !== 'login') router.replace({ name: 'login', query: { to: route.fullPath } }) })
</script>
