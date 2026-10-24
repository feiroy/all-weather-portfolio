"""性能比较回归：仅合成数据，不导入 app.py，不读取账户或运行真实回测。"""
import inspect
from unittest.mock import Mock, create_autospec

import numpy as np
import pandas as pd
import pytest

from allweather import config, data, pipeline
from allweather.stats import comparison_metrics, comparison_slice, period_performance
from streamlit_app import performance


STRATEGIES = ("V3c 多元", "V3-B 风险平价", "V3-B 保守增强")
FREQUENCIES = ("monthly", "biweekly", "weekly")
PERIOD_CASES = (("M", "月度"), ("Y", "年度"))


def series(values, dates):
    return pd.Series(values, index=pd.to_datetime(dates), dtype=float, name="nv")


def expected_metrics(values):
    """独立预期：直接用相邻比值与逐点高水位，不调用生产统计函数。"""
    values = np.asarray(values, dtype=float)
    returns = values[1:] / values[:-1] - 1
    peak, mdd = values[0], 0.0
    for value in values:
        peak = max(peak, value)
        mdd = min(mdd, value / peak - 1)
    daily_vol = np.std(returns, ddof=1) if len(returns) > 1 else np.nan
    cumulative = values[-1] / values[0] - 1
    cagr = (values[-1] / values[0]) ** (252 / len(returns)) - 1
    vol = daily_vol * np.sqrt(252)
    return {
        "cum_return": cumulative, "mdd": mdd, "daily_vol": daily_vol,
        "n_years": len(returns) / 252, "cagr": cagr, "vol": vol,
        "sharpe": (cagr - config.RISK_FREE_ANNUAL) / vol if vol > 0 else np.nan,
        "final_nv": values[-1] / values[0],
    }


@pytest.fixture(autouse=True)
def forbid_real_io_and_backtests(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("性能单元测试禁止读取真实 CSV、加载真实面板或执行真实回测")

    monkeypatch.setattr(pd, "read_csv", forbidden)
    monkeypatch.setattr(data, "load_panel", forbidden)
    monkeypatch.setattr(pipeline, "load_panel", forbidden)
    monkeypatch.setattr(pipeline, "backtest_iv", forbidden)
    monkeypatch.setattr(pipeline, "backtest_b", forbidden)


@pytest.fixture
def synthetic_results():
    dates = [
        "2022-12-29", "2022-12-30", "2023-01-01", "2023-01-03",
        "2023-01-31", "2023-02-01", "2023-02-03", "2023-02-28",
        "2023-12-29", "2024-01-01", "2024-01-03", "2024-01-31",
        "2024-02-01", "2024-02-29", "2024-12-31", "2025-01-01",
        "2025-01-03",
    ]
    paths = (
        [200, 100, 90, 94, 95, 85.5, 92, 94, 100, 88, 91, 93, 96, 97, 104, 99, 103],
        [350, 175, 166, 171, 173, 180, 170, 177, 182, 170, 178, 180, 181, 179, 190, 180, 184],
        [500, 250, 245, 248, 249, 247, 248, 250, 253, 249, 251, 252, 255, 253, 260, 258, 259],
    )
    return {
        strategy: {"nv": series(values, dates), "n_rebal": i + 5}
        for i, (strategy, values) in enumerate(zip(STRATEGIES, paths))
    }


@pytest.mark.parametrize("freq,granularity", PERIOD_CASES)
def test_period_first_day_return_and_drawdown_include_prior_close(freq, granularity):
    nv = series([200, 100, 90, 95], ["2023-12-28", "2023-12-31", "2024-01-01", "2024-01-05"])
    start, end = "2024-01-01", "2024-01-31" if freq == "M" else "2024-12-31"
    period = pd.Period(start, freq=freq)
    row = period_performance(nv, freq).loc[period]
    assert row["cum_return"] == pytest.approx(-0.05)
    assert row["mdd"] == pytest.approx(-0.10)
    assert row["first_date"] == pd.Timestamp(start)
    assert row["last_date"] == pd.Timestamp("2024-01-05")
    assert row["n_years"] == pytest.approx(2 / 252)
    results = {STRATEGIES[0]: {"nv": nv, "n_rebal": 1}}
    selected = performance.metric_rows(results, start, end, granularity).iloc[0]
    plotted = performance.chart_frame(results, granularity).set_index("date").loc[pd.Timestamp(start)]
    assert selected["涨幅(%)"] == pytest.approx(-5)
    assert selected["最大回撤(%)"] == pytest.approx(-10)
    assert plotted["收益"] == pytest.approx(-5)
    assert plotted["回撤"] == pytest.approx(-10)


@pytest.mark.parametrize("freq,dates,target", [
    ("M", ["2024-01-01", "2024-01-31", "2024-02-01", "2024-02-29"], "2024-02"),
    ("Y", ["2023-01-01", "2023-12-31", "2024-01-01", "2024-12-31"], "2024"),
])
def test_drawdown_resets_at_every_period(freq, dates, target):
    nv = series([200, 100, 110, 105], dates)
    row = period_performance(nv, freq).loc[pd.Period(target, freq=freq)]
    assert row["cum_return"] == pytest.approx(0.05)
    assert row["mdd"] == pytest.approx(105 / 110 - 1)
    assert row["mdd"] > -0.05
    assert comparison_metrics(nv)["mdd"] == pytest.approx(-0.50)


@pytest.mark.parametrize("include_prior,expected_dates", [
    (False, ["2024-02-02", "2024-02-05"]),
    (True, ["2024-01-31", "2024-02-02", "2024-02-05"]),
])
def test_comparison_slice_sorts_drops_nan_and_takes_only_last_prior(include_prior, expected_dates):
    nv = series([110, 90, np.nan, 105, 100, 80], [
        "2024-02-06", "2024-01-30", "2024-02-01", "2024-02-05", "2024-02-02", "2024-01-31",
    ])
    before = nv.copy(deep=True)
    actual = comparison_slice(nv, "2024-02-01", "2024-02-05", include_prior=include_prior)
    pd.testing.assert_series_equal(actual, nv.loc[pd.to_datetime(expected_dates)])
    pd.testing.assert_series_equal(nv, before)
    assert actual.index.isin(nv.index).all()


@pytest.mark.parametrize("start,end,expected", [
    (None, None, [0, 1, 2]),
    (None, "2024-01-02", [0, 1]),
    ("2024-01-02", None, [1, 2]),
    ("2024-01-02", "2024-01-02", [1]),
])
def test_comparison_slice_optional_and_inclusive_bounds(start, end, expected):
    nv = series([10, 11, 12], ["2024-01-01", "2024-01-02", "2024-01-03"])
    pd.testing.assert_series_equal(comparison_slice(nv, start, end), nv.iloc[expected])


@pytest.mark.parametrize("date_freq", ["D", "3D", "B"])
def test_comparison_metrics_nonunit_start_and_252_observation_annualization(date_freq):
    daily = np.tile([0.001, -0.0005, 0.002, -0.001], 63)
    values = 7.25 * np.r_[1, np.cumprod(1 + daily)]
    nv = pd.Series(values, index=pd.date_range("2020-01-01", periods=253, freq=date_freq))
    actual, expected = comparison_metrics(nv), expected_metrics(values)
    for field, value in expected.items():
        assert actual[field] == pytest.approx(value), field
    assert actual["n_years"] == 1
    assert actual["cagr"] == pytest.approx(actual["cum_return"])
    scaled = comparison_metrics(nv * 23)
    for field in expected:
        assert scaled[field] == pytest.approx(actual[field]), field


@pytest.mark.parametrize("values", [[], [1], [np.nan, 1], [1, 0], [1, -1], [1, np.inf], [1, -np.inf]])
def test_comparison_metrics_rejects_invalid_nav(values):
    nv = pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values)), dtype=float)
    with pytest.raises(ValueError, match="至少两条有限、正值净值"):
        comparison_metrics(nv)


