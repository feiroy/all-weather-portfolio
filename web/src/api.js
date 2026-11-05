// 接口 + 内存缓存：同一个地址先立刻给上次的结果（页面秒开），后台再取新的
const cache = new Map()

export async function get(url, { fresh = false } = {}) {
  if (!fresh && cache.has(url)) {
    refresh(url)
    return cache.get(url)
  }
  return refresh(url)
}

async function refresh(url) {
  const r = await fetch(url)
  const d = await r.json()
  if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`)
  cache.set(url, d)
  return d
}

export function peek(url) { return cache.get(url) }

export async function post(url, body) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  const d = await r.json()
  if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`)
  // 写了账，账户相关的缓存全部作废
  for (const k of [...cache.keys()]) if (k.includes('/api/acct/') || k === '/api/accounts') cache.delete(k)
  return d
}
