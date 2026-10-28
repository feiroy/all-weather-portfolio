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
from allweather.sim_account import (load_acct, save_acct, stats as acct_stats,
                                  fund_pnl as _fund_pnl, rounds as _acct_rounds,
                                  MONEY_SIDES as _MONEY_SIDES)
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
/* 位置卡片里的基金清单：一行一只，代码 / 名称 / 占比三栏，占比右对齐 */
.flist{ display:flex; flex-direction:column; gap:3px; margin:2px 0 8px; }
.flist .frow{ display:grid; grid-template-columns:56px minmax(0,1fr) 42px; gap:8px;
  align-items:baseline; font-size:12px; color:var(--sub); line-height:1.6; }
.flist .fc{ font-variant-numeric:tabular-nums; color:var(--ink); }
.flist .fn{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.flist .fp{ text-align:right; font-variant-numeric:tabular-nums; color:var(--ink); font-weight:600; }
.flist .none{ font-size:12px; color:var(--sub); }

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

/* ========== 我的持仓：支付宝式头卡 + 列表 + 点开的详情面板 ========== */
/* 头卡只有一个：总资产大字 + 今日/持有/收益率，蓝底白字（与侧栏 brand 同一渐变） */
.pf-head{
  background:linear-gradient(135deg,#1E3A8A 0%,#1E40AF 55%,#3B82F6 100%);
  border-radius:18px; padding:20px 22px 16px; color:#fff; box-shadow:var(--shadow2);
  margin:4px 0 14px;
}
.pf-head .pf-k{ font-size:12px; opacity:.82; letter-spacing:.4px; }
.pf-head .pf-amt{
  font-size:38px; font-weight:700; letter-spacing:-1.4px; line-height:1.12;
  margin:5px 0 3px; font-variant-numeric:tabular-nums;
}
.pf-head .pf-sub{ font-size:12px; opacity:.8; }
.pf-head .pf-grid{
  display:grid; grid-template-columns:repeat(4,1fr); gap:14px;
  margin-top:16px; padding-top:14px; border-top:1px solid rgba(255,255,255,.22);
}
.pf-head .pf-grid .k{ font-size:11.5px; opacity:.82; }
.pf-head .pf-grid .v{
  font-size:16px; font-weight:650; margin-top:3px; font-variant-numeric:tabular-nums;
}
.pf-head .pf-grid .v.up{ color:#FCA5A5; }    /* 蓝底上用浅红/浅绿，保持红涨绿跌语义 */
.pf-head .pf-grid .v.down{ color:#86EFAC; }

/* 点开一只基金：详情面板（列表点中哪一只，就在下面展开哪一只） */
.pf-detail{
  background:var(--card); border:1px solid var(--line); border-left:4px solid var(--brand);
  border-radius:14px; padding:15px 18px 13px; box-shadow:var(--shadow); margin:14px 0 10px;
}
.pf-detail .pd-top{ display:flex; align-items:flex-start; gap:10px; }
.pf-detail .pd-name{ font-size:16px; font-weight:650; letter-spacing:-.3px; line-height:1.3; }
.pf-detail .pd-sub{ font-size:11.5px; color:var(--sub); font-variant-numeric:tabular-nums; margin-top:3px; }
.pf-detail .pd-grid{
  display:grid; grid-template-columns:repeat(6,1fr); gap:10px; margin-top:14px;
  padding-top:12px; border-top:1px solid var(--line-soft);
}
.pf-detail .pd-grid .k{ font-size:11px; color:var(--sub); }
.pf-detail .pd-grid .v{ font-size:14px; font-weight:650; margin-top:2px; font-variant-numeric:tabular-nums; }
.pf-detail .pd-grid .v.up{ color:var(--red); }
.pf-detail .pd-grid .v.down{ color:var(--green); }
.pf-detail.is-closed{ border-left-color:var(--line-strong); }   /* 已清仓：灰边，和「在手上」的蓝边区分 */
/* 就地展开：详情插在被点的那一行下面，和上下两段列表拼成一张卡（各自只留需要的圆角/边框） */
.pf-detail.inline{
  margin:0; border:0; border-radius:0; box-shadow:none; padding:0 0 2px;
}
/* 就地展开时上面那一行已经写着基金名/代码/这一轮标记，详情里不再重复一遍 */
.pf-detail.inline .pd-top{ display:none; }
/* 6 个数字收成一条浅色数据带：比直接摊在白底上整齐，也不会看着像散落的几串数字 */
.pf-detail.inline .pd-grid{
  margin:0; padding:10px 12px; gap:4px 10px;
  background:var(--bg); border:1px solid var(--line-soft); border-radius:10px;
}
.pf-detail.inline .pd-grid .v{ font-size:13.5px; margin-top:1px; }
/* Streamlit 给 markdown 内层挂了 -15px 底边（为了吃掉末段 <p> 的间距），
   我们这里末行是 <div>，于是真实高度被吃掉 15px —— 数据带会压到下面那条工具行上 */
.st-key-pf_inline .stMarkdown div{ margin-bottom:0 !important; }
.st-key-pf_stack{ gap:0 !important; }        /* 三段之间不要空隙，否则断成三张卡 */
.st-key-pf_inline{
  background:var(--card); border-left:1px solid var(--line); border-right:1px solid var(--line);
  padding:10px 14px 12px; gap:.5rem !important;
  box-shadow:inset 3px 0 0 #3B82F6;           /* 和上面那一行「选中」的竖条同宽同色，连成一条 */
}
/* 记一笔：标题与类型选项卡同一行，类型不再单独占一行、右边空一大片 */
.st-key-tr_mode_switch{ align-items:center !important }
.st-key-tr_mode_switch .sec-head{ margin:0 }
.st-key-tr_mode_switch .sec-head .t{ white-space:nowrap }
/* 标题那块的盒子比按钮矮 7px，靠 flex 居中会让字比按钮低半行 —— 给它和按钮一样的高度 */
.st-key-tr_mode_switch .stMarkdown{
  height:34px; display:flex; align-items:center;
}
.st-key-tr_mode_switch .stMarkdown div{ margin-bottom:0 !important }
/* 台账头：摘要条铺满整行、紧贴表格，左右两端跟表格对齐 ——
   它原来是跟筛选下拉挤一行的右半格，左边比表格缩进 270px、右边却齐平，看着「前后没对上」 */
.pf-summary.ledger{
  height:40px; padding:0 14px 0 12px; margin:6px 0 0; gap:10px 16px;
  flex-wrap:nowrap; overflow:hidden; box-shadow:none; border-left-width:3px;
}
.pf-summary.ledger .lead{ font-size:13px; white-space:nowrap }
.pf-summary.ledger .item{ font-size:12.5px; white-space:nowrap }
/* 台账筛选那行的右半边：说明文字贴底对齐下拉框，右端跟表格内容右边缘（14px 内边距）对齐 */
.tr-ledger-hint{ display:flex; justify-content:flex-end; align-items:center; height:40px;
  padding-right:14px; font-size:12px; color:var(--muted); white-space:nowrap }
@media(max-width:900px){
  .tr-ledger-hint{ display:none }                      /* 手机上列会叠成一列，这句跟着落到下拉下面很碍事 */
  /* 摘要条别裁：窄屏放不下一行就换行，宁可两行也别把「涉及 N 只基金」切掉 */
  .pf-summary.ledger{ height:auto; min-height:40px; padding:9px 12px; flex-wrap:wrap; row-gap:4px }
}
/* 子页签那一条：左侧留白和上面的数据带对齐 */
.st-key-pf_sub{ margin-top:2px; }
/* 只有两三天记录时，累计盈亏先给数字，不画那条一条直线的图 */
@media(max-width:900px){ .pf-detail .pd-grid{ grid-template-columns:repeat(3,1fr); row-gap:14px; } }
/* 买卖标记：红买绿卖，和支付宝走势图里的「买入 / 卖出」气泡同色 */
.pf-badge{
  margin-left:auto; border-radius:999px; padding:4px 11px; font-size:11.5px;
  font-weight:650; white-space:nowrap; border:1px solid transparent;
}
.pf-badge.buy{ background:#FEF2F2; color:var(--red); border-color:#FECACA; }
.pf-badge.sell{ background:#F0FDF4; color:var(--green); border-color:#BBF7D0; }
.pf-badge.hold{ background:var(--bg); color:var(--muted); border-color:var(--line); font-weight:500; }
.pf-badge.warn{ background:#FFFBEB; color:var(--amber); border-color:#FDE68A; font-weight:500; }

/* 调仓页顶部的结论条：这一轮该不该动、买多少卖多少，一行说完 */
.pf-summary{
  display:flex; align-items:center; gap:12px 22px; flex-wrap:wrap;
  background:var(--card); border:1px solid var(--line); border-left:4px solid var(--brand);
  border-radius:12px; padding:14px 18px; margin:6px 0 14px; box-shadow:var(--shadow);
}
.pf-summary .lead{ font-size:14px; font-weight:650; color:var(--ink); }
.pf-summary .item{ font-size:13px; color:var(--sub); font-variant-numeric:tabular-nums; }
.pf-summary .item b{ font-size:15px; margin-left:4px; }
.pf-summary .item b.buy{ color:var(--red); }
.pf-summary .item b.sell{ color:var(--green); }
.pf-summary b.up{ color:var(--red); }
.pf-summary b.down{ color:var(--green); }
.pf-summary .lead b{ font-size:16px; font-variant-numeric:tabular-nums; }
.pf-summary.quiet{ border-left-color:var(--line-strong); }

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

/* ========== 基金检索页：含阶段数字的概览 / 走势分析 ========== */
/* 基金检索 / 收益日历 / 基金对比 共用同一卡片容器 */
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
/* 视图切换（单只走势 / 多只对比）、建仓·调仓模式切换、记账类型切换：共用同一套 tab 按钮组样式 */
.st-key-trend_mode_switch,.st-key-rb_mode_switch,.st-key-tr_mode_switch{margin:0 0 6px}
.st-key-trend_mode_switch [role="radiogroup"],.st-key-rb_mode_switch [role="radiogroup"],.st-key-tr_mode_switch [role="radiogroup"]{gap:2px;padding:3px;background:var(--bg);
  border:1px solid var(--line-strong);border-radius:12px;width:fit-content}
.st-key-trend_mode_switch button,.st-key-rb_mode_switch button,.st-key-tr_mode_switch button{border:0 !important;border-radius:9px !important;
  min-height:34px;height:34px;padding:0 14px;background:transparent;color:var(--sub)}
.st-key-trend_mode_switch button p,.st-key-rb_mode_switch button p,.st-key-tr_mode_switch button p{font-size:13px !important;line-height:1.4;color:inherit}
.st-key-trend_mode_switch button:hover,.st-key-rb_mode_switch button:hover,.st-key-tr_mode_switch button:hover{color:var(--ink)}
.st-key-trend_mode_switch button[aria-checked="true"],.st-key-rb_mode_switch button[aria-checked="true"],.st-key-tr_mode_switch button[aria-checked="true"]{background:var(--card) !important;
  box-shadow:0 1px 2px rgba(15,23,42,.08)}
.st-key-trend_mode_switch button[aria-checked="true"] p,.st-key-rb_mode_switch button[aria-checked="true"] p,.st-key-tr_mode_switch button[aria-checked="true"] p{color:var(--brand) !important;font-weight:600}
/* 交易记录页：记一笔那块画成卡片（已不用 st.form，控件改动即刷新下面的提示） */
.st-key-tr_card{background:var(--card); border:1px solid var(--line); border-radius:16px;
  padding:20px !important; margin-bottom:18px}
.st-key-tr_card [data-testid="stHorizontalBlock"]{gap:14px; align-items:flex-end}
.st-key-tr_card [data-testid="stButton"] button{height:38px; min-height:38px}
.fund-head.flat{border:none; box-shadow:none; padding:0; margin:0; background:transparent}
.fh-top,.fh-price{flex-wrap:wrap; row-gap:8px}
.fh-price .fh-date{margin-left:0}
.sec-head{display:flex; align-items:center; flex-wrap:wrap; gap:12px; margin:0 0 16px}
.sec-head .t{font-size:17px; font-weight:600; color:var(--ink)}
.sec-head .r{margin-left:auto; font-size:12px; color:var(--sub); min-width:0; text-align:right}
/* 手机上标题与右侧统计放一行会互相挤掉，右侧整行下移 */
@media(max-width:760px){
  .sec-head .r{margin-left:0; width:100%; text-align:left; line-height:1.7}
}
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
@media(max-width:520px){#range-controls{gap:0;width:100%;flex-wrap:wrap}
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


def _compare_chart_html(series_map, height=560, default_range="近1年", title="走势对比",
                        pct_mode=False):
    """多序列对比图。

    ``pct_mode=True`` 时把序列当「归一净值」（1.0 = 起点）但**全程按收益率说话**：
    面板标题、刻度和提示框都换算成 %，上面那块写「累计收益率」而不是「净值」——
    几条线归一之后本来比的就是涨跌幅，写成净值只会让人以为在比 1.02 和 0.98 这种数。
    """
    names, hist = _compare_payload(series_map)
    payload = json.dumps({"names": names, "colors": _CMP_COLORS, "histories": hist,
                          "height": int(height), "defaultRange": default_range,
                          "pct": bool(pct_mode)},
                         ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    btns = _range_buttons(default_range)
    template = r"""<style>
__BASE_CSS__
__CMP_CSS__
</style>
<div id="wrap" aria-busy="false">
<div class="heading"><h3><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4v16h16M7 14l4-5 4 3 5-7"/></svg>__TITLE__</h3><span id="updating" role="status">正在更新</span></div>
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
  // 收益率口径：序列本身是「1.0 = 起点」的归一净值，(v-1)·100 才是那个 %
  const PC = !!D.pct;
  const shown1 = v => !valid(v) ? '—' : (PC ? pct((v - 1) * 100) : v.toFixed(4));
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
    ticks += `<text x="${L}" y="18" font-size="12" fill="#475569">${PC ? '累计收益率（建仓日 = 0）' : '净值'}</text>`;
    for (let k = 0; k <= 4; k++) {
      const v = lo + (hi - lo) * k / 4, yy = yN(v);
      grid += `<line x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}" stroke="#EEF2F7"/>`;
      ticks += `<text x="${L-8}" y="${yy+4}" text-anchor="end" font-size="10" fill="#475569">${PC ? pct((v - 1) * 100) : v.toFixed(hi - lo < .5 ? 4 : 3)}</text>`;
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
      return `<tr>${head}<td>${PC ? shown1(v0) + ' → ' + shown1(v1) : v0.toFixed(4) + ' → ' + v1.toFixed(4)}</td><td><b style="color:${color(chg)}">${pct(chg)}</b></td><td style="color:${color(ann)}">${pct(ann)}</td>`
        + `<td style="color:${color(mdd)}">${mdd < 0 ? pct(mdd) : '0.00%'}</td><td>${valid(vol) ? vol.toFixed(2) + '%' : '—'}</td>`
        + `<td>${esc(P.dates[b])} — ${esc(P.dates[e])}</td></tr>`;
    }).join('');
    document.getElementById('stats').innerHTML =
      `<div class="summary-main"><div class="summary-result"><span>当前区间指标</span></div>`
      + `<span class="hint">拖动/滚轮平移 · Ctrl+滚轮缩放 · 双击复位 · 点图例隐藏/显示</span></div>`
      + `<div class="tbl-wrap"><table class="cmp-tbl"><thead><tr><th>基金</th><th>${PC ? '累计收益 起 → 止' : '净值 起 → 止'}</th><th>区间涨跌</th><th>年化</th><th>最大回撤</th><th>波动(年化)</th><th>起止</th></tr></thead><tbody>${rows}</tbody></table></div>`
      + `<div class="amp-row"><small>${PC
          ? '三条线都以账户建仓日为 0%，比的是收益率、不是净值绝对值；区间内首个有效值再归 0% 看强弱。'
          : '净值为复权净值（最新值 = 最新单位净值，历史按日增长率含分红还原）'}；区间不足 3 个月不计年化；波动按${period}收益年化。</small></div>`;
    if (pinned !== null) showTip(pinned); else tip.style.display = 'none';
    fit();
  }
  function showTip(i, clientY = null) {
    const [first, last] = bounds(), guide = document.getElementById('guide');
    if (!Number.isInteger(i) || i < first || i > last) { tip.style.display = 'none'; if (guide) guide.setAttribute('visibility', 'hidden'); return; }
    if (guide) { guide.setAttribute('x1', x(i)); guide.setAttribute('x2', x(i)); guide.setAttribute('visibility', 'visible'); }
    tip.innerHTML = `<b>${esc(P.dates[i])}</b><div class="tip-row tip-head"><span>基金</span><span>${PC ? '累计' : '净值'}</span><span>相对起点</span><span>单${period}</span></div>`
      + shown().map(nm => { const r = rel(nm, i), st = P.steps[nm][i], v = P.vals[nm][i];
          return `<div class="tip-row"><span class="tip-label"><i style="background:${col(nm)}"></i>${esc(nm)}</span><b>${shown1(v)}</b><b style="color:${color(r)}">${pct(r)}</b><b style="color:${color(st)}">${pct(st)}</b></div>`; }).join('')
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
            .replace("__BTNS__", btns).replace("__CMP_DATA__", payload).replace("__TITLE__", title))


def _chart_head_block(heading: str, icon_path: str) -> str:
    """图表卡片顶部那一行标题。heading 为空就整行隐藏，只留一个 #updating 给加载提示用。

    详情卡里已经有「买卖点 / 累计盈亏」子页签，图里再写一遍标题就是重复，也把版面撑得很高。
    """
    if not heading:
        return '<div class="heading" hidden><span id="updating" role="status">正在更新</span></div>'
    return ('<div class="heading"><h3><svg class="icon" viewBox="0 0 24 24" aria-hidden="true">'
            f'<path d="{icon_path}"/></svg>{html_escape(heading)}</h3>'
            '<span id="updating" role="status">正在更新</span></div>')


def _scroll_chart_html(labels, values, win, height=540, rets=None, revision=0, histories=None,
                       trades=None, store=None, default_range="近1月", heading="走势分析"):
    """全历史数据 + 有界索引视窗；只绘制可见部分，不创建超宽画布。

    一张图三层面板，共用同一条时间轴：上方净值折线（含起点虚线），
    中间每个点位相对区间起点的涨跌幅柱，下方单期涨跌幅柱（涨红跌绿）。

    trades：历史成交点 [{date:"2026/10/27", side:"买入", label:"1,234.00 份 @ 2.4567"}]，
    按日期落到当前粒度的那一期上，买画红上三角、卖画绿下三角，悬停/点开进提示框。
    持仓页「点开一只基金」用它标出这只基金自己的买卖时间点（基金检索页不传，行为不变）。
    store/default_range/heading：同一个组件的三种文案，持仓页要独立的区间记忆与标题。
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
  // 当前视窗内的成交点：期号 → [成交...]，每次 draw 重算，悬停提示与三角标记共用
  let tradeAt = new Map(), nBuy = 0, nSell = 0;
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
    // 区间最高/最低只用来算「振幅」那个数字，不再往图上钉白底标注框：
    // 占地方、还容易压住买卖三角，看图的人真正要认的是买卖点。
    let hiI = null, loI = null;
    for (let i = first; i <= last; i++) {
      if (!valid(P.prices[i])) continue;
      if (hiI === null || P.prices[i] > P.prices[hiI]) hiI = i;
      if (loI === null || P.prices[i] < P.prices[loI]) loI = i;
    }
    // 历史成交点：按日期落到当前粒度的那一期（日线=当天，月/年线=该期最后一条记录）。
    // 买入画在净值点下方的红三角、卖出画在上方的绿三角；同一期多笔只画一个，逐笔细节进提示框。
    tradeAt = new Map(); nBuy = 0; nSell = 0;
    let tmarks = '';
    for (const t of (D.trades || [])) {
      let ti = -1;
      for (let k = n - 1; k >= 0; k--) { if (P.dates[k] <= t.date) { ti = k; break; } }
      if (ti < 0 || ti < first || ti > last || !valid(P.prices[ti])) continue;
      const e = tradeAt.get(ti) || {list: []}; e.list.push(t); tradeAt.set(ti, e);
    }
    for (const [ti, e] of tradeAt) {
      // 首末那两期的点在裁剪框边缘，三角会有一半被裁掉 → 水平往内收 8px
      const cx = clamp(x(ti), L + 8, W - R - 8), cy = y(P.prices[ti]);
      const nb = e.list.filter(t => t.side === '买入').length;
      nBuy += nb; nSell += e.list.length - nb;
      // 三角比原来大一圈（半宽 8.5 / 高 13）+ 2px 白描边，压在曲线上也认得出是买还是卖
      if (nb) tmarks += `<path d="M${cx-8.5},${cy+15} L${cx+8.5},${cy+15} L${cx},${cy+2} Z" fill="#C52828" stroke="#fff" stroke-width="2" stroke-linejoin="round" data-tri="buy"/>`;
      if (e.list.length - nb) tmarks += `<path d="M${cx-8.5},${cy-15} L${cx+8.5},${cy-15} L${cx},${cy-2} Z" fill="#16703B" stroke="#fff" stroke-width="2" stroke-linejoin="round" data-tri="sell"/>`;
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
         ? `<div class="amp-row" id="trade-row"><span>历史成交</span><b>▲ ${nBuy} 买 · ▼ ${nSell} 卖</b>`
           + `<small>三角标在净值曲线上（红买绿卖），悬停或点开看每笔的份额与净值</small></div>`
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
    tip.innerHTML = `<b>${esc(P.dates[i])}</b>`
      + `<div class="tip-row"><span class="tip-label">净值</span><b>${price(px)}</b></div>`
      + `<div class="tip-row"><span class="tip-label">单${period}涨跌幅</span><b style="color:${color(rt)}">${pct(rt)}</b></div>`
      + `<div class="tip-row"><span class="tip-label">相对起点</span><b style="color:${color(rel)}">${pct(rel)}</b></div>`
      + ((tradeAt.get(i) || {list: []}).list.map(t =>
          `<div class="tip-row"><span class="tip-label" style="color:${t.side === '买入' ? '#C52828' : '#16703B'}">${esc(t.side)}</span>`
          + `<b>${esc(t.label)}</b></div>`).join(''))
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
            .replace("__HEAD_CSS__", "" if heading else ".controls{margin-top:2px}")
            .replace("__HEAD_BLOCK__", _chart_head_block(heading, "M4 4v16h16M7 14l4-5 4 3 5-7"))
            .replace("__RANGE_BTNS__", _range_buttons(default_range))
            .replace("__CHART_DATA__", payload))


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
        "sell_slot": "nonferr", "buy_slot": "credit",
        "desc": f"{_nf} 跌破 SMA75",
        "condition": lambda s: s.get("nonferr_below_sma75", False),
        "sell": _nf,
        "buy": _cr,
        "strategies": ["B-Con", "B-RP", "V3c"],
        "type": "趋势过滤",
    },
    {
        "key": "gold_below_sma75",
        "sell_slot": "gold", "buy_slot": "credit",
        "desc": f"{_au} 跌破 SMA75",
        "condition": lambda s: s.get("gold_below_sma75", False),
        "sell": _au,
        "buy": _cr,
        "strategies": ["B-RP", "V3c"],
        "type": "趋势过滤",
    },
    {
        "key": "sp500_below_sma75",
        "sell_slot": "us_sp500", "buy_slot": "credit",
        "desc": f"{_sp} 跌破 SMA{SP500_TREND_WINDOW}",
        "condition": lambda s: s.get("sp500_below_sma75", False),
        "sell": _sp,
        "buy": _cr,
        "strategies": ["B-RP", "V3c"],
        "type": "趋势过滤",
    },
    {
        "key": "hs300_dip_ready",
        "sell_slot": "credit", "buy_slot": "hs300",
        "desc": f"HS300 回撤>{HS300_DIP_THRESHOLD:.0%} + PB<{HS300_PB_ENTRY}%ile + 价格>SMA{HS300_DIP_SMA}",
        "condition": lambda s: s.get("hs300_dip_ready", False),
        "sell": f"{_cr}（筹资）",
        "buy": f"{_hs} ×1.8",
        "strategies": ["B-Con", "B-RP", "V3c"],
        "type": "抄底加仓",
    },
    {
        "key": "hs300_dip_exit",
        "sell_slot": "hs300", "buy_slot": "credit",
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


@st.cache_data(ttl=600, show_spinner=False)
def _nav_series_cached(code: str) -> pd.Series:
    """兜底取净值（配置里已经没有、但账上还留着份额的旧代码）。"""
    return HG.nav_series(code)


def _nav_of_code(code: str) -> pd.Series:
    """按**基金代码**取净值序列。

    持仓换过基金时，账上可能还留着旧代码的份额（比如把沪深300 从 510300 换成 110020，
    之前买的 510300 还在）。这时候必须用旧代码自己的净值估值，不能拿新基金的净值去乘。

    面板 `_hg_panel` 的列就是基金代码（一个位置可以挂多只），命中就直接返回，
    没命中（配置里已删掉的旧代码）才走联网/缓存兜底。
    """
    if code in _hg_panel.columns:
        col = _hg_panel[code].dropna()
        if len(col):
            return col
    return _nav_series_cached(code)


def _hg_nav_on(slot, day, code=None):
    """某只代码在 day 当天的净值（day 非交易日时取前一个交易日）。"""
    col = _nav_of_code(code) if code else pd.Series(dtype=float)
    if not len(col):
        return None
    sub = col.loc[:pd.Timestamp(day)]
    return float(sub.iloc[-1]) if len(sub) else None


def _replay_holdings(trades, capital, created):
    """按份额记账重放成交，得到日度净值/持仓/成本/现金。

    与 allweather.sim_account.replay 的差别：
    - 持仓以**基金代码**为键（原来以策略资产 key 为键，换基金就记不进去）；
    - 买入/卖出按份额 × 单位净值成交（场外基金的口径）；
    - 净值 = (持仓市值 + 现金) / units，转入转出按当时净值折算份额，不虚增收益。
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
    _navmap: dict[str, pd.Series] = {}

    def _nav_at(code: str, day):
        """重放里被调用上万次，每个代码只取一次净值序列（别在循环里反复 dropna）。"""
        if code not in _navmap:
            _navmap[code] = _nav_of_code(code)
        col = _navmap[code]
        if not len(col):
            return None
        sub = col.loc[:pd.Timestamp(day)]
        return float(sub.iloc[-1]) if len(sub) else None

    for d in idx:
        for t in buckets.get(d, []):
            code = str(t.get("code", "") or "")
            sh = float(t.get("shares", 0) or 0)
            px = float(t.get("nav", 0) or 0)
            fee = float(t.get("fee", 0) or 0)
            side = t.get("side")
            if side == "买入" and code and sh > 0:
                if px <= 0:
                    px = _nav_at(code, d) or 0
                cash -= sh * px + fee
                prev = pos.get(code, 0.0)
                cost[code] = ((prev * cost.get(code, 0.0) + sh * px + fee) / (prev + sh)) if (prev + sh) > 0 else px
                pos[code] = prev + sh
            elif side == "卖出" and code and sh > 0:
                if px <= 0:
                    px = _nav_at(code, d) or 0
                cash += sh * px - fee
                pos[code] = pos.get(code, 0.0) - sh
                if pos[code] <= 1e-9:
                    pos.pop(code, None)
                    cost.pop(code, None)
            elif side in ("转入", "入金"):
                base = last_nav if last_nav > 0 else 1.0
                units += sh / base
                cash += sh
            elif side in ("转出", "出金"):
                base = last_nav if last_nav > 0 else 1.0
                units = max(1e-9, units - sh / base)
                cash -= sh
        mv = 0.0
        for code, sh in pos.items():
            v = _nav_at(code, d)
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
        if t.get("code") or t.get("side") in _MONEY_SIDES:
            continue
        key = t.get("asset") or t.get("slot")
        if not key:
            continue
        t["slot"] = key
        _first = (HG.codes(holdings.get(key, {})) or [None])[0]
        t["code"] = _first or ETF_META.get(key, {}).get("code", "")
        t["nav"] = float(t.get("price", 0) or 0)
        changed = bool(t["code"])
    if changed:
        save_acct(a, ACCT_FILE)
    return changed


if acct and _migrate_trades(acct):
    st.toast("已把旧的记账（按场内价/资产名）换成按基金代码与份额", icon=":material/autorenew:")
# 回测资产（项目默认那 8 个），基金检索/对比页的下拉用
_ACCT_ASSETS = [a for a in ["hs300", "us_sp500", "credit", "bond_10y",
                            "bond_30y", "gold", "nonferr", "wti"] if a in prices.columns]
_ASSET_LABEL = {a: f"{ETF_META.get(a, {}).get('name', a)} ({ETF_META.get(a, {}).get('code', '')})"
                for a in _ACCT_ASSETS}

# 账户重放结果（按份额记账）：我的持仓 / 帮你算 / 收益对比 / 持仓详情共用
_acct_daily, _acct_pos, _acct_cost, _acct_cash, _acct_units = (
    _replay_holdings(acct.get("trades", []), acct.get("capital", 0), acct.get("created"))
    if acct else (pd.DataFrame(), {}, {}, 0.0, 0.0)
)
# 代码 → 第一笔成交日（每次重跑重算，别用模块级缓存：录一笔新成交后缓存就过期了）
_acct_first_trade: dict[str, pd.Timestamp] = {}
for _t in ((acct or {}).get("trades") or []):
    if _t.get("side") not in ("买入", "卖出"):
        continue
    try:
        _td = pd.Timestamp(_t["date"])
    except Exception:  # noqa: BLE001 - 日期写坏就跳过
        continue
    _tc = str(_t.get("code") or "")
    if _tc and (_tc not in _acct_first_trade or _td < _acct_first_trade[_tc]):
        _acct_first_trade[_tc] = _td


def _held_day(code: str, shares: float, px: float, px_prev: float,
              prev_day=None) -> tuple[float, float | None]:
    """这只基金的「今日」涨跌（元, %）—— **建仓那天之前的变化不算这笔持仓的收益**。

    `px_prev` 只是净值序列的倒数第二个点，对刚建仓的基金来说那个点还落在建仓之前：
    000006 是 10/26 按 2.7612 买的，列表却把 10/22→10/26 那 0.0273 的下跌算成「今日 -51」，
    而同一个面板里的累计盈亏是 0.00 —— 一边亏 51 一边不动，看着就是算错了。
    建仓日不早于 prev_day 那天时，没有「上一交易日的持仓」可比，今日收益只能是 0。
    """
    shares, px, px_prev = float(shares or 0), float(px or 0), float(px_prev or 0)
    if shares <= 0 or px <= 0:
        return 0.0, None
    _f = _acct_first_trade.get(str(code))
    if _f is not None and prev_day is not None and _f > pd.Timestamp(prev_day):
        return 0.0, None
    return (px - px_prev) * shares, ((px / px_prev - 1) * 100 if px_prev > 0 else None)
_hg_w = HG.slot_weights(w, holdings)            # 目标权重（按我启用的位置归一）
_hg_last = _hg_panel.index[-1] if len(_hg_panel) else prices.index[-1]


def _hg_mv_by_slot():
    """位置 → 当前市值（按该位置下**每只**持仓基金的净值分别估值后相加）。"""
    out = {}
    for s in HG.active(holdings):
        v = 0.0
        for code in HG.codes(holdings[s]):
            sh = float(_acct_pos.get(code, 0) or 0)
            if sh <= 0 or code not in _hg_panel.columns:
                continue
            col = _hg_panel[code].dropna()
            if len(col):
                v += sh * float(col.iloc[-1])
        if v > 0:
            out[s] = v
    return out


_hg_mv = _hg_mv_by_slot()
_hg_configured_codes = set(HG.all_codes(holdings))
# 「不在启用位置里」的份额：配置里删掉的旧代码，以及**位置被关掉、但账上还留着**的基金。
# 只按 all_codes 判断会把第二种漏掉 —— 那样这笔钱既不在列表里、也不进总金额，账就对不上了。
_hg_active_slot_codes = {c for s in HG.active(holdings) for c in HG.codes(holdings[s])}
_hg_other_mv = {
    c: sh * float(_hg_nav_on(None, _hg_panel.index[-1], c) or 0) if len(_hg_panel) else 0.0
    for c, sh in _acct_pos.items()
    if sh > 0 and c not in _hg_active_slot_codes
}


def _hg_plan() -> dict:
    """按策略目标权重算「该买多少 / 该卖多少」—— 全站唯一一份调仓计划。

    「我的账户」的持仓表、「帮你算」的两份清单都读这一份，
    两处不再各算一遍，避免数字对不上。

    口径：**调仓基数 = 配置内持仓市值 + 现金**，不含「其他」（位置已关/已删、账上还有份额的代码）。
    那些钱我们不能替你卖，算进基数只会把目标金额撑大，最后给出「要买 29 万而现金只有 1 万」
    这种执行不了的清单（真实踩过）。总资产另用 total，含「其他」。
    位置整体偏离 < 0.5% 视为不用动（省手续费），要动的位置再按位置内占比拆到每只基金。
    """
    cash = float(_acct_cash or 0)
    asset = float(sum(_hg_mv.values())) + cash
    rows, orders, by_code = [], [], {}
    buy_total = sell_total = mv_total = today_pnl = 0.0
    for s in HG.active(holdings):
        funds = HG.funds(holdings[s])
        if not funds:
            continue
        tgt_w = float(_hg_w.get(s, 0) or 0)
        tgt = tgt_w * asset
        items = []
        for f, x in zip(funds, HG.share_of(holdings[s])):
            code = f["code"]
            col = _hg_panel[code].dropna() if code in _hg_panel.columns else pd.Series(dtype=float)
            px = float(col.iloc[-1]) if len(col) else 0.0
            px_prev = float(col.iloc[-2]) if len(col) > 1 else px
            sh = float(_acct_pos.get(code, 0) or 0)
            cst = float(_acct_cost.get(code, 0) or 0)
            items.append({"f": f, "x": float(x), "code": code, "px": px, "px_prev": px_prev,
                          "px_prev_day": (col.index[-2] if len(col) > 1 else None),
                          "shares": sh, "cost": cst, "mv": sh * px,
                          "pl": ((px / cst - 1) if (cst > 0 and px > 0) else None)})
        slot_mv = sum(it["mv"] for it in items)
        mv_total += slot_mv
        today_pnl += sum(_held_day(it["code"], it["shares"], it["px"], it["px_prev"],
                                   it.get("px_prev_day"))[0] for it in items)
        slot_w = (slot_mv / asset) if asset else 0.0
        moved = abs(tgt - slot_mv) >= max(1.0, asset * 0.005)
        for i, it in enumerate(items):
            f = it["f"]
            diff = (tgt * it["x"] - it["mv"]) if moved else 0.0
            side, qty, amt, note = "", 0.0, 0.0, ""
            if it["px"] <= 0:
                note = "缺净值"
            elif not moved or abs(diff) < 1.0:
                note = ""
            else:
                qty, amt = HG.order_quantity(f, abs(diff), it["px"])
                if qty <= 0:
                    note = "不足一手"
                elif diff > 0:
                    side, buy_total = "买入", buy_total + amt
                else:
                    side, sell_total = "卖出", sell_total + amt
            it.update({"slot": s, "side": side, "qty": qty, "amount": amt, "note": note,
                       "otc": HG.is_otc(f),
                       "w_now": (it["mv"] / asset) if asset else 0.0,
                       "w_tgt": tgt_w * it["x"],
                       # 位置级偏离只在该位置首行有意义，同位置其余行留 0 不显示
                       "dev": ((slot_w - tgt_w) if i == 0 else 0.0),
                       "slot_w": slot_w, "slot_tgt_w": tgt_w,
                       "slot_first": i == 0, "slot_n": len(items)})
            if side:
                orders.append({"date": _hg_last.strftime("%Y-%m-%d"), "slot": s, "code": it["code"],
                               "side": side, "shares": round(float(qty), 4),
                               "nav": round(it["px"], 4), "fee": 0.0})
                by_code[it["code"]] = {"side": side, "amount": amt, "qty": qty}
            rows.append(it)
    # 不在启用位置里、但账上还留着份额的代码：占着总资产却不在目标权重里
    other = [{"code": c, "mv": v, "in_cfg": c in _hg_configured_codes}
             for c, v in (_hg_other_mv or {}).items() if v > 0]
    # 「其他」的今日涨跌也要算进头卡的「今日收益」：它们不参与调仓，但钱还是我的，
    # 漏掉的话 28 万持仓一天的波动在页面上完全看不见。
    for _c, _sh in (_acct_pos or {}).items():
        if float(_sh or 0) <= 0 or _c in _hg_active_slot_codes:
            continue
        _nv = _nav_of_code(_c)
        if len(_nv) > 1:
            today_pnl += _held_day(_c, float(_sh), float(_nv.iloc[-1]), float(_nv.iloc[-2]),
                                   _nv.index[-2])[0]
    total = mv_total + sum(o["mv"] for o in other) + cash
    # 收益按「份额」算，不按「本金金额差」：units 起于初始资金（记作 1 元 1 份），转入/转出按当时
    # 净值折算份额，所以 equity/units 就是时间加权净值，收益 = 总资产 − 份额本金。
    # 不能写成 total − capital：那样每次「转入」都会被当成赚到的钱（真踩过：转入 1 万后
    # 持仓页持有收益从 +184 跳到 +10,184，而「收益对比」页累计收益仍 +0.04%，两页互相打架）。
    base = float(_acct_units or 0)
    return {"asset": asset, "cash": cash, "mv": mv_total,
            "mv_all": mv_total + sum(o["mv"] for o in other), "total": total,
            "other": other,
            "rows": rows, "orders": orders, "by_code": by_code,
            "buy": buy_total, "sell": sell_total, "today": today_pnl,
            "pnl": (total - base) if base > 0 else 0.0,
            "pnl_pct": ((total / base - 1) if base > 0 else 0.0),
            "has_acct": acct is not None}


_plan = _hg_plan()


def _acct_flows() -> pd.Series:
    """日频净入金（正=进钱，负=出钱）：转入/入金为正，转出/出金为负。

    成交日先顺延到交易日（周末、节假日的转账算到下一个净值日），与 `_replay_holdings` 同一口径 ——
    否则按年切段时这笔钱会落在「那天没有净值」的日子上，收益就被算歪了。
    """
    if acct is None or not len(_acct_daily):
        return pd.Series(dtype=float)
    idx = _acct_daily.index
    out = pd.Series(0.0, index=idx)
    for t in acct.get("trades", []):
        side = t.get("side")
        if side not in ("转入", "入金", "转出", "出金"):
            continue
        try:
            d = pd.Timestamp(t.get("date"))
        except Exception:
            continue
        i = min(int(idx.searchsorted(d)), len(idx) - 1)
        amt = float(t.get("shares", 0) or 0)
        out.iloc[i] += -amt if side in ("转出", "出金") else amt
    return out


def _period_perf(freq: str = "Y") -> list[dict]:
    """账户按年 / 按月切段：赚了多少钱、收益率、期内回撤（口径见 HG.period_performance）。"""
    if acct is None or len(_acct_daily) == 0:
        return []
    return HG.period_performance(_acct_daily, _acct_flows(), freq)


def _acct_pnl_series() -> pd.Series:
    """账户累计收益（元）= 总资产 − 累计净投入。

    净投入 = 初始资金 + 到那天为止的转入转出合计。转入那天钱变多但收益不变，
    所以这条线是「我到底赚了多少」，和总资产那条线在加钱那天会分开 —— 那正是它的用处。
    """
    if acct is None or not len(_acct_daily):
        return pd.Series(dtype=float)
    eq = _acct_daily["equity"].astype(float)
    fl = _acct_flows().reindex(eq.index).fillna(0.0)
    return eq - (float(acct.get("capital") or 0) + fl.cumsum())


def _acct_equity_series() -> pd.Series:
    """账户总资产（元）= 持仓市值 + 现金 —— 看「钱变多了多少」。"""
    if acct is None or not len(_acct_daily):
        return pd.Series(dtype=float)
    return _acct_daily["equity"].astype(float)


def _acct_calendar_payload():
    """账户收益日历：每格两个数 —— 这段时间的**收益率**和**赚的钱**。

    收益率走账户单位净值（转入按当时净值折份额，加钱不抬高收益率）；
    钱走「当天总资产变化 − 当天转入转出」，逐日加出周 / 月 / 年。
    两个数天然对不上（同样 1%，钱多的账户赚得多），所以要并排给。
    """
    if acct is None or not len(_acct_daily):
        return None
    d = _acct_daily.dropna(subset=["nav", "equity"]).sort_index()
    if len(d) < 2:
        return None
    fl = _acct_flows().reindex(d.index).fillna(0.0)
    day = d["equity"].astype(float).diff() - fl
    if len(day):
        day.iloc[0] = float("nan")          # 第一天没有「昨天」可比，不编一个 0 出来
    return _calendar_payload(d["nav"].astype(float), money=day)


_PC_CSS = r"""
#wrap{padding:0}
.plg{display:flex;gap:18px;align-items:center;font-size:12px;color:#475569;margin:0 0 6px}
.plg span{display:inline-flex;align-items:center;gap:6px}
.plg i{width:11px;height:11px;border-radius:2px;display:inline-block}
.plg i.b{background:#C52828;opacity:.85}
.plg i.l{height:0;border-top:2px solid #3B82F6;border-radius:0;width:16px}
#chart{display:block;width:100%}
#tip{width:172px}
"""


def _period_chart_html(rows: list[dict], height: int = 300) -> str:
    """每期收益柱（元，左轴）+ 收益率折线（%，右轴）——上面是「钱」，同一张图上叠「百分比」。

    单纯画净值曲线看不出「这个月到底赚了多少钱」；只画柱子又看不出「这份钱本身的涨跌」。
    两个都画，才能对上「加了钱 ≠ 赚了钱」这件事。
    """
    data = json.dumps(
        {"rows": [{"k": r["period"], "pnl": round(float(r["pnl"]), 2),
                   "ret": round(float(r["ret"]) * 100, 4),
                   "mdd": round(float(r["mdd"]) * 100, 4),
                   "flow": round(float(r["flow"]), 2)} for r in reversed(rows)],
         "height": int(height)}, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    tpl = r"""<style>
__BASE_CSS__
__PC_CSS__
</style>
<div id="wrap">
<div class="plg"><span><i class="b"></i>每期收益（元 · 左轴）</span><span><i class="l"></i>收益率（% · 右轴）</span></div>
<svg id="chart" role="img" aria-label="每期收益与收益率"></svg>
<div id="tip"></div>
</div>
<script>
(() => {
  const D = __PDATA__;
  const rows = D.rows || [];
  const wrap = document.getElementById('wrap'), svg = document.getElementById('chart'), tip = document.getElementById('tip');
  const H = D.height, L = 66, R = 60, T = 16, B = 30;
  const ok = v => v !== null && v !== undefined && Number.isFinite(v);
  const col = v => Math.abs(v) < 1e-9 ? '#94A3B8' : (v > 0 ? '#C52828' : '#16703B');
  const fmtC = v => { const a = Math.abs(v);
    if (a >= 10000) return (v / 10000).toFixed(a >= 100000 ? 0 : 2) + '万';
    return v.toFixed(0); };
  let rdec = 2, W = 0, slot = 0;
  const fmtP = v => (v > 0 ? '+' : '') + v.toFixed(Math.max(2, rdec)) + '%';
  const money = v => Math.abs(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  function show(r, i) {
    tip.innerHTML = `<div class="tip-row"><span class="tip-label">${r.k}</span>`
      + `<b style="color:${col(r.pnl)}">${r.pnl > 0 ? '+' : ''}¥${money(r.pnl)}</b></div>`
      + `<div class="tip-row"><span class="tip-label">收益率</span><b style="color:${col(r.ret)}">${fmtP(r.ret)}</b></div>`
      + `<div class="tip-row"><span class="tip-label">期内回撤</span><b>${fmtP(r.mdd)}</b></div>`
      + `<div class="tip-row"><span class="tip-label">净投入</span><b>¥${money(r.flow)}</b></div>`;
    const g = document.getElementById('guide');
    if (g) { const cx = L + slot * (i + .5); g.setAttribute('x1', cx); g.setAttribute('x2', cx); g.setAttribute('visibility', 'visible'); }
    tip.style.display = 'block';
    const x = L + slot * (i + .5) + 12;
    tip.style.left = Math.max(0, Math.min(W - 184, x)) + 'px';
    tip.style.top = (T + 4) + 'px';
  }
  function hide() {
    tip.style.display = 'none';
    const g = document.getElementById('guide');
    if (g) g.setAttribute('visibility', 'hidden');
  }
  function draw() {
    W = wrap.getBoundingClientRect().width;
    if (W <= L + R + 10) return;
    const n = rows.length, PW = W - L - R, PH = H - T - B;
    svg.setAttribute('width', W); svg.setAttribute('height', H);
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    if (!n) { svg.innerHTML = `<text x="${W/2}" y="${H/2}" text-anchor="middle" font-size="12" fill="#94A3B8">还没有完整的收益区间</text>`; return; }
    let pLo = 0, pHi = 0, rLo = 0, rHi = 0;
    for (const r of rows) { pLo = Math.min(pLo, r.pnl); pHi = Math.max(pHi, r.pnl); rLo = Math.min(rLo, r.ret); rHi = Math.max(rHi, r.ret); }
    const padP = (pHi - pLo) * .16 || 1, padR = (rHi - rLo) * .18 || .5;
    pLo -= padP; pHi += padP; rLo -= padR; rHi += padR;
    const yP = v => T + (pHi - v) * PH / (pHi - pLo);
    const yR = v => T + (rHi - v) * PH / (rHi - rLo);
    rdec = (rHi - rLo) < 0.2 ? 3 : ((rHi - rLo) < 2 ? 2 : 1);
    slot = PW / n;
    const bw = Math.min(42, Math.max(2.5, slot * .56)), xc = i => L + slot * (i + .5);
    let g = '', tx = '', bars = '', dots = '';
    for (let k = 0; k <= 4; k++) {
      const y = T + PH * k / 4;
      g += `<line x1="${L}" y1="${y}" x2="${W-R}" y2="${y}" stroke="#EEF2F7"/>`;
      tx += `<text x="${L-8}" y="${y+4}" text-anchor="end" font-size="10" fill="#475569">${fmtC(pHi - (pHi-pLo)*k/4)}</text>`;
      tx += `<text x="${W-R+8}" y="${y+4}" font-size="10" fill="#94A3B8">${(rHi - (rHi-rLo)*k/4).toFixed(rdec)}%</text>`;
    }
    if (pLo < 0 && pHi > 0) g += `<line x1="${L}" y1="${yP(0)}" x2="${W-R}" y2="${yP(0)}" stroke="#CBD5E1"/>`;
    const step = Math.max(1, Math.ceil(n / Math.max(3, Math.floor(PW / 78))));
    rows.forEach((r, i) => {
      const y0 = yP(0), y1 = yP(r.pnl);
      bars += `<rect x="${xc(i)-bw/2}" y="${Math.min(y0,y1)}" width="${bw}" height="${Math.max(1.5, Math.abs(y1-y0))}" rx="2" fill="${col(r.pnl)}" opacity=".8"/>`;
      if (i % step === 0 || i === n - 1)
        tx += `<text x="${xc(i)}" y="${H-B+16}" text-anchor="middle" font-size="10" fill="#475569">${r.k}</text>`;
      if (n <= 36) dots += `<circle cx="${xc(i)}" cy="${yR(r.ret)}" r="2.8" fill="#3B82F6" stroke="#fff" stroke-width="1"/>`;
    });
    const pts = rows.map((r, i) => `${xc(i)},${yR(r.ret)}`).join(' ');
    let zones = '';
    rows.forEach((r, i) => { zones += `<rect x="${L + slot*i}" y="${T}" width="${slot}" height="${PH}" fill="transparent" style="cursor:crosshair"/>`; });
    svg.innerHTML = g + bars
      + `<polyline points="${pts}" fill="none" stroke="#3B82F6" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>`
      + dots
      + `<line id="guide" x1="0" y1="${T}" x2="0" y2="${T+PH}" stroke="#CBD5E1" stroke-dasharray="3 3" visibility="hidden"/>`
      + tx + zones;
    svg.querySelectorAll('rect[style]').forEach((el, i) => {
      el.addEventListener('mouseenter', () => show(rows[i], i));
      el.addEventListener('mouseleave', hide);
    });
  }
  let raf = 0;
  window.addEventListener('resize', () => { if (!raf) raf = requestAnimationFrame(() => { raf = 0; draw(); }); });
  draw();
})();
</script>"""
    return (tpl.replace("__BASE_CSS__", _COMP_BASE_CSS).replace("__PC_CSS__", _PC_CSS)
               .replace("__PDATA__", data))



def _hg_other_item(code: str, why: str = "位置已关闭") -> dict:
    """「不在启用位置里、账上还有份额」的一只基金 → 与 `_pf_row` 同结构的条目。

    这样列表里点它也能展开走势与累计盈亏（不然点了只剩一句说明，等于只能看不能查）。
    """
    _nav = _nav_of_code(code)
    px = float(_nav.iloc[-1]) if len(_nav) else 0.0
    px_prev = float(_nav.iloc[-2]) if len(_nav) > 1 else px
    sh = float(_acct_pos.get(code, 0) or 0)
    cst = float(_acct_cost.get(code, 0) or 0)
    _meta = HG.fund_meta(holdings, code)[1] or {}
    return {
        "code": code, "f": _meta, "slot": why, "x": 1.0, "slot_n": 1,
        "px": px, "px_prev": px_prev, "px_prev_day": (_nav.index[-2] if len(_nav) > 1 else None),
        "shares": sh, "cost": cst, "mv": sh * px,
        "pl": ((px / cst - 1) if (cst > 0 and px > 0) else None),
        "otc": HG.is_otc(_meta) if _meta else (HG.default_unit(code) == "份额"),
        # 权重按「全账户总资产」算：这些钱不进调仓，但占总资产多少要说得对
        # （用调仓基数当分母会算出 130% 这种数）
        "w_now": ((sh * px / _plan["total"]) if _plan["total"] else 0.0), "w_tgt": None,
        "side": "", "qty": 0.0, "amount": 0.0, "note": "", "why": why,
        "dev": 0.0, "slot_first": True,
    }


def _pf_sign(v: float) -> str:
    return "up" if v > 0 else ("down" if v < 0 else "")


def _pf_num(v: float, digits: int = 0) -> str:
    """0 不写正负号（避免「+0」「-0」这种看着像出错的写法），其余照常带符号。"""
    if abs(v) < 0.5 * 10 ** (-digits):
        return f"{0:.{digits}f}"
    return f"{v:+,.{digits}f}"


def _pf_badge_parts(it: dict, with_qty: bool = False) -> tuple[str, str]:
    """买卖标记的（文字, 样式类）—— 列表、提醒清单、成交登记共用一套措辞，不改口径。

    with_qty：调仓清单里要直接下单，金额后面跟上「多少份 / 多少股」；
    持仓列表空间小，只留金额。
    """
    _qty_txt = ""
    if with_qty and it.get("qty", 0) > 0:
        _u, _d = ("份", 2) if it.get("otc") else ("股", 0)
        _qty_txt = f' · {it["qty"]:,.{_d}f} {_u}'
    if it.get("side") == "买入":
        return (f'买入 ¥{it["amount"]:,.0f}{_qty_txt}', "buy")
    if it.get("side") == "卖出":
        return (f'卖出 ¥{it["amount"]:,.0f}{_qty_txt}', "sell")
    if it.get("note") == "缺净值":
        return ("缺净值", "warn")
    if it.get("note") == "不足一手":
        return ("不足一手", "warn")
    if it.get("shares", 0) <= 0:
        return ("未持有", "hold")
    return ("持有不动", "hold")


def _pf_badge(it: dict, with_qty: bool = False) -> str:
    """买卖标记 —— 一行只看最右就知道这一轮该买还是该卖。"""
    text, cls = _pf_badge_parts(it, with_qty)
    return f'<span class="pf-badge {cls}">{text}</span>'


def _pf_state_parts(it: dict) -> tuple[str, str]:
    """持仓表的最后一列：只报「这只基金现在有什么问题」，正常持有的行留空。

    买卖动作一律在「帮你算」页给一处 —— 同一个东西在两张表上各标一遍，
    位置开关一变就会互相打脸。留空的列反而更好用：扫一眼只有异常行有字。
    """
    if it.get("why"):
        return (it["why"], "warn")           # 位置已关闭 / 不在配置里
    if it.get("note") == "缺净值":
        return ("缺净值", "warn")
    if it.get("shares", 0) <= 0:
        return ("未持有", "hold")
    return ("", "")


def _pf_state_badge(it: dict) -> str:
    text, cls = _pf_state_parts(it)
    return f'<span class="pf-badge {cls}">{text}</span>'


def _pf_day(it: dict) -> tuple[float, float | None]:
    """条目 → 今日涨跌（元, %）。规则见 `_held_day`（列表、详情、头卡共用一份口径）。"""
    return _held_day(it["code"], it["shares"], it["px"], it["px_prev"], it.get("px_prev_day"))


def _pf_row(it: dict) -> dict:
    """一只基金 → 持仓列表的一行。所有显示串在这里算好，组件只负责排版与点击。"""
    code = it["code"]
    tag = "场外" if it["otc"] else "场内"
    if it["slot_n"] > 1:
        tag += f" · 位置内 {it['x'] * 100:.0f}%"
    shares, px, px_prev, cost = it["shares"], it["px"], it["px_prev"], it["cost"]
    held = shares > 0
    day, day_pct = _pf_day(it)          # 建仓日之前那段涨跌不属于这笔持仓，见 _pf_day
    hold = it["mv"] - shares * cost
    hold_pct = it["pl"] * 100 if it["pl"] is not None else None
    w_tgt = it.get("w_tgt")            # None = 不在任何启用位置里（没有目标权重）
    dev = (it["w_now"] - w_tgt) if w_tgt is not None else 0.0
    badge, badge_cls = _pf_state_parts(it)
    return {
        "code": code,
        "name": str(it["f"].get("name") or FL.fund_name(code) or code),
        "tag": tag,
        "slot": HG.SLOT_LABEL.get(it["slot"], it["slot"]),
        "amt": f"{it['mv']:,.0f}",
        "day": _pf_num(day) if held else "—",
        "day_sub": (f"{_pf_num(day_pct, 2)}%" if (held and day_pct is not None) else ""),
        "day_cls": _pf_sign(day) if held else "",
        "hold": _pf_num(hold) if held else "—",
        "hold_sub": (f"{_pf_num(hold_pct, 2)}%" if (held and hold_pct is not None) else ""),
        "hold_cls": _pf_sign(hold) if held else "",
        "w": f'{it["w_now"] * 100:.1f}%',
        "wtgt": "—" if w_tgt is None else f"{w_tgt * 100:.1f}%",
        "dev": ("—" if (w_tgt is None or abs(dev) < 0.005) else f"{dev * 100:+.1f}pp"),
        "dev_cls": "" if (w_tgt is None or abs(dev) < 0.005) else _pf_sign(dev),
        "badge": badge,
        "badge_cls": badge_cls,
    }


# 持仓列表：一只基金一行，点一行回传代码。用 components v2 而不是 st.dataframe，
# 因为「涨红跌绿 + 买卖标记」要自己上色，表格控件给不了每个单元格的颜色。
_PF_LIST_CSS = r"""
:host{display:block}
.tbl{font:13px/1.5 -apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans SC","Microsoft YaHei",sans-serif;
  color:#0F172A;background:#fff;border:1px solid #E2E8F0;border-radius:14px;
  max-height:462px;overflow:auto}   /* 限高：不展开详情时列表自己滚，别把整页顶长 */
/* 点开一只基金时列表被切成上下两段，详情插在中间 —— 三段拼起来仍是一张卡 */
.tbl.nocap{max-height:none;overflow:visible}
.tbl.nohead .hd{display:none}
.tbl.pos-top{border-radius:14px 14px 0 0;border-bottom:0}
.tbl.pos-bot{border-radius:0 0 14px 14px;border-top:0}
.hd,.rw{display:grid;grid-template-columns:minmax(0,2.2fr) 118px 104px 104px 128px 112px;
  gap:10px;align-items:center;padding:10px 14px}
.hd{background:#F8FAFC;border-bottom:1px solid #E2E8F0;font-size:12px;color:#64748B;
  position:sticky;top:0;z-index:2}
.hd .r{text-align:right}
.rw{border-bottom:1px solid #F1F5F9;cursor:pointer;transition:background .12s}
.rw:last-child{border-bottom:0}
.rw:hover{background:#F8FAFC}
.rw:focus-visible{outline:2px solid #3B82F6;outline-offset:-2px}
.rw.on{background:#EFF6FF;box-shadow:inset 3px 0 0 #3B82F6}
.nm{font-size:13.5px;font-weight:600;letter-spacing:-.1px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sub{font-size:11.5px;color:#94A3B8;margin-top:2px;font-variant-numeric:tabular-nums;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.num{text-align:right;font-variant-numeric:tabular-nums;font-size:13px;font-weight:600}
.num .sub{font-weight:400;opacity:.78;color:inherit}
.up{color:#C52828}
.down{color:#16703B}
.bg{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11.5px;font-weight:600;
  border:1px solid transparent;white-space:nowrap}
.bg.buy{background:#FEF2F2;color:#C52828;border-color:#FECACA}
.bg.sell{background:#F0FDF4;color:#16703B;border-color:#BBF7D0}
.bg.hold{background:#F1F5F9;color:#64748B;border-color:#E2E8F0;font-weight:500}
.bg.warn{background:#FFFBEB;color:#B45309;border-color:#FDE68A;font-weight:500}
.c-badge{text-align:right}
@media(max-width:900px){   /* 手机上只留「基金名 / 金额 / 这一轮」，其余数字点开看详情 */
  .hd,.rw{grid-template-columns:minmax(0,1fr) 88px 92px;padding:9px 12px;gap:8px}
  .c-day,.c-hold,.c-w{display:none}
  .hd div{white-space:nowrap}
}
"""

_PF_LIST_JS = r"""
export default function (c) {
  const { data, setStateValue, parentElement } = c;
  const D = data || {};
  // 每次重跑都会重新调用本函数，旧实例的清理要等卸载，先清掉上一次留下的
  Array.from(parentElement.children).forEach(el => {
    if (el && el.classList && el.classList.contains('tbl')) el.remove();
  });
  const rows = D.rows || [], sel = D.selected || '';
  // 展开/收起时，这块内容会被整块清空重画：页面高度瞬间掉到几十像素，浏览器就把滚动位置
  // 夹到顶上再让我们拉回来 —— 用户看到的就是「闪一下、往上跳、再弹回去」。两件事一起做：
  //   1) 点下去的瞬间把主容器 min-height 钉在当前高度，页面塌不下来，位置就不会被夹；
  //   2) 同时记下被点那一行在屏幕上离顶多远，重跑期间按帧把它挪回原位（行还没画出来的帧不动）。
  // 守卫挂在父页 window 上而不是本组件里：重跑会卸载本组件，卸载之后还得有人继续钉着。
  const PDOC = parentElement.ownerDocument, PWIN = PDOC && PDOC.defaultView;
  const GKEY = '__awPfGuard';
  const scroller = () => (PDOC && (PDOC.querySelector('[data-testid="stMain"]') || PDOC.scrollingElement)) || null;
  const hostOf = () => PDOC && PDOC.querySelector('[data-testid="stMainBlockContainer"]');
  // 行在组件自己的影子树里，document.querySelector 找不到 —— 递归穿一遍 shadowRoot
  const deepRow = (code) => {
    const find = (root) => {
      const hit = root.querySelector && root.querySelector('.rw[data-code="' + code + '"]');
      if (hit) return hit;
      const kids = (root.querySelectorAll && root.querySelectorAll('*')) || [];
      for (const k of kids) if (k.shadowRoot) { const r = find(k.shadowRoot); if (r) return r; }
      return null;
    };
    return find(PDOC);
  };
  const guard = (PWIN && (PWIN[GKEY] = PWIN[GKEY] || { anchor: null, raf: 0, row: null, hostMin: null })) || null;
  if (guard) {
    guard.stop = () => {
      const h = hostOf();
      if (h && guard.hostMin !== null) h.style.minHeight = guard.hostMin;   // 先把钉住的高度还回去
      const a = guard.anchor, row = guard.row;
      guard.anchor = null; guard.row = null; guard.hostMin = null;
      // 还回去之后页面可能变矮（收起的那个方向），再按行钉一次；超界就交给浏览器夹
      const sc = scroller();
      if (sc && row && row.isConnected && a) {
        const dy = row.getBoundingClientRect().top - a.top;
        if (Math.abs(dy) > 0.5) sc.scrollTop = sc.scrollTop + dy;
      }
    };
    guard.loop = () => {
      const a = guard.anchor;
      if (!a) { guard.raf = 0; return; }
      const sc = scroller();
      let key = '?';
      if (sc) {
        if (!guard.row || !guard.row.isConnected) guard.row = deepRow(a.code);
        if (guard.row) {
          const dy = guard.row.getBoundingClientRect().top - a.top;
          if (Math.abs(dy) > 0.5) sc.scrollTop = sc.scrollTop + dy;
        }
        key = sc.scrollTop + '/' + sc.scrollHeight;
      }
      const now = Date.now();
      if (key !== a.key) { a.key = key; a.still = now; }
      // 位置连续 260ms 没再变就收工（常见的展开 300ms 内就稳了）；
      // 最多钉 900ms，防止中途出错把页面高度永久锁住
      if (now - a.t > 900 || (now - a.t > 280 && now - (a.still || now) > 260)) {
        guard.stop(); guard.raf = 0; return;
      }
      guard.raf = requestAnimationFrame(guard.loop);
    };
    guard.start = (code, el) => {
      const h = hostOf();
      // 连点同一下（展开再收起）：沿用第一次记下的屏幕位置。第二次若在重排中间量，
      // 量到的是「已经被挪走」的位置，越钉越偏
      const keep = guard.anchor && guard.anchor.code === code && Date.now() - guard.anchor.t < 1500;
      guard.anchor = { code, top: keep ? guard.anchor.top : el.getBoundingClientRect().top,
                       t: Date.now(), key: '', still: Date.now() };
      guard.row = el;
      if (h && guard.hostMin === null) {
        guard.hostMin = h.style.minHeight || '';
        h.style.minHeight = Math.round(h.offsetHeight) + 'px';
      }
      if (!guard.raf) guard.raf = requestAnimationFrame(guard.loop);
    };
    // 用户自己滚了就不再抢：滚轮/触摸/按键一出现就收工（我们自己改 scrollTop 不会触发这些）
    if (!guard.wired) {
      guard.wired = true;
      const bail = () => { if (guard.anchor) guard.stop(); };
      ['wheel', 'touchstart', 'keydown'].forEach(n =>
        PDOC.addEventListener(n, bail, { passive: true, capture: true }));
    }
  }
  const esc = s => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const rowHtml = r => '<div class="rw' + (r.code === sel ? ' on' : '') + '" role="row" tabindex="0"'
    + ' data-code="' + esc(r.code) + '">'
    + '<div class="c-name"><div class="nm">' + esc(r.name) + '</div>'
    + '<div class="sub">' + esc(r.code) + ' · ' + esc(r.tag) + ' · ' + esc(r.slot) + '</div></div>'
    + '<div class="num c-amt">' + esc(r.amt) + '</div>'
    + '<div class="num c-day ' + esc(r.day_cls) + '">' + esc(r.day)
    + (r.day_sub ? '<div class="sub">' + esc(r.day_sub) + '</div>' : '') + '</div>'
    + '<div class="num c-hold ' + esc(r.hold_cls) + '">' + esc(r.hold)
    + (r.hold_sub ? '<div class="sub">' + esc(r.hold_sub) + '</div>' : '') + '</div>'
    + '<div class="num c-w">' + esc(r.w) + ' <span class="sub">/ ' + esc(r.wtgt) + '</span>'
    + '<div class="sub ' + esc(r.dev_cls) + '">' + esc(r.dev) + '</div></div>'
    + '<div class="c-badge">' + (r.badge
        ? '<span class="bg ' + esc(r.badge_cls) + '">' + esc(r.badge) + '</span>' : '')
    + '</div>'
    + '</div>';
  const root = document.createElement('div');
  root.className = ['tbl', D.pos ? 'pos-' + D.pos : '', D.cap === false ? 'nocap' : '',
    D.head === false ? 'nohead' : ''].filter(Boolean).join(' ');
  root.setAttribute('role', 'table');
  root.innerHTML = '<div class="hd"><div>我的基金</div><div class="r">金额</div>'
    + '<div class="r c-day">今日收益</div><div class="r c-hold">持有收益</div>'
    + '<div class="r c-w">占比 / 目标</div><div class="r c-badge">状态</div></div>'
    + rows.map(rowHtml).join('');
  parentElement.appendChild(root);
  root.querySelectorAll('.rw').forEach(el => {
    // 每次点击都带上时间戳：点同一行（收起后再点回来）也要触发重跑，
    // 只回传代码时「值没变 → 不重跑 → 点了没反应」
    const pick = () => {
      // 先把守卫叫起来（钉高度 + 记锚点），再交给 Streamlit 重跑 —— 顺序反了会漏掉第一帧
      try { if (guard) guard.start(el.dataset.code, el); } catch (e) { /* 钉不住也不影响点击 */ }
      setStateValue('picked', el.dataset.code);
      setStateValue('picked_at', Date.now());
    };
    el.addEventListener('click', pick);
    el.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); }
    });
  });
  return () => root.remove();
}
"""

_PF_LIST = st.components.v2.component("aw_pf_list", css=_PF_LIST_CSS, js=_PF_LIST_JS)


def _pf_list(rows: list[dict], selected: str = "", key: str = "pf_list",
             head: bool = True, cap: bool = True, pos: str = ""):
    """渲染持仓列表，返回 (这次点中的代码, 点击时刻)。

    `selected` 由调用方给（没展开详情就传空串，列表不高亮任何一行）；
    时刻用来区分「用户刚点了这一行」和「上一次的选择还留着」——
    有了它，收起之后再点同一行也能重新展开。

    点开一只基金时，调用方把列表切成上下两段、详情插在中间（详情就落在被点的那一行下面）：
    上半段 pos="top"、下半段 pos="bot" 且 head=False（不重复表头），两段都不限高。
    """
    if not rows:
        return "", 0
    codes = [r["code"] for r in rows]
    sel = selected if selected in codes else ""
    res = _PF_LIST(key=key, data={"rows": rows, "selected": sel,
                                  "head": head, "cap": cap, "pos": pos},
                   default={"picked": sel, "picked_at": 0},
                   on_picked_change=lambda: None, on_picked_at_change=lambda: None)
    out = res.get("picked") if hasattr(res, "get") else None
    at = int(res.get("picked_at") or 0) if hasattr(res, "get") else 0
    return (out if out in codes else ""), at


# 台账：点行尾铅笔，这一行下面直接展开编辑面板（日期 / 类型 / 基金 / 金额 / 单价 / 手续费），
# 保存后整页重算；点垃圾桶在行内就地确认删除。全部在组件里完成，不再把人送回页面顶部的表单。
# 回传都带时间戳：只回传行号时连点同一行第二次值不变，不会触发 rerun。
_TRADE_LIST_CSS = r"""
:host{display:block}
.wrap{font:13px/1.5 -apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans SC","Microsoft YaHei",sans-serif;
  color:#0F172A;background:#fff;border:1px solid #E2E8F0;border-radius:14px;overflow:auto;
  max-height:520px}   /* 台账不超过一屏半：记多少笔都这个高度，表头吸顶、里面自己滚 */
.hd,.rw{display:grid;grid-template-columns:minmax(0,1fr) 104px 86px 112px 72px;
  gap:12px;align-items:center;padding:9px 14px}
.hd{background:#F8FAFC;border-bottom:1px solid #E2E8F0;font-size:12px;color:#64748B;
  position:sticky;top:0;z-index:2}
.hd .r{text-align:right}
.rw{border-bottom:1px solid #F1F5F9}
.rw:last-child{border-bottom:0}
.rw:hover{background:#F8FAFC}
.rw.on{background:#EFF6FF;box-shadow:inset 3px 0 0 #3B82F6}
/* 日期分组头：同一天的成交归一组，日期不再每行重复 */
.grp{display:flex;align-items:baseline;gap:10px;padding:9px 14px 7px;background:#F8FAFC;
  border-top:1px solid #E2E8F0;font-size:12px;color:#64748B}
.hd+.grp{border-top:0}
.grp .gd{font-weight:600;color:#334155;font-variant-numeric:tabular-nums}
.grp .gm{margin-left:auto;font-variant-numeric:tabular-nums}
.dt{font-variant-numeric:tabular-nums;color:#334155}
/* 基金名 + 类型徽标同一行：类型贴着名字，不单独占一列（14 行全「买入」时那样大片是空的） */
.nm{display:flex;align-items:center;gap:8px;min-width:0}
.nm .t{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.nm .bg{flex:none}
.sub{font-size:11.5px;color:#94A3B8;font-variant-numeric:tabular-nums;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.num{text-align:right;font-variant-numeric:tabular-nums;font-weight:600;font-size:13px}
.bg{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11.5px;font-weight:600;
  border:1px solid transparent;white-space:nowrap}
.bg.buy{background:#FEF2F2;color:#C52828;border-color:#FECACA}
.bg.sell{background:#F0FDF4;color:#16703B;border-color:#BBF7D0}
.bg.money{background:#F1F5F9;color:#475569;border-color:#E2E8F0;font-weight:500}
.ops{display:flex;gap:6px;justify-content:flex-end}
.op{width:28px;height:28px;display:grid;place-items:center;border-radius:8px;cursor:pointer;
  border:1px solid #E2E8F0;background:#fff;color:#64748B;padding:0;transition:.12s}
.op:hover{border-color:#94A3B8;color:#0F172A;background:#F8FAFC}
.op.del:hover{border-color:#FECACA;color:#C52828;background:#FEF2F2}
.op svg{width:15px;height:15px}

/* ---- 就地展开的编辑面板 ---- */
.ed{background:#F8FAFC;border-bottom:1px solid #E2E8F0;padding:14px;box-shadow:inset 3px 0 0 #3B82F6}
.ed .r1{display:grid;grid-template-columns:150px 272px minmax(0,1fr);gap:10px}
.ed .r2{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:10px}
.ed .r2.one{grid-template-columns:minmax(0,240px)}
.ed label,.ed .fld{display:flex;flex-direction:column;gap:4px;font-size:11.5px;color:#64748B;min-width:0}
.ed .lb{font-size:11.5px;color:#64748B}
.ed input,.ed select{height:34px;border:1px solid #CBD5E1;border-radius:8px;padding:0 9px;
  font:13px/34px inherit;color:#0F172A;background:#fff;width:100%;box-sizing:border-box;min-width:0}
.ed input:focus,.ed select:focus{outline:2px solid #BFDBFE;border-color:#3B82F6}
.ed .chips{display:flex;gap:2px;padding:3px;background:#fff;border:1px solid #CBD5E1;border-radius:9px;height:34px;box-sizing:border-box}
.ed .chips button{flex:1;border:0;border-radius:6px;background:transparent;color:#475569;
  font-size:12.5px;cursor:pointer;padding:0}
.ed .chips button[aria-pressed="true"]{background:#0F172A;color:#fff;font-weight:600}
.ed .calc{text-align:right;font-size:12px;color:#475569;margin-top:8px;
  font-variant-numeric:tabular-nums;min-height:18px}
.ed .foot{display:flex;justify-content:flex-end;gap:8px;margin-top:12px}
.ed .foot button{height:32px;padding:0 16px;border-radius:8px;font-size:13px;cursor:pointer;border:1px solid #CBD5E1}
.ed .foot .ghost{background:#fff;color:#475569}
.ed .foot .ghost:hover{background:#F1F5F9}
.ed .foot .primary{background:#1E40AF;border-color:#1E40AF;color:#fff;font-weight:600}
.ed .foot .primary:hover{background:#1E3A8A}
/* ---- 删除就地确认 ---- */
.cf{display:flex;align-items:center;gap:12px;flex-wrap:wrap;background:#FEF2F2;
  border-bottom:1px solid #FECACA;padding:11px 14px;font-size:12.5px;color:#7F1D1D;
  box-shadow:inset 3px 0 0 #C52828}
.cf b{font-weight:600}
.cf .btns{margin-left:auto;display:flex;gap:8px}
.cf .btns button{height:30px;padding:0 14px;border-radius:8px;font-size:12.5px;cursor:pointer;border:1px solid #FECACA}
.cf .btns .danger{background:#C52828;border-color:#C52828;color:#fff;font-weight:600}
.cf .btns .ghost{background:#fff;color:#7F1D1D}
@media(max-width:900px){   /* 手机上留「基金 / 类型 / 金额 / 操作」，单价等细节进编辑面板再看 */
  .hd,.rw{grid-template-columns:minmax(0,1fr) 96px 72px;padding:9px 12px;gap:8px}
  .c-nav,.c-qty{display:none}
  .grp{padding:8px 12px 6px}
  .ed{padding:12px}
  .ed .r1{grid-template-columns:1fr 1fr;gap:8px}
  .ed .r1 label:nth-child(3),.ed .r2{grid-column:1/-1}
  .ed .r2{grid-template-columns:1fr 1fr;margin-top:8px}
  .ed .calc{text-align:left}
  .ed .foot{margin-top:10px}
}
"""

_TRADE_LIST_JS = r"""
export default function (c) {
  const { data, setStateValue, parentElement } = c;
  const D = data || {};
  // 每次重跑都会重新调用本函数，旧实例的清理要等卸载，先清掉上一次留下的
  Array.from(parentElement.children).forEach(el => {
    if (el && el.classList && el.classList.contains('wrap')) el.remove();
  });
  const rows = D.rows || [], funds = D.funds || [];
  let open = null, confirmDel = null, draft = null;

  const esc = s => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
  const SVG = {
    edit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>',
    del: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/></svg>'
  };
  const fmt = (v, d) => (Number(v) || 0).toLocaleString('en-US',
    {minimumFractionDigits: d, maximumFractionDigits: d});
  const round2 = v => Math.round(v * 100) / 100;
  const isMoneySide = s => s === '转入' || s === '转出';

  const root = document.createElement('div');
  root.className = 'wrap';
  root.setAttribute('role', 'table');

  // 金额 → 份额：买入按「(金额−手续费)/单价」，卖出按「(金额+手续费)/单价」
  function sharesOf(d) {
    if (isMoneySide(d.side)) return {shares: Number(d.amount) || 0, nav: 0, fee: 0};
    const nav = Number(d.nav) || 0, fee = Number(d.fee) || 0, amt = Number(d.amount) || 0;
    if (!(nav > 0)) return {shares: 0, nav: nav, fee: fee};
    const raw = d.side === '买入' ? (amt - fee) / nav : (amt + fee) / nav;
    return {shares: round2(Math.max(0, raw)), nav: nav, fee: fee};
  }

  // 金额列：买入/转出是钱出去（−），卖出/转入是钱进来（+）；转入转出没有份额和单价
  function amountHtml(r) {
    const out = r.side === '买入' || r.side === '转出';
    return (out ? '−¥' : '+¥') + fmt(Math.abs(Number(r.amount) || 0), 0);
  }

  function rowHtml(r, on) {
    const money = isMoneySide(r.side);
    return '<div class="rw' + (on ? ' on' : '') + '" data-i="' + esc(r.i) + '" role="row">'
      + '<div class="fc"><div class="nm"><span class="t">' + esc(r.name) + '</span>'
      + '<span class="bg ' + esc(r.cls) + '">' + esc(r.side) + '</span></div>'
      + '<div class="sub">' + esc(r.sub) + '</div></div>'
      + '<div class="num c-qty">' + (money ? '' : esc(r.qty)) + '</div>'
      + '<div class="num c-nav">' + (money ? '' : esc(r.nav)) + '</div>'
      + '<div class="num">' + amountHtml(r) + '</div>'
      + '<div class="ops">'
      + '<button class="op" type="button" data-act="edit" title="修改这一笔" aria-label="修改这一笔">' + SVG.edit + '</button>'
      + '<button class="op del" type="button" data-act="del" title="删除这一笔" aria-label="删除这一笔">' + SVG.del + '</button>'
      + '</div></div>';
  }

  // 同一天合成一组：日期只在组头出现一次，右侧给当日小计
  function groupHead(date, same) {
    const sum = (side) => same.filter((x) => x.side === side)
      .reduce((s, x) => s + (Number(x.amount) || 0), 0);
    const bits = [same.length + ' 笔'];
    [['买入', sum('买入')], ['卖出', sum('卖出')]].forEach(([k, v]) => {
      if (v > 0.5) bits.push(k + ' ¥' + fmt(v, 0));
    });
    return '<div class="grp"><span class="gd">' + esc(date) + '</span>'
      + '<span class="gm">' + bits.join(' · ') + '</span></div>';
  }

  function editorHtml(r) {
    const d = draft;
    const chips = ['买入', '卖出'].map(s =>
      '<button type="button" data-side="' + s + '" aria-pressed="' + (d.side === s) + '">' + s + '</button>').join('');
    const opts = funds.map(f => {
      const key = esc(f.code) + '|' + esc(f.slot);
      const sel = (f.code === d.code && (!d.slot || f.slot === d.slot)) ? ' selected' : '';
      return '<option value="' + key + '"' + sel + '>' + esc(f.label) + '</option>';
    }).join('');
    const third = '<label>基金<select data-f="fund">' + opts + '</select></label>';
    const r2 = '<div class="r2">'
      + '<label>金额（元）<input type="number" step="0.01" min="0" data-f="amount" value="' + esc(d.amount) + '"></label>'
      + '<label>单价（元/' + (d.unit === '股' ? '股' : '份') + '）<input type="number" step="0.0001" min="0" data-f="nav" value="' + esc(d.nav) + '"></label>'
      + '<label>手续费（元，可留 0）<input type="number" step="0.01" min="0" data-f="fee" value="' + esc(d.fee) + '"></label>'
      + '</div>';
    return '<div class="ed" data-i="' + esc(r.i) + '">'
      + '<div class="r1">'
      + '<label>日期<input type="date" data-f="date" value="' + esc(d.date) + '"></label>'
      + '<div class="fld"><span class="lb">类型</span><div class="chips">' + chips + '</div></div>'
      + third + '</div>' + r2 + '<div class="calc" id="calc"></div>'
      + '<div class="foot"><button type="button" class="ghost" data-act="cancel">取消</button>'
      + '<button type="button" class="primary" data-act="save">保存这一笔</button></div></div>';
  }

  function confirmHtml(r) {
    return '<div class="cf" data-i="' + esc(r.i) + '"><span>删除这一笔？<b>'
      + esc(r.date) + ' ' + esc(r.side) + ' ' + esc(r.name) + ' ' + esc(r.qty) + '</b>'
      + '　删除后持仓与收益会立刻重算。</span>'
      + '<span class="btns"><button type="button" class="ghost" data-act="cancel">取消</button>'
      + '<button type="button" class="danger" data-act="delyes">删除</button></span></div>';
  }

  function refreshCalc() {
    const el = root.querySelector('#calc');
    if (!el || !draft) return;
    if (isMoneySide(draft.side)) {
      el.textContent = (draft.side === '转入' ? '现金 +¥' : '现金 −¥') + fmt(draft.amount, 2);
      return;
    }
    const r = sharesOf(draft);
    el.textContent = r.nav > 0
      ? '= ' + fmt(r.shares, 2) + (draft.unit === '股' ? ' 股' : ' 份') + ' @ ' + Number(draft.nav).toFixed(4)
      : '单价要大于 0';
  }

  function render() {
    let body = '';
    let last = '';
    for (const r of rows) {
      if (r.dateRaw !== last) {
        body += groupHead(r.date, rows.filter((x) => x.dateRaw === r.dateRaw));
        last = r.dateRaw;
      }
      if (confirmDel === r.i) body += rowHtml(r, true) + confirmHtml(r);
      else if (open === r.i) body += rowHtml(r, true) + editorHtml(r);
      else body += rowHtml(r, false);
    }
    root.innerHTML = '<div class="hd"><div>基金 / 说明</div>'
      + '<div class="r c-qty">数量</div><div class="r c-nav">单价</div>'
      + '<div class="r">金额</div><div class="r">操作</div></div>' + body;
    bind();
    refreshCalc();
  }

  function bind() {
    root.querySelectorAll('[data-act]').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        const act = btn.dataset.act;
        const holder = btn.closest('[data-i]');
        const i = holder ? Number(holder.dataset.i) : -1;
        if (act === 'edit') {
          const r = rows.find(x => x.i === i);
          if (!r) return;
          open = i; confirmDel = null;
          draft = {i: r.i, date: r.dateRaw, side: r.side, code: r.code, slot: r.slot,
                   amount: r.amount, nav: r.navf, fee: r.feef, unit: r.unit, shares: r.shares};
          render();
        } else if (act === 'del') {
          confirmDel = i; open = null; draft = null; render();
        } else if (act === 'delyes') {
          setStateValue('del', i + ':' + Date.now());
        } else if (act === 'cancel') {
          confirmDel = null; open = null; draft = null; render();
        } else if (act === 'save') {
          save();
        }
      });
    });
    root.querySelectorAll('.chips button').forEach(btn => {
      btn.addEventListener('click', () => {
        draft.side = btn.dataset.side;
        render();
      });
    });
    root.querySelectorAll('[data-f]').forEach(el => {
      const f = el.dataset.f;
      const onEdit = () => {
        if (f === 'fund') {
          const parts = String(el.value).split('|');
          draft.code = parts[0] || ''; draft.slot = parts[1] || '';
          const meta = funds.find(x => x.code === draft.code && x.slot === draft.slot) || {};
          draft.unit = meta.unit || '份';
        } else if (f === 'date') {
          draft.date = el.value;
        } else {
          draft[f] = el.value;
        }
        refreshCalc();
      };
      el.addEventListener('input', onEdit);
      el.addEventListener('change', onEdit);
    });
  }

  function save() {
    if (!draft) return;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(draft.date || ''))) {
      const el = root.querySelector('#calc');
      if (el) el.textContent = '日期要选一下';
      return;
    }
    const r = sharesOf(draft);
    if (!isMoneySide(draft.side) && !draft.code) {
      const el = root.querySelector('#calc');
      if (el) el.textContent = '先选一只基金';
      return;
    }
    if (!(r.shares > 0)) {
      const el = root.querySelector('#calc');
      if (el) el.textContent = isMoneySide(draft.side) ? '金额要大于 0' : '金额和单价要填对（份额要大于 0）';
      return;
    }
    // 只是打开又不改金额时，沿用原来的份额，避免「四舍五入」把份额算歪
    const same = Math.abs(r.shares - (Number(draft.shares) || 0)) < 0.01
      && Number(draft.amount) === (Number(rows.find(x => x.i === draft.i).amount) || 0);
    const payload = {
      i: draft.i, ts: Date.now(), date: draft.date, side: draft.side,
      slot: draft.slot || '', code: isMoneySide(draft.side) ? '' : (draft.code || ''),
      shares: same ? Number(draft.shares) : r.shares,
      nav: isMoneySide(draft.side) ? 0 : r.nav,
      fee: isMoneySide(draft.side) ? 0 : r.fee
    };
    setStateValue('save', JSON.stringify(payload));
  }

  render();
  parentElement.appendChild(root);
  return () => root.remove();
}
"""

_TRADE_LIST = st.components.v2.component("aw_trade_list", css=_TRADE_LIST_CSS, js=_TRADE_LIST_JS)


def _trade_list(rows: list[dict], funds: list[dict] | None = None, key: str = "trade_list"):
    """渲染台账并返回 (保存请求, 删除请求)：保存是 JSON 字符串，删除是「行号:时间戳」，没点过就是 None。"""
    if not rows:
        return None, None
    res = _TRADE_LIST(key=key, data={"rows": rows, "funds": funds or []},
                      default={"save": None, "del": None},
                      on_save_change=lambda: None, on_del_change=lambda: None)
    if not hasattr(res, "get"):
        return None, None
    return res.get("save"), res.get("del")


def _trade_row(i: int, t: dict) -> dict:
    """一笔成交 → 台账一行：既给显示用的字符串，也给编辑面板要用的原始数值。"""
    side = "转入" if t.get("side") in ("转入", "入金") else (
        "转出" if t.get("side") in ("转出", "出金") else str(t.get("side") or ""))
    money = side in _MONEY_SIDES
    _, meta = HG.fund_meta(holdings, t.get("code", ""))
    name = ((meta.get("name") if meta else "") or FL.fund_name(t.get("code", ""))
            or ("账户现金" if money else "—"))
    shares, nav, fee = (float(t.get("shares") or 0), float(t.get("nav") or 0),
                        float(t.get("fee") or 0))
    if money:
        qty, nav_s, code_s, unit = f"¥{shares:,.0f}", "—", "", "元"
        amount = shares
        sub = "银行卡 → 现金" if side == "转入" else "现金 → 银行卡"
    else:
        unit = ((meta.get("unit") if meta else None) or HG.default_unit(t.get("code", "")))
        qty = f"{shares:,.2f} 份" if unit == "份额" or unit == "份" else f"{shares:,.0f} 股"
        nav_s, code_s = (f"{nav:.4f}" if nav > 0 else "—"), str(t.get("code") or "")
        amount = shares * nav + fee if side == "买入" else shares * nav - fee
        sub = code_s
    return {"i": i, "date": _cn_date(t.get("date")), "dateRaw": str(t.get("date"))[:10],
            "side": side, "slot": str(t.get("slot") or ""), "code": code_s,
            "cls": "buy" if side == "买入" else ("sell" if side == "卖出" else "money"),
            "name": str(name), "sub": sub, "qty": qty, "nav": nav_s,
            "fee": (f"{fee:,.2f}" if fee else "—"),
            "amount": round(amount, 2), "navf": (0.0 if money else nav),
            "feef": (0.0 if money else fee), "shares": shares,
            "unit": ("股" if unit == "股" else "份")}


def _code_trades(code: str) -> list[dict]:
    """这只基金的历史买卖点：图上三角 + 提示框文案。日期转成与图表相同的 2026/10/27 口径。"""
    out = []
    for t in ((acct or {}).get("trades") or []):
        if str(t.get("code") or "") != str(code) or t.get("side") not in ("买入", "卖出"):
            continue
        try:
            day = pd.Timestamp(str(t.get("date"))).strftime("%Y/%m/%d")
        except Exception:  # noqa: BLE001
            continue
        sh, nav = float(t.get("shares") or 0), float(t.get("nav") or 0)
        _, _meta = HG.fund_meta(holdings, code)
        _unit = (_meta.get("unit") if _meta else None) or HG.default_unit(code)
        qty = f"{sh:,.0f} 股" if _unit == "股" else f"{sh:,.2f} 份"
        out.append({"date": day, "side": t["side"],
                    "label": (f"{qty} @ {nav:.4f}" if nav > 0 else qty)})
    return sorted(out, key=lambda x: x["date"])


def _code_pnl_curve(code: str) -> pd.Series:
    """这只基金从第一笔成交到今天的**累计盈亏**（元），口径对齐支付宝「累计盈亏」。

    累计盈亏 = 当前持仓市值 + 累计卖出净额 − 累计买入总额（买入含手续费、卖出扣手续费）。
    也就是「还拿在手里的浮盈 + 已经落袋的实盈」，所以卖出后曲线不会掉下来，
    而「持有收益」只算手上这一部分。转入/转出是账户层面的钱，与单只基金无关，不进这条曲线。
    """
    nav = _nav_of_code(code)
    if not len(nav):
        return pd.Series(dtype=float)
    rows = [t for t in ((acct or {}).get("trades") or [])
            if str(t.get("code") or "") == code]
    return _fund_pnl(rows, nav)


_PNL_CSS = _COMP_BASE_CSS + r"""
.pnl-top{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:12px 0 2px}
.pnl-val{font-size:26px;font-weight:650;letter-spacing:-.6px;font-variant-numeric:tabular-nums}
.pnl-val.up{color:#C52828}.pnl-val.down{color:#16703B}.pnl-val.flat{color:#475569}
.pnl-sub{font-size:12px;color:#475569}
#chart{display:block;width:100%;touch-action:pan-y;cursor:crosshair}
#tip{width:auto;min-width:172px;max-width:280px}
#tip .tip-big{font-size:15px;font-weight:600;font-variant-numeric:tabular-nums;margin-bottom:2px}
@media(max-width:520px){.pnl-val{font-size:23px}}
"""

_PNL_TPL = r"""<style>__CSS____HEAD_CSS__</style>
<div id="wrap" aria-busy="false">
__HEAD_BLOCK__
<div class="pnl-top"><span class="pnl-val" id="last">—</span><span class="pnl-sub" id="lastsub"></span></div>
<div class="controls"><div id="range-controls" role="group" aria-label="常用区间">__BTNS__</div></div>
<div class="state-line"><span id="selection"></span><span class="date-line"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5" width="16" height="15" rx="2" fill="none"/><path d="M8 3v5m8-5v5M4 10h16"/></svg><span id="range"></span></span></div>
<svg id="chart" role="img" aria-label="累计盈亏曲线，可悬停查看每天的数" tabindex="0"></svg>
<div id="tip"></div>
</div>
<script>
(() => {
  const D = __DATA__;
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

  function apply(label) {
    cur = R[label] ? label : cur;
    start = R[cur].start; count = Math.max(1, R[cur].count);
    start = clamp(start, 0, Math.max(0, n - count));
    const last = clamp(start + count - 1, 0, n - 1);
    // 「全部」按 0 起算，不按第一个观测点起算：累计盈亏的第一天本身就带着浮盈
    // （成本价和当天净值不一样），从首点算会写出一句「持有以来 · 没有变化」，
    // 和上面那个 +¥267 的大数字直接打架。有区间按钮时才比「区间内的变化」。
    const base = PLAIN ? V[start] : (cur === '全部' ? 0 : V[start]);
    const delta = (V[last] - base);
    if (PLAIN) {
      // 总资产没有「盈利」这种说法：只说这段时间多了还是少了多少
      elSel.textContent = (cur === '全部' ? '建仓以来' : cur) + ' · ' + (Math.abs(delta) < .005 ? '没有变化'
        : (delta > 0 ? '增加 ' : '减少 ') + fmt(Math.abs(delta)));
    } else {
      elSel.textContent = (cur === '全部' ? '持有以来' : cur) + ' · ' + (Math.abs(delta) < .005 ? '没有变化'
        : (delta > 0 ? '盈利 ' : '亏损 ') + fmt(Math.abs(delta)));
    }
    elSel.style.color = delta > .005 ? '#C52828' : (delta < -.005 ? '#16703B' : '#475569');
    elRange.textContent = DATES[start] + ' ~ ' + DATES[last];
    document.querySelectorAll('[data-range]').forEach(b =>
      b.setAttribute('aria-pressed', String(b.dataset.range === cur)));
    hover = -1; hideTip(); requestDraw();
    try { localStorage.setItem(STORE, JSON.stringify({ range: cur })); } catch (e) {}
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
    let g = '<defs><clipPath id="pu"><rect x="0" y="0" width="' + W + '" height="' + y0.toFixed(1) + '"/></clipPath>'
          + '<clipPath id="pd"><rect x="0" y="' + y0.toFixed(1) + '" width="' + W + '" height="' + Math.max(0, H - y0).toFixed(1) + '"/></clipPath>'
          // 填充用竖向渐变淡出：平直的曲线（刚买、还没波动）会把线下的面积涂成一整块实色，
          // 看着像「一片空粉色」；贴着曲线浓、越靠近零轴越淡，就不会抢走曲线本身。
          // 用默认的 objectBoundingBox：渐变范围跟着曲线自己的高低走，不用另算坐标
          + '<linearGradient id="gu" x1="0" y1="0" x2="0" y2="1">'
          + '<stop offset="0" stop-color="#C52828" stop-opacity=".18"/>'
          + '<stop offset="1" stop-color="#C52828" stop-opacity=".02"/></linearGradient>'
          + '<linearGradient id="gd" x1="0" y1="0" x2="0" y2="1">'
          + '<stop offset="0" stop-color="#16703B" stop-opacity=".02"/>'
          + '<stop offset="1" stop-color="#16703B" stop-opacity=".18"/></linearGradient></defs>';
    // 横向网格 + 左侧刻度（0 那条单独加深）
    ticks.forEach(v => {
      const Y = ys(v);
      g += '<line x1="' + L + '" x2="' + (W - RT) + '" y1="' + Y.toFixed(1) + '" y2="' + Y.toFixed(1)
         + '" stroke="#F1F5F9" stroke-width="1"/>';
      g += '<text x="' + (L - 8) + '" y="' + (Y + 4).toFixed(1) + '" text-anchor="end" font-size="11" fill="#94A3B8">'
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
    // 折线 + 零轴上下分别填红/绿（涨红跌绿）
    let d = '', firstX = null, lastX = null;
    for (let i = start; i < start + count && i < n; i++) {
      const v = V[i];
      if (!Number.isFinite(v)) continue;
      const X = xs(i), Y = ys(v);
      d += (d ? 'L' : 'M') + X.toFixed(1) + ' ' + Y.toFixed(1);
      if (firstX === null) firstX = X;
      lastX = X;
    }
    if (d) {
      if (D.area !== false) {
        const area = d + 'L' + lastX.toFixed(1) + ' ' + y0.toFixed(1) + 'L' + firstX.toFixed(1) + ' ' + y0.toFixed(1) + 'Z';
        g += '<path d="' + area + '" fill="url(#gu)" clip-path="url(#pu)"/>';
        g += '<path d="' + area + '" fill="url(#gd)" clip-path="url(#pd)"/>';
      }
      g += '<path d="' + d + '" fill="none" stroke="#1E40AF" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>';
    }
    // 窗口里只有十几天时给每个观测点补个小圆点：两点数据的折线是一条横贯全宽的直线，
    // 下面再填一块粉色，看着像「一整块空面积」；有点才知道「这是有数的那几天」。
    if (count <= 20) {
      for (let i = start; i < start + count && i < n; i++) {
        if (!Number.isFinite(V[i])) continue;
        g += '<circle cx="' + xs(i).toFixed(1) + '" cy="' + ys(V[i]).toFixed(1)
           + '" r="2.6" fill="#1E40AF" stroke="#fff" stroke-width="1.4"/>';
      }
    }
    // 买卖点：买画红上三角（线以上）、卖画绿下三角（线以下）
    // 三角放大到 8×13 并加 2px 白描边 —— 原来 6×10 无描边，压在蓝色曲线和粉色面积上几乎看不见
    (D.trades || []).forEach(t => {
      const i = idxOf.get(t.date);
      if (i === undefined || i < start || i >= start + count) return;
      const v = V[i];
      if (!Number.isFinite(v)) return;
      const X = clamp(xs(i), L + 8, W - RT - 8), Y = ys(v);
      g += t.side === '买入'
        ? '<path d="M' + (X - 8).toFixed(1) + ' ' + (Y - 11).toFixed(1) + 'L' + (X + 8).toFixed(1) + ' ' + (Y - 11).toFixed(1) + 'L' + X.toFixed(1) + ' ' + (Y - 24).toFixed(1) + 'Z" fill="#C52828" stroke="#fff" stroke-width="2" stroke-linejoin="round" data-tri="buy"/>'
        : '<path d="M' + (X - 8).toFixed(1) + ' ' + (Y + 11).toFixed(1) + 'L' + (X + 8).toFixed(1) + ' ' + (Y + 11).toFixed(1) + 'L' + X.toFixed(1) + ' ' + (Y + 24).toFixed(1) + 'Z" fill="#16703B" stroke="#fff" stroke-width="2" stroke-linejoin="round" data-tri="sell"/>';
    });
    // 横轴日期（首 / 中 / 尾三档，手机上只留首尾）
    const rawTicks = W < 460 ? [start, start + count - 1]
      : [start, Math.round(start + (count - 1) / 2), start + count - 1];
    const xTicks = [...new Set(rawTicks.map(i => clamp(i, 0, n - 1)))];   // 只有两三天时首中尾会重复
    xTicks.forEach((i, k) => {
      if (i < 0 || i >= n) return;
      const anchor = k === 0 ? 'start' : (k === xTicks.length - 1 ? 'end' : 'middle');
      const X = k === 0 ? L : (k === xTicks.length - 1 ? W - RT : xs(i));
      g += '<text x="' + X.toFixed(1) + '" y="' + (H - 7) + '" text-anchor="' + anchor + '" font-size="11" fill="#94A3B8">' + esc(DATES[i]) + '</text>';
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
    const col = V[i] > 0 ? '#C52828' : (V[i] < 0 ? '#16703B' : '#475569');
    let html = '<div class="tip-big" style="color:' + (PLAIN ? '#0F172A' : col) + '">'
      + esc(PLAIN ? plainFull(V[i]) : fmtFull(V[i])) + '</div>'
      + '<div class="tip-row"><span class="tip-label">' + esc(DATES[i]) + '</span>'
      + (dChg === null ? '' : '<span style="color:' + (dChg > 0 ? '#C52828' : dChg < 0 ? '#16703B' : '#475569') + '">'
         + (dChg >= 0 ? '+' : '-') + '¥' + Math.abs(dChg).toLocaleString('en-US', {maximumFractionDigits: 2}) + '</span>') + '</div>';
    (D.trades || []).filter(t => t.date === DATES[i]).forEach(t => {
      html += '<div class="tip-row"><span class="tip-label">' + esc(t.side) + '</span><span>' + esc(t.label) + '</span></div>';
    });
    tip.innerHTML = html;
    tip.style.display = 'block';
    const wrapRect = wrap.getBoundingClientRect();
    const x = clientX - wrapRect.left, y = clientY - wrapRect.top;
    tip.style.left = clamp(x + 14, 4, Math.max(4, W - 250)) + 'px';
    tip.style.top = clamp(y - 10, 4, Math.max(4, wrapRect.height - 90)) + 'px';
  }

  svg.addEventListener('mousemove', e => {
    const r = svg.getBoundingClientRect();
    const px = (e.clientX - r.left) * (W / r.width);
    const i = clamp(Math.round(start + (px - L) / (PW || 1) * Math.max(1, count - 1)), start, start + count - 1);
    if (i !== hover) { hover = i; requestDraw(); }
    showTip(i, e.clientX, e.clientY);
  });
  svg.addEventListener('mouseleave', () => { hover = -1; hideTip(); requestDraw(); });
  svg.addEventListener('touchstart', e => {
    const t0 = e.touches[0]; if (!t0) return;
    const r = svg.getBoundingClientRect();
    const px = (t0.clientX - r.left) * (W / r.width);
    const i = clamp(Math.round(start + (px - L) / (PW || 1) * Math.max(1, count - 1)), start, start + count - 1);
    hover = i; requestDraw(); showTip(i, t0.clientX, t0.clientY);
  }, { passive: true });
  svg.addEventListener('touchend', () => { hover = -1; hideTip(); requestDraw(); });

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


def _pnl_chart_html(series, trades=None, height=200, store="awPnl.fund",
                    default_range="全部", heading="累计盈亏",
                    mark=None, mark_label="清仓", area=True, sub="", aria=""):
    """单序列金额曲线（元）：零轴上下分别填红/绿，标出这只基金的买卖点。

    和 `_scroll_chart_html` 那张净值图分开：净值图上读不出「我赚了多少钱」，
    这张图直接用元为单位，和支付宝「累计盈亏」同口径。

    ``mark``：竖虚线 + 角标的日期（`YYYY/MM/DD`，已清仓的基金标清仓那天）。
    ``area=False``：不填色、不画零轴 —— 给「账户总资产」这种永远为正的曲线用，
    否则整张图会被涂成一整块粉色，像在说「全程亏」。
    ``sub``：大数字下面那句小字（默认是「持有以来累计…」，总资产要说别的）。
    """
    dates = series.index.strftime("%Y/%m/%d").tolist()
    values = [round(float(v), 2) for v in series.values]
    labels = [lb for lb in ("近1月", "近3月", "近6月", "近1年", "全部") if lb in _TREND_RANGES]
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
            .replace("__HEAD_CSS__", "" if heading else ".controls{margin-top:2px}")
            .replace("__HEAD_BLOCK__", _chart_head_block(heading, "M3 17l5-6 4 3 5-7 4 4"))
            .replace("__BTNS__", btns).replace("__DATA__", payload))


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
/* 第二行「这段时间赚了多少钱」：收益率是百分比、钱是元，两个都要给 ——
   同样 1%，五万的账户和五十万的账户差十倍，只看 % 回顾不出到底赚了多少 */
.cal-cell .mv{font-size:10.5px;color:#64748B;text-align:right;font-variant-numeric:tabular-nums;
  margin-top:-2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cal-cell.up .mv{color:#C0605F}.cal-cell.down .mv{color:#3F7D57}
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


def _calendar_payload(series, money=None):
    """收益日历数据：日涨跌、自然周(W-FRI)、月、年涨跌幅%，均为每期最后交易日相对上期末。

    ``money``：与 series 同索引的「当天赚了多少钱（元）」。给了就同时带每期的钱 ——
    日历格子只写 %，看不出账户到底多了几百还是几千；两个并排才算回顾。
    """
    x = _trend_aggregate(series, "日")
    if len(x) < 2:
        return None
    d = (x.pct_change(fill_method=None) * 100).dropna()
    day = {f"{t:%Y/%m/%d}": round(float(v), 4) for t, v in d.items()}
    mm = pd.Series(dtype=float) if money is None else pd.Series(money).reindex(x.index)
    week, prev = [], None
    for _, g in x.groupby(pd.Grouper(freq="W-FRI")):
        if len(g) == 0:
            continue
        last = float(g.iloc[-1])
        if prev is not None and prev > 0:
            w = {"s": f"{g.index[0]:%Y/%m/%d}", "e": f"{g.index[-1]:%Y/%m/%d}",
                 "v": round((last / prev - 1) * 100, 4)}
            if len(mm):
                w["m"] = round(float(mm.loc[g.index].sum()), 2)
            week.append(w)
        prev = last

    def per(freq, fmt):
        """每期涨跌 = 期末 / 上期期末 − 1。

        第一段没有「上期末」，就拿区间起点当基准 —— 否则 `pct_change` 会把第一段整段丢掉：
        账户只跑了一年时「年」只剩下一段，页脚就变成「全年涨跌 —」，明明月月都有数。
        """
        p = x.resample(freq).last().dropna()
        out, prev = {}, float(x.iloc[0])
        for t, v in p.items():
            if prev > 0:
                out[t.strftime(fmt)] = round((float(v) / prev - 1) * 100, 4)
            prev = float(v)
        return out

    def per_money(freq, fmt):
        """每期赚的钱 = 期内每天的「当天收益（已扣入金）」相加。"""
        if not len(mm):
            return {}
        out = {}
        for _, g in x.groupby(pd.Grouper(freq=freq)):
            if not len(g):
                continue
            v = float(mm.loc[g.index].sum())
            if pd.notna(v):
                out[g.index[-1].strftime(fmt)] = round(v, 2)
        return out

    months = sorted({(t.year, t.month) for t in x.index}, reverse=True)
    years = sorted({t.year for t in x.index}, reverse=True)
    today = date.today()
    dm = [today.year, today.month] if (today.year, today.month) in months else list(months[0])
    dy = today.year if today.year in years else years[0]
    out = {"day": day, "week": week, "month": per("ME", "%Y-%m"), "year": per("YE", "%Y"),
           "months": [list(m) for m in months], "years": years,
           "defMonth": dm, "defYear": dy, "today": f"{today:%Y/%m/%d}"}
    if len(mm):
        out["mday"] = {f"{t:%Y/%m/%d}": round(float(v), 2) for t, v in mm.dropna().items()}
        out["mmonth"] = per_money("ME", "%Y-%m")
        out["myear"] = per_money("YE", "%Y")
    return out


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
  // 保留两位小数，但量级不到 0.01% 时多给两位 —— 账户一天赚两块 / 五十万 = 0.0004%，
  // 只留两位就成了「-0.00%」：既看不出涨跌，又会跟页脚「上涨 3 天」对不上。
  const pct = v => !ok(v) ? '—'
    : (v > 0 ? '+' : '') + v.toFixed(Math.abs(v) > 0 && Math.abs(v) < 0.01 ? 4 : 2) + '%';
  const color = v => !ok(v) || Math.abs(v) < 1e-10 ? '#475569' : (v > 0 ? '#C52828' : '#16703B');
  const p2 = n => String(n).padStart(2, '0');
  const cls = v => !ok(v) ? 'none' : (v > 1e-10 ? 'up' : (v < -1e-10 ? 'down' : 'flat'));
  // 涨跌幅越大底色越深（热力），颜色与 --red / --green 同值
  const heat = (v, mx) => {
    if (!ok(v) || Math.abs(v) < 1e-10) return '';
    const a = (0.06 + 0.22 * Math.min(1, Math.abs(v) / (mx || 1))).toFixed(3);
    return v > 0 ? `background:rgba(197,40,40,${a})` : `background:rgba(22,112,59,${a})`;
  };
  const maxAbs = vals => vals.reduce((m, v) => ok(v) ? Math.max(m, Math.abs(v)) : m, 0.01);
  // 每格的第二行：这段时间赚了多少钱。收益率是百分比、钱是元，两个都要给
  const MDAY = D.mday || {}, MMO = D.mmonth || {}, MYE = D.myear || {};
  const money = v => !ok(v) ? '' : (v > 0 ? '+' : v < 0 ? '-' : '') + '¥'
    + Math.abs(v).toLocaleString('zh-CN', { maximumFractionDigits: 0 });
  const cell = (k, v, mx, extra = '', sub = '', title = '', m) =>
    `<div class="cal-cell ${cls(v)} ${extra}" style="${heat(v, mx)}" title="${title}">`
    + `<span class="k">${k}${sub ? `<small>${sub}</small>` : ''}</span>`
    + `<span class="v">${pct(v)}</span>`
    + (ok(m) ? `<span class="mv">${money(m)}</span>` : '') + '</div>';
  const item = (k, v) => `<span>${k}</span><b style="color:${color(v)}">${pct(v)}</b>`;
  // 只有拿到金额（账户页）才提「赚了多少钱」；基金检索页没有金额，别拿空映射求和冒充 ¥0
  const HASM = Object.keys(MDAY).length + Object.keys(MMO).length + Object.keys(MYE).length > 0;
  const mItem = (k, v) => HASM && ok(v) ? `<span>${k}</span><b style="color:${color(v)}">${money(v)}</b>` : '';
  const sumM = obj => { const ks = Object.keys(obj); return ks.length ? ks.reduce((a, k) => a + (ok(obj[k]) ? obj[k] : 0), 0) : null; };
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
          html += cell(String(d), D.day[key], mx, key === D.today ? 'today' : '', '', key, MDAY[key]);
        }
        grid.style.gridTemplateColumns = 'repeat(7,minmax(0,1fr))';
        // 当月赚的钱 = 这个月每一格的「钱」加起来
        const mk = Object.keys(MDAY).filter(k => k.startsWith(`${y}/${p2(m)}/`));
        const mSum = mk.length ? mk.reduce((a, k) => a + (ok(MDAY[k]) ? MDAY[k] : 0), 0) : null;
        s = `<span class="sum-k">${y}年${m}月</span>` + item('当月涨跌', mv) + mItem('当月赚了', mSum)
          + cnt('上涨', vals.filter(v => v > 0).length, '天') + cnt('下跌', vals.filter(v => v < 0).length, '天')
          + (vals.length ? item('最大单日涨', Math.max(...vals)) + item('最大单日跌', Math.min(...vals)) : '');
      } else {
        const ms = `${y}/${p2(m)}/01`, me = `${y}/${p2(m)}/${p2(nd)}`;
        const wk = D.week.filter(w => w.e >= ms && w.s <= me), mx = maxAbs(wk.map(w => w.v));
        html = wk.map((w, k) => cell(`第${k + 1}周`, w.v, mx, '', `${w.s.slice(5)} – ${w.e.slice(5)}`, `${w.s} — ${w.e}`, w.m)).join('')
          || '<div class="cal-cell none"><span class="k">本月暂无完整周数据</span><span class="v">—</span></div>';
        grid.style.gridTemplateColumns = 'repeat(auto-fill,minmax(150px,1fr))';
        s = `<span class="sum-k">${y}年${m}月</span>` + item('当月涨跌', mv)
          + mItem('当月赚了', wk.some(w => ok(w.m)) ? wk.reduce((a, w) => a + (ok(w.m) ? w.m : 0), 0) : null)
          + cnt('共', wk.length, '周')
          + cnt('上涨', wk.filter(w => w.v > 0).length, '周') + cnt('下跌', wk.filter(w => w.v < 0).length, '周');
      }
    } else if (mode === '月') {
      const vals = []; for (let k = 1; k <= 12; k++) vals.push(D.month[`${yy}-${p2(k)}`]);
      const mx = maxAbs(vals);
      html = vals.map((v, k) => cell(`${k + 1}月`, v, mx, '', '', `${yy}年${k + 1}月`,
        MMO[`${yy}-${p2(k + 1)}`])).join('');
      grid.style.gridTemplateColumns = 'repeat(6,minmax(0,1fr))';
      const got = vals.map((v, k) => [k + 1, v]).filter(t => ok(t[1]));
      const best = got.reduce((a, t) => !a || t[1] > a[1] ? t : a, null), worst = got.reduce((a, t) => !a || t[1] < a[1] ? t : a, null);
      const mk2 = Object.keys(MMO).filter(k => k.startsWith(`${yy}-`));
      const mSum = mk2.length ? mk2.reduce((a, k) => a + (ok(MMO[k]) ? MMO[k] : 0), 0) : null;
      s = `<span class="sum-k">${yy}年</span>` + item('全年涨跌', D.year[String(yy)]) + mItem('全年赚了', mSum)
        + cnt('上涨', got.filter(t => t[1] > 0).length, '个月') + cnt('下跌', got.filter(t => t[1] < 0).length, '个月')
        + (best ? item(`最好 ${best[0]}月`, best[1]) + item(`最差 ${worst[0]}月`, worst[1]) : '');
    } else {
      const ys = Object.keys(D.year).sort(), vals = ys.map(y => D.year[y]), mx = maxAbs(vals);
      html = ys.map(y => cell(`${y}年`, D.year[y], mx, '', '', `${y}年`, MYE[y])).join('');
      grid.style.gridTemplateColumns = 'repeat(6,minmax(0,1fr))';
      const got = ys.map(y => [y, D.year[y]]);
      const best = got.reduce((a, t) => !a || t[1] > a[1] ? t : a, null), worst = got.reduce((a, t) => !a || t[1] < a[1] ? t : a, null);
      s = cnt('共', ys.length, '年') + mItem('合计赚了', sumM(MYE))
        + cnt('上涨', got.filter(t => t[1] > 0).length, '年') + cnt('下跌', got.filter(t => t[1] < 0).length, '年')
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


def _pf_detail(it: dict, inline: bool = False) -> None:
    """点开一只基金：上面是它自己的数字，下面是「买卖点 / 累计盈亏」两个子页签。

    inline=True 时是「就地展开」：上下两段列表之间，紧贴被点的那一行，不再是一张独立卡片。
    收起不再由这里负责 —— 调用方把它挂在「再点一下这一行」上。
    """
    code = it["code"]
    name = str(it["f"].get("name") or FL.fund_name(code) or code)
    shares, px, cost = it["shares"], it["px"], it["cost"]
    held = shares > 0
    day, _ = _pf_day(it)
    hold = it["mv"] - shares * cost
    hold_pct = it["pl"] * 100 if it["pl"] is not None else None
    qty = (f"{shares:,.2f} 份" if it["otc"] else f"{shares:,.0f} 股") if held else "未持有"
    _cells = [
        ("金额", f"¥{it['mv']:,.0f}", ""),
        ("今日收益", _pf_num(day, 2) if held else "—", _pf_sign(day) if held else ""),
        ("持有收益", _pf_num(hold) if held else "—", _pf_sign(hold) if held else ""),
        ("持有收益率", (f"{_pf_num(hold_pct, 2)}%" if (held and hold_pct is not None) else "—"),
         _pf_sign(hold) if held else ""),
        ("份额 / 股数", qty, ""),
        ("成本 / 净值", f"{cost:.4f} / {px:.4f}" if cost > 0 else f"— / {px:.4f}", ""),
    ]
    st.markdown(
        '<div class="pf-detail' + (' inline' if inline else '') + '">'
        '<div class="pd-top"><div>'
        f'<div class="pd-name">{html_escape(name)}</div>'
        f'<div class="pd-sub">{code} · {"场外" if it["otc"] else "场内"} · '
        f'{html_escape(HG.SLOT_LABEL.get(it["slot"], it["slot"]))}</div>'
        '</div>' + (f'<span class="pf-badge warn">{html_escape(it["why"])}</span>'
                    if it.get("why") else _pf_badge(it)) + '</div>'
        '<div class="pd-grid">'
        + "".join(f'<div><div class="k">{k}</div><div class="v {c}">{v}</div></div>'
                  for k, v, c in _cells)
        + '</div></div>',
        unsafe_allow_html=True,
    )

    _tr = _code_trades(code)
    # 用 _nav_of_code 而不是 _hg_panel：位置关掉／配置删掉的基金不在面板里，但它们自己仍然有净值
    _ser = _nav_of_code(code)
    if not held:
        _cl = [r for r in _closed_rounds() if r["code"] == code]
        if _cl:
            st.caption(f"这一只已经清仓（最近一次 {_cn_date(_cl[0]['close'])}，"
                       f"当时累计 {_pf_num(float(_cl[0]['pnl'] or 0), 2)} 元）—— "
                       "清仓那天赚了多少、拿了多久、期间最高最低，都在页面下方「已清仓」里。")

    # 子页签：一行里切换看买卖点还是累计盈亏。
    # 不再给「收起」按钮 —— 再点一下上面那行基金名就是收起，两个入口做同一件事只会让人犹豫。
    _sub = st.segmented_control(
        "看这只基金的", ["买卖点", "累计盈亏"], default="买卖点", key="pf_sub",
        label_visibility="collapsed",
        help="买卖点＝净值走势上标出每一笔买入/卖出；累计盈亏＝这只基金从第一笔到现在的累计赚亏（元）。",
    ) or "买卖点"

    if _sub == "买卖点":
        if len(_ser) < 2:
            st.info("这只基金还没有净值数据，拉取后才有走势图（页底「拉取缺的净值」）。")
        else:
            _hist = _trend_chart_data(_ser)
            _d = _hist["日"]
            st.iframe(
                _scroll_chart_html(_d["labels"], _d["prices"], _d["windows"]["近1年"]["count"],
                                   rets=_d["rets"], histories=_hist, trades=_tr,
                                   store="awTrend.fund", default_range="近1年",
                                   heading="",   # 子页签已经写着「买卖点」，图里再写一遍就是重复
                                   # 画布高度要算上页头/控件/状态行那 260px，否则 700 的框里
                                   # 只有 440 可见，最下面那条涨跌幅栏会被裁掉
                                   height=440),
                height=700,
            )
            if _tr:
                st.caption(f"红三角＝买入、绿三角＝卖出（这只基金共 {len(_tr)} 笔），"
                           "悬停或点一下净值线能看到每笔的份额与成交净值。")
            else:
                st.caption("这只基金还没有买卖成交 —— 在「交易记录」补录后，"
                           "图上就会出现三角标记。")
    else:
        # 累计盈亏：换成「元」来看赚了多少，口径与支付宝「累计盈亏」一致。
        # 只要有两个交易日就画 —— 哪怕曲线是一条平的，那也是「这一笔到现在赚了多少」的真实答案，
        # 换成一句「数据太少」反而让人以为没算。
        _pnl = _code_pnl_curve(code)
        _tr_days = []
        for _t in ((acct or {}).get("trades") or []):
            if str(_t.get("code") or "") != code or _t.get("side") not in ("买入", "卖出"):
                continue
            try:
                _tr_days.append(pd.Timestamp(_t["date"]))
            except Exception:  # noqa: BLE001 - 日期写坏了就跳过这一笔
                continue
        _tr_days.sort()

        if len(_pnl) > 1:
            # 只有十几天记录时图矮一点：曲线是一条平的，高画布只剩下大片空面积。
            # 画布高度要单独传给图（默认 200），iframe 还得加上页头/控件/状态行那 160px，
            # 否则横轴那排日期会被框底切掉。
            _pnl_h = 460 if len(_pnl) > 20 else 300
            st.iframe(_pnl_chart_html(_pnl, trades=_tr, store="awPnl.fund",
                                      default_range="全部", heading="",
                                      height=_pnl_h), height=_pnl_h + 160)
            st.caption("累计盈亏 = 手上还拿着的浮盈 + 已经卖出落袋的实盈（买入算手续费、卖出扣手续费），"
                       "所以卖掉之后曲线不会掉下来；零轴以上填红＝赚、以下填绿＝亏，三角是这只基金的买卖点。"
                       "上面的「持有收益」只算手上这一部分，两者差多少，就是已经卖掉的那部分赚到（或亏掉）的钱。"
                       + (f"这只基金目前只有 {len(_pnl)} 个交易日的记录（第一笔 "
                          f"{_pnl.index[0].strftime('%Y/%m/%d')}），曲线会随着持有天数慢慢长起来。"
                          if len(_pnl) <= 5 else ""))
        elif len(_pnl) == 1 and _tr_days:
            # 只有一个点。这时说「缺净值」是错的 —— 净值是有的，只是最新那根就停在成交那天，
            # 再往后还没有新净值。用户看到上面「今日收益 / 成本净值」都有数，自然会问「为啥还是空」。
            _d0, _v0, _first = _pnl.index[0], float(_pnl.iloc[-1]), _tr_days[0]
            if len(_ser) and _ser.index[-1] < _first:
                st.caption(f"累计盈亏还没起算：这只基金的净值最新只到 {_cn_date(_ser.index[-1])}，"
                           f"比第一笔成交（{_cn_date(_first)}）还早 —— 成交那天的净值还没出来。"
                           "点右上角「更新数据」拉一次，或等这个净值日出来，曲线就从那天开始。")
            else:
                _v_cls = "up" if _v0 > 0.005 else ("down" if _v0 < -0.005 else "")
                st.markdown(
                    '<div class="pf-summary quiet">'
                    f'<span class="lead">累计盈亏 <b class="{_v_cls}">{_pf_num(_v0, 2)}</b></span>'
                    f'<span class="item">净值最新 {_cn_date(_d0)}</span>'
                    '<span class="item">只有 1 个净值点，还画不成曲线</span></div>',
                    unsafe_allow_html=True)
                st.caption(f"净值停在 {_cn_date(_d0)}（就是第一笔成交那天），之后还没有新的净值 —— "
                           "下一个净值日出来，曲线才会从这一点往上（或往下）长。"
                           "所以现在看到的不是一个空图，是「到今天为止只走了这一步」。")
        elif _tr:
            st.caption("累计盈亏要等有净值数据才能画：这只基金缺净值，拉取后自动出现。")
        else:
            st.caption("这只基金还没有成交，累计盈亏是 0。")

    # 逐笔成交流水不在这里重复一遍：只报个数并指路，「交易记录」页可以按基金筛出全部记录就地改
    _mine_tr = [t for t in ((acct or {}).get("trades") or [])
                if str(t.get("code") or "") == code]
    if _mine_tr:
        _nb = sum(1 for t in _mine_tr if t.get("side") == "买入")
        _ns = sum(1 for t in _mine_tr if t.get("side") == "卖出")
        _amt_b = sum(float(t.get("shares") or 0) * float(t.get("nav") or 0)
                     + float(t.get("fee") or 0)
                     for t in _mine_tr if t.get("side") == "买入")
        _amt_s = sum(float(t.get("shares") or 0) * float(t.get("nav") or 0)
                     - float(t.get("fee") or 0)
                     for t in _mine_tr if t.get("side") == "卖出")
        st.caption(f"这只基金一共 {len(_mine_tr)} 笔成交（买 {_nb} · 卖 {_ns}）："
                   f"累计买入 ¥{_amt_b:,.0f}、卖出 ¥{_amt_s:,.0f}。"
                   "要逐笔看或改动，去「交易记录」页顶上选这只基金 —— 那里能把它的记录全筛出来，"
                   "日期 / 金额 / 单价都可以就地改。")

# ============================================================
# 已清仓：份额归零的那一轮，赚了多少、拿了多久 —— 从成交记录还原，不依赖基金是否还在配置里
# ============================================================
_CL_LIST_CSS = r"""
:host{display:block}
.tbl{font:13px/1.5 -apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans SC","Microsoft YaHei",sans-serif;
  color:#0F172A;background:#fff;border:1px solid #E2E8F0;border-radius:14px;overflow:auto;max-height:330px}
.hd,.rw{display:grid;grid-template-columns:minmax(0,2.2fr) 104px 74px 112px 92px;gap:10px;
  align-items:center;padding:10px 14px}
.hd{background:#F8FAFC;border-bottom:1px solid #E2E8F0;font-size:12px;color:#64748B;
  position:sticky;top:0;z-index:2}
.hd .r{text-align:right}
.rw{border-bottom:1px solid #F1F5F9;cursor:pointer;transition:background .12s}
.rw:last-child{border-bottom:0}
.rw:hover{background:#F8FAFC}
.rw:focus-visible{outline:2px solid #3B82F6;outline-offset:-2px}
.rw.on{background:#EFF6FF;box-shadow:inset 3px 0 0 #3B82F6}
.nm{font-size:13.5px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sub{font-size:11.5px;color:#94A3B8;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.num{text-align:right;font-variant-numeric:tabular-nums;font-size:13px;font-weight:600}
.num .sub{font-weight:400;opacity:.78;color:inherit}
.mid{text-align:right;font-variant-numeric:tabular-nums;font-size:13px;color:#475569}
.up{color:#C52828}
.down{color:#16703B}
@media(max-width:900px){
  .hd,.rw{grid-template-columns:minmax(0,1fr) 96px 88px;padding:9px 12px;gap:8px}
  .c-day,.c-days{display:none}
}
"""

_CL_LIST_JS = r"""
export default function (c) {
  const { data, setStateValue, parentElement } = c;
  const D = data || {};
  Array.from(parentElement.children).forEach(el => {
    if (el && el.classList && el.classList.contains('tbl')) el.remove();
  });
  const rows = D.rows || [], sel = D.selected || '';
  const esc = s => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const rowHtml = r => '<div class="rw' + (r.key === sel ? ' on' : '') + '" role="row" tabindex="0"'
    + ' data-key="' + esc(r.key) + '">'
    + '<div class="c-name"><div class="nm">' + esc(r.name) + '</div>'
    + '<div class="sub">' + esc(r.sub) + '</div></div>'
    + '<div class="mid c-day">' + esc(r.close) + '</div>'
    + '<div class="mid c-days">' + esc(r.days) + '</div>'
    + '<div class="num ' + esc(r.cls) + '">' + esc(r.pnl) + '</div>'
    + '<div class="num ' + esc(r.cls) + '">' + esc(r.ret) + '</div>'
    + '</div>';
  const root = document.createElement('div');
  root.className = 'tbl';
  root.setAttribute('role', 'table');
  root.innerHTML = '<div class="hd"><div>已清仓的基金</div><div class="r c-day">清仓日</div>'
    + '<div class="r c-days">持有</div><div class="r">累计盈亏</div><div class="r">收益率</div></div>'
    + rows.map(rowHtml).join('');
  parentElement.appendChild(root);
  root.querySelectorAll('.rw').forEach(el => {
    const pick = () => { if (el.dataset.key !== sel) setStateValue('picked', el.dataset.key); };
    el.addEventListener('click', pick);
    el.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); }
    });
  });
  return () => root.remove();
}
"""

_CL_LIST = st.components.v2.component("aw_closed_list", css=_CL_LIST_CSS, js=_CL_LIST_JS)


def _cl_list(rows: list[dict], key: str = "cl_list"):
    """渲染已清仓列表并返回选中那一轮的 key（code@清仓日）；没点过就选第一行。"""
    if not rows:
        return None
    keys = [r["key"] for r in rows]
    _state = st.session_state.get(key)
    picked = _state.get("picked") if isinstance(_state, dict) else None
    if picked not in keys:
        picked = keys[0]
    res = _CL_LIST(key=key, data={"rows": rows, "selected": picked},
                   default={"picked": picked}, on_picked_change=lambda: None)
    out = res.get("picked") if hasattr(res, "get") else None
    return out if out in keys else picked


def _closed_rounds() -> list[dict]:
    """已清仓的持仓轮次，最近的排前面；`seq` 是这只基金第几次清仓（按时间正序数）。"""
    if not acct:
        return []
    _seq: dict[str, int] = {}
    out = []
    for r in _acct_rounds(acct.get("trades") or []):
        if not r["closed"]:
            continue
        _seq[r["code"]] = _seq.get(r["code"], 0) + 1
        out.append({**r, "seq": _seq[r["code"]]})
    return sorted(out, key=lambda x: (x["close"] or "", x["code"]), reverse=True)


def _closed_section() -> None:
    """「我的账户 · 持仓」底部的已清仓区块：一轮一行，点开看当时的盈亏曲线与成交。"""
    _rows_all = _closed_rounds()
    if acct is None:
        return
    _sum = sum(float(r["pnl"] or 0) for r in _rows_all)
    _sum_col = "#C52828" if _sum > 0.005 else ("#16703B" if _sum < -0.005 else "#475569")
    _head_right = (f'{len(_rows_all)} 轮 · 累计兑现 '
                   f'<b style="color:{_sum_col};font-variant-numeric:tabular-nums">'
                   f'{_pf_num(_sum, 2)}</b> 元') if _rows_all else "还没有清仓过"
    st.markdown(
        '<div class="sec-head"><span class="t">已清仓</span>'
        f'<span class="r">{_head_right}</span></div>',
        unsafe_allow_html=True,
    )
    if not _rows_all:
        st.caption("卖出后份额归零，那一轮就会自动记到这里：清仓日、持有天数、清仓当时的累计盈亏都留着，"
                   "不用事后自己记。")
        return
    st.caption("卖出后份额归零就算清仓（卖了又买是新的一轮）：这里留着清仓那天赚了多少、拿了多久，"
               "点一行看当时的走势与成交。清仓不影响账户总资产，钱已经回到现金里。")
    _cfg_codes = set(HG.all_codes(holdings))
    _rows = [{
        "key": f'{r["code"]}@{r["close"]}',
        "name": FL.fund_name(r["code"]) or r["code"],
        "sub": f'{r["code"]} · 第 {r["seq"]} 次清仓'
               + (" · 仍在配置里" if r["code"] in _cfg_codes else ""),
        "close": _cn_date(r["close"]),
        "days": f'{r["days"]} 天',
        "pnl": _pf_num(float(r["pnl"] or 0), 2),
        "ret": (f'{r["ret"] * 100:+.2f}%' if r["ret"] is not None else "—"),
        "cls": _pf_sign(float(r["pnl"] or 0)),
    } for r in _rows_all]
    _picked = _cl_list(_rows)
    _sel = next((r for r in _rows_all if f'{r["code"]}@{r["close"]}' == _picked), None)
    if _sel:
        _cl_detail(_sel)


def _cl_detail(r: dict) -> None:
    """一次清仓的「当时的场景」：清仓时累计盈亏、收益率、持有天数、曲线（标清仓日）、那一轮的成交。"""
    code = r["code"]
    name = FL.fund_name(code) or code
    _pnl_v, _ret = float(r["pnl"] or 0), r["ret"]
    _meta = HG.fund_meta(holdings, code)[1]
    _in_cfg = bool(_meta)
    _cells = [
        ("清仓时累计盈亏", f"¥{_pnl_v:+,.2f}", _pf_sign(_pnl_v)),
        ("累计收益率", (f"{_ret * 100:+.2f}%" if _ret is not None else "—"),
         _pf_sign(_ret or 0)),
        ("投入成本", f"¥{r['buy_amount']:,.0f}", ""),
        ("卖出回收", f"¥{r['sell_amount']:,.0f}", ""),
        ("持有天数", f"{r['days']} 天", ""),
        ("手续费", f"¥{r['fee']:,.2f}", ""),
    ]
    st.markdown(
        '<div class="pf-detail is-closed">'
        '<div class="pd-top"><div>'
        f'<div class="pd-name">{html_escape(name)}</div>'
        f'<div class="pd-sub">{code} · 建仓 {_cn_date(r["open"])} → 清仓 {_cn_date(r["close"])} · '
        f'第 {r["seq"]} 次清仓 · {r["buy_n"]} 买 / {r["sell_n"]} 卖'
        f'{" · 仍在配置里" if _in_cfg else " · 已不在配置里"}</div>'
        '</div><span class="pf-badge hold">已清仓</span></div>'
        '<div class="pd-grid">'
        + "".join(f'<div><div class="k">{k}</div><div class="v {c}">{v}</div></div>'
                  for k, v, c in _cells)
        + '</div></div>',
        unsafe_allow_html=True,
    )

    # 这一轮的成交（同一只基金清仓多次时，只取这一轮的日期区间）
    _o, _c = pd.Timestamp(r["open"]), pd.Timestamp(r["close"])
    _mine = []
    for t in ((acct or {}).get("trades") or []):
        if str(t.get("code") or "") != code or t.get("side") not in ("买入", "卖出"):
            continue
        try:
            _d = pd.Timestamp(t.get("date"))
        except Exception:  # noqa: BLE001
            continue
        if _o <= _d <= _c:
            _mine.append(t)
    _tr = _code_trades(code)
    _curve = _code_pnl_curve(code)
    if len(_curve) > 1:
        _win = _curve.loc[_o:_c]
        _hi, _lo = float(_win.max()), float(_win.min())
        st.iframe(_pnl_chart_html(_curve, trades=_tr, store="awPnl.closed",
                                  default_range="全部", mark=_cn_date(r["close"]),
                                  mark_label="清仓"), height=380)
        st.caption(
            f"竖虚线是 {_cn_date(r['close'])} 清仓那天：之后份额是 0，曲线停在已经落袋的钱上不再变。"
            f"持有期间累计盈亏最高 ¥{_hi:+,.0f}（{_cn_date(_win.idxmax())}）、"
            f"最低 ¥{_lo:+,.0f}（{_cn_date(_win.idxmin())}）—— 和清仓时的数字差多少，就是没卖在最高点的那部分。")
    else:
        _nav = _nav_of_code(code)
        if not len(_nav):
            st.caption("这只基金还没有净值数据，画不出曲线；上面的数字是按成交净额算的，仍然准确。")
        else:
            st.caption(f"这只基金的净值只更新到 {_cn_date(_nav.index[-1])}，"
                       f"清仓那天（{_cn_date(r['close'])}）的净值还没到，曲线暂时只有一个点 —— "
                       "等净值更新到那天就会画出来。上面的数字是按成交金额算的，仍然准确。")

    if _mine:
        _unit = (_meta.get("unit") if _meta else None) or HG.default_unit(code)
        _rows = []
        for t in _mine:
            _side = t.get("side") or "—"
            _cls = "buy" if _side == "买入" else "sell"
            _q = (f"{float(t.get('shares', 0)):,.2f} 份" if _unit == "份额"
                  else f"{float(t.get('shares', 0)):,.0f} 股")
            _rows.append([
                _cn_date(t.get("date")),
                f'<span class="pf-badge {_cls}">{_side}</span>',
                _q,
                f'{float(t.get("nav", 0)):.4f}' if float(t.get("nav", 0) or 0) > 0 else "—",
                f'{float(t.get("fee", 0)):,.2f}' if float(t.get("fee", 0) or 0) else "—",
            ])
        st.markdown(f"**这一轮的成交（{len(_rows)} 笔）**")
        _render_table([("日期", "left"), ("类型", "left"), ("数量", "right"),
                       ("成交净值", "right"), ("手续费", "right")], _rows)


# ============================================================
# Hero
# ============================================================
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
    # 原来这里挂着一个「N 个信号触发」的 chip，等于在每一页顶上再标一次信号 ——
    # 策略信号只有「模型 · 信号」页一处，这里不再重复，只留「更新数据」。
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


def _hg_slot_options():
    """记账下拉选项：每**只基金**一项，value=(位置, 代码)，显示「位置 · 代码 名称」。

    一个位置挂多只时这里就有多行 —— 成交必须记到具体那一只基金上。
    末尾补上「账上还有份额、但配置里已经删掉」的代码：不然「我的账户」提示你
    「想卖就到交易记录记一笔卖出」，而这里根本选不到它（提示指向的操作做不到）。
    """
    out = []
    off = []
    for s in HG.SLOTS:
        _on = bool(holdings.get(s, {}).get("on", True))
        for f in HG.funds(holdings.get(s, {})):
            _lb = f'{HG.SLOT_LABEL[s]} · {f["code"]} {f.get("name") or ""}'.strip()
            if not _on:
                _lb += "（位置已关闭）"
            (out if _on else off).append((s, f["code"], _lb))
    # 参与调仓的排前面：默认选中项不该是「已关闭位置」的基金（第一版就是这样，很容易记错）
    out += off
    _cfg_codes = {c for _s, c, _lb in out}
    for _c, _sh in (_acct_pos or {}).items():
        if _c in _cfg_codes or float(_sh or 0) <= 0:
            continue
        out.append(("", _c, f'已删除的位置 · {_c} {FL.fund_name(_c) or ""}'.strip()))
    return out


def _held_on(trades: list, code: str, day, skip: int | None = None) -> float:
    """按日期重放，算某只基金到 `day`（含当天）为止持有多少份。

    只用于记账前的「别卖超过持有」校验，所以按成交日期字符串排序累加即可，
    精度要求不高；`skip` 是编辑某笔时要排除的那一行。"""
    held = 0.0
    for i, t in enumerate(trades or []):
        if skip is not None and i == skip:
            continue
        if str(t.get("code") or "") != str(code or ""):
            continue
        if str(t.get("date") or "") > str(day):
            continue
        side = t.get("side")
        if side == "买入":
            held += float(t.get("shares") or 0)
        elif side == "卖出":
            held -= float(t.get("shares") or 0)
    return held
# ============================================================
# 三类提醒一次算完、分头显示
# 原来独占一个「提醒」tab，内容和 帮你算（偏离）、收益对比（体检）、指数估值（估值）三页重复，
# 用户看不懂它是干嘛的 → 拆开贴到对应页面，不再单独占一个 tab
# ============================================================
def _alert_card(level, title, body, tip=""):
    _cls = {"urgent": "warn", "warn": "warn", "info": "", "ok": "calm"}.get(level, "")
    _tip = f'<div class="m">{tip}</div>' if tip else ""
    return (f'<div class="sig {_cls}"><div class="main"><div class="t">{title}</div>'
            f'<div class="m">{body}</div>{_tip}</div></div>')


def _alerts_compute() -> dict:
    """偏离 / 估值 / 体检三类提醒，一次算完供三个页面各自取用。"""
    _val_by_code = {}
    try:
        from allweather import valuation as _VAL
        _snap = _VAL.load_snapshot()
        if not _snap.empty:
            for _r in _snap.to_dict("records"):
                _dd = _VAL.drawdown_10y(_r["代码"])
                _tot, _vs, _ps, _lb = _VAL.score(_r["PE百分位"], _r["PB百分位"], _dd)
                _val_by_code[str(_r["代码"])] = {
                    "name": _r["名称"],
                    "pe_pct": _r["PE百分位"] if pd.notna(_r["PE百分位"]) else None,
                    "pb_pct": _r["PB百分位"] if pd.notna(_r["PB百分位"]) else None,
                    "score": _tot, "label": _lb,
                    "asof": f'{pd.Timestamp(_snap["数据日"].max()):%Y/%m/%d}',
                }
    except Exception:  # noqa: BLE001
        _val_by_code = {}

    _bench = {}
    if acct is not None and len(_acct_daily) > 1:
        _bd = BM.replay_target(w, acct.get("created"), nav_getter=HG.nav_series)
        if len(_bd) > 1:
            _bench["项目默认基金"] = _bd
        _bs = BM.strategy_curve(_BENCH_COL.get(acct.get("strategy"), ""), start=acct.get("created"))
        if _bs is not None and len(_bs) > 1:
            _bench["策略理论"] = _bs

    _nav_latest = {}
    for _c in HG.all_codes(holdings):
        if _c in _hg_panel.columns:
            _col = _hg_panel[_c].dropna()
            if len(_col):
                _nav_latest[_c] = float(_col.iloc[-1])

    return AL.compute(
        mv=_hg_mv, target_w=_hg_w, holdings=holdings, slot_label=HG.SLOT_LABEL,
        val_by_code=_val_by_code, daily=_acct_daily if acct is not None else None,
        cash=float(_acct_cash or 0), pos=_acct_pos if acct is not None else {},
        cost=_acct_cost if acct is not None else {}, bench=_bench,
        slot_of_code=lambda c: HG.slot_of(c, holdings),
        nav_by_code=_nav_latest,
    )


_al = _alerts_compute()

# ============================================================
# 每个位置挂哪只基金 —— 属于「设置」，跟着目标权重一起看
# 持仓页只回答「有什么、赚多少」，不再混着配置表
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
    """把 (slot → (code, name)) 写成该位置**唯一**的一只基金（"全部填入参考代码"用）。

    换基金时同步判断买卖单位：场内代码（5xxxxx 沪市 ETF/LOF、1xxxxx 深市、
    0xxxxx 深市股票型）按股，其余（场外基金，如 110020）按份额申购。
    """
    new = {s: HG._norm_slot(holdings.get(s)) for s in HG.SLOTS}
    for s, (code, name) in code_map.items():
        _slot = new.get(s) or HG._norm_slot({})
        _prev = next((f for f in HG.funds(_slot) if f["code"] == code), {})
        _unit = HG.default_unit(code)                  # 场内「股」/ 场外「份额」
        new[s] = {"on": _slot.get("on", True), "funds": [HG._fund({
            "code": code,
            "name": name or (FL.fund_name(code) or code),
            "unit": _unit,
            "lot": int(_prev.get("lot") or (100 if _unit == "股" else 1)),
            "min_amount": float(_prev.get("min_amount") or 1.0),
            "share": 1.0,
        })]}
    HG.save(new)
    return new


def _slot_config_panel() -> None:
    """给位置挂基金 / 改买卖单位 / 开关位置：低频设置，收在权重页底部一个展开里。"""
    st.divider()
    with st.expander("每个位置挂什么基金（加 / 换 / 移除 · 买卖单位 · 开关位置）",
                     expanded=True):
        st.caption(
            "这里回答的是「某个位置**用哪只基金**去实现」，跟上面的目标权重是两件事："
            "权重由策略算（项目自带），挂哪只看你自己。"
            "一个位置可以挂多只同类基金，也可以一只都不挂；挂多只时按「占比」分该位置的目标金额"
            "（留空或全 0 就是等权），一只都不挂 = 这个位置暂时不投，权重会按同桶比例让给别的位置。"
        )
        # 加基金后要让搜索框回到空态：key 里带版本号，换号即重建组件（直接 pop 已渲染的 widget key 会报错）
        _add_ver = int(st.session_state.get("hg_add_ver", 0))
        _pending_add, _pending_on = {}, {}
        # 一行两个位置、从左到右念。原来按列填（1/3/5/7 在左、2/4/6/8 在右），
        # 两列卡片高度不一样就互相错开，看着像整页错位
        _slot_list = list(HG.SLOTS)
        for _r0 in range(0, len(_slot_list), 2):
            _row_cols = st.columns(2, gap="medium")
            for _c, _s in zip(_row_cols, _slot_list[_r0:_r0 + 2]):
                _h = holdings.get(_s, {})
                _fs_ = HG.funds(_h)
                with _c, st.container(border=True):
                    _c1, _c2 = st.columns([2.4, 1], vertical_alignment="center")
                    _c1.markdown(f"**{HG.SLOT_LABEL[_s]}**")
                    with _c2:
                        _on_now = bool(_h.get("on", True))
                        _on_new = st.toggle("参与", value=_on_now, key=f"hg_on_{_s}",
                                            help="关掉后这个位置不参与建仓/调仓/提醒，权重让给同桶别的位置")
                        if _on_new != _on_now:
                            _pending_on[_s] = _on_new
                    if _fs_:
                        # 一行一只基金：代码 / 名称 / 占比，占比右对齐才扫得动
                        _sh_ = HG.share_of(_h)
                        st.markdown(
                            '<div class="flist">' + "".join(
                                f'<div class="frow"><span class="fc">{f["code"]}</span>'
                                f'<span class="fn">{f.get("name") or FL.fund_name(f["code"]) or ""}</span>'
                                f'<span class="fp">{x * 100:.0f}%</span></div>'
                                for f, x in zip(_fs_, _sh_)) + '</div>',
                            unsafe_allow_html=True)
                    else:
                        st.markdown('<div class="flist"><span class="none">未挂基金 · 这个位置不持有</span></div>',
                                    unsafe_allow_html=True)
                    _picked = FS.fund_search(
                        f"hg_add_{_s}_{_add_ver}", mode="single", default=None,
                        placeholder="搜索基金，加到这一位置（可多次加不同基金）",
                    )
                    if _picked and str(_picked) not in HG.codes(_h):
                        _pending_add[_s] = str(_picked)

        if _pending_add or _pending_on:
            _new = {s: HG._norm_slot(holdings.get(s)) for s in HG.SLOTS}
            for _s, _c in _pending_add.items():
                if _c:
                    _new[_s] = HG.add_fund(_new[_s], _c, FL.fund_name(_c) or _c)
            for _s, _onv in _pending_on.items():
                _new[_s]["on"] = _onv
            HG.save(_new)
            st.session_state["hg_add_ver"] = _add_ver + 1
            st.rerun()

        # 一只基金一行：单位/每手/最低金额/占比可改，「移除」勾上保存即删
        _rows_cfg = []
        for _s in HG.SLOTS:
            _h = holdings.get(_s, {})
            for _f, _x in zip(HG.funds(_h), HG.share_of(_h)):
                _code = _f["code"]
                _col = _hg_panel[_code].dropna() if _code in _hg_panel.columns else pd.Series(dtype=float)
                _rows_cfg.append({
                    "位置": HG.SLOT_LABEL[_s],
                    "代码": _code,
                    "我的基金": _f.get("name") or FL.fund_name(_code) or "—",
                    "买卖单位": _f.get("unit", "股"),
                    "每手": int(_f.get("lot") or 1),
                    "最低申购金额": float(_f.get("min_amount") or 1.0),
                    "占比%": round(_x * 100, 2),
                    "净值": round(float(_col.iloc[-1]), 4) if len(_col) else None,
                    "移除": False,
                    "_slot": _s,
                })

        if not _rows_cfg:
            st.info("还没有挂任何基金 —— 用上面的搜索框加一只，或点下面的「恢复项目默认代码」。")
            _edited = None
        else:
            _edited = st.data_editor(
                pd.DataFrame(_rows_cfg),
                column_config={
                    "位置": st.column_config.TextColumn("位置", disabled=True),
                    "代码": st.column_config.TextColumn("代码", disabled=True,
                                                       help="用上方搜索框加，勾「移除」再保存即删"),
                    "我的基金": st.column_config.TextColumn("我的基金", disabled=True),
                    "买卖单位": st.column_config.SelectboxColumn("买卖单位", options=["股", "份额"],
                                                             help="场内按股（100 股一手），场外按份额（按金额申购）"),
                    "每手": st.column_config.NumberColumn("每手/最小", min_value=1, step=1),
                    "最低申购金额": st.column_config.NumberColumn("最低申购(元)", min_value=1.0, step=1.0),
                    "占比%": st.column_config.NumberColumn("占该位置", min_value=0.0, max_value=100.0,
                                                          step=5.0, format="%.1f%%",
                                                          help="该位置内这只基金分到多少比例；同位置全部为 0 时按等权"),
                    "净值": st.column_config.NumberColumn(f"净值({_cn_date(_hg_last)})", format="%.4f",
                                                         disabled=True),
                    "移除": st.column_config.CheckboxColumn("移除", help="勾上→保存，这只基金就从该位置删掉"),
                    "_slot": None,
                },
                hide_index=True, width="stretch", key="hg_editor",
            )
            # 同一个面板里两套提交方式，不说清楚很容易「改完切页就没了」
            st.caption("这张表改完要点右下角「保存修改」才生效；上面的「参与」开关和搜索框是**立即生效**的。")

        # 只看「参与中」的位置：关闭的位置既不调仓也不定投，缺净值并不影响任何数字，
        # 把它们算进来只会让人以为一定要去拉 9 只基金的净值。
        _miss_codes = [c for c in dict.fromkeys(
            c for s in HG.active(holdings) for c in HG.codes(holdings[s]))
            if c not in _hg_panel.columns or not len(_hg_panel[c].dropna())]
        _off_codes = [c for s in HG.SLOTS if not holdings.get(s, {}).get("on", True)
                      for c in HG.codes(holdings.get(s, {}))]
        _miss = [f'{_c} {FL.fund_name(_c) or ""}'.strip() for _c in _miss_codes]
        if _miss:
            st.warning("这些基金还没有净值数据，拉取后建仓/调仓/提醒才能算：" + "；".join(_miss))
            if st.button("拉取缺的净值", key="hg_fetch_missing", type="primary"):
                st.toast("正在拉取净值…", icon=":material/sync:", duration="long")
                for _c in _miss_codes:
                    try:
                        FL.ensure_fresh(_c)
                    except Exception:  # noqa: BLE001
                        pass
                st.cache_data.clear()
                st.rerun()
        elif _off_codes:
            st.caption(f"另有 {len(set(_off_codes))} 只基金挂在已关闭的位置上，"
                       "不参与建仓/调仓/定投，缺不缺净值都不用管。")

        with st.container(horizontal=True, horizontal_alignment="right", gap="small"):
            if _edited is not None and st.button("保存修改", type="primary", key="hg_save"):
                _new = {s: HG._norm_slot(holdings.get(s)) for s in HG.SLOTS}
                _drop = []
                for r in _edited.to_dict("records"):
                    _s, _c = r.get("_slot"), r.get("代码")
                    if not _s or not _c:
                        continue
                    if r.get("移除"):
                        _drop.append((_s, _c))
                        continue
                    for _f in _new[_s]["funds"]:
                        if _f["code"] == _c:
                            _f["unit"] = r.get("买卖单位") or "股"
                            _f["lot"] = max(1, int(r.get("每手") or 1))
                            _f["min_amount"] = max(1.0, float(r.get("最低申购金额") or 1.0))
                            _f["share"] = max(0.0, float(r.get("占比%") or 0.0)) / 100
                for _s, _c in _drop:
                    _new[_s] = HG.remove_fund(_new[_s], _c)
                HG.save(_new)
                st.toast("持仓设置已保存", icon=":material/check_circle:")
                st.rerun()
            if st.button("恢复项目默认代码", key="hg_reset"):
                HG.save(HG._default_holdings())
                st.toast("已恢复为项目默认的 8 个代码", icon=":material/check_circle:")
                st.rerun()

        st.markdown("**换成场外（支付宝可买）同类基金 — 一键填入参考代码**")
        st.caption("下面是同类基金的参考代码，跟踪指数和费率不一定和原版一致，填入后请自己核对；"
                   "收益差异会在「我的账户 · 对比」里的「vs 项目默认基金」体现出来。"
                   "填入会把该位置**替换**成这一只（原来挂的多只会被清掉）。")
        _preset_rows = [[HG.SLOT_LABEL[s], ETF_META.get(s, {}).get("code", ""),
                         ETF_META.get(s, {}).get("name", ""), c, n] for s, c, n in _HG_PRESET]
        _render_table([("位置", "left"), ("原版代码", "left"), ("原版基金", "left"),
                       ("参考代码", "left"), ("参考基金", "left")], _preset_rows)
        if st.button("全部填入参考代码", key="hg_preset_all"):
            _hg_apply({s: (c, n) for s, c, n in _HG_PRESET})
            st.toast("已填入场外参考代码，请核对跟踪指数", icon=":material/check_circle:")
            st.rerun()


# ============================================================
# Main Tabs —— 前四页是「我的账户」（每天用），后四页是项目自带的策略模型（偶尔看）
# 「我的账户」一页管完：有什么（持仓）、赚了多少（收益）、跟谁比（对比）、有没有风险（体检）；
# 「帮你算」是**唯一**给出「该买多少、卖多少」的地方，而且只算不写账。
# ============================================================
tab3, tab5, tab_calc, tab7, tab2, tab1, tab8, tab10 = st.tabs(
    ["我的账户", "交易记录", "帮你算", "基金检索",
     "权重与选基", "模型 · 信号", "模型 · 回测", "指数估值"]
)

# ============================================================
# Tab 1: 信号仪表盘
# ============================================================
with tab1:
    st.caption("这一页是**项目自带策略模型**算出来的信号（估值分位、宏观季节、趋势过滤），"
               "跟你自己买了什么无关；你的钱这一轮该不该动，看「帮你算」页。")
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
# Tab 2: 权重与选基 —— 上半是策略给的目标权重，下半是我的基金配置
# ============================================================
with tab2:
    st.subheader("权重与选基 · 每个位置该占多少、我拿哪只基金去实现")
    st.caption(
        "上一半是**策略算的目标权重**（项目自带模型，跟你的账户无关）；"
        "下一半是**我实际挂的基金**——这就是你在支付宝里买的那几只。"
        "平时只看不动；换基金、加基金、开关位置都在页底展开里。"
    )
    st.markdown(f"**目标权重 · {cfg['name']} — {tier}% RP**")

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

    # ---- 下半：我的基金配置（原来挂在「我的持仓」页底，用户看不出它是干嘛的）----
    _slot_config_panel()

# ============================================================
# 我的账户 · 三个子视图（收益 / 对比 / 信号）—— 持仓视图直接在 tab3 里写完，本页最长
# ============================================================
def _my_funds_txt(slot: str | None) -> str:
    """位置 → 我实际买的基金，让「策略信号」能落到自己的账户上（不然只知道该卖 510880）。"""
    if not slot:
        return '<span class="muted">—</span>'
    label = HG.SLOT_LABEL.get(slot, slot)
    if not holdings.get(slot, {}).get("on", True):
        return f'<span class="muted">{label} · 位置已关闭</span>'
    fs = HG.funds(holdings.get(slot, {}))
    if not fs:
        return f'<span class="muted">{label} · 没挂基金</span>'
    return "、".join(f'{f.get("name") or f["code"]}<br><span class="muted">{f["code"]}</span>'
                    for f in fs)


def _pct_txt(v: float, digits: int = 2) -> str:
    """涨跌幅文案：小到 0.00% 以下时自动多留一位，避免「-0.00%」这种看着像出错的写法。"""
    p = v * 100
    d = digits + 1 if (p and abs(p) < 10 ** -digits) else digits
    return ("+" if p > 0 else "") + f"{p:.{d}f}%"


def _acct_period_view() -> None:
    """账户收益：先一条曲线、一本日历回顾，再按年 / 按月对账。

    三块各回答一个问题，不重复：
      曲线  = 一路走过来赚了多少（累计收益）/ 账户大到了多少（总资产）；
      日历  = 哪一天、哪一周、哪个月赚了或亏了多少（% 和钱并排）；
      分年表 = 年化、回撤这些只能按段算的数。
    """
    st.markdown(
        '<div class="sec-head"><span class="t">收益 · 账户赚了多少</span>'
        '<span class="r">曲线看走势 · 日历看每天 / 每周 / 每月 · 分年表看回撤</span></div>',
        unsafe_allow_html=True,
    )
    if acct is None or len(_acct_equity_series()) <= 1:
        st.info("账户还没有净值曲线：先在「交易记录」补录成交，之后这里自动按天算。")
        return
    # ① 曲线：累计收益（钱）/ 总资产（钱），一个切换看两条线 —— 一条答「赚了多少」，一条答「有多少」
    with st.container(key="acct_curve_switch"):
        _ck = st.segmented_control(
            "看哪条", ["累计收益", "账户总资产"], default="累计收益", key="acct_curve_kind",
            label_visibility="collapsed",
            help="累计收益＝总资产 − 累计净投入（转入转出不算收益），答「我到底赚了多少」；\n\n"
                 "账户总资产＝持仓市值 + 现金，答「账上现在有多少钱」。转入那天两条线会分开，那正是它们的分工。",
        ) or "累计收益"
    with st.container(key="acct_curve"):
        if _ck == "累计收益":
            st.iframe(_pnl_chart_html(_acct_pnl_series(), height=240, store="awAcctPnl",
                                      default_range="全部", heading="",
                                      sub="建仓以来累计（转入 / 转出不算收益）"),
                      height=400)
        else:
            st.iframe(_pnl_chart_html(_acct_equity_series(), height=240, store="awAcctEq",
                                      default_range="全部", heading="", area=False,
                                      sub="持仓市值 + 现金"),
                      height=400)
    st.caption("**累计收益 = 总资产 − 累计净投入**：转入那天钱变多了但收益不变，所以这条线在转入日不会跳。"
               "**总资产**在转入日会跳一格 —— 那个跳不是赚的。两条换着看，就知道「钱变多」有多少是赚的、多少是又打进来的。")

    # ② 收益日历：日 / 周 / 月 / 年，每格给收益率 + 那份钱
    _cal = _acct_calendar_payload()
    if _cal:
        st.iframe(_calendar_html(_cal), height="content")
        st.caption("日历里的 **%** 是账户单位净值的涨跌（转入按当天净值折份额，加钱不会抬高它），"
                   "**¥** 是这段时间真赚到的钱（已扣掉当天转入转出）。同一个月，钱多的账户同样的 % 会赚得更多。")
    else:
        st.caption("日历要有两个交易日以上的净值才画得出来 —— 现在还不够。")

    # ③ 按年 / 按月对账（收益、净投入、回撤；环比表看把「又转进来多少钱」剔掉之后的数）
    st.markdown(
        '<div class="sec-head"><span class="t">按年 / 按月对账</span>'
        '<span class="r">收益＝账户多了多少钱；收益率＝这份钱本身涨了几个点</span></div>',
        unsafe_allow_html=True,
    )
    with st.container(key="perf_freq_switch"):
        _freq = st.segmented_control(
            "切段", ["按年", "按月"], default="按年", key="perf_freq",
            label_visibility="collapsed",
            help="按年＝每年一段；按月＝每月一段（从当月第一个净值日到最后一个）。",
        ) or "按年"
    _rows = _period_perf("Y" if _freq == "按年" else "M")
    if not _rows:
        st.info("账户还没有可切段的净值曲线：先在「交易记录」补录成交，之后这里自动按月/按年切段。")
        return

    _show = _rows if _freq == "按年" else _rows[:36]      # 按月最多摆三年，再往前看意义不大
    st.iframe(_period_chart_html(_show, height=320 if len(_show) >= 4 else 236), height="content")

    _nav_all = _acct_daily["nav"].dropna()
    _tbl = []
    for _r in _show:
        _tbl.append([
            _r["period"],
            f'{_r["eq0"]:,.0f}',
            (_r["flow"] if abs(_r["flow"]) >= 0.5 else None) and
            f'<span class="{_pf_sign(_r["flow"])}">{_pf_num(_r["flow"], 0)}</span>' or
            '<span class="muted">—</span>',
            f'<span class="{_pf_sign(_r["pnl"])}">{_pf_num(_r["pnl"], 2)}</span>',
            f'<span class="{_pf_sign(_r["ret"])}">{_pct_txt(_r["ret"])}</span>',
            f'<span class="{_pf_sign(_r["mdd"])}">{_pct_txt(_r["mdd"])}</span>',
            f'{_r["eq1"]:,.0f}',
        ])
    _sum_pnl = sum(r["pnl"] for r in _rows)
    _sum_flow = sum(r["flow"] for r in _rows)
    _all_ret = float(_nav_all.iloc[-1]) - 1.0 if len(_nav_all) else 0.0
    _all_mdd = float((_nav_all / _nav_all.cummax() - 1).min()) if len(_nav_all) else 0.0
    _render_table(
        [("期间", "left"), ("期初总资产", "right"), ("净投入", "right"), ("收益(元)", "right"),
         ("收益率", "right"), ("期内回撤", "right"), ("期末总资产", "right")],
        _tbl,
        totals=["合计", "—",
                f'<span class="{_pf_sign(_sum_flow)}">{_pf_num(_sum_flow, 0)}</span>',
                f'<span class="{_pf_sign(_sum_pnl)}">{_pf_num(_sum_pnl, 2)}</span>',
                f'<span class="{_pf_sign(_all_ret)}">{_pct_txt(_all_ret)}</span>',
                f'<span class="{_pf_sign(_all_mdd)}">{_pct_txt(_all_mdd)}</span>', "—"],
        min_width=760,
    )
    if _freq == "按月" and len(_rows) > len(_show):
        st.caption(f"上面只摆了最近 {len(_show)} 个月（共 {len(_rows)} 个月），合计行给的是建仓以来的全期数。")
    _gap = _sum_pnl - float(_plan["pnl"])
    if abs(_gap) >= 1:
        st.caption(
            f"合计比首页「持有收益」多 **¥{_gap:,.2f}** —— 首页按「份额本金」算（转入那天按前一天的净值折份额），"
            "这里按「逐日资产变化 − 当日净投入」算；转入当天的净值有波动，两个口径就会差一点，"
            "跟支付宝对账以首页的「持有收益」为准。"
        )
    st.caption(
        "**收益（元）= 期末总资产 − 期初总资产 − 期内净投入**，把「又转进来多少钱」剔掉，剩下的才是赚的；"
        "**收益率 = 账户单位净值的涨跌**（总资产 ÷ 份额，转入按当时净值折份额，所以加钱不会抬高收益率）。"
        "两个数对不上是正常的 —— 钱多的时候同样 1% 也是更多的钱。"
        "期初总资产＝上一段最后一个交易日的总资产，所以每段的「收益」跟上一段的「期末」能接上；"
        "期内回撤每段重新起算，不把上一年的跌幅带进来。"
    )


def _acct_compare_view() -> None:
    """我的账户 vs 项目默认基金 vs 策略理论：**比收益率，不比净值**。

    三条线都从「账户建仓那天」起算，画的是各自相对起点的累计收益率。
    净值绝对值不能这么比：账户是「份额 × 净值 + 现金」除出来的、两个基准各自从 1.0 起，
    三条线本来就不同量纲，只有换算成 % 才有可比性。
    """
    _acct_strat = _strat_display.get(acct.get("strategy"), acct.get("strategy") or "—") if acct else "—"
    st.markdown(
        '<div class="sec-head"><span class="t">对比 · 我的账户 vs 项目默认基金 vs 策略理论</span>'
        '<span class="r">都以建仓日为 0%，比的是收益率</span></div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "**项目默认基金**＝拿项目自带那 8 个代码、按你**此刻侧边栏选的策略**和同样的再平衡节奏重放一遍，"
        "和它的差基本就是「换基金」带来的；"
        f"**策略理论**＝账户**建仓时选的策略**（{_acct_strat}）的回测曲线，切侧边栏不会改它 —— "
        "和它的差还含调仓时点、申赎费用，以及回测按累计净值、实盘按单位净值的口径差。"
    )
    _mine = _acct_daily["nav"].dropna() if (acct is not None and len(_acct_daily)) else pd.Series(dtype=float)
    if acct is None or len(_mine) <= 1:
        st.info("账户还没有净值曲线：在「交易记录」补录成交后自动生成。")
        return
    _curves, _gap_def, _gap_strat = {}, None, None
    if float(_mine.iloc[0]) > 0:
        _curves["我的账户"] = _mine / float(_mine.iloc[0])
    _bench_def = BM.replay_target(w, acct.get("created"), nav_getter=HG.nav_series)
    if _bench_def is not None and len(_bench_def.dropna()) > 1:
        _bd = _bench_def.dropna()
        _curves["项目默认基金"] = _bd / float(_bd.iloc[0])
    _bench_strat = BM.strategy_curve(_BENCH_COL.get(acct.get("strategy"), ""),
                                     start=acct.get("created"))
    if _bench_strat is not None and len(_bench_strat.dropna()) > 1:
        _bs = _bench_strat.dropna()
        _curves["策略理论"] = _bs / float(_bs.iloc[0])
    # 差距按两条线共同覆盖的最后一天算，避免其中一条缺数据时把区间拉长
    for _nm, _tag in (("项目默认基金", "def"), ("策略理论", "strat")):
        if "我的账户" in _curves and _nm in _curves:
            _a, _b = _curves["我的账户"], _curves[_nm]
            _e = min(_a.index[-1], _b.index[-1])
            _v = float(_a.loc[:_e].iloc[-1] / _b.loc[:_e].iloc[-1] - 1)
            if _tag == "def":
                _gap_def = _v
            else:
                _gap_strat = _v
    if len(_curves) > 1:
        st.iframe(_compare_chart_html(_curves, height=420, default_range="全部",
                                      title="累计收益率对比", pct_mode=True), height="content")
    else:
        st.info("基准曲线暂时取不到，只显示我的账户。")
    _ret_mine = float(_mine.iloc[-1] / float(_mine.iloc[0]) - 1) if float(_mine.iloc[0]) > 0 else 0.0
    _g1, _g2, _g3 = st.columns(3)
    _g1.metric("账户累计收益率", f"{_ret_mine*100:+.2f}%",
               help="建仓那天算 0%。转入按当天净值折份额，加钱不会抬高这个数。"
                    "想核对总资产：份额 × 最新单位净值 + 现金。")
    _g2.metric("vs 项目默认基金", f"{_gap_def*100:+.2f}pp" if _gap_def is not None else "—",
               help="把项目默认那 8 个代码按你现在的权重、同样的再平衡节奏重放一遍。"
                    "这一列只体现「换成你的基金」带来的差异。")
    _g3.metric("vs 策略理论", f"{_gap_strat*100:+.2f}pp" if _gap_strat is not None else "—",
               help="回测曲线从建仓日起归一。差的是选基、调仓时点、费用，"
                    "以及回测用累计净值/实盘用单位净值的口径差。")
    st.caption("三条线都以**建仓日 = 0%**，图上不看净值绝对值 —— 账户是两个基准各自归一出来的，"
               "只有收益率能放到同一把尺子上；两条差距就是「我的收益率 − 基准收益率」。"
               "图上可以拖动缩放、切日/月/年线，和「基金检索」页的用法一致。")


def _acct_health_view() -> None:
    """账户体检：只回答「有没有风险、哪一项越线、越线了去哪调」。

    这一页曾经把「累计收益」「与基准差」也列进指标表 —— 那是「收益」和「对比」两页的结论，
    等于同一件事在三个地方各印一遍，所以看着不伦不类。现在只留账户层面的风险：
    集中度（一只 / 一个位置吃多少）、现金够不够、回撤深不深、哪只在亏、偏离目标多少。
    判断阈值写在行里（现状 / 提醒线 / 判断），越线才在结论卡里说一句「该怎么看」。
    """
    st.markdown(
        '<div class="sec-head"><span class="t">体检 · 账户有没有风险</span>'
        '<span class="r">集中度 / 现金 / 回撤 / 单只浮亏 / 偏离目标</span></div>',
        unsafe_allow_html=True,
    )
    _rows = [r for r in _plan["rows"] if float(r["shares"] or 0) > 0]
    if not _rows:
        st.info("还没有持仓：先到「交易记录」补录成交，这里才有可体检的对象。")
        return
    _m = _al["指标"]

    def _nm(_r):
        return str(_r["f"].get("name") or _r["code"])

    # 集中的风险不在「哪只涨跌多少」，而在「一只 / 一个位置出问题能不能把账户拖下去」
    _big = max(_rows, key=lambda r: float(r["w_now"] or 0))
    _slot_w: dict[str, float] = {}
    for _r in _rows:
        _slot_w[_r["slot"]] = _slot_w.get(_r["slot"], 0.0) + float(_r["w_now"] or 0)
    _slot_k, _slot_max = max(_slot_w.items(), key=lambda kv: kv[1]) if _slot_w else ("", 0.0)
    _worst = min((r for r in _rows if r.get("pl") is not None), key=lambda r: r["pl"], default=None)
    _dev = max((r for r in _rows if r.get("w_tgt") is not None and r.get("dev") is not None),
               key=lambda r: abs(float(r["dev"])), default=None)
    _cash_r = float(_m.get("现金占比") or 0)
    _mdd = _m.get("最大回撤")
    _days = len(_acct_daily) if len(_acct_daily) else 0

    # ---- 逐项对阈值：越线的记进 _bad，结论卡只讲这几条 ----
    _tbl, _bad = [], []
    _MUT = 'color:var(--muted)'
    _WRN = 'color:var(--amber)'

    def _row(label, now, line, over, why, advice, bad):
        """一行检查：现状 / 提醒线 / 判断；越线时把「为什么算越线、去哪处理」攒给结论卡。"""
        _tbl.append([label, now, line,
                     f'<span style="{_WRN}">{over}</span>' if bad else f'<span style="{_MUT}">正常</span>'])
        if bad:
            _bad.append({"t": f"{label} {now}", "m": f"提醒线 {line}：{why}{advice}"})

    # 一个位置里挂了多只基金时，「单只」和「单一位置」是两个数，分别列；
    # 只挂一只时两个数一模一样，列两行就是自己抄自己
    _multi = any(sum(1 for r in _rows if r["slot"] == k) > 1 for k in _slot_w)
    if _multi:
        _row("单只最大占比", f"{_big['w_now']*100:.1f}%（{_nm(_big)}）", "25%", "偏高",
             "一只基金的涨跌就能左右整个账户", "；想分散到「权重与选基」给这个位置再挂一只同类基金",
             float(_big["w_now"] or 0) > 0.25)
        _row("单一位置最大占比", f"{_slot_max*100:.1f}%（{HG.SLOT_LABEL.get(_slot_k, _slot_k)}）", "50%", "偏高",
             "整个位置同涨同跌，相当于半个账户压在一个资产上", "；压不压看「帮你算」给的目标比例",
             _slot_max > 0.50)
    else:
        _row("最大仓位", f"{_slot_max*100:.1f}%（{_nm(_big)} · 位置「{HG.SLOT_LABEL.get(_slot_k, _slot_k)}」）",
             "25%", "偏高",
             "一只基金就占了账户这么多，它自己出问题等于账户出问题",
             "；接受也行（这是策略定的比例），想稳一点就给这个位置再挂一只同类基金分摊",
             _slot_max > 0.25)
    _row("现金占比", f"{_cash_r*100:.1f}%", "3% ~ 15%",
         "偏少" if _cash_r < 0.03 else "偏多",
         "调仓要先卖后买，现金太少会卡住；太多则拖低收益",
         "" if 0.03 <= _cash_r <= 0.15 else "；到「帮你算」按目标比例算一遍，买多少卖多少那里有数",
         (_cash_r < 0.03 or _cash_r > 0.15))
    _row("最大回撤",
         (f"{_mdd*100:.2f}%（账户 {_days} 天）" if _mdd is not None else "—"), "12%", "超线",
         "净值从最高点回落的最大幅度，越深越考验能不能拿住", "；扛不住就降波动，别硬撑",
         (_mdd is not None and _mdd <= -0.12))
    if _worst is not None:
        _row("单只最大浮亏", f"{_worst['pl']*100:.2f}%（{_nm(_worst)}）", "15%", "超线",
             "只说明「这一只买贵了」，不等于该卖", "；先判断是整体下跌还是这只自己的问题",
             float(_worst["pl"]) <= -0.15)
    if _dev is not None:
        _row("偏离目标最大", f"{float(_dev['dev'])*100:+.1f}pp（{_nm(_dev)}）", "±5pp", "该调了",
             "和策略目标已经拉开距离，再放下去就是「凭感觉持仓」", "；调多少看「帮你算」",
             abs(float(_dev["dev"])) >= 0.05)

    # ---- 结论卡：全正常只报平安，越线才说「越了哪条、去哪处理」 ----
    if not _bad:
        # 报平安的话按实际检查到的项目拼，别写死「仓位/现金/回撤」—— 项目数会随数据变
        st.markdown('<div class="sig calm"><div class="main"><div class="t">账户状态正常</div>'
                    f'<div class="m">{len(_tbl)} 项都在提醒线内：'
                    + "、".join(x[0] for x in _tbl) + '</div></div></div>',
                    unsafe_allow_html=True)
    else:
        # 只把第一条展开说透，其余交给下表 —— 每行都再起一张卡，就是同一件事写两遍
        _more = (f"另外 {len(_bad) - 1} 项也越线："
                 + "、".join(x["t"].split(" ")[0] for x in _bad[1:]) + "。") if len(_bad) > 1 else ""
        _title = (f"{len(_bad)} 项越过提醒线 · 最要紧的是这一条" if len(_bad) > 1
                  else f"{len(_bad)} 项越过提醒线")
        st.markdown(_alert_card("warn", _title, _bad[0]["m"], _more), unsafe_allow_html=True)

    _render_table([("检查项", "left"), ("现状", "left"), ("提醒线", "left"), ("判断", "left")], _tbl)

    _tail = []
    if _days and _days < 120:
        _tail.append(f"账户才 {_days} 天，回撤和浮亏这两个数还说明不了太多，样本长起来才准。")
    _tail.append("这里的判断只看账户层面；策略该不该触发在「模型 · 信号」，真要动手在「帮你算」。")
    st.caption("".join(_tail))


# ============================================================
# Tab 3: 我的账户（持仓 / 收益 / 对比 / 体检 四个子页签）
# ============================================================
with tab3:
    st.subheader("我的账户 · 有什么，赚多少，跑得怎么样")
    st.caption(
        "一页四看：**持仓**＝手里有什么、占多少；**收益**＝按年 / 按月赚了多少钱、收益率多少（不是净值）；"
        "**对比**＝跟项目默认基金、策略理论各差多少；**体检**＝仓位集不集中、现金够不够、回撤深不深。"
        "逐笔成交在「交易记录」页；该怎么调、调多少在「帮你算」页；策略触发在「模型 · 信号」页。"
    )

    # ---- 头卡：全站唯一一处「总金额 / 今日 / 持有收益」----
    _tot = _plan["total"]
    _n_funds = len([r for r in _plan["rows"] if r["shares"] > 0])
    _head_sub = (f"账户起始 {_cn_date(acct['created'])} · 净值日期 {_cn_date(_hg_last)} · {_n_funds} 只基金"
                 if acct else "还没有账户")
    st.markdown(
        '<div class="pf-head">'
        '<div class="pf-k">总金额（元）</div>'
        f'<div class="pf-amt">¥{_tot:,.2f}</div>'
        f'<div class="pf-sub">{_head_sub}</div>'
        '<div class="pf-grid">'
        f'<div><div class="k">今日收益</div><div class="v {_pf_sign(_plan["today"])}">'
        f'{_pf_num(_plan["today"], 2)}</div></div>'
        f'<div><div class="k">持有收益</div><div class="v {_pf_sign(_plan["pnl"])}">'
        f'{_pf_num(_plan["pnl"], 2)}</div></div>'
        f'<div><div class="k">持有收益率</div><div class="v {_pf_sign(_plan["pnl_pct"])}">'
        f'{_pf_num(_plan["pnl_pct"] * 100, 2)}%</div></div>'
        f'<div><div class="k">现金</div><div class="v">¥{_plan["cash"]:,.0f}</div></div>'
        '</div></div>',
        unsafe_allow_html=True,
    )

    # ---- 一页四看：持仓 / 收益 / 对比 / 信号（说的是同一个账户，只是角度不同）----
    with st.container(key="acct_view_switch"):
        _av = st.segmented_control(
            "账户视图", ["持仓", "收益", "对比", "体检"], default="持仓", key="acct_view",
            label_visibility="collapsed",
            help="持仓：手里有什么、占多少；收益：按年 / 按月赚了多少钱和收益率；"
                 "对比：跟项目默认基金、策略理论各差多少；体检：集中度、现金、回撤、单只浮亏、偏离目标。",
        ) or "持仓"

    if _av == "持仓":
        # 这一页只回答「手里有什么、占多少」。该买该卖多少一律在「帮你算」，
        # 这里连个数都不报 —— 同一件事两个页面各标一遍，迟早互相打脸。
        # ---- 持仓列表：一只基金一行，点一下就地展开、再点一下收起 ----
        if not _plan["rows"] and not _plan["other"]:
            st.info("还没有挂任何基金 —— 到「权重与选基」页底部给位置加一只，或点「恢复项目默认代码」。")
        else:
            _pf_rows = [_pf_row(it) for it in _plan["rows"]]
            for _o in _plan["other"]:          # 位置关掉了、或配置里已删，账上还留着份额的代码
                _why = "位置已关闭" if _o.get("in_cfg") else "不在配置里"
                _r = _pf_row(_hg_other_item(_o["code"], _why))
                # 占比列留空：这些钱不参与目标权重，跟上面几行的百分比不是同一把尺，混排会看起来「对不上」
                _r.update({"badge": _why, "badge_cls": "warn", "w": "—"})
                _pf_rows.append(_r)

            @st.fragment
            def _pf_stack_block():
                """持仓列表 + 就地展开的详情，整块跑在 fragment 里。

                点一行只重跑这一块（不重跑整页），头卡、上面的统计都不用重算，
                所以展开是「闪一下」而不是整页重载那种卡顿。
                """
                _pf_open = st.session_state.get("pf_open") or ""
                _codes = [r["code"] for r in _pf_rows]
                _cut = _codes.index(_pf_open) if _pf_open in _codes else -1
                _upper = _pf_rows if _cut < 0 else _pf_rows[:_cut + 1]
                _lower = [] if _cut < 0 else _pf_rows[_cut + 1:]
                _sel_it = next((it for it in _plan["rows"] if it["code"] == _pf_open), None)
                _sel_other = next((o for o in _plan["other"] if o["code"] == _pf_open), None)
                _sel_note = ""
                if not _sel_it and _sel_other:
                    _why = "位置被关掉了" if _sel_other.get("in_cfg") else "位置已从配置里删掉"
                    # 这句解释放进详情面板、贴着被点的那一行：留在列表上方的话，
                    # 选中/取消各来一次，整张表就上下平移 37px —— 那正是「点一下抖一下」的来源
                    _sel_note = (f"这只基金所在的{_why}（账上还有 ¥{_sel_other['mv']:,.0f}，占着总资产）："
                                 "想卖就到「交易记录」记一笔卖出，想继续拿就把位置重新打开 —— "
                                 "否则它不参与这一轮的调仓。")
                    _sel_it = _hg_other_item(_pf_open,
                                             "位置已关闭" if _sel_other.get("in_cfg") else "不在配置里")

                # 三段拼成一张卡：上半段列表 / 详情 / 下半段列表（详情落在被点的那一行正下方）
                with st.container(key="pf_stack"):
                    _sel_a, _at_a = _pf_list(_upper, selected=_pf_open, key="pf_list_a",
                                             cap=not _sel_it, pos="top" if _sel_it else "")
                    if _sel_it:
                        with st.container(key="pf_inline"):
                            if _sel_note:
                                st.caption(_sel_note)
                            _pf_detail(_sel_it, inline=True)
                    if _lower:
                        _sel_b, _at_b = _pf_list(_lower, key="pf_list_b", head=False,
                                                 cap=False, pos="bot")
                    else:
                        _sel_b, _at_b = "", 0

                # 点行 = 切换：展开着的那行再点一下就收起（全站唯一的收起入口）
                _new_sel, _new_at = (_sel_a, _at_a) if _at_a >= _at_b else (_sel_b, _at_b)
                if _new_at and _new_at != st.session_state.get("pf_click_at"):
                    st.session_state["pf_click_at"] = _new_at
                    st.session_state["pf_open"] = "" if _new_sel == _pf_open else _new_sel
                    st.rerun(scope="fragment")
                if not _sel_it:
                    st.caption("点一下基金名，就在这一行下面展开金额、买卖点与累计盈亏；再点一下收起。")

            _pf_stack_block()

            # 汇总紧跟列表：点开某只基金后详情很长，这句被推到详情下面就等于看不见了
            _other_sum = sum(float(o["mv"]) for o in _plan["other"])
            if _other_sum > 0:
                st.caption(
                    f"另有 **¥{_other_sum:,.0f}**（占 {_other_sum / _plan['total'] * 100 if _plan['total'] else 0:.0f}%）"
                    "落在「位置已关闭 / 不在配置里」的基金上（上表最后几行）：钱是你的、也算进总金额，"
                    "但**不参与目标权重和调仓**。想让它继续干活就到「权重与选基」把那个位置打开，"
                    "不想拿就到「交易记录」记一笔卖出。"
                )


        # ---- 已清仓：从成交记录还原的历史轮次（清仓时赚了多少、拿了多久）----
        _closed_section()

    elif _av == "收益":
        _acct_period_view()
    elif _av == "对比":
        _acct_compare_view()
    else:
        _acct_health_view()

# ============================================================
# Tab 3: 帮你算 —— 全站唯一给出「该买/卖多少」的地方，只算不写账
#   · 存量调仓：钱已经在账户里，把现有仓位调回目标比例（可能一边买一边卖）
#   · 新钱怎么分：往账户里新投一笔钱，只买不卖
# 两边都不再提供「登记成成交」—— 记什么、记多少，由你到「交易记录」自己填。
# 原来这是两个独立页签（买卖提醒 / 定投一笔），同一件事要在两个页面上看金额，现已合并。
# ============================================================
def _calc_rebalance() -> None:
    st.markdown(
        '<div class="sec-head"><span class="t">存量调仓 · 把仓位调回目标比例</span>'
        '<span class="r">只算不记账 · 算完到「交易记录」自己填</span></div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "钱已经在账户里，这里只回答一件事：把现有仓位调回目标比例，该买什么、卖什么、各多少（可能一边买一边卖）。"
        "**这是「计划」，不是流水** —— 具体记哪几笔，到「交易记录」自己填；"
        "新投一笔钱怎么分，切到「新钱怎么分」。"
    )

    if not _plan["has_acct"]:
        st.info("还没有账户：先到「交易记录」建一个账户（填一笔初始资金），之后这里就会按你的真实持仓算买卖。")
    elif _plan["total"] <= 0:
        st.info("账户里还没有钱和持仓：先到「交易记录」建账户时填上初始资金，再在支付宝买好后补录买入。")
    elif _plan["asset"] <= 0:
        # 钱都在「位置已关闭 / 配置里已删」的代码上：能算不能动，先告诉人怎么把钱挪出来
        st.warning(
            f"账户里有 ¥{_plan['total']:,.0f}，但都落在**已关闭或已删掉的位置**里，没有可调仓的钱。"
            "这些份额不参与调仓（见「我的账户」里标「位置已关闭 / 不在配置里」的行）："
            "想继续拿就把它所在的位置重新打开，想换掉就到「交易记录」逐笔记卖出。"
        )
    elif not _plan["rows"]:
        st.warning("还没有挂任何基金：先到「权重与选基」给位置加一只，或点右上角「更新数据」拉取净值。")
    else:
        # ---- 结论：这一轮动不动、买多少卖多少 ----
        if _plan["orders"]:
            st.markdown(
                '<div class="pf-summary">'
                f'<span class="lead">这一轮要动 {len(_plan["orders"])} 笔</span>'
                f'<span class="item">买入<b class="buy">¥{_plan["buy"]:,.0f}</b></span>'
                f'<span class="item">卖出<b class="sell">¥{_plan["sell"]:,.0f}</b></span>'
                f'<span class="item">调仓基数 ¥{_plan["asset"]:,.0f}</span>'
                '</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="pf-summary quiet"><span class="lead">这一轮不用动</span>'
                '<span class="item">所有位置偏离都在 0.5% 以内</span></div>',
                unsafe_allow_html=True,
            )

        # ---- 差额清单：当前权重 vs 目标权重 → 该买卖多少 ----
        _rb_rows = []
        for _it in _plan["rows"]:
            _rb_rows.append([
                (HG.SLOT_LABEL[_it["slot"]] if _it["slot_first"] else '<span class="muted">↳</span>'),
                f'{_it["f"].get("name") or _it["code"]}<br><span class="muted">{_it["code"]} · '
                + ("场外" if _it["otc"] else "场内")
                + (f' · 位置内 {_it["x"]*100:.0f}%' if _it["slot_n"] > 1 else "") + '</span>',
                f'{_it["mv"]:,.0f}',
                (f'{_it["slot_w"]*100:.1f}%' if _it["slot_first"] else ""),
                (f'{_it["slot_tgt_w"]*100:.1f}%' if _it["slot_first"] else ""),
                (('<span class="muted">—</span>' if abs(_it["dev"]) < 0.03
                  else f'<span class="{_pf_sign(_it["dev"])}">{_it["dev"]*100:+.1f}pp</span>')
                 if _it["slot_first"] else ""),
                _pf_badge(_it, with_qty=True),
            ])
        # 不在启用位置里、但账上还留着份额的代码：占着总资产却不在目标权重里，单独列出来
        for _o in _plan["other"]:
            _why = "位置已关闭" if _o.get("in_cfg") else "不在配置里"
            _rb_rows.append([
                "其他",
                f'{FL.fund_name(_o["code"]) or _o["code"]}<br><span class="muted">{_o["code"]} · {_why}</span>',
                f'{_o["mv"]:,.0f}',
                # 这些钱不进调仓基数，所以权重只能按「全账户」算，不能跟上面配置内的百分比混着比
                f'<span class="muted">占全账户 '
                f'{(_o["mv"] / _plan["total"] * 100) if _plan["total"] else 0:.1f}%</span>',
                "0.0%", '<span class="muted">—</span>',
                f'<span class="muted">{_why}，不参与调仓</span>',
            ])
        _render_table(
            [("位置", "left"), ("我的基金", "left"), ("当前市值(¥)", "right"),
             ("当前权重", "right"), ("目标权重(位置)", "right"), ("偏离", "right"), ("操作", "left")],
            _rb_rows,
            totals=["合计", "—", f'{_plan["mv_all"]:,.0f}',
                    f'{(_plan["mv_all"] / _plan["total"] * 100) if _plan["total"] else 0:.1f}%',
                    "100.0%", "—",
                    (f'买 ¥{_plan["buy"]:,.0f} / 卖 ¥{_plan["sell"]:,.0f}'
                     if (_plan["buy"] or _plan["sell"]) else "—")],
            min_width=900,
        )
        _other_mv = sum(float(o["mv"]) for o in _plan["other"])
        st.caption(f"调仓基数 ¥{_plan['asset']:,.0f} = 持仓 ¥{_plan['mv']:,.0f} + 现金 ¥{_plan['cash']:,.0f}。"
                   + (f"另有 ¥{_other_mv:,.0f} 落在「其他」（位置已关闭或已删）里，**不进基数**——"
                      "那部分钱不替你买卖，想让它参与就把位置重新打开。"
                      if _other_mv > 0 else "")
                   + "配置内各行的「当前权重」和「目标权重」是同一把尺（分母都是调仓基数），"
                   "「其他」行和合计按全账户算。"
                   "位置整体偏离 < 0.5% 不用动，省手续费；场内按每手取整，场外按最低申购金额。")

        # ---- 现金够不够：只提示，不替人下单 ----
        if _plan["orders"]:
            _net_out = float(_plan["buy"]) - float(_plan["sell"])
            if _net_out > float(_plan["cash"]) + 100:
                st.warning(
                    f"这份清单要买入 ¥{_plan['buy']:,.0f}、卖出 ¥{_plan['sell']:,.0f}，"
                    f"净流出 ¥{_net_out:,.0f}，超过账户现金 ¥{_plan['cash']:,.0f}。"
                    "支付宝里卖出的钱 T+1 才到账 —— 先卖、等钱到了再买；"
                    "或者把买入的那几笔按比例调小，差额留到下次。"
                )
            st.caption("金额按最新净值估算；实际以你在支付宝成交的价格为准。"
                       "这一页不写账 —— 成交后到「交易记录」逐笔填日期 / 金额 / 单价，"
                       "差多少都能就地改。")

# ============================================================
# 「帮你算」的另一半：新钱怎么分（只买不卖）
# ============================================================
def _calc_dca() -> None:
    st.markdown(
        '<div class="sec-head"><span class="t">新钱怎么分 · 这一笔只买不卖</span>'
        '<span class="r">只算不记账 · 算完到「交易记录」自己填</span></div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "往账户里新投一笔钱，按目标权重补缺口，直接给出每只基金买多少份/股。"
        "这是「还没发生」的计算，**不会写进账户**；钱早就在现金里、只想调回目标比例的，切到「存量调仓」。"
    )

    if not _plan["has_acct"]:
        st.info("还没有账户：先到「交易记录」建一个账户（填一笔初始资金），之后这里才能按目标权重分钱。")
    elif _plan["total"] <= 0:
        st.info("账户里还没有钱和持仓：先到「交易记录」建账户时填上初始资金，再在支付宝买好后补录买入。")
    elif not _plan["rows"]:
        st.warning("还没有挂任何基金：先到「权重与选基」给位置加一只，或点右上角「更新数据」拉取净值。")
    else:
        # ---------------- 新钱怎么分：按目标权重分，直接给出每只买多少份 ----------------
        with st.container(key="dca_card"):
            # 不再加一行「这次投多少」小标题：页面标题已经写着「新钱怎么分」，连着两行标题只是重复
            _dc1, _dc2 = st.columns([1.0, 3.0], gap="small", vertical_alignment="bottom")
            _dc_amt = _dc1.number_input("打算投多少（元）", min_value=0.0, step=1000.0,
                                        value=5000.0, format="%.0f", key="dc_amount")
            _dc2.caption("按最新净值估算份额（场外按金额申购，实际份额以支付宝确认为准）。"
                         "这里只告诉你「每只买多少」，账户什么都不改。")

        # 位置聚合（含位置内多只基金）→ 按目标权重分配这笔钱
        _dc_slots: dict[str, dict] = {}
        _dc_meta: dict[str, dict] = {}
        _dc_dead: list[dict] = []           # 缺净值、这次分不到的基金
        for _it in _plan["rows"]:
            _g = _dc_slots.setdefault(_it["slot"], {
                "slot": _it["slot"], "w": float(_it["slot_tgt_w"]), "mv": 0.0, "items": []})
            _g["mv"] += float(_it["mv"])     # 缺净值的市值也算进去，否则目标市值会算小
            if _it["px"] <= 0:
                _dc_dead.append(_it)
                continue
            _g["items"].append({"code": _it["code"], "x": float(_it["x"])})
            _dc_meta[_it["code"]] = _it
        _dc_alloc = HG.plan_invest(list(_dc_slots.values()), float(_dc_amt))

        _dc_slot_alloc: dict[str, float] = {}   # 分到的钱（含买不到的），用来判断「谁超配没分到」
        _dc_rows, _dc_n = [], 0
        _dc_buy = _dc_lost_amt = 0.0
        for _a in _dc_alloc:
            _m = _dc_meta.get(_a["code"])
            if not _m:
                continue
            _want = float(_a["amount"])
            _qty, _amt = HG.order_quantity(_m["f"], _want, float(_m["px"]))
            _dc_slot_alloc[_a["slot"]] = _dc_slot_alloc.get(_a["slot"], 0.0) + _want
            _note = ""
            if _qty <= 0:
                # 钱分到了但下不了单：场外是低于最低申购，场内是一手太贵 —— 必须说出来，不能静默丢掉
                if HG.is_otc(_m["f"]):
                    _note = f'低于最低申购 ¥{float(_m["f"].get("min_amount") or 1):,.0f}'
                else:
                    _note = f'不足一手，一手 ≈ ¥{int(_m["f"].get("lot") or 100) * float(_m["px"]):,.0f}'
                _dc_lost_amt += _want
            else:
                _dc_buy += _amt
                _dc_n += 1
            _dc_rows.append({"slot": _a["slot"], "m": _m, "want": _want, "amt": _amt,
                             "qty": float(_qty), "x": _a["x"], "note": _note})

        if not _dc_rows:
            st.info("这个金额分不出可买的份额：把金额调大一点，或先给位置挂上基金 / 点右上角更新净值。")
        else:
            st.markdown(
                '<div class="pf-summary">'
                f'<span class="lead">投 ¥{float(_dc_amt):,.0f} → 买到 {_dc_n} 只基金</span>'
                f'<span class="item">实际买入 <b class="buy">¥{_dc_buy:,.0f}</b></span>'
                # 这笔钱是新进来的，投完总资产才变大；只算不记账，所以这里只是「投完会是多少」
                f'<span class="item">投后总资产 '
                f'¥{_plan["total"] + float(_dc_amt):,.0f}</span>'
                '</div>',
                unsafe_allow_html=True,
            )
            _dc_tbl, _dc_seen = [], set()
            for _r in _dc_rows:
                _slot, _m, _qty, _x, _note = (_r["slot"], _r["m"], _r["qty"],
                                              _r["x"], _r["note"])
                _first = _slot not in _dc_seen
                _dc_seen.add(_slot)
                _unit = "份" if _m["otc"] else "股"
                _dc_tbl.append([
                    (HG.SLOT_LABEL.get(_slot, _slot) if _first else '<span class="muted">↳</span>'),
                    f'{_m["f"].get("name") or _m["code"]}<br><span class="muted">{_m["code"]} · '
                    + ("场外" if _m["otc"] else "场内")
                    + (f' · 位置内 {_x * 100:.0f}%' if _m["slot_n"] > 1 else "") + '</span>',
                    (f'{_m["slot_tgt_w"] * 100:.1f}%' if _first else ""),
                    f'{_m["mv"]:,.0f}',
                    f'<b>¥{_r["want"]:,.0f}</b>',
                    f'{_m["px"]:.4f}',
                    (f'<span class="muted">{_note}</span>' if _note else
                     (f'<b>{_qty:,.2f}</b> 份' if _unit == "份" else f'<b>{_qty:,.0f}</b> 股')),
                ])
            _render_table(
                [("位置", "left"), ("我的基金", "left"), ("目标权重", "right"),
                 ("当前市值(¥)", "right"), ("分配金额(¥)", "right"),
                 ("净值", "right"), ("能买多少", "right")],
                _dc_tbl,
                totals=["合计", "—", "100.0%", f'{_plan["mv"]:,.0f}',
                        f'{_dc_buy + _dc_lost_amt:,.0f}', "—", f'实买 ¥{_dc_buy:,.0f}'],
                min_width=920,
            )
            if _dc_lost_amt > 0.5:
                # 每个位置都能买到一手/够最低申购，这次至少要投多少钱
                _dc_buyable = [_g for _g in _dc_slots.values() if _g["items"]]
                _dc_wsum = sum(_g["w"] for _g in _dc_buyable) or 1.0
                _dc_min_need = 0.0
                for _g in _dc_buyable:
                    _wi = _g["w"] / _dc_wsum
                    _xs = sum(it["x"] for it in _g["items"]) or 1.0
                    if _wi <= 0:
                        continue
                    for _it in _g["items"]:
                        _mm = _dc_meta.get(_it["code"])
                        if not _mm:
                            continue
                        if HG.is_otc(_mm["f"]):
                            _need = float(_mm["f"].get("min_amount") or 1)
                        else:
                            _need = int(_mm["f"].get("lot") or 100) * float(_mm["px"])
                        _dc_min_need = max(_dc_min_need, _need * _xs / _it["x"] / _wi)
                st.warning(
                    f"有 ¥{_dc_lost_amt:,.0f} 分到了但下不了单（见上表「能买多少」），这笔钱先留在现金里。"
                    + (f"按现在的权重，这次至少要投 ¥{_dc_min_need:,.0f} 才能每个位置都买到一手。"
                       if _dc_min_need > 0 else "")
                    + "\n\n如果这只基金你其实是在支付宝按**金额**买的，说明它的「买卖单位」被记成了「股」，"
                    "到「权重与选基」页底改成「份额」就能算份额；如果确实是场内 ETF，就调大金额。"
                )
            _dc_skip = [_s for _s in _dc_slots if _s not in _dc_slot_alloc]
            st.caption(
                "分配规则：按目标权重补缺口 —— 市值低于目标的先拿钱，已经超配的一分不给，"
                "剩下的再按权重摊。"
                + ("这次没分到钱的位置：" + "、".join(HG.SLOT_LABEL.get(_s, _s) for _s in _dc_skip)
                   + "（已经超配）。" if _dc_skip else "")
                + "场外基金按金额申购，份额 = 金额 ÷ 净值 是估算，实际以支付宝确认的份额为准；"
                "场内按每手取整。"
            )
            if _dc_dead:
                _dead_txt = "、".join(f'{_d["f"].get("name") or _d["code"]}（{_d["code"]}）'
                                     for _d in _dc_dead[:6])
                if len(_dc_dead) > 6:
                    _dead_txt += f" 等 {len(_dc_dead)} 只"
                _dead_mv = sum(float(_d["mv"]) for _d in _dc_dead)
                _dead_pct = (_dead_mv / _plan["mv"] * 100) if _plan["mv"] else 0.0
                st.warning(
                    f"这些基金没有净值数据，这次分不到钱：{_dead_txt}。"
                    f"它们占持仓 {_dead_pct:.0f}%，这份钱只能让给别的基金，买完比例会偏。"
                    "建议先点右上角「更新数据」补齐净值，再回来定投。"
                )
            if _dc_buy > float(_plan["cash"]):
                st.warning(f"账户现金只有 ¥{_plan['cash']:,.0f}，这笔要买 ¥{_dc_buy:,.0f} —— "
                           "把这次的金额调小到现金以内再算。")
            st.caption("按最新净值估算；实际成交净值以支付宝确认为准。"
                       "这一页不写账 —— 成交后到「交易记录」逐笔填日期 / 金额 / 单价。")


# ============================================================
# 「帮你算」页：两个子视图共用一个页签，都只算不写
# ============================================================
with tab_calc:
    with st.container(key="calc_switch"):
        _calc_view = st.segmented_control(
            "算哪种", ["存量调仓", "新钱怎么分"], default="存量调仓", key="calc_view",
            label_visibility="collapsed",
            help="存量调仓：钱已经在账户里，把它调回目标比例；新钱怎么分：往账户里再投一笔，只买不卖。",
        ) or "存量调仓"
    if _calc_view == "存量调仓":
        _calc_rebalance()
    else:
        _calc_dca()


# ============================================================
# Tab 5: 交易记录（补录 + 台账）—— 只记录支付宝上实际发生了什么
# ============================================================
with tab5:
    _cash, _mv_all, _total = (float(_plan["cash"]), float(_plan["mv_all"]),
                              float(_plan["total"]))
    st.markdown(
        '<div class="sec-head"><span class="t">交易记录</span>'
        f'<span class="r">现金 <b>¥{_cash:,.0f}</b>　持仓 <b>¥{_mv_all:,.0f}</b>'
        f'　总资产 <b>¥{_total:,.0f}</b></span></div>',
        unsafe_allow_html=True,
    )
    st.caption("这一页只记「实际做了什么」，每一笔都会立刻重算持仓和收益。"
               "「帮你算」里的那份是策略算出来的计划，记不记、记多少由你。"
               "只有两种类型：**买入** 把现金换成基金，**卖出** 把基金换回现金 —— "
               "卖出的钱自动回到账户现金里，不用另外记一笔。")

    _slot_opts = _hg_slot_options()
    if acct is None:
        st.markdown('<div class="sec-head"><span class="t">先建一个账户</span></div>',
                    unsafe_allow_html=True)
        st.caption("账户就是一笔本金 + 一串成交记录；建完再逐笔补录（也可以在支付宝买完后回来补录）。")
        with st.container(key="tr_card"):
            c1, c2, c3 = st.columns(3, gap="small", vertical_alignment="bottom")
            s_init = c1.selectbox("跟随策略", list(STRATEGIES),
                                  format_func=lambda k: STRATEGIES[k]["name"])
            cap0 = c2.number_input("初始资金（元）", min_value=1000.0, value=500000.0,
                                   step=10000.0, format="%.0f")
            start0 = c3.date_input("起始日期", value=prices.index[-1].date())
            if st.button("创建账户", type="primary", key="tr_acct_new"):
                save_acct({"strategy": s_init, "capital": float(cap0),
                           "created": str(start0), "trades": []}, ACCT_FILE)
                st.rerun()
    elif not _slot_opts:
        st.warning("还没有挂任何基金：先到「权重与选基」给位置加至少一只基金，才能记账。")
    else:
        _trades = acct.setdefault("trades", [])

        # 场内 / 场外不用再选一次 —— 代码本身就定了：5/1 开头的 ETF、LOF 在交易所买卖（场内），
        # 0 开头的开放式基金在支付宝申购（场外）。但它决定**记账单位**，所以要在表单里说出来：
        #   场内 → 按「股」，100 股一手，价格一天里随时变，还有溢价折价；
        #   场外 → 按「份额」，按金额申购，份额带两位小数，一天只有一个净值。
        # 判错了不用改代码：「权重与选基」页底的「买卖单位」一列可以改成股 / 份额，这里以那里为准；
        # 没改过的（unit 还是默认值）就用代码 + 申购状态猜。
        _unit_of: dict[str, str] = {}
        for _s0 in HG.SLOTS:
            for _f0 in HG.funds(holdings.get(_s0, {})):
                _unit_of[str(_f0["code"])] = str(_f0.get("unit") or HG.default_unit(_f0["code"]))

        def _uw(code) -> str:
            """这只基金按「股」还是「份」记账。"""
            return "股" if _unit_of.get(str(code), HG.default_unit(str(code))) == "股" else "份"

        def _mkt(code) -> str:
            """一句话说清这只基金是哪类、按什么成交 —— 用户只关心「我该填股价还是净值」。"""
            return ("场内 · 按股成交，100 股一手" if _uw(code) == "股"
                    else "场外 · 按份额申购，一天一个净值")

        _funds = [{"slot": s, "code": c, "label": lb, "unit": _uw(c)}
                  for s, c, lb in _slot_opts]

        # ---------------- 记一笔：金额优先，和支付宝「买入 5,000 元」的说法一致 ----------------
        with st.container(key="tr_card"):
            # 标题和「买入 / 卖出」同一行：类型不单独占一行，也不用推到右边 ——
            # 推到右边就跟页面上那些筛选器长得一样。
            with st.container(horizontal=True, horizontal_alignment="left",
                              vertical_alignment="center", key="tr_mode_switch"):
                st.markdown('<div class="sec-head"><span class="t">记一笔</span></div>',
                            unsafe_allow_html=True)
                tr_side = st.segmented_control(
                    "类型",
                    ["买入", "卖出"],
                    default="买入", key="tr_side",
                    # 不显标签：跟「记一笔」标题同一行，标签会把标题挤到下面半行去
                    label_visibility="collapsed",
                    help="买入 = 账户现金换基金；卖出 = 基金换回现金 —— "
                         "卖出的钱自动回到现金，不用另外记一笔。",
                ) or "买入"

            # 一套列宽管一行：日期 / 基金 / 金额 / 单价 / 手续费 / 按钮
            rB = st.columns([1.2, 2.0, 1.2, 1.2, 1.2, 0.8], gap="small",
                            vertical_alignment="bottom")
            tr_date = rB[0].date_input("日期", value=pd.Timestamp(_hg_last).date(),
                                       max_value=date.today(),
                                       format="YYYY/MM/DD", key="tr_date")
            tr_slot = rB[1].selectbox(
                "基金", _slot_opts, format_func=lambda x: x[2], key="tr_fund",
                help="这只基金按「股」还是按「份额」记账，由它的代码决定（ETF/LOF 场内按股，"
                     "开放式基金场外按份额）；判错了到「权重与选基」页底把「买卖单位」改成份额 / 股。")
            tr_amount = rB[2].number_input("金额（元）", min_value=0.0, step=1000.0,
                                           format="%.2f", key="tr_amount")
            _nav_hint = _hg_nav_on(None, tr_date, tr_slot[1])
            _uw1 = _uw(tr_slot[1])
            tr_nav = rB[3].number_input(
                f"单价（元/{_uw1}）",
                min_value=0.0, value=round(float(_nav_hint or 0), 4),
                step=0.0001, format="%.4f", key=f"tr_nav_{tr_slot[1]}_{tr_date}",
                help=("默认取这天的净值（场外按当日收盘净值成交）；支付宝里确认价不一样时改这里。"
                      if _uw1 == "份" else
                      "默认取这天的收盘价；场内成交价会比净值高一点或低一点（溢价 / 折价），"
                      "按证券账户里实际的成交价填。"))
            tr_fee = rB[4].number_input("手续费（元）", min_value=0.0, step=1.0,
                                        format="%.2f", key="tr_fee")
            _side_note = (f"买入：现金 → 基金。金额按单价折成{_uw1}数，现金减少。"
                          if tr_side == "买入" else
                          "卖出：基金 → 现金。钱自动回到账户现金里。")
            _act = rB[5]

            _sh_new = 0.0
            if tr_nav > 0:
                _sh_new = ((float(tr_amount) - float(tr_fee)) / float(tr_nav) if tr_side == "买入"
                           else (float(tr_amount) + float(tr_fee)) / float(tr_nav))
            # 现金只看「金额」：买入付出去多少、卖出到账多少（手续费已含在金额里）
            _cash_after = (_cash + float(tr_amount) if tr_side == "卖出"
                           else _cash - float(tr_amount))
            # 先说这只基金按什么成交，再说这笔会发生什么 —— 「我该填股价还是净值」是这个表单最容易填错的地方
            _hint = f"**{_mkt(tr_slot[1])}**　{_side_note}"
            if tr_amount > 0 and tr_nav > 0:
                _hint += (f"　≈ {_sh_new:,.2f} {_uw(tr_slot[1])}"
                          f"，现金 ¥{_cash:,.0f} → ¥{_cash_after:,.0f}")
                # 场内买入只能是整手（100 股），折出零股基本就是金额或单价填错了 —— 顺带给出就近那一手
                if tr_side == "买入" and _uw(tr_slot[1]) == "股" and abs(round(_sh_new) - _sh_new) > 0.01:
                    _near = int(round(_sh_new / 100)) * 100
                    _hint += ("（场内买入按整手 100 股，这个金额不够一手）" if _near <= 0 else
                              f"（场内买入按整手 100 股；就近是 {_near:,} 股 ≈ ¥{_near * float(tr_nav):,.2f}）")
            st.caption(_hint)
            if _cash_after < -1:
                st.warning(
                    f"记完现金会变成 ¥{_cash_after:,.0f}（负的）—— 账户里没有这么多现金。"
                    "把金额调小到现金以内；如果这只基金之前就有持仓、只是没补录，"
                    "先把那笔买入补上，现金就够扣了。")

            if _act.button("记一笔", type="primary", key="tr_add", width="stretch"):
                _t = {"date": str(tr_date), "side": tr_side,
                      "slot": (tr_slot[0] if tr_slot else ""),
                      "code": (tr_slot[1] if tr_slot else ""),
                      "shares": round(float(_sh_new), 4),
                      "nav": float(tr_nav), "fee": float(tr_fee)}
                if float(tr_amount) <= 0:
                    st.warning("金额要大于 0")
                elif float(tr_nav) <= 0:
                    st.warning("单价要大于 0 —— 换一天或手工填那天的成交净值")
                elif (tr_side == "卖出"
                      and _sh_new > _held_on(_trades, tr_slot[1], tr_date) + 1e-6):
                    # 卖出超过当时持有 = 凭空多出现金，账目直接错；先拦住并说清楚能卖多少
                    _held = _held_on(_trades, tr_slot[1], tr_date)
                    _uw2 = _uw(tr_slot[1])
                    st.warning(
                        f"卖不了这么多：{FL.fund_name(tr_slot[1]) or tr_slot[1]} 到 {_cn_date(tr_date)} "
                        f"只持有 {_held:,.2f} {_uw2}（约 ¥{_held * float(tr_nav):,.0f}），"
                        f"这次要卖 {_sh_new:,.2f} {_uw2}。改小金额，或先补录这笔之前漏记的买入。"
                    )
                else:
                    _trades.append(_t)
                    save_acct(acct, ACCT_FILE)
                    st.toast("已记录", icon=":material/check_circle:")
                    st.rerun()

        # ---------------- 成交台账：先筛，再看表；最近的在最上面 ----------------
        _ledger_codes = []
        for _t0 in _trades:
            _c0 = str(_t0.get("code") or "")
            if _c0 and _c0 not in _ledger_codes:
                _ledger_codes.append(_c0)
        _pick_map = {"全部基金": ""}
        for _c0 in _ledger_codes:
            _pick_map[f'{_c0} {FL.fund_name(_c0) or ""}'.strip()] = _c0
        st.markdown('<div class="sec-head"><span class="t">成交台账</span></div>',
                    unsafe_allow_html=True)
        # 筛选和摘要是台账的头，跟表贴在一起 ——
        # 夹在「记一笔」和表中间，看着就像凭空多出来的第三个区块。
        # 摘要必须**单独一行铺满全宽**：跟下拉挤一行时它从下拉右边起，左边比表格缩进近 300px、
        # 右边却跟表格齐平，上下扫过去就是「前后没对齐」。那空出来的右半行给操作说明，别留白。
        _fc1, _fc2 = st.columns([1.6, 5.0], gap="medium", vertical_alignment="bottom")
        _fcode = _pick_map[_fc1.selectbox("看哪只基金的历史", list(_pick_map),
                                          key="tr_fund_filter")]
        _fc2.markdown('<div class="tr-ledger-hint">最近的在上 · 铅笔就地改，垃圾桶就地删</div>',
                      unsafe_allow_html=True)
        _f_tr = ([t for t in _trades if str(t.get("code") or "") == _fcode]
                 if _fcode else list(_trades))
        # 摘要跟着筛选走：不选基金时给全账户的，别把右半边留成一片空白
        _fb = sum(float(t.get("shares") or 0) * float(t.get("nav") or 0)
                  + float(t.get("fee") or 0) for t in _f_tr if t.get("side") == "买入")
        _fs = sum(float(t.get("shares") or 0) * float(t.get("nav") or 0)
                  - float(t.get("fee") or 0) for t in _f_tr if t.get("side") == "卖出")
        _ff = sum(float(t.get("fee") or 0) for t in _f_tr)
        _it_html = [f'<span class="item">{len(_f_tr)} 笔</span>',
                    f'<span class="item">买入 <b class="buy">¥{_fb:,.0f}</b></span>',
                    f'<span class="item">卖出 <b class="sell">¥{_fs:,.0f}</b></span>']
        _it_html.append(f'<span class="item">手续费 ¥{_ff:,.2f}</span>')
        if _fcode:
            _fsh = float((_acct_pos or {}).get(_fcode, 0) or 0)
            _funit = _uw(_fcode)
            _fqty = f"{_fsh:,.0f} 股" if _funit == "股" else f"{_fsh:,.2f} 份"
            _fpnl = _code_pnl_curve(_fcode)
            _fpnl_v = float(_fpnl.iloc[-1]) if len(_fpnl) else None
            _fpnl_s = ("" if _fpnl_v is None else
                       "0" if abs(_fpnl_v) < 0.5 else f"{_fpnl_v:+,.0f}")
            _fpnl_cls = "buy" if (_fpnl_v or 0) > 0.5 else ("sell" if (_fpnl_v or 0) < -0.5 else "")
            _it_html += [f'<span class="item">持有 {_fqty}</span>']
            if _fpnl_v is not None:
                _it_html += [f'<span class="item">累计盈亏 <b class="{_fpnl_cls}">¥{_fpnl_s}</b></span>']
            _lead = FL.fund_name(_fcode) or _fcode
        else:
            _it_html += [f'<span class="item">涉及 {len(_ledger_codes)} 只基金</span>']
            _lead = "全部成交"
        st.markdown(
            f'<div class="pf-summary quiet ledger"><span class="lead">{_lead}</span>'
            + "".join(_it_html) + '</div>', unsafe_allow_html=True)

        if not _trades:
            st.caption("还没有成交。上面记一笔即可；「帮你算」只给金额，不会自己写账。")
        elif not _f_tr:
            st.caption("这只基金还没有成交记录。")
        else:
            # 出错提示要先存起来：这条分支末尾会 st.rerun()，直接 st.warning 会一闪而过看不到
            _S_err = st.session_state.pop("_tr_err", "")
            if _S_err:
                st.warning(_S_err)
            # 最近的排最上面（按成交日期，再按录入顺序倒序）：刚记错的那笔就在第一行
            _rows = [_trade_row(i, t) for i, t in
                     sorted(enumerate(_trades),
                            key=lambda kv: (str(kv[1].get("date") or ""), kv[0]), reverse=True)
                     if not _fcode or str(t.get("code") or "") == _fcode]
            _saved, _dsig = _trade_list(_rows, _funds)
            if _saved and _saved != st.session_state.get("_tr_save_sig"):
                st.session_state["_tr_save_sig"] = _saved
                try:
                    _p = json.loads(_saved)
                except Exception:                 # noqa: BLE001
                    _p = None
                if isinstance(_p, dict):
                    _i = int(_p.get("i", -1))
                    if 0 <= _i < len(_trades):
                        _new = {"date": str(_p.get("date") or ""),
                                "side": str(_p.get("side") or ""),
                                "slot": str(_p.get("slot") or ""),
                                "code": str(_p.get("code") or ""),
                                "shares": float(_p.get("shares") or 0),
                                "nav": float(_p.get("nav") or 0),
                                "fee": float(_p.get("fee") or 0)}
                        if _new["shares"] > 0 and _new["date"]:
                            _held_edit = _held_on(_trades, _new["code"], _new["date"], skip=_i)
                            if _new["side"] == "卖出" and _new["shares"] > _held_edit + 1e-6:
                                st.session_state["_tr_err"] = (
                                    f"这一笔没保存：{FL.fund_name(_new['code']) or _new['code']} "
                                    f"到 {_cn_date(_new['date'])} 只持有 {_held_edit:,.2f} 份，"
                                    f"改完却要卖 {_new['shares']:,.2f} 份 —— 卖出超过持有会让账上多出现金。")
                            else:
                                _trades[_i] = {**_trades[_i], **_new}
                                save_acct(acct, ACCT_FILE)
                                st.toast("已保存这一笔", icon=":material/check_circle:")
                        else:
                            st.session_state["_tr_err"] = "这一笔没保存：日期或金额不对"
                st.rerun()
            if _dsig and _dsig != st.session_state.get("_tr_del_sig"):
                st.session_state["_tr_del_sig"] = _dsig
                _di = int(str(_dsig).split(":")[0])
                if 0 <= _di < len(_trades):
                    _trades.pop(_di)
                    save_acct(acct, ACCT_FILE)
                    st.toast("已删除这一笔", icon=":material/delete:")
                st.rerun()
        st.caption(f"账户文件：{ACCT_FILE.name}（保存在 data/ 下，重装或换机时记得备份）")


# ============================================================
# Tab 7: 基金检索（搜全市场基金 / 8 个回测资产，看日 / 月 / 年 的涨跌幅与价格）
# ============================================================
# 范围和采样粒度独立，切周期不改变所选范围。区间口径与支付宝「历史业绩」一致（见 _trend_window_start）。






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



@st.cache_data(ttl=600, show_spinner=False)
def _val_snapshot():
    """本地估值快照（不发请求，「更新数据」按钮负责刷新）。"""
    from allweather import valuation as _val
    return _val.load_snapshot()


def _val_tag_html(asset, code, name):
    """基金检索页头部的估值标签：能对应到跟踪指数时显示，否则返回空串。"""
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
               "我自己持仓的收益在「我的账户」看。")
    from streamlit_app.performance import render_performance
    render_performance(PROJECT_ROOT)


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

    # ---- 落到我持仓上的估值提醒（原来在独立的「提醒」tab）----
    st.divider()
    st.markdown('<div class="sec-head"><span class="t">我的持仓 · 贵不贵</span>'
                '<span class="r">按持仓基金匹配到的指数估值</span></div>',
                unsafe_allow_html=True)
    if not _al["估值"]:
        st.caption("持仓的基金暂时匹配不上指数估值 —— 蛋卷按指数代码收录，单只场外基金（如某某ETF联接A）"
                   "往往对不上，属于正常情况；看上面的指数表做参考即可。")
    for _x in _al["估值"]:
        st.markdown(_alert_card(
            _x["level"], f'{_x["name"]}（{_x["code"]}）',
            f'评分 {_x["score"]} · {_x["label"]}：{_x["action"]}'
            + (f' · PE/PB 百分位较高者 {_x["pct"]:.0f}%' if _x.get("pct") is not None else ""),
            "估值只作加减仓参考，不进策略信号；评分 ≥18 猎杀区、≤6 泡沫区"),
            unsafe_allow_html=True)
