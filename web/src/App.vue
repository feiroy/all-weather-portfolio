<template>
  <router-view v-slot="{ Component, route }">
    <div class="view-stack">
      <transition :name="route.meta.transition === 'none' ? '' : route.meta.transition">
        <keep-alive :include="['Home', 'Accounts']">
          <component :is="Component" :key="route.name === 'fund' || route.name === 'record' ? route.fullPath : route.name + (route.params.aid || '')" />
        </keep-alive>
      </transition>
    </div>
  </router-view>
</template>
