import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'accounts', component: () => import('./views/Accounts.vue'), meta: { depth: 0 } },
  { path: '/a/:aid', name: 'home', component: () => import('./views/Home.vue'), meta: { depth: 1, tab: 'home' } },
  { path: '/a/:aid/fund/:code', name: 'fund', component: () => import('./views/Fund.vue'), meta: { depth: 2 } },
  { path: '/a/:aid/record', name: 'record', component: () => import('./views/Record.vue'), meta: { depth: 3 } },
  { path: '/a/:aid/:tab(calc|trades|market)', name: 'tab', component: () => import('./views/Placeholder.vue'), meta: { depth: 1 } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: (to, from, saved) => saved || { top: 0 },
})

// 页面转场方向：往深处走从右滑入，返回时从左滑回；同级（底部导航之间）淡入淡出
router.afterEach((to, from) => {
  const a = to.meta.depth ?? 0, b = from.meta.depth ?? 0
  to.meta.transition = !from.name ? 'none' : a > b ? 'push' : a < b ? 'pop' : 'fade'
})
export default router
