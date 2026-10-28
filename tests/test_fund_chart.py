"""图表回归：仅写测试产物，不更新行情或恢复覆盖账户。

python tests/test_fund_chart.py --unit-only
python tests/test_fund_chart.py --fixtures-only
python tests/test_fund_chart.py --app-only
python tests/test_fund_chart.py --serve-readonly  # 浏览器测试用 127.0.0.1:8511
不带参数：单元测试、AppTest、生成 outputs/trend-test-cases.json。
"""
import argparse
import ast
import calendar
from contextlib import contextmanager
import csv
from datetime import date, datetime, timedelta
import hashlib
import html
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "streamlit_app/app.py"
SOURCE = ROOT / "data/hs300.csv"
FIXTURE = ROOT / "outputs/trend-test-cases.json"
RANGES = {"近1月": ("months", 1), "近3月": ("months", 3), "近6月": ("months", 6),
          "近1年": ("years", 1), "近3年": ("years", 3), "近5年": ("years", 5),
          "今年来": ("ytd", 0), "全部": ("all", 0)}
STAGES = {"近1月": ("months", 1), "近3月": ("months", 3), "近6月": ("months", 6),
          "近1年": ("years", 1), "近3年": ("years", 3), "今年来": ("ytd", 0)}
PERIODS = ("日", "月", "年")
# 2026/10/24 更新：区间按钮改由 _range_buttons() 生成；去掉「近1月=30自然日」提示（区间口径改为与支付宝一致）。
# 已用 jsdom 实跑验证区间切换、日/月/年线、悬停提示与区间统计。
# 2026/10/27 更新：新增 trades（历史买卖点，红上三角买入 / 绿下三角卖出）、store / default_range / heading
# 三个文案参数（持仓页详情图要独立记忆区间与标题）。用 headless Chrome + CDP 实跑 10 项验证：
# 三角形数量与颜色、统计条笔数、悬停提示列出该笔成交、区间切换只画区间内成交点且不残留、
# 月线按周期聚合仍标点、区间/周期写入各自 localStorage 键并还原。
# 2026/10/27 再更新：tab7 改名「基金检索」，只改了 _scroll_chart_html docstring 里的页名，
# 绘图与交互逻辑一字未动（diff 仅此一处），故刷新哈希、无需重跑 CDP 用例。
# 2026/10/28 更新：标题行改由 _chart_head_block() 生成（heading="" 时整行标题隐藏，只留隐藏的
# #updating），持仓页「点开一只基金」的详情图不再和上面的子页签重复写一遍标题。
# 已用 headless Chrome + CDP 在详情面板里实跑：区间按钮 8 个齐、点近3月后区间文案与统计条同步重算、
# 日线切月线（5 期 / 全历史 155 期）、localStorage awTrend.fund 写入 {"period":"日","range":"近3月"} 并还原。
# 2026/10/28 再更新：删掉「最高/最低」白底标注框（只用来算振幅，不再钉在图上压住三角），
# 买卖三角放大到 8×13 并加 2px 白描边。改完实跑 CDP：区间按钮点近1年 → sel 文案与按钮同步、
# localStorage 写入、整页重载后仍是近1年（iframe 重建读回）；点回近3月同样还原。
CHART_SOURCE_SHA256 = "110906798588e65c6e6f08cf5bb733ede16d9ec533e397e70fbf34e25377b8f8"
NAMES = {"_scroll_chart_html", "_trend_aggregate", "_trend_window_start",
         "_stage_rows", "_stage_summary_html", "_trend_chart_data",
         "_period_label", "_range_buttons", "_chart_head_block"}
CONSTANTS = {"_TREND_RANGES", "_TREND_STAGES", "_COMP_BASE_CSS"}