def test_comparison_metrics_rejects_duplicate_dates():
    with pytest.raises(ValueError, match="净值日期不能重复"):
        comparison_metrics(series([1, 2], ["2024-01-01", "2024-01-01"]))


@pytest.mark.parametrize("freq,granularity", PERIOD_CASES)
def test_period_detail_selected_metrics_and_chart_share_independent_expected_values(synthetic_results, freq, granularity):
    chart = performance.chart_frame(synthetic_results, granularity)
    count = 0
    for strategy, item in synthetic_results.items():
        nv = item["nv"]
        # 初始净值仅作基准；之后每个观测按所属自然期分组。
        positions = {}
        for i in range(1, len(nv)):
            positions.setdefault(nv.index[i].to_period(freq), []).append(i)
        detail = period_performance(nv, freq)
        assert list(detail.index) == list(positions)
        for period, indices in positions.items():
            expected = expected_metrics(nv.iloc[indices[0] - 1:indices[-1] + 1])
            row = detail.loc[period]
            for field, value in expected.items():
                assert row[field] == pytest.approx(value, nan_ok=True), (strategy, period, field)
            assert row["date"] == period.start_time
            assert row["first_date"] == nv.index[indices[0]]
            assert row["last_date"] == nv.index[indices[-1]]
            selected = performance.metric_rows(synthetic_results, period.start_time, period.end_time, granularity)
            selected = selected.set_index("策略").loc[strategy]
            point = chart.loc[(chart["策略"] == strategy) & (chart["date"] == period.start_time)]
            assert len(point) == 1
            assert point.iloc[0]["收益"] == pytest.approx(expected["cum_return"] * 100)
            assert point.iloc[0]["回撤"] == pytest.approx(expected["mdd"] * 100)
            assert selected["涨幅(%)"] == pytest.approx(point.iloc[0]["收益"])
            assert selected["最大回撤(%)"] == pytest.approx(point.iloc[0]["回撤"])
            if granularity == "月度":
                assert selected["日收益波动(%)"] == pytest.approx(expected["daily_vol"] * 100, nan_ok=True)
                assert "年化收益(%)" not in selected.index
                assert "夏普" not in selected.index
            else:
                assert selected["年化波动(%)"] == pytest.approx(expected["vol"] * 100, nan_ok=True)
                assert selected["夏普"] == pytest.approx(expected["sharpe"], nan_ok=True)
            count += 1
    assert len(chart) == count


@pytest.mark.parametrize("freq,granularity", PERIOD_CASES)
def test_period_chart_filters_calendar_labels_inclusively(synthetic_results, freq, granularity):
    start, end = pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31")
    whole = performance.chart_frame(synthetic_results, granularity)
    filtered = performance.chart_frame(synthetic_results, granularity, start, end)
    expected = whole.loc[whole["date"].between(start, end)].reset_index(drop=True)
    pd.testing.assert_frame_equal(filtered, expected)
    assert set(filtered["策略"]) == set(STRATEGIES)


