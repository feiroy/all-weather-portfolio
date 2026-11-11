"""方案 A / A+ / B：三套「纯真实基金」池 + 「拼接到底骗在哪」归因。

    PYTHONPATH=. ./myenv/bin/python experiments/_real_pool_abc.py

规则：一条拼接都不做。每个资产 = 一只真实基金，收益 = 官方日增长率 JZZZL 累乘
（不用累计净值，分红会稀释；场外基金尤其严重）。

三套池（键名沿用策略里的资产名，只换数据源，策略代码不动）：

  A   5 只 · 长窗口 · 允许标的替代
       hs300 160706 / us_sp500 050025 / credit 000032 / bond_10y 511010 / gold 518880
       2013-07 起 13.3 年。代价：通胀桶只剩黄金，债券是 5 年期不是 10 年期。

  A+  7 只 · 长窗口 · 商品"有替代品"
       A + nonferr 160221（国证有色股票指数基金）/ ene 160216（QDII 商品配置）
       2015-04 起 11.6 年。注意：这两只和生产用的 159980/159981 期货 ETF 标的不同，
       一个是股票一个是期货，只能算"同一宏观角色的替代品"。

  B   8 只 · 生产标的原样 · 全真实净值
       510300 / 513500 / 511220 / 511260 / 518850 / 159980 / 159981 / 512890
       2020-04 起 6.6 年。代价：没有 bond_30y（511130 真实净值 2024-03 才有）。

  表 2 是同一资产组合、同一窗口、同一标的，只把数据源从项目面板换成基金真实净值，
  差 = 「数据/复权口径」的净影响。表 3 单独量化 bond_30y 这个拼接资产的分量。
"""
from __future__ import annotations

import warnings

import pandas as pd

warnings.filterwarnings("ignore")

from allweather import data as D          # noqa: E402
from allweather import pipeline as P      # noqa: E402

STRATS = ("V3-B 保守增强", "V3-B 风险平价", "V3c 多元")
_ORIG_SA, _ORIG_BK = P.STRATEGY_ASSETS, P.V3B_RP_BUCKETS

B5 = {"增长↑": ["hs300", "us_sp500"], "收益垫": ["credit"],
      "增长↓": ["bond_10y"], "通胀↑": ["gold"]}
B7 = {"增长↑": ["hs300", "us_sp500"], "收益垫": ["credit"],
      "增长↓": ["bond_10y"], "通胀↑": ["gold", "nonferr", "ene"]}
B8 = {"增长↑": ["hs300", "us_sp500", "divlow"], "收益垫": ["credit"],
      "增长↓": ["bond_10y"], "通胀↑": ["gold", "nonferr", "ene"]}

POOLS = [
    dict(tag="A", n=5, buckets=B5, spec={
        "hs300": "hs300", "us_sp500": "us_sp500", "credit": "credit",
        "bond_10y": "bond_10y", "gold": "gold"}),
    dict(tag="A+", n=7, buckets=B7, spec={
        "hs300": "hs300", "us_sp500": "us_sp500", "credit": "credit",
        "bond_10y": "bond_10y", "gold": "gold",
        "nonferr": "nonferr", "ene": "ene"}),
    dict(tag="B", n=8, buckets=B8, spec={
        "hs300": "p_hs300", "us_sp500": "p_sp500", "credit": "p_credit",
        "bond_10y": "p_bond10", "gold": "p_gold",
        "nonferr": "p_nonferr", "ene": "p_ene", "divlow": "divlow"}),
    dict(tag="B30", n=9, buckets={**B8, "增长↓30Y": ["bond_30y"]}, spec={
        "hs300": "p_hs300", "us_sp500": "p_sp500", "credit": "p_credit",
        "bond_10y": "p_bond10", "bond_30y": "p_bond30", "gold": "p_gold",
        "nonferr": "p_nonferr", "ene": "p_ene", "divlow": "divlow"}),
]


