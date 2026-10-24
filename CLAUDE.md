# CLAUDE.md
This file provides guidance to Claude Code when working with code in this repository.
## 策略优化闭环
所有策略改动遵循此流程，不跳步：
```
问题定义 → 假设 → 设计 → 验证 → 稳健性检验 → 决策 → 实施
   ↑                                                            │
   └────────────────────────────────────────────────────────────┘
```
1. **问题定义** — 可量化的缺陷（具体时间、幅度、原因）
2. **假设** — 因果陈述，可证伪，有经济学逻辑
3. **设计** — 参数选择 + 逻辑边界 + 交互效应；网格搜索，整数窗口
4. **验证** — 单变量对比，检查 CAGR/波动/MDD/Sharpe/Calmar/最差年份/事件期/宏观情景
5. **稳健性检验** — 参数敏感度(±50%) + D_excess + 80/20 检验 + 过拟合风险
6. **决策** — 二选一，通过→实施，否决→写 memory 记录原因
7. **实施** — 按 checklist 执行
## 前置原则
### 第 0 层：哲学基座
方法论的底层。所有 Sperandeo 原则之所以成立，是因为它们符合以下更根本的认知规律：
**实事求是。** 每个参数回答"为什么在中国数据上成立"。桥水原版是起点不是终点。30Y 三阶段合成、HS300 AND 抄底、nonferr 75d — 全是实事求是的结果。
**矛盾论。** 80/20 是主要矛盾的量化。桶结构是主要方面，内部加权是次要方面。牛市收益是主要矛盾，熊市回撤是主要矛盾。不同质的矛盾用不同方法解决。
**实践论。** 7 步闭环 = 认识→实践→再认识。memory 是实践记录，否决≠删除。具体分析见 `docs/framework/马克思主义.md`。
### Sperandeo 三层结构
按优先级排序，不可颠倒：
**第一层：保障资本。** D_excess 尾部风险诊断（每次验证必须跑，D<<0 直接否决）| 墨菲定律（每个信号有 fallback）| 止损纪律（不扛下跌趋势）
**第二层：一致性的获利能力。** 奥卡姆剃刀（从最简开始）| 80/20 检验（CAGR+0.3pp 或 MDD-1pp 以上才值得）| 休谟因果（必须有经济学逻辑）| 最小描述长度（参数响应面平的→砍掉）
**第三层：追求卓越的报酬。** HS300 AND 抄底（只在极端便宜时加仓 1.8x）| 方案 C 教训（不可摊平亏损）
## 实施 Checklist
| # | 步骤 | 内容 |
|---|------|------|
| 1 | 改代码 | `config.py`(常量) → `pipeline.py`(调用) → `strategy_b.py`/`backtest.py`(引擎) |
| 2 | 全量回测 | `py main.py`，确认无报错并记录指标 |
| 3 | 更新文档 | `py main.py` 自动同步 `README.md`（编辑文字改 `README.template.md`）、`docs/index.html`、`docs/charts/` |
| 4 | 更新 Memory | 有新结论或推翻旧结论时才写 |
| 5 | 提交 | `git add -A && git commit -m "..." && git push` |
## 行为原则
| # | 原文 | 含义 |
|---|------|------|
| 1 | **Think Before Coding** | 先分析再动手，不沉默假设 |
| 2 | **Simplicity First** | 最短代码，不为未来造抽象 |
| 3 | **Surgical Changes** | 只改必须改的，不重构没坏的东西 |
| 4 | **Goal-Driven Execution** | 定义验收标准，循环直到通过 |
| 5 | **Don't route decisions through the model** | 确定性逻辑写代码，不消耗 token |
| 6 | **Hard token budgets** | 每任务设上限，到了就停 |
| 7 | **Surface conflicts, don't average** | 有分歧选一个，不取平均 |
| 8 | **Read before you write** | 先读相邻文件，理解既有模式 |
| 9 | **Tests are not optional, but they're not the goal** | 写有意义测试，假通过不如没有 |
| 10 | **Long-running operations need checkpoints** | 每步检查点，一步错不丢全部进度 |
| 11 | **Convention beats novelty** | 匹配既有模式，两个模式比一个坏模式更糟 |
| 12 | **Fail visibly, not silently** | 出问题大声说，沉默隐藏 bug |
## 界面与文案规范（硬性 rule，每次开发前必须先读本节）
> 写任何页面/图表/表格前先读完本节；写完按末尾「自检清单」逐项过。不允许自创风格。