def test_multiyear_chart_normalizes_visible_start_and_resets_drawdown(synthetic_results):
    start, end = "2023-01-03", "2024-02-29"
    chart = performance.chart_frame(synthetic_results, "多年", start, end)
    metrics = performance.metric_rows(synthetic_results, start, end, "多年").set_index("策略")
    for strategy, item in synthetic_results.items():
        nv = item["nv"].loc[start:end]
        normalized = nv.to_numpy() / nv.iloc[0]
        plotted = chart.loc[chart["策略"] == strategy]
        np.testing.assert_array_equal(plotted["date"], nv.index)
        np.testing.assert_allclose(plotted["收益"], (normalized - 1) * 100)
        np.testing.assert_allclose(plotted["回撤"], (normalized / np.maximum.accumulate(normalized) - 1) * 100)
        assert plotted.iloc[0]["收益"] == 0
        assert plotted.iloc[0]["回撤"] == 0
        expected = expected_metrics(nv)
        for column, field in (("涨幅(%)", "cum_return"), ("最大回撤(%)", "mdd"),
                              ("年化收益(%)", "cagr"), ("年化波动(%)", "vol")):
            assert metrics.loc[strategy, column] == pytest.approx(expected[field] * 100)
        assert metrics.loc[strategy, "夏普"] == pytest.approx(expected["sharpe"])


@pytest.mark.parametrize("with_monthly", [False, True])
def test_align_results_uses_sorted_intersection_without_filling_or_mutation(synthetic_results, with_monthly):
    current = {s: {**item, "nv": item["nv"].iloc[i:].iloc[::-1]} for i, (s, item) in enumerate(synthetic_results.items())}
    monthly = {s: {**item, "nv": item["nv"].iloc[3:-1].drop(item["nv"].index[5]) * 2} for s, item in synthetic_results.items()} if with_monthly else None
    groups = [current] + ([monthly] if monthly is not None else [])
    originals = [[{**item, "nv": item["nv"].copy(deep=True)} for item in group.values()] for group in groups]
    common = sorted(set.intersection(*(set(item["nv"].index) for group in groups for item in group.values())))
    aligned_current, aligned_monthly = performance.align_results(current, monthly)
    aligned_groups = [aligned_current] + ([aligned_monthly] if with_monthly else [])
    if not with_monthly:
        assert aligned_monthly is None
    for source, snapshots, aligned in zip(groups, originals, aligned_groups):
        assert source is not aligned
        for (strategy, item), before in zip(source.items(), snapshots):
            pd.testing.assert_series_equal(item["nv"], before["nv"])
            pd.testing.assert_series_equal(aligned[strategy]["nv"], before["nv"].loc[common])
            assert aligned[strategy]["n_rebal"] == item["n_rebal"]
    chart = performance.chart_frame(aligned_current, "多年")
    for strategy in STRATEGIES:
        assert chart.loc[chart["策略"] == strategy, "date"].tolist() == common


@pytest.mark.parametrize("shared_dates", [0, 1])
def test_align_results_rejects_insufficient_shared_dates(shared_dates):
    a = series([1, 2, 3], ["2024-01-01", "2024-01-02", "2024-01-03"])
    b = series([4, 5], ["2024-01-03" if shared_dates else "2024-01-04", "2024-01-05"])
    with pytest.raises(ValueError, match="没有足够的共同净值日期"):
        performance.align_results({"a": {"nv": a}}, {"b": {"nv": b}})


@pytest.mark.parametrize("granularity", ["月度", "年度", "多年"])
def test_difference_frame_joins_dates_and_strategies_and_keeps_delta_precision(granularity):
    dates = pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01"])
    current_rows, baseline_rows = [], []
    for factor, strategy in enumerate(STRATEGIES, start=1):
        for i, day in enumerate(dates):
            current_rows.append({"date": day, "策略": strategy, "收益": factor * [1.004, 0.4, 0.9][i], "回撤": factor * [-1.004, -0.5, -3][i]})
            baseline_rows.append({"date": day, "策略": strategy, "收益": factor * [1.003, 0.6, 0.7][i], "回撤": factor * [-1.006, -0.1, -2][i]})
    current = pd.DataFrame(current_rows)
    # 图表保证每个策略按日期递增；只打乱策略组，避免给内部接口造逆序时间。
    baseline = pd.DataFrame(baseline_rows).iloc[[6, 7, 8, 3, 4, 5, 0, 1, 2]].reset_index(drop=True)
    before_cur, before_base = current.copy(deep=True), baseline.copy(deep=True)
    actual = performance.difference_frame(current, baseline, granularity)
    assert len(actual) == 9
    for factor, strategy in enumerate(STRATEGIES, start=1):
        rows = actual.loc[actual["策略"] == strategy].set_index("date").loc[dates]
        np.testing.assert_allclose(rows["收益"], np.array([0.001, -0.2, 0.2]) * factor, atol=1e-12)
        expected_dd = [0.002, 0.002, -1] if granularity == "多年" else [0.002, -0.4, -1]
        np.testing.assert_allclose(rows["回撤"], np.array(expected_dd) * factor, atol=1e-12)
    pd.testing.assert_frame_equal(current, before_cur)
    pd.testing.assert_frame_equal(baseline, before_base)
    reduced = baseline.loc[baseline["date"] != dates[1]]
    intersection = performance.difference_frame(current, reduced, granularity)
    assert len(intersection) == 6
    assert set(intersection["date"]) == {dates[0], dates[2]}


