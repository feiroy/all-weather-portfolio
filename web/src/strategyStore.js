// 自定义策略存在浏览器本地（不进账户文件，避免多端 git 冲突）。
// 回测页与设计页共用这一处读写，格式：[{id, name, freq, funds:[{key,code,name,from,src,weight}]}]
const KEY = 'aw-strategies'

export function loadStrategies() {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || '[]')
    return Array.isArray(v) ? v : []
  } catch { return [] }
}

export function saveStrategies(list) {
  localStorage.setItem(KEY, JSON.stringify(list))
  return list
}
