"""基金搜索框（单选 / 多选），替代内置 selectbox / multiselect。

为什么不用内置控件：全市场名录 2.8 万条，内置控件每次加载页面都要把全部选项发给浏览器
（两个控件合计约 2.2 MB），浏览器解析时主线程卡 1~2 秒（手机上更久），这时点 tab 没反应。

做法：名录写成静态文件 streamlit_app/static/fund_names.json（需 server.enableStaticServing=true），
组件在用户**第一次点开搜索框时**才下载一次，浏览器缓存后两个搜索框共用；页面加载只传当前选中项。
筛选在浏览器里完成（代码/名称包含匹配，最多显示 50 条），选中后才回传 Python。

返回值：单选 → 代码字符串（回测资产为 "bt:hs300" 形式）；多选 → 代码列表。
"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

import fund_lookup as FL

STATIC_DIR = Path(__file__).resolve().parent / "static"
NAMES_JSON = STATIC_DIR / "fund_names.json"


def ensure_static_names() -> None:
    """名录静态文件不存在或比名录缓存旧时重写（刷新名录后自动更新）。"""
    src = FL.NAME_CACHE
    if NAMES_JSON.exists() and (not src.exists() or NAMES_JSON.stat().st_mtime >= src.stat().st_mtime):
        return
    rows = [[c, n] for c, n in FL.name_map().items() if n and not n.endswith("(后端)")]
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    NAMES_JSON.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


_CSS = r"""
:host{display:block}
.fs{position:relative;font:14px/1.5 -apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans SC","Microsoft YaHei",sans-serif;color:#0F172A}
.box{display:flex;flex-wrap:wrap;align-items:center;gap:6px;min-height:44px;padding:5px 36px 5px 12px;box-sizing:border-box;
  border:1px solid #CBD5E1;border-radius:12px;background:#fff;box-shadow:0 1px 2px rgba(15,23,42,.04);cursor:text;
  transition:border-color .15s,box-shadow .15s}
.box:hover{border-color:#94A3B8}
.fs.open .box,.box:focus-within{border-color:#3B82F6;box-shadow:0 0 0 3px rgba(59,130,246,.12)}
.tags{display:contents}   /* 标签直接参与 .box 的换行，输入框紧跟最后一个标签，不会被挤到单独一行 */
.q{flex:1 1 120px;min-width:80px;border:0;outline:0;background:transparent;font:inherit;font-size:14px;color:#0F172A;padding:4px 0}
.q::placeholder{color:#94A3B8}
.fs.multi.has .q:not(:focus){flex:1 1 0;min-width:16px}   /* 已有标签且没在输入时，输入框缩到最小，不单独占一行 */
.fs.single .q:not(:focus){font-weight:500}
.chev{position:absolute;right:12px;top:50%;width:12px;height:12px;margin-top:-6px;pointer-events:none;
  background:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12'%3E%3Cpath d='M3 4.5l3 3 3-3' fill='none' stroke='%2394A3B8' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") no-repeat center}
.tag{display:inline-flex;align-items:center;gap:4px;max-width:100%;background:#DBEAFE;color:#1E3A8A;border-radius:8px;
  padding:2px 4px 2px 8px;font-size:13px;font-weight:500;line-height:1.5}
.tag span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:260px}
.tag button{border:0;background:transparent;color:#1E3A8A;cursor:pointer;width:18px;height:18px;border-radius:6px;font-size:14px;line-height:1;padding:0}
.tag button:hover{background:rgba(30,58,138,.12)}
.dd{position:absolute;left:0;right:0;top:calc(100% + 6px);z-index:1000;background:#fff;border:1px solid #E2E8F0;border-radius:12px;
  box-shadow:0 10px 30px rgba(15,23,42,.14);max-height:340px;overflow:auto;padding:4px}
.it{display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:8px;cursor:pointer}
.it.on{background:#EFF6FF}
.it .cd{font-variant-numeric:tabular-nums;color:#475569;font-size:13px;flex:none}
.it .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
.it .tg{flex:none;font-size:11px;color:#1E40AF;background:#DBEAFE;border-radius:999px;padding:1px 7px}
.it .tg.ok{color:#475569;background:#F1F5F9}
.ft{padding:6px 10px 4px;font-size:12px;color:#94A3B8}
.msg{padding:14px 10px;color:#94A3B8;font-size:13px}
@media(max-width:640px){.q{font-size:16px}}   /* iOS 小于 16px 会自动放大页面 */
"""

_JS = r"""
export default function (c) {
  const { data, setStateValue, parentElement } = c;
  const D = data || {};
  const multi = D.mode === 'multi', LIMIT = 50, max = D.max || 99;
  const fixed = D.fixed || [], cached = new Set(D.cached || []);
  let sel = (D.selected || []).slice();               // [{code, label, tag}]
  // 页面每次重算都会用新数据重新调用本函数，但旧实例的清理函数要到卸载时才执行 → 先清掉上一次留下的
  Array.from(parentElement.children).forEach(el => { if (el.classList && el.classList.contains('fs')) el.remove(); });   // parentElement 是 ShadowRoot，不支持 :scope
  const root = document.createElement('div');
  root.className = 'fs ' + (multi ? 'multi' : 'single');
  root.innerHTML = '<div class="box"><span class="tags"></span><input class="q" type="text" autocomplete="off" spellcheck="false"><span class="chev"></span></div><div class="dd" hidden></div>';
  parentElement.appendChild(root);
  const box = root.querySelector('.box'), tags = root.querySelector('.tags'), q = root.querySelector('.q'), dd = root.querySelector('.dd');
  const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  let all = null, items = [], active = 0;

  // 名录：首次聚焦时才下载；全页共用一份（两个搜索框只下载一次，之后走浏览器缓存）
  const load = () => {
    if (!window.__awFundNames) {
      window.__awFundNames = fetch(new URL(D.url, document.baseURI), { credentials: 'same-origin' })
        .then(r => r.ok ? r.json() : []).catch(() => []);
    }
    return window.__awFundNames;
  };

  function renderTags() {
    if (multi) {
      tags.innerHTML = sel.map((s, i) => `<span class="tag" title="${esc(s.label)}"><span>${esc(s.label)}</span><button data-i="${i}" aria-label="移除">×</button></span>`).join('');
      tags.querySelectorAll('button').forEach(b => b.onmousedown = e => { e.preventDefault(); e.stopPropagation(); sel.splice(+b.dataset.i, 1); emit(); renderTags(); });
      q.placeholder = sel.length ? '' : (D.placeholder || '');
      root.classList.toggle('has', sel.length > 0);
    } else {
      q.placeholder = D.placeholder || '';
      if (document.activeElement !== q && root.getRootNode().activeElement !== q) q.value = sel[0] ? sel[0].label : '';
    }
  }
  function emit() { setStateValue('value', multi ? sel.map(s => s.code) : (sel[0] ? sel[0].code : null)); }

  // 漏字/跳字匹配：输入的字按顺序都出现在名称里即可（如「易方达新综」→ 易方达中债新综指）
  const subseq = (t, n) => { let i = 0; for (const ch of n) { if (ch === t[i]) i++; if (i === t.length) return true; } return false; };
  function search(text) {
    const t = text.trim().toLowerCase(), out = [], seen = new Set();
    const chosen = new Set(multi ? sel.map(s => s.code) : []);        // 多选才排除已选项
    let total = 0;
    const add = (code, label, tag) => { if (chosen.has(code) || seen.has(code)) return; seen.add(code); total++; if (out.length < LIMIT) out.push({ code, label, tag }); };
    for (const f of fixed) if (!t || f.label.toLowerCase().includes(t)) add(f.code, f.label, f.tag);
    if (!all) return { out, total, loading: true };
    if (!t) { for (const [c, n] of all) if (cached.has(c)) add(c, `${c} ${n}`, '已有数据'); return { out, total }; }
    const hit = (c, n) => c.includes(t) || n.toLowerCase().includes(t);
    for (const [c, n] of all) if (cached.has(c) && hit(c, n)) add(c, `${c} ${n}`, '已有数据');
    for (const [c, n] of all) if (!cached.has(c) && hit(c, n)) add(c, `${c} ${n}`, '');
    if (total < 10 && t.length >= 2 && !/^\d+$/.test(t)) {           // 精确包含太少时补充漏字匹配
      for (const [c, n] of all) if (subseq(t, n.toLowerCase())) add(c, `${c} ${n}`, cached.has(c) ? '已有数据' : '');
    }
    return { out, total };
  }
  function renderList() {
    const r = search(q.value);
    items = r.out; active = Math.min(active, Math.max(0, items.length - 1));
    if (!multi && !q.value && sel[0] && active === 0) { const k = items.findIndex(x => x.code === sel[0].code); if (k > 0) active = k; }
    if (multi && sel.length >= max) { dd.innerHTML = `<div class="msg">最多选 ${max} 只，先移除一只再添加</div>`; return; }
    dd.innerHTML = items.length
      ? items.map((it, i) => `<div class="it${i === active ? ' on' : ''}" data-i="${i}"><span class="nm">${esc(it.label)}</span>${it.tag ? `<span class="tg${it.tag === '已有数据' ? ' ok' : ''}">${esc(it.tag)}</span>` : ''}</div>`).join('')
        + (r.total > items.length ? `<div class="ft">共 ${r.total} 条，显示前 ${items.length} 条，继续输入可缩小范围</div>` : '')
      : `<div class="msg">${r.loading ? '正在加载基金名录…' : '没有匹配的基金'}</div>`;
    dd.querySelectorAll('.it').forEach(el => {
      el.onmousedown = e => { e.preventDefault(); pick(+el.dataset.i); };
      el.onmouseenter = () => { active = +el.dataset.i; dd.querySelectorAll('.it').forEach((x, j) => x.classList.toggle('on', j === active)); };
    });
  }
  function pick(i) {
    const it = items[i]; if (!it) return;
    if (multi) { if (sel.length < max) sel.push(it); q.value = ''; renderTags(); renderList(); }
    else { sel = [it]; close(); q.blur(); }
    emit();
  }
  function open() {
    root.classList.add('open'); dd.hidden = false;
    if (!multi) { q.value = ''; }
    renderList();
    if (!all) load().then(rows => { all = rows; if (!dd.hidden) renderList(); });
  }
  function close() { root.classList.remove('open'); dd.hidden = true; active = 0; if (!multi) q.value = sel[0] ? sel[0].label : ''; }

  box.onmousedown = e => { if (e.target !== q) { e.preventDefault(); q.focus(); } };
  q.onfocus = open;
  q.onblur = () => setTimeout(close, 120);
  q.oninput = () => { active = 0; if (dd.hidden) open(); else renderList(); };
  q.onkeydown = e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); active = Math.min(active + 1, items.length - 1); renderList(); dd.querySelector('.it.on')?.scrollIntoView({ block: 'nearest' }); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); active = Math.max(active - 1, 0); renderList(); dd.querySelector('.it.on')?.scrollIntoView({ block: 'nearest' }); }
    else if (e.key === 'Enter') { e.preventDefault(); pick(active); }
    else if (e.key === 'Escape') { q.blur(); }
    else if (e.key === 'Backspace' && multi && !q.value && sel.length) { sel.pop(); renderTags(); renderList(); emit(); }
  };
  renderTags();
  return () => root.remove();
}
"""

_COMP = st.components.v2.component("aw_fund_search", css=_CSS, js=_JS)


def _label(code: str, fixed: list[dict]) -> dict:
    for f in fixed:
        if f["code"] == code:
            return f
    name = FL.fund_name(code) or ""
    return {"code": code, "label": f"{code} {name}".strip(), "tag": ""}


def fund_search(key: str, *, mode: str = "single", fixed: list[dict] | None = None,
                default=None, placeholder: str = "", max_sel: int | None = None):
    """渲染搜索框并返回当前选择。fixed = 置顶选项 [{code, label, tag}]（如 8 类回测资产）。"""
    ensure_static_names()
    fixed = fixed or []
    cur = (st.session_state.get(key) or {}).get("value", default)
    codes = (cur or []) if mode == "multi" else ([cur] if cur else [])
    ver = int(NAMES_JSON.stat().st_mtime) if NAMES_JSON.exists() else 0
    res = _COMP(
        key=key,
        data={"mode": mode, "fixed": fixed, "cached": FL.cached_codes(), "placeholder": placeholder,
              "max": max_sel, "selected": [_label(c, fixed) for c in codes],
              "url": f"app/static/fund_names.json?v={ver}"},
        default={"value": default},
        on_value_change=lambda: None,
    )
    val = res.get("value", default) if hasattr(res, "get") else default
    if mode == "multi":
        return list(val or [])
    return val or default