### 日期
- **具体某一天只准 `2026/09/24`（`%Y/%m/%d`）**：不许英文月份（Oct 24, 2026）、不许 `2026-09-24`、不许 `2026年9月24日`。
- **表示"某个月 / 某一年"这个期间时用中文**：月 = `2026年10月`（不补零，`f"{y}年{m}月"`），年 = `2026年`。用于月份/年份选择器、月线/年线横轴标签、日历格子标题。**不许 `2026/10`、`2026-10`**。统一用 `app.py::_period_label(t, period)`。
- 区间写法：`2026/09/24 — 2026/10/22`。
- Altair/Vega（默认英文，必须显式覆盖）：轴 `format="%Y/%m/%d"` 或按上条写期间，tooltip `format="%Y/%m/%d"`；任何 `:T` 编码必须带 format。
- `st.dataframe` 不放 Timestamp 列（随浏览器 locale 变英文），先转字符串。matplotlib 用 `mdates.DateFormatter`，不依赖 locale。
- 仅文件名/日志时间戳可用 `%Y%m%d`，页面展示不行。

### 设计 token（一律用 app.py `:root` 里的 CSS 变量，禁止硬编码色值）
| 用途 | 变量 | 值 |
|------|------|-----|
| 主文字 / 次级 / 弱化 | `--ink` / `--sub` / `--muted` | #0F172A / #475569 / #94A3B8 |
| 描边 / 更浅描边 / 输入控件描边 | `--line` / `--line-soft` / `--line-strong` | #E2E8F0 / #EEF2F7 / #CBD5E1 |
| 卡片面 / 页面背景 | `--card` / `--bg` | #FFFFFF / #F8FAFC |
| 主色 / 焦点 | `--brand` / `--focus` | #1E40AF / #3B82F6 |
| **涨（红）/ 跌（绿）** | `--red` / `--green` | #C52828 / #16703B（A 股习惯，禁止反用） |
| 警示 | `--amber` | #B45309 |
| 圆角 / 阴影 | `--radius`(14px) / `--shadow` | 页面卡片 16px，控件 12px，格子 10px |
> iframe 组件（`st.iframe`）内拿不到父页面 CSS 变量，只能写同值十六进制；这些值只允许出现在 `_COMP_BASE_CSS` / `_CAL_CSS` / `_CMP_CSS` 里，且必须与上表一致。

### 页面结构（基金走势页是唯一样板，新页面照抄，不另起炉灶）
- **卡片容器**：每个区块包在 `st.container(key=...)` 里，key 加进 `.st-key-trend_head, .st-key-trend_chart, ...` 这组共享 CSS（白底、1px `--line` 边、16px 圆角、24px 内边距）。不用 `st.subheader` / `st.divider` 拼版面。
- **区块标题**：页面级用 `.sec-head`（`.t` 标题 + `.r` 右侧说明）；iframe 组件内用 `.heading h3` + 图标。
- **底部说明**：数据来源/口径一律 `.sec-note`（12px、`--sub`），放在卡片最后。
- **页面宽度**：内容区 `max-width:1480px`，左右内边距 `clamp(1rem,3vw,3rem)`；页头右侧操作区用 `st.container(key="hero_actions", horizontal=True, horizontal_alignment="right")`，状态胶囊与按钮同一行、同高 40px。
- **头部**：左侧 `.fund-head`（名称 + 代码 + 标签 + 最新值 + 单日涨跌 + 截至日期），下方 `.stage-summary` 阶段表现；右侧放选择器。

