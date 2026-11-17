"""调仓计划的买入必须由「卖出到账 + 现金」支付（2026-11-17）。

账户模型是「不留现金」：买入的钱只能来自卖出。原来 `_plan()` 不校验这一点，
于是一个「30 年国债一手买多了、又不足一手卖不掉」的账户会拿到
**卖出 ¥0、现金 ¥0、买入 ¥1,967** 的计划 —— 钱没有出处。

用户原话：「有问题，为啥还需要买1960，昨天买的时候是按推荐比例买的，怎么变了？」
他要的不是再买一笔，而是「为什么还要我出钱」；答案是：那 2,038 元是场内一整手取整
多买的，而这次计划在追它，却既没有卖出也说不清钱从哪来。

所以两条硬约束：
  1. 任何账户：买入总额 ≤ 卖出总额 + 现金；
  2. 没卖出又没现金时，不能有任何买入单 —— 缺口只登记成 `need`，让用户自己决定要不要加钱。
"""
import pytest

from allweather import accounts as AC
from allweather.portfolio import Portfolio

AIDS = ("sim-c01062", "main")


def _portfolio(aid: str) -> Portfolio:
    import api.server as S

    a = AC.load(aid)
    if not a:
        pytest.skip(f"没有 {aid} 账户")
    w = S.strategy_weights(a.get("strategy"), a)[0]
    P = Portfolio(a, w)
    if any(r["px"] <= 0 for r in P.plan["rows"]):
        pytest.skip("本地缺这几只基金的净值缓存")
    return P


@pytest.mark.parametrize("aid", AIDS)
def test_buy_never_exceeds_sell_plus_cash(aid):
    p = _portfolio(aid).plan
    assert p["buy"] <= p["sell"] + p["cash"] + 0.01, \
        f"{aid}: 买入 {p['buy']:.2f} > 卖出 {p['sell']:.2f} + 现金 {p['cash']:.2f}，钱没有出处"


@pytest.mark.parametrize("aid", AIDS)
def test_no_buy_orders_when_nothing_to_fund_them(aid):
    P = _portfolio(aid)
    p = P.plan
    if p["sell"] > 0.01:
        pytest.skip(f"{aid} 这一轮有卖出，买入可以由卖出支付")
    assert not [o for o in p["orders"] if o["side"] == "买入"], "没卖出也没现金，却给了买入单"
    if p["need"] > 0:
        # 缺口要登记出来，页面才能解释「为什么不动 / 还差多少钱」
        assert P.status()["kind"] == "stuck"
        assert P.status()["need"] == pytest.approx(p["need"], abs=0.01)


@pytest.mark.parametrize("aid", AIDS)
def test_rows_note_explains_missing_money(aid):
    """被砍掉的买入行要写明原因，不能默默把 side 清空让用户以为不用买。"""
    p = _portfolio(aid).plan
    dropped = [it for it in p["rows"] if not it["side"] and "没钱买" in (it.get("note") or "")]
    if p["need"] <= 0:
        assert not dropped
        return
    assert dropped, "有缺口却没有任何一行说明原因"
    assert all(it["qty"] == 0 and it["amount"] == 0 for it in dropped)
