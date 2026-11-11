// 自定义策略存在服务端 data/strategies.json —— 跟着 git 多端同步，而且实盘要按它下单，
// 服务端必须读得到（浏览器里的东西服务端看不见）。
// 老的 localStorage（aw-strategies）降级成**一次性迁移来源**：本地有、服务端还没有的自动上传，
// 传成功的从本地删掉，失败的留着下次再试（不能把人家的策略悄悄弄丢）。
// 格式：[{id, name, method, freq, funds:[{key,code,name,weight}], ...}]
import { get, post, del } from './api'

const KEY = 'aw-strategies'
let cache = null
let migrated = false

function readLocal() {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || '[]')
    return Array.isArray(v) ? v : []
  } catch { return [] }
}

// 本地存量 → 服务端。只做一次：之后 localStorage 里只剩「传失败的」。
async function migrate(rows) {
  if (migrated) return rows
  migrated = true
  const local = readLocal()
  if (!local.length) return rows
  const have = new Set(rows.map(r => r.id))
  const left = []
  for (const r of local) {
    if (!r || !r.id) continue
    if (have.has(r.id)) continue                       // 服务端已经有同 id，不重复传
    try {
      rows.push((await post('/api/strategies', r)).strategy)
    } catch {
      left.push(r)                                     // 失败留着，下次打开再试
    }
  }
  try { localStorage.setItem(KEY, JSON.stringify(left)) } catch { /* 隐私模式写不进去就算了 */ }
  return rows
}

// 策略列表。fresh=true 跳过缓存（刚存/刚删之后用）。
export async function loadStrategies(fresh = false) {
  if (cache && !fresh) return cache
  const d = await get('/api/strategies', { fresh: true })
  cache = await migrate(d.rows || [])
  return cache
}

// 新增或覆盖一条。后端返回存下来的那条（已补 id / updated）。
export async function saveStrategy(rec) {
  const r = await post('/api/strategies', rec)
  cache = null
  return r.strategy
}

export async function deleteStrategy(id) {
  await del(`/api/strategies/${id}`)
  cache = null
}

// 别处改了策略（比如账户页绑定时），回来重新读
export function invalidateStrategies() { cache = null }
