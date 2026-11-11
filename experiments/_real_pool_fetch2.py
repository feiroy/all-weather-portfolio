"""方案 B 补拉：真实基金齐全版需要但 A / A+ 没用到的几只。

    ./myenv/bin/python experiments/_real_pool_fetch2.py

方案 B 目标：不拼接、不合成，但尽量贴近原 9 资产策略结构。
为此要补：
    divlow      512890 红利低波 ETF      （决定方案 B 的公共起点）
    credit_etf  511220 城投债 ETF        （A 用的是场外 000032，这里换场内真 ETF 做对照）
    bond_10y_a  511260 10 年国债 ETF     （A 用的是 511010 5 年期，对照一下久期差异）
    bond_short  511360 短融 ETF          （进面板但本就不进策略）
bond_30y（511130）不补 —— 真实净值 2024-04 才有，拼不出长窗口。
"""
from __future__ import annotations

from pathlib import Path

from experiments._real_pool_fetch import OUT, fetch

POOL2 = {
    "divlow":     ("512890", "华泰柏瑞中证红利低波动 ETF"),
    "credit_etf": ("511220", "海富通上证城投债 ETF"),
    "bond_10y_a": ("511260", "国泰上证 10 年期国债 ETF"),
    "bond_short": ("511360", "海富通中证短融 ETF"),
}


def main():
    Path(OUT).mkdir(parents=True, exist_ok=True)
    print(f"{'key':13s}{'代码':8s}{'条数':>6s}  {'首日':11s}{'末日':11s}{'缺chg':>6s}  名称")
    for key, (code, name) in POOL2.items():
        df = fetch(code)
        if df.empty:
            print(f"{key:13s}{code:8s}  抓取为空")
            continue
        df.to_csv(Path(OUT) / f"{key}.csv", index=False)
        miss = int(df["chg"].isna().sum())
        print(f"{key:13s}{code:8s}{len(df):6d}  {df['date'].iloc[0].date()!s:11s}"
              f"{df['date'].iloc[-1].date()!s:11s}{miss:6d}  {name}")


if __name__ == "__main__":
    main()