### 交互图表（统一组件体系，禁止用 Altair/st.dataframe 替代）
- 时间序列图一律用 `app.py` 里的 iframe 组件，共用 `_COMP_BASE_CSS`：
  - 单基金：`_scroll_chart_html`（拖动/滚轮平移、Ctrl+滚轮缩放、双击复位、区间 tab + 日线/月线/年线、悬停提示、区间统计）。区间选项只在 `_TREND_RANGES` 定义一次（近1月/近3月/近6月/近1年/近3年/近5年/今年来/全部），按钮由 `_range_buttons()` 生成，单基金和多基金组件共用，禁止在模板里手写按钮。
  - 多基金：`_compare_chart_html`（同上交互，多条线同图，图例可点隐藏，下方表格随可见区间实时重算区间涨跌/年化/最大回撤/波动）。**不要为每只基金再单独画一张图。**
  - 收益日历：`_calendar_html`（日/周/月/年 格子 + ‹ 选择器 › 翻页）。
  - 指数估值：`_valuation_html`（市场 tab + 搜索 + 估值档筛选、表头排序、点行看近10年 PE/PB 走势与 30/50/70% 分位线）。默认按评分降序，未点选时详情跟随列表第一行（不写死某个指数）。评分/回撤口径见 `allweather/valuation.py::score / drawdown_10y`（沿用 etf-dashboard-auto）。
  - iframe 内的 `@media` 断点按 **iframe 自身宽度**（≈ 页面内容区宽 − 卡片内边距）计算，不是浏览器窗口宽度；多列表格用像素列宽 + 逐级隐藏次要列，验收时至少截 1440 / 1180 / 900 三档。
  - 多基金对比与单基金同为三层面板：净值 / 相对起点涨跌幅 / 单期涨跌幅。基金净值统一用 `fund_lookup.build_nav`（最新值 = 单位净值；复权收益见 `adjusted_returns`：平常日子用单位净值之比，分红/拆分日用 chg；不要直接累乘 chg，2 位小数长期累乘有舍入误差）。
  - **区间涨跌口径 = 支付宝「历史业绩」**（`_trend_window_start`）：近N月/年基准 = N 个自然月/年前那天的净值（休市取之前最近一个交易日）；今年来基准 = 去年最后一个交易日。2026/10/24 用 161119 对账，近1月/3月/6月/1年/3年全部一致。
  - **净值缓存要检查新鲜度**：选中基金时用 `FL.is_stale` 判断（落后于应公布净值日且超过 1 小时未拉）就重拉；拉取失败有旧缓存则继续显示旧数据。
- 控件样式：区间/粒度用下划线 tab 按钮（`button[data-range]`，选中红字红下划线）；期间/周期用 `select`（12px 圆角、42px 高），和 tab 同一行右对齐。**不要用 st.radio 横排 + 整行宽 selectbox 的组合。**
- `select` 一律去掉系统原生箭头（`appearance:none`），用 `_COMP_BASE_CSS` 里的细线 chevron（`--muted` 色）；翻页按钮用同款 SVG chevron，不用 ‹ › 字符。
- 期间切换、拖动、隐藏图例等纯展示交互放在组件内 JS 完成，不触发 Streamlit 整页重跑。
- **iframe 高度**：内容高度会变的组件一律 `st.iframe(html, height="content")`，由 Streamlit 自动测量；组件 JS 里**禁止**改 `window.frameElement` 的尺寸（只撑大 iframe、外层容器不变，会盖住下方说明文字）。
- **st.markdown 里的多行 HTML**：插值可能为空字符串时（如估值标签），会留下空行，紧跟的 4 格以上缩进被 Markdown 当成代码块，页面直接显示源码。多行 HTML 一律先压成一行再渲染（`.replace("\n", "")`），或在 iframe 组件里渲染。
- **表格列对齐**：`table-layout:fixed` + `<colgroup>` 定列宽；文本列左对齐、数值列右对齐，表头与单元格用同一个对齐 class；排序箭头绝对定位不占宽度（右对齐列放文字左侧）；图表标签放绘图区外并做防重叠。
- 多基金配色用 `_CMP_COLORS`（已避开红/绿——红绿只表示涨跌）。

### 组件细则
- **涨跌着色**：涨=`--red`，跌=`--green`，0/无数据=`--sub`/`--muted`；格子底色可按涨跌幅深浅做热力（同色系透明度）。class 用 `.up`/`.down`/`.neutral`。
- **数字**：涨跌幅一律带符号两位小数 `+1.23%`；数值列右对齐、`tabular-nums`；无数据显示 `—`。
- **表格**：iframe 内用 `.cmp-tbl` 风格（表头 12px `--sub`、行分隔 `--line-soft`、首列左对齐其余右对齐）；页面级用 `.tbl`。不用 st.dataframe 展示涨跌色。
- **输入控件外观**：所有 selectbox / multiselect / number_input / date_input 用 `--line-strong` 边框、白底、12px 圆角、44px 高，悬停加深、聚焦蓝色描边（app.py「控件」CSS 块统一定义）。主题 secondaryBackgroundColor 是白色，不覆盖的话控件在白卡片里看不见边框。Streamlit ≥1.6x 的下拉控件是 react-aria（`.react-aria-ComboBox > div`），不是 baseweb，新增控件类型要先在真实页面查 DOM。多选已选标签用 `--brand-soft` 中性色，**不用主题红**（红色只表示上涨）。同一行多个输入用 `vertical_alignment="bottom"`，标签单行，长说明放 help。
- **选择器**：优先 selectbox/multiselect（输入即提示）；空态用 placeholder（如「至少选择 1 个基金」），不塞默认值；不要重复放两个功能相同的搜索框。
  选项上千条时 selectbox/multiselect 必须 `filter_mode="contains"`，multiselect 再加 `select_all=False`。
