// 接口 + 内存缓存：同一个地址先立刻给上次的结果（页面秒开），后台再取新的
const cache = new Map()
let onLogin = null
export const setLoginHandler = fn => { onLogin = fn }

async function req(url, opt = {}) {
  const r = await fetch(url, { credentials: 'same-origin', ...opt })
  const d = await r.json().catch(() => ({ error: `HTTP ${r.status}` }))
  if (r.status === 401 && d.login && onLogin) onLogin()
  if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`)
  return d
}

export async function get(url, { fresh = false } = {}) {
  if (!fresh && cache.has(url)) {
    refresh(url).catch(() => {})
    return cache.get(url)
  }
  return refresh(url)
}

async function refresh(url) {
  const d = await req(url)
  cache.set(url, d)
  return d
}

export function peek(url) { return cache.get(url) }

// 写了账，账户相关的缓存全部作废（市场类公共数据不动）
function dropAcct() {
  for (const k of [...cache.keys()]) if (k.includes('/api/acct/') || k === '/api/accounts') cache.delete(k)
}
export function dropAll() { cache.clear() }

const body = (method, b) => ({ method, headers: { 'Content-Type': 'application/json' }, body: b == null ? undefined : JSON.stringify(b) })
export async function post(url, b) { const d = await req(url, body('POST', b)); dropAcct(); return d }
export async function put(url, b) { const d = await req(url, body('PUT', b)); dropAcct(); return d }
export async function patch(url, b) { const d = await req(url, body('PATCH', b)); dropAcct(); return d }
export async function del(url) { const d = await req(url, { method: 'DELETE' }); dropAcct(); return d }

// 数据版本：点了「更新数据」并完成后 +1，各页面 watch 它重新取数
import { ref } from 'vue'
export const dataVer = ref(0)
