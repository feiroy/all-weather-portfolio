"""配置常量 - ETF 代码、桶定义、回测期间、调仓规则参数。"""
from datetime import date
from pathlib import Path

# === 路径 ===
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"

# === 回测期间 ===
BACKTEST_START = "2005-04-08"
# 回测 / 抓取 / 页面的截止日：**默认今天**，不再写死某一天
# （写死会出现在「行情已更新到 11 月、页面还停在 10 月」的错觉，2026-11-08 用户踩过）
# 需要复现某次历史回测，调用处显式传 end= 即可。
BACKTEST_END   = date.today().isoformat()

# === 30 年国债合成参数 ===
# 2024-03 之前没有 30Y ETF（511130）：用中债 30 年国债收益率重建恒定期限总回报（data.bond_total_return_from_yield）。
# 旧的「10Y 日收益 × 3 + 利差法」把票息也放大 3 倍，2015-2020 段高估 4.91pp/年，2026-11-08 废弃。
BOND_30Y_TENOR = 30.0

# === 合成数据安全扣减（年化）===
# 仅对合成段（ETF 上市前的替代数据）应用，ETF 真实数据段不扣减
SAFETY_DEDUCT = {
    "nonferr":  0.005,   # 申万有色指数不含管理费、跟踪误差
    "bond_30y": 0.0052,  # 收益率重建 vs 511130 重合期（2024-04~2026-11）年化高 0.52pp = 管理费 + 跟踪误差
}

# === 调仓规则 ===
REBAL_FREQ = "monthly"        # 调仓频率: monthly(月频,默认,回测最优)/biweekly(双周)/weekly(周频)
# 实测：月频 CAGR 最高、MDD 最小；周/双周因逆波动率窗口(20d/60d)本身是月度节奏，
# 高频调仓引入换手噪声，三策略均「月频 > 双周 > 周频」。默认保持月频。
REBAL_MODE = "month_end"     # 调仓日: 月末最后交易日 — 远离商品期货主力换月窗口（月中），
                             # 实证: V3c +0.43pp / RP +0.47pp / Con +0.10pp，三策略受益或中性
RISK_FREE_RATE = 0.017 / 252   # 10年期国债收益率 ~1.7%（日度，2026.07）
RISK_FREE_ANNUAL = 0.017       # 无风险利率年化，用于 Sharpe 修正

# === 现金降杠杆档位 ===
CASH_TIERS = [
    ("100% RP", 0.00),
    ("85% RP",  0.15),
    ("70% RP",  0.30),
]

# === 8 资产元信息 ===
# 顺序就是各个表的标准列序
ASSETS = [
    "hs300", "us_sp500", "credit", "bond_short",
    "bond_10y", "bond_30y",
    "gold", "nonferr", "wti",
]

ETF_META = {
    "hs300":     {"code": "510300", "name": "沪深 300 ETF",        "bucket": "增长↑", "role": "A股大盘"},
    "us_sp500":  {"code": "513500", "name": "标普 500 ETF（QDII）", "bucket": "增长↑", "role": "海外权益"},
    "credit":    {"code": "511220", "name": "城投债 ETF",          "bucket": "收益垫", "role": "信用债"},
    "bond_short": {"code": "511360", "name": "短融 ETF",            "bucket": "收益垫", "role": "短久期利率债"},
    "bond_10y":  {"code": "511260", "name": "10 年国债 ETF",       "bucket": "增长↓10Y", "role": "中久期利率债"},
    "bond_30y":  {"code": "511130", "name": "30 年国债 ETF",       "bucket": "增长↓30Y", "role": "长久期利率债"},
    "gold":      {"code": "518850", "name": "黄金 ETF",            "bucket": "通胀↑", "role": "实物黄金"},
    "nonferr":   {"code": "159980", "name": "有色金属期货 ETF",        "bucket": "通胀↑", "role": "工业金属"},
    "wti":       {"code": "501018", "name": "南方原油 LOF",         "bucket": "通胀↑", "role": "原油LOF"},
}

# === 桶定义（用于风险贡献分析）===
BUCKETS = {
    "增长↑权益(A股)":  ["hs300"],
    "增长↑权益(海外)": ["us_sp500"],
    "信用债":          ["credit", "bond_short"],
    "增长↓10Y":       ["bond_10y"],
    "增长↓30Y":       ["bond_30y"],
    "通胀↑黄金":      ["gold"],
    "通胀↑有色":      ["nonferr"],
    "通胀↑能源":      ["wti"],
}

