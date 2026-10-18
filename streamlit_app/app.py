"""再平衡调仓工具 — Streamlit Web 界面.

用法: streamlit run streamlit_app/app.py
"""
import sys
from pathlib import Path
import json
from html import escape as html_escape

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
import pandas as pd
from datetime import date
import numpy as np
import altair as alt
import streamlit.components.v1 as components

from allweather.rebalance import (
    compute_signal_states,
    compute_target_weights,
    apply_signal_overrides,
    STRATEGIES,
    ETF_META,
)
from allweather.sim_account import load_acct, save_acct, replay, stats as acct_stats
from allweather.config import (
    DATA_DIR,
    GOLD_DIP_THRESHOLD,
    HS300_DIP_THRESHOLD,
    HS300_DIP_SMA,
    HS300_PB_ENTRY,
    HS300_PE_EXIT,
    SP500_TREND_WINDOW,
)

st.set_page_config(page_title="全天候再平衡", page_icon="🌤️", layout="wide")

st.markdown("""<style>
/* ========== 设计变量 ========== */
:root{
  --ink:#111827; --sub:#6b7280; --line:#e8ebf2; --card:#ffffff;
  --bg:#f6f7fb; --brand:#ff4b4b; --radius:16px;
  --red:#d14b4b; --green:#1a9e6b;
  --shadow:0 1px 2px rgba(16,24,40,.04), 0 4px 14px rgba(16,24,40,.04);
}

/* ========== 基础排版 ========== */
html, body, [data-testid="stAppViewContainer"]{
  font-family:-apple-system,BlinkMacSystemFont,"SF Pro SC","PingFang SC","Segoe UI",sans-serif;
  color:var(--ink);
}
[data-testid="stAppViewContainer"]{ background:var(--bg); }
[data-testid="stHeader"]{ background:transparent; }
.block-container{ padding-top:1.1rem; padding-bottom:3rem; max-width:1180px; }
h1,h2,h3{ letter-spacing:-.3px; color:var(--ink); }
hr{ border-color:#eef1f6; }
.up{ color:var(--red); } .down{ color:#1a9e6b; }

/* ========== 顶部 Hero ========== */
.hero{
  display:flex; align-items:flex-end; justify-content:space-between;
  gap:14px; flex-wrap:wrap; padding:4px 2px 16px;
}
.hero-title{ font-size:26px; font-weight:700; letter-spacing:-.8px; margin:0; }
.hero-sub{ font-size:12.5px; color:var(--sub); margin-top:4px; }
.mini-title{ font-size:12px; color:var(--sub); margin:2px 0 -6px; }

/* ========== 基金详情页头部 ========== */
.fund-head{
  background:var(--card); border:1px solid var(--line); border-radius:18px;
  padding:18px 20px 16px; box-shadow:var(--shadow); margin:6px 0 14px;
}
.fh-top{ display:flex; align-items:center; gap:10px; }
.fh-name{ font-size:17px; font-weight:650; letter-spacing:-.3px; }
.fh-code{ font-size:12px; color:var(--sub); font-variant-numeric:tabular-nums; }
.fh-tag{
  font-size:11px; color:#374151; background:#f2f4f8; border-radius:999px;
  padding:2px 9px; border:1px solid #e8ebf2;
}
.fh-price{ display:flex; align-items:baseline; gap:12px; margin-top:12px; }
.fh-price .px{ font-size:32px; font-weight:700; letter-spacing:-1.2px; line-height:1; }
.fh-price .chg{ font-size:15px; font-weight:650; }
.fh-price .chg.up{ color:var(--red); }
.fh-price .chg.down{ color:#1a9e6b; }
.fh-price .fh-date{ margin-left:8px; }
.fh-date{ font-size:12px; color:var(--sub); margin-left:auto; }

/* 一行统计文字 */
.stats-row{
  display:flex; flex-wrap:wrap; gap:8px 30px; padding:16px 4px 2px;
  font-size:12px; color:var(--sub);
}
.stats-row .item b{
  display:block; font-size:15.5px; color:var(--ink); font-weight:600;
  margin-top:3px; font-variant-numeric:tabular-nums;
}

/* 阶段涨幅网格 */
.grid4{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-top:10px; }
.grid4 .cell{
  background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:11px 13px;
}
.grid4 .cell .k{ font-size:11.5px; color:var(--sub); }
.grid4 .cell .v{ font-size:15px; font-weight:600; margin-top:3px; font-variant-numeric:tabular-nums; }
.stats-row .item b.up, .grid4 .cell .v.up{ color:var(--red); }
.stats-row .item b.down, .grid4 .cell .v.down{ color:#1a9e6b; }

/* 阶段涨跌幅胶囊 */
.stage{ display:flex; flex-wrap:wrap; gap:8px; margin:12px 0 2px; }
.stage>span{
  background:var(--card); border:1px solid var(--line); border-radius:999px;
  padding:6px 13px; font-size:12.5px; font-variant-numeric:tabular-nums;
}
.chips{ display:flex; gap:8px; flex-wrap:wrap; }
.chip{
  display:inline-flex; align-items:center; gap:6px; padding:5px 11px;
  border-radius:999px; background:var(--card); border:1px solid var(--line);
  font-size:12px; color:#374151; box-shadow:0 1px 1px rgba(16,24,40,.03);
}
.chip .dot{ width:7px; height:7px; border-radius:50%; background:#22c55e; }
.chip .dot.warn{ background:#f59e0b; }

/* ========== Tabs（Streamlit 1.66 是自定义 tab，不是 baseweb） ========== */
[data-testid="stTabs"] [role="tab"]{
  padding:10px 2px 12px; margin-right:26px; font-size:14px; color:var(--sub);
  letter-spacing:-.1px; white-space:nowrap; transition:color .15s ease;
}
[data-testid="stTabs"] [role="tab"]:hover{ color:var(--ink); }
[data-testid="stTabs"] [role="tab"][aria-selected="true"]{
  color:var(--ink) !important; font-weight:650;
}
[data-testid="stTabs"] [role="tablist"]{
  gap:0; border-bottom:1px solid var(--line); overflow-x:auto; scrollbar-width:none;
}
[data-testid="stTabs"] [role="tablist"]::-webkit-scrollbar{ display:none; }
[data-testid="stTabs"] [data-testid="stTabPanel"]{ padding-top:16px; }

/* ========== 卡片容器（st.container(border=True)） ========== */
[data-testid="stVerticalBlockBorderWrapper"]{
  background:var(--card); border:1px solid var(--line) !important;
  border-radius:var(--radius); box-shadow:var(--shadow);
}

/* ========== 指标卡 ========== */
[data-testid="stMetric"]{
  background:var(--card); border:1px solid var(--line); border-radius:14px;
  padding:13px 15px; box-shadow:var(--shadow);
}
[data-testid="stMetricLabel"] p{ font-size:12px !important; color:var(--sub) !important; }
[data-testid="stMetricValue"]{ font-size:23px !important; font-weight:650; }
[data-testid="stMetricDelta"]{ font-size:12px !important; }

/* ========== 按钮 ========== */
.stButton>button, .stDownloadButton>button{
  border-radius:10px; border:1px solid var(--line); font-weight:500;
  padding:.45rem .95rem; transition:all .15s ease;
}
.stButton>button:hover{ border-color:#cfd5e2; transform:translateY(-1px); }
.stButton>button[kind="primary"]{
  background:var(--ink); border-color:var(--ink); color:#fff;
}

/* ========== 表格 ========== */
[data-testid="stDataFrame"]{
  border:1px solid var(--line); border-radius:12px; overflow:hidden;
}

/* ========== 提示条 ========== */
[data-testid="stAlert"]{ border-radius:12px; border:1px solid var(--line); }

/* ========== 侧边栏（品牌化分组重排） ========== */
[data-testid="stSidebar"]{ background:var(--card); border-right:1px solid var(--line); }
[data-testid="stSidebar"] .block-container{ padding:1.1rem 1.05rem 2rem; }
.sb-brand{
  display:flex; align-items:center; gap:9px; margin:2px 0 18px;
  font-size:15px; font-weight:650; letter-spacing:-.2px; color:var(--ink);
}
.sb-brand .mark{
  width:22px; height:22px; border-radius:7px; display:inline-flex; align-items:center; justify-content:center;
  background:linear-gradient(135deg,#ffd9a0,#ffb199); font-size:12px;
}
.sb-label{ font-size:11px; color:var(--sub); letter-spacing:.5px; margin:14px 0 3px; }
.sb-divider{ border-top:1px solid var(--line); margin:18px 0 12px; }
.sb-status{
  display:inline-flex; align-items:center; gap:7px; font-size:12px; padding:5px 10px;
  border-radius:999px; border:1px solid var(--line); background:#f8fafc; color:#374151;
}
.sb-status .dot{ width:7px; height:7px; border-radius:50%; background:#22c55e; }
.sb-status.warn .dot{ background:#f59e0b; }
.sb-status.err .dot{ background:#ef4444; }
/* 单选组做成“列表项”，选中项浅底高亮 */
[data-testid="stSidebar"] [role="radiogroup"]{ gap:4px; }
[data-testid="stSidebar"] [role="radiogroup"] label{
  border:1px solid transparent; border-radius:9px; padding:6px 10px;
  font-size:13px; transition:background .12s; cursor:pointer;
}
[data-testid="stSidebar"] [role="radiogroup"] label:hover{ background:#f4f6fa; }
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked){
  background:#f0f2f7; border-color:#e4e8f0; font-weight:600;
}
[data-testid="stSidebar"] [data-testid="stButton"]>button{
  width:100%; justify-content:flex-start; color:var(--sub); font-weight:500;
}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"]{ font-size:11px; margin-top:6px; }

/* ========== 自定义表格 ========== */
.tbl{
  width:100%; border-collapse:separate; border-spacing:0; font-size:13px;
  background:var(--card); border:1px solid var(--line); border-radius:12px;
  overflow:hidden; box-shadow:var(--shadow);
}
.tbl th{
  background:#fafbfd; color:var(--sub); font-weight:500; font-size:12px;
  text-align:left; padding:9px 12px; border-bottom:1px solid var(--line);
}
.tbl td{ padding:9px 12px; border-bottom:1px solid #f2f4f8; }
.tbl tbody tr:last-child td{ border-bottom:none; }
.tbl tr.total td{ font-weight:650; background:#fafbfd; }
.tbl td.num, .tbl th.num{ text-align:right; font-variant-numeric:tabular-nums; }
.tbl .up{ color:var(--red); } .tbl .down{ color:#1a9e6b; }
.tbl .muted{ color:var(--sub); }
/* 宽表横向滚动容器（月度矩阵） */
.tblwrap{ overflow-x:auto; border-radius:12px; box-shadow:var(--shadow); }
.tblwrap .tbl{ border-radius:12px; }
.tbl.wide{ min-width:940px; }
.tbl.wide th:first-child, .tbl.wide td:first-child{
  position:sticky; left:0; background:var(--card); z-index:1;
}
.tbl.wide th:first-child{ background:#fafbfd; }

/* ========== 基金走势页：含阶段数字的概览 / 走势分析 ========== */
.st-key-trend_head, .st-key-trend_chart{
  background:var(--card); border:1px solid var(--line); border-radius:16px;
  padding:24px !important; margin-bottom:24px;
}
.st-key-trend_chart{container-type:inline-size}
.st-key-trend_chart iframe,.st-key-trend_chart [data-testid="stElementContainer"]:has(>iframe){height:800px !important;flex-basis:800px !important}
@container(max-width:650px){
  .st-key-trend_chart iframe,.st-key-trend_chart [data-testid="stElementContainer"]:has(>iframe){height:850px !important;flex-basis:850px !important}
}
@container(max-width:420px){
  .st-key-trend_chart iframe,.st-key-trend_chart [data-testid="stElementContainer"]:has(>iframe){height:940px !important;flex-basis:940px !important}
}
.st-key-trend_head [data-testid="stHorizontalBlock"]{align-items:center; gap:20px}
.fund-head.flat{border:none; box-shadow:none; padding:0; margin:0; background:transparent}
.fh-top,.fh-price{flex-wrap:wrap; row-gap:8px}
.fh-price-label,.fh-price small{font-size:12px; font-weight:400; color:var(--sub)}
.fh-price .fh-date{margin-left:0}
.sec-head{display:flex; align-items:center; flex-wrap:wrap; gap:12px; margin:0 0 16px}
.sec-head .t{font-size:17px; font-weight:600; color:var(--ink)}
.sec-head .r{margin-left:auto; font-size:12px; color:var(--sub)}
.sec-note{font-size:12px; color:var(--sub); line-height:1.8; margin-top:12px}
.stage-summary{border-top:1px solid var(--line);margin-top:16px;padding-top:14px}
.stage-summary-title{font-size:12px;font-weight:400;color:var(--sub);margin-bottom:10px}
.stage-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.stage-metric{min-width:0;cursor:default}
.stage-label{display:block;font-size:12px;color:var(--sub);line-height:1.6}
.stage-return{display:block;margin-top:4px;font-size:22px;font-weight:600;line-height:1.4;
  font-variant-numeric:tabular-nums;white-space:nowrap;letter-spacing:-.3px}
.stage-return.up{color:var(--red)}.stage-return.down{color:var(--green)}
.stage-return.neutral{color:var(--sub)}
@media(max-width:600px){
  .st-key-trend_head,.st-key-trend_chart{padding:14px !important;margin-bottom:18px}
  .stage-metrics{gap:6px}.stage-return{font-size:16px;letter-spacing:-.4px}
  .stage-label{font-size:11px}
  .fh-price .px{font-size:28px}.fh-price .chg{font-size:14px}
}

/* ========== 信号卡片 ========== */
.sig{
  display:flex; align-items:center; gap:14px; background:var(--card);
  border:1px solid var(--line); border-left:4px solid var(--brand);
  border-radius:12px; padding:12px 15px; margin-bottom:8px; box-shadow:var(--shadow);
}
.sig .main{ flex:1; min-width:0; }
.sig .t{ font-weight:600; font-size:14px; }
.sig .m{ font-size:11.5px; color:var(--sub); margin-top:2px; }
.sig .side{ font-size:12.5px; color:#374151; white-space:nowrap; text-align:right; }
.sig .side b{ display:block; font-size:11px; color:var(--sub); font-weight:400; margin-bottom:1px; }
.sig.calm{ border-left-color:#22c55e; }
.sig.off{ border-left-color:#cbd5e1; opacity:.72; }

/* ========== 隐藏不需要的 UI ========== */
[data-testid="stAppDeployButton"]{ display:none; }
[data-testid="stDeployButton"]{ display:none; }
[data-testid="stDecoration"]{ display:none; }
[data-testid="stStatusWidget"]{ display:none; }
#MainMenu{ visibility:hidden; }
/* 注意：不要隐藏 stHeader / stToolbar 容器，侧边栏"展开"按钮在里面 */
</style>""", unsafe_allow_html=True)