@pytest.mark.parametrize("freq_label", ["双周频", "周频"])
def test_frequency_table_subtracts_unrounded_values_and_matches_by_strategy(freq_label):
    current = pd.DataFrame({"策略": STRATEGIES, "涨幅(%)": [1.004, 3, -1], "最大回撤(%)": [-1.004, -3, -2]})
    baseline = pd.DataFrame({"策略": STRATEGIES, "涨幅(%)": [1.003, 4, -2], "最大回撤(%)": [-1.006, -2, -3]}).iloc[::-1]
    before_cur, before_base = current.copy(deep=True), baseline.copy(deep=True)
    actual = performance.frequency_table(current, baseline, freq_label)
    assert actual["策略"].tolist() == list(STRATEGIES)
    np.testing.assert_allclose(actual["Δ涨幅(pp)"], [0.001, -1, 1], atol=1e-12)
    np.testing.assert_allclose(actual["Δ回撤(pp)"], [0.002, -1, 1], atol=1e-12)
    assert actual.iloc[0]["Δ涨幅(pp)"] != round(1.004, 2) - round(1.003, 2)
    assert actual.iloc[0]["Δ回撤(pp)"] != round(-1.004, 2) - round(-1.006, 2)
    for field, label in (("涨幅(%)", "涨幅"), ("最大回撤(%)", "回撤")):
        np.testing.assert_allclose(actual[f"{freq_label}{label}(%)"], current[field])
        np.testing.assert_allclose(actual[f"月频{label}(%)"], baseline.set_index("策略").loc[list(STRATEGIES), field])
    pd.testing.assert_frame_equal(current, before_cur)
    pd.testing.assert_frame_equal(baseline, before_base)


def expected_strategy_kwargs(strategy, frequency):
    common = dict(cash_ratio=0.0, nonferr_trend_window=75, wti_trend_window=75,
                  hs300_value_dip=True, gold_dip_threshold=None, rebal_freq=frequency)
    if strategy == "V3c 多元":
        params = dict(assets=config.V3C_ASSETS, iv_window=config.STRATEGY_PARAMS["v3c"]["window"],
                      max_w=config.STRATEGY_PARAMS["v3c"]["max_w"], min_w=config.STRATEGY_PARAMS["v3c"]["min_w"],
                      gold_trend_filter=True, gold_trend_window=75, gold_dip_cap=0.20,
                      equity_trend_assets=["us_sp500"], equity_trend_window=75)
    elif strategy == "V3-B 风险平价":
        params = dict(rp_buckets=config.V3B_RP_BUCKETS, rp_window=config.STRATEGY_PARAMS["rp"]["window"],
                      gold_trend_filter=True, gold_trend_window=75,
                      equity_trend_assets=["us_sp500", "hs300"],
                      equity_trend_windows={"us_sp500": config.SP500_TREND_WINDOW, "hs300": config.HS300_TREND_WINDOW},
                      target_vol=config.RISK_PARITY_TARGET_VOL, vol_target_window=config.RISK_PARITY_COV_WINDOW)
    else:
        params = dict(rp_window=config.STRATEGY_PARAMS["con"]["window"], max_w=config.STRATEGY_PARAMS["con"]["max_w"],
                      weighting_method="inverse_vol", gold_dip_cap=0.20)
    return {**common, **params}


@pytest.mark.parametrize("frequency", FREQUENCIES)
@pytest.mark.parametrize("strategy", STRATEGIES)
def test_all_strategy_frequency_parameters(strategy, frequency):
    assert performance.FREQUENCIES == {"月频": "monthly", "双周频": "biweekly", "周频": "weekly"}
    assert tuple(performance.STRATEGY_COLUMNS) == STRATEGIES
    assert pipeline.strategy_backtest_kwargs(strategy, frequency) == expected_strategy_kwargs(strategy, frequency)
    if frequency == "monthly":
        assert pipeline.strategy_backtest_kwargs(strategy) == expected_strategy_kwargs(strategy, "monthly")


@pytest.mark.parametrize("frequency", FREQUENCIES)
@pytest.mark.parametrize("strategy", STRATEGIES)
def test_run_strategy_dispatches_correct_engine_assets_and_runtime(monkeypatch, strategy, frequency):
    from allweather.backtest import backtest_iv
    from allweather.strategy_b import backtest_b

    dates = pd.date_range("2024-01-01", periods=4)
    columns = list(reversed(config.ASSETS)) + ["extra"]
    rets = pd.DataFrame(np.arange(4 * len(columns)).reshape(4, -1) / 10000, index=dates, columns=columns)
    before = rets.copy(deep=True)
    result = (series([1, 1.01], dates[:2]), None, 7, "合成权重", "合成信号")
    iv, b = create_autospec(backtest_iv, return_value=result), create_autospec(backtest_b, return_value=result)
    monkeypatch.setattr(pipeline, "backtest_iv", iv)
    monkeypatch.setattr(pipeline, "backtest_b", b)
    pb = pd.Series([1, 2, 3, 4], index=dates)
    runtime = dict(track_weights=True, track_signals=False, track_dynamic_nav=False, signal_label="合成测试", hs300_pb_data=pb)
    assert pipeline.run_strategy_backtest(rets, strategy, frequency, **runtime) is result
    chosen, unused = (iv, b) if strategy == "V3c 多元" else (b, iv)
    chosen.assert_called_once()
    unused.assert_not_called()
    args, kwargs = chosen.call_args
    assets = config.V3B_RP_ASSETS if strategy == "V3-B 风险平价" else config.V3B_CON_ASSETS
    expected_rets = rets if strategy == "V3c 多元" else rets[assets]
    pd.testing.assert_frame_equal(args[0], expected_rets)
    expected = expected_strategy_kwargs(strategy, frequency)
    assert set(kwargs) == set(expected) | set(runtime)
    for key, value in expected.items():
        assert kwargs[key] == value, key
    for key, value in runtime.items():
        assert kwargs[key] is value if key == "hs300_pb_data" else kwargs[key] == value
    if strategy != "V3c 多元":
        effective = inspect.signature(backtest_b).bind(*args, **kwargs)
        effective.apply_defaults()
        strategy_key = "rp" if strategy == "V3-B 风险平价" else "con"
        assert effective.arguments["max_w"] == config.STRATEGY_PARAMS[strategy_key]["max_w"]
        assert effective.arguments["min_w"] == config.STRATEGY_PARAMS[strategy_key]["min_w"]
        assert effective.arguments["weighting_method"] == ("hierarchical_rp" if strategy_key == "rp" else "inverse_vol")
    pd.testing.assert_frame_equal(rets, before)


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_run_strategy_runtime_can_override_base_parameters(monkeypatch, strategy):
    rets = pd.DataFrame(0.001, index=pd.date_range("2024-01-01", periods=3), columns=config.ASSETS)
    engine = Mock(return_value=(None, None, 0, None, None))
    monkeypatch.setattr(pipeline, "backtest_iv" if strategy == "V3c 多元" else "backtest_b", engine)
    window = "iv_window" if strategy == "V3c 多元" else "rp_window"
    pipeline.run_strategy_backtest(rets, strategy, "weekly", **{window: 7, "track_signals": True})
    assert engine.call_args.kwargs[window] == 7
    assert engine.call_args.kwargs["rebal_freq"] == "weekly"
    assert engine.call_args.kwargs["track_signals"] is True


