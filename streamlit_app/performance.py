"""回测表现：三策略比较 / 调频影响。独立渲染，避免触发实盘页面副作用。"""
import hashlib
from html import escape
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from allweather.stats import comparison_metrics, comparison_slice, period_performance

STRATEGY_COLUMNS = {
    "V3c 多元": "V3c 多元_100% RP",
    "V3-B 风险平价": "V3-B 风险平价(20d)_100% RP",
    "V3-B 保守增强": "V3-B 保守增强(20d)_100% RP",
}
STRATEGY_COLORS = {"V3c 多元": "#8b5cf6", "V3-B 风险平价": "#2563eb", "V3-B 保守增强": "#d97706"}
FREQUENCIES = {"月频": "monthly", "双周频": "biweekly", "周频": "weekly"}

# 只作用于回测容器；保留项目字体和策略颜色，不影响账户/基金走势页。
PERFORMANCE_CSS = """
<style>
.st-key-perf_root {
  --perf-bg: #f4f6fa; --perf-surface: #ffffff; --perf-ink: #1e293b;
  --perf-muted: #526175; --perf-line: #e2e8f0; --perf-focus: #1d4ed8;
  --perf-up: #c52828; --perf-down: #16703b;
  --perf-caption: .8125rem; --perf-body: .9375rem;
  --perf-heading: 1.125rem; --perf-title: 1.875rem;
  color: var(--perf-ink); font-size: var(--perf-body); line-height: 1.5;
}
.st-key-perf_root h1 { font-size: var(--perf-title); line-height: 1.25; font-weight: 700; letter-spacing: -.02em; }
.st-key-perf_root h3, .st-key-perf_root h4 {
  font-size: var(--perf-heading); line-height: 1.4; font-weight: 600; letter-spacing: 0;
}
.st-key-perf_root p { line-height: 1.5; overflow-wrap: break-word; }
.st-key-perf_root [data-testid="stCaptionContainer"] { color: var(--perf-muted); font-size: var(--perf-caption); }
.perf-header { display: flex; justify-content: space-between; align-items: start; gap: 1rem; padding-block: .25rem .5rem; }
.perf-header h1 { margin: 0 0 .5rem; padding: 0; }
.perf-header p { margin: 0; color: var(--perf-muted); max-width: 62ch; }
.perf-header-note { font-size: var(--perf-caption); color: var(--perf-muted); white-space: nowrap; padding-block-start: .5rem; }
.st-key-perf_root .st-key-perf_controls {
  background: var(--perf-surface); border: 1px solid var(--perf-line); border-radius: 10px;
  padding: 1rem 1.25rem; gap: .875rem;
}
.st-key-perf_root [data-testid="stRadioGroup"] { flex-wrap: wrap; gap: .5rem; }
.st-key-perf_root [data-testid="stRadioOption"] {
  padding: .5rem .875rem; min-height: 44px; border-radius: 7px;
  background: var(--perf-bg); border: 1px solid transparent; cursor: pointer;
}
.st-key-perf_root [data-testid="stRadioOption"][data-selected="true"] {
  background: #eff5ff; border-color: #93b4eb; color: #1e40af;
}
.st-key-perf_root [data-testid="stRadioOption"] > div > div:first-child { display: none; }
.st-key-perf_root [data-testid="stRadioOption"] p { font-size: var(--perf-body); font-weight: 500; }
.st-key-perf_root [data-testid="stRadioOption"]:focus-within,
.st-key-perf_root [role="combobox"]:focus-visible,
.st-key-perf_root summary:focus-visible { outline: 2px solid var(--perf-focus); outline-offset: 3px; }
.st-key-perf_root [data-testid="stSelectbox"] [role="combobox"] { min-height: 44px; }
.st-key-perf_root [data-testid="stWidgetLabel"] p { color: var(--perf-muted); font-size: var(--perf-caption); }
.perf-context { display: flex; flex-wrap: wrap; justify-content: space-between; gap: .375rem 1.5rem;
  color: var(--perf-muted); font-size: var(--perf-caption); margin-block: .125rem .375rem; }
.perf-context strong { color: var(--perf-ink); font-weight: 600; }
.perf-kpis { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1rem; }
.perf-kpi { min-width: 0; padding: 1.125rem 1.25rem; background: var(--perf-surface);
  border: 1px solid var(--perf-line); border-radius: 10px; border-block-start: 3px solid var(--strategy); }
.perf-kpi h3 { margin: 0; padding: 0; font-size: 1rem; line-height: 1.5; }
.perf-kpi-label { margin-block: .875rem .125rem; color: var(--perf-muted); font-size: var(--perf-caption); }
.perf-kpi-number { font-size: clamp(1.625rem, 2.6vw, 2rem); font-weight: 650; line-height: 1.25;
  font-variant-numeric: tabular-nums; letter-spacing: -.01em; }
.perf-up { color: var(--perf-up); } .perf-down { color: var(--perf-down); } .perf-neutral { color: var(--perf-ink); }
.perf-kpi dl { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: .25rem .5rem;
  margin: .875rem 0 0; font-size: var(--perf-caption); }
.perf-kpi dt { color: var(--perf-muted); } .perf-kpi dd { margin: 0; font-weight: 500; font-variant-numeric: tabular-nums; text-align: end; }
.perf-kpi-reference { font-size: var(--perf-caption); color: var(--perf-muted); margin-block-start: .375rem; font-variant-numeric: tabular-nums; }
.st-key-perf_root .st-key-perf_charts { background: var(--perf-surface); border: 1px solid var(--perf-line);
  border-radius: 10px; padding: 1rem 1.25rem; gap: .5rem; margin-block-start: .75rem; }
.perf-legend { display: flex; flex-wrap: wrap; gap: .5rem 1.5rem; font-size: var(--perf-caption); color: var(--perf-muted); }
.perf-legend-item { display: inline-flex; align-items: center; gap: .5rem; }
.perf-legend-swatch { width: 22px; border-block-start: 3px solid var(--strategy); }
.perf-table-wrap { width: 100%; overflow-x: auto; border: 1px solid var(--perf-line); border-radius: 8px; background: var(--perf-surface); }
.perf-table-wrap:focus-visible { outline: 2px solid var(--perf-focus); outline-offset: 3px; }
.perf-table { width: 100%; border-collapse: collapse; font-size: var(--perf-caption); white-space: nowrap; }
.perf-table th, .perf-table td { padding: .75rem .875rem; text-align: end; font-variant-numeric: tabular-nums; }
.perf-table thead th { background: #f8fafc; color: var(--perf-muted); font-weight: 500; }
.perf-table th:first-child { text-align: start; }
.perf-table tbody tr + tr { border-block-start: 1px solid var(--perf-line); }
.perf-table tbody tr:hover { background: #f8fafc; }
.perf-table-note { margin-block: .5rem 0; font-size: var(--perf-caption); color: var(--perf-muted); }
.st-key-perf_root [data-testid="stExpander"] { box-shadow: none; border-radius: 8px !important; }
.st-key-perf_root [data-testid="stExpander"] summary { min-height: 44px; }
@media (max-width: 760px) {
  .perf-kpis { grid-template-columns: minmax(0, 1fr); gap: .75rem; }
  .perf-kpi { padding: .875rem 1rem; }
  .perf-kpi-number { font-size: 1.75rem; }
  .perf-kpi dl { margin-block-start: .625rem; }
  .perf-header-note { display: none; }
  .st-key-perf_root .st-key-perf_controls, .st-key-perf_root .st-key-perf_charts { padding: .875rem; }
  .st-key-perf_root [role="combobox"], .st-key-perf_root input { font-size: 1rem !important; }
}
@media (prefers-reduced-motion: reduce) {
  .st-key-perf_root *, .st-key-perf_root *::before, .st-key-perf_root *::after { transition: none !important; animation: none !important; }
}
</style>
"""