- **基金搜索一律用 `fund_search.fund_search()`**（单选/多选两种 mode），**不要把 2.8 万只基金名录塞进 st.selectbox/multiselect**：每个控件会把 1.1MB 选项序列化进页面，切到基金走势/基金对比 tab 时主线程卡 2 秒、点不动。名录由 `ensure_static_names()` 写成 `streamlit_app/static/fund_names.json`（`server.enableStaticServing`），前端首次聚焦才下载、全页共享一份。
- **耗时操作不阻塞页面**：自动拉取放后台线程（`_start_background_fetch`）；按钮触发的更新用 `st.toast` 提示进度，**不用 st.spinner/st.info 在页面里插一行**（会把下方内容顶下去再弹回，页面抖动）。
- **按钮文案写动作不写状态**：如「更新数据」，状态（是否最新、滞后几天）放 help/图标/颜色里。
- **净值口径（展示）**：页面上的净值和日涨幅一律用「单位净值 + 官方日涨幅」（`data/nav_detail/`，`_asset_display_series` / `fund_lookup.build_nav`），与支付宝一致；**不要用累计净值算涨跌幅**（累计净值 = 单位净值 + 历年分红，涨跌会被分红稀释，510300 在 2026/10/22 为 −1.51% vs 官方 −1.82%）。「场内价格」= 交易所收盘价，不叫「收盘价」或「净值」。策略回测目前仍读 `data/{name}.csv` 的累计净值，改口径须走策略优化闭环。
- **估值数据口径**：策略信号只用 `data/hs300_pe.csv`/`hs300_pb.csv`（乐咕乐股，全历史）；蛋卷估值（近10年加权）只用于估值页和估值标签，不进策略。两者由「更新数据」按钮一起更新（`allweather/valuation.py::update_all`）。

### 自检清单（每次写完新页面/新区块必须逐项过，过不了不交付）
1. 日期：具体日 `2026/09/24`、期间 `2026年10月`/`2026年`，`grep -n ':T\|%Y-%m\|%Y/%m"' streamlit_app/*.py` 无展示层违规。
2. 结构：区块是否在共享卡片容器里，是否用了 `.sec-head` / `.sec-note`，与基金走势页并排看是否一致；**用无头 Chrome 打开真实页面截图检查重叠和对齐**（AppTest 与 jsdom 都看不出布局问题）。
3. 图表：时间序列是否用了 iframe 组件体系，控件是否 tab + select 同行。
4. 颜色：涨红跌绿方向正确，无新增硬编码色（iframe 组件 CSS 常量除外）。
5. 空态与默认值：placeholder 文案、无数据提示是否齐全；有无重复控件。

- 适用范围：`streamlit_app/`、`rebal/*.py` 生成的 HTML 报告、`docs/`、Excel/Markdown 报告。

## 线上部署（手机访问）
- 打包：`./myenv/bin/python scripts/build_web.py` → `deploy_web/`（只含代码、streamlit_app/static/fund_names.json、data/、output/nv_curves.csv、自选基金净值缓存 data/fund_nav/，约 19MB；不含 myenv）。`--password` 生成新访问密码（明文只存本机 `.workbuddy/web_password.txt`，线上只放哈希）。
- 发布：用 WorkBuddy「发布应用」，目录固定为 `deploy_web/`（目录决定线上应用，不要换目录），启动 `sh start.sh`（Streamlit 监听 $PORT、绑定 0.0.0.0）。每次发布前必须重新打包，且要用户明确说"发布/同步到线上"。
- 访问密码：`_password_gate()` 只在有密码哈希时启用，本机运行不受影响；登录后网址带 `?k=` 令牌，手机收藏该网址免输密码，换密码后令牌失效。
- 线上数据：发布时带上本机快照；线上「更新数据」写在云端沙箱，重新发布会被本机快照覆盖；线上录入的模拟账户成交不回传本机。
- **访问范围**：当前账号发布出来的域名是 `*.app-tencent.workbuddy.host`，公网 DNS 解析到 21.x 内网地址，**只有公司内网（办公网/iOA）能打开，手机走 5G 或家里 Wi-Fi 会连接超时**。

