"""H5 / Streamlit 共用的内嵌图表 HTML 生成（纯函数，零 Streamlit 依赖）。

与 `streamlit_app/app.py` 里的 `_scroll_chart_html` / `_pnl_chart_html` 及其依赖
（`_COMP_BASE_CSS`、`_PNL_TPL`、`_range_buttons`、`_trend_*` 系列、`_chart_head_block`）
**逐字节同源**。这里是不带 `st.*` 调用的副本，供 `api/server.py` 直接 import。

为什么是副本而不是 import app.py：app.py 文件底部会执行 Streamlit UI，
bare mode 下 `ACCT_INFO is None` 会在 4607 行直接抛 TypeError，API 进程里 import 不了。
改动任一图表逻辑时，本文件与 app.py 必须同步修改，保证 H5 与 Python 版视觉/交互一致。
"""
from __future__ import annotations

import json
from datetime import date
from html import escape as html_escape

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 共享样式：走势分析 / 收益日历 / 基金对比 三个 iframe 组件共用，保证视觉完全一致。
# 改样式只改这里；颜色与 :root 设计 token 同值（iframe 内拿不到父页面 CSS 变量）。
# ---------------------------------------------------------------------------
_COMP_BASE_CSS = r"""html,body{margin:0;padding:0;background:#fff;color:#334155;font:13px/1.6 -apple-system,"PingFang SC",sans-serif}
*{box-sizing:border-box}#wrap{position:relative;width:100%}
.heading{display:flex;align-items:center;justify-content:space-between;gap:12px}
h3{margin:0;font-size:17px;font-weight:600;color:#0F172A;display:flex;align-items:center;gap:8px}
.icon{width:17px;height:17px;fill:none;stroke:currentColor;stroke-width:1.5;vertical-align:middle}
#updating{font-size:12px;color:#475569;visibility:hidden}#wrap[aria-busy="true"] #updating{visibility:visible}
/* 控件区：与 H5 的 RangeBar 逐项同款（无下划线、无下拉框）。
   区间 = 药丸 chip；周期 = 分段控件。用户 2026-11-08：「一个曲线用不同的展示方式」—— 
   同一个「日线/月线/年线」在 iframe 是 select 下拉、在 H5 页面是分段按钮，必须只有一种。 */
.controls{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:14px;flex-wrap:wrap}
#range-controls{display:flex;gap:8px;flex-wrap:wrap;min-width:0}
button[data-range]{font:inherit;font-size:13px;line-height:1.4;border:1px solid #EEF0F3;border-radius:15px;
  background:#fff;color:#4B5563;padding:5px 12px;white-space:nowrap;cursor:pointer;flex:none}
button[data-range]:hover{border-color:#CBD5E1;color:#0F172A}
button[data-range][aria-pressed="true"]{background:#EEF2FF;color:#1E40AF;border-color:#C7D2FE;font-weight:600}
button:focus-visible,#chart:focus-visible{outline:2px solid #3B82F6;outline-offset:2px}
/* 周期分段：与 H5 的 .seg2 同款（浅灰槽 + 白色选中块） */
#period-seg{display:inline-flex;background:#EEF0F3;border-radius:9px;padding:2px;margin-left:auto;
  font-size:12.5px;color:#4B5563}
#period-seg button{font:inherit;font-size:12.5px;line-height:1.5;border:0;background:transparent;padding:4px 12px;
  border-radius:7px;color:#4B5563;cursor:pointer}
#period-seg button:disabled{opacity:.4;cursor:default}
#period-seg button[aria-pressed="true"]{background:#fff;color:#111827;font-weight:600;box-shadow:0 1px 2px rgba(0,0,0,.08)}
.state-line{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin:8px 0 2px;font-size:12px;color:#475569;font-variant-numeric:tabular-nums}
.date-line{display:flex;align-items:center;gap:6px}#selection{color:#475569}#selection[data-custom="true"]{font-weight:600}
#range{font-variant-numeric:tabular-nums}#notice{min-height:20px;font-size:12px;color:#475569}
#chart{display:block;width:100%;touch-action:pan-y;cursor:grab;user-select:none}
#chart.dragging{cursor:grabbing}
/* 图表带 tabindex，鼠标点一下/拖一下浏览器会套一圈蓝色焦点框（看着像选中了整个图）；
   鼠标操作不要这圈框，键盘 Tab 进来才留，a11y 不减 */
#chart:focus{outline:none}
#chart:focus-visible{outline:2px solid #1E40AF;outline-offset:2px;border-radius:6px}
#tip{position:absolute;pointer-events:none;background:#fff;color:#0F172A;border:1px solid #E2E8F0;
font-size:12px;line-height:1.8;padding:10px 14px;border-radius:8px;display:none;z-index:10;width:240px;max-width:calc(100% - 8px);
box-shadow:0 4px 16px rgba(15,23,42,.16);font-variant-numeric:tabular-nums}
#tip .tip-row{display:flex;justify-content:space-between;gap:18px}#tip .tip-label{color:#475569}
#stats{border-top:1px solid #E2E8F0;margin-top:8px;padding:16px 0 4px}
.summary-main{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.summary-result{display:flex;align-items:baseline;gap:12px}.summary-result b{font-size:24px;font-weight:600;letter-spacing:-.5px}
.summary-prices{display:flex;gap:10px;align-items:center;font-size:13px;font-variant-numeric:tabular-nums}
.summary-prices small{color:#475569;margin-right:4px}.summary-prices b{font-weight:500}
.amp-row{display:flex;align-items:center;gap:8px 16px;flex-wrap:wrap;margin-top:10px;color:#475569;font-size:12px}
.amp-row b{color:#334155;font-size:14px;font-weight:600}.amp-row small{font-size:11px}
/* 与 RangeBar 的 400px 断点对齐：iframe 的 @media 量的是 iframe 自身宽度（卡片内容宽 ≈
   父页面视口 - 56），所以这里写 344 才和父页面的 400 落在同一个实际屏幕上（430 宽的手机两边都是行内）。 */
@media(max-width:344px){#period-seg{margin-left:0;width:100%}#period-seg button{flex:1}}
@media(max-width:520px){#range-controls{gap:6px;width:100%;flex-wrap:wrap}
  .state-line{font-size:11px}.summary-result b{font-size:21px}.summary-prices{flex-wrap:wrap;font-size:12px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto}}
"""

# 区间与阶段：走势页、账户净值曲线共用（定义要在 trend_chart_html 之前）
_TREND_RANGES = {
    "近1月": ("months", 1), "近3月": ("months", 3), "近6月": ("months", 6),
    "近1年": ("years", 1), "近3年": ("years", 3), "近5年": ("years", 5),
    "今年来": ("ytd", 0), "全部": ("all", 0),
}


# 两条 iframe 曲线的 tooltip 结构只此一份：第一行日期，下面每项一行「文字描述（左）+ 数值（右对齐）」。
# 净值走势与累计盈亏都插这段，别再各写一套 —— 累计盈亏曾经一直是大数字打头的老结构，
# 规范写了却没人发现漏改（2026-11-08 用户第三次指出）。
_TIP_JS = r"""
  const tipHead = d => '<b>' + esc(d) + '</b>';
  const tipRow = (label, value, labelColor, valueColor) =>
    '<div class="tip-row"><span class="tip-label"' + (labelColor ? ' style="color:' + labelColor + '"' : '')
    + '>' + label + '</span><b' + (valueColor ? ' style="color:' + valueColor + '"' : '') + '>' + value + '</b></div>';
"""