@pytest.mark.parametrize("strategy,frequency,error", [
    ("未知策略", "monthly", "未知策略"),
    ("V3c 多元", "daily", "未知调仓频率"),
])
def test_strategy_helpers_reject_unknown_parameters_before_engine_calls(strategy, frequency, error):
    with pytest.raises(ValueError, match=error):
        pipeline.strategy_backtest_kwargs(strategy, frequency)
    with pytest.raises(ValueError, match=error):
        pipeline.run_strategy_backtest(pd.DataFrame(), strategy, frequency)


@pytest.fixture
def comparison_cache(monkeypatch):
    performance.run_comparison.clear()
    panel = pd.DataFrame({"hs300": [100, 102, 101, 104], "gold": [200, 198, 202, 203]}, index=pd.date_range("2024-01-01", periods=4))
    state = {"panel": panel}
    loader = Mock(side_effect=lambda: state["panel"].copy(deep=True))
    series_clear, optional_clear = Mock(), Mock()
    monkeypatch.setattr(data, "load_panel", loader)
    monkeypatch.setattr(data.load_series, "cache_clear", series_clear)
    monkeypatch.setattr(data._load_optional, "cache_clear", optional_clear)

    def fake_runner(rets, strategy, frequency, **runtime):
        expected = state["panel"].pct_change().dropna()
        pd.testing.assert_frame_equal(rets, expected)
        assert runtime == {"track_weights": False, "track_signals": False}
        assert series_clear.call_count == loader.call_count
        assert optional_clear.call_count == loader.call_count
        i = STRATEGIES.index(strategy)
        f = FREQUENCIES.index(frequency)
        nv = (1 + rets["hs300"] * (f + 1)).cumprod() * (i + 2)
        return nv, "不应保存的动态净值", np.int64(10 * (f + 1) + i), "不应保存的权重", "不应保存的信号"

    runner = Mock(side_effect=fake_runner)
    monkeypatch.setattr(pipeline, "run_strategy_backtest", runner)
    yield state, loader, runner, series_clear, optional_clear
    # 仅清除此函数的内存缓存，不清全局缓存，也不恢复覆盖任何文件。
    performance.run_comparison.clear()


@pytest.mark.parametrize("frequency", FREQUENCIES)
def test_run_comparison_runs_three_strategies_once_and_reuses_real_cache(comparison_cache, frequency):
    state, loader, runner, series_clear, optional_clear = comparison_cache
    key = (frequency, "合成数据版本1", "合成模型版本1", "/synthetic/project")
    first = performance.run_comparison(*key)
    second = performance.run_comparison(*key)
    assert list(first) == list(STRATEGIES)
    assert loader.call_count == series_clear.call_count == optional_clear.call_count == 1
    assert runner.call_count == 3
    assert [call.args[1:3] for call in runner.call_args_list] == [(s, frequency) for s in STRATEGIES]
    for i, strategy in enumerate(STRATEGIES):
        assert set(first[strategy]) == {"nv", "n_rebal"}
        assert type(first[strategy]["n_rebal"]) is int
        assert first[strategy]["n_rebal"] == 10 * (FREQUENCIES.index(frequency) + 1) + i
        pd.testing.assert_series_equal(first[strategy]["nv"], second[strategy]["nv"])
    # 展示粒度、统计窗口变化不应重新触发回测。
    for granularity in ("多年", "年度", "月度"):
        performance.chart_frame(second, granularity)
        performance.metric_rows(second, "2024-01-01", "2024-01-31", granularity)
    performance.run_comparison(*key)
    assert loader.call_count == 1
    assert runner.call_count == 3
    # cache_data 应返回独立副本，调用者的修改不能污染之后命中的结果。
    first[STRATEGIES[0]]["nv"].iloc[0] = -999
    first[STRATEGIES[0]]["n_rebal"] = -999
    fresh = performance.run_comparison(*key)
    pd.testing.assert_series_equal(fresh[STRATEGIES[0]]["nv"], second[STRATEGIES[0]]["nv"])
    assert fresh[STRATEGIES[0]]["n_rebal"] == second[STRATEGIES[0]]["n_rebal"]
    assert runner.call_count == 3