# ------------------------------------------------------------ 数据装配
def _cum(fname: str) -> pd.Series:
    """单只基金复权曲线。主口径 = 官方日增长率；缺的时候的兜底顺序很关键：

    1. chg（JZZZL）：正确，含分红再投
    2. ljjz.pct_change()：累计净值只受分红影响（会轻微低估），但**不受份额折算影响**
    3. unit_nav.pct_change()：只在累计净值缺失时用，且必须剔除 |x|>30% 的跳变
       —— 518850 黄金 ETF 2020-05-29 做过份额合并（单位净值 1.0098→3.9217，
       累计净值不变），按单位净值算会把这次拆分当成 +288% 的收益。
    """
    df = pd.read_csv(f"data/real/{fname}.csv", parse_dates=["date"]).set_index("date").sort_index()
    r = df["chg"] / 100.0
    if r.isna().any():
        r = r.fillna(df["ljjz"].pct_change())
    if r.isna().any():
        un = df["unit_nav"].pct_change().where(lambda s: s.abs() <= 0.30)
        r = r.fillna(un)
    return (1.0 + r.dropna()).cumprod()


def build_rets(spec: dict[str, str]) -> pd.DataFrame:
    """按 A 股日历对齐：境外节假日缺净值那天净值 ffill（记 0 涨幅），
    不把两天涨幅挤进一天，也不制造人为缺失行。"""
    cum = {k: _cum(f) for k, f in spec.items()}
    cal = cum["hs300"].index
    g = pd.DataFrame({k: s.reindex(cal).ffill() for k, s in cum.items()})
    return g.pct_change().dropna(how="any")


def stats(nv: pd.Series) -> dict:
    nv = nv.dropna()
    yrs = (nv.index[-1] - nv.index[0]).days / 365.25
    cagr = nv.iloc[-1] ** (1 / yrs) - 1
    mdd = (nv / nv.cummax() - 1).min()
    r = nv.pct_change().dropna()
    vol = r.std() * (252 ** 0.5)
    yv = nv.groupby(nv.index.year).last()
    yr = yv.pct_change()
    yr.iloc[0] = yv.iloc[0] / nv.iloc[0] - 1
    return {"years": yrs, "cagr": cagr * 100, "mdd": mdd * 100, "vol": vol * 100,
            "sharpe": (cagr - 0.017) / vol if vol else float("nan"),
            "calmar": cagr / abs(mdd) if mdd else float("nan"),
            "neg": {int(i): round(v * 100, 2) for i, v in yr[yr < 0].items()}}


def run_board(rets: pd.DataFrame, keys, buckets) -> dict:
    P.STRATEGY_ASSETS = {k: list(keys) for k in STRATS}
    P.V3B_RP_BUCKETS = {k: list(v) for k, v in buckets.items()}
    r = rets[[c for c in keys if c in rets.columns]]
    out = {}
    for st in STRATS:
        kw = {"assets": list(keys)} if st == "V3c 多元" else {}
        out[st] = stats(P.run_strategy_backtest(r, st, "monthly", **kw).nv)
    return out


def run_production(rets: pd.DataFrame, drop: tuple = ()) -> dict:
    P.STRATEGY_ASSETS, P.V3B_RP_BUCKETS = _ORIG_SA, _ORIG_BK
    if drop:
        P.STRATEGY_ASSETS = {k: [a for a in v if a not in drop] for k, v in _ORIG_SA.items()}
        bk = {k: [a for a in v if a not in drop] for k, v in _ORIG_BK.items()}
        P.V3B_RP_BUCKETS = {k: v for k, v in bk.items() if v}
    d = rets.drop(columns=[c for c in drop if c in rets.columns])
    out = {}
    for st in STRATS:
        kw = {"assets": [a for a in P.STRATEGY_ASSETS[st] if a in d.columns]} if st == "V3c 多元" else {}
        out[st] = stats(P.run_strategy_backtest(d, st, "monthly", **kw).nv)
    return out