def _formatted(value, suffix="", signed=False):
    if not np.isfinite(value):
        return "—"
    return f"{value:+.2f}{suffix}" if signed else f"{value:.2f}{suffix}"


def _value_class(value):
    if not np.isfinite(value) or abs(value) < 0.005:
        return "perf-neutral"
    return "perf-up" if value > 0 else "perf-down"


def summary_cards_html(selected: pd.DataFrame, label: str, baseline=None, freq_label="月频") -> str:
    """卡片直接消费指标表原始数值；视觉层不另行计算收益。"""
    cards = []
    baseline = baseline.set_index("策略") if baseline is not None else None
    for _, row in selected.iterrows():
        strategy = row["策略"]
        increase, drawdown = row["涨幅(%)"], row["最大回撤(%)"]
        reference = ""
        details = []
        if baseline is not None:
            previous = baseline.loc[strategy]
            increase -= previous["涨幅(%)"]
            improvement = drawdown - previous["最大回撤(%)"]
            primary_label = "涨幅变化"
            primary_unit = " pp"
            reference = f'<div class="perf-kpi-reference">月频 {_formatted(previous["涨幅(%)"], "%", True)} → {escape(freq_label)} {_formatted(row["涨幅(%)"], "%", True)}</div>'
            details.append(("回撤变化", improvement, " pp", True))
            details.append((f"{freq_label}最大回撤", drawdown, "%", False))
        else:
            primary_label, primary_unit = "涨幅", "%"
            details.append(("最大回撤", drawdown, "%", False))
            for column, name in (("年化收益(%)", "年化收益"), ("年化波动(%)", "年化波动"),
                                 ("日收益波动(%)", "日收益波动"), ("夏普", "夏普")):
                if column in row:
                    details.append((name, row[column], "" if column == "夏普" else "%", False))
        values = "".join(f'<dt>{escape(name)}</dt><dd data-metric="{escape(name)}" data-value="{value:.12g}"'
                         f' class="{_value_class(value) if signed else "perf-neutral"}">{_formatted(value, suffix, signed)}</dd>'
                         for name, value, suffix, signed in details)
        cards.append(
            f'<article class="perf-kpi" style="--strategy:{STRATEGY_COLORS[strategy]}" aria-label="{escape(strategy)}，{escape(label)}">'
            f'<h3>{escape(strategy)}</h3><div class="perf-kpi-label">{escape(primary_label)}</div>'
            f'<div class="perf-kpi-number {_value_class(increase)}" data-metric="涨幅" data-value="{increase:.12g}">{_formatted(increase, primary_unit, True)}</div>'
            f'{reference}<dl>{values}</dl></article>'
        )
    return '<div class="perf-kpis">' + "".join(cards) + '</div>'