def _range_buttons(active):
    """区间 tab 按钮（走势分析 / 走势对比共用），选项来自 _TREND_RANGES。"""
    tips = {"今年来": "以去年最后一个交易日为基准"}
    return "".join(
        f'<button data-range="{r}" aria-pressed="{str(r == active).lower()}"'
        + (f' title="{tips[r]}"' if r in tips else "") + f">{r}</button>"
        for r in _TREND_RANGES)


def _trend_aggregate(series, period):
    """只聚合数值，保留每期最后一条记录的真实日期，不伪造未来期末日期。"""
    clean = pd.to_numeric(series, errors="coerce").dropna().sort_index()
    clean = clean.loc[~clean.index.duplicated(keep="last")]
    clean = clean.loc[np.isfinite(clean) & (clean.index <= pd.Timestamp(date.today()))]
    if period != "日":
        freq = "M" if period == "月" else "Y"
        clean = clean.groupby(clean.index.to_period(freq), sort=True).tail(1)
    return clean


def _trend_window_start(series, span):
    """区间起点下标 = 基准那一条（与支付宝/天天基金「历史业绩」同口径）。

    - 近N月/年：基准 = 截止日往前推 N 个自然月/年那天的净值；那天不是交易日就用之前最近一个交易日。
    - 今年来：基准 = 去年最后一个交易日的净值（不是今年第一天，否则会漏掉第一天的涨跌）。
    - 数据不够长：从第一条开始。
    """
    if series.empty:
        return 0
    kind, amount = span
    if kind == "all":
        return 0
    if kind == "count":
        return max(0, len(series) - int(amount))
    end = series.index[-1]
    if kind == "ytd":
        i = int(series.index.searchsorted(pd.Timestamp(year=end.year, month=1, day=1), side="left")) - 1
    else:
        i = int(series.index.searchsorted(end - pd.DateOffset(**{kind: int(amount)}), side="right")) - 1
    return max(0, min(i, len(series) - 1))


def _period_label(t, period):
    """期间标签：日=2026/09/24；月=2026年9月；年=2026年（CLAUDE.md 日期规范）。"""
    if period == "日":
        return f"{t:%Y/%m/%d}"
    if period == "月":
        return f"{t.year}年{t.month}月"
    return f"{t.year}年"


def trend_chart_data(series):
    """一次提供三种粒度的全量历史；只预计算五个初始视窗，不截断历史。"""
    histories = {}
    for period in ("日", "月", "年"):
        agg = _trend_aggregate(series, period)
        returns = agg.pct_change(fill_method=None) * 100
        histories[period] = {
            "labels": [_period_label(t, period) for t in agg.index],
            "dates": agg.index.strftime("%Y/%m/%d").tolist(),
            "prices": agg.tolist(),
            "rets": [float(v) if pd.notna(v) and np.isfinite(v) else None for v in returns],
            "windows": {label: {"start": _trend_window_start(agg, span),
                                "count": len(agg) - _trend_window_start(agg, span)}
                        for label, span in _TREND_RANGES.items()},
        }
    return histories


def _chart_head_block(heading: str, icon_path: str) -> str:
    """图表卡片顶部那一行标题。heading 为空就整行隐藏，只留一个 #updating 给加载提示用。"""
    if not heading:
        return '<div class="heading" hidden><span id="updating" role="status">正在更新</span></div>'
    return ('<div class="heading"><h3><svg class="icon" viewBox="0 0 24 24" aria-hidden="true">'
            f'<path d="{icon_path}"/></svg>{html_escape(heading)}</h3>'
            '<span id="updating" role="status">正在更新</span></div>')