BUCKET_GROUPS = {
    "增长↑":   ["hs300", "us_sp500"],
    "收益垫":  ["credit", "bond_short"],
    "增长↓10Y": ["bond_10y"],
    "增长↓30Y": ["bond_30y"],
    "通胀↑":   ["gold", "nonferr", "wti"],
}

# === 关键事件压力测试 ===
STRESS_EVENTS = [
    ("2008 GFC",          "2008-09-15", "2009-03-09"),
    ("2015 股灾",         "2015-06-12", "2015-08-26"),
    ("2016 熔断",         "2016-01-04", "2016-01-07"),
    ("2017 债熊",         "2017-01-03", "2017-12-29"),
    ("2018 大熊市",       "2018-01-24", "2018-10-19"),
    ("2019 春季反弹",     "2019-01-04", "2019-04-19"),
    ("2020 疫情",         "2020-02-19", "2020-03-23"),
    ("2020-Q4 内需复苏",  "2020-09-01", "2020-12-31"),
    ("2021-2 白马回撤",   "2021-02-10", "2021-03-31"),
    ("2022 股债双杀",     "2022-01-04", "2022-11-30"),
    ("2022 理财赎回",     "2022-10-30", "2022-12-31"),
    ("2024 雪球危机",     "2024-01-02", "2024-02-29"),
    ("2024-08 长债",      "2024-08-01", "2024-09-30"),
    ("2024-924 反弹",     "2024-09-23", "2024-10-08"),
    ("2025-Q1 长债",      "2025-01-02", "2025-03-31"),
    ("2025-9 关税",       "2025-09-01", "2025-10-31"),
]

CHART_EVENT_NAMES = [
    "2008 GFC", "2015 股灾", "2018 大熊市", "2020 疫情",
    "2022 股债双杀", "2024-924 反弹",
]

# === Block Bootstrap 参数 ===
BOOTSTRAP_N_SIM = 1000
BOOTSTRAP_HORIZON_DAYS = 252 * 5
BOOTSTRAP_BLOCK_DAYS = 21
BOOTSTRAP_SEED = 42

# === V3c 精简资产 ===
V3C_ASSETS = ["hs300", "us_sp500", "credit", "bond_30y", "gold", "nonferr", "wti"]
V3C_ASSETS_NO_WTI = ["hs300", "us_sp500", "credit", "bond_30y", "gold", "nonferr"]
# wti — 南方原油 LOF(501018)，目前申购暂停

# === V3-B 风险平价资产/桶 ===
# 2026-11-08 撤掉短融（c7e0bc6 加入）：短融平均占 18.5%、几乎全从信用债挤出，等于多持一块现金。
# 2015→ 同区间 A/B：年化 -0.42pp（7.91→7.49）、MDD 只浅 0.65pp、夏普 +0.03，过不了 80/20（+0.3pp 或 -1pp），
# 还让风险平价只能从 2015 起回测。要更稳就用现有 85% / 70% 现金档。短融数据 / 基金检索保留，只是不进策略。
V3B_RP_BUCKETS = {
    "增长↑":   ["hs300", "us_sp500"],
    "收益垫":  ["credit"],
    "增长↓":   ["bond_30y"],
    "通胀↑":   ["gold", "nonferr", "wti"],
}
V3B_RP_ASSETS = ["hs300", "us_sp500", "credit", "bond_30y", "gold", "nonferr", "wti"]
# 历史短的资产：不参与面板「共同起点」，起点之前保持 NaN，由用到它的策略自己从它的起点开始。
# （短融已不进任何策略，仍留在面板里给基金检索 / 自定义策略用；以后再加短历史资产也要登记在这里。）
# 2026-10-30 c7e0bc6 给风险平价加短融（中证短融指数 2015-01 起）后，load_panel 取所有资产最晚起点，
# 把保守增强 / V3c（根本不用短融）也截到了 2015，丢掉近 10 年历史、提交说明却写「Con/V3c 不动」。
LATE_START_ASSETS = ("bond_short",)
V3B_RP_BUCKETS_NO_WTI = {
    "增长↑":   ["hs300", "us_sp500"],
    "收益垫":  ["credit"],
    "增长↓":   ["bond_30y"],
    "通胀↑":   ["gold", "nonferr"],
}
V3B_RP_ASSETS_NO_WTI = ["hs300", "us_sp500", "credit", "bond_30y", "gold", "nonferr"]

# === V3-B 保守增强资产/桶 ===
V3B_CON_BUCKETS = {
    "增长↑":   ["hs300", "us_sp500"],
    "收益垫":  ["credit"],
    "增长↓10Y": ["bond_10y"],
    "增长↓30Y": ["bond_30y"],
    "通胀↑":   ["gold", "nonferr", "wti"],
}
V3B_CON_ASSETS = ["hs300", "us_sp500", "credit", "bond_10y", "bond_30y", "gold", "nonferr", "wti"]
V3B_CON_ASSETS_NO_WTI = ["hs300", "us_sp500", "credit", "bond_10y", "bond_30y", "gold", "nonferr"]