def comparison_versions(root: Path) -> tuple[str, str]:
    """内容指纹进入缓存键；行情、参数或引擎修改不会复用旧结果。"""
    data_hash, model_hash = hashlib.sha256(), hashlib.sha256()
    for path in sorted((root / "data").glob("*.csv")):
        if not path.name.startswith("price_"):
            data_hash.update(path.name.encode())
            data_hash.update(path.read_bytes())
    for name in ("config.py", "pipeline.py", "backtest.py", "strategy_b.py", "risk.py", "data.py"):
        model_hash.update((root / "allweather" / name).read_bytes())
    return data_hash.hexdigest(), model_hash.hexdigest()


@st.cache_data(show_spinner=False, max_entries=12)
def run_comparison(freq_key: str, data_version: str, model_version: str, root_path: str) -> dict:
    """一次计算指定频率的三策略；所有参数都参与缓存，统计视图不参与回测。"""
    from allweather.data import load_panel, load_series, _load_optional
    from allweather.pipeline import run_strategy_backtest

    # data.py 还有进程内文件缓存；数据指纹改变后的首次运行必须读新文件。
    load_series.cache_clear()
    _load_optional.cache_clear()
    rets = load_panel().pct_change().dropna()
    results = {}
    for strategy in STRATEGY_COLUMNS:
        nv, _, count, _, _ = run_strategy_backtest(
            rets, strategy, freq_key, track_weights=False, track_signals=False,
        )
        results[strategy] = {"nv": nv, "n_rebal": int(count)}
    return results