def row(tag, n, start, s, first=True):
    head = (f"{tag:5s}{n:3d}  {start:%Y-%m-%d}  " if first else " " * 22)
    return (f"{head}{s['cagr']:7.2f}%{s['mdd']:8.2f}%{s['vol']:7.2f}%"
            f"{s['sharpe']:7.2f}{s['calmar']:8.2f}  {s['neg']}")


def main():
    legacy_all = D.load_panel().pct_change().dropna(how="all")

    real, lgap, rets_of, start_of = {}, {}, {}, {}
    for p in POOLS:
        rr = build_rets(p["spec"])
        start, keys = rr.index[0], list(p["spec"])
        rets_of[p["tag"]], start_of[p["tag"]] = rr, start
        real[p["tag"]] = (run_board(rr, keys, p["buckets"]), start)
        lgap[p["tag"]] = run_board(legacy_all.loc[start:], keys, p["buckets"])
        print(f"· {p['tag']:3s} 真实 {p['n']} 只  {start:%Y-%m-%d} 起  "
              f"{real[p['tag']][0][STRATS[0]]['years']:.1f} 年")

    print("\n" + "═" * 100)
    print("表 1  纯真实基金池 · 三策略")
    print("═" * 100)
    print(f"{'方案':7s}{'只数':>3s}{'起点':>13s}{'年化':>8s}{'回撤':>9s}{'波动':>8s}"
          f"{'夏普':>7s}{'Calmar':>8s}  策略 / 负年")
    print("─" * 100)
    for p in POOLS:
        board, start = real[p["tag"]]
        for st in STRATS:
            print(row(p["tag"], p["n"], start, board[st]) + f"  {st}")
        print()

    print("═" * 100)
    print("表 2  同池 · 同窗口 · 同标的，只换数据源（真实净值 vs 项目面板）")
    print("═" * 100)
    print(f"{'方案':8s}{'起点':>12s}{'策略':13s}{'真实年化':>9s}{'面板年化':>9s}{'差':>10s}"
          f"{'真实回撤':>10s}{'面板回撤':>10s}{'差':>10s}{'真实夏普':>9s}{'面板夏普':>9s}")
    print("─" * 108)
    for p in POOLS:
        a, start = real[p["tag"]]
        b = lgap[p["tag"]]
        for i, st in enumerate(STRATS):
            head = f"{p['tag']:8s}{start:%Y-%m-%d}  " if i == 0 else " " * 22
            print(f"{head}{st:13s}{a[st]['cagr']:8.2f}%{b[st]['cagr']:8.2f}%"
                  f"{a[st]['cagr']-b[st]['cagr']:+9.2f}pp"
                  f"{a[st]['mdd']:9.2f}%{b[st]['mdd']:9.2f}%{a[st]['mdd']-b[st]['mdd']:+9.2f}pp"
                  f"{a[st]['sharpe']:9.2f}{b[st]['sharpe']:9.2f}")
        dl = sum(a[st]["cagr"] - b[st]["cagr"] for st in STRATS) / 3
        dd = sum(a[st]["mdd"] - b[st]["mdd"] for st in STRATS) / 3
        ds = sum(a[st]["sharpe"] - b[st]["sharpe"] for st in STRATS) / 3
        print(f"{'':8s}{'':12s}{'均值':13s}{'':9s}{'':9s}{dl:+9.2f}pp{'':11s}{'':11s}"
              f"{dd:+9.2f}pp{'':10s}{ds:+9.2f}")
        print()

    # ---------------------------------------------------------- 表 3
    print("═" * 100)
    print("表 3  同窗口换池：分离「窗口变短」与「加/换资产」")
    print("═" * 100)
    print(f"{'窗口':12s}{'池':5s}{'只数':>3s}{'策略':13s}{'年化':>8s}{'回撤':>9s}"
          f"{'波动':>8s}{'夏普':>7s}{'Calmar':>8s}")
    print("─" * 100)
    for win, tags in (("2015-04-07", ("A", "A+")), ("2020-04-20", ("A", "A+", "B"))):
        for tg in tags:
            p = [x for x in POOLS if x["tag"] == tg][0]
            keys = [k for k in p["spec"] if k in rets_of[tg].columns]
            board = run_board(rets_of[tg].loc[win:], keys, p["buckets"])
            for i, st in enumerate(STRATS):
                s = board[st]
                head = f"{win:12s}{tg:5s}{len(keys):3d}" if i == 0 else " " * 20
                print(f"{head}{st:13s}{s['cagr']:7.2f}%{s['mdd']:8.2f}%{s['vol']:7.2f}%"
                      f"{s['sharpe']:7.2f}{s['calmar']:8.2f}")
            print()

    # ---------------------------------------------------------- 表 4
    print("═" * 100)
    print("表 4  生产口径（原 9 资产）单独抽掉 bond_30y —— 回测的浅回撤靠的是哪只资产")
    print("═" * 100)
    for win in ("2013-07-22", "2018-12-24"):
        full = run_production(legacy_all.loc[win:])
        n30 = run_production(legacy_all.loc[win:], drop=("bond_30y",))
        print(f"\n窗口 {win} 起 · {full[STRATS[0]]['years']:.1f} 年")
        print(f"{'口径':24s}{'策略':13s}{'年化':>8s}{'回撤':>9s}{'波动':>8s}{'夏普':>7s}{'Calmar':>8s}")
        print("─" * 100)
        for i, st in enumerate(STRATS):
            s = full[st]
            head = f"{'含 bond_30y（现值）':24s}" if i == 0 else " " * 24
            print(f"{head}{st:13s}{s['cagr']:7.2f}%{s['mdd']:8.2f}%{s['vol']:7.2f}%"
                  f"{s['sharpe']:7.2f}{s['calmar']:8.2f}")
        for i, st in enumerate(STRATS):
            s = n30[st]
            head = f"{'抽掉 bond_30y':24s}" if i == 0 else " " * 24
            print(f"{head}{st:13s}{s['cagr']:7.2f}%{s['mdd']:8.2f}%{s['vol']:7.2f}%"
                  f"{s['sharpe']:7.2f}{s['calmar']:8.2f}")
        for i, st in enumerate(STRATS):
            d1, d2 = full[st], n30[st]
            head = f"{'bond_30y 的贡献':24s}" if i == 0 else " " * 24
            print(f"{head}{st:13s}{d1['cagr']-d2['cagr']:+7.2f}pp{d1['mdd']-d2['mdd']:+8.2f}pp"
                  f"{d1['vol']-d2['vol']:+7.2f}pp{d1['sharpe']-d2['sharpe']:+7.2f}"
                  f"{d1['calmar']-d2['calmar']:+8.2f}")

    # bond_30y 拼接段 vs 真实 511130
    panel = D.load_panel()
    b30 = panel["bond_30y"].pct_change().dropna()
    b30 = b30[b30.index >= pd.Timestamp(win)]
    r30 = pd.read_csv("data/real/p_bond30.csv", parse_dates=["date"]).set_index("date")
    r30r = (1 + r30["chg"].fillna(r30["unit_nav"].pct_change()).dropna() / 100).cumprod()
    r30r = r30r.pct_change().dropna()
    ov = b30.index.intersection(r30r.index)
    print(f"\nbond_30y：拼接段 2018-12~2024-03 年化波动 {b30.loc[:'2024-03-19'].std()*252**0.5*100:.2f}%"
          f" / 真实 511130 2024-03 后 {r30r.std()*252**0.5*100:.2f}%"
          f" / 重合 {len(ov)} 天日收益相关 {b30.loc[ov].corr(r30r.loc[ov]):.3f}")


if __name__ == "__main__":
    main()
