#!/usr/bin/env python
"""体检：页面上的数对不对，一条命令查完。

    ./myenv/bin/python scripts/doctor.py                # 查最近在用的账户
    ./myenv/bin/python scripts/doctor.py --acct sim-c01062
    ./myenv/bin/python scripts/doctor.py --fix          # 先把落后的净值补一遍再查
    ./myenv/bin/python scripts/doctor.py --json         # 给程序读

查的是「症状背后的硬约束」，不是猜：
- 五组数据文件最新到哪天（少扫一组 = 文件更新了但页面不动）
- 每只基金的净值停在哪天（停住会被 ffill 成直线，市值和今日收益全错）
- 场内市价到没到、折溢价多大
- 三处口径是否自洽：plan.total vs 曲线末端、头卡今日 vs 收益日历、市值 vs 份额×价
- 这份实例是不是市价口径

退出码：有红项 = 1，其余 = 0。可以直接挂到 cron / CI 里。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "streamlit_app"))

COLOR = {"ok": "\033[32m", "warn": "\033[33m", "bad": "\033[31m"}
DIM, RESET = "\033[2m", "\033[0m"


def main() -> int:
    ap = argparse.ArgumentParser(description="全天气再平衡 · 数据与口径自检")
    ap.add_argument("--acct", help="账户 id，默认最近在用的那个")
    ap.add_argument("--fix", action="store_true", help="先补一遍场外净值再查")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    from allweather import accounts as AC
    from allweather import selfcheck

    aid = args.acct or AC.last() or "main"
    import api.server as S

    if args.fix:
        if not args.json:
            print(f"{DIM}先补一遍场外基金净值…{RESET}")
        errs = S._refresh_fund_nav()
        if not args.json:
            print(f"{DIM}补数完成{'，' + str(len(errs)) + ' 项失败' if errs else ''}{RESET}"
                  + (("\n  " + "\n  ".join(errs)) if errs else ""))

    # 先把现价灌进缓存再建 Portfolio：`spots_now` 是非阻塞的，直接建出来的实例是净值口径，
    # 自检就会误报「行情没到位」（服务进程靠启动预热避开这一段，命令行没有）。
    try:
        from allweather import quote as QUOTE
        _a0 = AC.load(aid) or {}
        _codes = sorted({str(t.get("code") or "") for t in (_a0.get("trades") or [])} - {""})
        if _codes:
            QUOTE.snapshot(_codes)
    except Exception:  # noqa: BLE001  行情取不到就让它按净值算，后面自检里会报
        pass

    a = AC.load(aid) or {}
    try:
        P = S._portfolio(aid)[0]
        rep = selfcheck.run(P, a, blocking_quotes=True)
    except Exception as e:  # noqa: BLE001  账户算不出来时仍然把净值/行情查完，别丢线索
        rep = selfcheck.run(None, a, blocking_quotes=True, error=str(e))
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 0 if rep["ok"] else 1

    print(f"\n全天气再平衡 · 自检   {datetime.now():%Y/%m/%d %H:%M}")
    print(f"{DIM}账户 {aid} · {a.get('name') or ''} · 数据截至 {rep['asof'] or '—'}{RESET}\n")
    for c in rep["checks"]:
        print(f"{COLOR[c['level']]}[{c['icon']}]{RESET} {c['title']}")
        if c["detail"]:
            print(f"      {DIM}{c['detail']}{RESET}")
        if c["fix"]:
            print(f"      {DIM}→ {c['fix']}{RESET}")
    print()
    if rep["ok"]:
        print(f"{COLOR['ok']}全部通过{RESET}" + (f"（{rep['warn']} 项提示）" if rep["warn"] else ""))
    else:
        print(f"{COLOR['bad']}{rep['bad']} 项需要修{RESET}" + (f"，{rep['warn']} 项提示" if rep["warn"] else ""))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