def load_namespace():
    """只执行约定的纯函数与常量，不导入或运行应用顶层代码。"""
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    parts = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in NAMES:
            parts.append(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id in CONSTANTS for t in targets):
                parts.append(node)
    ns = {"pd": pd, "np": np, "json": json, "date": date, "html_escape": html.escape}
    exec(compile(ast.Module(body=parts, type_ignores=[]), str(APP), "exec"), ns)
    missing = (NAMES | CONSTANTS) - ns.keys()
    assert not missing, f"新版接口尚未就绪：{sorted(missing)}"
    return ns


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def readonly_hashes():
    paths = [ROOT / "data/sim_account.json", *sorted((ROOT / "data").glob("*.csv"))]
    return {str(p.relative_to(ROOT)): file_hash(p) for p in paths}


@contextmanager
def unchanged_data():
    before = readonly_hashes()
    try:
        yield
    finally:
        after = readonly_hashes()
        assert before == after, f"只读测试改变了账户或行情；不进行恢复覆盖：{[(p, before.get(p), after.get(p)) for p in before.keys() | after.keys() if before.get(p) != after.get(p)]}"
        print("账户 SHA256（前/后相同）：", after["data/sim_account.json"])


@contextmanager
def block_mutations():
    sys.path.insert(0, str(ROOT))
    with patch("allweather.fetch.fetch_all", side_effect=AssertionError("测试禁止更新行情")), \
         patch("allweather.sim_account.save_acct", side_effect=AssertionError("测试禁止写入账户")):
        yield


def shift_months(day, amount):
    ordinal = day.year * 12 + day.month - 1 + amount
    year, month0 = divmod(ordinal, 12)
    month = month0 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def csv_records(source=SOURCE):
    """独立 oracle：标准库读真实 CSV，不调用任何生产计算函数。"""
    records = {}
    with source.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            day = datetime.fromisoformat(row["date"]).date()
            try:
                price = float(row["close"])
            except (ValueError, TypeError):
                continue
            if day <= date.today() and math.isfinite(price):
                records[day] = price
    return sorted(records.items())


def expected_aggregate(records, period):
    grouped = {}
    for day, price in records:
        key = day if period == "日" else ((day.year, day.month) if period == "月" else day.year)
        grouped[key] = (day, price)
    return list(grouped.values())


def expected_start(records, span):
    """支付宝「历史业绩」口径（2026/10/24 对账 161119 五个区间全部一致）：
    基准 = 截止日往前推 N 个自然月/年那天（或之前最近一个交易日）的记录；今年来 = 去年最后一条记录；不够长则第一条。"""
    if not records or span[0] == "all":
        return 0
    kind, amount = span
    end = records[-1][0]
    if kind == "ytd":
        before = [i for i, (day, _) in enumerate(records) if day < date(end.year, 1, 1)]
        return before[-1] if before else 0
    cutoff = end - timedelta(days=amount) if kind == "days" else shift_months(end, -amount * (12 if kind == "years" else 1))
    before = [i for i, (day, _) in enumerate(records) if day <= cutoff]
    return before[-1] if before else 0


def as_series(records):
    return pd.Series([price for _, price in records], index=pd.to_datetime([day for day, _ in records]), dtype=float)


def expected_history(records, period):
    data = expected_aggregate(records, period)
    prices = [price for _, price in data]
    labels = {"日": lambda d: d.strftime("%Y/%m/%d"), "月": lambda d: f"{d.year}年{d.month}月",
              "年": lambda d: f"{d.year}年"}[period]
    return {"labels": [labels(day) for day, _ in data],
            "dates": [day.strftime("%Y/%m/%d") for day, _ in data], "prices": prices,
            "rets": [None] + [(prices[i] / prices[i - 1] - 1) * 100 for i in range(1, len(prices))],
            "windows": {label: {"start": expected_start(data, span),
                                 "count": len(data) - expected_start(data, span)} for label, span in RANGES.items()}}


