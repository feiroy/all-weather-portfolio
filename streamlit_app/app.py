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

from allweather.rebalance import (
    compute_signal_states,
    compute_target_weights,
    apply_signal_overrides,
    STRATEGIES,
    ETF_META,
)
from allweather.sim_account import load_acct, save_acct, stats as acct_stats
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fund_lookup as FL
import fund_search as FS
import importlib
# 仅在 fund_lookup.py 改动后重载：每次 rerun 都 reload 会清空模块缓存（2.8 万条名录、选项列表），
# 且选项文案变化会让 selectbox 丢失当前选择
_fl_mtime = Path(FL.__file__).stat().st_mtime
if getattr(FL, "_LOADED_MTIME", None) != _fl_mtime:
    importlib.reload(FL)
    FL._LOADED_MTIME = _fl_mtime
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


def _password_gate():
    """线上访问密码。只在配置了密码哈希时启用（本机运行默认不启用）：
    - 环境变量 AW_PASSWORD_SHA256，或 .streamlit/secrets.toml 里的 password_sha256（scripts/build_web.py 生成）。
    - 登录成功后在网址上加 ?k=令牌，手机把这个网址加到主屏幕/收藏，下次打开免输密码；改密码后旧令牌自动失效。
    """
    import hashlib
    import os
    want = os.environ.get("AW_PASSWORD_SHA256", "")
    if not want:
        try:
            want = str(st.secrets.get("password_sha256", ""))
        except Exception:
            want = ""
    if not want:
        return
    token = hashlib.sha256(f"aw-token:{want}".encode()).hexdigest()[:20]
    if st.session_state.get("_authed") or st.query_params.get("k") == token:
        st.session_state["_authed"] = True
        return
    st.markdown("<div style='height:12vh'></div>", unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid, st.form("login", border=True):
        st.markdown("#### 全天候再平衡")
        st.caption("请输入访问密码")
        pw = st.text_input("密码", type="password", label_visibility="collapsed", placeholder="访问密码")
        if st.form_submit_button("进入", type="primary", use_container_width=True):
            if hashlib.sha256(pw.encode()).hexdigest() == want:
                st.session_state["_authed"] = True
                st.query_params["k"] = token
                st.rerun()
            st.error("密码不对")
    st.stop()


_password_gate()

# 品牌/图标 SVG 片段（替换 emoji 图标）
_LOGO_SVG = (
    '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    '<path d="M3 13.5h2.5l1.8-4.5 2.2 7 2-5 1.7 2.5H21" '
    'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
    '</svg>'
)
# 四季象限图标（Lucide 风格线性 SVG）
_QUAD_ICONS = {
    "复苏": '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M12 3v3m0 12v3M3 12h3m12 0h3M5.6 5.6l2.1 2.1m8.6 8.6 2.1 2.1m0-12.8-2.1 2.1M7.7 16.3l-2.1 2.1" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="12" cy="12" r="3.2" stroke="currentColor" stroke-width="1.8"/></svg>',
    "过热": '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M12 3c.8 3.5 3.5 5 3.5 8.5a3.5 3.5 0 0 1-7 0C8.5 8 11.2 6.5 12 3Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M12 21c-1.6 0-3-.5-4-1.4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
    "滞胀": '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="8" cy="6" r="1.6" fill="currentColor"/><circle cx="16" cy="12" r="1.6" fill="currentColor"/><circle cx="10" cy="18" r="1.6" fill="currentColor"/></svg>',
    "衰退": '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M12 2v20M12 2l-4 4m4-4 4 4M12 22l-4-4m4 4 4-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
}

st.markdown("""<style>
/* ============================================================
   设计系统 · 全天候再平衡
   主色：金融蓝 #1E40AF / 辅助蓝 #3B82F6
   涨红跌绿（A股约定）：涨 #C52828 · 跌 #16703B
   中性：slate 色阶  bg #F8FAFC / surface #FFFFFF / muted #475569
   ============================================================ */
:root{
  --ink:#0F172A;          /* 主文字 slate-900 */
  --sub:#475569;          /* 次级 slate-600 */
  --muted:#94A3B8;        /* 弱化 slate-400 */
  --line:#E2E8F0;         /* 描边 slate-200 */
  --line-soft:#EEF2F7;    /* 更浅描边 */
  --line-strong:#CBD5E1;  /* 输入控件描边（比卡片边框深一档，白卡片里也能认出是输入框） */
  --card:#FFFFFF;         /* 卡片面 */
  --bg:#F8FAFC;           /* 页面背景 slate-50 */
  --brand:#1E40AF;        /* 主色 blue-800 */
  --brand-strong:#1E3A8A; /* 主色深 blue-900 */
  --brand-soft:#DBEAFE;   /* 主色浅 blue-100 */
  --focus:#3B82F6;        /* 焦点/强调 blue-500 */
  --red:#C52828;          /* 涨（A股红） */
  --green:#16703B;        /* 跌（A股绿） */
  --amber:#B45309;        /* 警示 */
  --radius:14px;
  --shadow:0 1px 2px rgba(15,23,42,.06), 0 1px 3px rgba(15,23,42,.05);
  --shadow2:0 4px 12px rgba(15,23,42,.08), 0 2px 4px rgba(15,23,42,.05);
}

/* ========== 基础排版 ========== */
html, body, [data-testid="stAppViewContainer"]{
  font-family:-apple-system,BlinkMacSystemFont,"SF Pro SC","PingFang SC","Noto Sans SC","Segoe UI","Microsoft YaHei",sans-serif;
  color:var(--ink);
}
html{ font-size:15px; }
[data-testid="stAppViewContainer"]{ background:var(--bg); }
[data-testid="stAppViewContainer"] p, [data-testid="stAppViewContainer"] li,
[data-testid="stMarkdownContainer"]{ line-height:1.7; }
[data-testid="stHeader"]{ background:transparent; }
.block-container{ padding-top:1.6rem; padding-bottom:4rem; max-width:1480px;
  padding-left:clamp(1rem, 3vw, 3rem) !important; padding-right:clamp(1rem, 3vw, 3rem) !important; }
[data-testid="stAppViewContainer"] .block-container > [data-testid="stVerticalBlock"]{ gap:1.4rem; }
h1,h2,h3{ letter-spacing:-.3px; color:var(--ink); }
[data-testid="stHeadingWithActionElements"] h2{ font-size:1.3rem; font-weight:650; letter-spacing:-.3px; }
[data-testid="stHeadingWithActionElements"] h3{ font-size:1.12rem; font-weight:650; }
hr{ border-color:var(--line); margin:1.6rem 0; }
.up{ color:var(--red); } .down{ color:var(--green); }

/* ========== 顶部 Hero ========== */
.hero{
  display:flex; align-items:flex-end; justify-content:space-between;
  gap:14px; flex-wrap:wrap; padding:6px 2px 18px;
}
.hero-title{ font-size:32px; font-weight:700; letter-spacing:-1px; line-height:1.25; margin:0; }
.hero-sub{ font-size:13.5px; color:var(--sub); margin-top:6px; }
.mini-title{ font-size:12px; color:var(--sub); margin:2px 0 -6px; }

/* 状态胶囊 */
.chips{ display:flex; gap:8px; flex-wrap:wrap; }
.chip{
  display:inline-flex; align-items:center; gap:6px; padding:6px 12px;
  border-radius:10px; background:var(--card); border:1px solid var(--line);
  font-size:12px; color:var(--sub); box-shadow:var(--shadow);
}
/* 页头操作区：状态胶囊与「更新数据」按钮同一行、同高 40px、右对齐，贴标题底边 */
.st-key-hero_actions{ align-items:center; padding-bottom:18px; }
.st-key-hero_actions .chip{ height:40px; padding:0 14px; font-size:13px; white-space:nowrap; }
.st-key-hero_actions .chip.warn{ color:#92400E; background:#FFFBEB; border-color:#FDE68A; }
.st-key-hero_actions [data-testid="stButton"] button{ height:40px; min-height:40px; padding:0 16px; border-radius:10px; white-space:nowrap; }
.st-key-hero_actions [data-testid="stMarkdownContainer"]{ margin:0 !important; }   /* 去掉 Markdown 默认 -15px 下边距，否则胶囊比按钮低 7px */
.st-key-hero_actions [data-testid="stMarkdownContainer"] p{ margin:0; display:flex; }
.chip .dot{ width:7px; height:7px; border-radius:50%; background:var(--green); }
.chip .dot.warn{ background:var(--amber); }

/* ========== 基金详情页头部 ========== */
.fund-head{
  background:var(--card); border:1px solid var(--line); border-radius:18px;
  padding:18px 20px 16px; box-shadow:var(--shadow); margin:6px 0 14px;
}
.fh-top{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.fh-name{ font-size:17px; font-weight:650; letter-spacing:-.3px; }
.fh-code{ font-size:12px; color:var(--sub); font-variant-numeric:tabular-nums; }
.fh-tag{
  font-size:11px; color:var(--sub); background:var(--bg); border-radius:999px;
  padding:2px 9px; border:1px solid var(--line);
}
/* 估值标签：跟踪指数的估值档 + PE/PB 百分位（便宜=绿、贵=红，与涨跌色同一套 token） */
.fh-val{ display:inline-flex; align-items:center; gap:8px; font-size:12px; color:var(--sub);
  border:1px solid var(--line); border-radius:999px; padding:2px 10px 2px 4px; background:var(--card); }
.fh-val b{ font-weight:600; color:var(--ink); font-variant-numeric:tabular-nums; }
.fh-val .lv{ border-radius:999px; padding:1px 8px; font-weight:600; font-size:11px; }
.fh-val .lv.low{ background:#F0FDF4; color:var(--green); }
.fh-val .lv.mid{ background:var(--bg); color:var(--sub); }
.fh-val .lv.high{ background:#FEF2F2; color:var(--red); }
.fh-price{ display:flex; align-items:baseline; gap:12px; margin-top:12px; flex-wrap:wrap; row-gap:8px; }
.fh-price .px{ font-size:32px; font-weight:700; letter-spacing:-1.2px; line-height:1; }
.fh-price .chg{ font-size:15px; font-weight:650; }
.fh-price .chg.up{ color:var(--red); }
.fh-price .chg.down{ color:var(--green); }
.fh-price .fh-date{ margin-left:8px; }
.fh-date{ font-size:12px; color:var(--sub); margin-left:auto; }
.fh-price-label,.fh-price small{font-size:12px; font-weight:400; color:var(--sub)}

/* 一行统计文字 */
.stats-row{
  display:flex; flex-wrap:wrap; gap:8px 30px; padding:16px 4px 2px;
  font-size:12px; color:var(--sub);
}
.stats-row .item b{
  display:block; font-size:15.5px; color:var(--ink); font-weight:600;
  margin-top:3px; font-variant-numeric:tabular-nums;
}
.stats-row .item b.up{ color:var(--red); }
.stats-row .item b.down{ color:var(--green); }

/* 阶段涨幅网格 */
.grid4{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-top:10px; }
.grid4 .cell{
  background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:11px 13px;
}
.grid4 .cell .k{ font-size:11.5px; color:var(--sub); }
.grid4 .cell .v{ font-size:15px; font-weight:600; margin-top:3px; font-variant-numeric:tabular-nums; }
.grid4 .cell .v.up{ color:var(--red); }
.grid4 .cell .v.down{ color:var(--green); }

/* 阶段涨跌幅胶囊 */
.stage{ display:flex; flex-wrap:wrap; gap:8px; margin:12px 0 2px; }
.stage>span{
  background:var(--card); border:1px solid var(--line); border-radius:999px;
  padding:6px 13px; font-size:12.5px; font-variant-numeric:tabular-nums;
}

/* ========== Tabs（Streamlit 自定义 tab） ========== */
[data-testid="stTabs"] [role="tablist"]{
  gap:0; border-bottom:1px solid var(--line); overflow-x:auto; scrollbar-width:none;
}
[data-testid="stTabs"] [role="tablist"]::-webkit-scrollbar{ display:none; }
[data-testid="stTabs"] [role="tab"]{
  padding:12px 4px 14px; margin-right:30px; font-size:15px; color:var(--sub);
  letter-spacing:-.1px; white-space:nowrap; transition:color .15s ease;
}
[data-testid="stTabs"] [role="tab"]:hover{ color:var(--ink); }
[data-testid="stTabs"] [role="tab"][aria-selected="true"]{
  color:var(--brand) !important; font-weight:650;
}
[data-testid="stTabs"] [data-testid="stTabPanel"]{ padding-top:16px; }

/* ========== 卡片容器（st.container(border=True)） ========== */
[data-testid="stVerticalBlockBorderWrapper"]{
  background:var(--card); border:1px solid var(--line) !important;
  border-radius:16px; box-shadow:var(--shadow);
}
[data-testid="stVerticalBlockBorderWrapper"] > [data-testid="stVerticalBlock"]{ padding:6px 4px; }
[data-testid="stVerticalBlockBorderWrapper"]:hover{ box-shadow:var(--shadow2); }

/* ========== 指标卡 ========== */
[data-testid="stMetric"]{
  background:var(--card); border:1px solid var(--line); border-radius:16px;
  padding:16px 18px; box-shadow:var(--shadow);
}
[data-testid="stMetricLabel"] p{
  font-size:11.5px !important; letter-spacing:.6px; color:var(--sub) !important; font-weight:500;
}
[data-testid="stMetricValue"]{ font-size:27px !important; font-weight:650; letter-spacing:-.6px; }
[data-testid="stMetricDelta"]{ font-size:12px !important; }

/* ========== 按钮 ========== */
.stButton>button, .stDownloadButton>button{
  border-radius:10px; border:1px solid var(--line); font-weight:500; font-size:14px;
  min-height:42px; padding:.5rem 1.3rem; transition:all .15s ease;
}
.stButton>button:hover{ border-color:var(--brand-soft); transform:translateY(-1px); box-shadow:var(--shadow); }
.stButton>button[kind="primary"]{
  background:var(--brand); border-color:var(--brand); color:#fff;
}
.stButton>button[kind="primary"]:hover{ background:var(--brand-strong); border-color:var(--brand-strong); }

/* ========== 表格（dataframe 与自定义 .tbl 统一观感） ========== */
[data-testid="stDataFrame"]{
  border:1px solid var(--line); border-radius:14px; overflow:hidden;
  box-shadow:var(--shadow); background:var(--card);
}
[data-testid="stDataFrame"] [role="grid"]{ font-size:13.5px; }
.tbl{
  width:100%; border-collapse:separate; border-spacing:0; font-size:14px;
  background:var(--card); border:1px solid var(--line); border-radius:12px;
  overflow:hidden; box-shadow:var(--shadow);
}
.tbl th{
  background:var(--bg); color:var(--sub); font-weight:500; font-size:12px;
  letter-spacing:.4px; text-align:left; padding:11px 14px; border-bottom:1px solid var(--line);
}
.tbl td{ padding:11px 14px; border-bottom:1px solid var(--line-soft); }
.tbl tbody tr:last-child td{ border-bottom:none; }
.tbl tbody tr:hover td{ background:rgba(59,130,246,.04); }
.tbl tr.total td{ font-weight:650; background:var(--bg); }
.tbl td.num, .tbl th.num{ text-align:right; font-variant-numeric:tabular-nums; }
.tbl .up{ color:var(--red); } .tbl .down{ color:var(--green); }
.tbl .muted{ color:var(--sub); }
/* 宽表横向滚动容器（月度矩阵） */
.tblwrap{ overflow-x:auto; border-radius:12px; box-shadow:var(--shadow); }
.tblwrap .tbl{ border-radius:12px; }
.tbl.wide{ min-width:940px; }
.tbl.wide th:first-child, .tbl.wide td:first-child{
  position:sticky; left:0; background:var(--card); z-index:1;
}
.tbl.wide th:first-child{ background:var(--bg); }

/* ========== 提示条 ========== */
[data-testid="stAlert"]{ border-radius:12px; border:1px solid var(--line); }
div[data-testid="stAlert"]{ background:#EFF6FF; border-color:var(--brand-soft) !important; }
div[data-testid="stAlert"] p{ color:var(--brand-strong); }

/* ========== 侧边栏 ========== */
[data-testid="stSidebar"]{ background:var(--card); border-right:1px solid var(--line); }
[data-testid="stSidebar"] .block-container{ padding:1.4rem 1.2rem 2.4rem; }
.sb-brand{
  display:flex; align-items:center; gap:10px; margin:2px 0 24px;
  font-size:17px; font-weight:700; letter-spacing:-.2px; color:var(--ink);
}
.sb-brand .mark{
  width:32px; height:32px; border-radius:10px; display:inline-flex; align-items:center; justify-content:center;
  background:linear-gradient(135deg,#1E40AF,#3B82F6); color:#fff; flex:0 0 auto;
}
.sb-brand .mark svg{ width:18px; height:18px; }
.sb-label{ font-size:11px; color:var(--muted); letter-spacing:1px; margin:20px 0 5px; text-transform:uppercase; }
.sb-divider{ border-top:1px solid var(--line); margin:18px 0 12px; }
/* 数据拉取失败提示 */
.sb-fetch-err{
  margin-top:10px; padding:9px 11px; font-size:12px; line-height:1.5;
  border-radius:10px; background:#FEF2F2; border:1px solid #FECACA; color:var(--red);
}
.sb-fetch-err-detail{ margin-top:4px; color:#991B1B; font-size:11px; word-break:break-all; }
/* 单选组做成等宽"列表项"，选中项浅底高亮 */
[data-testid="stSidebar"] [data-testid="stElementContainer"]:has([data-testid="stRadio"]),
[data-testid="stSidebar"] [data-testid="stRadio"],
[data-testid="stSidebar"] [data-testid="stRadioGroup"],
[data-testid="stSidebar"] [role="radiogroup"]{ width:100% !important; }
[data-testid="stSidebar"] [role="radiogroup"]{ gap:4px; display:flex; flex-direction:column; }
[data-testid="stSidebar"] [role="radiogroup"] > div{ width:100% !important; }
[data-testid="stSidebar"] [role="radiogroup"] label{
  border:1px solid transparent; border-radius:10px; padding:9px 12px;
  font-size:14px; transition:background .12s; cursor:pointer;
  display:flex; align-items:center; width:100%; box-sizing:border-box;
}
[data-testid="stSidebar"] [role="radiogroup"] label:hover{ background:var(--bg); }
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked){
  background:var(--brand-soft); border-color:var(--brand-soft); color:var(--brand-strong); font-weight:600;
}
[data-testid="stSidebar"] [data-testid="stButton"]>button{
  width:100%; justify-content:flex-start; color:var(--sub); font-weight:500;
}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"]{ font-size:11px; margin-top:6px; }

/* ========== 基金走势页：含阶段数字的概览 / 走势分析 ========== */
/* 基金走势 / 收益日历 / 基金对比 共用同一卡片容器 */
.st-key-trend_head, .st-key-trend_chart, .st-key-trend_cal, .st-key-cmp_head, .st-key-cmp_chart,
.st-key-cmp_stage, .st-key-val_head, .st-key-val_table, .st-key-val_chart{
  background:var(--card); border:1px solid var(--line); border-radius:16px;
  padding:24px !important; margin-bottom:24px;
}
.st-key-cmp_head .sec-head{margin-bottom:12px}
.st-key-trend_chart{container-type:inline-size}
.st-key-trend_chart iframe,.st-key-trend_chart [data-testid="stElementContainer"]:has(>iframe){height:800px !important;flex-basis:800px !important}
@container(max-width:650px){
  .st-key-trend_chart iframe,.st-key-trend_chart [data-testid="stElementContainer"]:has(>iframe){height:850px !important;flex-basis:850px !important}
}
@container(max-width:420px){
  .st-key-trend_chart iframe,.st-key-trend_chart [data-testid="stElementContainer"]:has(>iframe){height:940px !important;flex-basis:940px !important}
}
.st-key-trend_head [data-testid="stHorizontalBlock"]{align-items:center; gap:20px}
/* 视图切换（单只走势 / 多只对比）：tab 按钮组，与输入控件同圆角、同高度档位 */
.st-key-trend_mode_switch{margin:0 0 6px}
.st-key-trend_mode_switch [role="radiogroup"]{gap:2px;padding:3px;background:var(--bg);
  border:1px solid var(--line-strong);border-radius:12px;width:fit-content}
.st-key-trend_mode_switch button{border:0 !important;border-radius:9px !important;
  min-height:34px;height:34px;padding:0 14px;background:transparent;color:var(--sub)}
.st-key-trend_mode_switch button p{font-size:13px !important;line-height:1.4;color:inherit}
.st-key-trend_mode_switch button:hover{color:var(--ink)}
.st-key-trend_mode_switch button[aria-checked="true"]{background:var(--card) !important;
  box-shadow:0 1px 2px rgba(15,23,42,.08)}
.st-key-trend_mode_switch button[aria-checked="true"] p{color:var(--brand) !important;font-weight:600}
.fund-head.flat{border:none; box-shadow:none; padding:0; margin:0; background:transparent}
.fh-top,.fh-price{flex-wrap:wrap; row-gap:8px}
.fh-price .fh-date{margin-left:0}
.sec-head{display:flex; align-items:center; flex-wrap:wrap; gap:12px; margin:0 0 16px}
.sec-head .t{font-size:17px; font-weight:600; color:var(--ink)}
.sec-head .r{margin-left:auto; font-size:12px; color:var(--sub)}
.sec-note{font-size:12px; color:var(--sub); line-height:1.8; margin-top:12px}
.stage-summary{border-top:1px solid var(--line);margin-top:16px;padding-top:14px}
.stage-summary-title{font-size:12px;font-weight:400;color:var(--sub);margin-bottom:10px}
.stage-metrics{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px}
.stage-metric{min-width:0;cursor:default}
.stage-label{display:block;font-size:12px;color:var(--sub);line-height:1.6}
.stage-return{display:block;margin-top:4px;font-size:22px;font-weight:600;line-height:1.4;
  font-variant-numeric:tabular-nums;white-space:nowrap;letter-spacing:-.3px}
.stage-return.up{color:var(--red)}.stage-return.down{color:var(--green)}
.stage-return.neutral{color:var(--sub)}

@media(max-width:600px){
  .st-key-trend_head,.st-key-trend_chart,.st-key-trend_cal,.st-key-cmp_head,.st-key-cmp_chart,.st-key-cmp_stage,.st-key-val_head,.st-key-val_table,.st-key-val_chart{padding:14px !important;margin-bottom:18px}
  .stage-metrics{grid-template-columns:repeat(3,minmax(0,1fr));gap:10px 6px}.stage-return{font-size:16px;letter-spacing:-.4px}
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
.sig .side{ font-size:12.5px; color:var(--sub); white-space:nowrap; text-align:right; }
.sig .side b{ display:block; font-size:11px; color:var(--muted); font-weight:400; margin-bottom:1px; }
.sig.calm{ border-left-color:var(--green); }
.sig.off{ border-left-color:var(--line); opacity:.72; }

/* ========== 控件（统一 44px 触控、12px 圆角） ========== */
/* Streamlit ≥1.6x 的 selectbox / multiselect 改为 react-aria ComboBox，输入框是 .react-aria-ComboBox 的第一层 div；
   主题 secondaryBackgroundColor=白色导致默认边框也是白色，放在白卡片里看不见 → 这里显式给边框、底色和悬停/聚焦态。
   旧版 baseweb 选择器保留兼容。 */
[data-testid="stSelectbox"] .react-aria-ComboBox > div,
[data-testid="stMultiSelect"] .react-aria-ComboBox > div,
[data-testid="stSelectbox"] [data-baseweb="select"] > div{
  border:1px solid var(--line-strong) !important; border-radius:12px !important; min-height:44px;
  background:var(--card) !important; box-shadow:0 1px 2px rgba(15,23,42,.04);
  transition:border-color .15s, box-shadow .15s;
}
[data-testid="stSelectbox"] .react-aria-ComboBox > div:hover,
[data-testid="stMultiSelect"] .react-aria-ComboBox > div:hover{ border-color:#94A3B8 !important; }
[data-testid="stSelectbox"] .react-aria-ComboBox > div:focus-within,
[data-testid="stMultiSelect"] .react-aria-ComboBox > div:focus-within,
[data-testid="stSelectbox"] [data-baseweb="select"] > div:focus-within{
  border-color:var(--focus) !important; box-shadow:0 0 0 3px rgba(59,130,246,.12) !important;
}
[data-testid="stSelectbox"] .react-aria-ComboBox input::placeholder,
[data-testid="stMultiSelect"] .react-aria-ComboBox input::placeholder{ color:var(--muted); opacity:1; }
/* 多选已选标签：默认用主题主色（红），而红色在本项目只表示上涨 → 改为中性蓝灰标签 */
[data-testid="stMultiSelectTagsContainer"] [data-tag]{
  background:var(--brand-soft) !important; color:var(--brand-strong) !important;
  border-radius:8px !important; font-weight:500;
}
[data-testid="stMultiSelectTagsContainer"] [data-tag] *{ color:var(--brand-strong) !important; }
[data-testid="stMultiSelectTagsContainer"] [data-tag] button:hover{ opacity:.7; }
/* 数字框 / 日期框：同样是白底白边，统一成和下拉框一样的边框与聚焦态 */
[data-testid="stNumberInputContainer"], [data-testid="stDateInputField"], [data-testid="stTextInputRootElement"]{
  border:1px solid var(--line-strong) !important; border-radius:12px !important; min-height:44px;
  background:var(--card) !important; box-shadow:0 1px 2px rgba(15,23,42,.04); transition:border-color .15s, box-shadow .15s;
}
[data-testid="stNumberInputContainer"]:hover, [data-testid="stDateInputField"]:hover, [data-testid="stTextInputRootElement"]:hover{ border-color:#94A3B8 !important; }
[data-testid="stNumberInputContainer"]:focus-within, [data-testid="stDateInputField"]:focus-within, [data-testid="stTextInputRootElement"]:focus-within{
  border-color:var(--focus) !important; box-shadow:0 0 0 3px rgba(59,130,246,.12) !important;
}
[data-testid="stNumberInputField"], [data-testid="stDateInputField"] input{ border:0 !important; outline:none !important; background:transparent !important; }
[data-testid="stTextInput"] input, [data-testid="stNumberInput"] input{
  border-radius:12px !important; min-height:44px;
}
[data-testid="stDateInput"] input{ border-radius:12px !important; min-height:44px; }
[data-testid="stNumberInput"] button{ border-radius:0 12px 12px 0; }

/* ========== 展开器 ========== */
[data-testid="stExpander"]{
  border:1px solid var(--line) !important; border-radius:14px !important;
  background:var(--card); box-shadow:var(--shadow); overflow:hidden;
}
[data-testid="stExpander"] details summary{ padding:14px 18px; font-weight:600; }
[data-testid="stExpander"] details summary:hover{ background:var(--bg); }

/* ========== 进度条 ========== */
[data-testid="stProgress"] > div{ border-radius:999px; overflow:hidden; }
[data-testid="stProgress"] > div > div{ border-radius:999px; }

/* ========== 隐藏不需要的 UI ========== */
[data-testid="stAppDeployButton"]{ display:none; }
[data-testid="stDeployButton"]{ display:none; }
[data-testid="stDecoration"]{ display:none; }
[data-testid="stStatusWidget"]{ display:none; }
#MainMenu{ visibility:hidden; }
/* 注意：不要隐藏 stHeader / stToolbar 容器，侧边栏"展开"按钮在里面 */

/* ========== 响应式 ========== */
@media(max-width:640px){
  .hero-title{ font-size:26px; }
  .grid4{ grid-template-columns:repeat(2,1fr); }
  .quad-grid{ grid-template-columns:1fr !important; }
  [data-testid="stMetricValue"]{ font-size:22px !important; }
  .block-container{ padding-left:1rem; padding-right:1rem; }
}
/* 无障碍：尊重减少动效偏好 */
@media (prefers-reduced-motion: reduce){
  *{ transition:none !important; animation:none !important; }
}
</style>""", unsafe_allow_html=True)

# 回测独立入口：不触发自动拉行情、账户重放及实盘信号状态写入。
if st.query_params.get("view") == "performance":
    from streamlit_app.performance import render_performance
    render_performance(PROJECT_ROOT)
    st.stop()

# ============================================================
# 信号 → 操作 映射表
# ============================================================
_BENCH_COL = {
    "B-RP": "V3-B 风险平价(20d)_100% RP",
    "B-Con": "V3-B 保守增强(20d)_100% RP",
    "V3c": "V3c 多元_100% RP",
}
_UP, _DOWN, _BRAND, _SUB = "#C52828", "#16703B", "#1E40AF", "#475569"


def _cn_date(v):
    """日期 → 2026年10月16日"""
    t = pd.Timestamp(v)
    return f"{t.year}/{t.month:02d}/{t.day:02d}"


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
def _asset_series(asset, price=False):
    """读取单只基金自己的完整历史（不受多资产公共区间限制）。

    price=False: 返回累计净值（data/{name}.csv 的 close 列，回测口径）。
    price=True:  返回场内收盘价（data/price_{name}.csv 的 close 列，看盘口径）。
    """
    fname = _LIVE_ASSETS.get(asset)
    if not fname:
        return None
    fp = DATA_DIR / (f"price_{fname}.csv" if price else f"{fname}.csv")
    if not fp.exists():
        return None
    try:
        df = pd.read_csv(fp, parse_dates=["date"], index_col="date")
        return df["close"].dropna()
    except Exception:
        return None


# HTML 组件共享样式：走势分析 / 收益日历 / 基金对比 三个 iframe 组件共用，保证视觉完全一致。
# 改样式只改这里；颜色与 :root 设计 token 同值（iframe 内拿不到父页面 CSS 变量）。
_COMP_BASE_CSS = r"""html,body{margin:0;padding:0;background:#fff;color:#334155;font:13px/1.6 -apple-system,"PingFang SC",sans-serif}
*{box-sizing:border-box}#wrap{position:relative;width:100%}
.heading{display:flex;align-items:center;justify-content:space-between;gap:12px}
h3{margin:0;font-size:17px;font-weight:600;color:#0F172A;display:flex;align-items:center;gap:8px}
.icon{width:17px;height:17px;fill:none;stroke:currentColor;stroke-width:1.5;vertical-align:middle}
#updating{font-size:12px;color:#475569;visibility:hidden}#wrap[aria-busy="true"] #updating{visibility:visible}
.controls{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-top:18px;border-bottom:1px solid #E2E8F0}
#range-controls{display:flex;gap:4px;min-width:0;overflow-x:auto;scrollbar-width:none}#range-controls::-webkit-scrollbar{display:none}
button[data-range]{font:inherit;font-size:14px;border:0;border-bottom:2px solid transparent;border-radius:0;background:transparent;
  color:#475569;padding:10px 11px;white-space:nowrap;cursor:pointer;min-height:42px;flex:none}
button[data-range]:hover{background:rgba(59,130,246,.06);color:#0F172A}
button[data-range][aria-pressed="true"]{font-weight:600;color:#C52828;border-bottom-color:#C52828}
button:focus-visible,select:focus-visible,#chart:focus-visible{outline:2px solid #3B82F6;outline-offset:2px}
select{font:inherit;font-size:14px;font-weight:500;border:1px solid #E2E8F0;border-radius:12px;color:#0F172A;
  padding:6px 34px 6px 14px;min-height:42px;cursor:pointer;-webkit-appearance:none;-moz-appearance:none;appearance:none;
  background:#fff url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath d='M3 4.5l3 3 3-3' fill='none' stroke='%2394A3B8' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") no-repeat right 12px center;
  transition:border-color .15s,background-color .15s}
select:hover{border-color:#CBD5E1;background-color:#F8FAFC}
select:focus{outline:none;border-color:#3B82F6;box-shadow:0 0 0 3px rgba(59,130,246,.12)}
#period{margin-bottom:4px;min-width:96px}
.state-line{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin:12px 0 8px;font-size:12px;color:#475569}
.date-line{display:flex;align-items:center;gap:6px}#selection{color:#475569}#selection[data-custom="true"]{font-weight:600}
#range{font-variant-numeric:tabular-nums}#notice{min-height:20px;font-size:12px;color:#475569}
#chart{display:block;width:100%;touch-action:pan-y;cursor:grab;user-select:none}
#chart.dragging{cursor:grabbing}
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
@media(max-width:520px){#range-controls{gap:0;width:100%}
  button[data-range]{padding:8px 9px;font-size:12px}.controls{flex-wrap:wrap;gap:6px}#period{margin-left:auto}
  .state-line{font-size:11px}.summary-result b{font-size:21px}.summary-prices{flex-wrap:wrap;font-size:12px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto}}
"""


def _range_buttons(active):
    """区间 tab 按钮（走势分析 / 走势对比共用），选项来自 _TREND_RANGES。"""
    tips = {"今年来": "以去年最后一个交易日为基准"}
    return "".join(
        f'<button data-range="{r}" aria-pressed="{str(r == active).lower()}"'
        + (f' title="{tips[r]}"' if r in tips else "") + f">{r}</button>"
        for r in _TREND_RANGES)


@st.cache_data(ttl=300, show_spinner=False)
def _asset_display_series(asset):
    """回测资产的展示用净值：复权单位净值（最新值 = 单位净值，每日涨跌 = 官方日涨幅）。

    data/{name}.csv 存的是累计净值（= 单位净值 + 历年分红，分红不再投资），按它算的涨跌幅会被分红
    稀释（510300 在 2026/10/22：累计净值 −1.51% vs 官方 −1.82%）。策略回测仍用累计净值，页面展示改用这里。
    """
    fname = _LIVE_ASSETS.get(asset)
    fp = DATA_DIR / "nav_detail" / f"{fname}.csv"
    if not fname or not fp.exists():
        return None
    try:
        d = pd.read_csv(fp, parse_dates=["date"]).dropna(subset=["unit_nav"]).set_index("date").sort_index()
        chg = pd.to_numeric(d["daily_chg"], errors="coerce")
        chg = chg.fillna(pd.to_numeric(d["acc_nav"], errors="coerce").pct_change() * 100)   # 少数缺日涨幅的日子用累计净值补
        idx = (1 + FL.adjusted_returns(d["unit_nav"], chg)).cumprod()
        return (idx * float(d["unit_nav"].iloc[-1]) / float(idx.iloc[-1])).rename(asset)
    except Exception:
        return None


# 区间与阶段：走势页、账户净值曲线共用（定义要在 _scroll_chart_html 之前）
_TREND_RANGES = {
    "近1月": ("months", 1), "近3月": ("months", 3), "近6月": ("months", 6),
    "近1年": ("years", 1), "近3年": ("years", 3), "近5年": ("years", 5),
    "今年来": ("ytd", 0), "全部": ("all", 0),
}
_TREND_STAGES = {
    "近1月": ("months", 1), "近3月": ("months", 3), "近6月": ("months", 6),
    "近1年": ("years", 1), "近3年": ("years", 3), "今年来": ("ytd", 0),
}


def _scroll_chart_html(labels, values, win, height=540, rets=None, revision=0, histories=None):
    """全历史数据 + 有界索引视窗；只绘制可见部分，不创建超宽画布。

    一张图三层面板，共用同一条时间轴：上方净值折线（含起点虚线），
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
__BASE_CSS__
</style>
<div id="wrap" aria-busy="false">
<div class="heading"><h3><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4v16h16M7 14l4-5 4 3 5-7"/></svg>走势分析</h3><span id="updating" role="status">正在更新</span></div>
<div class="controls"><div id="range-controls" role="group" aria-label="常用区间">
__RANGE_BTNS__
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
  // 切「单只/多只」或换基金都会重建 iframe，JS 里的选择随之丢失 → 存一份到 localStorage（srcdoc 同源可访问），重建时还原
  const STORE = 'awTrend.single';
  const memo = (() => { try { return JSON.parse(localStorage.getItem(STORE) || '{}'); } catch (e) { return {}; } })();
  const saveMemo = () => { try { localStorage.setItem(STORE, JSON.stringify({period, range: lastRange})); } catch (e) {} };
  let period = D.histories[memo.period] ? memo.period : '日';
  let lastRange = (D.histories[period].windows || {})[memo.range] ? memo.range : '近1月';
  let activeRange = lastRange, customDates = null;
  let P = D.histories[period], n = P.prices.length;
  const H = D.height, L = 64, R = 16, T = 32, B = 32, GAP = 30, minCount = 1;
  // 绘图区主次：净值55%、累计变化27%、单期变化18%。
  const PH = H - T - B - GAP * 2, AH = PH * .55, BH = PH * .27, CH = PH * .18;
  const bTop1 = T + AH + GAP, bTop2 = bTop1 + BH + GAP;
  let initialCount = P.windows[lastRange].count, initialStart = P.windows[lastRange].start;
  let count = initialCount, start = initialStart, W = 0, PW = 0, frame = 0;
  let dragging = null, pinned = null, hover = null;
  const periodControl = document.getElementById('period');
  for (const option of periodControl.options) option.disabled = !D.histories[option.value];
  periodControl.value = period;
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
    } else { start = initialStart; count = initialCount; }
    pinned = hover = null; wrap.setAttribute('aria-busy', 'true'); requestDraw(); saveMemo();
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
    marks += `<polyline points="${pts.join(' ')}" fill="none" stroke="#3B82F6" stroke-width="2" stroke-linejoin="round"/>`;
    for (let i = first; i <= last; i++) if (valid(P.prices[i])) {
      marks += `<circle data-index="${i}" cx="${x(i)}" cy="${y(P.prices[i])}" r="${Math.min(3.5,Math.max(1,step*.12))}" fill="#3B82F6"/>`;
    }
    // 起点：净值面板上画一条虚线并圈出该点，相对起点柱全部以它为 0% 基准
    const y0 = startPx ? y(startPx) : null;
    if (y0 !== null && y0 >= T && y0 <= T + AH) {
      grid += `<line x1="${L}" y1="${y0}" x2="${W-R}" y2="${y0}" stroke="#94A3B8" stroke-dasharray="2 4" opacity=".85"/>`;
      marks += `<circle cx="${x(first)}" cy="${y0}" r="4.5" fill="none" stroke="#3B82F6" stroke-width="1.5" opacity=".9"/>`;
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
        + `<text x="${L-8}" y="${top+11}" text-anchor="end" font-size="11" fill="#475569">+${bmax.toFixed(2)}%</text>`
        + `<text x="${L-8}" y="${zero+3.5}" text-anchor="end" font-size="11" fill="#475569">0%</text>`
        + `<text x="${L-8}" y="${top+paneHeight-1}" text-anchor="end" font-size="11" fill="#475569">-${bmax.toFixed(2)}%</text>`;
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
    // 最高/最低直接标注在净值图内；仅标真实可见点，并对标签做碰撞处理。
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
        marks += `<circle cx="${x(i)}" cy="${y(P.prices[i])}" r="4" fill="${k === 0 ? '#C52828' : '#fff'}" stroke="#C52828" stroke-width="1.5"/>`;
        annotations += `<g data-extreme="${kind}" data-index="${i}" data-price="${P.prices[i]}" data-date="${esc(P.dates[i])}">`
          + `<rect x="${box.x}" y="${box.y}" width="${labelW}" height="${labelH}" rx="6" fill="#fff" fill-opacity=".96" stroke="#FECACA"/>`
          + `<text x="${box.x+10}" y="${box.y+17}" font-size="12" fill="#C52828">${label} ${price(P.prices[i])}</text>`
          + `<text x="${box.x+10}" y="${box.y+33}" font-size="11" fill="#475569">${esc(P.dates[i])}</text></g>`;
      });
    }
    svg.innerHTML = `<defs><clipPath id="plot-clip"><rect x="${L}" y="${T-5}" width="${PW}" height="${H-T-B+10}"/></clipPath></defs>${grid}<g clip-path="url(#plot-clip)">${marks}<line id="guide" y1="${T}" y2="${H-B}" stroke="#94A3B8" stroke-dasharray="4 4" visibility="hidden"/></g>${ticks}${annotations}`;
    wrap.dataset.bars = String(cntRel); wrap.dataset.stepBars = String(cntStep);
    const change = relAt(last);
    const amplitude = hiI !== null && loI !== null && P.prices[loI] > 0 ? (P.prices[hiI]/P.prices[loI]-1)*100 : null;
    document.getElementById('stats').innerHTML =
      `<div class="summary-main"><div class="summary-result"><span>当前区间变化</span>`
      + `<b id="change" data-value="${valid(change) ? change : ''}" style="color:${color(change)}">${pct(change)}</b></div>`
      + `<div class="summary-prices"><span><small>起点价</small><b id="start-price" data-value="${startPx ?? ''}">${price(startPx)}</b></span>`
      + `<span aria-hidden="true">→</span><span><small>终点价</small><b id="end-price" data-value="${P.prices[last] ?? ''}">${price(P.prices[last])}</b></span></div></div>`
      + `<div class="amp-row"><span>净值区间振幅</span><b id="amplitude" data-value="${valid(amplitude) ? amplitude : ''}">${valid(amplitude) ? amplitude.toFixed(2)+'%' : '—'}</b>`
      + `<small>最高净值 ÷ 最低净值 − 1 · 当前 ${visibleCount} 期 / 全历史 ${n} 期</small></div>`;
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
      + `<div class="tip-row"><span class="tip-label">净值</span><b>${price(px)}</b></div>`
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
    return (template.replace("__BASE_CSS__", _COMP_BASE_CSS)
            .replace("__RANGE_BTNS__", _range_buttons("近1月")).replace("__CHART_DATA__", payload))


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


def _render_table(columns, rows, totals=None, min_width=None):
    """渲染 HTML 表格。columns: [(标题, 对齐)]，rows: list[list[str]]。

    totals 传入一行（list[str]）时会渲染为高亮的合计行。
    min_width：给窄屏（手机）用，列多时不再压缩换行，改为在卡片内横向滑动。
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
    style = f' style="min-width:{int(min_width)}px"' if min_width else ""
    table = f'<table class="tbl"{style}><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'
    if min_width:
        table = f'<div class="tblwrap">{table}</div>'
    st.markdown(table, unsafe_allow_html=True)


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


_QDII_LAG = {"us_sp500", "wti"}     # QDII 净值比境内晚 1 个交易日公布


def _expected_nav_date(now, extra_lag=0):
    """此刻应当已公布的最新净值日：工作日 21:00 后算当天，否则算上一个工作日；QDII 再往前推。"""
    d = now.date() if (now.weekday() < 5 and now.hour >= 21) else now.date() - pd.Timedelta(days=1)
    while d.weekday() >= 5:
        d -= pd.Timedelta(days=1)
    for _ in range(extra_lag):
        d -= pd.Timedelta(days=1)
        while d.weekday() >= 5:
            d -= pd.Timedelta(days=1)
    return d


def _trading_days_ago(last_date, today, extra_lag=0):
    """本地最后一条净值比「应当已公布的最新净值日」少了几个交易日（0 = 已是最新）。
    旧版按日历天估算且下限为 1，10/22 的数据在 10/24 也显示「最新」，导致 10/23 漏拉。"""
    expected = _expected_nav_date(pd.Timestamp.now() if today is None else pd.Timestamp(today) + pd.Timedelta(hours=12), extra_lag)
    if last_date >= expected:
        return 0
    return int(len(pd.bdate_range(last_date + pd.Timedelta(days=1), expected)))

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
            results.append((name, _trading_days_ago(last_date, None, 1 if name in _QDII_LAG else 0)))
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
    f'<div class="sb-brand"><span class="mark">{_LOGO_SVG}</span>全天候再平衡</div>',
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

def _fetch_everything():
    """拉取全部数据（不依赖页面会话，前台按钮和后台线程共用）。返回 (错误列表, 说明列表)。

    8 类资产行情 + 场内价格 + 单位净值明细 + 沪深300 PE/PB（策略信号用）+ 指数估值快照/历史/点位，
    基金名录超过 7 天也顺带刷新（搜索框的静态名录文件会在下次渲染时自动重写）。
    """
    from allweather.fetch import fetch_all, fetch_prices, update_nav_detail
    from allweather import valuation as _val
    _ok, _errs, _uptodate = fetch_all(force=False, end=date.today().strftime("%Y%m%d"))
    _pok, _perr = fetch_prices()                   # 场内价格（看盘口径）
    _nmsg, _nerr = update_nav_detail()             # 单位净值 + 官方日涨幅（页面展示口径）
    _vmsg, _verr = _val.update_all()
    _msgs = list(_nmsg) + list(_vmsg)
    try:
        import time as _t
        if not FL.NAME_CACHE.exists() or _t.time() - FL.NAME_CACHE.stat().st_mtime > 7 * 86400:
            _msgs.append(FL.refresh_names())
    except Exception:
        pass
    st.cache_data.clear()
    return list(_errs) + list(_perr) + list(_nerr) + list(_verr), _msgs


def _update_all_data():
    """「更新数据」按钮：前台同步拉取，结果写进本会话的提示。"""
    _errs, _msgs = _fetch_everything()
    st.session_state.fetch_errors = _errs
    st.session_state.fetch_summary = _msgs
    st.session_state.fetched_lag = _check_data_staleness()[0]   # 拉过之后仍缺 → 节假日/尚未公布，不再标红
    st.session_state.auto_fetch_done = True
    return _errs


@st.cache_resource
def _bg_fetch_state():
    """全进程共享的后台更新状态（所有浏览器会话共用一个，避免多人/多次刷新重复拉取）。"""
    return {"thread": None, "errors": None, "finished": 0.0}


def _start_background_fetch():
    """数据滞后时在后台线程里更新，页面先用现有数据立刻显示，不再整页卡住等拉取。

    同一时间只跑一个；30 分钟内拉过（无论成功与否）就不再自动拉，避免净值尚未公布时每次刷新都重拉。
    返回 "running" / "started" / "recent"。
    """
    import threading
    import time as _t
    stt = _bg_fetch_state()
    if stt["thread"] is not None and stt["thread"].is_alive():
        return "running"
    marker = DATA_DIR / ".last_auto_fetch"
    if marker.exists() and _t.time() - marker.stat().st_mtime < 1800:
        return "recent"
    marker.touch()

    def _run():
        try:
            stt["errors"], _ = _fetch_everything()
        except Exception as e:  # noqa: BLE001
            stt["errors"] = [f"后台更新失败：{str(e)[:120]}"]
        finally:
            stt["finished"] = _t.time()

    th = threading.Thread(target=_run, name="aw-auto-fetch", daemon=True)
    th.start()
    stt["thread"] = th
    return "started"


# 自动更新：数据滞后时后台拉取（不阻塞页面）；拉完后下一次操作/刷新即显示新数据
staleness_days, staleness_asset = _check_data_staleness()
if "auto_fetch_done" not in st.session_state:
    st.session_state.auto_fetch_done = False
_bg_status = None
if staleness_days is not None and staleness_days >= 1 and not st.session_state.auto_fetch_done:
    _bg_status = _start_background_fetch()
if (_bg_fetch_state()["thread"] is not None and _bg_fetch_state()["thread"].is_alive()):
    st.sidebar.caption("⟳ 后台正在更新数据，完成后刷新页面即可看到最新值")

# 按钮文案 = 动作（更新数据），状态写在提示里；「数据已是最新」像状态标签，不像能点的按钮
if staleness_days is not None:
    # 本会话已拉过且仍缺同样天数 → 数据源还没出（节假日/当晚未公布），不算滞后
    _already = st.session_state.get("fetched_lag") == staleness_days
    if staleness_days == 0 or _already:
        _data_state = ("ok", "更新数据", "已是最新净值；点击同时更新行情、净值明细、沪深300估值和指数估值")
    elif staleness_days > 5:
        _data_state = ("err", "更新数据", f"{staleness_asset} 缺 {staleness_days} 个交易日的净值，点击拉取")
    else:
        _data_state = ("warn", "更新数据", f"{staleness_asset} 缺 {staleness_days} 个交易日的净值，点击拉取")
else:
    _data_state = ("err", "拉取数据", "数据缺失，点击拉取")

# 数据拉取失败提示：任何资产拉取失败都在侧边栏顶部醒目展示
if st.session_state.get("fetch_errors"):
    _errs = st.session_state.fetch_errors
    _err_txt = "<br>".join(html_escape(e) for e in _errs)
    st.sidebar.markdown(
        f'<div class="sb-fetch-err">⚠️ 数据拉取失败 {len(_errs)} 项'
        f'<div class="sb-fetch-err-detail">{_err_txt}</div></div>',
        unsafe_allow_html=True,
    )

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
# 我的持仓（策略位置 → 我实际买的基金）+ 按份额记账的账户重放
# ============================================================
from allweather import holdings as HG          # noqa: E402
from allweather import alerts as AL            # noqa: E402
from allweather import benchmark as BM         # noqa: E402

_hg_state = HG.load()
holdings = _hg_state["holdings"]
HG_SLOT_LABEL = HG.SLOT_LABEL


# 缓存版本号：净值口径或持仓配置结构变了就 +1，避免拿到旧结构的缓存
_NAV_CACHE_V = 2


@st.cache_data(ttl=600, show_spinner=False)
def _nav_of_code(code: str, _v: int = _NAV_CACHE_V) -> pd.Series:
    """按**基金代码**取净值序列。

    持仓换过基金时，账上可能还留着旧代码的份额（比如把沪深300 从 510300 换成 110020，
    之前买的 510300 还在）。这时候必须用旧代码自己的净值估值，不能拿新基金的净值去乘。
    """
    for s in HG.SLOTS:
        if holdings.get(s, {}).get("code") == code:
            col = _hg_panel[s].dropna() if s in _hg_panel.columns else pd.Series(dtype=float)
            return col
    return HG.nav_series(code)


def _hg_nav_on(slot, day, code=None):
    """某个位置（或某只代码）在 day 当天的净值（day 非交易日时取前一个交易日）。"""
    if code:
        col = _nav_of_code(code)
    else:
        col = _hg_panel[slot].dropna() if slot in _hg_panel.columns else pd.Series(dtype=float)
    if not len(col):
        return None
    sub = col.loc[:pd.Timestamp(day)]
    return float(sub.iloc[-1]) if len(sub) else None


def _replay_holdings(trades, capital, created):
    """按份额记账重放成交，得到日度净值/持仓/成本/现金。

    与 allweather.sim_account.replay 的差别：
    - 持仓以**基金代码**为键（原来以策略资产 key 为键，换基金就记不进去）；
    - 买入/卖出按份额 × 单位净值成交（场外基金的口径）；
    - 净值 = (持仓市值 + 现金) / units，入金出金按当时净值折算份额，不虚增收益。
    """
    idx = _hg_panel.index[_hg_panel.index >= pd.Timestamp(created)] if len(_hg_panel) else pd.DatetimeIndex([])
    if len(idx) == 0:
        idx = _hg_panel.index[-1:] if len(_hg_panel) else pd.DatetimeIndex([])
    if len(idx) == 0:
        return pd.DataFrame(), {}, {}, float(capital or 0), float(capital or 0)

    buckets: dict[pd.Timestamp, list] = {}
    for t in trades or []:
        try:
            d = pd.Timestamp(t.get("date"))
        except Exception:
            continue
        i = int(idx.searchsorted(d))
        i = min(i, len(idx) - 1)
        buckets.setdefault(idx[i], []).append(t)

    cash, units = float(capital or 0), float(capital or 0)
    pos: dict[str, float] = {}
    cost: dict[str, float] = {}
    rows, last_nav = [], 1.0
    for d in idx:
        for t in buckets.get(d, []):
            code = str(t.get("code", "") or "")
            sh = float(t.get("shares", 0) or 0)
            px = float(t.get("nav", 0) or 0)
            fee = float(t.get("fee", 0) or 0)
            side = t.get("side")
            if side == "买入" and code and sh > 0:
                if px <= 0:
                    px = _hg_nav_on(t.get("slot"), d, code) or 0
                cash -= sh * px + fee
                prev = pos.get(code, 0.0)
                cost[code] = ((prev * cost.get(code, 0.0) + sh * px + fee) / (prev + sh)) if (prev + sh) > 0 else px
                pos[code] = prev + sh
            elif side == "卖出" and code and sh > 0:
                if px <= 0:
                    px = _hg_nav_on(t.get("slot"), d, code) or 0
                cash += sh * px - fee
                pos[code] = pos.get(code, 0.0) - sh
                if pos[code] <= 1e-9:
                    pos.pop(code, None)
                    cost.pop(code, None)
            elif side == "入金":
                base = last_nav if last_nav > 0 else 1.0
                units += sh / base
                cash += sh
            elif side == "出金":
                base = last_nav if last_nav > 0 else 1.0
                units = max(1e-9, units - sh / base)
                cash -= sh
        mv = 0.0
        for code, sh in pos.items():
            v = _hg_nav_on(None, d, code)
            if v:
                mv += sh * v
        eq = cash + mv
        nav = eq / units if units > 0 else 1.0
        last_nav = nav
        rows.append({"date": d, "equity": eq, "nav": nav, "cash": cash, "market": mv})
    daily = pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()
    return daily, pos, cost, cash, units


_hg_panel = HG.nav_panel(holdings)
ACCT_FILE = DATA_DIR / "sim_account.json"
acct = load_acct(ACCT_FILE)


def _migrate_trades(a: dict) -> bool:
    """老成交（asset=策略资产 key、price=场内价）→ 新格式（code/slot/nav）。

    老记账按场内价记股数，换成基金代码后口径是份额 × 单位净值，
    不做迁移这些成交就全部读不出来。仅在缺 code 字段时改写一次。
    """
    if not a:
        return False
    changed = False
    for t in a.get("trades", []):
        if t.get("code") or t.get("side") in ("入金", "出金"):
            continue
        key = t.get("asset") or t.get("slot")
        if not key:
            continue
        t["slot"] = key
        t["code"] = holdings.get(key, {}).get("code") or ETF_META.get(key, {}).get("code", "")
        t["nav"] = float(t.get("price", 0) or 0)
        changed = bool(t["code"])
    if changed:
        save_acct(a, ACCT_FILE)
    return changed


if acct and _migrate_trades(acct):
    st.toast("已把旧的记账（按场内价/资产名）换成按基金代码与份额", icon=":material/autorenew:")
# 回测资产（项目默认那 8 个），基金走势/对比页的下拉用
_ACCT_ASSETS = [a for a in ["hs300", "us_sp500", "credit", "bond_10y",
                            "bond_30y", "gold", "nonferr", "wti"] if a in prices.columns]
_ASSET_LABEL = {a: f"{ETF_META.get(a, {}).get('name', a)} ({ETF_META.get(a, {}).get('code', '')})"
                for a in _ACCT_ASSETS}

# 账户重放结果（按份额记账）：tab3 持仓概览、tab5 调仓、tab6 实操账户、tab10 提醒共用
_acct_daily, _acct_pos, _acct_cost, _acct_cash, _acct_units = (
    _replay_holdings(acct.get("trades", []), acct.get("capital", 0), acct.get("created"))
    if acct else (pd.DataFrame(), {}, {}, 0.0, 0.0)
)
_hg_w = HG.slot_weights(w, holdings)            # 目标权重（按我启用的位置归一）
_hg_last = _hg_panel.index[-1] if len(_hg_panel) else prices.index[-1]


def _hg_mv_by_slot():
    """位置 → 当前市值（按我持仓基金的净值算）。"""
    out = {}
    for s in HG.active(holdings):
        code = holdings[s]["code"]
        sh = float(_acct_pos.get(code, 0) or 0)
        if sh > 0 and s in _hg_panel.columns:
            v = _hg_panel[s].dropna()
            out[s] = sh * float(v.iloc[-1]) if len(v) else 0.0
    return out


_hg_mv = _hg_mv_by_slot()
_hg_other_mv = {
    c: sh * float(_hg_nav_on(None, _hg_panel.index[-1], c) or 0) if len(_hg_panel) else 0.0
    for c, sh in _acct_pos.items()
    if sh > 0 and c not in {holdings.get(s, {}).get("code") for s in HG.SLOTS}
}

# ============================================================
# Hero
# ============================================================
_n_sig = sum(1 for sa in SIGNAL_ACTIONS
             if bool(sa["condition"](signals)) and strat_key in sa["strategies"])
_hero_cols = st.columns([3, 2], vertical_alignment="bottom")
with _hero_cols[0]:
    st.markdown(
        f"""<div class="hero">
          <div>
            <div class="hero-title">全天候再平衡</div>
            <div class="hero-sub">数据截止 {_cn_date(last_date)} · {cfg['name']} · {tier}% 风险平价</div>
          </div>
        </div>""",
        unsafe_allow_html=True,
    )
with _hero_cols[1], st.container(key="hero_actions", horizontal=True, horizontal_alignment="right",
                                  vertical_alignment="center", gap="small"):
    # 信号状态（只读）在左、「更新数据」按钮在右，同一行
    st.markdown(
        f'<span class="chip{" warn" if _n_sig else ""}">'
        f'<span class="dot{" warn" if _n_sig else ""}"></span>'
        f'{f"{_n_sig} 个信号触发" if _n_sig else "无信号触发"}</span>',
        unsafe_allow_html=True,
    )
    # 「更新数据」按钮：一次更新行情 + 沪深300 PE/PB + 指数估值；滞后/缺失时变成主色按钮
    _data_cls, _data_label, _data_help = _data_state
    _data_icon = {"ok": ":material/sync:", "warn": ":material/warning:", "err": ":material/error:"}[_data_cls]
    _data_type = "secondary" if _data_cls == "ok" else "primary"
    if st.button(_data_label, icon=_data_icon, type=_data_type, help=_data_help):
        # 用浮层提示而不是 st.spinner：spinner 会在按钮下插入一行，整页往下跳
        st.toast("正在更新行情、净值和估值，约 10~30 秒…", icon=":material/sync:", duration="long")
        _errs = _update_all_data()
        if _errs:
            st.toast(f"有 {len(_errs)} 项拉取失败，详见侧边栏提示", icon=":material/error:")
        else:
            st.toast("行情与估值已更新", icon=":material/check_circle:")
        st.rerun()

# ============================================================
# Main Tabs
# ============================================================
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10 = st.tabs(
    ["信号仪表盘", "目标权重", "我的持仓", "建仓清单", "调仓清单", "实操账户",
     "基金走势", "回测表现", "提醒", "指数估值"]
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
         "icon": _QUAD_ICONS["复苏"], "color": "#16703B", "assets": "沪深300 · 标普500"},
        {"label": "过热", "sub": "增长↑ 通胀↑",  "growth": True,  "inflation": True,
         "icon": _QUAD_ICONS["过热"], "color": "#C52828", "assets": "黄金 · 有色金属"},
        {"label": "滞胀", "sub": "增长↓ 通胀↑", "growth": False, "inflation": True,
         "icon": _QUAD_ICONS["滞胀"], "color": "#B45309", "assets": "黄金（避险）"},
        {"label": "衰退", "sub": "增长↓ 通胀↓",  "growth": False, "inflation": False,
         "icon": _QUAD_ICONS["衰退"], "color": "#1E40AF", "assets": "10Y国债 · 30Y国债"},
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
        border = f"2px solid {_BRAND}" if active else "1px solid #E2E8F0"
        bg = "#EFF6FF" if active else "#FFFFFF"
        cells.append(
            f"<div style='display:flex;align-items:center;gap:12px;border:{border};border-radius:14px;"
            f"padding:12px 16px;background:{bg};box-shadow:0 1px 2px rgba(15,23,42,.04)'>"
            f"<span style='display:inline-flex;align-items:center;justify-content:center;"
            f"width:38px;height:38px;border-radius:10px;background:{q['color']}1A;color:{q['color']};flex:0 0 auto'>"
            f"<span style='width:20px;height:20px;display:inline-flex'>{q['icon']}</span></span>"
            f"<span style='min-width:0'>"
            f"<strong style='font-size:15px;color:#0F172A'>{q['label']}</strong> "
            f"<span style='color:#94A3B8;font-size:12px'>{q['sub']}</span><br>"
            f"<span style='font-size:12.5px;color:#475569'>{q['assets']}</span>"
            f"</span></div>"
        )

    html = ("<div class='quad-grid' style='display:grid;grid-template-columns:1fr 1fr;gap:12px'>"
            + "".join(cells) + "</div>")
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
# Tab 3: 我的持仓（策略位置 → 我实际买的基金）
# ============================================================
_HG_PRESET = [  # 场外（支付宝可买）同类基金参考，只是建议，买前请自己核对跟踪指数和费率
    ("hs300",    "110020", "易方达沪深300ETF联接A"),
    ("us_sp500", "050025", "博时标普500ETF联接A"),
    ("credit",   "000047", "华夏鼎沛A（信用债）"),
    ("bond_10y", "000191", "富国信用债A（中久期）"),
    ("bond_30y", "003376", "广发中债7-10年国开行A"),
    ("gold",     "000217", "华安易富黄金ETF联接A"),
    ("nonferr",  "165520", "中信保诚中证800有色"),
    ("wti",      "501018", "南方原油A（当前暂停申购）"),
]


def _hg_apply(code_map: dict[str, tuple[str, str]]) -> dict:
    """把 (slot → (code, name)) 写进持仓配置。

    换基金时同步判断买卖单位：场内代码（5xxxxx 沪市 ETF/LOF、1xxxxx 深市、
    0xxxxx 深市股票型）按股，其余（场外基金，如 110020）按份额申购。
    """
    new = json.loads(json.dumps(holdings))
    for s, (code, name) in code_map.items():
        old = new.get(s, {})
        if s not in new:
            new[s] = {"code": code, "name": name, "unit": "份额", "lot": 1, "on": True}
        else:
            new[s]["code"] = code
            new[s]["name"] = name or (FL.fund_name(code) or code)
        if HG.default_unit(code) == "股":              # 场内：按股，100 股一手
            new[s]["unit"] = "股"
            new[s]["lot"] = int(old.get("lot") or 100)
        else:                                          # 场外：按金额申购
            new[s]["unit"] = "份额"
            new[s]["lot"] = 1
            new[s].setdefault("min_amount", 1.0)
    HG.save(new)
    return new


with tab3:
    st.subheader("我的持仓 · 策略位置 → 我实际买的基金")
    st.caption(
        "策略算的是 8 个**位置**的权重（增长↑权益、收益垫、增长↓国债、通胀↑黄金/有色/能源）。"
        "这里把每个位置换成你自己买的基金，之后的建仓、调仓、记账、提醒全部按你的基金算。"
        "策略本身和回测不动，仍用项目默认的 8 个代码。"
    )

    _pending = {}
    for _s in HG.SLOTS:
        _h = holdings.get(_s, {})
        _cur_code = _h.get("code", "")
        _picked = FS.fund_search(
            f"hg_{_s}", mode="single",
            placeholder=f"搜索基金，当前 {_cur_code or '未设置'}",
            default=_cur_code or None,
        )
        if _picked and _picked != _cur_code:
            _pending[_s] = _picked
    if _pending:
        _hg_apply({s: (c, FL.fund_name(c) or c) for s, c in _pending.items()})
        st.rerun()

    # 表格：可编辑单位/每手/最低金额/启用
    _rows = []
    for _s in HG.SLOTS:
        _h = holdings.get(_s, {})
        _code = _h.get("code", "")
        _nav = _hg_panel[_s].dropna() if _s in _hg_panel.columns else pd.Series(dtype=float)
        _rows.append({
            "位置": HG.SLOT_LABEL[_s],
            "代码": _code,
            "基金": _h.get("name") or (FL.fund_name(_code) if _code else "") or "—",
            "单位": _h.get("unit", "股"),
            "每手": int(_h.get("lot") or (100 if _h.get("unit", "股") == "股" else 1)),
            "最低金额": float(_h.get("min_amount") or 1.0),
            "最新净值": round(float(_nav.iloc[-1]), 4) if len(_nav) else None,
            "启用": bool(_h.get("on", True)),
            "_slot": _s,
        })
    _edited = st.data_editor(
        pd.DataFrame(_rows),
        column_config={
            "位置": st.column_config.TextColumn("位置", disabled=True),
            "代码": st.column_config.TextColumn("代码", disabled=True,
                                               help="用上方搜索框换基金"),
            "基金": st.column_config.TextColumn("我的基金", disabled=True),
            "单位": st.column_config.SelectboxColumn("买卖单位", options=["股", "份额"],
                                                    help="场内按股（100 股一手），场外按份额（按金额申购）"),
            "每手": st.column_config.NumberColumn("每手/最小", min_value=1, step=1),
            "最低金额": st.column_config.NumberColumn("最低申购金额(元)", min_value=1.0, step=1.0),
            "最新净值": st.column_config.NumberColumn(f"净值({_cn_date(_hg_last)})", format="%.4f",
                                                     disabled=True),
            "启用": st.column_config.CheckboxColumn("启用", help="关掉的位置不参与建仓/调仓/提醒"),
            "_slot": None,
        },
        hide_index=True, width="stretch", key="hg_editor",
    )
    _miss = [f'{holdings.get(s, {}).get("code", "")} {holdings.get(s, {}).get("name", "")}'
             for s in HG.active(holdings)
             if not len(_hg_panel.get(s, pd.Series(dtype=float)).dropna())]
    if _miss:
        st.warning("这些基金还没有净值数据，拉取后建仓/调仓/提醒才能算：" + "；".join(_miss))
        if st.button("拉取缺的净值", key="hg_fetch_missing", type="primary"):
            st.toast("正在拉取净值…", icon=":material/sync:", duration="long")
            for _s in HG.active(holdings):
                _c = holdings.get(_s, {}).get("code", "")
                if _c and not len(_hg_panel.get(_s, pd.Series(dtype=float)).dropna()):
                    try:
                        FL.ensure_fresh(_c)
                    except Exception:  # noqa: BLE001
                        pass
            st.cache_data.clear()
            st.rerun()

    with st.container(horizontal=True, horizontal_alignment="right", gap="small"):
        if st.button("保存修改", type="primary", key="hg_save"):
            _new = json.loads(json.dumps(holdings))
            for r in _edited.to_dict("records"):
                s = r.get("_slot")
                if not s:
                    continue
                _new[s]["unit"] = r.get("单位") or "股"
                _new[s]["lot"] = int(r.get("每手") or 1)
                _new[s]["min_amount"] = float(r.get("最低金额") or 1.0)
                _new[s]["on"] = bool(r.get("启用"))
            HG.save(_new)
            st.toast("持仓设置已保存", icon=":material/check_circle:")
            st.rerun()
        if st.button("恢复项目默认代码", key="hg_reset"):
            HG.save(HG._default_holdings())
            st.toast("已恢复为项目默认的 8 个代码", icon=":material/check_circle:")
            st.rerun()

    with st.expander("换成场外（支付宝可买）同类基金 — 一键填入参考代码"):
        st.caption("下面是同类基金的参考代码，跟踪指数和费率不一定和原版一致，填入后请自己核对；"
                   "收益差异会在「提醒」页用「项目默认基金」那列体现出来。")
        _preset_rows = [[HG.SLOT_LABEL[s], ETF_META.get(s, {}).get("code", ""),
                         ETF_META.get(s, {}).get("name", ""), c, n] for s, c, n in _HG_PRESET]
        _render_table([("位置", "left"), ("原版代码", "left"), ("原版基金", "left"),
                       ("参考代码", "left"), ("参考基金", "left")], _preset_rows)
        if st.button("全部填入参考代码", key="hg_preset_all"):
            _hg_apply({s: (c, n) for s, c, n in _HG_PRESET})
            st.toast("已填入场外参考代码，请核对跟踪指数", icon=":material/check_circle:")
            st.rerun()

    st.divider()
    st.markdown("**当前持仓概览**（来自「实操账户」的成交记录）")
    if not _hg_mv and not _acct_cash:
        st.caption("还没有持仓。到「实操账户」创建账户并录入成交，这里会显示每只基金的份额、市值、"
                   "相对目标权重的偏离。")
    else:
        _tot = sum(_hg_mv.values()) + float(_acct_cash or 0)
        _ov_rows = []
        for _s in HG.SLOTS:
            _h = holdings.get(_s, {})
            if not _h.get("on", True):
                continue
            _code = _h.get("code", "")
            _sh = float(_acct_pos.get(_code, 0) or 0)
            if _sh <= 0 and _s not in _hg_mv:
                continue
            _mv = float(_hg_mv.get(_s, 0.0))
            _c = float(_acct_cost.get(_code, 0) or 0)
            _nav = _hg_panel[_s].dropna() if _s in _hg_panel.columns else pd.Series(dtype=float)
            _p = float(_nav.iloc[-1]) if len(_nav) else 0.0
            _curw = _mv / _tot if _tot else 0.0
            _tgt = float(_hg_w.get(_s, 0) or 0)
            _pl = (_p / _c - 1) if (_c > 0 and _p > 0) else None
            _pl_txt = "—" if _pl is None else f'<span class="{"up" if _pl >= 0 else "down"}">{_pl*100:+.2f}%</span>'
            _dev = _curw - _tgt
            _dev_txt = ('<span class="muted">—</span>' if abs(_dev) < 0.03
                        else f'<span class="{"up" if _dev > 0 else "down"}">{_dev*100:+.1f}pp</span>')
            _ov_rows.append([
                HG.SLOT_LABEL[_s],
                f'{_h.get("name") or _code}<br><span class="muted">{_code}</span>',
                f"{_sh:,.2f}" if _h.get("unit") == "份额" else f"{_sh:,.0f}",
                f"{_p:.4f}" if _p else "—",
                f"{_mv:,.0f}", _pl_txt, f"{_curw*100:.1f}%", f"{_tgt*100:.1f}%", _dev_txt,
            ])
        _render_table(
            [("位置", "left"), ("我的基金", "left"), ("份额/股数", "right"), ("净值", "right"),
             ("市值(¥)", "right"), ("浮盈亏", "right"), ("当前权重", "right"),
             ("目标权重", "right"), ("偏离", "right")],
            _ov_rows,
            totals=["合计", "—", "—", "—", f"{sum(_hg_mv.values()):,.0f}", "—",
                    f"{(sum(_hg_mv.values())/_tot*100 if _tot else 0):.1f}%", "100.0%", "—"],
        )
        if _hg_other_mv:
            st.caption("**换基金前买的、现在配置里没有的基金**（按各自净值照常估值）："
                       + "；".join(f"{c} ¥{v:,.0f}" for c, v in _hg_other_mv.items()))
        st.caption(f"现金 ¥{_acct_cash:,.0f} · 总资产 ¥{_tot:,.0f} · 净值日期 {_cn_date(_hg_last)}"
                   + (f" · 持仓配置更新于 {_hg_state.get('updated', '—')}" if _hg_state.get("updated") else ""))

# ============================================================
# Tab 4: 建仓清单
# ============================================================
with tab4:
    st.subheader("从零建仓")
    st.caption("按「我的持仓」里你自己的基金、以及策略给这 8 个位置算出的目标权重分配资金。")

    amount = st.number_input(
        "投资总额（元）",
        min_value=1000,
        value=500000,
        step=10000,
        format="%d",
        key="build_amount_input",
    )

    _bg_rows, _bg_used, _bg_target = [], 0.0, 0.0
    for _s in HG.active(holdings):
        _h = holdings[_s]
        _pct = float(_hg_w.get(_s, 0) or 0)
        if not np.isfinite(_pct) or _pct <= 0:
            continue
        _nav = _hg_panel[_s].dropna() if _s in _hg_panel.columns else pd.Series(dtype=float)
        _px = float(_nav.iloc[-1]) if len(_nav) else 0.0
        if _px <= 0:
            _bg_rows.append([HG.SLOT_LABEL[_s], f'{_h.get("name") or ""}', _h.get("code", ""),
                             f"{_pct*100:.1f}%", "—", '<span class="muted">缺净值，先更新数据</span>'])
            continue
        _tgt_amt = _pct * amount
        _qty, _act = HG.order_quantity(_h, _tgt_amt, _px)
        _bg_used += _act
        _bg_target += _tgt_amt
        _qty_txt = (f"{_qty:,.2f} 份" if HG.is_otc(_h) else f"{_qty:,.0f} 股")
        _bg_rows.append([
            HG.SLOT_LABEL[_s], f'{_h.get("name") or ""}<br><span class="muted">{_h.get("code", "")}</span>',
            "场外" if HG.is_otc(_h) else "场内", f"{_pct*100:.1f}%",
            f"¥{_tgt_amt:,.0f}<br><span class='muted'>净值 {_px:.4f}</span>",
            f"{_qty_txt}<br><span class='muted'>¥{_act:,.0f}</span>",
        ])

    if _bg_rows:
        _render_table(
            [("位置", "left"), ("我的基金", "left"), ("场内/场外", "left"), ("目标权重", "right"),
             ("目标金额", "right"), ("买入数量", "right")],
            _bg_rows,
            totals=["合计", "—", "—", "100.0%", f"¥{_bg_target:,.0f}", f"¥{_bg_used:,.0f}"],
        )
        _c1, _c2, _c3 = st.columns(3)
        _c1.metric("总投资", f"¥{amount:,.0f}")
        _c2.metric("已分配", f"¥{_bg_used:,.0f}")
        _c3.metric("剩余现金", f"¥{amount - _bg_used:,.0f}", delta="留作调仓子弹或放货基")
        st.caption("场外按金额申购（最低金额见「我的持仓」表）；场内按 100 股取整。"
                   "成交价以当天实际净值为准，这里是按最新净值估算。")
        if st.button("按此清单生成建仓成交", key="hg_build_trades",
                     help="把这份清单写成「实操账户」的首批成交，日期用最新净值日"):
            if acct is None:
                st.warning("请先在「实操账户」创建账户")
            else:
                _tr = [{"date": _hg_last.strftime("%Y-%m-%d"), "slot": _s,
                        "code": holdings[_s]["code"], "side": "买入", "shares": 0,
                        "nav": 0.0, "fee": 0.0}
                       for _s in HG.active(holdings)]
                # 复用上面的计算结果重新生成数量（保持与目标金额一致）
                _tr = []
                for _s in HG.active(holdings):
                    _h = holdings[_s]
                    _pct = float(_hg_w.get(_s, 0) or 0)
                    _nav = _hg_panel[_s].dropna() if _s in _hg_panel.columns else pd.Series(dtype=float)
                    _px = float(_nav.iloc[-1]) if len(_nav) else 0.0
                    if _pct <= 0 or _px <= 0:
                        continue
                    _qty, _ = HG.order_quantity(_h, _pct * amount, _px)
                    if _qty <= 0:
                        continue
                    _tr.append({"date": _hg_last.strftime("%Y-%m-%d"), "slot": _s,
                                "code": holdings[_s]["code"], "side": "买入",
                                "shares": round(float(_qty), 4), "nav": round(_px, 4), "fee": 0.0})
                acct.setdefault("trades", []).extend(_tr)
                save_acct(acct, ACCT_FILE)
                st.toast(f"已生成 {len(_tr)} 笔建仓成交", icon=":material/check_circle:")
                st.rerun()
    else:
        st.warning("没有可建仓的位置：请先到「我的持仓」设置基金，或点「更新数据」拉取净值")

# ============================================================
# Tab 5: 调仓清单
# ============================================================
with tab5:
    st.subheader("调仓清单")
    st.caption("默认带出「实操账户」里的持仓份额，可直接改；按目标权重算出该买/卖多少。")

    _use_ledger = st.toggle("用实操账户的持仓份额", value=True, key="reb_use_ledger")
    _rb_inputs = {}
    _rb_nav = {}
    for _s in HG.active(holdings):
        _h = holdings[_s]
        _nav = _hg_panel[_s].dropna() if _s in _hg_panel.columns else pd.Series(dtype=float)
        _px = float(_nav.iloc[-1]) if len(_nav) else 0.0
        _rb_nav[_s] = _px
    _rb_cols = st.columns(4)
    for _i, _s in enumerate(HG.active(holdings)):
        _h = holdings[_s]
        with _rb_cols[_i % 4]:
            _default_sh = float(_acct_pos.get(_h["code"], 0) or 0) if _use_ledger else 0.0
            _rb_inputs[_s] = st.number_input(
                f'{HG.SLOT_LABEL[_s]} · {_h.get("code", "")}',
                min_value=0.0, value=round(_default_sh, 2),
                step=100.0 if _h.get("unit") == "股" else 100.0,
                format="%.2f" if HG.is_otc(_h) else "%.0f",
                key=f"reb_sh_{_s}",
                help=f"{_h.get('name') or ''}　净值 {_rb_nav[_s]:.4f}" if _rb_nav[_s] else "",
            )

    _rb_mv = {s: _rb_inputs.get(s, 0.0) * _rb_nav.get(s, 0.0) for s in HG.active(holdings)}
    _rb_total = float(sum(_rb_mv.values()))
    if _rb_total > 0:
        st.divider()
        st.caption(f"持仓总市值: ¥{_rb_total:,.0f}（净值日期 {_cn_date(_hg_last)}）")
        _rb_rows, _any, _sum_tgt, _sum_diff = [], False, 0.0, 0.0
        for _s in HG.active(holdings):
            _h = holdings[_s]
            _px = _rb_nav.get(_s, 0.0)
            _sh = float(_rb_inputs.get(_s, 0.0) or 0)
            _cur = _sh * _px
            _tgt = float(_hg_w.get(_s, 0) or 0) * _rb_total
            _diff = _tgt - _cur
            _sum_tgt += _tgt
            _sum_diff += _diff
            _pct = abs(_diff) / _rb_total if _rb_total else 0
            if _pct < 0.005 or _px <= 0:
                _act = '<span class="muted">不变</span>'
            elif _diff > 0:
                _qty, _amt = HG.order_quantity(_h, _diff, _px)
                _act = (f'<span class="up">买入 {_amt:,.0f} 元</span>' if HG.is_otc(_h)
                        else f'<span class="up">买入 {_qty:,.0f} 股</span>')
                _any = _any or _qty > 0
            else:
                _qty, _amt = HG.order_quantity(_h, -_diff, _px)
                _act = (f'<span class="down">卖出 {_amt:,.0f} 元</span>' if HG.is_otc(_h)
                        else f'<span class="down">卖出 {_qty:,.0f} 股</span>')
                _any = _any or _qty > 0
            _curw = _cur / _rb_total if _rb_total else 0
            _tgtw = float(_hg_w.get(_s, 0) or 0)
            _dev = _curw - _tgtw
            _rb_rows.append([
                HG.SLOT_LABEL[_s],
                f'{_h.get("name") or ""}<br><span class="muted">{_h.get("code", "")}</span>',
                f"{_sh:,.2f}" if HG.is_otc(_h) else f"{_sh:,.0f}",
                f"{_cur:,.0f}", f"{_curw*100:.1f}%", f"{_tgtw*100:.1f}%",
                ('<span class="muted">—</span>' if abs(_dev) < 0.03
                 else f'<span class="{"up" if _dev > 0 else "down"}">{_dev*100:+.1f}pp</span>'),
                f'<span class="{"up" if _diff > 0 else "down"}">{_diff:+,.0f}</span>' if abs(_diff) >= 1 else '<span class="muted">—</span>',
                _act,
            ])
        _render_table(
            [("位置", "left"), ("我的基金", "left"), ("份额/股数", "right"), ("市值(¥)", "right"),
             ("当前权重", "right"), ("目标权重", "right"), ("偏离", "right"), ("差额(¥)", "right"),
             ("操作", "left")],
            _rb_rows,
            totals=["合计", "—", "—", f"{_rb_total:,.0f}", "100.0%", "100.0%", "—",
                    f"{_sum_diff:+,.0f}", "—"],
        )
        if not _any:
            st.success("所有位置偏离 < 0.5%，无需调仓")
        with st.expander("调仓规则说明"):
            st.markdown("""
            1. 每月最后一个交易日执行一次
            2. 先卖后买 — 场外卖出到账后再买入（一般 T+1~T+3）
            3. 非农/黄金/标普 跌破 SMA → 策略已把权重转到城投债位置，照上面清单执行即可
            4. 偏离 < 0.5% 不用动，省手续费
            5. 场内按 100 股取整；场外按金额申购，最低金额见「我的持仓」
            6. 场外当天申赎按当日收盘净值成交，和场内实时价不同
            """)
    else:
        st.caption("填写持仓份额后自动生成调仓清单")

# ============================================================
# Tab 6: 实操账户（按我自己的基金、按份额记账）
# ============================================================


def _fmt_money(v):
    return f"¥{v:,.0f}"


def _hg_slot_options():
    """位置下拉选项：value=(key, label)，显示「位置 · 代码 名称」。"""
    return [(s, f'{HG.SLOT_LABEL[s]} · {holdings.get(s, {}).get("code", "")} '
                 f'{holdings.get(s, {}).get("name", "")}'.strip()) for s in HG.SLOTS]


with tab6:
    st.subheader("实操账户 · 我的基金 vs 两条基准")
    st.caption(
        "按份额记账：买多少份、每份净值多少，和支付宝对账单一致。"
        "入金/出金按当时净值折算份额，所以资金进出不会让收益率虚增。"
    )

    if acct is None:
        st.info("**还没有实操账户** — 创建后录入成交，这里会自动给出：净值曲线、持仓明细，"
                "以及和「策略理论」「项目默认基金」的对比。")
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
        daily, pos, cost, cash, units = _acct_daily, _acct_pos, _acct_cost, _acct_cash, _acct_units
        stn = acct_stats(daily) if len(daily) else {"nav": 1.0, "ret": 0.0, "mdd": 0.0}
        equity = float(daily["equity"].iloc[-1]) if len(daily) else float(acct.get("capital", 0))
        pnl = equity - float(acct.get("capital", 0))

        # ---- 两条基准 ----
        bench_def = BM.replay_target(w, acct.get("created"), nav_getter=HG.nav_series)
        bench_strat = BM.strategy_curve(_BENCH_COL.get(acct.get("strategy"), ""),
                                        start=acct.get("created"))
        gap_def = gap_strat = None
        if len(daily) > 1:
            if len(bench_def) > 1:
                _e = min(bench_def.index[-1], daily.index[-1])
                gap_def = float(daily["nav"].loc[:_e].iloc[-1]
                                / (bench_def.loc[:_e].iloc[-1] / bench_def.iloc[0]) - 1)
            if bench_strat is not None and len(bench_strat) > 1:
                _e = min(bench_strat.index[-1], daily.index[-1])
                gap_strat = float(daily["nav"].loc[:_e].iloc[-1]
                                  / (bench_strat.loc[:_e].iloc[-1] / bench_strat.iloc[0]) - 1)

        st.caption(f"账户起始 {_cn_date(acct['created'])} · 净值日期 {_cn_date(_hg_last)} · "
                   f"{len(daily)} 个数据日 · 持仓配置更新于 {_hg_state.get('updated') or '—'}")

        with st.expander("⚙️ 账户设置（起始日期 / 清空）"):
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

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("总资产", _fmt_money(equity))
        m2.metric("累计收益", _fmt_money(pnl), delta=f"{stn['ret']*100:+.2f}%")
        m3.metric("现金", _fmt_money(cash))
        m4.metric("最大回撤", f"{stn['mdd']*100:.2f}%")
        b1, b2, b3 = st.columns(3)
        b1.metric("vs 策略理论", f"{gap_strat*100:+.2f}pp" if gap_strat is not None else "—",
                  help="回测曲线（output/nv_curves.csv）从建仓日起归一。差的是选基、调仓时点、"
                       "费用，以及回测用累计净值/实盘用单位净值的口径差。")
        b2.metric("vs 项目默认基金", f"{gap_def*100:+.2f}pp" if gap_def is not None else "—",
                  help="同样从建仓日起、同样目标权重、每月再平衡，但用项目默认那 8 个代码重放。"
                       "这一列主要体现「换基金带来多少差异」。")
        b3.metric("怎么校验最准", "对支付宝",
                  help="最硬的校验：份额 × 最新单位净值 + 现金 = 总资产，"
                       "收益率和支付宝「持有收益」应该一致。")

        # ---- 净值曲线 ----
        if len(daily) > 1:
            _labels = [t.strftime("%Y/%m/%d") for t in daily.index]
            _mine = [float(v) for v in daily["nav"]]
            st.markdown('<div class="sec-note">账户净值：1.0 = 建仓起点，可拖动缩放。'
                        '两条基准的差距见上方「vs 策略理论 / vs 项目默认基金」。</div>',
                        unsafe_allow_html=True)
            st.iframe(_scroll_chart_html(_labels, _mine, len(_labels), height=460,
                                         revision=len(daily)),
                      height="content")

        # ---- 持仓明细 ----
        st.markdown("**持仓明细**")
        _pr = []
        _tot_mv = 0.0
        # 按代码列出：换过基金时旧代码的份额也照常显示，不会凭空消失
        for _code, _sh in sorted(pos.items()):
            _sh = float(_sh or 0)
            if _sh <= 0:
                continue
            _s = HG.slot_of(_code, holdings)
            _h = holdings.get(_s, {}) if _s else {}
            _px = float(_hg_nav_on(_s, _hg_last, _code) or 0)
            _mv = _sh * _px
            _tot_mv += _mv
            _c = float(cost.get(_code, 0) or 0)
            _pl = (_px / _c - 1) if (_c > 0 and _px > 0) else None
            _pr.append([
                HG.SLOT_LABEL.get(_s, "换基金前的旧持仓"),
                f'{_h.get("name") or FL.fund_name(_code) or _code}'
                f'<br><span class="muted">{_code}</span>',
                f"{_sh:,.2f}" if HG.is_otc(_h) else f"{_sh:,.0f}",
                f"{_c:.4f}" if _c else "—",
                f"{_px:.4f}" if _px else "—",
                f"{_mv:,.0f}",
                ("—" if _pl is None else
                 f'<span class="{"up" if _pl >= 0 else "down"}">{_pl*100:+.2f}%</span>'),
                ("—" if not _c else
                 f'<span class="{"up" if (_mv - _c * _sh) >= 0 else "down"}">{_mv - _c * _sh:+,.0f}</span>'),
            ])
        if _pr:
            _render_table(
                [("位置", "left"), ("基金", "left"), ("份额/股数", "right"), ("成本单价", "right"),
                 ("最新净值", "right"), ("市值(¥)", "right"), ("浮盈亏", "right"),
                 ("浮盈亏(¥)", "right")],
                _pr,
                totals=["合计", "—", "—", "—", "—", f"{_tot_mv:,.0f}", "—", "—"],
            )
        else:
            st.caption("暂无持仓（全部为现金）")

        # ---- 录入成交 ----
        st.divider()
        st.markdown("**录入成交**")
        _slot_opts = _hg_slot_options()
        with st.form("acct_trade", clear_on_submit=True):
            r1 = st.columns([1.1, 0.9, 2.2], gap="small")
            tr_date = r1[0].date_input("日期", value=pd.Timestamp(_hg_last).date(), format="YYYY/MM/DD")
            tr_side = r1[1].selectbox("类型", ["买入", "卖出", "入金", "出金"])
            tr_slot = r1[2].selectbox("基金（位置）", _slot_opts, format_func=lambda x: x[1])
            _is_money = tr_side in ("入金", "出金")
            _unit_otc = HG.is_otc(holdings.get(tr_slot[0], {}))
            r2 = st.columns([1, 1, 1], gap="small")
            tr_shares = r2[0].number_input(
                "金额（元）" if _is_money else ("份额（场外）" if _unit_otc else "股数（场内）"),
                min_value=0.0, step=100.0, format="%.2f")
            _nav_hint = _hg_nav_on(tr_slot[0], tr_date)
            tr_nav = r2[1].number_input(
                "成交净值（元/份）", min_value=0.0,
                value=round(float(_nav_hint or 0), 4) if (not _is_money and _nav_hint) else 0.0,
                step=0.0001, format="%.4f",
                help="场外按当天收盘净值成交；留 0 会自动取该日净值。入金/出金不用填。")
            tr_fee = r2[2].number_input("手续费（元）", min_value=0.0, step=1.0, format="%.2f")
            if st.form_submit_button("记一笔", type="primary"):
                _t = {"date": str(tr_date), "side": tr_side, "slot": tr_slot[0],
                      "code": holdings.get(tr_slot[0], {}).get("code", ""),
                      "shares": float(tr_shares), "nav": float(tr_nav), "fee": float(tr_fee)}
                if _is_money and tr_shares <= 0:
                    st.warning("金额要大于 0")
                elif not _is_money and (tr_shares <= 0 or not _t["code"]):
                    st.warning("数量要大于 0，且该位置要先在「我的持仓」设置基金代码")
                else:
                    acct.setdefault("trades", []).append(_t)
                    save_acct(acct, ACCT_FILE)
                    st.toast("已记录", icon=":material/check_circle:")
                    st.rerun()

        # ---- 成交流水 ----
        with st.expander(f"成交流水（{len(acct.get('trades', []))} 笔）", expanded=False):
            _tr_rows = []
            for i, t in enumerate(acct.get("trades", [])):
                _sl = t.get("slot", "")
                _nm = holdings.get(_sl, {}).get("name") or t.get("code", "")
                _u = holdings.get(_sl, {}).get("unit", "份额")
                _qty = (f"¥{float(t.get('shares', 0)):,.0f}" if t.get("side") in ("入金", "出金")
                        else (f'{float(t.get("shares", 0)):,.2f} 份' if _u == "份额"
                              else f'{float(t.get("shares", 0)):,.0f} 股'))
                _tr_rows.append([
                    _cn_date(t.get("date")), t.get("side"),
                    f'{_nm}<br><span class="muted">{t.get("code", "")}</span>',
                    _qty,
                    f'{float(t.get("nav", 0)):.4f}' if float(t.get("nav", 0) or 0) > 0 else "—",
                    f'{float(t.get("fee", 0)):,.2f}' if float(t.get("fee", 0) or 0) else "—",
                    str(i),
                ])
            if _tr_rows:
                _render_table([("日期", "left"), ("类型", "left"), ("基金", "left"),
                               ("数量", "right"), ("净值", "right"), ("手续费", "right"),
                               ("#", "right")], _tr_rows)
                _del = st.number_input("删除第几笔（最后一列的序号）", min_value=0,
                                       max_value=max(0, len(acct.get("trades", [])) - 1),
                                       step=1, format="%d", key="acct_del_idx")
                if st.button("删除这笔", key="acct_del_btn"):
                    acct["trades"].pop(int(_del))
                    save_acct(acct, ACCT_FILE)
                    st.rerun()
            else:
                st.caption("暂无成交")

        st.caption(f"账户文件：{ACCT_FILE.name}（保存在 data/ 下，重装或换机时记得备份）")

# ============================================================
# Tab 7: 基金走势（日 / 月 / 年 的涨跌幅与价格）
# ============================================================
# 范围和采样粒度独立，切周期不改变所选范围。区间口径与支付宝「历史业绩」一致（见 _trend_window_start）。


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
      例：最新 2026/10/23，近3月基准 = 2026/07/23 的净值。
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


def _trend_chart_data(series):
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


@st.cache_data(show_spinner=False, max_entries=200)
def _nav_last_cached(code: str, ver: float) -> str:
    """本地缓存净值的最后日期（只读盘、不联网）。ver 传文件 mtime，数据更新后缓存自动失效。"""
    d = FL.load_cached(code)
    return f"{d.index[-1]:%Y/%m/%d}" if d is not None and len(d) else ""


def _cmp_cached_last(codes) -> str:
    """已选基金里最新的「数据截至」日期；拿不到就返回空串，避免头卡高度在两帧之间变化。"""
    out = []
    for c in codes or []:
        c = str(c)
        if not (c.isdigit() and len(c) == 6):
            continue
        p = FL.NAV_DIR / f"{c}.csv"
        if not p.exists():
            continue
        d = _nav_last_cached(c, p.stat().st_mtime)
        if d:
            out.append(d)
    return max(out) if out else ""


def _sticky_search(key: str, **kw):
    """基金搜索框的记忆版：切走再切回时保住已选值。

    「单只走势」和「多只对比」是 if / else 两个分支，切走后那个分支的搜索框这一轮不渲染，
    Streamlit 会把它的 widget state 一起丢掉（切回来就退回默认值）。这里在 Python 侧另存一份
    镜像，组件被重新挂载时把它当默认值传回去。注意：只在「条件渲染」的搜索框上用，
    默认值会随数据变化的搜索框（如持仓配置）不能用，否则镜像会盖住真实值。
    """
    memo_key = f"_sel_{key}"
    kw["default"] = st.session_state.get(memo_key, kw.get("default"))
    val = FS.fund_search(key, **kw)
    st.session_state[memo_key] = list(val) if isinstance(val, list) else val
    return val


def _stage_rows(series):
    """四个固定阶段数字，基准与图表视窗同一口径（_trend_window_start），不受图表拖动影响。"""
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
        tip = dates + " · 基准日净值至最新净值（与支付宝历史业绩同口径）"
        items.append(
            f'<div class="stage-metric" data-stage="{html_escape(cell["label"])}" title="{html_escape(tip)}">'
            f'<span class="stage-label">{html_escape(cell["label"])}</span>'
            f'<b class="stage-return {cls}" data-value="{value if valid else ""}">{text}</b></div>'
        )
    return ('<div class="stage-summary"><div class="stage-summary-title">阶段表现</div>'
            '<div class="stage-metrics">' + ''.join(items) + '</div></div>')


# ------------------------------------------------------------------
# 收益日历组件（iframe）：日/周/月/年 格子，与走势分析同一套按钮/选择器样式
# ------------------------------------------------------------------
_CAL_CSS = r"""
.cal-grid{display:grid;gap:6px;margin-top:16px}
.cal-h{text-align:center;font-size:12px;color:#94A3B8;padding:0 0 2px}
.cal-cell{display:flex;flex-direction:column;justify-content:space-between;gap:6px;min-height:64px;
  padding:8px 10px;border-radius:10px;background:#F8FAFC;border:1px solid transparent}
.cal-cell .k{font-size:12px;color:#475569;line-height:1.35;display:flex;flex-direction:column}
.cal-cell .k small{font-size:11px;color:#94A3B8;margin-top:2px;font-variant-numeric:tabular-nums}
.cal-cell .v{font-size:14px;font-weight:600;text-align:right;font-variant-numeric:tabular-nums;letter-spacing:-.2px}
.cal-cell.up .v{color:#C52828}.cal-cell.down .v{color:#16703B}.cal-cell.flat .v{color:#475569}
.cal-cell.none{background:#fff;border-color:#F1F5F9}.cal-cell.none .v{color:#CBD5E1;font-weight:400}
.cal-cell.pad{visibility:hidden}
.cal-cell.today{border-color:#3B82F6}
.nav{display:flex;align-items:center;gap:6px;margin-bottom:4px}
.nav button{width:42px;height:42px;display:inline-flex;align-items:center;justify-content:center;padding:0;
  border:1px solid #E2E8F0;border-radius:12px;background:#fff;color:#475569;cursor:pointer;transition:border-color .15s,background-color .15s}
.nav button svg{width:12px;height:12px;fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}
.nav button:hover:not(:disabled){border-color:#CBD5E1;background:#F8FAFC;color:#0F172A}
.nav button:disabled{color:#CBD5E1;cursor:default}
#pick{min-width:128px;text-align:center;text-align-last:center}
#summary{border-top:1px solid #E2E8F0;margin-top:16px;padding-top:12px}
.sum-k{font-weight:600;color:#0F172A}
@media(max-width:560px){.cal-cell{min-height:52px;padding:6px}.cal-cell .v{font-size:12px}#pick{min-width:110px}}
"""


def _calendar_payload(series):
    """收益日历数据：日涨跌、自然周(W-FRI)、月、年涨跌幅%，均为每期最后交易日相对上期末。"""
    x = _trend_aggregate(series, "日")
    if len(x) < 2:
        return None
    d = (x.pct_change(fill_method=None) * 100).dropna()
    day = {f"{t:%Y/%m/%d}": round(float(v), 4) for t, v in d.items()}
    week, prev = [], None
    for _, g in x.groupby(pd.Grouper(freq="W-FRI")):
        if len(g) == 0:
            continue
        last = float(g.iloc[-1])
        if prev is not None and prev > 0:
            week.append({"s": f"{g.index[0]:%Y/%m/%d}", "e": f"{g.index[-1]:%Y/%m/%d}",
                         "v": round((last / prev - 1) * 100, 4)})
        prev = last

    def per(freq, fmt):
        p = x.resample(freq).last().dropna()
        r = (p.pct_change(fill_method=None) * 100).dropna()
        return {t.strftime(fmt): round(float(v), 4) for t, v in r.items()}

    months = sorted({(t.year, t.month) for t in x.index}, reverse=True)
    years = sorted({t.year for t in x.index}, reverse=True)
    today = date.today()
    dm = [today.year, today.month] if (today.year, today.month) in months else list(months[0])
    dy = today.year if today.year in years else years[0]
    return {"day": day, "week": week, "month": per("ME", "%Y-%m"), "year": per("YE", "%Y"),
            "months": [list(m) for m in months], "years": years,
            "defMonth": dm, "defYear": dy, "today": f"{today:%Y/%m/%d}"}


def _calendar_html(payload):
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    template = r"""<style>
__BASE_CSS__
__CAL_CSS__
</style>
<div id="wrap">
<div class="heading"><h3><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M8 3v5m8-5v5M4 10h16"/></svg>收益日历</h3></div>
<div class="controls"><div id="range-controls" role="group" aria-label="粒度">
<button data-range="日" aria-pressed="true">日</button><button data-range="周" aria-pressed="false">周</button><button data-range="月" aria-pressed="false">月</button><button data-range="年" aria-pressed="false">年</button>
</div><div id="nav" class="nav"><button id="prev" aria-label="上一期"><svg viewBox="0 0 12 12" aria-hidden="true"><path d="M7.5 3l-3 3 3 3"/></svg></button><select id="pick" aria-label="选择期间"></select><button id="next" aria-label="下一期"><svg viewBox="0 0 12 12" aria-hidden="true"><path d="M4.5 3l3 3-3 3"/></svg></button></div></div>
<div id="grid" class="cal-grid"></div>
<div id="summary" class="amp-row"></div>
</div>
<script>
(() => {
  const D = __CAL_DATA__;
  const wrap = document.getElementById('wrap'), grid = document.getElementById('grid'), sum = document.getElementById('summary');
  const pick = document.getElementById('pick'), prevB = document.getElementById('prev'), nextB = document.getElementById('next'), nav = document.getElementById('nav');
  let mode = '日', ym = D.defMonth.slice(), yy = D.defYear;
  const ok = v => v !== null && v !== undefined && Number.isFinite(v);
  const pct = v => ok(v) ? (v > 0 ? '+' : '') + v.toFixed(2) + '%' : '—';
  const color = v => !ok(v) || Math.abs(v) < 1e-10 ? '#475569' : (v > 0 ? '#C52828' : '#16703B');
  const p2 = n => String(n).padStart(2, '0');
  const cls = v => !ok(v) ? 'none' : (v > 0 ? 'up' : (v < 0 ? 'down' : 'flat'));
  // 涨跌幅越大底色越深（热力），颜色与 --red / --green 同值
  const heat = (v, mx) => {
    if (!ok(v) || Math.abs(v) < 1e-10) return '';
    const a = (0.06 + 0.22 * Math.min(1, Math.abs(v) / (mx || 1))).toFixed(3);
    return v > 0 ? `background:rgba(197,40,40,${a})` : `background:rgba(22,112,59,${a})`;
  };
  const maxAbs = vals => vals.reduce((m, v) => ok(v) ? Math.max(m, Math.abs(v)) : m, 0.01);
  const cell = (k, v, mx, extra = '', sub = '', title = '') =>
    `<div class="cal-cell ${cls(v)} ${extra}" style="${heat(v, mx)}" title="${title}"><span class="k">${k}${sub ? `<small>${sub}</small>` : ''}</span><span class="v">${pct(v)}</span></div>`;
  const item = (k, v) => `<span>${k}</span><b style="color:${color(v)}">${pct(v)}</b>`;
  const cnt = (k, n, u) => `<span>${k}</span><b>${n} ${u}</b>`;
  function fillPick() {
    if (mode === '年') { nav.style.visibility = 'hidden'; return; }
    nav.style.visibility = 'visible';
    if (mode === '月') {
      pick.innerHTML = D.years.map(y => `<option value="${y}">${y}年</option>`).join('');
      pick.value = String(yy);
    } else {
      pick.innerHTML = D.months.map(([y, m]) => `<option value="${y}-${m}">${y}年${m}月</option>`).join('');
      pick.value = `${ym[0]}-${ym[1]}`;
    }
    const i = pick.selectedIndex;            // 列表倒序：越往后越早
    prevB.disabled = i >= pick.options.length - 1; nextB.disabled = i <= 0;
  }
  pick.onchange = () => { if (mode === '月') yy = +pick.value; else ym = pick.value.split('-').map(Number); render(); };
  prevB.onclick = () => { const i = pick.selectedIndex; if (i < pick.options.length - 1) { pick.selectedIndex = i + 1; pick.onchange(); } };
  nextB.onclick = () => { const i = pick.selectedIndex; if (i > 0) { pick.selectedIndex = i - 1; pick.onchange(); } };
  document.querySelectorAll('[data-range]').forEach(b => b.onclick = () => { mode = b.dataset.range; render(); });
  function render() {
    document.querySelectorAll('[data-range]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.range === mode)));
    fillPick();
    let html = '', s = '';
    if (mode === '日' || mode === '周') {
      const [y, m] = ym, nd = new Date(y, m, 0).getDate(), mv = D.month[`${y}-${p2(m)}`];
      if (mode === '日') {
        const first = new Date(y, m - 1, 1).getDay(), vals = [];
        for (let d = 1; d <= nd; d++) { const v = D.day[`${y}/${p2(m)}/${p2(d)}`]; if (ok(v)) vals.push(v); }
        const mx = maxAbs(vals);
        html = ['日', '一', '二', '三', '四', '五', '六'].map(w => `<div class="cal-h">${w}</div>`).join('')
          + '<div class="cal-cell pad"></div>'.repeat(first);
        for (let d = 1; d <= nd; d++) {
          const key = `${y}/${p2(m)}/${p2(d)}`;
          html += cell(String(d), D.day[key], mx, key === D.today ? 'today' : '', '', key);
        }
        grid.style.gridTemplateColumns = 'repeat(7,minmax(0,1fr))';
        s = `<span class="sum-k">${y}年${m}月</span>` + item('当月涨跌', mv)
          + cnt('上涨', vals.filter(v => v > 0).length, '天') + cnt('下跌', vals.filter(v => v < 0).length, '天')
          + (vals.length ? item('最大单日涨', Math.max(...vals)) + item('最大单日跌', Math.min(...vals)) : '');
      } else {
        const ms = `${y}/${p2(m)}/01`, me = `${y}/${p2(m)}/${p2(nd)}`;
        const wk = D.week.filter(w => w.e >= ms && w.s <= me), mx = maxAbs(wk.map(w => w.v));
        html = wk.map((w, k) => cell(`第${k + 1}周`, w.v, mx, '', `${w.s.slice(5)} – ${w.e.slice(5)}`, `${w.s} — ${w.e}`)).join('')
          || '<div class="cal-cell none"><span class="k">本月暂无完整周数据</span><span class="v">—</span></div>';
        grid.style.gridTemplateColumns = 'repeat(auto-fill,minmax(150px,1fr))';
        s = `<span class="sum-k">${y}年${m}月</span>` + item('当月涨跌', mv) + cnt('共', wk.length, '周')
          + cnt('上涨', wk.filter(w => w.v > 0).length, '周') + cnt('下跌', wk.filter(w => w.v < 0).length, '周');
      }
    } else if (mode === '月') {
      const vals = []; for (let k = 1; k <= 12; k++) vals.push(D.month[`${yy}-${p2(k)}`]);
      const mx = maxAbs(vals);
      html = vals.map((v, k) => cell(`${k + 1}月`, v, mx, '', '', `${yy}年${k + 1}月`)).join('');
      grid.style.gridTemplateColumns = 'repeat(6,minmax(0,1fr))';
      const got = vals.map((v, k) => [k + 1, v]).filter(t => ok(t[1]));
      const best = got.reduce((a, t) => !a || t[1] > a[1] ? t : a, null), worst = got.reduce((a, t) => !a || t[1] < a[1] ? t : a, null);
      s = `<span class="sum-k">${yy}年</span>` + item('全年涨跌', D.year[String(yy)])
        + cnt('上涨', got.filter(t => t[1] > 0).length, '个月') + cnt('下跌', got.filter(t => t[1] < 0).length, '个月')
        + (best ? item(`最好 ${best[0]}月`, best[1]) + item(`最差 ${worst[0]}月`, worst[1]) : '');
    } else {
      const ys = Object.keys(D.year).sort(), vals = ys.map(y => D.year[y]), mx = maxAbs(vals);
      html = ys.map(y => cell(`${y}年`, D.year[y], mx, '', '', `${y}年`)).join('');
      grid.style.gridTemplateColumns = 'repeat(6,minmax(0,1fr))';
      const got = ys.map(y => [y, D.year[y]]);
      const best = got.reduce((a, t) => !a || t[1] > a[1] ? t : a, null), worst = got.reduce((a, t) => !a || t[1] < a[1] ? t : a, null);
      s = cnt('共', ys.length, '年') + cnt('上涨', got.filter(t => t[1] > 0).length, '年') + cnt('下跌', got.filter(t => t[1] < 0).length, '年')
        + (best ? item(`最好 ${best[0]}年`, best[1]) + item(`最差 ${worst[0]}年`, worst[1]) : '');
    }
    grid.innerHTML = html; sum.innerHTML = s; fit();
  }
  function fit() {}   // 高度由 st.iframe(height="content") 自动测量，组件内不再改 iframe 尺寸
  render();
})();
</script>"""
    return (template.replace("__BASE_CSS__", _COMP_BASE_CSS).replace("__CAL_CSS__", _CAL_CSS)
            .replace("__CAL_DATA__", data))


# ------------------------------------------------------------------
# 多基金走势对比组件（iframe）：与 _scroll_chart_html 同交互、同样式，多条线同图
# ------------------------------------------------------------------
_CMP_COLORS = ["#2563EB", "#D97706", "#7C3AED", "#0891B2", "#DB2777",
               "#4F46E5", "#EA580C", "#0F172A", "#A16207", "#9333EA"]   # 避开红/绿，红绿只表示涨跌

_CMP_CSS = r"""
#legend{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
.lg{font:inherit;font-size:12px;display:inline-flex;align-items:center;gap:6px;border:1px solid #E2E8F0;border-radius:999px;
  background:#fff;color:#0F172A;padding:5px 12px;cursor:pointer;max-width:100%}
.lg:hover{border-color:#CBD5E1}
.lg i{width:10px;height:10px;border-radius:50%;flex:none}
.lg span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:280px}
.lg[aria-pressed="false"]{opacity:.45}.lg[aria-pressed="false"] span{text-decoration:line-through}
.hint{font-size:12px;color:#94A3B8}
.tbl-wrap{overflow-x:auto}
.cmp-tbl{width:100%;border-collapse:collapse;margin-top:12px;font-size:13px;font-variant-numeric:tabular-nums}
.cmp-tbl th{font-weight:500;color:#475569;font-size:12px;text-align:right;padding:8px 10px;border-bottom:1px solid #E2E8F0;white-space:nowrap}
.cmp-tbl td{text-align:right;padding:10px;border-bottom:1px solid #EEF2F7;white-space:nowrap}
.cmp-tbl th:first-child,.cmp-tbl td:first-child{text-align:left;padding-left:0}
.cmp-tbl td:first-child{max-width:320px;overflow:hidden;text-overflow:ellipsis;color:#0F172A}
.cmp-tbl td b{font-weight:600}
.cmp-tbl i,#tip i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:8px;vertical-align:0}
#tip{width:420px}
#tip .tip-row{display:grid;grid-template-columns:minmax(0,1fr) 62px 66px 62px;gap:8px}
#tip .tip-row .tip-label{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#tip .tip-row b{text-align:right}
#tip .tip-head{color:#94A3B8;font-size:11px}#tip .tip-head span:not(:first-child){text-align:right}
"""


def _compare_payload(series_map):
    """多基金按期对齐（日=日期、月=年月、年=年份），返回 names / histories（与走势组件同结构）。"""
    names = list(series_map)
    hist = {}
    keyfmt = {"日": "%Y%m%d", "月": "%Y%m", "年": "%Y"}
    for period in ("日", "月", "年"):
        keyed = {}
        for nm, s in series_map.items():
            agg = _trend_aggregate(s, period)
            keyed[nm] = {t.strftime(keyfmt[period]): (t, float(v)) for t, v in agg.items()}
        keys = sorted(set().union(*[k.keys() for k in keyed.values()]))
        if not keys:
            continue
        stamps = [max(keyed[nm][k][0] for nm in names if k in keyed[nm]) for k in keys]
        idx = pd.Series(range(len(stamps)), index=pd.DatetimeIndex(stamps))
        hist[period] = {
            "labels": [_period_label(t, period) for t in stamps],
            "dates": [t.strftime("%Y/%m/%d") for t in stamps],
            "vals": {nm: [round(keyed[nm][k][1], 6) if k in keyed[nm] else None for k in keys] for nm in names},
            "windows": {label: {"start": _trend_window_start(idx, span),
                                "count": len(idx) - _trend_window_start(idx, span)}
                        for label, span in _TREND_RANGES.items()},
        }
    return names, hist


def _compare_chart_html(series_map, height=560, default_range="近1年"):
    names, hist = _compare_payload(series_map)
    payload = json.dumps({"names": names, "colors": _CMP_COLORS, "histories": hist,
                          "height": int(height), "defaultRange": default_range},
                         ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    btns = _range_buttons(default_range)
    template = r"""<style>
__BASE_CSS__
__CMP_CSS__
</style>
<div id="wrap" aria-busy="false">
<div class="heading"><h3><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4v16h16M7 14l4-5 4 3 5-7"/></svg>走势对比</h3><span id="updating" role="status">正在更新</span></div>
<div class="controls"><div id="range-controls" role="group" aria-label="常用区间">__BTNS__</div>
<select id="period" aria-label="周期"><option value="日">日线</option><option value="月">月线</option><option value="年">年线</option></select></div>
<div id="legend"></div>
<div class="state-line"><span id="selection" aria-live="polite"></span><span class="date-line"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5" width="16" height="15" rx="2" fill="none"/><path d="M8 3v5m8-5v5M4 10h16"/></svg><span id="range"></span></span></div>
<div id="notice" role="status"></div>
<svg id="chart" role="img" aria-label="多基金走势对比，可拖动和缩放" tabindex="0"></svg>
<div id="stats"></div><div id="tip"></div>
</div>
<script>
(() => {
  const D = __CMP_DATA__;
  const names = D.names, COL = D.colors;
  const svg = document.getElementById('chart'), wrap = document.getElementById('wrap');
  const tip = document.getElementById('tip'), range = document.getElementById('range'), legend = document.getElementById('legend');
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const valid = v => v !== null && v !== undefined && Number.isFinite(v);
  const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  const pct = v => valid(v) ? (v > 0 ? '+' : '') + v.toFixed(2) + '%' : '—';
  const color = v => !valid(v) || Math.abs(v) < 1e-10 ? '#475569' : (v > 0 ? '#C52828' : '#16703B');
  const col = nm => COL[names.indexOf(nm) % COL.length];
  const PPY = {'日': 252, '月': 12, '年': 1};
  const toMs = s => new Date(s.replace(/\//g, '-') + 'T00:00:00').getTime();
  for (const k in D.histories) {            // 各基金单期涨跌幅：相对本基金上一条有效记录
    const Hh = D.histories[k]; Hh.steps = {};
    for (const nm of names) {
      const v = Hh.vals[nm], r = new Array(v.length).fill(null); let prev = null;
      for (let i = 0; i < v.length; i++) if (valid(v[i])) { if (prev !== null && prev > 0) r[i] = (v[i] / prev - 1) * 100; prev = v[i]; }
      Hh.steps[nm] = r;
    }
  }
  // 与单只走势同一套记忆：切视图 / 增删基金都会重建 iframe，区间与周期从 localStorage 还原
  const STORE = 'awTrend.multi';
  const memo = (() => { try { return JSON.parse(localStorage.getItem(STORE) || '{}'); } catch (e) { return {}; } })();
  const saveMemo = () => { try { localStorage.setItem(STORE, JSON.stringify({period, range: lastRange})); } catch (e) {} };
  let period = D.histories[memo.period] ? memo.period : '日';
  let lastRange = (D.histories[period].windows || {})[memo.range] ? memo.range : D.defaultRange;
  let activeRange = lastRange, customDates = null;
  let P = D.histories[period], n = P.dates.length;
  const hidden = new Set();
  const H = D.height, L = 64, R = 16, T = 32, B = 32, GAP = 30;
  // 与走势分析同一布局：净值 55% / 相对起点涨跌幅 27% / 单期涨跌幅 18%
  const PH = H - T - B - GAP * 2, AH = PH * .55, RH = PH * .27, BH = PH * .18;
  const rTop = T + AH + GAP, bTop = rTop + RH + GAP;
  let initialCount = P.windows[lastRange].count, initialStart = P.windows[lastRange].start;
  let count = initialCount, start = initialStart, W = 0, PW = 0, frame = 0;
  let dragging = null, pinned = null, hover = null, bases = {};
  const periodControl = document.getElementById('period');
  for (const o of periodControl.options) o.disabled = !D.histories[o.value];
  periodControl.value = period;
  legend.innerHTML = names.map((nm, k) => `<button class="lg" data-k="${k}" aria-pressed="true" title="点击隐藏/显示"><i style="background:${col(nm)}"></i><span>${esc(nm)}</span></button>`).join('');
  legend.querySelectorAll('.lg').forEach(b => b.onclick = () => {
    const nm = names[+b.dataset.k];
    if (hidden.has(nm)) hidden.delete(nm); else if (names.length - hidden.size > 1) hidden.add(nm);
    b.setAttribute('aria-pressed', String(!hidden.has(nm))); requestDraw();
  });
  const shown = () => names.filter(nm => !hidden.has(nm));
  const x = i => L + (i + .5 - start) * PW / count;
  const bounds = () => {
    if (count <= 0) return [0, -1];
    let first = Math.max(0, Math.ceil(start - .5 + 1e-8));
    let last = Math.min(n - 1, Math.floor(start + count - .5 - 1e-8));
    if (last < first) first = last = clamp(Math.round(start + count / 2 - .5), 0, n - 1);
    return [first, last];
  };
  const rel = (nm, i) => { const b = bases[nm], v = P.vals[nm][i]; return (b !== null && b !== undefined && valid(v)) ? (v / P.vals[nm][b] - 1) * 100 : null; };
  function requestDraw() { if (!frame) frame = requestAnimationFrame(() => { frame = 0; draw(); }); }
  function update(nextStart, nextCount) {
    if (!n) return;
    count = clamp(nextCount, 1, n);
    start = clamp(nextStart, 0, Math.max(0, n - count));
    activeRange = Math.abs(count - initialCount) < 1e-6 && Math.abs(start - initialStart) < 1e-6 ? lastRange : null;
    const [first, last] = bounds();
    customDates = activeRange ? null : [P.dates[first], P.dates[last]];
    hover = null; requestDraw();
  }
  function useRange(label) {
    lastRange = activeRange = label; customDates = null;
    initialCount = P.windows[label].count; initialStart = P.windows[label].start;
    count = initialCount; start = initialStart; pinned = hover = null;
    wrap.setAttribute('aria-busy', 'true'); requestDraw(); saveMemo();
  }
  document.querySelectorAll('[data-range]').forEach(b => b.onclick = () => useRange(b.dataset.range));
  periodControl.onchange = () => {
    const keepDates = activeRange ? null : customDates;
    period = periodControl.value; P = D.histories[period]; n = P.dates.length;
    initialCount = P.windows[lastRange].count; initialStart = P.windows[lastRange].start;
    if (keepDates) {
      const first = P.dates.findIndex(d => d >= keepDates[0]);
      let last = P.dates.length - 1;
      while (last >= 0 && P.dates[last] > keepDates[1]) last--;
      start = Math.max(0, first); count = first < 0 || last < first ? 0 : last - first + 1;
      activeRange = null;
    } else { start = initialStart; count = initialCount; }
    pinned = hover = null; wrap.setAttribute('aria-busy', 'true'); requestDraw(); saveMemo();
  };
  function zoom(factor, px = L + PW / 2) {
    if (!PW) return;
    const fraction = clamp((px - L) / PW, 0, 1), anchor = start + fraction * count;
    update(anchor - fraction * clamp(count * factor, 1, n), clamp(count * factor, 1, n));
  }
  function line(nm, valAt, yf, first, last, w, dot) {
    const pts = []; let c = '';
    for (let i = first; i <= last; i++) { const v = valAt(nm, i); if (!valid(v)) continue;
      pts.push(`${x(i)},${yf(v)}`); if (dot) c += `<circle cx="${x(i)}" cy="${yf(v)}" r="2.3" fill="${col(nm)}"/>`; }
    return `<polyline points="${pts.join(' ')}" fill="none" stroke="${col(nm)}" stroke-width="${w}" stroke-linejoin="round"/>` + c;
  }
  function draw() {
    const width = wrap.getBoundingClientRect().width;
    if (width <= L + R) return;
    W = width; PW = W - L - R;
    svg.setAttribute('width', W); svg.setAttribute('height', H); svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    const [first, last] = bounds(), visibleCount = Math.max(0, last - first + 1);
    document.querySelectorAll('[data-range]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.range === activeRange)));
    const selection = document.getElementById('selection');
    selection.textContent = `当前：${activeRange || '自选区间'} · ${period}线`;
    selection.dataset.custom = String(!activeRange);
    wrap.setAttribute('aria-busy', 'false');
    if (!visibleCount) {
      range.textContent = customDates ? customDates.join(' — ') : '暂无有效日期';
      document.getElementById('notice').textContent = '该范围暂无此粒度的数据，请更换范围或周期。';
      svg.innerHTML = ''; tip.style.display = 'none'; document.getElementById('stats').innerHTML = ''; fit(); return;
    }
    document.getElementById('notice').textContent = visibleCount === 1 ? '该范围仅有1期数据，保留真实单点。' : '';
    range.textContent = `${P.dates[first]} — ${P.dates[last]}`;
    const S = shown(); bases = {};
    for (const nm of S) { bases[nm] = null; for (let i = first; i <= last; i++) { const v = P.vals[nm][i]; if (valid(v) && v > 0) { bases[nm] = i; break; } } }
    const step = PW / count, dot = step >= 7;
    let grid = '', marks = '', ticks = '';
    // ① 净值面板：各基金自己的复权净值（最新值 = 最新单位净值）；量纲不同时左轴按可见范围统一缩放
    let lo = null, hi = null;
    for (const nm of S) for (let i = first; i <= last; i++) { const v = P.vals[nm][i]; if (valid(v)) { lo = lo === null ? v : Math.min(lo, v); hi = hi === null ? v : Math.max(hi, v); } }
    if (lo === null) { lo = 0; hi = 1; }
    const padN = (hi - lo) * .12 || Math.max(Math.abs(hi) * .02, .01); lo -= padN; hi += padN;
    const yN = v => T + (hi - v) * AH / (hi - lo);
    ticks += `<text x="${L}" y="18" font-size="12" fill="#475569">净值</text>`;
    for (let k = 0; k <= 4; k++) {
      const v = lo + (hi - lo) * k / 4, yy = yN(v);
      grid += `<line x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}" stroke="#EEF2F7"/>`;
      ticks += `<text x="${L-8}" y="${yy+4}" text-anchor="end" font-size="10" fill="#475569">${v.toFixed(hi - lo < .5 ? 4 : 3)}</text>`;
    }
    for (const nm of S) marks += line(nm, (m, i) => P.vals[m][i], yN, first, last, 2, dot);
    // ② 相对起点涨跌幅：各基金以可见区间首个有效值为 0%（同一把尺子比强弱）
    let rlo = 0, rhi = 0;
    for (const nm of S) for (let i = first; i <= last; i++) { const r = rel(nm, i); if (valid(r)) { rlo = Math.min(rlo, r); rhi = Math.max(rhi, r); } }
    const padR = (rhi - rlo) * .1 || 1; rlo -= padR; rhi += padR;
    const yR = v => rTop + (rhi - v) * RH / (rhi - rlo);
    ticks += `<text x="${L}" y="${rTop-10}" font-size="12" fill="#475569">相对起点涨跌幅</text>`
      + `<text x="${L-8}" y="${rTop+9}" text-anchor="end" font-size="11" fill="#475569">${pct(rhi - padR)}</text>`
      + `<text x="${L-8}" y="${yR(0)+3.5}" text-anchor="end" font-size="11" fill="#475569">0%</text>`
      + `<text x="${L-8}" y="${rTop+RH-1}" text-anchor="end" font-size="11" fill="#475569">${pct(rlo + padR)}</text>`;
    marks += `<line x1="${L}" y1="${yR(0)}" x2="${W-R}" y2="${yR(0)}" stroke="#94A3B8" stroke-dasharray="2 4"/>`;
    for (const nm of S) marks += line(nm, rel, yR, first, last, 1.6, false);
    // ③ 单期涨跌幅（0 轴居中）
    const zero = bTop + BH / 2;
    let bmax = .5;
    for (const nm of S) for (let i = first; i <= last; i++) { const v = P.steps[nm][i]; if (valid(v)) bmax = Math.max(bmax, Math.abs(v)); }
    const yB = v => zero - v * (BH / 2 - 4) / bmax;
    ticks += `<text x="${L}" y="${bTop-10}" font-size="12" fill="#475569">单${period}涨跌幅</text>`
      + `<text x="${L-8}" y="${bTop+9}" text-anchor="end" font-size="11" fill="#475569">+${bmax.toFixed(2)}%</text>`
      + `<text x="${L-8}" y="${zero+3.5}" text-anchor="end" font-size="11" fill="#475569">0%</text>`
      + `<text x="${L-8}" y="${bTop+BH-1}" text-anchor="end" font-size="11" fill="#475569">-${bmax.toFixed(2)}%</text>`;
    marks += `<line x1="${L}" y1="${zero}" x2="${W-R}" y2="${zero}" stroke="#E2E8F0" stroke-dasharray="3 3"/>`;
    for (const nm of S) marks += line(nm, (m, i) => P.steps[m][i], yB, first, last, 1.2, false);
    const spacing = Math.max(1, Math.ceil(74 / step)), ids = [];
    for (let i = first; i <= last; i += spacing) ids.push(i);
    if (ids.length > 1 && last - ids[ids.length-1] < spacing) ids.pop();
    if (!ids.includes(last)) ids.push(last);
    const labs = [];
    for (const i of ids) { const cx = clamp(x(i), L + 40, W - R - 40); while (labs.length && cx - labs[labs.length-1].cx < 70) labs.pop(); labs.push({i, cx}); }
    for (const {i, cx} of labs) ticks += `<text x="${cx}" y="${H-15}" text-anchor="middle" font-size="10" fill="#475569">${esc(P.labels[i])}</text>`;
    svg.innerHTML = `<defs><clipPath id="plot-clip"><rect x="${L}" y="${T-5}" width="${PW}" height="${H-T-B+10}"/></clipPath></defs>${grid}<g clip-path="url(#plot-clip)">${marks}<line id="guide" y1="${T}" y2="${H-B}" stroke="#94A3B8" stroke-dasharray="4 4" visibility="hidden"/></g>${ticks}`;
    // 当前可见区间指标（随拖动/缩放/切周期实时重算）
    const rows = S.map(nm => {
      const b = bases[nm]; let e = null;
      for (let i = last; i >= first; i--) if (valid(P.vals[nm][i])) { e = i; break; }
      const head = `<td title="${esc(nm)}"><i style="background:${col(nm)}"></i>${esc(nm)}</td>`;
      if (b === null || e === null) return `<tr>${head}<td colspan="6" style="color:#94A3B8">该区间无数据</td></tr>`;
      const v0 = P.vals[nm][b], v1 = P.vals[nm][e], chg = (v1 / v0 - 1) * 100;
      const yrs = (toMs(P.dates[e]) - toMs(P.dates[b])) / (365.25 * 864e5);
      const ann = yrs >= .25 ? (Math.pow(v1 / v0, 1 / yrs) - 1) * 100 : null;
      let peak = null, mdd = 0; const rs = [];
      for (let i = b; i <= e; i++) { const v = P.vals[nm][i]; if (!valid(v)) continue;
        if (peak === null || v > peak) peak = v; mdd = Math.min(mdd, (v / peak - 1) * 100);
        if (i > b && valid(P.steps[nm][i])) rs.push(P.steps[nm][i] / 100); }
      let vol = null;
      if (rs.length >= 3) { const m = rs.reduce((a, c) => a + c, 0) / rs.length;
        vol = Math.sqrt(rs.reduce((a, c) => a + (c - m) ** 2, 0) / (rs.length - 1)) * Math.sqrt(PPY[period]) * 100; }
      return `<tr>${head}<td>${v0.toFixed(4)} → ${v1.toFixed(4)}</td><td><b style="color:${color(chg)}">${pct(chg)}</b></td><td style="color:${color(ann)}">${pct(ann)}</td>`
        + `<td style="color:${color(mdd)}">${mdd < 0 ? pct(mdd) : '0.00%'}</td><td>${valid(vol) ? vol.toFixed(2) + '%' : '—'}</td>`
        + `<td>${esc(P.dates[b])} — ${esc(P.dates[e])}</td></tr>`;
    }).join('');
    document.getElementById('stats').innerHTML =
      `<div class="summary-main"><div class="summary-result"><span>当前区间指标</span></div>`
      + `<span class="hint">拖动/滚轮平移 · Ctrl+滚轮缩放 · 双击复位 · 点图例隐藏/显示</span></div>`
      + `<div class="tbl-wrap"><table class="cmp-tbl"><thead><tr><th>基金</th><th>净值 起 → 止</th><th>区间涨跌</th><th>年化</th><th>最大回撤</th><th>波动(年化)</th><th>起止</th></tr></thead><tbody>${rows}</tbody></table></div>`
      + `<div class="amp-row"><small>净值为复权净值（最新值 = 最新单位净值，历史按日增长率含分红还原）；以各基金可见区间内首个有效值为 0% 基准；区间不足 3 个月不计年化；波动按${period}收益年化。</small></div>`;
    if (pinned !== null) showTip(pinned); else tip.style.display = 'none';
    fit();
  }
  function showTip(i, clientY = null) {
    const [first, last] = bounds(), guide = document.getElementById('guide');
    if (!Number.isInteger(i) || i < first || i > last) { tip.style.display = 'none'; if (guide) guide.setAttribute('visibility', 'hidden'); return; }
    if (guide) { guide.setAttribute('x1', x(i)); guide.setAttribute('x2', x(i)); guide.setAttribute('visibility', 'visible'); }
    tip.innerHTML = `<b>${esc(P.dates[i])}</b><div class="tip-row tip-head"><span>基金</span><span>净值</span><span>相对起点</span><span>单${period}</span></div>`
      + shown().map(nm => { const r = rel(nm, i), st = P.steps[nm][i], v = P.vals[nm][i];
          return `<div class="tip-row"><span class="tip-label"><i style="background:${col(nm)}"></i>${esc(nm)}</span><b>${valid(v) ? v.toFixed(4) : '—'}</b><b style="color:${color(r)}">${pct(r)}</b><b style="color:${color(st)}">${pct(st)}</b></div>`; }).join('')
      + (pinned !== null ? '<small class="tip-label">已固定，再次点击取消</small>' : '');
    tip.style.display = 'block';
    const wrapBox = wrap.getBoundingClientRect(), chartBox = svg.getBoundingClientRect();
    const chartTop = chartBox.top - wrapBox.top;
    const screenX = chartBox.left - wrapBox.left + x(i) * chartBox.width / W;
    const preferredLeft = screenX + 12 + tip.offsetWidth <= wrapBox.width - 4 ? screenX + 12 : screenX - tip.offsetWidth - 12;
    tip.style.left = clamp(preferredLeft, 4, Math.max(4, wrapBox.width - tip.offsetWidth - 4)) + 'px';
    const cursorY = clientY === null ? null : clientY - chartBox.top;
    const anchorY = cursorY === null ? chartTop + T + 4 : chartTop + cursorY + (cursorY > chartBox.height / 2 ? -tip.offsetHeight - 14 : 14);
    tip.style.top = clamp(anchorY, chartTop + 4, Math.max(chartTop + 4, chartBox.bottom - wrapBox.top - tip.offsetHeight - 4)) + 'px';
  }
  function fit() {}   // 高度由 st.iframe(height="content") 自动测量，组件内不再改 iframe 尺寸
  const localX = e => e.clientX - svg.getBoundingClientRect().left;
  svg.addEventListener('pointerdown', e => {
    if (e.button !== 0 || !PW || !count || localX(e) < L || localX(e) > W - R) return;
    dragging = {id: e.pointerId, x: e.clientX, start, count, moved: false};
    svg.setPointerCapture(e.pointerId); svg.classList.add('dragging');
  });
  svg.addEventListener('pointermove', e => {
    if (dragging) {
      const delta = e.clientX - dragging.x;
      if (Math.abs(delta) > 3) dragging.moved = true;
      if (dragging.moved) { pinned = null; update(dragging.start - delta * dragging.count / PW, dragging.count); }
    } else if (pinned === null && PW) {
      const px = localX(e);
      hover = px < L || px > W - R ? null : Math.floor(start + (px - L) * count / PW);
      showTip(hover, e.clientY);
    }
  });
  function release(e) {
    if (!dragging) return;
    if (!dragging.moved && e.type === 'pointerup') { const i = Math.floor(start + (localX(e) - L) * count / PW); pinned = pinned === i ? null : i; showTip(pinned, e.clientY); }
    if (svg.hasPointerCapture(e.pointerId)) svg.releasePointerCapture(e.pointerId);
    dragging = null; svg.classList.remove('dragging');
  }
  svg.addEventListener('pointerup', release); svg.addEventListener('pointercancel', release);
  svg.addEventListener('pointerleave', () => { if (pinned === null && !dragging) showTip(null); });
  svg.addEventListener('wheel', e => {
    if (!PW || !count) return;
    e.preventDefault(); pinned = null;
    if (e.ctrlKey || e.metaKey) zoom(Math.exp(clamp(e.deltaY, -400, 400) * .003), localX(e));
    else { const delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY; update(start + delta * (e.deltaMode === 1 ? 16 : 1) * count / PW, count); }
  }, {passive: false});
  svg.addEventListener('dblclick', () => useRange(lastRange));
  new ResizeObserver(requestDraw).observe(wrap);
  requestDraw();
})();
</script>"""
    return (template.replace("__BASE_CSS__", _COMP_BASE_CSS).replace("__CMP_CSS__", _CMP_CSS)
            .replace("__BTNS__", btns).replace("__CMP_DATA__", payload))


@st.cache_data(ttl=600, show_spinner=False)
def _val_snapshot():
    """本地估值快照（不发请求，「更新数据」按钮负责刷新）。"""
    from allweather import valuation as _val
    return _val.load_snapshot()


def _val_tag_html(asset, code, name):
    """基金走势页头部的估值标签：能对应到跟踪指数时显示，否则返回空串。"""
    from allweather import valuation as _val
    idx = _val.index_for_fund(code, name, asset)
    snap = _val_snapshot()
    if not idx or snap.empty or idx not in set(snap["代码"]):
        return ""
    r = snap[snap["代码"] == idx].iloc[0]
    lv = {"低估": "low", "适中": "mid", "高估": "high"}.get(r["估值"], "mid")
    pe = f'PE 百分位 <b>{r["PE百分位"]:.0f}%</b>' if pd.notna(r["PE百分位"]) else ""
    pb = f'PB 百分位 <b>{r["PB百分位"]:.0f}%</b>'
    tip = (f'跟踪指数 {r["名称"]}（{idx}）· PE {r["PE"]:.2f} · PB {r["PB"]:.2f} · 股息率 {r["股息率"]:.2f}%'
           f' · 近10年百分位，蛋卷估值 {pd.Timestamp(r["数据日"]):%Y/%m/%d}') if pd.notna(r["PE"]) else ""
    return (f'<span class="fh-val" title="{html_escape(tip)}"><span class="lv {lv}">{r["估值"]}</span>'
            f'{html_escape(r["名称"])} · {pe}{" · " if pe else ""}{pb}</span>')


# ------------------------------------------------------------------
# 指数估值组件（iframe）：筛选/排序表格 + 点选指数看近 10 年 PE/PB 走势；全部在组件内完成，不触发整页重跑
# ------------------------------------------------------------------
_VAL_CSS = r"""
.filters{display:flex;align-items:center;gap:10px;margin-bottom:4px}
#q{font:inherit;font-size:14px;border:1px solid #E2E8F0;border-radius:12px;padding:6px 12px;min-height:42px;width:200px;color:#0F172A}
#q:focus{outline:none;border-color:#3B82F6;box-shadow:0 0 0 3px rgba(59,130,246,.12)}
#q::placeholder{color:#94A3B8}
/* 表格：固定列宽（table-layout:fixed + colgroup），每列表头与数值同一对齐方式、同一内边距 */
.vt-wrap{max-height:520px;overflow:auto;margin-top:16px;border:1px solid #E2E8F0;border-radius:12px}
.vt{width:100%;table-layout:fixed;border-collapse:separate;border-spacing:0;font-size:13px;font-variant-numeric:tabular-nums}
.vt th,.vt td{padding:0 12px;height:52px;border-bottom:1px solid #EEF2F7;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;vertical-align:middle}
.vt th{position:sticky;top:0;z-index:1;height:40px;background:#F8FAFC;border-bottom:1px solid #E2E8F0;
  font-weight:500;color:#475569;font-size:12px;cursor:pointer;user-select:none}
.vt th:hover{color:#0F172A}
.vt .l{text-align:left}.vt .c{text-align:center}.vt .r{text-align:right}
/* 排序箭头：右对齐列放在文字左侧、其余列放右侧，且用绝对定位不占宽度 → 表头文字边缘与数值对齐 */
.vt th span{position:relative;display:inline-block}
.vt th span::after{position:absolute;top:0;font-size:11px;color:#C52828;content:''}
.vt th.l span::after,.vt th.c span::after{left:100%;margin-left:4px}
.vt th.r span::after{right:100%;margin-right:4px}
.vt th[data-dir="asc"] span::after{content:'▲'}.vt th[data-dir="desc"] span::after{content:'▼'}
.vt th[data-dir]{color:#0F172A}
.vt tbody tr{cursor:pointer;transition:background-color .1s}.vt tbody tr:hover{background:#F8FAFC}
.vt tbody tr:last-child td{border-bottom:0}
.vt th:first-child,.vt td:first-child{padding-left:16px}.vt th:last-child,.vt td:last-child{padding-right:16px}
.vt tbody tr.sel{background:#EFF6FF}.vt tbody tr.sel td:first-child{box-shadow:inset 3px 0 0 #3B82F6}
.ix{display:flex;flex-direction:column;justify-content:center;line-height:1.35;min-width:0}
.ix .nm{color:#0F172A;font-weight:500;overflow:hidden;text-overflow:ellipsis}
.ix .cd{color:#94A3B8;font-size:11px}
.mine{font-size:10px;font-weight:500;color:#1E40AF;background:#DBEAFE;border-radius:999px;padding:1px 6px;margin-left:6px;vertical-align:1px}
.lv{display:inline-block;min-width:36px;text-align:center;border-radius:999px;padding:2px 8px;font-size:12px;font-weight:600;line-height:1.5}
.lv.low{background:#F0FDF4;color:#16703B}.lv.mid{background:#F1F5F9;color:#475569}.lv.high{background:#FEF2F2;color:#C52828}
.mk{font-size:12px;color:#475569}
.na{color:#CBD5E1}
/* 百分位：数值右对齐贴列边，进度条在数值左侧，宽度固定 */
/* 列宽按比例分配（合计 100%），宽屏时多出的宽度各列均分，不再全堆给指数列；
   百分位/回撤列里的进度条可收缩（24~64px），数字固定宽度，列变窄时先缩进度条，不截断数字 */
.vt .c-nm{width:15%}.vt .c-lv{width:7%}.vt .c-pe{width:7%}.vt .c-pb{width:7%}.vt .c-pct{width:12.5%}
.vt .c-dy{width:7.5%}.vt .c-roe{width:7%}.vt .c-dd{width:12.5%}.vt .c-sc{width:12%}
.pc,.dd{display:flex !important;align-items:center;justify-content:flex-end;gap:8px;width:100%}
.pc .bar{flex:0 1 64px;min-width:24px;height:6px;border-radius:999px;background:#EEF2F7;position:relative;overflow:hidden}
.pc .bar i{position:absolute;left:0;top:0;bottom:0;border-radius:999px}
.pc b{font-weight:600;flex:none;width:48px;text-align:right}
/* 当前回撤：跌幅越深绿色越满（跌=绿；按模型回撤越深越接近"便宜"） */
.dd .bar{flex:0 1 64px;min-width:24px;height:6px;border-radius:999px;background:#EEF2F7;position:relative;overflow:hidden}
.dd .bar i{position:absolute;left:0;top:0;bottom:0;border-radius:999px;background:#16703B}
.dd b{font-weight:600;flex:none;width:48px;text-align:right;color:#334155}
/* 评分：猎杀区/稳中求胜=绿（便宜）、中性=灰、高位警戒=琥珀、泡沫区=红（贵） */
.sc{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:2px 10px 2px 4px;font-size:12px;font-weight:600;white-space:nowrap;border:1px solid transparent}
.sc b{display:inline-flex;align-items:center;justify-content:center;min-width:24px;height:20px;border-radius:999px;font-size:12px;color:#fff;font-variant-numeric:tabular-nums}
.sc.r0{background:#F0FDF4;color:#166534;border-color:#BBF7D0}.sc.r0 b{background:#16703B}
.sc.r1{background:#F7FEE7;color:#3F6212;border-color:#D9F99D}.sc.r1 b{background:#65A30D}
.sc.r2{background:#F8FAFC;color:#475569;border-color:#E2E8F0}.sc.r2 b{background:#94A3B8}
.sc.r3{background:#FFFBEB;color:#92400E;border-color:#FDE68A}.sc.r3 b{background:#D97706}
.sc.r4{background:#FEF2F2;color:#991B1B;border-color:#FECACA}.sc.r4 b{background:#C52828}
.empty{padding:32px;text-align:center;color:#94A3B8;height:auto}
.foot{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-top:10px;font-size:12px;color:#94A3B8}
.foot b{color:#475569;font-weight:600}
/* 详情：选中指数的估值走势 */
#detail{border-top:1px solid #E2E8F0;margin-top:24px;padding-top:20px}
.d-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.d-title{font-size:16px;font-weight:600;color:#0F172A}.d-title small{font-size:12px;color:#94A3B8;font-weight:400;margin-left:8px}
.seg{display:flex;gap:2px;border-bottom:1px solid #E2E8F0}
.seg button{font:inherit;font-size:13px;border:0;border-bottom:2px solid transparent;background:transparent;color:#475569;
  padding:8px 12px;cursor:pointer;margin-bottom:-1px}
.seg button:hover{color:#0F172A}
.seg button[aria-pressed="true"]{color:#C52828;font-weight:600;border-bottom-color:#C52828}
/* KPI：flex 换行，每行最后的格子自动撑满 → 不会出现空白灰格 */
.d-kpi{display:flex;flex-wrap:wrap;gap:1px;background:#EEF2F7;margin-top:16px;border:1px solid #EEF2F7;border-radius:12px;overflow:hidden}
.d-kpi>div{flex:1 1 104px;padding:12px 14px;background:#fff;min-width:0}
.d-kpi small{display:block;font-size:12px;color:#475569;white-space:nowrap}
.d-kpi>div>b{display:block;font-size:18px;font-weight:600;color:#0F172A;font-variant-numeric:tabular-nums;margin-top:4px;line-height:1.4;white-space:nowrap}
.d-kpi .sc{font-size:12px;vertical-align:2px}
#vchart{display:block;width:100%;margin-top:12px}
#vtip{position:absolute;pointer-events:none;background:#fff;color:#0F172A;border:1px solid #E2E8F0;font-size:12px;line-height:1.8;
  padding:8px 12px;border-radius:8px;display:none;z-index:10;box-shadow:0 4px 16px rgba(15,23,42,.16);font-variant-numeric:tabular-nums}
#vtip .tip-row{display:flex;justify-content:space-between;gap:16px}#vtip .tip-label{color:#475569}
/* 窄屏：先去掉百分位进度条（只留数字），表格不出现横向滚动 */
/* 窄屏逐级收缩：先去进度条（百分位/回撤列变窄）→ 再隐藏股息率、ROE → 再隐藏 PE、PB 原值 */
/* 断点按 iframe 自身宽度（≈ 页面内容区宽 − 卡片内边距）：1440 屏时约 1010px，仍显示进度条 */
@media(max-width:900px){.pc .bar,.dd .bar{display:none}.vt .o1{display:none}#q{width:160px}
  .vt .c-nm{width:22%}.vt .c-pct,.vt .c-dd{width:13%}.vt .c-sc{width:15%}}
@media(max-width:620px){.vt .o2,.vt .c-lv{display:none}.vt .c-nm{width:28%}.vt .c-pct,.vt .c-dd{width:17%}.vt .c-sc{width:21%}.vt th,.vt td{padding:0 8px}.vt th:first-child,.vt td:first-child{padding-left:12px}}
@media(max-width:640px){.filters{width:100%}#q{flex:1;width:auto}}
"""


@st.cache_data(ttl=600, show_spinner=False)
def _valuation_payload():
    from allweather import valuation as _val
    snap = _val.load_snapshot()
    if snap.empty:
        return None
    hist = {}
    for c in snap["代码"]:
        h = _val.load_history(c)
        if h.empty:
            continue
        hist[c] = {"d": [t.strftime("%Y/%m/%d") for t in h.index],
                   "pe": [round(float(v), 3) if pd.notna(v) and v > 0 else None for v in h.get("pe", pd.Series(index=h.index))],
                   "pb": [round(float(v), 4) if pd.notna(v) and v > 0 else None for v in h.get("pb", pd.Series(index=h.index))]}
    mine = {v: k for k, v in _val.ASSET_INDEX.items()}
    rows = []
    for r in snap.to_dict("records"):
        dd = _val.drawdown_10y(r["代码"])
        tot, vs, ps, lb = _val.score(r["PE百分位"], r["PB百分位"], dd)
        rows.append({"code": r["代码"], "name": r["名称"], "mkt": r["市场"], "lv": r["估值"],
                     "pe": r["PE"] if pd.notna(r["PE"]) else None,
                     "pep": r["PE百分位"] if pd.notna(r["PE百分位"]) else None,
                     "pb": r["PB"], "pbp": r["PB百分位"], "dy": r["股息率"], "roe": r["ROE"],
                     "dd": round(dd * 100, 2) if dd is not None else None,
                     "sc": tot, "vs": vs, "ps": ps, "rt": lb,
                     "mine": _ASSET_LABEL.get(mine[r["代码"]], "").split(" (")[0] if r["代码"] in mine else ""})
    return {"rows": rows, "hist": hist, "date": f"{pd.Timestamp(snap['数据日'].max()):%Y/%m/%d}"}


def _valuation_html(payload):
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    template = r"""<style>
__BASE_CSS__
__VAL_CSS__
</style>
<div id="wrap">
<div class="heading"><h3><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19h16M7 16V9m5 7V5m5 11v-4"/></svg>指数估值</h3><span class="hint" id="asof"></span></div>
<div class="controls"><div id="range-controls" role="group" aria-label="市场">
<button data-range="全部" aria-pressed="true">全部</button><button data-range="A股" aria-pressed="false">A股</button><button data-range="港股" aria-pressed="false">港股</button><button data-range="中概" aria-pressed="false">中概</button><button data-range="海外" aria-pressed="false">海外</button>
</div><div class="filters"><input id="q" placeholder="搜索指数名称或代码" autocomplete="off"><select id="lvsel" aria-label="估值档"><option value="">全部估值</option><option>低估</option><option>适中</option><option>高估</option></select></div></div>
<div class="vt-wrap"><table class="vt">
<thead><tr>
<th class="l c-nm" data-k="name"><span>指数</span></th><th class="l c-lv" data-k="lvn"><span>估值</span></th>
<th class="r o2 c-pe" data-k="pe"><span>PE</span></th><th class="r c-pct" data-k="pep"><span>PE 百分位</span></th>
<th class="r o2 c-pb" data-k="pb"><span>PB</span></th><th class="r c-pct" data-k="pbp"><span>PB 百分位</span></th>
<th class="r o1 c-dy" data-k="dy"><span>股息率</span></th><th class="r o1 c-roe" data-k="roe"><span>ROE</span></th>
<th class="r c-dd" data-k="dd" title="当前点位距近10年最高点的跌幅"><span>当前回撤</span></th>
<th class="l c-sc" data-k="sc" title="评分 = 估值分(0~12) + 回撤分(0~8)，满分 20"><span>评分</span></th></tr></thead><tbody id="tb"></tbody></table></div>
<div class="foot"><span id="cnt"></span><span>评分 = 估值分（0~12，PE/PB 百分位取较高者，越低越高分）+ 回撤分（0~8，近10年回撤 × 16）· 点击表头排序 · 点击行查看估值走势</span></div>
<div id="detail"></div><div id="vtip"></div>
</div>
<script>
(() => {
  const D = __VAL_DATA__;
  const wrap = document.getElementById('wrap'), tb = document.getElementById('tb'), detail = document.getElementById('detail'), vtip = document.getElementById('vtip');
  const ok = v => v !== null && v !== undefined && Number.isFinite(v);
  const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  const LV = {'低估': 'low', '适中': 'mid', '高估': 'high'}, LVN = {'低估': 0, '适中': 1, '高估': 2};
  D.rows.forEach(r => r.lvn = LVN[r.lv] ?? 1);
  // 百分位着色：0%（历史最便宜）绿 → 50% 灰 → 100%（历史最贵）红
  const pcColor = p => !ok(p) ? '#CBD5E1' : (p < 30 ? '#16703B' : (p > 70 ? '#C52828' : '#94A3B8'));
  const pcText = p => !ok(p) ? '#94A3B8' : (p < 30 ? '#16703B' : (p > 70 ? '#C52828' : '#334155'));
  const pc = p => ok(p) ? `<span class="pc"><span class="bar"><i style="width:${Math.max(2, p)}%;background:${pcColor(p)}"></i></span><b style="color:${pcText(p)}">${p.toFixed(1)}%</b></span>` : '<span class="na">—</span>';
  const num = (v, d, u = '') => ok(v) ? v.toFixed(d) + u : '<span class="na">—</span>';
  // 默认按评分从高到低；未手动点选时，详情图跟随当前列表第一行（排序/筛选变化后也跟着变）
  let mkt = '全部', q = '', lv = '', sortK = 'sc', sortDir = -1, picked = null, sel = null;
  const RT = {'猎杀区': 'r0', '稳中求胜': 'r1', '中性观察': 'r2', '高位警戒': 'r3', '泡沫区': 'r4'};
  const ddCell = v => ok(v) ? `<span class="dd"><span class="bar"><i style="width:${Math.min(100, Math.max(2, v * 2))}%"></i></span><b>${v.toFixed(1)}%</b></span>`
    : '<span class="na" title="暂无该指数的行情源，回撤分按 0 计">—</span>';
  const scCell = r => `<span class="sc ${RT[r.rt] || 'r2'}" title="估值分 ${r.vs}/12 + 回撤分 ${r.ps}/8${ok(r.dd) ? '' : '（缺回撤数据）'}"><b>${r.sc}</b>${r.rt}</span>`;
  document.getElementById('asof').textContent = `数据日 ${D.date} · 百分位为近10年`;
  document.querySelectorAll('[data-range]').forEach(b => b.onclick = () => { mkt = b.dataset.range; render(); });
  document.getElementById('q').oninput = e => { q = e.target.value.trim().toLowerCase(); render(); };
  document.getElementById('lvsel').onchange = e => { lv = e.target.value; render(); };
  document.querySelectorAll('.vt th').forEach(th => th.onclick = () => {
    // 评分 / 回撤 / 股息率 / ROE 首次点击按从高到低，其余从低到高
    const k = th.dataset.k; if (sortK === k) sortDir = -sortDir; else { sortK = k; sortDir = ['sc', 'dd', 'dy', 'roe'].includes(k) ? -1 : 1; } render();
  });
  function render() {
    document.querySelectorAll('[data-range]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.range === mkt)));
    document.querySelectorAll('.vt th').forEach(th => {
      if (th.dataset.k === sortK) th.dataset.dir = sortDir > 0 ? 'asc' : 'desc'; else th.removeAttribute('data-dir'); });
    const rows = D.rows.filter(r => (mkt === '全部' || r.mkt === mkt) && (!lv || r.lv === lv)
      && (!q || r.name.toLowerCase().includes(q) || r.code.toLowerCase().includes(q)))
      .sort((a, b) => { const x = a[sortK], y = b[sortK];
        if (!ok(x) && typeof x !== 'string') return 1; if (!ok(y) && typeof y !== 'string') return -1;
        const c = (typeof x === 'string' ? x.localeCompare(y, 'zh') : x - y) * sortDir;
        return c || ((a.pep ?? 101) - (b.pep ?? 101)); });          // 同分时 PE 百分位低的在前
    sel = (picked && rows.some(r => r.code === picked)) ? picked : (rows[0] ? rows[0].code : null);
    tb.innerHTML = rows.length ? rows.map(r => `<tr data-code="${r.code}" class="${r.code === sel ? 'sel' : ''}">`
      + `<td class="l"><div class="ix"><span class="nm" title="${esc(r.name)}">${esc(r.name)}${r.mine ? `<span class="mine" title="对应本策略资产：${esc(r.mine)}">策略资产</span>` : ''}</span><span class="cd">${r.code} · ${r.mkt}</span></div></td>`
      + `<td class="l c-lv"><span class="lv ${LV[r.lv] || 'mid'}">${r.lv}</span></td>`
      + `<td class="r o2">${num(r.pe, 2)}</td><td class="r">${pc(r.pep)}</td><td class="r o2">${num(r.pb, 2)}</td><td class="r">${pc(r.pbp)}</td>`
      + `<td class="r o1">${num(r.dy, 2, '%')}</td><td class="r o1">${num(r.roe, 1, '%')}</td>`
      + `<td class="r">${ddCell(r.dd)}</td><td class="l">${scCell(r)}</td></tr>`).join('')
      : '<tr><td colspan="10" class="empty">没有符合条件的指数</td></tr>';
    tb.querySelectorAll('tr[data-code]').forEach(tr => tr.onclick = () => { picked = tr.dataset.code; render(); });
    const n = {低估: 0, 适中: 0, 高估: 0}; rows.forEach(r => n[r.lv] = (n[r.lv] || 0) + 1);
    document.getElementById('cnt').innerHTML = `共 <b>${rows.length}</b> 个指数 · 低估 <b style="color:#16703B">${n['低估']}</b> · 适中 <b>${n['适中']}</b> · 高估 <b style="color:#C52828">${n['高估']}</b>`;
    drawDetail();
  }
  // ---- 选中指数的近 10 年 PE / PB 走势 ----
  let vr = '全部';
  function drawDetail() {
    const r = D.rows.find(x => x.code === sel), h = D.hist[sel];
    if (!r || !h) { detail.innerHTML = '<div class="empty">该指数暂无估值历史</div>'; return; }
    const ranges = ['近1年', '近3年', '近5年', '全部'];
    detail.innerHTML = `<div class="d-head"><div class="d-title">${esc(r.name)}<small>${r.code} · ${r.mkt} · 估值走势${picked ? '' : '（默认显示列表第一行，点击任意行切换）'}</small></div>`
      + `<div class="seg" role="group" aria-label="区间">${ranges.map(x => `<button data-vr="${x}" aria-pressed="${x === vr}">${x}</button>`).join('')}</div></div>`
      + `<div class="d-kpi"><div><small>估值</small><b><span class="lv ${LV[r.lv] || 'mid'}">${r.lv}</span></b></div>`
      + `<div><small>PE</small><b>${num(r.pe, 2)}</b></div><div><small>PE 百分位</small><b style="color:${pcText(r.pep)}">${num(r.pep, 1, '%')}</b></div>`
      + `<div><small>PB</small><b>${num(r.pb, 2)}</b></div><div><small>PB 百分位</small><b style="color:${pcText(r.pbp)}">${num(r.pbp, 1, '%')}</b></div>`
      + `<div><small>股息率</small><b>${num(r.dy, 2, '%')}</b></div><div><small>ROE</small><b>${num(r.roe, 1, '%')}</b></div>`
      + `<div><small>当前回撤</small><b>${num(r.dd, 1, '%')}</b></div><div><small>评分</small><b>${scCell(r)}</b></div></div>`
      + `<svg id="vchart" role="img" aria-label="估值走势"></svg>`
      + `<div class="amp-row"><small>虚线为该指数近10年 30% / 50% / 70% 分位；悬停查看当期数值。</small></div>`;
    detail.querySelectorAll('[data-vr]').forEach(b => b.onclick = () => { vr = b.dataset.vr; drawDetail(); });
    const svg = document.getElementById('vchart');
    const W = Math.max(320, Math.round(detail.getBoundingClientRect().width) || 900), H = 380, L = 56, R = 84, T = 26, B = 30, GAP = 34;
    const PW = W - L - R, PH = (H - T - B - GAP) / 2;
    const cut = {'近1年': 1, '近3年': 3, '近5年': 5}[vr];
    let i0 = 0;
    if (cut) { const last = new Date(h.d[h.d.length - 1].replace(/\//g, '-')); last.setFullYear(last.getFullYear() - cut);
      const c = last.toISOString().slice(0, 10).replace(/-/g, '/'); i0 = Math.max(0, h.d.findIndex(d => d >= c)); }
    const n = h.d.length - i0, x = i => L + (i - i0 + .5) * PW / n;
    const q = (arr, p) => { const v = arr.filter(ok).slice().sort((a, b) => a - b); if (!v.length) return null;
      const k = (v.length - 1) * p, f = Math.floor(k); return v[f] + (v[Math.min(f + 1, v.length - 1)] - v[f]) * (k - f); };
    let out = '', ticks = '';
    const panes = [['pe', 'PE', T], ['pb', 'PB', T + PH + GAP]];
    const scales = {};
    for (const [k, lab, top] of panes) {
      const vis = h[k].slice(i0).filter(ok);
      ticks += `<text x="${L}" y="${top - 8}" font-size="12" fill="#475569">${lab}</text>`;
      if (!vis.length) { ticks += `<text x="${L + PW / 2}" y="${top + PH / 2}" text-anchor="middle" font-size="12" fill="#94A3B8">无${lab}数据</text>`; continue; }
      const bands = [.3, .5, .7].map(p => q(h[k], p));
      let lo = Math.min(...vis, ...bands), hi = Math.max(...vis, ...bands); const pad = (hi - lo) * .1 || hi * .05 || 1; lo -= pad; hi += pad;
      const y = v => top + (hi - v) * PH / (hi - lo); scales[k] = y;
      for (let j = 0; j <= 3; j++) { const v = lo + (hi - lo) * j / 3;
        out += `<line x1="${L}" y1="${y(v)}" x2="${W - R}" y2="${y(v)}" stroke="#EEF2F7"/>`;
        ticks += `<text x="${L - 8}" y="${y(v) + 4}" text-anchor="end" font-size="10" fill="#475569">${v.toFixed(k === 'pb' ? 2 : 1)}</text>`; }
      // 分位线：线画在绘图区，标签放右侧留白区并纵向错开（最少 13px），不压曲线、不互相重叠
      const BC = ['#16703B', '#94A3B8', '#C52828'], BL = ['30%', '50%', '70%'];
      const ys = bands.map(b => y(b));
      const tags = [2, 1, 0].map(j => ({ j, y: ys[j] }));           // 从上到下：70% → 50% → 30%
      for (let t = 1; t < tags.length; t++) tags[t].y = Math.max(tags[t].y, tags[t - 1].y + 13);
      for (let t = tags.length - 2; t >= 0; t--) tags[t].y = Math.min(tags[t].y, tags[t + 1].y - 13);
      bands.forEach((b, j) => {
        out += `<line x1="${L}" y1="${ys[j]}" x2="${W - R}" y2="${ys[j]}" stroke="${BC[j]}" stroke-dasharray="4 4" opacity=".7"/>`; });
      tags.forEach(({ j, y: ly }) => {
        ticks += `<text x="${W - R + 8}" y="${ly + 3.5}" font-size="10" fill="${BC[j]}">${BL[j]} ${bands[j].toFixed(k === 'pb' ? 2 : 1)}</text>`; });
      const pts = []; for (let i = i0; i < h.d.length; i++) if (ok(h[k][i])) pts.push(`${x(i)},${y(h[k][i])}`);
      out += `<polyline points="${pts.join(' ')}" fill="none" stroke="#3B82F6" stroke-width="1.8" stroke-linejoin="round"/>`;
      const li = h[k].length - 1; if (ok(h[k][li])) out += `<circle cx="${x(li)}" cy="${y(h[k][li])}" r="4" fill="#3B82F6" stroke="#fff" stroke-width="1.5"/>`;
    }
    // 横轴日期：最少间隔 96px，第一个和最后一个对齐绘图区两端
    const slots = Math.max(2, Math.floor(PW / 96)), xs = [];
    for (let t = 0; t <= slots; t++) xs.push(Math.round(i0 + (n - 1) * t / slots));
    [...new Set(xs)].forEach((i, t, arr) => {
      const anchor = t === 0 ? 'start' : (t === arr.length - 1 ? 'end' : 'middle');
      const px = t === 0 ? L : (t === arr.length - 1 ? W - R : x(i));
      ticks += `<text x="${px}" y="${H - 8}" text-anchor="${anchor}" font-size="10" fill="#475569">${h.d[i]}</text>`; });
    svg.setAttribute('width', W); svg.setAttribute('height', H); svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.innerHTML = out + `<line id="vg" y1="${T}" y2="${H - B}" stroke="#94A3B8" stroke-dasharray="4 4" visibility="hidden"/>` + ticks;
    // 悬停：当期 PE/PB 及其在近10年中的百分位
    const pctAt = (arr, v) => { const a = arr.filter(ok); return a.length ? a.filter(t => t < v).length / a.length * 100 : null; };
    svg.onmousemove = e => {
      const bx = svg.getBoundingClientRect(), px = (e.clientX - bx.left) * W / bx.width;
      if (px < L || px > W - R) { vtip.style.display = 'none'; document.getElementById('vg').setAttribute('visibility', 'hidden'); return; }
      const i = Math.min(h.d.length - 1, Math.max(i0, Math.floor(i0 + (px - L) * n / PW)));
      const g = document.getElementById('vg'); g.setAttribute('x1', x(i)); g.setAttribute('x2', x(i)); g.setAttribute('visibility', 'visible');
      const row = (lab, k, d) => ok(h[k][i]) ? `<div class="tip-row"><span class="tip-label">${lab}</span><b>${h[k][i].toFixed(d)}（${pctAt(h[k], h[k][i]).toFixed(0)}%分位）</b></div>` : '';
      vtip.innerHTML = `<b>${h.d[i]}</b>` + row('PE', 'pe', 2) + row('PB', 'pb', 2);
      vtip.style.display = 'block';
      const wb = wrap.getBoundingClientRect(), sx = bx.left - wb.left + x(i) * bx.width / W;
      vtip.style.left = Math.min(Math.max(4, sx + 12), wb.width - vtip.offsetWidth - 4) + 'px';
      vtip.style.top = (bx.top - wb.top + 10) + 'px';
    };
    svg.onmouseleave = () => { vtip.style.display = 'none'; const g = document.getElementById('vg'); if (g) g.setAttribute('visibility', 'hidden'); };
  }
  // 只在宽度变化时重画（高度由 Streamlit 自动测量）
  let lastW = 0;
  new ResizeObserver(() => { const w = Math.round(wrap.getBoundingClientRect().width); if (w !== lastW) { lastW = w; drawDetail(); } }).observe(wrap);
  render();
})();
</script>"""
    return (template.replace("__BASE_CSS__", _COMP_BASE_CSS).replace("__VAL_CSS__", _VAL_CSS)
            .replace("__VAL_DATA__", data))


_CAT = {"hs300": "宽基·A股", "us_sp500": "宽基·美股", "credit": "信用债",
        "bond_10y": "利率债", "bond_30y": "超长久期", "gold": "商品·黄金",
        "nonferr": "商品·有色", "wti": "商品·原油"}

# 搜索框置顶的 8 类回测资产
_BT_FIXED = [{"code": f"bt:{a}", "label": f"{ETF_META.get(a, {}).get('code', '')} {ETF_META.get(a, {}).get('name', a)}",
              "tag": "回测资产"} for a in _ACCT_ASSETS]

with tab7:
    # 视图切换：单只走势 / 多只对比（原「基金对比」页合并到这里，少一个标签页）
    _MODE_S, _MODE_C = "单只走势", "多只对比"
    with st.container(key="trend_mode_switch"):
        _mode = st.segmented_control(
            "视图", [_MODE_S, _MODE_C], default=_MODE_S, key="trend_mode",
            label_visibility="collapsed",
            help="单只走势：区间涨跌、阶段表现、收益日历（日/周/月/年）。\n\n"
                 "多只对比：多只基金同一张图（净值 / 相对起点 / 单期涨跌），可拖动缩放、切日/月/年线。",
        ) or _MODE_S
    if _mode == _MODE_S:
        st.caption("单只基金的走势：区间涨跌、阶段表现、收益日历（日/周/月/年）。"
                   "上面的下拉既能选项目那 8 个回测资产，也能搜全市场基金。")
        # 统一入口：8 类回测资产（排最前，默认沪深300ETF）+ 全市场 2.8 万只基金，同一个输入即提示的选择框
        with st.container(key="trend_head"):
            _h1, _h2 = st.columns([3.5, 1.15], vertical_alignment="center")
            with _h2:
                # 自研搜索框：全市场名录只在第一次点开时下载（静态文件），不随页面加载传输（见 fund_search.py）
                _pick = _sticky_search("trend_pick", mode="single", fixed=_BT_FIXED, default="bt:hs300",
                                       placeholder="输入基金名称或代码")
                asset = _pick[3:] if str(_pick).startswith("bt:") else None
                if asset:
                    # 单位净值（基金公司每晚公布，与支付宝「单位净值/日涨幅」一致） / 场内价格（交易所实时成交价）
                    # 口径也跨视图记住：切到「多只对比」再切回来时，widget state 会被丢掉
                    _pm_memo = "_sel_trend_price_mode"
                    _price_mode = st.radio("口径", ["单位净值", "场内价格"], horizontal=True,
                                           index=1 if st.session_state.get(_pm_memo) == "场内价格" else 0,
                                           key="trend_price_mode", label_visibility="collapsed",
                                           help="单位净值：基金公司每晚按持仓算出的每份价值，日涨幅与支付宝一致（分红日已复权）。\n\n"
                                                "场内价格：ETF 在交易所买卖的成交价（收盘价），会围绕净值小幅溢价/折价。\n\n"
                                                "累计净值 = 单位净值 + 历年分红，只用于看成立以来的总分红，不适合算涨跌幅。")
                else:
                    _price_mode = "净值"
                    st.caption("单位净值 + 官方日涨幅（分红日复权）")
                if _price_mode != "净值":           # 记住口径选择，切视图回来还是上一次那个
                    st.session_state["_sel_trend_price_mode"] = _price_mode

            _ready, _own = True, None
            if asset:
                _own = (_asset_series(asset, price=True) if _price_mode == "场内价格"
                        else _asset_display_series(asset))
                _all = _trend_aggregate(_own if _own is not None else prices[asset], "日")
                _meta = ETF_META.get(asset, {"name": asset, "code": ""})
                _tag = _CAT.get(asset, "其他")
                _price_label = "最新场内价格" if _price_mode == "场内价格" else "最新单位净值"
                _src_note = (f"data/price_{_LIVE_ASSETS.get(asset, asset)}.csv（交易所收盘价）" if _price_mode == "场内价格"
                             else f"data/nav_detail/{_LIVE_ASSETS.get(asset, asset)}.csv（单位净值 + 官方日涨幅，分红日复权；"
                                  f"最新值 = 单位净值，与支付宝一致）")
            else:
                _code = _pick if str(_pick).isdigit() and len(str(_pick)) == 6 else None
                if _code and FL.is_stale(_code):
                    with st.spinner(f"正在拉取 {_code} 最新净值…"):
                        _fok, _fmsg = FL.fetch_fund(_code)
                    if not _fok:
                        if FL.load_cached(_code) is None:
                            st.error(_fmsg)
                            _code = None
                        else:   # 拉取失败但有旧缓存：继续显示旧数据，提示一下
                            st.caption(f"⚠️ 最新净值拉取失败，显示本地缓存（{_fmsg}）")
                _own = FL.build_nav(_code) if _code else None
                _ready = _own is not None and len(_own) >= 2
                _all = _trend_aggregate(_own, "日") if _ready else pd.Series(dtype=float)
                _pm = FL._purchase_map().get(_code, {}) if _code else {}
                _meta = {"name": _pm.get("name") or (FL.fund_name(_code) if _code else "") or (_code or ""),
                         "code": _code or ""}
                _tag = _pm.get("type") or "场外基金"
                _price_label = "最新净值"
                _src_note = f"rebal/nav/{_code}.csv（复权净值：最新值=单位净值，历史按日增长率含分红还原）"

            if _ready and len(_all):
                _day_chg = float(_all.iloc[-1] / _all.iloc[-2] - 1) if len(_all) > 1 and _all.iloc[-2] > 0 else None
                _day_cls = "up" if _day_chg is not None and _day_chg > 0 else ("down" if _day_chg is not None and _day_chg < 0 else "neutral")
                _day_text = f"{_day_chg * 100:+.2f}%" if _day_chg is not None else "—"
                _latest_text = f"{_all.iloc[-1]:.4f}"
                _latest_date = f"{_all.index[-1]:%Y/%m/%d}"
            else:
                _day_cls, _day_text, _latest_text, _latest_date = "neutral", "—", "—", "暂无有效行情"
            with _h1:
                # 最新值、单日涨跌、数据截至三者严格同源：都是该期最后一个交易日
                st.markdown(
                    f"""<div class="fund-head flat">
                      <div class="fh-top">
                        <span class="fh-name">{html_escape(_meta['name'])}</span>
                        <span class="fh-code">{_meta['code']}</span>
                        <span class="fh-tag">{html_escape(_tag)}</span>
                        {_val_tag_html(asset, _meta.get('code'), _meta.get('name', ''))}
                      </div>
                      <div class="fh-price">
                        <span class="fh-price-label">{_price_label}</span>
                        <span class="px">{_latest_text}</span>
                        <span class="chg {_day_cls}"><small>单日</small> {_day_text}</span>
                        <span class="fh-date">截至 {_latest_date}</span>
                      </div>
                    </div>""".replace("\n", "").replace("  ", ""),   # 压成一行：空行+缩进会被 Markdown 当成代码块
                    unsafe_allow_html=True,
                )
            if _ready and len(_all):
                st.markdown(_stage_summary_html(_stage_rows(_all)), unsafe_allow_html=True)

        if not _ready or _all.empty:
            st.info("该基金暂无有效行情，请换一只或稍后重试。")
        else:
            if asset and _own is None:
                st.warning("单基金历史读取失败，当前使用已有组合行情，历史覆盖可能不完整。")
            _histories = _trend_chart_data(_all)
            _daily = _histories["日"]
            # 控件与SVG同处一个局部组件：视窗、高亮、日期和摘要同步，无跨iframe状态桥接。
            with st.container(key="trend_chart"):
                st.iframe(_scroll_chart_html(
                    _daily["labels"], _daily["prices"], _daily["windows"]["近1月"]["count"],
                    rets=_daily["rets"], histories=_histories,
                ), height=850)
                st.markdown(
                    f'<div class="sec-note">数据源：{_src_note} · '
                    f'截至 {_latest_date} · 月/年线取每期最后一条真实记录，未结束期间按最新数据计算。'
                    f'区间变化以首个可见值为基准（近N月=N个自然月前那天的净值，今年来=去年最后一个交易日），与支付宝历史业绩同口径。</div>',
                    unsafe_allow_html=True,
                )
            # 收益日历：日/周/月/年 格子，按钮与走势分析同款，期间切换在组件内完成（不触发整页重跑）
            _cal = _calendar_payload(_all)
            if _cal:
                with st.container(key="trend_cal"):
                    st.iframe(_calendar_html(_cal), height="content")
    else:
        st.caption("多只基金同图对比：三块面板分别是净值、相对起点涨跌幅、单期涨跌幅，"
                   f"可拖动缩放、切日/月/年线；下方按基金列出各阶段涨跌幅。最多同时 {len(_CMP_COLORS)} 只。")
        # ---- 多只对比：与单只共用同一套 iframe 组件（净值 / 相对起点 / 单期涨跌），只是叠加多条线 ----
        with st.container(key="trend_head"):
            # 头卡必须在搜索框之前、且只用「已选了哪几只」就渲染出来：
            # 之前用 st.empty() 占位、等净值全拉完才填，重跑时占位先是空的（矮 28px），
            # 页面整体上移、等回填再落下 —— 看起来就是「加一只基金页面跳一下」。
            # 实时值优先（同一轮里组件回报的最新选择），widget state 被丢掉时才用镜像兜底；
            # 不能用 `or`：用户把标签删光时 value=[] 也是「有效值」，不能退回旧的镜像
            _live_sel = (st.session_state.get("cmp_pick") or {}).get("value")
            _prev_sel = [c for c in (_live_sel if _live_sel is not None
                                     else (st.session_state.get("_sel_cmp_pick") or [])) if c]
            _prev_last = _cmp_cached_last(_prev_sel)     # 只读本地缓存，不联网
            _head_right = (f'数据截至 {_prev_last}' if _prev_last
                           else ('' if _prev_sel else f'最多同时对比 {len(_CMP_COLORS)} 只'))
            st.markdown(
                f'<div class="fund-head flat"><div class="fh-top">'
                f'<span class="fh-name">多只基金对比</span>'
                f'<span class="fh-tag">{"已选 %d 只" % len(_prev_sel) if _prev_sel else "未选择"}</span>'
                f'<span class="fh-date">{_head_right}</span>'
                f'</div></div>',
                unsafe_allow_html=True,
            )
            _sel = _sticky_search("cmp_pick", mode="multi", fixed=_BT_FIXED, default=[],
                                  placeholder="搜索并添加基金，可多选对比", max_sel=len(_CMP_COLORS))
            _bt_label = {f["code"]: f["label"] for f in _BT_FIXED}
            _series_map, _cmp_fail = {}, []
            for _o in (_sel or []):
                if str(_o).startswith("bt:"):
                    _a = _o[3:]
                    _ss = _asset_display_series(_a)
                    if _ss is None:
                        _ss = FL.backtest_index(_a)
                    _nm = _bt_label.get(_o, _a)
                else:
                    _c = _o if str(_o).isdigit() and len(str(_o)) == 6 else None
                    if not _c:
                        continue
                    if FL.is_stale(_c):
                        st.toast(f"正在拉取 {_c} 最新净值…")   # 用 toast 不用 spinner：spinner 会在页面里插一行，又跳一下
                        _fok, _fmsg = FL.fetch_fund(_c)
                        if not _fok and FL.load_cached(_c) is None:
                            _cmp_fail.append(_fmsg)
                            continue
                    _ss = FL.build_nav(_c)
                    _nm = f"{_c} {FL.fund_name(_c)}".strip()
                if _ss is not None and len(_ss) >= 2:
                    _series_map[_nm] = _ss
            if _cmp_fail:
                st.warning("以下基金没有画进图里：" + "；".join(_cmp_fail), icon=":material/info:")

        if not _series_map:
            st.info("在右上角的搜索框里添加基金：选 1 只也能看，选 2 只以上即同图对比。")
        else:
            with st.container(key="cmp_chart"):
                st.iframe(_compare_chart_html(_series_map), height="content")
                st.markdown(
                    '<div class="sec-note">净值为复权单位净值：最新值 = 最新单位净值，每日涨跌 = 官方日涨幅（分红日复权），与支付宝一致。'
                    '各基金以可见区间内首个有效值为 0% 基准，月/年线取每期最后一条真实记录。</div>',
                    unsafe_allow_html=True,
                )
            # 阶段涨跌幅：每只基金一行，口径与单只「阶段表现」完全一致（基准日净值 → 最新净值）
            with st.container(key="cmp_stage"):
                st.markdown('<div class="sec-head"><span class="t">阶段表现</span>'
                            '<span class="r">与单只走势同口径 · 基准日净值至最新净值 · 手机上左右滑动看全部</span></div>',
                            unsafe_allow_html=True)
                _rows = []
                for _nm, _ss in _series_map.items():
                    _cells = {}
                    for _cell in _stage_rows(_ss):
                        _v = _cell["ret"]
                        if _v is None or not np.isfinite(_v):
                            _cells[_cell["label"]] = '<span class="muted">—</span>'
                        else:
                            _cls = "up" if _v > 0 else ("down" if _v < 0 else "muted")
                            _cells[_cell["label"]] = f'<span class="{_cls}">{_v:+.2f}%</span>'
                    _rows.append([html_escape(_nm)] + [_cells[_l] for _l in _TREND_STAGES])
                _render_table([("基金", "left")] + [(f"{_l}", "right") for _l in _TREND_STAGES], _rows,
                              min_width=700)
# ============================================================
# Tab 8: 三策略比较 / 调频影响（统一月度、年度、多年视图）
# ============================================================
with tab8:
    st.caption("这里是**项目原始策略**的历史回测：三策略对比、调频影响，"
               "以及最下方「历史调仓」里每月的目标权重和当月收益。"
               "我自己持仓的收益在「实操账户」看。")
    from streamlit_app.performance import render_performance
    render_performance(PROJECT_ROOT)



# ============================================================
# Tab 9: 提醒（偏离 / 估值 / 体检）—— 全部按我持仓的基金算
# ============================================================
def _alert_card(level, title, body, tip=""):
    _cls = {"urgent": "warn", "warn": "warn", "info": "", "ok": "calm"}.get(level, "")
    _tip = f'<div class="m">{tip}</div>' if tip else ""
    return (f'<div class="sig {_cls}"><div class="main"><div class="t">{title}</div>'
            f'<div class="m">{body}</div>{_tip}</div></div>')


with tab9:
    st.subheader("提醒 · 按我持仓的基金算")
    st.caption("三类提醒分开看：偏离是「该不该调仓」，估值是「贵不贵」，体检是「账户本身怎么样」。")

    # 估值数据（蛋卷快照）按代码索引
    _val_by_code = {}
    try:
        from allweather import valuation as _VAL
        _snap = _VAL.load_snapshot()
        if not _snap.empty:
            for _r in _snap.to_dict("records"):
                _dd = _VAL.drawdown_10y(_r["代码"])
                _tot, _vs, _ps, _lb = _VAL.score(_r["PE百分位"], _r["PB百分位"], _dd)
                _val_by_code[str(_r["代码"])] = {
                    "name": _r["名称"], "pe_pct": _r["PE百分位"] if pd.notna(_r["PE百分位"]) else None,
                    "pb_pct": _r["PB百分位"] if pd.notna(_r["PB百分位"]) else None,
                    "score": _tot, "label": _lb,
                    "asof": f'{pd.Timestamp(_snap["数据日"].max()):%Y/%m/%d}',
                }
    except Exception:  # noqa: BLE001
        _val_by_code = {}

    _bench_for_alert = {}
    if acct is not None and len(_acct_daily) > 1:
        _bd = BM.replay_target(w, acct.get("created"), nav_getter=HG.nav_series)
        if len(_bd) > 1:
            _bench_for_alert["项目默认基金"] = _bd
        _bs = BM.strategy_curve(_BENCH_COL.get(acct.get("strategy"), ""), start=acct.get("created"))
        if _bs is not None and len(_bs) > 1:
            _bench_for_alert["策略理论"] = _bs

    _al = AL.compute(
        mv=_hg_mv, target_w=_hg_w, holdings=holdings, slot_label=HG.SLOT_LABEL,
        val_by_code=_val_by_code, daily=_acct_daily if acct is not None else None,
        cash=float(_acct_cash or 0),         pos=_acct_pos if acct is not None else {},
        cost=_acct_cost if acct is not None else {}, bench=_bench_for_alert,
        slot_of_code=lambda c: HG.slot_of(c, holdings),
    )

    _A, _B = st.columns([1.15, 1], gap="large")
    with _A:
        st.markdown("**偏离提醒**")
        if not _al["偏离"]:
            st.markdown('<div class="sig calm"><div class="main">'
                        '<div class="t">所有位置都在目标附近</div>'
                        '<div class="m">偏离都小于 3 个百分点，月末再看即可</div></div></div>',
                        unsafe_allow_html=True)
        else:
            for x in _al["偏离"]:
                st.markdown(_alert_card(
                    x["level"], x["label"], x["text"],
                    "偏离 ≥12pp 建议尽快调；3~12pp 可以等月末一起调"), unsafe_allow_html=True)
        st.markdown("**账户体检**")
        if not _al["体检"]:
            st.caption("录入成交后这里会给出收益、回撤、现金占比等提醒。")
        for x in _al["体检"]:
            st.markdown(_alert_card(x["level"], x["text"], x.get("tip", "")), unsafe_allow_html=True)
    with _B:
        st.markdown("**估值提醒**")
        if not _al["估值"]:
            st.caption("持仓的基金暂时没有对应的指数估值数据（蛋卷快照按指数代码收录，"
                       "单只场外基金可能匹配不上）。")
        else:
            for x in _al["估值"]:
                st.markdown(_alert_card(
                    x["level"], f'{x["name"]}（{x["code"]}）',
                    f'评分 {x["score"]} · {x["label"]}：{x["action"]}'
                    + (f' · PE/PB 百分位较高者 {x["pct"]:.0f}%' if x.get("pct") is not None else ""),
                    "估值只作加减仓参考，不进策略信号；评分 ≥18 猎杀区、≤6 泡沫区"),
                    unsafe_allow_html=True)
        _m = _al["指标"]
        if _m:
            st.divider()
            st.markdown("**关键指标**")
            _kv = []
            for k, v in _m.items():
                if isinstance(v, dict):
                    continue
                if k == "现金占比":
                    _kv.append([k, f"{v*100:.1f}%"])
                elif k in ("累计收益", "最大回撤"):
                    _kv.append([k, f'<span class="{"up" if v >= 0 else "down"}">{v*100:+.2f}%</span>'])
                elif k.startswith("对比"):
                    _kv.append([k, f'<span class="{"up" if v >= 0 else "down"}">{v*100:+.2f}pp</span>'])
                else:
                    _kv.append([k, str(v)])
            if _kv:
                _render_table([("指标", "left"), ("数值", "right")], _kv)


# ============================================================
# Tab 10: 指数估值 —— 蛋卷估值快照 + 近10年 PE/PB 走势（仅展示，不进入策略计算）
# ============================================================
with tab10:
    _vp = _valuation_payload()
    if not _vp:
        with st.container(key="val_head"):
            st.markdown('<div class="sec-head"><span class="t">指数估值</span></div>', unsafe_allow_html=True)
            st.info("本地还没有估值数据，点右上角「更新数据」拉取（约 10 秒）。")
    else:
        with st.container(key="val_table"):
            st.iframe(_valuation_html(_vp), height="content")
            # 口径说明：策略信号用的沪深300估值与本页口径不同，明确列出避免误读
            try:
                from allweather.data import load_hs300_pb, load_hs300_pe
                _spb, _spe = load_hs300_pb(), load_hs300_pe()
                _pbp = (_spb < _spb.iloc[-1]).mean() * 100
                _pep = (_spe < _spe.iloc[-1]).mean() * 100
                _sig = (f"策略信号另用一套沪深300口径（乐咕乐股 PB 中位数 / 等权 PE，2005 年起）："
                        f"截至 {_spb.index[-1]:%Y/%m/%d} PB 百分位 {_pbp:.1f}%（抄底需 &lt; {HS300_PB_ENTRY}%），"
                        f"PE 百分位 {_pep:.1f}%（退出线 {HS300_PE_EXIT}%）。")
            except Exception:
                _sig = ""
            st.markdown(
                '<div class="sec-note">数据源：蛋卷基金指数估值（加权口径，百分位为近10年），随右上角「更新数据」刷新；'
                '仅作参考展示，不参与策略计算。' + (f'<br>{_sig}' if _sig else '') + '</div>',
                unsafe_allow_html=True,
            )