def load_saved_monthly(root: Path) -> dict:
    """缺列/坏数据显式报错，不静默退化为一个策略。"""
    from allweather.config import REBAL_FREQ

    if REBAL_FREQ != "monthly":
        raise ValueError("当前流水线不是月频，不能把已保存结果当月频基准；请将 REBAL_FREQ 设为 monthly 并重新生成")
    frame = pd.read_csv(root / "output" / "nv_curves.csv", index_col=0, parse_dates=True)
    missing = set(STRATEGY_COLUMNS.values()) - set(frame.columns)
    if missing:
        raise ValueError("已保存净值缺少策略列：" + "、".join(sorted(missing)))
    results = {}
    for strategy, column in STRATEGY_COLUMNS.items():
        nv = frame[column].dropna().sort_index()
        comparison_metrics(nv)  # 有限/正值、重复日期检查
        results[strategy] = {"nv": nv, "n_rebal": None}
    return results


def align_results(current: dict, monthly: dict | None = None) -> tuple[dict, dict | None]:
    """所有策略/频率使用相同观测日期；禁止补造收益。"""
    collections = [current] + ([monthly] if monthly is not None else [])
    series = [item["nv"] for group in collections for item in group.values()]
    common = series[0].index
    for nv in series[1:]:
        common = common.intersection(nv.index)
    common = common.sort_values()
    if len(common) < 2:
        raise ValueError("策略之间没有足够的共同净值日期")
    aligned = [{key: {**item, "nv": item["nv"].loc[common]} for key, item in group.items()}
               for group in collections]
    return aligned[0], aligned[1] if monthly is not None else None


def chart_frame(results: dict, granularity: str, start=None, end=None) -> pd.DataFrame:
    """图表数据统一采用 %；月/年回撤为每期内部回撤，不继承上一期高点。"""
    frames = []
    for strategy, item in results.items():
        nv = item["nv"]
        if granularity == "多年":
            seg = comparison_slice(nv, start, end)
            normalized = seg / seg.iloc[0]
            frame = pd.DataFrame({
                "date": seg.index,
                "收益": (normalized - 1).to_numpy() * 100,
                "回撤": (normalized / normalized.cummax() - 1).to_numpy() * 100,
            })
        else:
            periods = period_performance(nv, "M" if granularity == "月度" else "Y")
            frame = pd.DataFrame({
                "date": periods["date"], "收益": periods["cum_return"] * 100,
                "回撤": periods["mdd"] * 100,
            }).reset_index(drop=True)
            if start is not None:
                frame = frame.loc[frame["date"] >= pd.Timestamp(start)]
            if end is not None:
                frame = frame.loc[frame["date"] <= pd.Timestamp(end)]
        frame["策略"] = strategy
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def difference_frame(current: pd.DataFrame, baseline: pd.DataFrame, granularity: str) -> pd.DataFrame:
    """调频减月频；多年回撤差比较截至各日的最深回撤，正值表示改善。"""
    current, baseline = current.copy(), baseline.copy()
    if granularity == "多年":
        for frame in (current, baseline):
            frame["回撤"] = frame.groupby("策略", sort=False)["回撤"].cummin()
    merged = current.merge(baseline, on=["date", "策略"], suffixes=("", "_月频"), validate="one_to_one")
    for field in ("收益", "回撤"):
        merged[field] = merged[field] - merged[field + "_月频"]
    return merged[["date", "策略", "收益", "回撤"]]


def metric_rows(results: dict, start, end, granularity: str) -> pd.DataFrame:
    rows = []
    for strategy, item in results.items():
        seg = comparison_slice(item["nv"], start, end, include_prior=granularity != "多年")
        metrics = comparison_metrics(seg)
        row = {"策略": strategy, "涨幅(%)": metrics["cum_return"] * 100,
               "最大回撤(%)": metrics["mdd"] * 100}
        if granularity == "多年":
            row["年化收益(%)"] = metrics["cagr"] * 100
        if granularity == "月度":
            row["日收益波动(%)"] = metrics["daily_vol"] * 100
        else:
            row["年化波动(%)"] = metrics["vol"] * 100
            row["夏普"] = metrics["sharpe"]
        rows.append(row)
    return pd.DataFrame(rows)