@pytest.mark.parametrize("dimension", ["frequency", "data", "model", "root"])
def test_comparison_cache_isolates_each_key_and_can_reuse_previous_version(comparison_cache, dimension):
    state, loader, runner, series_clear, optional_clear = comparison_cache
    original = ("monthly", "合成数据版本1", "合成模型版本1", "/synthetic/project1")
    changes = {"frequency": (0, "weekly"), "data": (1, "合成数据版本2"),
               "model": (2, "合成模型版本2"), "root": (3, "/synthetic/project2")}
    first = performance.run_comparison(*original)
    modified = list(original)
    index, value = changes[dimension]
    modified[index] = value
    # 数据/模型切换时，测试桩也改变结果以证明并非误命中旧缓存。
    if dimension != "frequency":
        state["panel"] = state["panel"].copy()
        state["panel"].iloc[-1, 0] = 108
    second = performance.run_comparison(*modified)
    assert loader.call_count == series_clear.call_count == optional_clear.call_count == 2
    assert runner.call_count == 6
    assert not first[STRATEGIES[0]]["nv"].equals(second[STRATEGIES[0]]["nv"])
    for key, expected in ((original, first), (tuple(modified), second), (original, first)):
        cached = performance.run_comparison(*key)
        for strategy in STRATEGIES:
            pd.testing.assert_series_equal(cached[strategy]["nv"], expected[strategy]["nv"])
            assert cached[strategy]["n_rebal"] == expected[strategy]["n_rebal"]
    assert loader.call_count == 2
    assert runner.call_count == 6


@pytest.fixture
def synthetic_selected():
    return pd.DataFrame({
        "策略": STRATEGIES,
        "涨幅(%)": [12.3456789012, -4.5678901234, 0.0],
        "最大回撤(%)": [-6.7890123456, -8.9012345678, 0.0],
        "年化收益(%)": [9.8765432109, -3.2109876543, 0.0],
        "年化波动(%)": [7.6543210987, 10.123456789, 2.3456789012],
        "日收益波动(%)": [0.4821678901, 0.6377123456, 0.1477654321],
        "夏普": [1.2345678901, -0.5432109876, 0.0],
    }, index=[7, 2, 9])


def summary_card_elements(markup):
    from xml.etree import ElementTree

    root = ElementTree.fromstring(markup)
    assert root.tag == "div"
    assert root.attrib["class"] == "perf-kpis"
    cards = root.findall("article")
    assert len(cards) == 3
    assert all(card.attrib["class"] == "perf-kpi" for card in cards)
    return cards


@pytest.mark.parametrize("granularity,fields", [
    ("多年", (("年化收益(%)", "年化收益"), ("年化波动(%)", "年化波动"), ("夏普", "夏普"))),
    ("年度", (("年化波动(%)", "年化波动"), ("夏普", "夏普"))),
    ("月度", (("日收益波动(%)", "日收益波动"),)),
])
def test_summary_cards_preserve_three_strategy_values_and_granularity_fields(synthetic_selected, granularity, fields):
    columns = ["策略", "涨幅(%)", "最大回撤(%)"] + [column for column, _ in fields]
    selected = synthetic_selected[columns].copy(deep=True)
    before = selected.copy(deep=True)
    label = f"合成{granularity}窗口"
    cards = summary_card_elements(performance.summary_cards_html(selected, label))
    for card, (_, row), value_class in zip(cards, selected.iterrows(), ("perf-up", "perf-down", "perf-neutral")):
        assert card.find("h3").text == row["策略"]
        assert card.attrib["aria-label"] == f'{row["策略"]}，{label}'
        assert card.attrib["style"] == f'--strategy:{performance.STRATEGY_COLORS[row["策略"]]}'
        primary = card.find("div[@data-metric='涨幅']")
        assert float(primary.attrib["data-value"]) == pytest.approx(row["涨幅(%)"], rel=1e-11, abs=1e-12)
        assert primary.text == f'{row["涨幅(%)"]:+.2f}%'
        assert value_class in primary.attrib["class"].split()
        assert card.find("div[@class='perf-kpi-label']").text == "涨幅"
        expected_details = (("最大回撤(%)", "最大回撤"),) + fields
        assert [item.text for item in card.findall("dl/dt")] == [name for _, name in expected_details]
        assert [item.attrib["data-metric"] for item in card.findall("dl/dd")] == [name for _, name in expected_details]
        for column, name in expected_details:
            detail = card.find(f"dl/dd[@data-metric='{name}']")
            suffix = "" if column == "夏普" else "%"
            assert float(detail.attrib["data-value"]) == pytest.approx(row[column], rel=1e-11, abs=1e-12)
            assert detail.text == f"{row[column]:.2f}{suffix}"
            assert detail.attrib["class"] == "perf-neutral"
        assert card.find("div[@class='perf-kpi-reference']") is None
    pd.testing.assert_frame_equal(selected, before)


@pytest.mark.parametrize("value,expected", [
    (-1.25, "perf-down"), (-0.005, "perf-down"), (-0.0049, "perf-neutral"),
    (-0.0, "perf-neutral"), (0.0, "perf-neutral"), (0.0049, "perf-neutral"),
    (0.005, "perf-up"), (1.25, "perf-up"), (np.nan, "perf-neutral"),
])
def test_value_class_sign_and_display_zero_boundary(value, expected):
    assert performance._value_class(value) == expected