## Git 规则
- 单人项目，直接推 main。`git add -A && git commit -m "..." && git push`
- Commit message 禁止 Co-Authored-By 署名
- 大改动可开 feature 分支，最终合 main
## 模型选择
### 分工原则
| 改动类型 | 执行 | 审查 | 说明 |
|---------|:----:|:----:|------|
| **简单任务** | Flash 直接 | 不审查 | 改常量、更新文档、常规 commit |
| **常规改动** | Flash Agent | Flash Agent | 策略参数调整、回测逻辑小改 — 一个改一个审，交叉检查 |
| **重要改动** | Flash Agent | Opus Agent | 新机制实现、参数网格搜索、多变量对比 — Opus 给高层指导，Flash 执行，Opus 审结果 |
| **核心决策** | Opus Agent 直接 | — | 问题定义→假设→设计阶段、统计诊断、D_excess、过拟合检验 |
### 常规改动审查流程
1. Agent A（Flash）：执行改动
2. Agent B（Flash）：独立审查，检查逻辑正确性、边界条件、是否符合 CLAUDE.md 规则
3. 审查发现问题则回到步骤 1，通过则继续
### 重要改动审查流程
1. Opus Agent：分析问题、给出设计方案、参数范围建议
2. Flash Agent：按 Opus 方案实现代码
3. Opus Agent：审查实现、检查指标、验证稳健性
4. 通过后进入实施 Checklist
## 命令
```bash
py main.py                         # 全量回测（自动增量更新数据 + 报告）
# flags: --force-fetch  --no-excel  --no-markdown
python -m allweather.rebalance     # 实盘再平衡
```
CI：`.github/workflows/backtest.yml` 跑 `py main.py`，检查 Sharpe/MDD 边界。
## 策略目标框架
所有改动必须满足各策略的目标约束，按通用红线 → 策略专属约束的优先级逐层检查。
| 指标 | V3-B 保守增强 | V3c 多元 | V3-B 风险平价 |
|------|:-------------:|:--------:|:-------------:|
| **定位** | 保守防御 | 中位中枢 | 进取高回报 |
| **CAGR 目标** | ≥ 7% | ≥ 8.5% | ≥ 8.5% |
| **MDD 上限** | ≤ -7% | ≤ -8.5% | ≤ -9% |
| **波动率上限** | ≤ 5% | ≤ 6% | ≤ 7% |
| **核心约束** | Sharpe ≥ 1.2 | 回撤优先 | CAGR 优先 |
| | | | |
| **通用红线** | | | |
| 换手率（年化） | ≤ 2x | ≤ 2x | ≤ 2x |
| 最差单年 | ≥ -8% | ≥ -8% | ≥ -10% |
| 正收益年比例 | ≥ 70% | ≥ 70% | ≥ 70% |
| Bootstrap 5年亏损概率 | < 5% | < 5% | < 8% |
| D_excess | ≥ -0.5 | ≥ -0.5 | ≥ -0.5 |
> Sharpe 为修正版 `(CAGR - 1.7%) / vol`（代码中 `sharpe` 字段，无风险利率见 `RISK_FREE_ANNUAL`）。MDD 为全样本最大回撤。CAGR 为几何年化收益率。
## 策略速查
| 策略 | 一句话 |
|------|--------|
| V3-B 保守增强(20d) | 逆波动率20d + nonferr75d趋势 + HS300 AND抄底 — Sharpe 1.77 |
| V3c 多元 | 6资产逆波动率20d + nonferr/gold/sp500趋势75d + HS300 AND抄底 — MDD -6.30% |
| V3-B 风险平价(20d) | 4桶HRP + 四重趋势 + 抄底 + target_vol=9% — CAGR 9.20% |
增长↑(hs300,sp500) | 收益垫(credit) | 增长↓10Y(bond_10y) | 增长↓30Y(bond_30y) | 通胀↑(gold,nonferr)
## 策略参考

