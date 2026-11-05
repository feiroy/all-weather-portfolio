"""账户视图：一个账户的持仓、收益、调仓计划 —— 不依赖 Streamlit 的纯计算层。

H5 前端（api/server.py）用它；口径逐行照搬 streamlit_app/app.py 里的同名函数
（_replay_holdings / _hg_plan / _held_day / _money_index / _plan_status / _pf_row …），
两边数字必须一模一样 —— tests/test_portfolio.py 拿主账户对过。
等 H5 版补齐功能后，Streamlit 版也改成调这里，删掉那份重复实现。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from . import holdings as HG
from .config import ETF_META

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "streamlit_app"))
import fund_lookup as FL  # noqa: E402

MONEY_IN = ("转入", "入金")
MONEY_OUT = ("转出", "出金")


def min_order(tgt_amt: float) -> float:
    """单只基金值不值得单独下一笔：目标金额的 5%，至少 1 元（见 app.py 同名函数的说明）。"""
    return max(1.0, abs(tgt_amt) * 0.05)


class Portfolio:
    """acct：账户文件内容（含 trades / holdings）；target_w：资产 key → 目标权重（策略算好的）。"""

    def __init__(self, acct: dict, target_w):
        self.acct = acct or {}
        self.holdings = ({s: HG._norm_slot(v) for s, v in self.acct["holdings"].items()}
                         if self.acct.get("holdings") else HG._default_holdings())
        self.trades = list(self.acct.get("trades") or [])
        self.panel = HG.nav_panel(self.holdings)
        self._navcache: dict[str, pd.Series] = {}
        self._rawcache: dict[str, pd.DatetimeIndex] = {}
        self.first_trade: dict[str, pd.Timestamp] = {}
        for t in self.trades:
            if t.get("side") not in ("买入", "卖出"):
                continue
            try:
                d = pd.Timestamp(t["date"])
            except Exception:  # noqa: BLE001
                continue
            c = str(t.get("code") or "")
            if c and (c not in self.first_trade or d < self.first_trade[c]):
                self.first_trade[c] = d
        self.daily, self.pos, self.cost, self.cash, self.units = self._replay()
        self.last = self.panel.index[-1] if len(self.panel) else pd.Timestamp.today().normalize()
        self.slot_w = HG.slot_weights(target_w, self.holdings)
        self.active_codes = {c for s in HG.active(self.holdings) for c in HG.codes(self.holdings[s])}
        self.cfg_codes = set(HG.all_codes(self.holdings))
        self.plan = self._plan()

    # ------------------------------------------------------------ 净值
    def nav(self, code: str) -> pd.Series:
        if code in self.panel.columns:
            col = self.panel[code].dropna()
            if len(col):
                return col
        if code not in self._navcache:
            self._navcache[code] = HG.nav_series(code)
        return self._navcache[code]

    def nav_on(self, code: str, day) -> float | None:
        col = self.nav(code)
        if not len(col):
            return None
        sub = col.loc[:pd.Timestamp(day)]
        return float(sub.iloc[-1]) if len(sub) else None

    # ------------------------------------------------------------ 重放（app.py::_replay_holdings）
    def _replay(self):
        created = self.acct.get("created")
        p = self.panel
        idx = p.index[p.index >= pd.Timestamp(created)] if (len(p) and created) else pd.DatetimeIndex([])
        if len(idx) == 0:
            idx = p.index[-1:] if len(p) else pd.DatetimeIndex([])
        capital = float(self.acct.get("capital") or 0)
        if len(idx) == 0:
            return pd.DataFrame(), {}, {}, capital, capital
        buckets: dict = {}
        for t in self.trades:
            try:
                d = pd.Timestamp(t.get("date"))
            except Exception:  # noqa: BLE001
                continue
            buckets.setdefault(idx[min(int(idx.searchsorted(d)), len(idx) - 1)], []).append(t)
        cash, units, last_nav = capital, capital, 1.0
        pos: dict[str, float] = {}
        cost: dict[str, float] = {}
        rows = []
        for d in idx:
            for t in buckets.get(d, []):
                code = str(t.get("code", "") or "")
                sh = float(t.get("shares", 0) or 0)
                px = float(t.get("nav", 0) or 0)
                fee = float(t.get("fee", 0) or 0)
                side = t.get("side")
                if side == "买入" and code and sh > 0:
                    if px <= 0:
                        px = self.nav_on(code, d) or 0
                    cash -= sh * px + fee
                    prev = pos.get(code, 0.0)
                    cost[code] = ((prev * cost.get(code, 0.0) + sh * px + fee) / (prev + sh)) if (prev + sh) > 0 else px
                    pos[code] = prev + sh
                elif side == "卖出" and code and sh > 0:
                    if px <= 0:
                        px = self.nav_on(code, d) or 0
                    cash += sh * px - fee
                    pos[code] = pos.get(code, 0.0) - sh
                    if pos[code] <= 1e-9:
                        pos.pop(code, None)
                        cost.pop(code, None)
                elif side in MONEY_IN:
                    units += sh / (last_nav if last_nav > 0 else 1.0)
                    cash += sh
                elif side in MONEY_OUT:
                    units = max(1e-9, units - sh / (last_nav if last_nav > 0 else 1.0))
                    cash -= sh
            mv = sum(sh * v for c, sh in pos.items() if (v := self.nav_on(c, d)))
            eq = cash + mv
            last_nav = eq / units if units > 0 else 1.0
            rows.append({"date": d, "equity": eq, "cash": cash, "market": mv})
        daily = pd.DataFrame(rows).set_index("date")
        fl = self.flows(daily.index)
        inv = capital + fl.cumsum()
        peak = float(inv.max()) if len(inv) else 0.0
        daily["invested"] = inv
        daily["pnl"] = daily["equity"] - inv
        # 收益 / 本金口径的指数（app.py::_money_index）：今天的值 = 持有收益率
        daily["nav"] = (1.0 + daily["pnl"] / peak) if peak > 0 else 1.0
        return daily, pos, cost, cash, units

    def flows(self, idx) -> pd.Series:
        out = pd.Series(0.0, index=idx)
        for t in self.trades:
            side = t.get("side")
            if side not in MONEY_IN + MONEY_OUT:
                continue
            try:
                d = pd.Timestamp(t.get("date"))
            except Exception:  # noqa: BLE001
                continue
            i = min(int(idx.searchsorted(d)), len(idx) - 1)
            amt = float(t.get("shares", 0) or 0)
            out.iloc[i] += -amt if side in MONEY_OUT else amt
        return out

    def invested_now(self) -> float:
        v = float(self.acct.get("capital") or 0)
        for t in self.trades:
            if t.get("side") in MONEY_IN:
                v += float(t.get("shares") or 0)
            elif t.get("side") in MONEY_OUT:
                v -= float(t.get("shares") or 0)
        return v

    # ------------------------------------------------------------ 今日（app.py::_held_day）
    def held_day(self, code, shares, px, px_prev, prev_day=None) -> tuple[float, float | None]:
        shares, px, px_prev = float(shares or 0), float(px or 0), float(px_prev or 0)
        if shares <= 0 or px <= 0:
            return 0.0, None
        f = self.first_trade.get(str(code))
        if f is not None and prev_day is not None and f > pd.Timestamp(prev_day):
            return 0.0, None
        return (px - px_prev) * shares, ((px / px_prev - 1) * 100 if px_prev > 0 else None)

    # ------------------------------------------------------------ 调仓计划（app.py::_hg_plan）
    def _plan(self) -> dict:
        h, cash = self.holdings, float(self.cash or 0)
        mv_by_slot, seen = {}, set()
        for s in HG.active(h):
            v = 0.0
            for code in HG.codes(h[s]):
                if code in seen:
                    continue
                sh = float(self.pos.get(code, 0) or 0)
                if sh <= 0 or code not in self.panel.columns:
                    continue
                col = self.panel[code].dropna()
                if len(col):
                    v += sh * float(col.iloc[-1])
                    seen.add(code)
            if v > 0:
                mv_by_slot[s] = v
        asset = float(sum(mv_by_slot.values())) + cash
        rows, orders = [], []
        buy_total = sell_total = mv_total = today = 0.0
        counted: dict[str, str] = {}
        for s in HG.active(h):
            funds = HG.funds(h[s])
            if not funds:
                continue
            tgt_w = float(self.slot_w.get(s, 0) or 0)
            tgt = tgt_w * asset
            items = []
            for f, x in zip(funds, HG.share_of(h[s])):
                code = f["code"]
                col = self.panel[code].dropna() if code in self.panel.columns else pd.Series(dtype=float)
                px = float(col.iloc[-1]) if len(col) else 0.0
                px_prev = float(col.iloc[-2]) if len(col) > 1 else px
                sh = float(self.pos.get(code, 0) or 0)
                cst = float(self.cost.get(code, 0) or 0)
                items.append({"f": f, "x": float(x), "code": code, "px": px, "px_prev": px_prev,
                              "px_prev_day": (col.index[-2] if len(col) > 1 else None),
                              "shares": sh, "cost": cst, "mv": sh * px, "dup": counted.get(code),
                              "pl": ((px / cst - 1) if (cst > 0 and px > 0) else None)})
                counted.setdefault(code, s)
            slot_mv = sum(it["mv"] for it in items if not it["dup"])
            mv_total += slot_mv
            today += sum(self.held_day(it["code"], it["shares"], it["px"], it["px_prev"],
                                       it["px_prev_day"])[0] for it in items if not it["dup"])
            slot_w = (slot_mv / asset) if asset else 0.0
            moved = abs(tgt - slot_mv) >= max(1.0, asset * 0.005)
            for i, it in enumerate(items):
                f = it["f"]
                diff = (tgt * it["x"] - it["mv"]) if moved else 0.0
                side, qty, amt, note, liq = "", 0.0, 0.0, "", False
                if it["px"] <= 0:
                    note = "缺净值"
                elif it["dup"]:
                    note = f'已在「{HG.SLOT_LABEL.get(it["dup"], it["dup"])}」计入'
                elif not moved or abs(diff) < min_order(tgt * it["x"]):
                    note = ""
                else:
                    qty, amt = HG.order_quantity(f, abs(diff), it["px"])
                    if qty <= 0:
                        note = "不足一手"
                    elif diff > 0:
                        side, buy_total = "买入", buy_total + amt
                    else:
                        side, sell_total = "卖出", sell_total + amt
                        liq = bool(it["shares"] > 0 and qty >= it["shares"] * (1 - 1e-9))
                it.update({"slot": s, "side": side, "qty": qty, "amount": amt, "note": note, "liq": liq,
                           "otc": HG.is_otc(f), "w_now": (0.0 if it["dup"] else it["mv"] / asset) if asset else 0.0,
                           "w_tgt": tgt_w * it["x"], "dev": ((slot_w - tgt_w) if i == 0 else 0.0),
                           "slot_w": slot_w, "slot_tgt_w": tgt_w, "slot_first": i == 0, "slot_n": len(items)})
                if side:
                    orders.append({"slot": s, "code": it["code"], "side": side, "shares": round(float(qty), 4),
                                   "nav": round(it["px"], 4), "amount": amt, "liq": liq})
                rows.append(it)
        other_mv = {c: sh * float(self.nav_on(c, self.last) or 0)
                    for c, sh in self.pos.items() if sh > 0 and c not in self.active_codes}
        other = [{"code": c, "mv": v, "in_cfg": c in self.cfg_codes} for c, v in other_mv.items() if v > 0]
        for c, sh in self.pos.items():
            if float(sh or 0) <= 0 or c in self.active_codes:
                continue
            nv = self.nav(c)
            if len(nv) > 1:
                today += self.held_day(c, float(sh), float(nv.iloc[-1]), float(nv.iloc[-2]), nv.index[-2])[0]
        total = mv_total + sum(o["mv"] for o in other) + cash
        base = self.invested_now()
        return {"asset": asset, "cash": cash, "mv": mv_total, "mv_all": mv_total + sum(o["mv"] for o in other),
                "total": total, "other": other, "rows": rows, "orders": orders,
                "buy": buy_total, "sell": sell_total, "today": today,
                "pnl": (total - base) if base > 0 else 0.0,
                "pnl_pct": ((total / base - 1) if base > 0 else 0.0)}

    # ------------------------------------------------------------ 结论（app.py::_plan_status）
    def status(self) -> dict:
        p = self.plan
        if p["orders"]:
            liq = [o for o in p["orders"] if o.get("liq")]
            return {"kind": "orders", "n": len(p["orders"]), "buy": p["buy"], "sell": p["sell"],
                    "liq": len(liq), "liq_amt": sum(o["shares"] * o["nav"] for o in liq)}
        over = sorted([it for it in p["rows"] if it.get("slot_first") and abs(it.get("dev") or 0) >= 0.005],
                      key=lambda it: -abs(it["dev"]))
        if not over:
            return {"kind": "calm"}
        w = over[0]
        return {"kind": "stuck", "n": len(over), "max_dev": abs(w["dev"]),
                "gap": abs(w["dev"]) * p["asset"], "lot": w["px"] * int(w["f"].get("lot") or 100),
                "note": w.get("note") or ""}

    # ------------------------------------------------------------ 给前端的结构
    def other_item(self, code: str, why: str) -> dict:
        nv = self.nav(code)
        px = float(nv.iloc[-1]) if len(nv) else 0.0
        px_prev = float(nv.iloc[-2]) if len(nv) > 1 else px
        sh, cst = float(self.pos.get(code, 0) or 0), float(self.cost.get(code, 0) or 0)
        meta = HG.fund_meta(self.holdings, code)[1] or {}
        return {"code": code, "f": meta, "slot": why, "x": 1.0, "slot_n": 1, "px": px, "px_prev": px_prev,
                "px_prev_day": (nv.index[-2] if len(nv) > 1 else None), "shares": sh, "cost": cst, "mv": sh * px,
                "pl": ((px / cst - 1) if (cst > 0 and px > 0) else None),
                "otc": HG.is_otc(meta) if meta else (HG.default_unit(code) == "份额"),
                "w_now": (sh * px / self.plan["total"]) if self.plan["total"] else 0.0, "w_tgt": None,
                "side": "", "qty": 0.0, "amount": 0.0, "note": "", "why": why, "dev": 0.0, "slot_first": True}

    def items(self) -> list[dict]:
        out = list(self.plan["rows"])
        for o in self.plan["other"]:
            out.append(self.other_item(o["code"], "位置已关闭" if o.get("in_cfg") else "不在配置里"))
        return out

    def holding(self, it: dict) -> dict:
        """一只基金 → 前端行（数值不格式化，前端自己排版）。"""
        code = it["code"]
        held = it["shares"] > 0
        day, day_pct = self.held_day(code, it["shares"], it["px"], it["px_prev"], it.get("px_prev_day"))
        hold = it["mv"] - it["shares"] * it["cost"]
        return {"code": code, "name": str(it["f"].get("name") or FL.fund_name(code) or code),
                "slot": HG.SLOT_LABEL.get(it["slot"], it["slot"]), "otc": bool(it["otc"]),
                "unit": "份" if it["otc"] else "股", "slot_n": it.get("slot_n", 1), "x": it.get("x", 1.0),
                "dup": bool(it.get("dup")), "held": held, "shares": it["shares"], "px": it["px"],
                "cost": it["cost"], "mv": it["mv"], "day": day if held else None,
                "day_pct": day_pct if held else None, "hold": hold if held else None,
                "hold_pct": (it["pl"] * 100 if (held and it["pl"] is not None) else None),
                "w_now": it["w_now"], "w_tgt": it.get("w_tgt"), "why": it.get("why", ""),
                "side": it.get("side", ""), "amount": it.get("amount", 0.0), "qty": it.get("qty", 0.0),
                "liq": bool(it.get("liq")), "note": it.get("note", "")}

    def month_curve(self) -> dict:
        """近一个月：起点记 0 的累计收益率(%) 与收益额（app.py::_head_month_curve_html 同口径）。"""
        d = self.daily
        if len(d) < 2:
            return {"dates": [], "ret": [], "money": []}
        nav, pnl = d["nav"].astype(float), d["pnl"].astype(float)
        i0 = int(nav.index.searchsorted(nav.index[-1] - pd.DateOffset(months=1), side="right")) - 1
        i0 = max(0, min(i0, len(nav) - 2))
        seg, ps = nav.iloc[i0:], pnl.iloc[i0:]
        return {"dates": [f"{x:%Y-%m-%d}" for x in seg.index],
                "ret": [round((float(v) / float(seg.iloc[0]) - 1) * 100, 4) for v in seg],
                "money": [round(float(v - ps.iloc[0]), 2) for v in ps]}

    def summary(self) -> dict:
        p = self.plan
        prev = p["total"] - p["today"]
        return {"total": p["total"], "today": p["today"], "today_pct": (p["today"] / prev * 100) if prev > 0 else 0.0,
                "pnl": p["pnl"], "pnl_pct": p["pnl_pct"] * 100, "cash": p["cash"],
                "asof": f"{self.last:%Y-%m-%d}", "created": self.acct.get("created"),
                "n_funds": len([r for r in p["rows"] if r["shares"] > 0]) + len(p["other"])}

    def slot_options(self) -> list[dict]:
        """记一笔可选的基金（app.py::_hg_slot_options）：参与调仓的在前，关掉的位置、已删的代码在后。"""
        out, off = [], []
        for s in HG.SLOTS:
            on = bool(self.holdings.get(s, {}).get("on", True))
            for f in HG.funds(self.holdings.get(s, {})):
                (out if on else off).append({"slot": s, "code": f["code"], "name": f.get("name") or FL.fund_name(f["code"]) or f["code"],
                                             "slot_label": HG.SLOT_LABEL[s] + ("（位置已关闭）" if not on else ""),
                                             "unit": "股" if str(f.get("unit") or HG.default_unit(f["code"])) == "股" else "份"})
        out += off
        have = {o["code"] for o in out}
        for c, sh in self.pos.items():
            if c not in have and float(sh or 0) > 0:
                out.append({"slot": "", "code": c, "name": FL.fund_name(c) or c, "slot_label": "已删除的位置",
                            "unit": "股" if HG.default_unit(c) == "股" else "份"})
        return out

    def held_on(self, code: str, day) -> float:
        held = 0.0
        for t in self.trades:
            if str(t.get("code") or "") != str(code) or str(t.get("date") or "") > str(day):
                continue
            if t.get("side") == "买入":
                held += float(t.get("shares") or 0)
            elif t.get("side") == "卖出":
                held -= float(t.get("shares") or 0)
        return held

    def trades_of(self, code: str | None = None) -> list[dict]:
        out = []
        for i, t in enumerate(self.trades):
            if code and str(t.get("code") or "") != code:
                continue
            sh, nv, fee = float(t.get("shares") or 0), float(t.get("nav") or 0), float(t.get("fee") or 0)
            side = t.get("side")
            amt = sh if side in MONEY_IN + MONEY_OUT else (sh * nv + fee if side == "买入" else sh * nv - fee)
            out.append({"i": i, "date": t.get("date"), "side": side, "code": t.get("code") or "",
                        "name": (FL.fund_name(str(t.get("code"))) or t.get("code") or "") if t.get("code") else "",
                        "shares": sh, "nav": nv, "fee": fee, "amount": amt})
        return sorted(out, key=lambda r: (str(r["date"]), r["i"]), reverse=True)


def asset_meta(asset: str) -> dict:
    return ETF_META.get(asset, {})