@pytest.mark.parametrize("value_class,variable,dominant_channel", [
    ("perf-up", "--perf-up", 0),
    ("perf-down", "--perf-down", 1),
])
def test_performance_css_uses_chinese_red_up_green_down(value_class, variable, dominant_channel):
    import re

    css = performance.PERFORMANCE_CSS
    root = re.search(r"\.st-key-perf_root\s*\{([^}]+)\}", css).group(1)
    hex_color = re.search(rf"{variable}\s*:\s*#([0-9a-fA-F]{{6}})\s*;", root).group(1)
    channels = [int(hex_color[i:i + 2], 16) for i in (0, 2, 4)]
    assert channels[dominant_channel] > max(channel for i, channel in enumerate(channels) if i != dominant_channel)
    assert re.search(rf"\.{value_class}\s*\{{\s*color\s*:\s*var\({variable}\)\s*;\s*\}}", css)


@pytest.mark.parametrize("value,suffix,signed,expected", [
    (1.234, "%", False, "1.23%"), (-1.234, "%", True, "-1.23%"),
    (1.236, " pp", True, "+1.24 pp"), (0.0, "", True, "+0.00"),
    (np.nan, "", False, "—"), (np.nan, "%", True, "—"),
    (np.inf, " pp", True, "—"), (-np.inf, "%", False, "—"),
])
def test_formatted_precision_sign_suffix_and_nonfinite_placeholder(value, suffix, signed, expected):
    assert performance._formatted(value, suffix, signed) == expected


@pytest.mark.parametrize("freq_label", ["双周频", "周频"])
def test_summary_cards_delta_subtracts_unrounded_values_and_matches_strategy(freq_label):
    selected = pd.DataFrame({"策略": STRATEGIES, "涨幅(%)": [1.004, 3, -1], "最大回撤(%)": [-1.004, -3, -2]})
    baseline = pd.DataFrame({"策略": STRATEGIES, "涨幅(%)": [1.003, 4, -2], "最大回撤(%)": [-1.006, -2, -3]}).iloc[::-1]
    before_cur, before_base = selected.copy(deep=True), baseline.copy(deep=True)
    cards = summary_card_elements(performance.summary_cards_html(selected, "合成窗口", baseline, freq_label))
    for card, (_, row), expected_class in zip(cards, selected.iterrows(), ("perf-neutral", "perf-down", "perf-up")):
        previous = baseline.set_index("策略").loc[row["策略"]]
        assert card.find("h3").text == row["策略"]
        assert card.find("div[@class='perf-kpi-label']").text == "涨幅变化"
        reference = card.find("div[@class='perf-kpi-reference']")
        assert reference.text == f'月频 {previous["涨幅(%)"]:+.2f}% → {freq_label} {row["涨幅(%)"]:+.2f}%'
        assert [item.text for item in card.findall("dl/dt")] == ["回撤变化", f"{freq_label}最大回撤"]
        for node, field in ((card.find("div[@data-metric='涨幅']"), "涨幅(%)"),
                            (card.find("dl/dd[@data-metric='回撤变化']"), "最大回撤(%)")):
            expected = row[field] - previous[field]
            assert float(node.attrib["data-value"]) == pytest.approx(expected, rel=1e-11, abs=1e-12)
            assert node.text == f"{expected:+.2f} pp"
            assert expected_class in node.attrib["class"].split()
        drawdown = card.find(f"dl/dd[@data-metric='{freq_label}最大回撤']")
        assert float(drawdown.attrib["data-value"]) == pytest.approx(row["最大回撤(%)"])
        assert drawdown.text == f'{row["最大回撤(%)"]:.2f}%'
        assert drawdown.attrib["class"] == "perf-neutral"
    first = cards[0]
    assert float(first.find("div[@data-metric='涨幅']").attrib["data-value"]) == pytest.approx(0.001, abs=1e-12)
    assert float(first.find("div[@data-metric='涨幅']").attrib["data-value"]) != round(1.004, 2) - round(1.003, 2)
    assert float(first.find("dl/dd[@data-metric='回撤变化']").attrib["data-value"]) == pytest.approx(0.002, abs=1e-12)
    assert float(first.find("dl/dd[@data-metric='回撤变化']").attrib["data-value"]) != round(-1.004, 2) - round(-1.006, 2)
    pd.testing.assert_frame_equal(selected, before_cur)
    pd.testing.assert_frame_equal(baseline, before_base)


@pytest.mark.parametrize("with_baseline", [False, True])
def test_summary_cards_escape_strategy_label_and_frequency(monkeypatch, synthetic_selected, with_baseline):
    from html import escape

    payload = '<script>"合成" & \'用户\'</script>'
    selected = synthetic_selected.copy(deep=True)
    strategies = [f"{strategy}{payload}" for strategy in STRATEGIES]
    selected["策略"] = strategies
    for original, strategy in zip(STRATEGIES, strategies):
        monkeypatch.setitem(performance.STRATEGY_COLORS, strategy, performance.STRATEGY_COLORS[original])
    label, freq_label = f"窗口{payload}", f"周频{payload}"
    baseline = selected.iloc[::-1].copy(deep=True) if with_baseline else None
    markup = performance.summary_cards_html(selected, label, baseline, freq_label)
    assert payload not in markup
    assert escape(payload) in markup
    assert escape(label) in markup
    cards = summary_card_elements(markup)
    for card, strategy in zip(cards, strategies):
        assert card.find("h3").text == strategy
        assert card.attrib["aria-label"] == f"{strategy}，{label}"
        if with_baseline:
            assert freq_label in card.find("div[@class='perf-kpi-reference']").text
            assert f"{freq_label}最大回撤" in [metric.attrib["data-metric"] for metric in card.findall("dl/dd")]
    assert all(element.tag != "script" for card in cards for element in card.iter())


