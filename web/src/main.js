import { createApp } from 'vue'
import Vant from 'vant'
import 'vant/lib/index.css'
import './style.css'
import App from './App.vue'
import router from './router'

createApp(App).use(router).use(Vant).mount('#app')

// 触控板两指左右滑 = 平移曲线，不能让浏览器把它当成「返回上一页」。
// style.css 里已给 html/body 加了 overscroll-behavior-x:none，这里再兜一道：
// 页面本身没有横向滚动区，横向为主的 wheel 一律 preventDefault（图表自己的 capture 监听
// 仍会收到事件并平移时间轴，preventDefault 不影响传播）。
// 用户在策略回测页左右拖动热力图时整页被退回上一页（2026-11-09 报障）。
// 例外：指针落在真正能横向滚动的容器里（区间药丸条 .chips、最近看过、阶段涨幅表）时放行。
function canScrollX(el) {
  for (let e = el; e && e !== document.body; e = e.parentElement) {
    const cs = getComputedStyle(e)
    if ((cs.overflowX === 'auto' || cs.overflowX === 'scroll') && e.scrollWidth > e.clientWidth + 1) return true
  }
  return false
}
window.addEventListener('wheel', e => {
  if (e.ctrlKey || e.metaKey) return                      // Ctrl/⌘ = 缩放，交给图表
  if (Math.abs(e.deltaX) <= Math.abs(e.deltaY) || Math.abs(e.deltaX) < 1) return
  if (canScrollX(e.target)) return
  e.preventDefault()
}, { passive: false, capture: true })