# ============================================================
# 信号 → 操作 映射表
# ============================================================
_BENCH_COL = {
    "B-RP": "V3-B 风险平价(20d)_100% RP",
    "B-Con": "V3-B 保守增强(20d)_100% RP",
    "V3c": "V3c 多元_100% RP",
}
_UP, _DOWN, _BRAND, _SUB = "#d14b4b", "#1a9e6b", "#ff4b4b", "#6b7280"


def _cn_date(v):
    """日期 → 2026年10月16日"""
    t = pd.Timestamp(v)
    return f"{t.year}年{t.month}月{t.day}日"


@st.cache_data(ttl=300, show_spinner=False)
def _bench_curve(strategy_key):
    """读 output/nv_curves.csv 里对应策略的净值（全历史）。"""
    p = PROJECT_ROOT / "output" / "nv_curves.csv"
    col = _BENCH_COL.get(strategy_key)
    if not p.exists() or not col:
        return None
    try:
        df = pd.read_csv(p, index_col=0, parse_dates=True)
        if col not in df.columns:
            return None
        return df[col].dropna()
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def _asset_series(asset):
    """读取单只基金自己的完整历史（不受多资产公共区间限制）。"""
    fname = _LIVE_ASSETS.get(asset)
    if not fname:
        return None
    fp = DATA_DIR / f"{fname}.csv"
    if not fp.exists():
        return None
    try:
        df = pd.read_csv(fp, parse_dates=["date"], index_col="date")
        return df["close"].dropna()
    except Exception:
        return None


def _scroll_chart_html(labels, values, win, height=540, rets=None, revision=0, histories=None):
    """全历史数据 + 有界索引视窗；只绘制可见部分，不创建超宽画布。

    一张图三层面板，共用同一条时间轴：上方收盘价折线（含起点虚线），
    中间每个点位相对区间起点的涨跌幅柱，下方单期涨跌幅柱（涨红跌绿）。
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
    }, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    template = r"""<style>