# ---------------------------------------------------------------------------
# 买卖点走势图：全历史数据 + 有界索引视窗；只绘制可见部分，不创建超宽画布。
# 一张图三层面板，共用同一条时间轴：上方净值折线（含起点虚线），
# 中间每个点位相对区间起点的涨跌幅柱，下方单期涨跌幅柱（涨红跌绿）。
# ---------------------------------------------------------------------------
def trend_chart_html(labels, values, win, height=540, rets=None, revision=0, histories=None,
                     trades=None, store=None, default_range="近1月", heading="走势分析"):
    """全历史数据 + 有界索引视窗；只绘制可见部分，不创建超宽画布。

    trades：历史成交点 [{date:"2026/10/27", side:"买入", label:"1,234.00 份 @ 2.4567"}]，
    按日期落到当前粒度的那一期上，买点上方挂红「买」、卖点下方挂绿「卖」小徽标，悬停/点开进提示框。
    """
    def numbers(items):
        if items is None:
            return []
        return [float(v) if pd.notna(v) and np.isfinite(v) else None for v in items]

    if histories is None:
        prices_list = numbers(values)
        actual_win = min(max(0, int(win)), len(prices_list))
        histories = {"日": {"labels": labels, "dates": labels, "prices": prices_list,
                              "rets": numbers(rets) if rets is not None else [None] * len(prices_list),
                              "windows": {key: {"start": len(prices_list) - actual_win, "count": actual_win}
                                          for key in _TREND_RANGES}}}
    payload = json.dumps({
        "histories": histories, "win": int(win), "height": int(height), "revision": revision,
        "trades": trades or [], "store": store or "awTrend.single",
        "defaultRange": default_range, "heading": heading,
    }, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    template = r"""<style>
__BASE_CSS__
__HEAD_CSS__
</style>
<div id="wrap" aria-busy="false">
__HEAD_BLOCK__
<div class="controls"><div id="range-controls" role="group" aria-label="常用区间">
__RANGE_BTNS__
</div><span id="period-seg" role="group" aria-label="周期"><button data-p="日" aria-pressed="false">日线</button><button data-p="月" aria-pressed="false">月线</button><button data-p="年" aria-pressed="false">年线</button></span></div>
<div id="notice" role="status"></div>
<svg id="chart" role="img" aria-label="基金历史走势，可拖动和缩放" tabindex="0"></svg>
<div class="state-line"><span id="selection" aria-live="polite"></span><span class="date-line"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5" width="16" height="15" rx="2" fill="none"/><path d="M8 3v5m8-5v5M4 10h16"/></svg><span id="range"></span></span></div>
<div id="stats"></div><div id="tip"></div>
</div>
<script>
(() => {
  const D = __CHART_DATA__;__TIP_JS__
  const svg = document.getElementById('chart'), wrap = document.getElementById('wrap');
  const tip = document.getElementById('tip'), range = document.getElementById('range');
  // 切「单只/多只」或换基金都会重建 iframe，JS 里的选择随之丢失 → 存一份到 localStorage（srcdoc 同源可访问），重建时还原
  const STORE = D.store || 'awTrend.single';
  const memo = (() => { try { return JSON.parse(localStorage.getItem(STORE) || '{}'); } catch (e) { return {}; } })();
  const saveMemo = () => { try { localStorage.setItem(STORE, JSON.stringify({period, range: lastRange})); } catch (e) {} };
  const DEF_RANGE = D.defaultRange || '近1月';
  let period = D.histories[memo.period] ? memo.period : '日';
  let lastRange = (D.histories[period].windows || {})[memo.range] ? memo.range : DEF_RANGE;
  let activeRange = lastRange, customDates = null;
  let P = D.histories[period], n = P.prices.length;
  const H = D.height, L = 64, R = 16, T = 32, B = 32, GAP = 30, minCount = 1;
  // 绘图区主次：净值55%、累计变化27%、单期变化18%。
  const PH = H - T - B - GAP * 2, AH = PH * .55, BH = PH * .27, CH = PH * .18;
  const bTop1 = T + AH + GAP, bTop2 = bTop1 + BH + GAP;
  let initialCount = P.windows[lastRange].count, initialStart = P.windows[lastRange].start;
  let count = initialCount, start = initialStart, W = 0, PW = 0, frame = 0;
  let dragging = null, pinned = null, hover = null;
  // 当前视窗内的成交点：期号 → [成交...]，每次 draw 重算，悬停提示与买卖徽标共用
  let tradeAt = new Map(), nBuy = 0, nSell = 0;
  // 周期控件：分段按钮（原来是 <select> 下拉，和 H5 的分段控件不是一套）
  const periodSeg = document.getElementById('period-seg');
  const periodBtns = [...periodSeg.querySelectorAll('button')];
  const syncPeriodButtons = () => periodBtns.forEach(b => {
    b.disabled = !D.histories[b.dataset.p];
    b.setAttribute('aria-pressed', String(b.dataset.p === period));
  });
  periodBtns.forEach(b => { b.onclick = () => { if (b.dataset.p !== period && D.histories[b.dataset.p]) setPeriod(b.dataset.p); }; });
  syncPeriodButtons();
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const valid = v => v !== null && Number.isFinite(v);
  const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  const x = i => L + (i + .5 - start) * PW / count;
  const bounds = () => {
    if (count <= 0) return [0, -1];
    let first = Math.max(0, Math.ceil(start - .5 + 1e-8));
    let last = Math.min(n - 1, Math.floor(start + count - .5 - 1e-8));
    if (last < first) first = last = clamp(Math.round(start + count / 2 - .5), 0, n - 1); // 窗口中点落在两期之间时取最近一期
    return [first, last];
  };
  const pct = v => valid(v) ? (v > 0 ? '+' : '') + v.toFixed(2) + '%' : '—';
  const color = v => !valid(v) || Math.abs(v) < 1e-10 ? '#475569' : (v > 0 ? '#C52828' : '#16703B');
  const price = v => valid(v) ? v.toFixed(4) : '—';
  // 买卖点标记：不用三角箭头（用户 2026-11-07「直接曲线上一个买入，卖出的图标」），
  // 改成挂在成交那一期旁边的「买」/「卖」小徽标 —— 圆角小牌 + 白描边，加一颗同色定位点说明是哪一天。
  // 买方挂点上方、卖方挂点下方，并夹在净值面板（T…T+AH）内，首末期也不会被裁掉一半。
  const badgeW = 21, badgeH = 15, badgeGap = 8;
  const tradeBadge = (cx, cy, text, fill, above) => {
    // 定位点永远压在真实数据点上；只有徽标贴边时往内收，并用细线接回定位点，
    // 免得首末期出现「点和徽标错开」（2026-11-08 用户指出）。
    const bx = clamp(cx - badgeW / 2, L + 1, W - R - badgeW - 1);
    const by = clamp(above ? cy - badgeGap - badgeH : cy + badgeGap, T + 1, T + AH - badgeH - 1);
    const cxB = bx + badgeW / 2, edgeY = above ? by + badgeH : by;
    const link = Math.abs(cxB - cx) > .5
      ? `<line x1="${cxB.toFixed(1)}" y1="${edgeY.toFixed(1)}" x2="${cx.toFixed(1)}" y2="${cy.toFixed(1)}" stroke="${fill}" stroke-width="1" opacity=".45"/>`
      : '';
    return `<g data-mark="${text === '买' ? 'buy' : 'sell'}">${link}`
      + `<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="3.6" fill="${fill}" stroke="#fff" stroke-width="1.4"/>`
      + `<rect x="${bx.toFixed(1)}" y="${by.toFixed(1)}" width="${badgeW}" height="${badgeH}" rx="4.5" fill="${fill}" stroke="#fff" stroke-width="1.4"/>`
      + `<text x="${cxB.toFixed(1)}" y="${(by + badgeH / 2 + 3.6).toFixed(1)}" text-anchor="middle" font-size="10" font-weight="600" fill="#fff">${text}</text></g>`;
  };
  function requestDraw() { if (!frame) frame = requestAnimationFrame(() => {frame = 0; draw();}); }
  function update(nextStart, nextCount) {
    if (!n) return;
    count = clamp(nextCount, minCount, n);
    start = clamp(nextStart, 0, Math.max(0, n - count));
    activeRange = Math.abs(count-initialCount)<1e-6 && Math.abs(start-initialStart)<1e-6 ? lastRange : null;
    const [first,last] = bounds();
    customDates = activeRange ? null : [P.dates[first], P.dates[last]];
    hover = null; requestDraw();
  }
  function useRange(label) {
    lastRange = activeRange = label; customDates = null;
    initialCount = P.windows[label].count; initialStart = P.windows[label].start;
    count = initialCount; start = initialStart; pinned = hover = null;
    wrap.setAttribute('aria-busy', 'true'); requestDraw(); saveMemo();
  }
  document.querySelectorAll('[data-range]').forEach(button => button.onclick = () => useRange(button.dataset.range));
  function setPeriod(next) {
    const keepDates = activeRange ? null : customDates;
    period = next; P = D.histories[period]; n = P.prices.length;
    initialCount = P.windows[lastRange].count; initialStart = P.windows[lastRange].start;
    if (keepDates) {
      const first = P.dates.findIndex(d => d >= keepDates[0]);
      let last = P.dates.length - 1;
      while (last >= 0 && P.dates[last] > keepDates[1]) last--;
      start = Math.max(0, first); count = first < 0 || last < first ? 0 : last - first + 1;
      activeRange = null;
    } else { start = initialStart; count = initialCount; }
    pinned = hover = null; wrap.setAttribute('aria-busy', 'true'); requestDraw(); saveMemo();
    syncPeriodButtons();
  }
  function zoom(factor, px = L + PW / 2) {
    if (!PW) return;
    const fraction = clamp((px - L) / PW, 0, 1), anchor = start + fraction * count;
    const next = clamp(count * factor, minCount, n);
    update(anchor - fraction * next, next);
  }
  function draw() {
    const width = wrap.getBoundingClientRect().width;
    if (width <= L + R) return; // 隐藏标签页尚未布局，等待 ResizeObserver。
    W = width; PW = W - L - R;
    svg.setAttribute('width', W); svg.setAttribute('height', H);
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    const [first, last] = bounds();
    const visibleCount = Math.max(0,last-first+1);
    document.querySelectorAll('[data-range]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.range === activeRange)));
    const selection = document.getElementById('selection');
    selection.textContent = `当前：${activeRange || '自选区间'} · ${period}线`;
    selection.dataset.custom = String(!activeRange);
    wrap.dataset.range = activeRange || '自选区间'; wrap.dataset.period = period;
    wrap.dataset.start = String(first); wrap.dataset.end = String(last);
    wrap.dataset.count = String(count); wrap.dataset.total = String(n);
    wrap.dataset.initialCount = String(initialCount); wrap.dataset.rendered = String(visibleCount);
    wrap.dataset.firstDate = visibleCount ? P.dates[first] : ''; wrap.dataset.lastDate = visibleCount ? P.dates[last] : '';
    document.getElementById('notice').textContent = visibleCount === 1 ? '该范围仅有1期数据，保留真实单点。' : '';
    wrap.setAttribute('aria-busy', 'false');
    if (!visibleCount) {
      range.textContent = customDates ? customDates.join(' — ') : '暂无有效日期';
      document.getElementById('notice').textContent = '该范围暂无此粒度的数据，请更换范围或周期。';
      svg.innerHTML = ''; tip.style.display = 'none'; document.getElementById('stats').innerHTML = '';
      wrap.dataset.bars = wrap.dataset.stepBars = '0'; return;
    }
    range.textContent = `${P.dates[first]} — ${P.dates[last]}`;
    const visible = P.prices.slice(first, last + 1).filter(valid);
    let lo = visible.length ? Math.min(...visible) : 0, hi = visible.length ? Math.max(...visible) : 1;
    const pad = (hi - lo) * .12 || Math.max(Math.abs(hi) * .02, .01);
    lo -= pad; hi += pad;
    const y = v => T + (hi - v) * AH / (hi - lo);
    // 相对起点（可见第一期净值为 0% 基准）与单期涨跌幅，各自一个柱面板
    const startPx = valid(P.prices[first]) ? P.prices[first] : null;
    const relAt = i => (startPx && startPx > 0 && valid(P.prices[i])) ? (P.prices[i]/startPx - 1) * 100 : null;
    const stepAt = i => P.rets[i];
    let grid = '', marks = '', ticks = `<text x="${L}" y="18" font-size="12" fill="#475569">净值</text>`;
    for (let k = 0; k <= 4; k++) {
      const v = lo + (hi - lo) * k / 4, yy = y(v);
      grid += `<line x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}" stroke="#EEF2F7"/>`;
      ticks += `<text x="${L-8}" y="${yy+4}" text-anchor="end" font-size="10" fill="#475569">${v.toFixed(4)}</text>`;
    }
    const step = PW / count;
    const pts = [], bw = Math.min(20, Math.max(.8, step * .45));
    for (let i = first; i <= last; i++) if (valid(P.prices[i])) pts.push(`${x(i)},${y(P.prices[i])}`);
    marks += `<polyline points="${pts.join(' ')}" fill="none" stroke="#1E40AF" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
    for (let i = first; i <= last; i++) if (valid(P.prices[i])) {
      marks += `<circle data-index="${i}" cx="${x(i)}" cy="${y(P.prices[i])}" r="${Math.min(3.5,Math.max(1,step*.12))}" fill="#1E40AF"/>`;
    }
    // 起点：净值面板上画一条虚线并圈出该点，相对起点柱全部以它为 0% 基准
    const y0 = startPx ? y(startPx) : null;
    if (y0 !== null && y0 >= T && y0 <= T + AH) {
      grid += `<line x1="${L}" y1="${y0}" x2="${W-R}" y2="${y0}" stroke="#94A3B8" stroke-dasharray="2 4" opacity=".85"/>`;
      marks += `<circle cx="${x(first)}" cy="${y0}" r="4.5" fill="none" stroke="#1E40AF" stroke-width="1.5" opacity=".9"/>`;
    }
    // 一个柱面板：0 轴居中、左刻度 ±上限、涨红跌绿
    function barPane(top, paneHeight, title, valAt, attr) {
      const zero = top + paneHeight / 2, vals = [], amps = [];
      for (let i = first; i <= last; i++) {
        const v = valAt(i); vals.push(v); if (valid(v)) amps.push(Math.abs(v));
      }
      const bmax = Math.max(.5, amps.length ? Math.max(...amps) : 0);
      const yB = v => zero - v * (paneHeight / 2 - 8) / bmax;
      // 刻度在裁剪区域之外，否则左侧百分比会被 plot-clip 裁掉。
      ticks += `<text x="${L}" y="${top-10}" font-size="12" fill="#475569">${title}</text>`
        + `<text x="${L-8}" y="${top+11}" text-anchor="end" font-size="10" fill="#475569">+${bmax.toFixed(2)}%</text>`
        + `<text x="${L-8}" y="${zero+3.5}" text-anchor="end" font-size="10" fill="#475569">0%</text>`
        + `<text x="${L-8}" y="${top+paneHeight-1}" text-anchor="end" font-size="10" fill="#475569">-${bmax.toFixed(2)}%</text>`;
      let out = `<line x1="${L}" y1="${zero}" x2="${W-R}" y2="${zero}" stroke="#E2E8F0" stroke-dasharray="3 3"/>`;
      let cnt = 0;
      for (let i = first; i <= last; i++) {
        const v = vals[i - first]; if (!valid(v)) continue;
        const yv = yB(v); cnt++;
        out += `<rect ${attr}="${i}" data-value="${v}" x="${x(i)-bw/2}" y="${Math.min(yv,zero)}" width="${bw}" height="${Math.abs(yv-zero)}" fill="${color(v)}" opacity=".88" rx="1"/>`;
      }
      return [out, cnt];
    }
    const [pane1, cntRel] = barPane(bTop1, BH, '相对起点涨跌幅', relAt, 'data-bar');
    const [pane2, cntStep] = barPane(bTop2, CH, `单${period}涨跌幅`, stepAt, 'data-step');
    marks += pane1 + pane2;
    // 标签只来自真实记录，横排并按实际像素间隔抽稀；两端标签留在画布内且互不重叠
    const spacing = Math.max(1, Math.ceil(74 / step));
    const ids = [];
    for (let i = first; i <= last; i += spacing) ids.push(i);
    if (ids.length > 1 && last - ids[ids.length-1] < spacing) ids.pop();
    if (!ids.includes(last)) ids.push(last);
    const labs = [];
    for (const i of ids) {
      const cx = clamp(x(i), L + 40, W - R - 40);
      while (labs.length && cx - labs[labs.length-1].cx < 70) labs.pop();
      labs.push({i, cx});
    }
    for (const {i, cx} of labs) {
      ticks += `<text data-date-label="${i}" x="${cx}" y="${H-15}" text-anchor="middle" font-size="10" fill="#475569">${esc(P.labels[i])}</text>`;
    }
    // 区间最高/最低只用来算「振幅」那个数字，不再往图上钉白底标注框：
    // 占地方、还容易压住买卖徽标，看图的人真正要认的是买卖点。
    let hiI = null, loI = null;
    for (let i = first; i <= last; i++) {
      if (!valid(P.prices[i])) continue;
      if (hiI === null || P.prices[i] > P.prices[hiI]) hiI = i;
      if (loI === null || P.prices[i] < P.prices[loI]) loI = i;
    }
    // 历史成交点：按日期落到当前粒度的那一期（日线=当天，月/年线=该期最后一条记录）。
    // 买挂「买」徽标在上、卖挂「卖」徽标在下；同一期多笔只挂一个，逐笔细节进提示框。
    tradeAt = new Map(); nBuy = 0; nSell = 0;
    let tmarks = '';
    for (const t of (D.trades || [])) {
      let ti = -1;
      for (let k = n - 1; k >= 0; k--) { if (P.dates[k] <= t.date) { ti = k; break; } }
      if (ti < 0 || ti < first || ti > last || !valid(P.prices[ti])) continue;
      const e = tradeAt.get(ti) || {list: []}; e.list.push(t); tradeAt.set(ti, e);
    }
    for (const [ti, e] of tradeAt) {
      // 定位点跟着真实净值的 x 走（只夹在绘图区内），不再为了给徽标腾地方把点也挪走
      const cx = clamp(x(ti), L, W - R), cy = y(P.prices[ti]);
      const nb = e.list.filter(t => t.side === '买入').length;
      nBuy += nb; nSell += e.list.length - nb;
      if (nb) tmarks += tradeBadge(cx, cy, '买', '#C52828', true);
      if (e.list.length - nb) tmarks += tradeBadge(cx, cy, '卖', '#16703B', false);
    }
    svg.innerHTML = `<defs><clipPath id="plot-clip"><rect x="${L}" y="${T-5}" width="${PW}" height="${H-T-B+10}"/></clipPath></defs>${grid}<g clip-path="url(#plot-clip)">${marks}<line id="guide" y1="${T}" y2="${H-B}" stroke="#94A3B8" stroke-dasharray="4 4" visibility="hidden"/></g>${ticks}${tmarks ? `<g clip-path="url(#plot-clip)" data-trades="${nBuy + nSell}">${tmarks}</g>` : ''}`;
    wrap.dataset.bars = String(cntRel); wrap.dataset.stepBars = String(cntStep);
    const change = relAt(last);
    const amplitude = hiI !== null && loI !== null && P.prices[loI] > 0 ? (P.prices[hiI]/P.prices[loI]-1)*100 : null;
    document.getElementById('stats').innerHTML =
      `<div class="summary-main"><div class="summary-result"><span>当前区间变化</span>`
      + `<b id="change" data-value="${valid(change) ? change : ''}" style="color:${color(change)}">${pct(change)}</b></div>`
      + `<div class="summary-prices"><span><small>起点价</small><b id="start-price" data-value="${startPx ?? ''}">${price(startPx)}</b></span>`
      + `<span aria-hidden="true">→</span><span><small>终点价</small><b id="end-price" data-value="${P.prices[last] ?? ''}">${price(P.prices[last])}</b></span></div></div>`
      + `<div class="amp-row"><span>净值区间振幅</span><b id="amplitude" data-value="${valid(amplitude) ? amplitude : ''}">${valid(amplitude) ? amplitude.toFixed(2)+'%' : '—'}</b>`
      + `<small>最高净值 ÷ 最低净值 − 1 · 当前 ${visibleCount} 期 / 全历史 ${n} 期</small></div>`
      + ((nBuy || nSell)
         ? `<div class="amp-row" id="trade-row"><span>历史成交</span><b>买 ${nBuy} 笔 · 卖 ${nSell} 笔</b></div>`
         : '');
    if (pinned !== null) showTip(pinned); else tip.style.display = 'none';
  }
  function showTip(i, clientY = null) {
    const [first,last] = bounds(), guide = document.getElementById('guide');
    if (!Number.isInteger(i) || i < first || i > last) {tip.style.display='none'; if(guide) guide.setAttribute('visibility','hidden'); return;}
    if (guide) {guide.setAttribute('x1',x(i)); guide.setAttribute('x2',x(i)); guide.setAttribute('visibility','visible');}
    tip.dataset.index = String(i);
    const px = P.prices[i], rt = P.rets[i];
    const sp = P.prices[first];
    const rel = valid(px) && valid(sp) && sp !== 0 ? (px/sp - 1) * 100 : null;
    tip.innerHTML = tipHead(P.dates[i])
      + tipRow('净值', price(px))
      + tipRow(`单${period}涨跌幅`, pct(rt), '', color(rt))
      + tipRow('相对起点', pct(rel), '', color(rel))
      + ((tradeAt.get(i) || {list: []}).list.map(t =>
          tipRow(esc(t.side), esc(t.label), t.side === '买入' ? '#C52828' : '#16703B')).join(''))
      + `<small class="tip-label">基准 ${esc(P.dates[first])}</small>`
      + `${pinned!==null?'<br><small>已固定，再次点击取消</small>':''}`;
    tip.style.display='block';
    // SVG没有offsetTop：必须用实际边界转为wrap内坐标，否则NaN使提示落入普通文档流。
    const wrapBox = wrap.getBoundingClientRect(), chartBox = svg.getBoundingClientRect();
    const chartTop = chartBox.top - wrapBox.top;
    const screenX = chartBox.left - wrapBox.left + x(i) * chartBox.width / W;
    const preferredLeft = screenX + 12 + tip.offsetWidth <= wrapBox.width - 4
      ? screenX + 12 : screenX - tip.offsetWidth - 12;
    tip.style.left = clamp(preferredLeft, 4, Math.max(4, wrapBox.width-tip.offsetWidth-4))+'px';
    const cursorY = clientY === null ? null : clientY - chartBox.top;
    const anchorY = cursorY === null ? chartTop + T + 4 : chartTop + cursorY
      + (cursorY > chartBox.height / 2 ? -tip.offsetHeight - 14 : 14);
    let visibleTop = 0, visibleBottom = innerHeight;
    // Streamlit同源iframe可能只有一部分在父页面屏幕内，提示也需落在该交集内。
    try {
      const embed = window.frameElement;
      if (embed) {
        const box = embed.getBoundingClientRect();
        visibleTop = Math.max(0, -box.top);
        visibleBottom = Math.min(innerHeight, parent.innerHeight-box.top);
      }
    } catch (_) { /* 跨源嵌入时按本iframe视口限制。 */ }
    const top = Math.max(chartTop+4, visibleTop-wrapBox.top+4);
    const bottom = Math.min(chartBox.bottom-wrapBox.top, visibleBottom-wrapBox.top);
    tip.style.top = clamp(anchorY, top, Math.max(top, bottom-tip.offsetHeight-4))+'px';
  }
  const localX = e => e.clientX - svg.getBoundingClientRect().left;
  svg.addEventListener('pointerdown', e => {
    if (e.button !== 0 || !PW || !count || localX(e)<L || localX(e)>W-R) return;
    dragging={id:e.pointerId,x:e.clientX,start,count,moved:false};
    svg.setPointerCapture(e.pointerId); svg.classList.add('dragging');
  });
  svg.addEventListener('pointermove', e => {
    if (dragging) {
      const delta=e.clientX-dragging.x;
      if(Math.abs(delta)>3) dragging.moved=true;
      if(dragging.moved) {pinned=null; update(dragging.start-delta*dragging.count/PW,dragging.count);}
    } else if (pinned===null && PW) {
      const px=localX(e);
      hover=px<L||px>W-R?null:Math.floor(start+(px-L)*count/PW);
      showTip(hover, e.clientY);
    }
  });
  function release(e) {
    if (!dragging) return;
    if(!dragging.moved && e.type==='pointerup') {
      const i=Math.floor(start+(localX(e)-L)*count/PW);
      pinned=pinned===i?null:i; showTip(pinned, e.clientY);
    }
    if(svg.hasPointerCapture(e.pointerId)) svg.releasePointerCapture(e.pointerId);
    dragging=null; svg.classList.remove('dragging');
  }
  svg.addEventListener('pointerup',release); svg.addEventListener('pointercancel',release);
  svg.addEventListener('pointerleave',()=>{if(pinned===null&&!dragging) showTip(null);});
  svg.addEventListener('wheel', e => {
    if(!PW || !count) return;
    if(e.ctrlKey||e.metaKey){
      e.preventDefault(); pinned=null;
      zoom(Math.exp(clamp(e.deltaY,-400,400)*.003),localX(e));
      return;
    }
    // 规则（CLAUDE.md「时间轴平移交互规范」）：只有水平滚动才平移时间轴；
    // 上下滑动页面（deltaY 为主）原样交给页面滚动，图表不动、也不 preventDefault。
    const dx=e.deltaX||0, dy=e.deltaY||0;
    if(Math.abs(dx)<=Math.abs(dy)||Math.abs(dx)<1) return;
    e.preventDefault(); pinned=null;
    update(start+dx*(e.deltaMode===1?16:1)*count/PW,count);
  },{passive:false});
  // 未展示工具栏：双击复位即可，交互能力不减
  function reset(){useRange(lastRange);}
  svg.addEventListener('dblclick',reset);
  new ResizeObserver(requestDraw).observe(wrap);
  requestDraw();
})();
</script>"""
    return (template.replace("__BASE_CSS__", _COMP_BASE_CSS)
            .replace("__TIP_JS__", _TIP_JS)
            .replace("__HEAD_CSS__", "" if heading else ".controls{margin-top:2px}")
            .replace("__HEAD_BLOCK__", _chart_head_block(heading, "M4 4v16h16M7 14l4-5 4 3 5-7"))
            .replace("__RANGE_BTNS__", _range_buttons(default_range))
            .replace("__CHART_DATA__", payload))


# ---------------------------------------------------------------------------
# 累计盈亏曲线（元）：零轴上下分别填红/绿，标出买卖点。
# ---------------------------------------------------------------------------
_PNL_CSS = _COMP_BASE_CSS + r"""
.pnl-top{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:12px 0 2px}
.pnl-val{font-size:26px;font-weight:650;letter-spacing:-.6px;font-variant-numeric:tabular-nums}
.pnl-val.up{color:#C52828}.pnl-val.down{color:#16703B}.pnl-val.flat{color:#475569}
.pnl-sub{font-size:12px;color:#475569}
#chart{display:block;width:100%;touch-action:pan-y;cursor:grab;user-select:none}
#tip{width:auto;min-width:172px;max-width:min(280px,calc(100% - 8px))}
@media(max-width:520px){.pnl-val{font-size:23px}}
"""

_PNL_TPL = r"""<style>__CSS____HEAD_CSS__</style>
<div id="wrap" aria-busy="false">
__HEAD_BLOCK__
<div class="pnl-top"><span class="pnl-val" id="last">—</span><span class="pnl-sub" id="lastsub"></span></div>
<div class="controls"><div id="range-controls" role="group" aria-label="常用区间">__BTNS__</div></div>
<svg id="chart" role="img" aria-label="累计盈亏曲线，可悬停查看每天的数" tabindex="0"></svg>
<div class="state-line"><span id="selection"></span><span class="date-line"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5" width="16" height="15" rx="2" fill="none"/><path d="M8 3v5m8-5v5M4 10h16"/></svg><span id="range"></span></span></div>
<div id="tip"></div>
</div>
<script>
(() => {
  const D = __DATA__;__TIP_JS__
  const wrap = document.getElementById('wrap'), svg = document.getElementById('chart');
  const tip = document.getElementById('tip'), elLast = document.getElementById('last');
  const elSub = document.getElementById('lastsub'), elSel = document.getElementById('selection');
  const elRange = document.getElementById('range');
  const STORE = D.store || 'awPnl.fund';
  const memo = (() => { try { return JSON.parse(localStorage.getItem(STORE) || '{}'); } catch (e) { return {}; } })();
  const R = D.ranges, V = D.values, DATES = D.dates, n = V.length;
  let cur = R[memo.range] ? memo.range : D.defaultRange;
  if (!R[cur]) cur = '全部';
  const H = D.height, L = 64, RT = 14, T = 12, B = 26;
  let start = 0, count = 0, W = 0, PW = 0, hover = -1, frame = 0;
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const fmt = v => {
    const a = Math.abs(v);
    const s = a >= 10 ? Math.round(a).toLocaleString('en-US') : (a === 0 ? '0' : a.toFixed(1));
    return (v < 0 ? '-' : '') + '¥' + s;
  };
  const fmtFull = v => (v < 0 ? '-' : '+') + '¥' + Math.abs(v).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  // plain = 「账户总资产」这种只有大小、没有正负的数：不带 +、不染红、区间变化说「增加/减少」
  const PLAIN = D.area === false;
  const plainFull = v => '¥' + Math.abs(v).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const esc = s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const idxOf = new Map(); DATES.forEach((d, i) => { idxOf.set(d, i); });
  const requestDraw = () => { if (!frame) frame = requestAnimationFrame(() => { frame = 0; draw(); }); };

  // 当前视窗（start/count）与「点了哪个区间按钮」（cur）分开管理：拖动或缩放之后 cur 置空，
  // 状态行显示「自选区间」、区间按钮全部取消选中 —— 与净值走势图同一套口径。
  let lastLabel = cur;
  function paint() {
    const last = clamp(start + count - 1, 0, n - 1);
    // 「全部」按 0 起算，不按第一个观测点起算：累计盈亏的第一天本身就带着浮盈
    // （成本价和当天净值不一样），从首点算会写出一句「持有以来 · 没有变化」，
    // 和上面那个 +¥267 的大数字直接打架。有区间按钮时才比「区间内的变化」。
    const base = PLAIN ? V[start] : (cur === '全部' ? 0 : V[start]);
    const delta = (V[last] - base);
    const head = cur ? (cur === '全部' ? (PLAIN ? '建仓以来' : '持有以来') : cur) : '自选区间';
    if (PLAIN) {
      // 总资产没有「盈利」这种说法：只说这段时间多了还是少了多少
      elSel.textContent = head + ' · ' + (Math.abs(delta) < .005 ? '没有变化'
        : (delta > 0 ? '增加 ' : '减少 ') + fmt(Math.abs(delta)));
    } else {
      elSel.textContent = head + ' · ' + (Math.abs(delta) < .005 ? '没有变化'
        : (delta > 0 ? '盈利 ' : '亏损 ') + fmt(Math.abs(delta)));
    }
    elSel.style.color = delta > .005 ? '#C52828' : (delta < -.005 ? '#16703B' : '#475569');
    elRange.textContent = DATES[start] + ' — ' + DATES[last];
    document.querySelectorAll('[data-range]').forEach(b =>
      b.setAttribute('aria-pressed', String(!!cur && b.dataset.range === cur)));
    hover = -1; hideTip(); requestDraw();
  }
  function apply(label) {
    if (!R[label]) return;
    lastLabel = label;
    cur = label;
    start = clamp(R[label].start, 0, Math.max(0, n - R[label].count));
    count = clamp(Math.max(1, R[label].count), Math.min(2, n), Math.max(1, n));
    paint();
    try { localStorage.setItem(STORE, JSON.stringify({ range: label })); } catch (e) {}
  }
  // 自由视窗：拖动平移、滚轮平移、⌘/Ctrl 缩放都走这里；cur 一律置空
  function update(nextStart, nextCount) {
    if (!n) return;
    const lo = Math.min(2, n), hi = Math.max(1, n);
    const c = clamp(Math.round(nextCount), lo, hi);
    const s = clamp(Math.round(nextStart), 0, Math.max(0, n - c));
    if (c === count && s === start && cur === null) return;
    count = c; start = s; cur = null; paint();
  }
  function zoom(factor, px) {
    if (!PW || !count) return;
    const f = clamp((px - L) / PW, 0, 1), anchor = start + f * (count - 1);
    const next = clamp(count * factor, Math.min(2, n), Math.max(1, n));
    update(anchor - f * (next - 1), next);
  }
  function hideTip() { tip.style.display = 'none'; }
  // 刻度步长落在 1/2/5×10ⁿ 这种整数上（￥-32 / ￥78 这种刻度看着很脏）；
  // 只画在数据范围内的刻度，不为了凑整把上下限撑开——否则曲线会缩在中间一小条
  function niceStep(raw) {
    const mag = Math.pow(10, Math.floor(Math.log10(raw || 1)));
    const norm = raw / mag;
    return (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
  }

  function draw() {
    const rect = wrap.getBoundingClientRect();
    W = Math.max(320, Math.round(rect.width || 640));
    PW = W - L - RT;
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    svg.setAttribute('height', H);
    const top = T, bot = H - B, avail = bot - top;
    // 折线图首尾要贴边（点位在格子中心是给柱状图用的，两点数据会缩在中间一小段）
    const xs = i => count <= 1 ? L + PW / 2 : L + (i - start) * PW / (count - 1);
    let lo = PLAIN ? Infinity : 0, hi = PLAIN ? -Infinity : 0, seen = 0;
    for (let i = start; i < start + count && i < n; i++) {
      const v = V[i];
      if (!Number.isFinite(v)) continue;
      if (v < lo) lo = v; if (v > hi) hi = v; seen++;
    }
    if (!seen) { svg.innerHTML = ''; return; }
    // 总资产不从 0 起算（否则 50 万的曲线会被压成贴着顶的一条直线），
    // 全是同一个数时（刚建仓、一分没动）按 1% 撑开，免得刻度挤成 ¥500,183 / ¥500,184
    if (PLAIN && !(hi > lo)) { const c = hi || 1; lo = c - Math.abs(c) * .01; hi = c + Math.abs(c) * .01; }
    const pad = (hi - lo) * .10 || 1;
    lo -= pad; hi += pad;
    const step = niceStep((hi - lo) / 4), ticks = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-6; v += step) ticks.push(v);
    const ys = v => top + (hi - v) / (hi - lo) * avail;
    const y0 = clamp(ys(0), top, bot);
    // 不再给零轴上下填红/绿渐变（2026-11-08 用户：「这个深色是干啥的，莫名其妙」）：
    // 那片色块在下跌段会糊成一大团墨绿，又和净值走势图（纯折线、无填充）不是一套。
    // 正负靠零轴虚线 + 左侧刻度 + 顶部大数字的红绿就能读，填充属于纯装饰。
    let g = '';
    // 横向网格 + 左侧刻度（0 那条单独加深）
    ticks.forEach(v => {
      const Y = ys(v);
      g += '<line x1="' + L + '" x2="' + (W - RT) + '" y1="' + Y.toFixed(1) + '" y2="' + Y.toFixed(1)
         + '" stroke="#EEF2F7" stroke-width="1"/>';
      g += '<text x="' + (L - 8) + '" y="' + (Y + 4).toFixed(1) + '" text-anchor="end" font-size="10" fill="#475569">'
         + esc(fmt(v)) + '</text>';
    });
    // 零轴虚线：只有「盈亏」这种有正负的数才画。总资产永远是正的，
    // 画一条贴着底的 0 会让曲线像悬在半空
    if (D.area !== false) {
      g += '<line x1="' + L + '" x2="' + (W - RT) + '" y1="' + y0.toFixed(1) + '" y2="' + y0.toFixed(1)
         + '" stroke="#CBD5E1" stroke-width="1" stroke-dasharray="4 4"/>';
    }
    // 清仓日竖线（已清仓的基金才有）：标记「这天之后就不再拿着了」，之后是平的余额
    if (D.mark) {
      const mi = idxOf.get(D.mark);
      if (mi !== undefined && mi >= start && mi < start + count) {
        const X = xs(mi).toFixed(1);
        g += '<line x1="' + X + '" x2="' + X + '" y1="' + top + '" y2="' + bot
           + '" stroke="#94A3B8" stroke-width="1" stroke-dasharray="4 3"/>';
        g += '<text x="' + clamp(xs(mi) + 6, L + 4, W - RT - 46).toFixed(1) + '" y="' + (top + 11) +
             '" font-size="10.5" fill="#64748B">' + esc(D.markLabel || '清仓') + '</text>';
      }
    }
    // 折线：只用折线，不填色（与净值走势图同一套口径，见 CLAUDE.md「H5 图表曲线规范」）
    let d = '';
    for (let i = start; i < start + count && i < n; i++) {
      const v = V[i];
      if (!Number.isFinite(v)) continue;
      d += (d ? 'L' : 'M') + xs(i).toFixed(1) + ' ' + ys(v).toFixed(1);
    }
    if (d) {
      g += '<path d="' + d + '" fill="none" stroke="#1E40AF" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>';
    }
    // 每个观测点都画圆点，半径随步长自适应 —— 与买卖点图同一套规则（CLAUDE.md「数据点标记」）。
    // 原来只在 count<=20 时画、半径固定 2.6 带白描边，和买卖点图是两套，已统一。
    const dotR = Math.min(3.5, Math.max(1, PW / Math.max(1, count) * .12));
    for (let i = start; i < start + count && i < n; i++) {
      if (!Number.isFinite(V[i])) continue;
      g += '<circle cx="' + xs(i).toFixed(1) + '" cy="' + ys(V[i]).toFixed(1)
         + '" r="' + dotR.toFixed(1) + '" fill="#1E40AF"/>';
    }
    // 买卖点：与净值走势图同一套标记 —— 买点上方挂红「买」、卖点下方挂绿「卖」小徽标（+ 同色定位点）。
    // 关键：定位点必须压在真实数据点上，只有徽标本身在贴边时内收；内收后用一条细连线接回定位点，
    // 否则首末期会出现「徽标和圆点对不齐」（2026-11-08 用户指出的就是这种）。
    (D.trades || []).forEach(t => {
      const i = idxOf.get(t.date);
      if (i === undefined || i < start || i >= start + count) return;
      const v = V[i];
      if (!Number.isFinite(v)) return;
      const buy = t.side === '买入', fill = buy ? '#C52828' : '#16703B';
      const X = clamp(xs(i), L, W - RT), Y = ys(v);
      const bx = clamp(X - 10.5, L + 1, W - RT - 22);
      const by = clamp(buy ? Y - 8 - 15 : Y + 8, top + 1, bot - 16);
      const cxB = bx + 10.5, edgeY = buy ? by + 15 : by;
      g += '<g data-mark="' + (buy ? 'buy' : 'sell') + '">'
        + (Math.abs(cxB - X) > .5
           ? '<line x1="' + cxB.toFixed(1) + '" y1="' + edgeY.toFixed(1) + '" x2="' + X.toFixed(1) + '" y2="' + Y.toFixed(1) + '" stroke="' + fill + '" stroke-width="1" opacity=".45"/>'
           : '')
        + '<circle cx="' + X.toFixed(1) + '" cy="' + Y.toFixed(1) + '" r="3.6" fill="' + fill + '" stroke="#fff" stroke-width="1.4"/>'
        + '<rect x="' + bx.toFixed(1) + '" y="' + by.toFixed(1) + '" width="21" height="15" rx="4.5" fill="' + fill + '" stroke="#fff" stroke-width="1.4"/>'
        + '<text x="' + cxB.toFixed(1) + '" y="' + (by + 11.1).toFixed(1)
        + '" text-anchor="middle" font-size="10" font-weight="600" fill="#fff">' + (buy ? '买' : '卖') + '</text></g>';
    });
    // 横轴日期（首 / 中 / 尾三档，手机上只留首尾）
    const rawTicks = W < 460 ? [start, start + count - 1]
      : [start, Math.round(start + (count - 1) / 2), start + count - 1];
    const xTicks = [...new Set(rawTicks.map(i => clamp(i, 0, n - 1)))];   // 只有两三天时首中尾会重复
    xTicks.forEach((i, k) => {
      if (i < 0 || i >= n) return;
      const anchor = k === 0 ? 'start' : (k === xTicks.length - 1 ? 'end' : 'middle');
      const X = k === 0 ? L : (k === xTicks.length - 1 ? W - RT : xs(i));
      g += '<text x="' + X.toFixed(1) + '" y="' + (H - 7) + '" text-anchor="' + anchor + '" font-size="10" fill="#475569">' + esc(DATES[i]) + '</text>';
    });
    if (hover >= start && hover < start + count && Number.isFinite(V[hover])) {
      const X = xs(hover), Y = ys(V[hover]);
      g += '<line x1="' + X.toFixed(1) + '" x2="' + X.toFixed(1) + '" y1="' + top + '" y2="' + bot + '" stroke="#CBD5E1" stroke-dasharray="3 3"/>';
      g += '<circle cx="' + X.toFixed(1) + '" cy="' + Y.toFixed(1) + '" r="3.5" fill="#1E40AF" stroke="#fff" stroke-width="1.5"/>';
    }
    svg.innerHTML = g;
  }

  function showTip(i, clientX, clientY) {
    if (!Number.isFinite(V[i])) { hideTip(); return; }
    const prev = i > 0 && Number.isFinite(V[i - 1]) ? V[i - 1] : null;
    const dChg = prev === null ? null : V[i] - prev;
    const colOf = v => (PLAIN ? '#0F172A' : (v > 0 ? '#C52828' : v < 0 ? '#16703B' : '#475569'));
    const money = v => (v >= 0 ? '+' : '-') + '¥' + Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    // 结构与净值走势图共用 tipHead / tipRow（CLAUDE.md「tooltip」）：金额曲线报
    // 累计盈亏 / 当日变动 / 每笔成交。原来是大数字打头、日期当标签用，两套样子并存。
    tip.innerHTML = tipHead(DATES[i])
      + tipRow('累计盈亏', esc(PLAIN ? plainFull(V[i]) : fmtFull(V[i])), '', colOf(V[i]))
      + (dChg === null ? '' : tipRow('当日变动', dChg === 0 ? '¥0.00' : money(dChg), '', colOf(dChg)))
      + (D.trades || []).filter(t => t.date === DATES[i])
          .map(t => tipRow(esc(t.side), esc(t.label), t.side === '买入' ? '#C52828' : '#16703B')).join('');
    tip.style.display = 'block';
    // 定位必须按实测宽高夹紧：原来写死 W-250 / height-90，窄屏上「买入 3,474.65 份 @ 1.4925」
    // 这类长描述 + 四行内容会把提示顶出右/下边界被裁（CLAUDE.md「提示框定位」）。
    const wrapRect = wrap.getBoundingClientRect();
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    const x = clientX - wrapRect.left, y = clientY - wrapRect.top;
    const preferLeft = x + 14 + tw <= wrapRect.width - 4 ? x + 14 : x - tw - 14;
    tip.style.left = clamp(preferLeft, 4, Math.max(4, wrapRect.width - tw - 4)) + 'px';
    const preferTop = y + 12 + th <= wrapRect.height - 4 ? y + 12 : y - th - 12;
    tip.style.top = clamp(preferTop, 4, Math.max(4, wrapRect.height - th - 4)) + 'px';
  }

  // ---- 时间轴操作：拖动平移 / 水平滚轮平移 / ⌘·Ctrl 滚轮缩放 / 双击复位 ----
  // 这张图原来只有区间按钮，左右根本滑不动，和净值走势图不是一套（2026-11-08 用户指出）。
  // 规则见 CLAUDE.md「左右滑动与状态行」：全站只保留这一套操作，垂直滚动一律不拦、不平移。
  let dragging = null;
  const localX = e => e.clientX - svg.getBoundingClientRect().left;
  const indexAt = px => clamp(Math.round(start + (px - L) / (PW || 1) * Math.max(1, count - 1)),
                              start, Math.max(start, start + count - 1));
  svg.addEventListener('pointerdown', e => {
    if (e.button !== 0 || !PW || !count) return;
    const px = localX(e);
    if (px < L || px > W - RT) return;
    dragging = { id: e.pointerId, x: e.clientX, start, count, moved: false };
    svg.setPointerCapture(e.pointerId); svg.classList.add('dragging');
  });
  svg.addEventListener('pointermove', e => {
    if (dragging) {
      const delta = e.clientX - dragging.x;
      if (Math.abs(delta) > 3) dragging.moved = true;
      if (dragging.moved) update(dragging.start - delta * (dragging.count - 1) / PW, dragging.count);
      return;
    }
    if (!PW) return;
    const px = localX(e);
    if (px < L || px > W - RT) { if (hover !== -1) { hover = -1; requestDraw(); } hideTip(); return; }
    const i = indexAt(px);
    if (i !== hover) { hover = i; requestDraw(); }
    showTip(i, e.clientX, e.clientY);
  });
  function release(e) {
    if (!dragging) return;
    // 没拖动 = 点了一下：把提示留在这一点（触屏没有 hover，松手就消失等于看不到）
    if (!dragging.moved && e.type === 'pointerup') {
      const i = indexAt(localX(e));
      hover = i; requestDraw(); showTip(i, e.clientX, e.clientY);
    }
    if (svg.hasPointerCapture(e.pointerId)) svg.releasePointerCapture(e.pointerId);
    dragging = null; svg.classList.remove('dragging');
  }
  svg.addEventListener('pointerup', release);
  svg.addEventListener('pointercancel', release);
  svg.addEventListener('pointerleave', e => {
    if (e.pointerType === 'mouse' && !dragging) { hover = -1; hideTip(); requestDraw(); }
  });
  svg.addEventListener('wheel', e => {
    if (!PW || !count) return;
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      zoom(Math.exp(clamp(e.deltaY, -400, 400) * .003), localX(e));
      return;
    }
    // 只有水平滚动才平移时间轴；上下滑动页面（deltaY 为主）原样交给页面滚动，图表不动、也不 preventDefault
    const dx = e.deltaX || 0, dy = e.deltaY || 0;
    if (Math.abs(dx) <= Math.abs(dy) || Math.abs(dx) < 1) return;
    e.preventDefault();
    update(start + dx * (e.deltaMode === 1 ? 16 : 1) * (count - 1) / PW, count);
  }, { passive: false });
  svg.addEventListener('dblclick', () => apply(R[lastLabel] ? lastLabel : (cur || '全部')));

  document.querySelectorAll('[data-range]').forEach(b => { b.onclick = () => apply(b.dataset.range); });

  // 顶部大数字 = 最新一笔的累计盈亏（持有以来），与上面详情卡里的「持有收益」不是一回事；
  // 总资产模式只报「现在有多少」，不带 +、不染红
  const lastV = V[n - 1];
  if (Number.isFinite(lastV)) {
    elLast.textContent = PLAIN ? plainFull(lastV) : fmtFull(lastV);
    elLast.className = 'pnl-val ' + (PLAIN ? 'flat' : (lastV > 0 ? 'up' : lastV < 0 ? 'down' : 'flat'));
    elSub.textContent = D.sub || '持有以来累计（已含卖出落袋的部分）';
  }
  apply(cur);
  new ResizeObserver(() => requestDraw()).observe(wrap);
})();
</script>"""


def pnl_chart_html(series, trades=None, height=200, store="awPnl.fund",
                   default_range="全部", heading="累计盈亏",
                   mark=None, mark_label="清仓", area=True, sub="", aria=""):
    """单序列金额曲线（元）：标出这只基金的买卖点，可拖动/缩放。"""
    dates = series.index.strftime("%Y/%m/%d").tolist()
    values = [round(float(v), 2) for v in series.values]
    # 区间标签与走势图完全一致（8 个，顺序取自 _TREND_RANGES）：
    # 同一个页面里两张曲线的「时间段」按钮不能一套 5 个一套 8 个（CLAUDE.md 统一区间标签）
    labels = list(_TREND_RANGES)
    ranges = {}
    for lb in labels:
        i = int(_trend_window_start(series, _TREND_RANGES[lb]))
        ranges[lb] = {"start": i, "count": max(1, len(series) - i)}
    if default_range not in ranges:
        default_range = labels[-1]
    btns = "".join(f'<button data-range="{lb}" aria-pressed="{str(lb == default_range).lower()}">{lb}</button>'
                   for lb in labels)
    payload = json.dumps({"dates": dates, "values": values, "trades": trades or [],
                          "ranges": ranges, "height": int(height), "store": store,
                          "defaultRange": default_range, "area": bool(area), "sub": sub or "",
                          "aria": aria or "",
                          "mark": mark or "", "markLabel": mark_label}, ensure_ascii=False,
                         allow_nan=False).replace("<", "\\u003c")
    return (_PNL_TPL.replace("__CSS__", _PNL_CSS)
            .replace("__TIP_JS__", _TIP_JS)
            .replace("__HEAD_CSS__", "" if heading else ".controls{margin-top:2px}")
            .replace("__HEAD_BLOCK__", _chart_head_block(heading, "M3 17l5-6 4 3 5-7 4 4"))
            .replace("__BTNS__", btns).replace("__DATA__", payload))
