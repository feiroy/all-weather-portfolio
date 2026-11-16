"""「数据变没变」的唯一判断入口。

接口层的缓存（策略权重、账户视图）都靠一个版本号失效。这个版本号以前是各处自己扫文件算的，
于是必然漏：场外净值目录漏了 → 净值补上了、缓存不失效 → 研究页（直读文件）正常、详情页（读缓存）
一条直线（2026-11-16 用户报的「黄金净值没了」）。

现在只在这里定义一次，谁要判断数据新旧都调 `data_ver()` / `data_files()`，**别处不要再写扫描逻辑**。
"""
from __future__ import annotations

import time
from pathlib import Path

from .config import DATA_DIR

# 五组文件，少一组就会出现「文件更新了但页面不动」：
#   行情    data/*.csv                 策略面板、趋势过滤
#   场内净值 data/nav_detail/*.csv      update_nav_detail 写
#   场外净值 fund_lookup.NAV_DIR/*.csv  本机指向 rebal/nav，线上在 data/fund_nav
#   估值    data/valuation/**/*.csv    估值页、溢价判断
#   策略库  data/strategies.json        改了策略就要重算目标权重
GROUPS = ("行情", "场内净值", "场外净值", "估值", "策略库")


def data_files() -> dict[str, list[Path]]:
    """按组列出所有参与版本号的文件（分组只为让自检能说清是哪一组变了）。"""
    out: dict[str, list[Path]] = {"行情": list(DATA_DIR.glob("*.csv"))}
    nd = DATA_DIR / "nav_detail"
    if nd.exists():
        out["场内净值"] = list(nd.glob("*.csv"))
    try:
        import fund_lookup as FL          # 在 streamlit_app 下，调用方负责 sys.path
        if FL.NAV_DIR.exists():
            out["场外净值"] = list(FL.NAV_DIR.glob("*.csv"))
    except Exception:  # noqa: BLE001  没有 fund_lookup（纯回测环境）就跳过这一组
        pass
    val = sorted(DATA_DIR.glob("valuation/**/*.csv"))
    if val:
        out["估值"] = val
    st = DATA_DIR / "strategies.json"
    if st.exists():
        out["策略库"] = [st]
    return out


_VER_TTL = 1.0
_CACHE: dict[str, float] = {"at": 0.0, "ver": 0.0}


def data_ver(fresh: bool = False) -> float:
    """版本号 = 全部数据文件里最新的 mtime。

    每个请求都要问一次，扫描 230 个文件约 2.5ms，所以缓存 1 秒。
    1 秒延迟没有影响（前端「更新数据」本来就每 1.5 秒轮询一次）；要立刻拿最新就传 `fresh=True`。
    """
    now = time.time()
    if not fresh and now - _CACHE["at"] < _VER_TTL:
        return _CACHE["ver"]
    fs = [f for group in data_files().values() for f in group]
    ver = max((f.stat().st_mtime for f in fs), default=0.0)
    _CACHE.update(at=now, ver=ver)
    return ver


def newest(groups: dict[str, list[Path]] | None = None) -> dict[str, tuple[float, str]]:
    """每组里最新的那个文件 → {组: (mtime, 文件名)}，自检用。"""
    groups = groups if groups is not None else data_files()
    out: dict[str, tuple[float, str]] = {}
    for k, files in groups.items():
        best = max(files, key=lambda p: p.stat().st_mtime, default=None)
        if best is not None:
            out[k] = (best.stat().st_mtime, best.name)
    return out