def frequency_table(current: pd.DataFrame, baseline: pd.DataFrame, freq_label: str) -> pd.DataFrame:
    """每个策略一行，月频/调频/差值并排；先相减再四舍五入。"""
    cur, base = current.set_index("策略"), baseline.set_index("策略")
    rows = []
    for strategy in cur.index:
        row = {"策略": strategy}
        for field, name in (("涨幅(%)", "涨幅"), ("最大回撤(%)", "回撤")):
            row[f"月频{name}(%)"] = base.loc[strategy, field]
            row[f"{freq_label}{name}(%)"] = cur.loc[strategy, field]
            row[f"Δ{name}(pp)"] = cur.loc[strategy, field] - base.loc[strategy, field]
        rows.append(row)
    return pd.DataFrame(rows)


def _line_chart(frame: pd.DataFrame, field: str, title: str, granularity: str, delta=False, height=275):
    colors = alt.Scale(domain=list(STRATEGY_COLORS), range=list(STRATEGY_COLORS.values()))
    unit = "pp" if delta else "%"
    dates = "%-m月" if granularity == "月度" else "%Y年"
    axis = alt.Axis(format=dates, labelAngle=0, grid=False)
    if granularity != "多年":
        axis.values = sorted(frame["date"].drop_duplicates().tolist())
    # 选择同一日期，悬停同时列出三策略，避免凭曲线猜数值。
    hover = alt.selection_point(fields=["date"], nearest=True, on="pointerover", empty=False, clear="pointerout")
    base = alt.Chart(frame).encode(
        x=alt.X("date:T", title=None, axis=axis),
        y=alt.Y(f"{field}:Q", title=f"{title} ({unit})", scale=alt.Scale(zero=True)),
        color=alt.Color("策略:N", scale=colors, legend=None),
        strokeDash=alt.StrokeDash("策略:N", scale=alt.Scale(domain=list(STRATEGY_COLORS), range=[[1, 0], [7, 2], [2, 2]]), legend=None),
    )
    line = base.mark_line(strokeWidth=2.4, point=granularity != "多年")
    selectors = base.mark_point(opacity=0).add_params(hover)
    wide = frame.pivot(index="date", columns="策略", values=field).reset_index()
    rule = alt.Chart(wide).mark_rule(color="#94a3b8").encode(
        x="date:T", opacity=alt.condition(hover, alt.value(0.5), alt.value(0)),
        tooltip=[alt.Tooltip("date:T", title="日期", format="%Y/%m/%d")]
                + [alt.Tooltip(f"{s}:Q", title=f"{s} ({unit})", format="+.2f") for s in STRATEGY_COLUMNS],
    )
    zero = alt.Chart(pd.DataFrame({"zero": [0]})).mark_rule(color="#9ca3af", strokeDash=[3, 3]).encode(y="zero:Q")
    return ((line + selectors + rule + zero).properties(height=height)
            .configure_view(stroke=None).configure(background="#ffffff")
            .configure_axis(labelFontSize=12, titleFontSize=12, labelColor="#526175", titleColor="#526175",
                            gridColor="#edf1f5", domain=False, tickColor="#cbd5e1", titlePadding=12))


def _legend_html():
    styles = ["solid", "dashed", "dotted"]
    return '<div class="perf-legend" aria-label="图例">' + "".join(
        f'<span class="perf-legend-item"><span class="perf-legend-swatch" aria-hidden="true" '
        f'style="--strategy:{color};border-block-start-style:{line_style}"></span>{escape(strategy)}</span>'
        for (strategy, color), line_style in zip(STRATEGY_COLORS.items(), styles)
    ) + '</div>'