| 策略 | 引擎 | 核心逻辑 | 资产 | 特点 |
|------|------|----------|------|------|
| V3-B 保守增强(20d) | `strategy_b.py::backtest_b` | 逆波动率 20d (max 0.25) + nonferr 75d + HS300 AND抄底 | 7 (含 bond_10y) | Sharpe 最高 |
| V3-B 风险平价(20d) | `strategy_b.py::backtest_b` | 4 桶等权 HRP + nonferr 75d + gold 75d + sp500 75d + hs300 30d + HS300 AND抄底 | 6 (无 bond_10y) | CAGR 最高 |
| V3c 多元 | `backtest.py::backtest_iv` | 逆波动率 20d + nonferr 75d + gold 75d + sp500 75d + HS300 AND抄底 | 6 (无 bond_10y) | 最均衡 |

× 3-4 现金档：100% RP / 85% RP / 70% RP / 动态（仅 V3-B 系列）。

### 资产与桶

| 桶 | 资产 | V3-B Con | V3-B RP | V3c |
|----|------|:--------:|:-------:|:---:|
| 增长↑ | hs300, us_sp500 | ✓ | ✓ | ✓ |
| 收益垫 | credit | ✓ | ✓ | ✓ |
| 增长↓10Y | bond_10y | ✓ | — | — |
| 增长↓30Y | bond_30y | ✓ | ✓ | ✓ |
| 通胀↑ | gold, nonferr | ✓ | ✓ | ✓ |

V3-B RP 和 V3c 去掉了 bond_10y（CAGR +1.43pp，Sharpe 仅 -0.02）。

### 关键常量

| 常量 | 值 | 说明 |
|------|-----|------|
| `BACKTEST_START/END` | 2005-04-08 / 2026-05-30 | ~21 年 |
| `RISK_FREE_ANNUAL` | 0.017 | 无风险利率（10Y 国债 2026.07 实际值） |
| `GOLD_DIP_THRESHOLD` | 0.15 | 黄金抄底触发 |
| `GOLD_DIP_BOOST` | 2.5 | 黄金抄底倍数 |
| `HS300_DIP_THRESHOLD` | 0.25 | HS300 抄底触发 |
| `HS300_DIP_BOOST` | 1.8 | HS300 抄底倍数 |
| `HS300_PB_ENTRY` / `HS300_PE_EXIT` | 30 / 70 | AND 入场PB / 出场PE 分位 |
| `RISK_PARITY_TARGET_VOL` | 0.09 | 风险平价目标波动率 |
| `BOOTSTRAP_N_SIM` | 1000 | 蒙特卡洛次数 |
| `REBAL_MODE` | month_end | 调仓日：月末最后交易日（远离期货换月窗口，三策略受益） |

> 代码中的权威定义在 `config.py`。

## 架构参考

```
main.py → pipeline.run_full_pipeline()
allweather/
  config.py         所有常量
  types.py          PerfMetrics/Step3Metrics 等共享类型
  experiment_log.py 实验日志（experiments.jsonl）
  data.py           加载 + 合成 30Y 国债
  fetch.py          akshare 数据拉取
  backtest.py       统一回测引擎
  strategy_b.py     backtest_b 向后兼容包装
  risk.py           逆波动率 / 分层风险平价 / 趋势过滤
  stats.py          指标 / Bootstrap / D_excess
  reports.py        控制台输出
  charts.py         8 张 matplotlib 图表
  excel_export.py   Excel 报告
  markdown_report.py Markdown 报告
  update_docs.py    README/CLAUDE.md/docs 同步
  rebalance.py      实盘再平衡（streamlit_app 调用）
  pipeline.py       6 步编排
streamlit_app/     Web 再平衡面板（app.py 主程序 + run.py 启动器）
joinquant/         聚宽平台量化测试代码（独立于核心流水线）
portfolio_comparison/  多策略对比工具
```

**模块依赖分层：**
- **第 0 层**: config.py, risk.py, experiment_log.py
- **第 1 层**: types.py, data.py, fetch.py, stats.py, charts.py, reports.py, excel_export.py, markdown_report.py, update_docs.py
- **第 2 层**: backtest.py, rebalance.py
- **第 3 层**: strategy_b.py
- **第 4 层(编排)**: pipeline.py
- **入口**: main.py（延迟导入）

## 外部参考
- [项目.md](项目.md) — 完整分析文档（架构深层解析、设计决策）
- Memory — `.claude/projects/C--Users-MOSS-Desktop------/memory/`
