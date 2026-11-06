// 时间轴的滚轮 / 触摸板交互。
// Mac 触摸板双指滑动产生的是 wheel 事件（横向 deltaX、纵向 deltaY），不是 mousemove，
// ECharts 内置 inside dataZoom 默认只把 wheel 当缩放且忽略 deltaX，导致触摸板无法左右平移。
// 这里统一接管：普通滑动 = 平移（窗口宽度不变），Ctrl/⌘ + 滑动（含捏合）= 缩放。
export function attachWheel(chart, el, enabled = () => true) {
  const onWheel = e => {
    if (!enabled()) return
    const dz = chart.getOption()?.dataZoom?.[0]
    if (!dz) return
    const dx = e.deltaX || 0, dy = e.deltaY || 0
    const d = Math.abs(dx) > Math.abs(dy) ? dx : dy
    if (!d && !(e.ctrlKey || e.metaKey)) return
    e.preventDefault()          // 阻止页面滚动 / macOS 横向返回手势
    let start = dz.start ?? 0, end = dz.end ?? 100
    const span = Math.max(1, end - start)
    if (e.ctrlKey || e.metaKey) {
      // 捏合 / Ctrl+滚轮：以视窗中心缩放
      const factor = d > 0 ? 1.15 : 0.87
      const next = Math.min(100, Math.max(1, span * factor))
      const mid = start + span / 2
      start = Math.max(0, Math.min(100 - next, mid - next / 2))
      end = start + next
    } else if (span >= 99.5) {
      // 默认全区间时平移会被边界钳住（触摸板怎么滑都没反应）：
      // 第一次滑动先把窗口收成固定宽度并按方向靠边，之后就能持续平移同一宽度的窗口
      const next = 72
      start = (100 - next) / 2          // 居中收窄，左右都还有平移空间
      end = start + next
    } else {
      // 平移：横向优先，窗口宽度保持不变（固定区间间隔）
      const shift = (d > 0 ? 1 : -1) * Math.max(1, span * 0.05)
      start = Math.max(0, Math.min(100 - span, start + shift))
      end = start + span
    }
    chart.dispatchAction({ type: 'dataZoom', start, end })
  }
  // 鼠标按住拖动同样受「窗口全开」限制：按下时先收窄成固定窗口，ECharts 的 moveOnMouseMove 才有平移空间
  const onDown = () => {
    if (!enabled()) return
    const dz = chart.getOption()?.dataZoom?.[0]
    if (dz && (dz.end ?? 100) - (dz.start ?? 0) >= 99.5) {
      chart.dispatchAction({ type: 'dataZoom', start: 14, end: 86 })
    }
  }
  // 必须用捕获阶段：zrender 会在冒泡链上截断 wheel，挂在 el 的冒泡监听收不到原生触摸板事件
  el.addEventListener('wheel', onWheel, { passive: false, capture: true })
  el.addEventListener('mousedown', onDown)
  el.addEventListener('touchstart', onDown, { passive: true })
  return () => {
    el.removeEventListener('wheel', onWheel, true)
    el.removeEventListener('mousedown', onDown)
    el.removeEventListener('touchstart', onDown)
  }
}
