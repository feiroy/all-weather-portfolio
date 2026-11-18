"""界面「只许有一份实现」的硬检查（2026-11-19 用户：表格、曲线必须统一）。

背景：收益日历在三个页面各写过一遍 —— 市场 · 基金详情（`Funds.vue`）、收益明细（`Period.vue`）、
账户 · 基金详情（`Fund.vue`）。第三次（`Fund.vue`）不但没复用，还另起了一套
`.grid7 / .pgrid / .pcell` 样式，同一个日历在三处长得不一样。用户当时的话是
「这个表格为啥没和其他页面里用成一个呢……有办法写成单测吗，加进测试流程里，违反就重新实现」。

所以这里不测业务，测**结构**：格子只能由 `components/ReturnCal.vue` 画，曲线只能由
`components/` 里的图表组件画。谁再在 views 里手写一遍，这个文件立刻挂。
"""
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "web/src"
VIEWS = WEB / "views"
CAL = WEB / "components/ReturnCal.vue"

# 日历专属的标记：出现在 views 里就说明又手写了一份。
# 不收 `.grid3`：首页那张资产卡的三列 KPI 也叫 grid3，它不是日历，别误伤。
CAL_MARKERS = [
    'class="wk"',                        # 星期行
    'class="grid7"',                     # 7 列网格
    'class="cell big"',                  # 月/年的格子
    "repeat(7,1fr)",                     # 7 列网格的样式
    '"一二三四五六日"',                   # 星期文字
    ".grid7{", ".cell{", ".wk{",           # 格子样式本身
]

# 这两个页面以前就有日历，必须继续走组件（防止「改成别的写法」绕过上面的标记检查）
CAL_PAGES = ["Fund.vue", "Funds.vue", "Period.vue"]


def _views():
    return sorted(VIEWS.glob("*.vue"))


def _read(p):
    return p.read_text(encoding="utf-8")


def test_calendar_component_exists():
    assert CAL.is_file(), "收益日历必须在 web/src/components/ReturnCal.vue 里"
    src = _read(CAL)
    for cls in ['class="wk"', 'class="cell"', "grid.g7"]:
        assert cls in src, f"ReturnCal.vue 里少了日历本体：{cls}"


@pytest.mark.parametrize("bad", CAL_MARKERS)
def test_views_do_not_reimplement_calendar(bad):
    """views 里不许再出现日历的网格/星期/格子样式 —— 用 ReturnCal。"""
    hits = [p.name for p in _views() if bad in _read(p)]
    assert not hits, (
        f"{hits} 里又手写了收益日历（命中 {bad!r}）。"
        "格子只能有 components/ReturnCal.vue 一份：把数据按 "
        "{ key, d | label, v, p, state?, act? } 传进去，格式用 :fmt / :sub-fmt 决定。"
    )


@pytest.mark.parametrize("page", CAL_PAGES)
def test_pages_use_calendar_component(page):
    src = _read(VIEWS / page)
    assert "ReturnCal" in src, f"{page} 展示了收益日历却没引用 ReturnCal.vue"


def test_views_do_not_import_echarts():
    """曲线只能由 components 里的图表组件画（LineChart / MultiLine / Heatmap），
    页面直接 import echarts 就是又一份实现。"""
    bad = [p.name for p in _views() if "from 'echarts" in _read(p)]
    assert not bad, f"{bad} 直接引了 echarts；请用 components/ 里的图表组件"


def test_calendar_source_of_truth_is_single_file():
    """全站只有 ReturnCal.vue 能写 7 列网格的 CSS。"""
    hits = [p.name for p in WEB.rglob("*.vue")
            if "repeat(7" in _read(p) and p.name != "ReturnCal.vue"]
    assert not hits, f"{hits} 里还有 7 列网格的样式定义；日历只在 ReturnCal.vue 里实现"