html,body{margin:0;padding:0;background:#fff;color:#334155;font:13px/1.6 -apple-system,"PingFang SC",sans-serif}
*{box-sizing:border-box}#wrap{position:relative;width:100%}
.heading{display:flex;align-items:center;justify-content:space-between;gap:12px}
h3{margin:0;font-size:17px;font-weight:600;color:#111827;display:flex;align-items:center;gap:8px}
.icon{width:17px;height:17px;fill:none;stroke:currentColor;stroke-width:1.5;vertical-align:middle}
#updating{font-size:12px;color:#64748b;visibility:hidden}#wrap[aria-busy="true"] #updating{visibility:visible}
.controls{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-top:18px;border-bottom:1px solid #e8ebf2}
#range-controls{display:flex;gap:8px;min-width:0}
button[data-range]{font:inherit;border:0;border-bottom:2px solid transparent;border-radius:0;background:transparent;
  color:#64748b;padding:10px 12px;white-space:nowrap;cursor:pointer;min-height:40px}
button[data-range]:hover{background:#f5f7fa}
button[data-range][aria-pressed="true"]{font-weight:600;color:#111827;border-bottom-color:#111827}
button:focus-visible,select:focus-visible,#chart:focus-visible{outline:2px solid #475569;outline-offset:2px}
select{font:inherit;border:1px solid #dce1e9;border-radius:8px;background:#fff;color:#334155;padding:6px 10px;min-height:36px;cursor:pointer}
#period{margin-bottom:4px;min-width:86px}
.state-line{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin:12px 0 8px;font-size:12px;color:#64748b}
.date-line{display:flex;align-items:center;gap:6px}#selection{color:#475569}#selection[data-custom="true"]{font-weight:600}
#range{font-variant-numeric:tabular-nums}#notice{min-height:20px;font-size:12px;color:#64748b}
#chart{display:block;width:100%;touch-action:pan-y;cursor:grab;user-select:none}
#chart.dragging{cursor:grabbing}
#tip{position:absolute;pointer-events:none;background:#fff;color:#0f172a;border:1px solid #cbd5e1;
font-size:12px;line-height:1.8;padding:10px 14px;border-radius:8px;display:none;z-index:10;width:240px;max-width:calc(100% - 8px);
box-shadow:0 4px 16px #0f172a18;font-variant-numeric:tabular-nums}
#tip .tip-row{display:flex;justify-content:space-between;gap:18px}#tip .tip-label{color:#64748b}
#stats{border-top:1px solid #e8ebf2;margin-top:8px;padding:16px 0 4px}
.summary-main{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.summary-result{display:flex;align-items:baseline;gap:12px}.summary-result b{font-size:24px;font-weight:600;letter-spacing:-.5px}
.summary-prices{display:flex;gap:10px;align-items:center;font-size:13px;font-variant-numeric:tabular-nums}
.summary-prices small{color:#64748b;margin-right:4px}.summary-prices b{font-weight:500}
.amp-row{display:flex;align-items:center;gap:8px 16px;flex-wrap:wrap;margin-top:10px;color:#64748b;font-size:12px}
.amp-row b{color:#334155;font-size:14px;font-weight:600}.amp-row small{font-size:11px}
@media(max-width:520px){#range-controls{gap:0;justify-content:space-between;width:100%}
  button[data-range]{padding:8px 9px;font-size:12px}.controls{flex-wrap:wrap;gap:6px}#period{margin-left:auto}
  .state-line{font-size:11px}.summary-result b{font-size:21px}.summary-prices{flex-wrap:wrap;font-size:12px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto}}
</style>
<div id="wrap" aria-busy="false">
<div class="heading"><h3><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4v16h16M7 14l4-5 4 3 5-7"/></svg>走势分析</h3><span id="updating" role="status">正在更新</span></div>
<div class="controls"><div id="range-controls" role="group" aria-label="常用区间">
<button data-range="近1月" aria-pressed="true" title="近30个自然日">近1月</button><button data-range="近3月" aria-pressed="false">近3月</button><button data-range="近1年" aria-pressed="false">近1年</button><button data-range="今年来" aria-pressed="false">今年来</button><button data-range="全部" aria-pressed="false">全部</button>
</div><select id="period" aria-label="周期"><option value="日">日线</option><option value="月">月线</option><option value="年">年线</option></select></div>
<div class="state-line"><span id="selection" aria-live="polite"></span><span class="date-line"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5" width="16" height="15" rx="2" fill="none"/><path d="M8 3v5m8-5v5M4 10h16"/></svg><span id="range"></span></span></div>
<div id="notice" role="status"></div>
<svg id="chart" role="img" aria-label="基金历史走势，可拖动和缩放" tabindex="0"></svg>
<div id="stats"></div><div id="tip"></div>
</div>
<script>
(() => {
  const D = __CHART_DATA__;
  const svg = document.getElementById('chart'), wrap = document.getElementById('wrap');
  const tip = document.getElementById('tip'), range = document.getElementById('range');
  let period = '日', lastRange = '近1月', activeRange = lastRange, customDates = null;
  let P = D.histories[period], n = P.prices.length;
  const H = D.height, L = 64, R = 16, T = 32, B = 32, GAP = 30, minCount = 1;
  // 绘图区主次：收盘价55%、累计变化27%、单期变化18%。
  const PH = H - T - B - GAP * 2, AH = PH * .55, BH = PH * .27, CH = PH * .18;
  const bTop1 = T + AH + GAP, bTop2 = bTop1 + BH + GAP;
  let initialCount = P.windows[lastRange].count, initialStart = P.windows[lastRange].start;
  let count = initialCount, start = initialStart, W = 0, PW = 0, frame = 0;
  let dragging = null, pinned = null, hover = null;
  const periodControl = document.getElementById('period');
  for (const option of periodControl.options) option.disabled = !D.histories[option.value];
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const valid = v => v !== null && Number.isFinite(v);
  const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  const x = i => L + (i + .5 - start) * PW / count;
  const bounds = () => count <= 0 ? [0, -1] : [Math.max(0, Math.ceil(start - .5 + 1e-8)), Math.min(n - 1, Math.floor(start + count - .5 - 1e-8))];
  const pct = v => valid(v) ? (v > 0 ? '+' : '') + v.toFixed(2) + '%' : '—';
  const color = v => !valid(v) || Math.abs(v) < 1e-10 ? '#64748b' : (v > 0 ? '#d14b4b' : '#1a9e6b');
  const price = v => valid(v) ? v.toFixed(4) : '—';
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
    wrap.setAttribute('aria-busy', 'true'); requestDraw();
  }
  document.querySelectorAll('[data-range]').forEach(button => button.onclick = () => useRange(button.dataset.range));
  periodControl.onchange = () => {
    const keepDates = activeRange ? null : customDates;
    period = periodControl.value; P = D.histories[period]; n = P.prices.length;
    initialCount = P.windows[lastRange].count; initialStart = P.windows[lastRange].start;
    if (keepDates) {
      const first = P.dates.findIndex(d => d >= keepDates[0]);
      let last = P.dates.length - 1;
      while (last >= 0 && P.dates[last] > keepDates[1]) last--;
      start = Math.max(0, first); count = first < 0 || last < first ? 0 : last - first + 1;
      activeRange = null;
    } else {start = initialStart; count = initialCount;}
    pinned = hover = null; wrap.setAttribute('aria-busy', 'true'); requestDraw();
  };
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
    selection.textContent = `当前：${activeRange || '自选区间'} · ${period}线${activeRange === '近1月' ? '（30自然日）' : ''}`;
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
    // 相对起点（可见第一期收盘为 0% 基准）与单期涨跌幅，各自一个柱面板
    const startPx = valid(P.prices[first]) ? P.prices[first] : null;
    const relAt = i => (startPx && startPx > 0 && valid(P.prices[i])) ? (P.prices[i]/startPx - 1) * 100 : null;
    const stepAt = i => P.rets[i];
    let grid = '', marks = '', ticks = `<text x="${L}" y="18" font-size="12" fill="#475569">收盘价</text>`;
    for (let k = 0; k <= 4; k++) {
      const v = lo + (hi - lo) * k / 4, yy = y(v);
      grid += `<line x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}" stroke="#edf1f7"/>`;
      ticks += `<text x="${L-8}" y="${yy+4}" text-anchor="end" font-size="10" fill="#64748b">${v.toFixed(4)}</text>`;
    }
    const step = PW / count;
    const pts = [], bw = Math.min(20, Math.max(.8, step * .45));
    for (let i = first; i <= last; i++) if (valid(P.prices[i])) pts.push(`${x(i)},${y(P.prices[i])}`);
    marks += `<polyline points="${pts.join(' ')}" fill="none" stroke="#326ce5" stroke-width="2" stroke-linejoin="round"/>`;
    for (let i = first; i <= last; i++) if (valid(P.prices[i])) {
      marks += `<circle data-index="${i}" cx="${x(i)}" cy="${y(P.prices[i])}" r="${Math.min(3.5,Math.max(1,step*.12))}" fill="#326ce5"/>`;
    }
    // 起点：价格面板上画一条虚线并圈出该点，相对起点柱全部以它为 0% 基准
    const y0 = startPx ? y(startPx) : null;
    if (y0 !== null && y0 >= T && y0 <= T + AH) {
      grid += `<line x1="${L}" y1="${y0}" x2="${W-R}" y2="${y0}" stroke="#8fa0b8" stroke-dasharray="2 4" opacity=".85"/>`;
      marks += `<circle cx="${x(first)}" cy="${y0}" r="4.5" fill="none" stroke="#326ce5" stroke-width="1.5" opacity=".9"/>`;
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
        + `<text x="${L-8}" y="${top+11}" text-anchor="end" font-size="11" fill="#64748b">+${bmax.toFixed(2)}%</text>`
        + `<text x="${L-8}" y="${zero+3.5}" text-anchor="end" font-size="11" fill="#64748b">0%</text>`
        + `<text x="${L-8}" y="${top+paneHeight-1}" text-anchor="end" font-size="11" fill="#64748b">-${bmax.toFixed(2)}%</text>`;
      let out = `<line x1="${L}" y1="${zero}" x2="${W-R}" y2="${zero}" stroke="#cbd5e1" stroke-dasharray="3 3"/>`;
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
      ticks += `<text data-date-label="${i}" x="${cx}" y="${H-15}" text-anchor="middle" font-size="10" fill="#64748b">${esc(P.labels[i])}</text>`;
    }
    // 最高/最低直接标注在价格图内；仅标真实可见点，并对标签做碰撞处理。
    let hiI = null, loI = null;
    for (let i = first; i <= last; i++) {
      if (!valid(P.prices[i])) continue;
      if (hiI === null || P.prices[i] > P.prices[hiI]) hiI = i;
      if (loI === null || P.prices[i] < P.prices[loI]) loI = i;
    }
    let annotations = '';
    if (hiI !== null && loI !== null) {
      const labelW = Math.min(148, PW), labelH = 42;
      const boxes = [hiI, loI].map((i,k) => ({
        x: clamp(x(i) - labelW/2, L, W-R-labelW),
        y: clamp(y(P.prices[i]) + (k === 0 ? -52 : 12), T+3, T+AH-labelH-3)
      }));
      if (Math.abs(boxes[0].x-boxes[1].x) < labelW+6 && Math.abs(boxes[0].y-boxes[1].y) < labelH+6) {
        boxes[0].y = T+4; boxes[1].y = T+AH-labelH-4;
      }
      [hiI,loI].forEach((i,k) => {
        const box = boxes[k], label = k === 0 ? '最高' : '最低', kind = k === 0 ? 'high' : 'low';
        marks += `<circle cx="${x(i)}" cy="${y(P.prices[i])}" r="4" fill="${k === 0 ? '#b33f48' : '#fff'}" stroke="#b33f48" stroke-width="1.5"/>`;
        annotations += `<g data-extreme="${kind}" data-index="${i}" data-price="${P.prices[i]}" data-date="${esc(P.dates[i])}">`
          + `<rect x="${box.x}" y="${box.y}" width="${labelW}" height="${labelH}" rx="6" fill="#fff" fill-opacity=".96" stroke="#efd8da"/>`
          + `<text x="${box.x+10}" y="${box.y+17}" font-size="12" fill="#b33f48">${label} ${price(P.prices[i])}</text>`
          + `<text x="${box.x+10}" y="${box.y+33}" font-size="11" fill="#64748b">${esc(P.dates[i])}</text></g>`;
      });
    }
    svg.innerHTML = `<defs><clipPath id="plot-clip"><rect x="${L}" y="${T-5}" width="${PW}" height="${H-T-B+10}"/></clipPath></defs>${grid}<g clip-path="url(#plot-clip)">${marks}<line id="guide" y1="${T}" y2="${H-B}" stroke="#94a3b8" stroke-dasharray="4 4" visibility="hidden"/></g>${ticks}${annotations}`;
    wrap.dataset.bars = String(cntRel); wrap.dataset.stepBars = String(cntStep);
    const change = relAt(last);
    const amplitude = hiI !== null && loI !== null && P.prices[loI] > 0 ? (P.prices[hiI]/P.prices[loI]-1)*100 : null;
    document.getElementById('stats').innerHTML =
      `<div class="summary-main"><div class="summary-result"><span>当前区间变化</span>`
      + `<b id="change" data-value="${valid(change) ? change : ''}" style="color:${color(change)}">${pct(change)}</b></div>`
      + `<div class="summary-prices"><span><small>起点价</small><b id="start-price" data-value="${startPx ?? ''}">${price(startPx)}</b></span>`
      + `<span aria-hidden="true">→</span><span><small>终点价</small><b id="end-price" data-value="${P.prices[last] ?? ''}">${price(P.prices[last])}</b></span></div></div>`
      + `<div class="amp-row"><span>收盘价区间振幅</span><b id="amplitude" data-value="${valid(amplitude) ? amplitude : ''}">${valid(amplitude) ? amplitude.toFixed(2)+'%' : '—'}</b>`
      + `<small>最高收盘价 ÷ 最低收盘价 − 1 · 当前 ${visibleCount} 期 / 全历史 ${n} 期</small></div>`;
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
    tip.innerHTML = `<b>${esc(P.dates[i])}</b>`
      + `<div class="tip-row"><span class="tip-label">收盘价</span><b>${price(px)}</b></div>`
      + `<div class="tip-row"><span class="tip-label">单${period}涨跌幅</span><b style="color:${color(rt)}">${pct(rt)}</b></div>`
      + `<div class="tip-row"><span class="tip-label">相对起点</span><b style="color:${color(rel)}">${pct(rel)}</b></div>`
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
    e.preventDefault(); pinned=null;
    if(e.ctrlKey||e.metaKey) zoom(Math.exp(clamp(e.deltaY,-400,400)*.003),localX(e));
    else {
      const delta=Math.abs(e.deltaX)>Math.abs(e.deltaY)?e.deltaX:e.deltaY;
      update(start+delta*(e.deltaMode===1?16:1)*count/PW,count);
    }
  },{passive:false});
  // 未展示工具栏：双击复位即可，交互能力不减
  function reset(){useRange(lastRange);}
  svg.addEventListener('dblclick',reset);
  new ResizeObserver(requestDraw).observe(wrap);
  requestDraw();
})();
</script>"""
    return template.replace("__CHART_DATA__", payload)


def _sparkline(series, height=58):
    """迷你净值走势（无坐标轴）。"""
    if series is None or len(series) < 2:
        return None
    d = series.tail(120).rename("nav").reset_index()
    d.columns = ["date", "nav"]
    base = d["nav"].iloc[0]
    d["ret"] = d["nav"] / base - 1
    color = _UP if d["ret"].iloc[-1] >= 0 else _DOWN
    area = (
        alt.Chart(d)
        .mark_area(
            line={"color": color, "strokeWidth": 2},
            color=alt.Gradient(
                gradient="linear",
                stops=[
                    alt.GradientStop(color="rgba(255,255,255,0)", offset=0),
                    alt.GradientStop(color=color, offset=1),
                ],
                x1=1, x2=1, y1=1, y2=0,
            ),
            opacity=0.18,
        )
        .encode(
            x=alt.X("date:T", axis=None),
            y=alt.Y("ret:Q", axis=None, scale=alt.Scale(zero=False)),
        )
        .properties(height=height)
    )
    return area


def _render_table(columns, rows, totals=None):
    """渲染 HTML 表格。columns: [(标题, 对齐)]，rows: list[list[str]]。

    totals 传入一行（list[str]）时会渲染为高亮的合计行。
    """
    head = "".join(
        f'<th class="{"num" if al=="right" else ""}">{c}</th>' for c, al in columns
    )
    body = ""
    for r in rows:
        body += "<tr>" + "".join(
            f'<td class="{"num" if columns[i][1]=="right" else ""}">{cell}</td>'
            for i, cell in enumerate(r)
        ) + "</tr>"
    if totals:
        body += '<tr class="total">' + "".join(
            f'<td class="{"num" if columns[i][1]=="right" else ""}">{cell}</td>'
            for i, cell in enumerate(totals)
        ) + "</tr>"
    st.markdown(f'<table class="tbl"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>',
                unsafe_allow_html=True)


_nf = f"{ETF_META['nonferr']['name']} ({ETF_META['nonferr']['code']})"
_au = f"{ETF_META['gold']['name']} ({ETF_META['gold']['code']})"
_hs = f"{ETF_META['hs300']['name']} ({ETF_META['hs300']['code']})"
_sp = f"{ETF_META['us_sp500']['name']} ({ETF_META['us_sp500']['code']})"
_cr = f"{ETF_META['credit']['name']} ({ETF_META['credit']['code']})"

SIGNAL_ACTIONS = [
    {
        "key": "nonferr_below_sma75",
        "desc": f"{_nf} 跌破 SMA75",
        "condition": lambda s: s.get("nonferr_below_sma75", False),
        "sell": _nf,
        "buy": _cr,
        "strategies": ["B-Con", "B-RP", "V3c"],
        "type": "趋势过滤",
    },
    {
        "key": "gold_below_sma75",
        "desc": f"{_au} 跌破 SMA75",
        "condition": lambda s: s.get("gold_below_sma75", False),
        "sell": _au,
        "buy": _cr,
        "strategies": ["B-RP", "V3c"],
        "type": "趋势过滤",
    },
    {
        "key": "sp500_below_sma75",
        "desc": f"{_sp} 跌破 SMA{SP500_TREND_WINDOW}",
        "condition": lambda s: s.get("sp500_below_sma75", False),
        "sell": _sp,
        "buy": _cr,
        "strategies": ["B-RP", "V3c"],
        "type": "趋势过滤",
    },
    {
        "key": "hs300_dip_ready",
        "desc": f"HS300 回撤>{HS300_DIP_THRESHOLD:.0%} + PB<{HS300_PB_ENTRY}%ile + 价格>SMA{HS300_DIP_SMA}",
        "condition": lambda s: s.get("hs300_dip_ready", False),
        "sell": f"{_cr}（筹资）",
        "buy": f"{_hs} ×1.8",
        "strategies": ["B-Con", "B-RP", "V3c"],
        "type": "抄底加仓",
    },
    {
        "key": "hs300_dip_exit",
        "desc": f"PE > {HS300_PE_EXIT}%ile，抄底出场",
        "condition": lambda s: s.get("hs300_dip_exit", False),
        "sell": f"{_hs} 恢复原权重",
        "buy": _cr,
        "strategies": ["B-Con", "B-RP", "V3c"],
        "type": "抄底出场",
    },
]

# ============================================================
# 数据新鲜度
# ============================================================
ASSETS_TO_CHECK = ["hs300", "us_sp500", "bond_credit", "bond_10y_etf", "bond_30y_etf", "gold", "nonferr", "wti"]


def _trading_days_ago(last_date, today):
    """估算交易日间隔（日历天 - 周末天数）。"""
    cal_days = (today - last_date).days
    weeks = cal_days // 7
    extra = min(cal_days % 7, 2)
    return max(1, cal_days - weeks * 2 - extra)

def _check_data_staleness():
    """返回 (最旧交易日数, 最旧资产名) 若无数据则返回 (None, None)。"""
    results = []
    now = pd.Timestamp.now().date()
    for name in ASSETS_TO_CHECK:
        fp = DATA_DIR / f"{name}.csv"
        if not fp.exists():
            return None, None
        try:
            df = pd.read_csv(fp, parse_dates=["date"])
            last_date = df["date"].max().date()
            results.append((name, _trading_days_ago(last_date, now)))
        except Exception:
            return None, None
    if not results:
        return None, None
    oldest = max(results, key=lambda x: x[1])
    return oldest[1], oldest[0]


# ============================================================
# Sidebar
# ============================================================
st.sidebar.markdown(
    '<div class="sb-brand"><span class="mark">🌤️</span>全天候再平衡</div>',
    unsafe_allow_html=True,
)

_strat_display = {"B-Con": "V3-B 保守增强", "B-RP": "V3-B 风险平价", "V3c": "V3c 多元"}
st.sidebar.markdown('<div class="sb-label">策略</div>', unsafe_allow_html=True)
strat_key = st.sidebar.radio(
    "策略",
    ["B-Con", "B-RP", "V3c"],
    format_func=lambda k: _strat_display[k],
    label_visibility="collapsed",
)
st.sidebar.markdown('<div class="sb-label">现金档位</div>', unsafe_allow_html=True)
tier = st.sidebar.radio(
    "现金档位",
    ["100", "85", "70"],
    format_func=lambda t: f"{t}% RP",
    label_visibility="collapsed",
)
st.sidebar.markdown('<div class="sb-divider"></div>', unsafe_allow_html=True)

# 自动拉取：数据超过 1 天就增量更新
staleness_days, staleness_asset = _check_data_staleness()
if "auto_fetch_done" not in st.session_state:
    st.session_state.auto_fetch_done = False

if staleness_days is not None and staleness_days > 1 and not st.session_state.auto_fetch_done:
    from allweather.fetch import fetch_all
    today_str = date.today().strftime("%Y%m%d")
    fetch_all(force=False, end=today_str)
    st.session_state.auto_fetch_done = True
    st.cache_data.clear()
    st.rerun()

if staleness_days is not None:
    if staleness_days > 7:
        _sb_cls, _sb_txt = "err", f"数据滞后 {staleness_days} 天"
    elif staleness_days > 1:
        _sb_cls, _sb_txt = "warn", f"数据滞后 {staleness_days} 个交易日"
    else:
        _sb_cls, _sb_txt = "", "数据已是最新"
else:
    _sb_cls, _sb_txt = "err", "数据缺失"
st.sidebar.markdown(
    f'<span class="sb-status {_sb_cls}"><span class="dot"></span>{_sb_txt}</span>',
    unsafe_allow_html=True,
)

if st.sidebar.button("拉取最新数据", icon="🔄", type="secondary", use_container_width=True):
    with st.sidebar:
        with st.spinner("正在拉取..."):
            from allweather.fetch import fetch_all
            today_str = date.today().strftime("%Y%m%d")
            fetch_all(force=False, end=today_str)
    st.session_state.auto_fetch_done = True
    st.cache_data.clear()
    st.rerun()

# ============================================================
# 数据加载（直接读 CSV，不截断到 BACKTEST_END）
# ============================================================
_LIVE_ASSETS = {
    "hs300": "hs300",
    "us_sp500": "us_sp500",
    "credit": "bond_credit",
    "bond_10y": "bond_10y_etf",
    "bond_30y": "bond_30y_etf",
    "gold": "gold",
    "nonferr": "nonferr",
    "wti": "wti",
}


def _load_live_prices():
    dfs = {}
    for col, filename in _LIVE_ASSETS.items():
        fp = DATA_DIR / f"{filename}.csv"
        if fp.exists():
            df = pd.read_csv(fp, parse_dates=["date"], index_col="date")
            dfs[col] = df["close"]
    panel = pd.DataFrame(dfs).sort_index().ffill().dropna()
    return panel


@st.cache_data(ttl=300, show_spinner=False)
def _load_prices_and_signals():
    prices = _load_live_prices()
    signals = compute_signal_states(prices)
    return prices, signals


prices, signals = _load_prices_and_signals()

last_date = prices.index[-1].strftime("%Y-%m-%d")
st.sidebar.caption(f"数据截止：{_cn_date(last_date)}")

missing = [a for a in STRATEGIES[strat_key]["assets"] if a not in prices.columns]
if missing:
    st.error(f"缺少数据: {missing}")
    st.stop()

cash_ratio = 1 - int(tier) / 100

# ============================================================
# 计算权重
# ============================================================
w0 = compute_target_weights(strat_key, prices, cash_ratio)
w = apply_signal_overrides(strat_key, w0, signals, prices)
cfg = STRATEGIES[strat_key]

# ============================================================
# Hero
# ============================================================
_n_sig = sum(1 for sa in SIGNAL_ACTIONS
             if bool(sa["condition"](signals)) and strat_key in sa["strategies"])
_fresh = staleness_days is not None and staleness_days <= 1
st.markdown(
    f"""<div class="hero">
      <div>
        <div class="hero-title">全天候再平衡</div>
        <div class="hero-sub">数据截止 {_cn_date(last_date)} · {cfg['name']} · {tier}% 风险平价</div>
      </div>
      <div class="chips">
        <span class="chip"><span class="dot {'warn' if not _fresh else ''}"></span>
          {'数据已更新' if _fresh else f'数据滞后 {staleness_days} 天'}</span>
        <span class="chip">{'⚠️ ' + str(_n_sig) + ' 个信号触发' if _n_sig else '✓ 无信号触发'}</span>
      </div>
    </div>""",
    unsafe_allow_html=True,
)

# ============================================================
# Main Tabs
# ============================================================
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    ["信号仪表盘", "目标权重", "建仓清单", "调仓清单",
     "实操记录", "基金走势"]
)

# ============================================================
# Tab 1: 信号仪表盘
# ============================================================
with tab1:
    # 策略净值迷你走势归入仪表盘内，不再占据首页顶部
    _bench_full = _bench_curve(strat_key)
    if _bench_full is not None and len(_bench_full) > 30:
        _seg = _bench_full.tail(120)
        _seg_ret = float(_seg.iloc[-1] / _seg.iloc[0] - 1)
        with st.container(border=True):
            _c_sp, _c_meta = st.columns([4.2, 1], vertical_alignment="center")
            with _c_sp:
                st.markdown(
                    f'<div class="mini-title">策略净值 · {_strat_display[strat_key]} · 近 120 个交易日</div>',
                    unsafe_allow_html=True,
                )
                st.altair_chart(_sparkline(_seg, height=72))
            with _c_meta:
                st.metric("区间涨跌", f"{_seg_ret*100:+.2f}%")
                st.caption(f"{_seg.index[0]:%Y/%m/%d} → {_seg.index[-1]:%Y/%m/%d}")
    triggered = []
    calm = []
    not_applicable = []

    for sa in SIGNAL_ACTIONS:
        active = sa["condition"](signals)
        applies = strat_key in sa["strategies"]
        if active and applies:
            triggered.append(sa)
        elif not applies:
            not_applicable.append(sa)
        else:
            calm.append(sa)

    if triggered:
        st.subheader(f"已触发信号 · {len(triggered)} 项")
        cards = "".join(
            f'<div class="sig"><div class="main">'
            f'<div class="t">{sa["desc"]}</div><div class="m">{sa["type"]}</div></div>'
            f'<div class="side"><b>卖出</b>{sa["sell"]}</div>'
            f'<div class="side"><b>买入</b>{sa["buy"]}</div></div>'
            for sa in triggered
        )
        st.markdown(cards, unsafe_allow_html=True)
    else:
        st.markdown(
            '<div class="sig calm"><div class="main">'
            '<div class="t">当前无触发信号</div>'
            '<div class="m">所有资产按目标权重正常配置，月末检查即可</div>'
            '</div></div>',
            unsafe_allow_html=True,
        )

    with st.expander(f"未触发信号（{len(calm)} 项，适用本策略）"):
        if calm:
            st.markdown("".join(
                f'<div class="sig off"><div class="main"><div class="t">{sa["desc"]}</div>'
                f'<div class="m">{sa["type"]}</div></div></div>' for sa in calm
            ), unsafe_allow_html=True)
        else:
            st.caption("无")

    with st.expander(f"不适用本策略（{len(not_applicable)} 项）"):
        if not_applicable:
            st.markdown("".join(
                f'<div class="sig off"><div class="main"><div class="t">{sa["desc"]}</div>'
                f'<div class="m">{sa["type"]}</div></div></div>' for sa in not_applicable
            ), unsafe_allow_html=True)
        else:
            st.caption("无")

    st.divider()
    st.subheader("估值分位")
    pb_col, pe_col = st.columns(2)
    with pb_col:
        pb_pct = signals.get("pb_pctile")
        if pb_pct is not None:
            st.metric("PB 分位", f"{pb_pct:.0f}%ile",
                      delta="便宜" if signals.get("pb_entry_ok") else "偏贵",
                      delta_color="inverse" if not signals.get("pb_entry_ok") else "normal")
            st.progress(min(pb_pct / 100, 1.0))
    with pe_col:
        pe_pct = signals.get("pe_pctile")
        if pe_pct is not None:
            st.metric("PE 分位", f"{pe_pct:.0f}%ile",
                      delta="偏贵" if signals.get("pe_exit_ok") is False else "正常",
                      delta_color="inverse" if signals.get("pe_exit_ok") is False else "normal")
            st.progress(min(pe_pct / 100, 1.0))

    st.divider()
    dd_col1, dd_col2 = st.columns(2)
    with dd_col1:
        gold_dd = signals.get("gold_dd_pct", 0)
        st.metric("黄金 1Y 回撤", f"{gold_dd*100:.1f}%",
                  delta=f"距深度回撤线 {(-GOLD_DIP_THRESHOLD*100):.0f}% 还差 {(gold_dd*100 + GOLD_DIP_THRESHOLD*100):.1f}%" if gold_dd > -GOLD_DIP_THRESHOLD else "深度回撤")
    with dd_col2:
        hs_dd = signals.get("hs300_dd_pct", 0)
        st.metric("沪深300 3Y 回撤", f"{hs_dd*100:.1f}%",
                  delta=f"距抄底线 {(-HS300_DIP_THRESHOLD*100):.0f}% 还差 {(hs_dd*100 + HS300_DIP_THRESHOLD*100):.1f}%" if hs_dd > -HS300_DIP_THRESHOLD else "深度回撤")

    # 四季象限
    st.divider()
    st.subheader("宏观季节")

    growth_up = signals.get("hs300_above_sma120", False)
    gold_sma75 = prices["gold"].rolling(75).mean().iloc[-1]
    inflation_up = prices["gold"].iloc[-1] > gold_sma75

    QUADRANTS = [
        {"label": "复苏", "sub": "增长↑ 通胀↓", "growth": True,  "inflation": False,
         "icon": "🌸", "color": "#2e7d32", "assets": "沪深300 · 标普500"},
        {"label": "过热", "sub": "增长↑ 通胀↑",  "growth": True,  "inflation": True,
         "icon": "🔥", "color": "#c62828", "assets": "黄金 · 有色金属"},
        {"label": "滞胀", "sub": "增长↓ 通胀↑", "growth": False, "inflation": True,
         "icon": "💨", "color": "#e65100", "assets": "黄金（避险）"},
        {"label": "衰退", "sub": "增长↓ 通胀↓",  "growth": False, "inflation": False,
         "icon": "❄️", "color": "#1565c0", "assets": "10Y国债 · 30Y国债"},
    ]

    current_label = ""
    for q in QUADRANTS:
        if q["growth"] == growth_up and q["inflation"] == inflation_up:
            current_label = q["label"]
            break

    st.caption(f"当前：**{current_label}**（增长{'↑' if growth_up else '↓'}  通胀{'↑' if inflation_up else '↓'}）")

    cells = []
    for q in QUADRANTS:
        active = q["growth"] == growth_up and q["inflation"] == inflation_up
        border = f"2px solid {_BRAND}" if active else "1px solid #e8ebf2"
        bg = "#fff5f5" if active else "#ffffff"
        cells.append(
            f"<div style='border:{border};border-radius:14px;padding:12px 16px;"
            f"background:{bg};box-shadow:0 1px 2px rgba(16,24,40,.04)'>"
            f"<span style='font-size:22px'>{q['icon']}</span> "
            f"<strong style='font-size:15px'>{q['label']}</strong> "
            f"<span style='color:#9aa3af;font-size:12px'>{q['sub']}</span><br>"
            f"<span style='font-size:12.5px;color:#6b7280'>{q['assets']}</span>"
            f"</div>"
        )

    html = "<div style='display:grid;grid-template-columns:1fr 1fr;gap:12px'>" + "".join(cells) + "</div>"
    st.markdown(html, unsafe_allow_html=True)

# ============================================================
# Tab 2: 目标权重
# ============================================================
with tab2:
    st.subheader(f"{cfg['name']}  —  {tier}% RP")

    rows = []
    for a in cfg["assets"]:
        meta = ETF_META.get(a, {"code": "", "name": a})
        pct = w.get(a, 0)
        status_parts = []

        if a == "nonferr" and signals.get("nonferr_below_sma75") and pct == 0:
            status_parts.append("趋势过滤→已清仓")
        if a == "gold" and strat_key in ("B-RP", "V3c") and signals.get("gold_below_sma75") and pct == 0:
            status_parts.append("趋势过滤→已清仓")
        if a == "us_sp500" and strat_key in ("B-RP", "V3c") and signals.get("sp500_below_sma75") and pct == 0:
            status_parts.append("趋势过滤→已清仓")
        if a == "hs300" and signals.get("hs300_dip_ready") and pct > 0:
            status_parts.append("AND抄底×1.8")
        if a == "credit":
            incoming = []
            if signals.get("nonferr_below_sma75"):
                incoming.append("有色")
            if strat_key in ("B-RP", "V3c") and signals.get("sp500_below_sma75"):
                incoming.append("标普")
            if strat_key in ("B-RP", "V3c") and signals.get("gold_below_sma75"):
                incoming.append("黄金")
            if incoming:
                status_parts.append(f"接收{'/'.join(incoming)}")

        rows.append({
            "资产": meta["name"],
            "代码": meta["code"],
            "权重": f"{pct*100:.1f}%",
            "状态": " / ".join(status_parts) if status_parts else "—",
        })

    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    if any(signals.get(k, False) for k in ["nonferr_below_sma75", "gold_below_sma75", "sp500_below_sma75"]):
        st.info("趋势过滤触发 → 对应资产已清仓，权重转入城投债ETF (511220)")

# ============================================================
# Tab 3: 建仓清单
# ============================================================
with tab3:
    st.subheader("从零建仓")

    amount = st.number_input(
        "投资总额（元）",
        min_value=1000,
        value=500000,
        step=10000,
        format="%d",
        key="build_amount_input",
    )

    if amount > 0:
        latest = prices.iloc[-1]
        lot_size = 100

        rows = []
        total_used = 0
        total_target = 0.0
        for a in cfg["assets"]:
            meta = ETF_META.get(a, {"code": "", "name": a})
            pct = w.get(a, 0)
            if not np.isfinite(pct) or pct <= 0:
                continue
            target_amount = pct * amount
            price = float(latest.get(a, np.nan))
            if np.isnan(price) or price <= 0:
                continue
            shares = int(target_amount / price / lot_size) * lot_size
            actual = shares * price
            total_used += actual
            total_target += target_amount
            rows.append([
                meta["name"], meta["code"], f"{pct*100:.1f}%",
                f"¥{target_amount:,.0f}", f"{price:.3f}", f"{shares:,}",
                f"¥{actual:,.0f}",
            ])

        if rows:
            _render_table(
                [("资产", "left"), ("代码", "left"), ("权重", "right"),
                 ("目标金额", "right"), ("现价", "right"), ("买入股数", "right"),
                 ("实际金额", "right")],
                rows,
                totals=["合计", "—", "100.0%", f"¥{total_target:,.0f}", "—", "—",
                        f"¥{total_used:,.0f}"],
            )

            remainder = amount - total_used
            cols = st.columns(3)
            with cols[0]:
                st.metric("总投资", f"¥{amount:,.0f}")
            with cols[1]:
                st.metric("已分配", f"¥{total_used:,.0f}")
            with cols[2]:
                st.metric("剩余现金", f"¥{remainder:,.0f}",
                          delta="放入货基/华宝添益(511990)")

            if any(a == "us_sp500" for a in cfg["assets"]) and w.get("us_sp500", 0) > 0:
                st.info("标普500 QDII 经常限购，买不到用场外联接 050025 替代")
        else:
            st.warning("无有效资产可建仓")

# ============================================================
# Tab 4: 调仓清单
# ============================================================
with tab4:
    st.subheader("调仓对比")

    st.caption("输入当前持仓股数，自动计算买卖清单")

    latest = prices.iloc[-1]
    lot_size = 100

    holdings_shares = {}
    cols = st.columns(3)
    for i, a in enumerate(cfg["assets"]):
        meta = ETF_META.get(a, {"code": "", "name": a})
        with cols[i % 3]:
            holdings_shares[a] = st.number_input(
                f"{meta['name']} ({meta['code']})",
                min_value=0,
                value=0,
                step=100,
                format="%d",
                key=f"holdings_{strat_key}_{a}",
            )

    total_value = sum(
        holdings_shares.get(a, 0) * float(latest.get(a, 0)) for a in cfg["assets"]
    )
    if total_value > 0:
        st.divider()
        st.caption(f"持仓总市值: ¥{total_value:,.0f}")

        trade_rows = []
        any_trade = False
        sum_target = 0.0
        sum_diff = 0.0
        for a in cfg["assets"]:
            meta = ETF_META.get(a, {"code": "", "name": a})
            price = float(latest.get(a, 0))
            shares = holdings_shares.get(a, 0)
            current_amt = shares * price
            target_amt = w.get(a, 0) * total_value
            diff_amt = target_amt - current_amt
            pct_diff = abs(diff_amt) / total_value if total_value > 0 else 0
            diff_shares = int(diff_amt / price / lot_size) * lot_size if price > 0 else 0
            sum_target += target_amt
            sum_diff += diff_amt

            if pct_diff < 0.005 or diff_shares == 0:
                action = '<span class="muted">不变</span>'
            elif diff_amt > 0:
                action = f'<span class="up">买入 {diff_shares:,} 股</span>'
                any_trade = True
            else:
                action = f'<span class="down">卖出 {-diff_shares:,} 股</span>'
                any_trade = True

            if abs(diff_amt) < 1:
                diff_txt = '<span class="muted">—</span>'
            else:
                cls = "up" if diff_amt > 0 else "down"
                diff_txt = f'<span class="{cls}">{diff_amt:+,.0f}</span>'

            trade_rows.append([
                meta["name"], meta["code"], f"{shares:,}",
                f"{current_amt:,.0f}", f"{target_amt:,.0f}", diff_txt, action,
            ])

        _render_table(
            [("资产", "left"), ("代码", "left"), ("持仓股数", "right"),
             ("市值 (¥)", "right"), ("目标 (¥)", "right"), ("差额 (¥)", "right"),
             ("操作", "left")],
            trade_rows,
            totals=["合计", "—", "—", f"{total_value:,.0f}", f"{sum_target:,.0f}",
                    f"{sum_diff:+,.0f}", "—"],
        )

        if not any_trade:
            st.success("所有资产偏离 < 0.5%，无需调仓")

        with st.expander("调仓规则说明"):
            st.markdown("""
            1. 每月最后一个交易日执行一次
            2. 先卖后买 — 卖出资金 T+0 可用后再买入
            3. nonferr / gold / SP500 跌破 SMA → 清仓转城投债
            4. 偏离 < 0.5% 不用动，省手续费
            5. 股数按 100 股取整，实际成交金额以市价为准
            6. 标普500 QDII 限购时用场外联接 050025 替代
            """)
    else:
        st.caption("输入持仓股数后自动生成调仓清单")

# ============================================================
# Tab 5: 实操记录
# ============================================================
ACCT_FILE = DATA_DIR / "sim_account.json"
_ACCT_ASSETS = [a for a in ["hs300", "us_sp500", "credit", "bond_10y",
                            "bond_30y", "gold", "nonferr", "wti"] if a in prices.columns]
_ASSET_LABEL = {a: f"{ETF_META.get(a, {}).get('name', a)} ({ETF_META.get(a, {}).get('code', '')})"
                for a in _ACCT_ASSETS}


def _fmt_money(v):
    return f"¥{v:,.0f}"


with tab5:
    st.subheader("实操记录 · 账户净值 vs 策略")
    acct = load_acct(ACCT_FILE)

    if acct is None:
        st.info("**还没有实操账户** — 创建后依次录入成交，页面会自动生成：净值曲线、月度收益（实际 vs 理论）、持仓明细。")
        with st.form("acct_init"):
            c1, c2, c3 = st.columns(3)
            with c1:
                s_init = st.selectbox("跟随策略", ["V3c", "B-RP", "B-Con"],
                                      format_func=lambda k: STRATEGIES[k]["name"])
            with c2:
                cap0 = st.number_input("初始资金（元）", min_value=1000.0, value=500000.0,
                                       step=10000.0, format="%.0f")
            with c3:
                start0 = st.date_input("起始日期", value=prices.index[-1].date())
            if st.form_submit_button("创建账户", type="primary"):
                save_acct({"strategy": s_init, "capital": float(cap0),
                           "created": str(start0), "trades": []}, ACCT_FILE)
                st.rerun()
    else:
        daily, pos, cost, cash, units = replay(
            acct.get("trades", []), prices, acct.get("capital", 0), acct.get("created"))
        stn = acct_stats(daily)
        equity = float(daily["equity"].iloc[-1]) if len(daily) else float(acct.get("capital", 0))
        pnl = equity - float(acct.get("capital", 0))

        # 基准：同策略回测净值（从建仓日起归一）
        bench = None
        nvc_p = PROJECT_ROOT / "output" / "nv_curves.csv"
        col = _BENCH_COL.get(acct.get("strategy"))
        if nvc_p.exists() and col:
            nvc_df = pd.read_csv(nvc_p, index_col=0, parse_dates=True)
            if col in nvc_df.columns:
                b = nvc_df[col].loc[pd.Timestamp(acct["created"]):].dropna()
                if len(b) > 1:
                    bench = b / b.iloc[0]
        excess = None
        if bench is not None and len(daily) and acct.get("trades"):
            end = min(bench.index[-1], daily.index[-1])
            excess = float(daily["nav"].loc[:end].iloc[-1] / bench.loc[:end].iloc[-1] - 1)

        st.caption(f"账户起始 {_cn_date(acct['created'])} · 数据区间 "
                   f"{_cn_date(prices.index.min())} ~ {_cn_date(prices.index.max())} · "
                   f"{len(daily)} 个数据日")

        with st.expander("⚙️ 账户设置（修改起始日期 / 重置）"):
            _sc1, _sc2 = st.columns([3, 2])
            with _sc1:
                _new_start = st.date_input(
                    "账户起始日期（净值曲线从这天开始）",
                    value=pd.Timestamp(acct["created"]).date(),
                    min_value=prices.index.min().date(),
                    max_value=prices.index.max().date(),
                    key="acct_start_date",
                )
            with _sc2:
                st.write("")
                st.write("")
                if st.button("保存起始日期", key="acct_start_save", type="primary"):
                    acct["created"] = str(_new_start)
                    save_acct(acct, ACCT_FILE)
                    st.rerun()
            if st.button("清空账户（删除全部成交）", key="acct_reset_top"):
                ACCT_FILE.unlink(missing_ok=True)
                st.rerun()
            st.caption("提示：起始日期越早，越能看到完整曲线；若要一键建仓，请用下方"
                       "「按当前目标权重建仓」，它会按起始日价格买入整仓，而不是几百股。")

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("总资产", _fmt_money(equity))
        m2.metric("累计收益", _fmt_money(pnl), delta=f"{stn['ret']*100:+.2f}%")
        m3.metric("现金", _fmt_money(cash))
        m4.metric("最大回撤", f"{stn['mdd']*100:.2f}%")
        if excess is not None:
            m5.metric("超额（vs 策略）", f"{excess*100:+.2f}pp")
        else:
            m5.metric("超额（vs 策略）", "—")

        # 净值曲线
        if len(daily) > 1:
            cmp_df = pd.DataFrame({"我的账户": daily["nav"]})
            if bench is not None:
                cmp_df["策略理论"] = bench.reindex(cmp_df.index).ffill()
            long_df = (
                cmp_df.reset_index()
                .melt(id_vars="date", var_name="曲线", value_name="nav")
                .dropna()
            )
            ch = (
                alt.Chart(long_df)
                .mark_line(strokeWidth=2)
                .encode(
                    x=alt.X("date:T", title=None,
                            axis=alt.Axis(format="%Y年%m月", labelColor=_SUB,
                                          domainColor="#e8ebf2")),
                    y=alt.Y("nav:Q", title="净值", scale=alt.Scale(zero=False)),
                    color=alt.Color(
                        "曲线:N",
                        scale=alt.Scale(range=["#2f6fed", "#c98a1a"]),
                        legend=alt.Legend(orient="top", title=None),
                    ),
                    tooltip=[
                        alt.Tooltip("date:T", title="日期", format="%Y年%m月%d日"),
                        alt.Tooltip("曲线:N", title="曲线"),
                        alt.Tooltip("nav:Q", format=".4f", title="净值"),
                    ],
                )
                .properties(height=300)
                .interactive()
            )
            st.altair_chart(ch)
            st.caption(
                f"{STRATEGIES[acct['strategy']]['name']} · 建仓 {acct['created']} · "
                f"{len(daily)} 个交易日 · 净值 {stn['nav']:.4f}"
            )
        else:
            if not acct.get("trades"):
                st.info("还没有成交记录 — 在下方「录入一笔成交」保存第一笔后，净值曲线与月度收益对比就会生成")
            else:
                st.warning(
                    f"账户起点 {_cn_date(acct['created'])} 晚于最新行情 {_cn_date(prices.index[-1])}"
                    "（或仅有 1 个数据日），暂时无法画曲线与月度对比。"
                    "等下一个交易日数据更新后会自动生成；也可以把账户起始日期改到 10-16 之前。"
                )

        # ---------- 月度收益对比 ----------
        if len(daily) > 1 and acct.get("trades"):
            st.divider()
            st.markdown("**月度收益 · 实际 vs 理论**")

            _m_acc = daily["nav"].groupby(daily.index.to_period("M")).last()
            _acc_ret = _m_acc.pct_change().dropna() * 100
            _bench_ret = None
            if bench is not None:
                _mb = bench.groupby(bench.index.to_period("M")).last()
                _bench_ret = _mb.pct_change().dropna() * 100

            _periods = sorted(_acc_ret.index)
            _rows_raw = []
            for _p in _periods:
                _a = _acc_ret.get(_p)
                _b = _bench_ret.get(_p) if _bench_ret is not None else None
                _rows_raw.append((_p, _a, _b))

            def _pct_html(v):
                if v is None or pd.isna(v):
                    return "—"
                _c = "up" if v >= 0 else "down"
                return f'<span class="{_c}">{v:+.2f}%</span>'

            _vals = [a for _, a, _ in _rows_raw if a is not None and not pd.isna(a)]
            _beats = [(a, b) for _, a, b in _rows_raw
                      if a is not None and b is not None and not pd.isna(a) and not pd.isna(b)]
            _k1, _k2, _k3, _k4 = st.columns(4)
            _k1.metric("平均月收益", f"{(sum(_vals)/len(_vals)):+.2f}%" if _vals else "—")
            _k2.metric("月胜率", f"{sum(1 for v in _vals if v>0)/len(_vals)*100:.0f}%" if _vals else "—")
            _k3.metric("策略平均月收益",
                       f"{(sum(b for _, b in _beats)/len(_beats)):+.2f}%" if _beats else "—")
            _k4.metric("跑赢策略", f"{sum(1 for a, b in _beats if a > b)}/{len(_beats)} 个月"
                       if _beats else "—")

            _tbl_rows = []
            for _p, _a, _b in reversed(_rows_raw):
                _d = None if (_a is None or _b is None or pd.isna(_a) or pd.isna(_b)) else _a - _b
                _tbl_rows.append([f"{_p.year}年{_p.month}月",
                                  _pct_html(_a), _pct_html(_b), _pct_html(_d)])
            _render_table(
                [("月份", "left"), ("我的账户", "right"), ("策略理论", "right"), ("超额", "right")],
                _tbl_rows,
            )

            _cdf = pd.DataFrame([{
                "月份": f"{_p.year}-{_p.month:02d}",
                "我的账户": _a,
                "策略理论": _b,
            } for _p, _a, _b in _rows_raw])
            _long = _cdf.melt(id_vars="月份", var_name="曲线", value_name="收益").dropna()
            st.altair_chart(
                alt.Chart(_long)
                .mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2)
                .encode(
                    x=alt.X("月份:N", sort=None, title=None,
                            axis=alt.Axis(labelAngle=-45, labelFontSize=9,
                                          labelColor=_SUB, domainColor="#e8ebf2")),
                    xOffset=alt.X("曲线:N", title=None),
                    y=alt.Y("收益:Q", title="%",
                            axis=alt.Axis(labelColor=_SUB, gridColor="#f1f3f8")),
                    color=alt.Color("曲线:N",
                                    scale=alt.Scale(range=["#2f6fed", "#c98a1a"]),
                                    legend=alt.Legend(orient="top", title=None)),
                    tooltip=[alt.Tooltip("月份:N", title="月份"),
                             alt.Tooltip("曲线:N", title="曲线"),
                             alt.Tooltip("收益:Q", format=".2f", title="月收益(%)")],
                )
                .properties(height=250)
            )
            st.caption("账户月收益按月末净值计算（份额记账，已剔除入金/出金影响）；"
                       "建仓当月为不完整月份，仅供参考。")

        # 持仓
        st.divider()
        st.markdown("**当前持仓**")
        hold_rows = []
        latest_px = prices.iloc[-1]
        for a, sh in sorted(pos.items(), key=lambda x: -abs(x[1])):
            if abs(sh) < 1e-9:
                continue
            px = float(latest_px.get(a, np.nan))
            mv = sh * px if not np.isnan(px) else np.nan
            hold_rows.append({
                "资产": ETF_META.get(a, {}).get("name", a),
                "代码": ETF_META.get(a, {}).get("code", ""),
                "份额": f"{sh:,.2f}",
                "成本价": f"{cost.get(a, 0):.4f}",
                "现价": f"{px:.4f}" if not np.isnan(px) else "—",
                "市值 (¥)": f"{mv:,.0f}" if not np.isnan(mv) else "—",
                "占比": f"{mv/equity*100:.1f}%" if equity and not np.isnan(mv) else "—",
            })
        if hold_rows:
            hold_rows.append({"资产": "现金", "代码": "—", "份额": "—", "成本价": "—",
                              "现价": "—", "市值 (¥)": f"{cash:,.0f}",
                              "占比": f"{cash/equity*100:.1f}%" if equity else "—"})
            st.dataframe(pd.DataFrame(hold_rows), width="stretch", hide_index=True)
        else:
            st.caption("暂无持仓（全部为现金）")

        # 录入成交
        st.divider()
        with st.form("add_trade", clear_on_submit=True):
            st.markdown("**录入一笔成交**")
            r1 = st.columns([1, 1, 1.4, 1, 1, 1])
            tr_date = r1[0].date_input("成交日期", value=date.today())
            tr_side = r1[1].selectbox("方向", ["买入", "卖出", "入金", "出金"])
            tr_asset = r1[2].selectbox("资产", _ACCT_ASSETS,
                                       format_func=lambda a: _ASSET_LABEL.get(a, a))
            tr_shares = r1[3].number_input("份额（入金/出金填金额）", min_value=0.0,
                                           value=0.0, step=100.0, format="%.2f")
            tr_price = r1[4].number_input("成交价", min_value=0.0, value=float(latest_px.get(tr_asset, 0)),
                                          step=0.001, format="%.4f")
            tr_fee = r1[5].number_input("费用（元）", min_value=0.0, value=0.0,
                                        step=1.0, format="%.2f")
            if st.form_submit_button("保存成交", type="primary"):
                if tr_shares <= 0:
                    st.error("份额需大于 0")
                else:
                    acct.setdefault("trades", []).append({
                        "date": str(tr_date), "asset": tr_asset, "side": tr_side,
                        "shares": float(tr_shares),
                        "price": 0.0 if tr_side in ("入金", "出金") else float(tr_price),
                        "fee": float(tr_fee),
                    })
                    acct["trades"].sort(key=lambda t: t["date"])
                    save_acct(acct, ACCT_FILE)
                    st.rerun()

        # 快捷操作
        with st.expander("按当前目标权重建仓（生成首笔成交）"):
            build_amt = st.number_input("建仓金额（元）", min_value=1000.0,
                                        value=float(acct.get("capital", 500000)),
                                        step=10000.0, format="%.0f", key="acct_build_amt")
            if st.button("生成建仓成交", key="acct_build_btn"):
                # cash_ratio=0 → 不留现金缓冲（100% 风险平价）
                w_build = compute_target_weights(acct["strategy"], prices, 0.0)
                w_build = apply_signal_overrides(acct["strategy"], w_build, signals, prices)

                # 按账户起始日期成交，这样建完立刻就有完整的历史曲线与月度对比
                _start_idx = prices.index[prices.index >= pd.Timestamp(acct["created"])]
                _build_day = _start_idx[0] if len(_start_idx) else prices.index[-1]
                _build_px = prices.loc[_build_day]

                new_trades, left = [], build_amt
                for a, pct in w_build.items():
                    if not np.isfinite(pct) or pct <= 0 or a not in prices.columns:
                        continue
                    px = float(_build_px.get(a, np.nan))
                    if not np.isfinite(px) or px <= 0:
                        continue
                    sh = int(build_amt * pct / px / 100) * 100
                    if sh > 0:
                        new_trades.append({"date": str(_build_day.date()), "asset": a,
                                           "side": "买入", "shares": sh, "price": px, "fee": 0.0})
                        left -= sh * px
                if new_trades:
                    acct.setdefault("trades", []).extend(new_trades)
                    acct["trades"].sort(key=lambda t: t["date"])
                    save_acct(acct, ACCT_FILE)
                    st.success(f"已生成 {len(new_trades)} 笔建仓成交，剩余现金约 ¥{left:,.0f}")
                    st.rerun()
                else:
                    st.warning("没有可建仓的资产")

        # 流水
        st.divider()
        st.markdown(f"**成交流水（{len(acct.get('trades', []))} 笔）**")
        if acct.get("trades"):
            trows = []
            for t in reversed(acct["trades"]):
                trows.append({
                    "日期": _cn_date(t["date"]),
                    "方向": t["side"],
                    "资产": "—" if t["side"] in ("入金", "出金") else ETF_META.get(t["asset"], {}).get("name", t["asset"]),
                    "份额": f"{t['shares']:,.2f}",
                    "价格": f"{t['price']:.4f}" if t.get("price") else "—",
                    "费用": f"{t.get('fee', 0):,.2f}",
                })
            st.dataframe(pd.DataFrame(trows), width="stretch", hide_index=True, height=240)
            c_undo, c_reset = st.columns([1, 1])
            with c_undo:
                if st.button("撤销最后一笔", key="acct_undo"):
                    acct["trades"].pop()
                    save_acct(acct, ACCT_FILE)
                    st.rerun()
            with c_reset:
                if st.button("清空账户", key="acct_reset", type="secondary"):
                    ACCT_FILE.unlink(missing_ok=True)
                    st.rerun()
        else:
            st.caption("暂无成交")

        st.caption(f"账户文件：{ACCT_FILE.name}（保存在 data/ 下，重装或换机时记得备份）")

# ============================================================
# Tab 6: 基金走势（日 / 月 / 年 的涨跌幅与价格）
# ============================================================
# 范围和采样粒度独立；近1月沿用30自然日，切周期不改变所选范围。
_TREND_RANGES = {
    "近1月": ("days", 30), "近3月": ("months", 3),
    "近1年": ("years", 1), "今年来": ("ytd", 0), "全部": ("all", 0),
}
_TREND_STAGES = {
    "近1月": ("days", 30), "近3月": ("months", 3),
    "近1年": ("years", 1), "今年来": ("ytd", 0),
}


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
    """所有粒度按真实日期筛选 (截止日减跨度, 截止日]，今年来含1月1日。"""
    if series.empty:
        return 0
    kind, amount = span
    if kind == "all":
        return 0
    if kind == "count":
        return max(0, len(series) - int(amount))
    end = series.index[-1]
    if kind == "ytd":
        cutoff = pd.Timestamp(year=end.year, month=1, day=1)
        return int(series.index.searchsorted(cutoff, side="left"))
    cutoff = end - pd.DateOffset(**{kind: int(amount)})
    return int(series.index.searchsorted(cutoff, side="right"))


def _trend_chart_data(series):
    """一次提供三种粒度的全量历史；只预计算五个初始视窗，不截断历史。"""
    histories = {}
    for period, fmt in (("日", "%Y/%m/%d"), ("月", "%Y/%m"), ("年", "%Y")):
        agg = _trend_aggregate(series, period)
        returns = agg.pct_change(fill_method=None) * 100
        histories[period] = {
            "labels": agg.index.strftime(fmt).tolist(),
            "dates": agg.index.strftime("%Y/%m/%d").tolist(),
            "prices": agg.tolist(),
            "rets": [float(v) if pd.notna(v) and np.isfinite(v) else None for v in returns],
            "windows": {label: {"start": _trend_window_start(agg, span),
                                "count": len(agg) - _trend_window_start(agg, span)}
                        for label, span in _TREND_RANGES.items()},
        }
    return histories


def _stage_rows(series):
    """四个固定阶段数字，沿用首个真实收盘基准，不受图表视窗影响。"""
    clean = _trend_aggregate(series, "日")
    cells = []
    for label, span in _TREND_STAGES.items():
        if clean.empty:
            cells.append({"label": label, "ret": None, "base": None, "end": None})
            continue
        bi = _trend_window_start(clean, span)
        base, end = clean.index[bi], clean.index[-1]
        price = float(clean.iloc[bi])
        ret = (float(clean.iloc[-1]) / price - 1) * 100 if price > 0 else None
        cells.append({"label": label, "ret": ret, "base": base, "end": end})
    return cells


def _stage_summary_html(cells):
    """概览内的一行只读数字，不提供点击、展开、同比或图表控件。"""
    items = []
    for cell in cells:
        value = cell["ret"]
        valid = value is not None and np.isfinite(value)
        cls = "up" if valid and value > 0 else ("down" if valid and value < 0 else "neutral")
        text = f"{value:+.2f}%" if valid and value != 0 else ("0.00%" if valid else "—")
        dates = (f'{cell["base"]:%Y/%m/%d} — {cell["end"]:%Y/%m/%d}'
                 if cell["base"] is not None and cell["end"] is not None else "暂无有效行情")
        tip = dates + " · 区间首个收盘至最新收盘" + (" · 30自然日" if cell["label"] == "近1月" else "")
        items.append(
            f'<div class="stage-metric" data-stage="{html_escape(cell["label"])}" title="{html_escape(tip)}">'
            f'<span class="stage-label">{html_escape(cell["label"])}</span>'
            f'<b class="stage-return {cls}" data-value="{value if valid else ""}">{text}</b></div>'
        )
    return ('<div class="stage-summary"><div class="stage-summary-title">阶段表现</div>'
            '<div class="stage-metrics">' + ''.join(items) + '</div></div>')


_CAT = {"hs300": "宽基·A股", "us_sp500": "宽基·美股", "credit": "信用债",
        "bond_10y": "利率债", "bond_30y": "超长久期", "gold": "商品·黄金",
        "nonferr": "商品·有色", "wti": "商品·原油"}

with tab6:
    # ---------- ① 基金概览：价格、单日变化和真实日期绑定 ----------
    with st.container(key="trend_head"):
        _h1, _h2 = st.columns([3.5, 1.15], vertical_alignment="center")
        with _h2:
            asset = st.selectbox("基金", _ACCT_ASSETS,
                                 format_func=lambda a: _ASSET_LABEL.get(a, a),
                                 key="trend_asset", label_visibility="collapsed")
        _own = _asset_series(asset)
        _all = _trend_aggregate(_own if _own is not None else prices[asset], "日")

        _meta = ETF_META.get(asset, {"name": asset, "code": ""})
        _day_chg = float(_all.iloc[-1] / _all.iloc[-2] - 1) if len(_all) > 1 and _all.iloc[-2] > 0 else None
        _day_cls = "up" if _day_chg is not None and _day_chg > 0 else ("down" if _day_chg is not None and _day_chg < 0 else "neutral")
        _day_text = f"{_day_chg * 100:+.2f}%" if _day_chg is not None else "—"
        _latest_text = f"{_all.iloc[-1]:.4f}" if len(_all) else "—"
        _latest_date = f"{_all.index[-1]:%Y/%m/%d}" if len(_all) else "暂无有效行情"

        with _h1:
            # 最新价、单日涨跌、数据截至三者严格同源：都是该期最后一个交易日
            st.markdown(
                f"""<div class="fund-head flat">
                  <div class="fh-top">
                    <span class="fh-name">{_meta['name']}</span>
                    <span class="fh-code">{_meta['code']}</span>
                    <span class="fh-tag">{_CAT.get(asset, '其他')}</span>
                  </div>
                  <div class="fh-price">
                    <span class="fh-price-label">最新收盘价</span>
                    <span class="px">{_latest_text}</span>
                    <span class="chg {_day_cls}"><small>单日</small> {_day_text}</span>
                    <span class="fh-date">截至 {_latest_date}</span>
                  </div>
                </div>""",
                unsafe_allow_html=True,
            )
        st.markdown(_stage_summary_html(_stage_rows(_all)), unsafe_allow_html=True)

    if _all.empty:
        st.info("该基金暂无有效行情，请检查数据源后重试。")
    else:
        if _own is None:
            st.warning("单基金历史读取失败，当前使用已有组合行情，历史覆盖可能不完整。")
        _histories = _trend_chart_data(_all)
        _daily = _histories["日"]
        # 控件与SVG同处一个局部组件：视窗、高亮、日期和摘要同步，无跨iframe状态桥接。
        with st.container(key="trend_chart"):
            components.html(_scroll_chart_html(
                _daily["labels"], _daily["prices"], _daily["windows"]["近1月"]["count"],
                rets=_daily["rets"], histories=_histories,
            ), height=850, scrolling=False)
            st.markdown(
                f'<div class="sec-note">数据源：data/{_LIVE_ASSETS.get(asset, asset)}.csv · '
                f'截至 {_latest_date} · 月/年线取每期最后一条真实记录，未结束期间按最新数据计算。'
                '区间变化以首个可见收盘为基准；近1月为30自然日。</div>',
                unsafe_allow_html=True,
            )

# ============================================================
# 底部：三策略对比
# ============================================================
st.divider()
with st.expander("📈 三策略权重对比"):
    all_weights = {}
    for k in ["B-Con", "B-RP", "V3c"]:
        w0_cmp = compute_target_weights(k, prices, cash_ratio)
        w_cmp = apply_signal_overrides(k, w0_cmp, signals, prices)
        all_weights[k] = w_cmp

    cmp_rows = []
    for a in ["hs300", "us_sp500", "credit", "bond_10y", "bond_30y", "gold", "nonferr", "wti"]:
        meta = ETF_META.get(a, {"code": "", "name": a})
        row = {"资产": meta["name"], "代码": meta["code"]}
        for k in ["B-Con", "B-RP", "V3c"]:
            row[_strat_display[k]] = f"{all_weights[k].get(a, 0)*100:.1f}%"
        cmp_rows.append(row)

    st.dataframe(pd.DataFrame(cmp_rows), width="stretch", hide_index=True)