def _primary_table(frame: pd.DataFrame):
    """主要比较表保留HTML语义与可选择数值；窄屏只滚动表格，不撑宽页面。"""
    columns = list(frame.columns)
    header = "".join(f'<th scope="col">{escape(col)}</th>' for col in columns)
    rows = []
    for _, row in frame.iterrows():
        cells = [f'<th scope="row">{escape(str(row[columns[0]]))}</th>']
        for col in columns[1:]:
            value = row[col]
            css = _value_class(value) if col.startswith("Δ") or col == "涨幅(%)" else "perf-neutral"
            cells.append(f'<td class="{css}">{_formatted(value, signed=col.startswith("Δ"))}</td>')
        rows.append('<tr>' + "".join(cells) + '</tr>')
    st.markdown('<div class="perf-table-wrap" role="region" aria-label="精确指标对比表，可左右滚动" tabindex="0">'
                '<table class="perf-table"><thead><tr>' + header + '</tr></thead><tbody>' + "".join(rows)
                + '</tbody></table></div><p class="perf-table-note">表格可横向滚动查看全部列；详细数据可在下方展开。</p>', unsafe_allow_html=True)


def _table(frame: pd.DataFrame):
    numeric = frame.select_dtypes(include="number").columns
    st.dataframe(frame, width="stretch", hide_index=True,
                 column_config={col: st.column_config.NumberColumn(col, format="%.2f") for col in numeric})


def render_performance(project_root: Path):
    st.markdown(PERFORMANCE_CSS, unsafe_allow_html=True)
    with st.container(key="perf_root"):
        _render_performance(project_root)


