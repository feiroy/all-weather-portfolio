import { createRouter, createWebHistory } from 'vue-router'

// depth：决定转场方向（往深处右滑入 / 返回左滑回 / 同级淡入）；tab：电脑顶部导航高亮哪个；keep：切走保留页面状态
const v = n => () => import(`./views/${n}.vue`)
const routes = [
  { path: '/', name: 'accounts', component: v('Accounts'), meta: { depth: 0, keep: true } },
  { path: '/login', name: 'login', component: v('Login'), meta: { depth: 0 } },
  { path: '/a/:aid', name: 'home', component: v('Home'), meta: { depth: 1, tab: 'home', keep: true } },
  { path: '/a/:aid/fund/:code', name: 'fund', component: v('Fund'), meta: { depth: 2, tab: 'home' } },
  { path: '/a/:aid/period', name: 'period', component: v('Period'), meta: { depth: 2, tab: 'home' } },
  { path: '/a/:aid/compare', name: 'compare', component: v('Compare'), meta: { depth: 2, tab: 'home' } },
  { path: '/a/:aid/health', name: 'health', component: v('Health'), meta: { depth: 2, tab: 'home' } },
  { path: '/a/:aid/weights', name: 'weights', component: v('Weights'), meta: { depth: 2, tab: 'home' } },
  { path: '/a/:aid/settings', name: 'settings', component: v('Settings'), meta: { depth: 2, tab: 'home' } },
  { path: '/a/:aid/calc', name: 'calc', component: v('Calc'), meta: { depth: 1, tab: 'calc' } },
  { path: '/a/:aid/dca', name: 'dca', component: v('Dca'), meta: { depth: 2, tab: 'calc' } },
  { path: '/a/:aid/trades', name: 'trades', component: v('Trades'), meta: { depth: 1, tab: 'trades', keep: true } },
  { path: '/a/:aid/record', name: 'record', component: v('Record'), meta: { depth: 3, tab: 'trades' } },
  { path: '/a/:aid/market', name: 'market', component: v('Market'), meta: { depth: 1, tab: 'market', keep: true } },
  { path: '/a/:aid/market/signals', name: 'signals', component: v('Signals'), meta: { depth: 2, tab: 'market' } },
  { path: '/a/:aid/market/backtest', name: 'backtest', component: v('Backtest'), meta: { depth: 2, tab: 'market' } },
  { path: '/a/:aid/market/valuation', name: 'valuation', component: v('Valuation'), meta: { depth: 2, tab: 'market' } },
  { path: '/a/:aid/market/funds', name: 'funds', component: v('Funds'), meta: { depth: 2, tab: 'market' } },
  { path: '/a/:aid/market/fund/:code', name: 'mfund', component: v('MarketFund'), meta: { depth: 3, tab: 'market' } },
  { path: '/:p(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: (to, from, saved) => saved || { top: 0 },
})

router.afterEach((to, from) => {
  const a = to.meta.depth ?? 0, b = from.meta.depth ?? 0
  to.meta.transition = !from.name ? 'none' : a > b ? 'push' : a < b ? 'pop' : 'fade'
  // 记住最后进的账户：下次打开首页直接进（只存本机，不写服务器，避免多端 git 冲突）
  if (to.params.aid) localStorage.setItem('aw-last', to.params.aid)
})
export default router
