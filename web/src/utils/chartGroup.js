// 同一页面里共用一条时间轴的几张图要联动：一张拖动/缩放，其余跟着走。
// 图之间是兄弟组件（没有共同父级可以 provide/inject），所以用模块级注册表。
// 注意：这段逻辑不能写在 <script setup> 里 —— 那里声明的变量是「每个组件实例一份」，
// 三张图各拿一个空 Map，永远同步不到一起（2026-11-08 踩过）。
const GROUPS = new Map()
let busy = false

export function joinGroup(group, chart) {
  if (!group || !chart) return
  if (!GROUPS.has(group)) GROUPS.set(group, new Set())
  GROUPS.get(group).add(chart)
}

export function leaveGroup(group, chart) {
  GROUPS.get(group)?.delete(chart)
}

// 把 chart 当前的 dataZoom 窗口同步给同组的其他图。
// busy 挡住回环：对面 dispatchAction 会立刻触发它自己的 dataZoom 事件，不再往外传。
export function syncGroup(group, chart, dz) {
  if (!group || busy || !dz) return
  busy = true
  for (const c of (GROUPS.get(group) || [])) {
    if (c !== chart) c.dispatchAction({ type: 'dataZoom', start: dz.start, end: dz.end })
  }
  busy = false
}