def _render_performance(project_root: Path):
    st.markdown('<header class="perf-header"><div><h1>回测表现</h1>'
                '<p>把收益与风险放在一起，看清三种策略的长期表现和调频影响。</p></div>'
                '<span class="perf-header-note">全天候策略研究</span></header>', unsafe_allow_html=True)
    controls = st.container(key="perf_controls")
    with controls:
        view = st.radio("比较对象", ["三策略对比", "调频影响"], horizontal=True, key="perf_view_v2")
        scale, control = st.columns([2, 1])
        with scale:
            granularity = st.radio("时间粒度", ["多年", "年度", "月度"], horizontal=True, key="perf_granularity_v2")
        with control:
            if view == "三策略对比":
                freq_label = st.selectbox("调仓频率", list(FREQUENCIES), key="perf_frequency_v2")
            else:
                freq_label = st.selectbox("对比月频的调仓频率", ["双周频", "周频"], key="perf_impact_frequency_v2")
    freq_key = FREQUENCIES[freq_label]
    try:
        saved = load_saved_monthly(project_root)
        monthly, current = saved, saved
        source = "output/nv_curves.csv（已保存月频）"
        if freq_key != "monthly":
            data_version, model_version = comparison_versions(project_root)
            with st.spinner(f"加载三策略{freq_label}与同口径月频基准；结果按数据与参数版本缓存"):
                monthly = run_comparison("monthly", data_version, model_version, str(project_root))
                current = run_comparison(freq_key, data_version, model_version, str(project_root))
            unchanged = all(saved[s]["nv"].index.equals(monthly[s]["nv"].index)
                            and np.allclose(saved[s]["nv"], monthly[s]["nv"], rtol=1e-10, atol=1e-12)
                            for s in STRATEGY_COLUMNS)
            if not unchanged:
                st.warning("已保存结果与当前数据/参数不一致，本次调频比较已改用同数据、同参数重新计算的月频基准，不混用旧结果。")
            source = "本地 data/ · 流水线共用参数 · 同版本现场回测（缓存）"
        current, monthly = align_results(current, monthly)
        index = current[next(iter(STRATEGY_COLUMNS))]["nv"].index
        first, last = index[0], index[-1]
        with controls:
            if granularity == "多年":
                span = st.selectbox("比较区间", ["全部历史", "近10年", "近5年", "近3年", "近1年"], key="perf_span_v2")
                start = first if span == "全部历史" else max(first, last - pd.DateOffset(years=int(span[1:-1])))
                end = last
                chart_start, chart_end = start, end
                label = f"{comparison_slice(current[next(iter(STRATEGY_COLUMNS))]['nv'], start).index[0]:%Y/%m/%d} ～ {end:%Y/%m/%d}"
            elif granularity == "年度":
                years = sorted(set(index[1:].year), reverse=True)
                year = st.selectbox("指标年份", years, key="perf_year_v2")
                start, end = pd.Timestamp(year, 1, 1), pd.Timestamp(year, 12, 31)
                chart_start, chart_end = None, None
                label = f"{year}年" + (f"（截至 {last:%m-%d}）" if year == last.year else "")
            else:
                year_col, month_col = st.columns(2)
                with year_col:
                    year = st.selectbox("查看年份", sorted(set(index[1:].year), reverse=True), key="perf_month_year_v2")
                months = sorted(set(index[1:][index[1:].year == year].month), reverse=True)
                with month_col:
                    month = st.selectbox("指标月份", months, format_func=lambda m: f"{m}月", key="perf_month_v2")
                start = pd.Timestamp(year, month, 1)
                end = start + pd.offsets.MonthEnd(0)
                chart_start, chart_end = pd.Timestamp(year, 1, 1), pd.Timestamp(year, 12, 31)
                label = f"{year}年{month}月" + (f"（截至 {last:%m-%d}）" if end > last else "")
        st.markdown(f'<div class="perf-context"><span>共同数据区间 <strong>{first:%Y/%m/%d} ～ {last:%Y/%m/%d}</strong></span>'
                    f'<span>{escape(freq_label)} · {escape(source)}</span></div>', unsafe_allow_html=True)
        selected = metric_rows(current, start, end, granularity)
        baseline_metrics = metric_rows(monthly, start, end, granularity) if view == "调频影响" else None
        st.markdown(f"#### {'指标对比' if view == '三策略对比' else f'月频 → {freq_label}'} · {label}")
        st.markdown(summary_cards_html(selected, label, baseline_metrics, freq_label), unsafe_allow_html=True)
        frame = chart_frame(current, granularity, chart_start, chart_end)
        if view == "三策略对比":
            chart_title = f"{year}年各月涨幅" if granularity == "月度" else {"多年": "累计涨幅", "年度": "各年涨幅"}[granularity]
            with st.container(key="perf_charts"):
                st.markdown(_legend_html(), unsafe_allow_html=True)
                st.markdown(f"#### {chart_title} · {freq_label}")
                st.altair_chart(_line_chart(frame, "收益", chart_title, granularity), width="stretch")
                drawdown_title = {"多年": "区间回撤走势", "年度": "各年期内最大回撤", "月度": "各月期内最大回撤"}[granularity]
                st.markdown(f"#### {drawdown_title}")
                st.altair_chart(_line_chart(frame, "回撤", drawdown_title, granularity, height=195), width="stretch")
                st.caption("悬停同一日期查看三策略数值；颜色与实线、虚线、点线共同区分策略。")
            st.markdown("#### 精确指标")
            _primary_table(selected)
            with st.expander("原始指标数据与下载"):
                _table(selected)
        else:
            baseline_frame = chart_frame(monthly, granularity, chart_start, chart_end)
            differences = difference_frame(frame, baseline_frame, granularity)
            with st.container(key="perf_charts"):
                st.markdown(_legend_html(), unsafe_allow_html=True)
                st.markdown(f"#### 调频后多赚 / 少赚了多少 · {freq_label} − 月频")
                st.altair_chart(_line_chart(differences, "收益", "涨幅差", granularity, delta=True), width="stretch")
                st.markdown("#### 回撤改善 / 恶化了多少")
                st.altair_chart(_line_chart(differences, "回撤", "最大回撤差", granularity, delta=True, height=195), width="stretch")
                st.caption("零线上方＝涨幅增加 / 回撤变浅；零线下方＝涨幅减少 / 回撤变深。差值单位是百分点 pp。")
            st.markdown("#### 精确差值")
            _primary_table(frequency_table(selected, baseline_metrics, freq_label))
            with st.expander("其他指标：收益年化、波动与夏普对比"):
                advanced = selected.copy()
                baseline_advanced = baseline_metrics.copy()
                advanced.insert(1, "频率", freq_label)
                baseline_advanced.insert(1, "频率", "月频")
                _table(pd.concat([baseline_advanced, advanced], ignore_index=True))
                extra_fields = [c for c in selected.columns if c not in {"策略", "涨幅(%)", "最大回撤(%)"}]
                changes = selected.set_index("策略")[extra_fields] - baseline_metrics.set_index("策略")[extra_fields]
                changes.columns = ["Δ" + c.replace("(%)", "(pp)") for c in changes.columns]
                _table(changes.reset_index())
                st.caption("上表为调频减月频：收益年化差正值为增加，波动差负值为降低，夏普差正值为提高。")
                if granularity == "多年":
                    count_rows = [{"策略": s, "月频调仓次数": monthly[s]["n_rebal"],
                                   f"{freq_label}调仓次数": current[s]["n_rebal"]} for s in STRATEGY_COLUMNS]
                    _table(pd.DataFrame(count_rows))
                    st.caption("调仓次数为完整历史的引擎触发次数，非所选多年区间的成交笔数。")
        if granularity != "多年":
            st.caption("月/年涨幅包含期首第一天相对上期末的收益；期内最大回撤以期前净值为起点，每期重新计算。首尾月/年可能不完整。")
            with st.expander("逐期精确指标（按需查看，不重复铺开图表）"):
                detail = []
                for strategy, item in current.items():
                    periods = period_performance(item["nv"], "M" if granularity == "月度" else "Y")
                    if granularity == "月度":
                        periods = periods.loc[periods.index.year == year]
                    for period, row in periods.iterrows():
                        detail.append({"期间": str(period), "策略": strategy, "涨幅(%)": row["cum_return"] * 100,
                                       "最大回撤(%)": row["mdd"] * 100, "日收益波动(%)": row["daily_vol"] * 100})
                _table(pd.DataFrame(detail).sort_values(["期间", "策略"]))
        with st.expander("统计口径与回测限制"):
            st.markdown(
                "- 三策略共享日期窗口；多年曲线从所选区间首个净值归一化。年度图比较自然年，月度图比较所选年份的自然月。\n"
                "- 年化收益、年化波动和夏普沿用报告的 **252 观测日/年** 口径；夏普＝（年化收益−无风险收益）/年化波动。短期年化指标仅供描述，月度优先显示日收益波动。\n"
                "- 多年调频回撤差比较截至每个日期的区间最深回撤；月/年调频回撤差比较当期内部最大回撤。\n"
                "- 月频默认读已保存文件；该文件缺少完整运行元数据，加载其他频率时会重算并校验月频，避免参数或数据漂移。\n"
                "- 使用既有累计净值/指数代理历史，不等于场内ETF实盘；净值未扣调仓佣金、滑点。历史面板有非交易日记录，初始权重使用开头窗口估计，存在初期前视偏差。\n"
                "- 双周沿用引擎的 ISO 偶数周最后观测日规则，不是连续每14天。本次仅改展示与比较口径，不修改调仓规则。\n"
                "- 历史回测不预示未来收益，不据此预先判定月频或高频一定更优。"
            )
        # 渲染末尾的状态标记便于验证异步视图更新，避免测试读取上一视图的图表。
        summary = f"{'指标对比' if view == '三策略对比' else f'月频 → {freq_label}'} · {label}"
        st.markdown(f'<span class="perf-render-state" hidden aria-hidden="true" '
                    f'data-summary="{escape(summary)}" data-granularity="{granularity}"></span>', unsafe_allow_html=True)
    except (OSError, ValueError, KeyError) as exc:
        st.error(f"无法完成三策略比较：{exc}")
        st.info("请检查本地数据及 output/nv_curves.csv；缺少基准时先用 myenv 环境运行 main.py。")