def expected_stages(records):
    cells = []
    for label, span in STAGES.items():
        if not records:
            cells.append({"label": label, "ret": None, "base": None, "end": None})
            continue
        # 同名阶段与日线采用一致基准：区间首个可见真实收盘，不用前一期。
        base, price = records[expected_start(records, span)]
        end, last = records[-1]
        ret = (last / price - 1) * 100 if math.isfinite(price) and price > 0 else None
        cells.append({"label": label, "ret": ret, "base": base.strftime("%Y/%m/%d"),
                      "end": end.strftime("%Y/%m/%d")})
    return cells


def payload_from_html(markup):
    match = re.search(r"const D = (\{.*?\});", markup, re.S)
    assert match, "图表必须以 const D = {...}; 提供数据"
    return json.loads(match.group(1), parse_constant=lambda value: (_ for _ in ()).throw(AssertionError(f"非法 JSON 数值：{value}")))


class Markup(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.text = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)

    def matching(self, tag=None, cls=None, **attrs):
        return [a for t, a in self.tags if (tag is None or t == tag)
                and (cls is None or cls in a.get("class", "").split())
                and all(a.get(k) == v for k, v in attrs.items())]


def assert_stage_summary(markup, expected):
    parsed = Markup(markup)
    assert [cell["label"] for cell in expected] == list(STAGES)
    for cls in ("stage-summary", "stage-summary-title", "stage-metrics"):
        assert len(parsed.matching(cls=cls)) == 1, f"必须有一个 {cls}"
    assert [a["data-stage"] for a in parsed.matching(cls="stage-metric")] == list(STAGES)
    assert len(parsed.matching(cls="stage-label")) == len(STAGES)
    returns = parsed.matching(cls="stage-return")
    assert len(returns) == len(STAGES)
    for tag in ("button", "a", "input", "select", "svg", "rect", "canvas"):
        assert not parsed.matching(tag), f"阶段概览不应有 {tag}"
    assert not parsed.matching(role="button")
    for cls in ("stage-row", "stage-bars", "prior-return", "stage-delta", "lifetime"):
        assert not parsed.matching(cls=cls), f"旧阶段对比应移除：{cls}"
    # 可见内容只能是标题、四个标签和百分比；日期可以放在 title 中。
    pattern = "阶段表现" + "".join(re.escape(label) + r"([+\-−]?\d+(?:\.\d+)?%|—)" for label in STAGES)
    match = re.fullmatch(pattern, re.sub(r"\s+", "", "".join(parsed.text)))
    assert match, f"概览不应直接堆说明或同比：{parsed.text}"
    for attrs, shown, cell in zip(returns, match.groups(), expected):
        assert "data-value" in attrs, f"{cell['label']} 缺少原始数值"
        value = cell["ret"]
        direction = "neutral" if value is None or value == 0 else ("up" if value > 0 else "down")
        assert set(attrs.get("class", "").split()) & {"up", "down", "neutral"} == {direction}
        if value is None:
            assert attrs["data-value"] in ("", "null")
            assert shown == "—"
        else:
            assert math.isfinite(float(attrs["data-value"]))
            assert math.isclose(float(attrs["data-value"]), value, rel_tol=1e-7, abs_tol=1e-7)
            number = shown[:-1].replace("−", "-")
            decimals = len(number.partition(".")[2])
            assert abs(float(number) - value) <= .5 * 10 ** -decimals + 1e-8


class ChartRangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = load_namespace()

    def setUp(self):
        dates = pd.bdate_range("2020-01-01", "2026-10-16")
        self.series = pd.Series(100 + np.arange(len(dates)) * .02 + np.sin(np.arange(len(dates))) * 2, index=dates)
        self.records = [(day.date(), float(price)) for day, price in self.series.items()]

    def test_exact_ranges_and_stage_labels(self):
        self.assertEqual(list(self.ns["_TREND_RANGES"]), list(RANGES))
        self.assertEqual(self.ns["_TREND_RANGES"], RANGES)
        self.assertEqual(list(self.ns["_TREND_STAGES"]), list(STAGES))
        self.assertEqual(self.ns["_TREND_STAGES"], STAGES)
        self.assertTrue(all(isinstance(span, tuple) for span in self.ns["_TREND_STAGES"].values()))
        self.assertEqual(self.ns["_scroll_chart_html"].__defaults__[0], 540)

    def test_chart_function_source_is_unchanged(self):
        source = APP.read_text(encoding="utf-8")
        nodes = [node for node in ast.parse(source).body
                 if isinstance(node, ast.FunctionDef) and node.name == "_scroll_chart_html"]
        self.assertEqual(len(nodes), 1)
        segment = ast.get_source_segment(source, nodes[0])
        self.assertEqual(hashlib.sha256(segment.encode("utf-8")).hexdigest(), CHART_SOURCE_SHA256,
                         "图表函数变更后必须验证交互，当前锁定「区间/周期写入 localStorage、重建 iframe 后还原」的版本")

    def test_trade_markers_are_opt_in_and_labelled(self):
        """历史买卖点：不传 trades 时行为与之前完全一致；传了就带上成交数据与三角标记。"""
        plain = self.ns["_scroll_chart_html"](["2024/01/02", "2024/01/03"], [100., 101.], 2)
        self.assertIn('"trades": []', plain)
        self.assertIn('"store": "awTrend.single"', plain)
        self.assertIn('"defaultRange": "近1月"', plain)
        self.assertIn("走势分析", plain)

        trades = [{"date": "2024/01/03", "side": "买入", "label": "1,000.00 份 @ 1.0100"}]
        markup = self.ns["_scroll_chart_html"](
            ["2024/01/02", "2024/01/03"], [100., 101.], 2, trades=trades,
            store="awTrend.fund", default_range="全部", heading="某基金 · 历史买卖点")
        self.assertIn('"date": "2024/01/03"', markup)
        self.assertIn('"side": "买入"', markup)
        self.assertIn('"store": "awTrend.fund"', markup)
        self.assertIn('"defaultRange": "全部"', markup)
        self.assertIn("某基金 · 历史买卖点", markup)
        self.assertIn('aria-pressed="true">全部</button>', markup)   # 默认区间按钮跟着 default_range
        # 买=红上三角、卖=绿下三角，颜色沿用全站涨跌 token
        self.assertIn('fill="#C52828" stroke="#fff"', markup)
        self.assertIn('fill="#16703B" stroke="#fff"', markup)
        self.assertIn("trade-row", markup)

    def test_tooltip_uses_finite_svg_geometry(self):
        markup = self.ns["_scroll_chart_html"](["2024/01/02"], [100.], 1)
        self.assertNotIn("svg.offsetTop", markup.replace("// SVG没有offsetTop", ""))
        self.assertIn("chartBox.top - wrapBox.top", markup)
        self.assertIn("clientY - chartBox.top", markup)
        self.assertIn("Number.isInteger(i)", markup)
        self.assertIn("tip.offsetHeight", markup)

    def test_month_window_matches_alipay_base_date(self):
        """近N月基准 = N 个自然月前那天的净值；那天休市取之前最近一个交易日（与支付宝一致，不再用 30 天）。"""
        series = pd.Series(np.arange(65) + 100., index=pd.date_range("2024-02-01", periods=65))   # 末日 2024/04/05
        idx = self.ns["_trend_window_start"](series, RANGES["近1月"])
        self.assertEqual(series.index[idx], pd.Timestamp("2024-03-05"))
        self.assertNotEqual(idx, expected_start([(d.date(), v) for d, v in series.items()], ("days", 30)))
        weekdays = series[series.index.weekday < 5]                     # 2024/03/05 是周二，有交易
        self.assertEqual(weekdays.index[self.ns["_trend_window_start"](weekdays, RANGES["近1月"])], pd.Timestamp("2024-03-05"))
        sat_end = series.loc[:"2024-04-06"][lambda x: x.index.weekday < 5]   # 截止 2024/04/05 周五，往前一月 03/05
        self.assertEqual(sat_end.index[self.ns["_trend_window_start"](sat_end, ("months", 1))], pd.Timestamp("2024-03-05"))
        hol = weekdays.drop(pd.Timestamp("2024-03-05"))                  # 基准日休市 → 用前一个交易日 03/04
        self.assertEqual(hol.index[self.ns["_trend_window_start"](hol, RANGES["近1月"])], pd.Timestamp("2024-03-04"))
        ytd = self.ns["_trend_window_start"](weekdays, RANGES["今年来"])  # 今年来基准 = 去年最后一条，没有则第一条
        self.assertEqual(ytd, 0)

    def test_all_fifteen_windows_keep_real_dates(self):
        got = self.ns["_trend_chart_data"](self.series)
        self.assertEqual(set(got), set(PERIODS))
        for period in PERIODS:
            expected = expected_history(self.records, period)
            with self.subTest(period=period):
                self.assertEqual(got[period]["dates"], expected["dates"])
                self.assertEqual(len(got[period]["labels"]), len(expected["dates"]))
                self.assertTrue(all(isinstance(label, str) and label for label in got[period]["labels"]))
                np.testing.assert_allclose(got[period]["prices"], expected["prices"])
                self.assertIsNone(got[period]["rets"][0])
                np.testing.assert_allclose(got[period]["rets"][1:], expected["rets"][1:])
                self.assertEqual(got[period]["windows"], expected["windows"])
                aggregated = self.ns["_trend_aggregate"](self.series, period)
                self.assertEqual(aggregated.index[-1], self.series.index[-1])
                self.assertTrue(aggregated.index.isin(self.series.index).all())
                for label, span in RANGES.items():
                    self.assertEqual(self.ns["_trend_window_start"](aggregated, span), expected["windows"][label]["start"])
        self.assertEqual(got["年"]["windows"]["近1月"]["count"], 2)       # 年线：基准为上一年末那条 + 今年最新
        self.assertGreater(got["年"]["windows"]["近1年"]["count"], 1)

    def test_real_csv_matches_independent_oracle(self):
        records = csv_records()
        self.assertGreater(len(records), 1)
        got = self.ns["_trend_chart_data"](as_series(records))
        for period in PERIODS:
            expected = expected_history(records, period)
            self.assertEqual(got[period]["dates"], expected["dates"])
            self.assertEqual(got[period]["windows"], expected["windows"])
            np.testing.assert_allclose(got[period]["prices"], expected["prices"])
            self.assertIsNone(got[period]["rets"][0])
            np.testing.assert_allclose(got[period]["rets"][1:], expected["rets"][1:])

    def test_short_history_never_fabricates_periods(self):
        short = self.series.tail(1)
        data = self.ns["_trend_chart_data"](short)
        for period in PERIODS:
            self.assertEqual(data[period]["prices"], short.tolist())
            self.assertEqual(data[period]["rets"], [None])
            self.assertEqual(data[period]["dates"], [short.index[0].strftime("%Y/%m/%d")])
            for span in RANGES.values():
                self.assertEqual(self.ns["_trend_window_start"](short, span), 0)
        self.assertEqual(self.ns["_trend_window_start"](pd.Series(dtype=float), ("days", 30)), 0)

    def test_returns_are_computed_before_windowing(self):
        data = self.ns["_trend_chart_data"](self.series)
        for period in PERIODS:
            h = data[period]
            start = h["windows"]["近1月"]["start"]
            self.assertGreater(start, 0)
            self.assertAlmostEqual(h["rets"][start], (h["prices"][start] / h["prices"][start - 1] - 1) * 100)

    def test_order_duplicates_nonfinite_and_future_dates(self):
        dirty = pd.Series([20., 10., 30., np.nan, np.inf, 99.], index=pd.to_datetime([
            "2024-01-03", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2099-01-01"]))
        clean = self.ns["_trend_aggregate"](dirty, "日")
        self.assertEqual(clean.index.strftime("%Y/%m/%d").tolist(), ["2024/01/02", "2024/01/03"])
        self.assertEqual(clean.tolist(), [10., 30.])

    def test_html_carries_all_histories_and_new_controls(self):
        histories = self.ns["_trend_chart_data"](self.series)
        daily = histories["日"]
        markup = self.ns["_scroll_chart_html"](daily["labels"], daily["prices"], daily["windows"]["近1月"]["count"],
                                                rets=daily["rets"], revision=19, histories=histories)
        payload = payload_from_html(markup)
        self.assertEqual(payload["histories"], histories)
        self.assertEqual(payload["revision"], 19)
        parsed = Markup(markup)
        self.assertEqual(len(parsed.matching(id="wrap")), 1)
        self.assertEqual(len(parsed.matching("svg", id="chart")), 1)
        self.assertEqual([a["data-range"] for a in parsed.matching("button") if "data-range" in a], list(RANGES))
        self.assertEqual(len(parsed.matching("select", id="period", **{"aria-label": "周期"})), 1)
        self.assertEqual([a["value"] for a in parsed.matching("option")], list(PERIODS))
        self.assertFalse(parsed.matching(cls="toolbar"))
        self.assertIn("ResizeObserver", markup)

    def test_single_dataset_payload_supports_synthetic_regression(self):
        prices = [100., 110., 99., 99.]
        labels = ["2024/01/02", "2024/01/03", "2024/01/04", "2024/01/05"]
        returns = [np.nan, 10., -10., 0.]
        markup = self.ns["_scroll_chart_html"](labels, prices, 3, rets=returns)
        payload = payload_from_html(markup)
        dataset = payload["histories"]["日"] if "histories" in payload else payload
        self.assertEqual(dataset["prices"], prices)
        self.assertEqual(dataset["labels"], labels)
        self.assertEqual(dataset["rets"], [None, 10., -10., 0.])
        self.assertEqual(payload["win"], 3)


class StageSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = load_namespace()
        cls.records = csv_records()
        cls.series = as_series(cls.records)

    def assert_cells(self, series, records):
        cells = self.ns["_stage_rows"](series)
        expected = expected_stages(records)
        self.assertIsInstance(cells, list)
        self.assertEqual(len(cells), len(STAGES))
        for cell, ex in zip(cells, expected):
            with self.subTest(stage=ex["label"]):
                self.assertEqual(set(cell), {"label", "ret", "base", "end"})
                self.assertEqual(cell["label"], ex["label"])
                if ex["ret"] is None:
                    self.assertIsNone(cell["ret"])
                else:
                    self.assertAlmostEqual(cell["ret"], ex["ret"])
                for key in ("base", "end"):
                    if ex[key] is None:
                        self.assertIsNone(cell[key])
                    else:
                        self.assertEqual(pd.Timestamp(cell[key]).strftime("%Y/%m/%d"), ex[key])
        assert_stage_summary(self.ns["_stage_summary_html"](cells), expected)
        return cells

    def test_four_cells_match_independent_real_csv_calculation(self):
        self.assert_cells(self.series, self.records)

    def test_stage_return_uses_window_base_record(self):
        dates = pd.bdate_range("2020-01-02", "2024-05-06")
        series = pd.Series(np.arange(len(dates)) + 100., index=dates)
        # 覆盖闰日、周末、今年来、月末边界；阶段数字的基准 = 图表视窗第一条（即支付宝口径的基准日）。
        for end in ("2024-02-29", "2024-04-05", "2024-05-06"):
            sample = series.loc[:end]
            records = [(day.date(), float(price)) for day, price in sample.items()]
            cells = self.assert_cells(sample, records)
            daily = self.ns["_trend_chart_data"](sample)["日"]
            for cell in cells:
                start = daily["windows"][cell["label"]]["start"]
                self.assertGreater(start, 0)
                self.assertEqual(cell["base"].strftime("%Y/%m/%d"), daily["dates"][start])
                self.assertAlmostEqual(cell["ret"], (daily["prices"][-1] / daily["prices"][start] - 1) * 100)
                self.assertNotAlmostEqual(cell["ret"], (daily["prices"][-1] / daily["prices"][start - 1] - 1) * 100)

    def test_empty_and_unusable_history_keep_four_blank_cells(self):
        for series in (as_series([]), pd.Series([np.nan, np.inf, 99.],
                      index=pd.to_datetime(["2024-01-02", "2024-01-03", "2099-01-01"]))):
            self.assert_cells(series, [])

    def test_single_point_has_four_zero_returns_and_real_dates(self):
        short = self.series.tail(1)
        cells = self.assert_cells(short, self.records[-1:])
        self.assertTrue(all(cell["ret"] == 0 for cell in cells))
        self.assertTrue(all(cell["base"] == cell["end"] == short.index[0] for cell in cells))

    def test_invalid_baseline_never_generates_infinite_or_fake_returns(self):
        for price in (0., -1.):
            with self.subTest(price=price):
                records = [(date(2024, 1, 2), price), (date(2024, 1, 3), 100.)]
                cells = self.assert_cells(as_series(records), records)
                self.assertTrue(all(cell["ret"] is None for cell in cells))

    def test_stage_summary_cleans_duplicates_nonfinite_and_future_dates(self):
        dirty = pd.Series([20., 10., 30., np.nan, np.inf, 99.], index=pd.to_datetime([
            "2024-01-03", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2099-01-01"]))
        self.assert_cells(dirty, [(date(2024, 1, 2), 10.), (date(2024, 1, 3), 30.)])

    def test_stage_markup_is_four_readonly_numbers_with_direction_classes(self):
        cells = [{"label": label, "ret": ret, "base": pd.Timestamp("2024-01-02"),
                  "end": pd.Timestamp("2024-01-03")} for label, ret in zip(STAGES, (12.5, -3.25, 0., None, 4.0, -1.5))]
        assert_stage_summary(self.ns["_stage_summary_html"](cells), cells)

    def test_removed_comparison_functions_are_not_retained(self):
        tree = ast.parse(APP.read_text(encoding="utf-8"))
        names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        self.assertFalse({"_stage_yoy", "_stage_comparison_html"} & names)

    def test_stage_labels_are_html_escaped(self):
        cells = self.ns["_stage_rows"](self.series)
        cells[0] = {**cells[0], "label": '<img src=x onerror="alert(1)">'}
        parsed = Markup(self.ns["_stage_summary_html"](cells))
        self.assertFalse(parsed.matching("img"))
        self.assertIn(cells[0]["label"], "".join(parsed.text))
        self.assertEqual(parsed.matching(cls="stage-metric")[0]["data-stage"], cells[0]["label"])


def app_regression():
    from streamlit.testing.v1 import AppTest
    with unchanged_data(), block_mutations():
        at = AppTest.from_file(str(APP), default_timeout=120)
        at.session_state["auto_fetch_done"] = True
        at.run()

        sources = {"hs300": "hs300", "gold": "gold", "wti": "wti", "bond_30y": "bond_30y_etf"}
        observed = {}

        def check(asset):
            assert not at.exception, [item.value for item in at.exception]
            assert not at.error, [item.value for item in at.error]
            assert not [b for b in at.button if str(b.key or "").startswith("stage_") or b.label in STAGES], "阶段必须只读"
            selectors = [s for s in at.selectbox if s.label == "基金"]
            assert len(selectors) == 1
            assert selectors[0].value == asset
            summaries = [m.value for m in at.markdown if Markup(m.value).matching(cls="stage-summary")]
            assert len(summaries) == 1, "概览必须只有一组四项阶段数字"
            expected = expected_stages(csv_records(ROOT / "data" / f"{sources[asset]}.csv"))
            assert_stage_summary(summaries[0], expected)
            for markup in at.markdown:
                assert not Markup(markup.value).matching(cls="stage-row"), "不得保留底部阶段对比"
            observed[asset] = tuple(c["ret"] for c in expected)

        check("hs300")
        for asset in ("gold", "wti", "bond_30y", "hs300"):
            next(s for s in at.selectbox if s.label == "基金").set_value(asset).run()
            check(asset)
        assert len(set(observed.values())) > 1, "真实样本须能区分基金，避免陈旧概览漏检"
        print("PASS：基金切换后四项概览匹配各自真实 CSV、无阶段按钮、无应用错误")


def browser_fixtures():
    with unchanged_data():
        ns = load_namespace()
        records = csv_records()
        histories = {period: expected_history(records, period) for period in PERIODS}
        synthetic = []
        for name, prices, win in [("mixed", [100., 110., 99., 99., 120., 90.], 4),
                                  ("flat", [100., 100., 100., 100.], 4),
                                  ("single", [123.45], 1),
                                  ("nearby-extremes", [100., 100.001, 100., 100.0005], 4)]:
            labels = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y/%m/%d") for i in range(len(prices))]
            rets = [None] + [(prices[i] / prices[i - 1] - 1) * 100 for i in range(1, len(prices))]
            markup = ns["_scroll_chart_html"](labels, prices, win, rets=rets)
            synthetic.append({"name": name, "html": markup, "win": win,
                              "history": {"labels": labels, "dates": labels, "prices": prices, "rets": rets}})
        fixture = {"version": 3, "source": "data/hs300.csv", "sourceSha256": file_hash(SOURCE),
                   "asOf": date.today().isoformat(), "ranges": list(RANGES), "periods": list(PERIODS),
                   "histories": histories, "stages": expected_stages(records), "synthetic": synthetic}
        if not FIXTURE.parent.exists():
            FIXTURE.parent.mkdir()
        FIXTURE.write_text(json.dumps(fixture, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        print("PASS：独立 CSV 预期与合成图表 fixture 已生成", FIXTURE)


def readonly_app():
    """作为 Streamlit 测试入口执行原 app，刷新也提前关闭自动抓取。"""
    import streamlit as st
    st.session_state["auto_fetch_done"] = True
    with unchanged_data(), block_mutations():
        scope = {"__name__": "__main__", "__file__": str(APP)}
        exec(compile(APP.read_text(encoding="utf-8"), str(APP), "exec"), scope)
        st.markdown('<span id="chart-readonly-test" hidden>只读图表回归</span>', unsafe_allow_html=True)


def main():
    parser = argparse.ArgumentParser(description="只读图表回归")
    modes = parser.add_mutually_exclusive_group()
    for mode in ("unit-only", "fixtures-only", "app-only", "serve-readonly", "readonly-app"):
        modes.add_argument(f"--{mode}", action="store_true")
    args = parser.parse_args()
    if args.readonly_app:
        readonly_app()
        return
    if args.serve_readonly:
        import subprocess
        with unchanged_data():
            subprocess.run([sys.executable, "-m", "streamlit", "run", str(Path(__file__).resolve()),
                            "--server.address", "127.0.0.1", "--server.port", "8511",
                            "--server.headless", "true", "--browser.gatherUsageStats", "false",
                            "--", "--readonly-app"], check=True)
        return
    with unchanged_data():
        if args.fixtures_only:
            browser_fixtures()
            return
        if args.app_only:
            app_regression()
            return
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls)
                                   for cls in (ChartRangeTests, StageSummaryTests))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        if not result.wasSuccessful():
            raise SystemExit(1)
        if not args.unit_only:
            app_regression()
            browser_fixtures()


if __name__ == "__main__":
    main()