# === 方案 B 常量（分层风险平价）===
RISK_PARITY_WINDOW = 20           # V3-B 波动率窗口（交易日）
RISK_PARITY_MAX_WEIGHT = 0.20    # 单资产权重上限（0.20 实现真正等桶风险平价，原 0.18 截断单资产桶）
RISK_PARITY_MIN_WEIGHT = 0.02    # 单资产权重下限
RISK_PARITY_TARGET_VOL = 0.09    # V3-B RP 目标波动率上限（超标等比降敞口）
RISK_PARITY_COV_WINDOW = 60      # V3-B RP 协方差估计窗口（target_vol 用）

# === Gold 抄底参数 ===
GOLD_DIP_THRESHOLD = 0.15        # 黄金从高点回撤超过此阈值触发抄底
GOLD_DIP_BOOST = 2.5             # 触发后黄金权重翻倍倍数（2.5x，网格搜索最优）
# === HS300 抄底参数（策略已不用：pipeline 里 hs300_value_dip=False，留给回测引擎做实验）===
HS300_DIP_THRESHOLD = 0.25       # 价格回撤阈值（25%，中度熊市即触发）
HS300_DIP_BOOST = 1.8            # 价格回撤 boost（1.8x，grid-search 最优）
HS300_DIP_SMA = 120              # 价格回撤需价格 > SMA120 确认（交易日）
HS300_DIP_EXIT_RECOVERY = 0.15   # 恢复到 peak-15% 退出（grid-search 最优）

# HS300 抄底 — AND 逻辑：PB确认入场 + PE确认出场
HS300_PB_ENTRY = 30              # PB%ile 入场阈值（PB便宜才抄底）
HS300_PE_EXIT = 70               # PE%ile 退出阈值（PE不再便宜才退出）

# === 标普500 趋势过滤 ===
SP500_TREND_WINDOW = 75      # 标普500 SMA 回看窗口（交易日），跌破则清仓转入 credit
# 120d→75d: 2020 COVID MDD -9.66%→-6.91%（+2.75pp），牺牲 CAGR -0.16pp
# 75d 提前 1 个月触发（3 月 vs 4 月），正好在 COVID 抛售最急期提供保护

# === 沪深300 趋势过滤 ===
HS300_TREND_WINDOW = 30      # 沪深300 SMA 回看窗口（交易日），跌破则清仓转入 credit
# 选择 30d 基于 HS300 走势分析：2015 股灾 -10% 触发（15d 延迟）、月频调仓下假信号可接受。
# 详细分析见 experiments/_analyze_hs300_sma.py


# === 策略名称 ===
PORTFOLIO_NAMES = {
    "con": "V3-B 保守增强(20d)",
    "rp": "V3-B 风险平价(20d)",
    "v3c": "V3c 多元",
}

# === 策略核心参数（回测/实盘共用，单一事实源）===
# method/window/max_w/min_w 在 pipeline.py 和 rebalance.py 间共享
STRATEGY_PARAMS = {
    "rp": {
        "method": "hierarchical_rp",
        "window": RISK_PARITY_WINDOW,
        "max_w": RISK_PARITY_MAX_WEIGHT,
        "min_w": RISK_PARITY_MIN_WEIGHT,
    },
    "con": {
        "method": "inverse_vol",
        "window": 20,
        "max_w": 0.25,
        "min_w": 0.02,
    },
    "v3c": {
        "method": "inverse_vol",
        "window": 20,    # 60→20: 更快响应波动率下降（Opus 设计，CAGR +0.47pp）
        "max_w": 0.25,   # 0.30→0.25: 压制 credit 集中（max_w 与 window 交互最优，MDD 1:1 对称）
        "min_w": 0.03,
    },
}

# === 策略标签 ===
PORTFOLIO_TAGS = {
    "V3-B 保守增强(20d)":  {"stars": "★★★", "label": "保守增强 — 逆波动率 20d + nonferr(75d)，max_w=0.25"},
    "V3-B 风险平价(20d)":  {"stars": "★★★", "label": "学院派 — 4桶等权 HRP + nonferr(75d) + Gold(75d) + SP500(75d) + HS300(30d)"},
    "V3c 多元":            {"stars": "★★★", "label": "V3c 多元 — 6资产逆波动率20d + nonferr(75d) + gold(75d) + SP500(75d)"},
}