@pytest.mark.parametrize("with_baseline", [False, True])
def test_summary_cards_nan_values_display_neutral_dash_without_suffix(synthetic_selected, with_baseline):
    selected = synthetic_selected.copy(deep=True)
    selected.loc[:, selected.columns != "策略"] = np.nan
    baseline = synthetic_selected.iloc[::-1].copy(deep=True) if with_baseline else None
    cards = summary_card_elements(performance.summary_cards_html(selected, "缺失指标", baseline, "周频"))
    for card in cards:
        metrics = [card.find("div[@data-metric='涨幅']"), *card.findall("dl/dd")]
        for metric in metrics:
            assert np.isnan(float(metric.attrib["data-value"]))
            assert metric.text == "—"
            assert "perf-neutral" in metric.attrib["class"].split()
        if with_baseline:
            assert card.find("div[@class='perf-kpi-reference']").text.endswith("→ 周频 —")


@pytest.mark.parametrize("view,freq_label", [("三策略对比", "月频"), ("调频影响", "周频")])
@pytest.mark.parametrize("granularity", ["多年", "年度", "月度"])
def test_render_performance_cards_with_isolated_synthetic_apptest(monkeypatch, synthetic_results, view, freq_label, granularity):
    import sys
    from pathlib import Path
    from streamlit.testing.v1 import AppTest

    current = {
        strategy: {**item, "nv": item["nv"] * np.linspace(1, 1.03 + i * 0.01, len(item["nv"]))}
        for i, (strategy, item) in enumerate(synthetic_results.items())
    }
    root = Path("/synthetic/performance-card-test")
    loader = Mock(return_value=synthetic_results)
    versions = Mock(return_value=("合成数据版本", "合成模型版本"))

    def fake_comparison(frequency, data_version, model_version, root_path):
        assert (data_version, model_version, root_path) == ("合成数据版本", "合成模型版本", str(root))
        assert frequency in ("monthly", "weekly")
        return synthetic_results if frequency == "monthly" else current

    runner = Mock(side_effect=fake_comparison)
    monkeypatch.setattr(performance, "load_saved_monthly", loader)
    monkeypatch.setattr(performance, "comparison_versions", versions)
    monkeypatch.setattr(performance, "run_comparison", runner)
    app_module_before = sys.modules.get("streamlit_app.app")
    app = AppTest.from_string(
        "from pathlib import Path\n"
        "from streamlit_app.performance import render_performance\n"
        "render_performance(Path('/synthetic/performance-card-test'))\n"
    )
    app.session_state["perf_view_v2"] = view
    app.session_state["perf_granularity_v2"] = granularity
    app.session_state["perf_impact_frequency_v2" if view == "调频影响" else "perf_frequency_v2"] = freq_label
    app.run()
    assert not app.exception
    assert not app.error
    assert not app.warning
    assert sys.modules.get("streamlit_app.app") is app_module_before
    loader.assert_called_once_with(root)
    if view == "调频影响":
        versions.assert_called_once_with(root)
        assert [call.args[0] for call in runner.call_args_list] == ["monthly", "weekly"]
    else:
        versions.assert_not_called()
        runner.assert_not_called()
    assert sum(element.value == performance.PERFORMANCE_CSS.strip() for element in app.markdown) == 1
    rendered = [element.value for element in app.markdown if element.value.startswith('<div class="perf-kpis">')]
    assert len(rendered) == 1
    cards = summary_card_elements(rendered[0])
    assert [card.find("h3").text for card in cards] == list(STRATEGIES)
    results = current if view == "调频影响" else synthetic_results
    for card, strategy in zip(cards, STRATEGIES):
        nv = results[strategy]["nv"]
        if granularity == "多年":
            values = nv.to_numpy()
        else:
            start = pd.Timestamp("2025-01-01")
            positions = np.flatnonzero(nv.index >= start)
            values = nv.iloc[positions[0] - 1:positions[-1] + 1].to_numpy()
        expected = expected_metrics(values)
        if view == "调频影响":
            base = synthetic_results[strategy]["nv"]
            base_values = base.to_numpy() if granularity == "多年" else base.iloc[positions[0] - 1:positions[-1] + 1].to_numpy()
            previous = expected_metrics(base_values)
            assert float(card.find("dl/dd[@data-metric='回撤变化']").attrib["data-value"]) == pytest.approx(
                (expected["mdd"] - previous["mdd"]) * 100, rel=1e-10, abs=1e-10)
            increase = (expected["cum_return"] - previous["cum_return"]) * 100
        else:
            increase = expected["cum_return"] * 100
            fields = (("日收益波动", "daily_vol", 100),) if granularity == "月度" else (
                ("年化波动", "vol", 100), ("夏普", "sharpe", 1))
            if granularity == "多年":
                fields += (("年化收益", "cagr", 100),)
            for name, field, factor in fields:
                metric = card.find(f"dl/dd[@data-metric='{name}']")
                assert metric is not None
                assert float(metric.attrib["data-value"]) == pytest.approx(expected[field] * factor, rel=1e-10, abs=1e-10)
        assert float(card.find("div[@data-metric='涨幅']").attrib["data-value"]) == pytest.approx(increase, rel=1e-10, abs=1e-10)
