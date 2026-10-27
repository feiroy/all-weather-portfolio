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

### 页面结构（基金检索页是唯一样板，新页面照抄，不另起炉灶）
- **卡片容器**：每个区块包在 `st.container(key=...)` 里，key 加进 `.st-key-trend_head, .st-key-trend_chart, ...` 这组共享 CSS（白底、1px `--line` 边、16px 圆角、24px 内边距）。不用 `st.subheader` / `st.divider` 拼版面。
- **区块标题**：页面级用 `.sec-head`（`.t` 标题 + `.r` 右侧说明）；iframe 组件内用 `.heading h3` + 图标。
- **底部说明**：数据来源/口径一律 `.sec-note`（12px、`--sub`），放在卡片最后。
- **页面宽度**：内容区 `max-width:1480px`，左右内边距 `clamp(1rem,3vw,3rem)`；页头右侧操作区用 `st.container(key="hero_actions", horizontal=True, horizontal_alignment="right")`，状态胶囊与按钮同一行、同高 40px。
- **头部**：左侧 `.fund-head`（名称 + 代码 + 标签 + 最新值 + 单日涨跌 + 截至日期），下方 `.stage-summary` 阶段表现；右侧放选择器。
- **一个 tab 内的视图切换**用 `st.segmented_control`，外层必须包 `st.container(key=...)` 才能挂样式：`.st-key-trend_mode_switch [role="radiogroup"]`（tab 按钮组：3px 内衬、12px 圆角、34px 高、选中白底 + `--brand` 字）。**不要为了两种视图再开一个 tab**——单只走势和多只对比已合并进「基金检索」（见下）。
- **不许让重跑把页面「跳一下」**：每次交互 Streamlit 整页重跑，任何「要等数据回来才知道写什么」的头部/统计条，必须先用 `st.session_state` 里已有的值渲染出等高内容，**禁止 `st.empty()` 占位、等算完再回填**——占位先是 0 高、回填后撑开，用户看到的就是上下抖一下（实测 28.8px）。耗时提示用 `st.toast`，不用 `st.spinner`（spinner 会在版面里插一行，同样跳）。
- **条件渲染（if / else 分支）里的控件会丢 state**：Streamlit 只保留「本轮渲染过」的 widget state，切到另一个分支后原控件这一轮不渲染，切回来就退回默认值。搜索框一律用 `_sticky_search(key, ...)`（在 Python 侧另存 `_sel_<key>` 镜像当兜底），`口径` 这类按钮把选中值存 `_sel_*` 再回填 `index`。**默认值会随数据变化的控件（如持仓配置）不能用镜像**，否则镜像会盖住真实值。头卡这类「先渲染、后拿值」的地方要 **实时值优先、丢了才用镜像**，且不能用 `or` 判断（清空后的 `[]` 是有效值）。
- **iframe 内的控件选择靠 localStorage 记住**：`_scroll_chart_html` / `_compare_chart_html` 把区间与周期存 `awTrend.single` / `awTrend.multi`（srcdoc 与父页同源，可用；访问要包 try/catch）。切视图、换基金、加删线都会重建 iframe，靠它还原。

### 交互图表（统一组件体系，禁止用 Altair/st.dataframe 替代）
- 时间序列图一律用 `app.py` 里的 iframe 组件，共用 `_COMP_BASE_CSS`：
  - 单基金：`_scroll_chart_html`（拖动/滚轮平移、Ctrl+滚轮缩放、双击复位、区间 tab + 日线/月线/年线、悬停提示、区间统计）。区间选项只在 `_TREND_RANGES` 定义一次（近1月/近3月/近6月/近1年/近3年/近5年/今年来/全部），按钮由 `_range_buttons()` 生成，单基金和多基金组件共用，禁止在模板里手写按钮。另有四个可选参数：`trades`（历史买卖点：按日期落到当前粒度那一期，红上三角买入 / 绿下三角卖出，悬停提示里列出该笔份额与净值）、`store`（localStorage 键，持仓页详情图用 `awTrend.fund`）、`default_range`、`heading`。不传 `trades` 时行为与以前完全一致（tab7 基金检索就是这样用的）。
  - 多基金：`_compare_chart_html`（同上交互，多条线同图，图例可点隐藏，下方表格随可见区间实时重算区间涨跌/年化/最大回撤/波动）。**不要为每只基金再单独画一张图。** 入口在「基金检索」tab 的「多只对比」视图（`trend_mode_switch`），不再单独占一个 tab；下方「阶段表现」表对每只基金复刻单只的 6 个阶段数字（`_stage_rows`）。
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
- **表格**：iframe 内用 `.cmp-tbl` 风格（表头 12px `--sub`、行分隔 `--line-soft`、首列左对齐其余右对齐）；页面级用 `.tbl`（`_render_table`）。不用 st.dataframe 展示涨跌色。列多（≥6 列）的表必须传 `_render_table(..., min_width=700)`：窄屏改为卡片内横向滑动，**不要**让单元格压缩到一字一行。
- **输入控件外观**：所有 selectbox / multiselect / number_input / date_input 用 `--line-strong` 边框、白底、12px 圆角、44px 高，悬停加深、聚焦蓝色描边（app.py「控件」CSS 块统一定义）。主题 secondaryBackgroundColor 是白色，不覆盖的话控件在白卡片里看不见边框。Streamlit ≥1.6x 的下拉控件是 react-aria（`.react-aria-ComboBox > div`），不是 baseweb，新增控件类型要先在真实页面查 DOM。多选已选标签用 `--brand-soft` 中性色，**不用主题红**（红色只表示上涨）。同一行多个输入用 `vertical_alignment="bottom"`，标签单行，长说明放 help。
- **选择器**：优先 selectbox/multiselect（输入即提示）；空态用 placeholder（如「至少选择 1 个基金」），不塞默认值；不要重复放两个功能相同的搜索框。
  选项上千条时 selectbox/multiselect 必须 `filter_mode="contains"`，multiselect 再加 `select_all=False`。
- **基金搜索一律用 `fund_search.fund_search()`**（单选/多选两种 mode），**不要把 2.8 万只基金名录塞进 st.selectbox/multiselect**：每个控件会把 1.1MB 选项序列化进页面，切到基金检索 tab 时主线程卡 2 秒、点不动。名录由 `ensure_static_names()` 写成 `streamlit_app/static/fund_names.json`（`server.enableStaticServing`），前端首次聚焦才下载、全页共享一份。
- **耗时操作不阻塞页面**：自动拉取放后台线程（`_start_background_fetch`）；按钮触发的更新用 `st.toast` 提示进度，**不用 st.spinner/st.info 在页面里插一行**（会把下方内容顶下去再弹回，页面抖动）。
- **按钮文案写动作不写状态**：如「更新数据」，状态（是否最新、滞后几天）放 help/图标/颜色里。
- **净值口径（展示）**：页面上的净值和日涨幅一律用「单位净值 + 官方日涨幅」（`data/nav_detail/`，`_asset_display_series` / `fund_lookup.build_nav`），与支付宝一致；**不要用累计净值算涨跌幅**（累计净值 = 单位净值 + 历年分红，涨跌会被分红稀释，510300 在 2026/10/22 为 −1.51% vs 官方 −1.82%）。「场内价格」= 交易所收盘价，不叫「收盘价」或「净值」。策略回测目前仍读 `data/{name}.csv` 的累计净值，改口径须走策略优化闭环。
- **估值数据口径**：策略信号只用 `data/hs300_pe.csv`/`hs300_pb.csv`（乐咕乐股，全历史）；蛋卷估值（近10年加权）只用于估值页和估值标签，不进策略。两者由「更新数据」按钮一起更新（`allweather/valuation.py::update_all`）。
- **持仓口径（「我的持仓」之后）**：策略算的是 8 个**位置**的权重；每个位置挂哪些基金由 `data/holdings.json` 决定（`allweather/holdings.py`，默认 = 项目原来的 8 个场内代码）。建仓/调仓/记账/提醒一律按**我持仓的那些基金**算；策略目标权重、回测理论净值仍用项目默认代码，**不要混用**。
  - **一个位置可以挂多只，也可以一只都不挂**：`holdings[slot] = {"on": bool, "funds": [{code,name,unit,lot,min_amount,share}]}`，`share` 是该位置内的资金占比（全 0 或留空 → 等权，`HG.share_of` 归一化）。`funds` 为空 = 这个位置不持有，它的权重按同桶比例让给别的位置（`HG.slot_weights`）。**不要再假设"一个位置一只基金"**：取值一律走 `HG.funds/codes/share_of/all_codes/fund_meta`。
  - `HG.nav_panel()` 的列是**基金代码**（不是位置 key）；`_hg_mv` 仍按位置聚合（策略口径），一只位置多只时按各自净值分别估值再相加。
  - 建仓/调仓清单**一只基金一行**（同位置第二行起位置列显示 `↳`，位置级的当前权重/目标权重/偏离只在首行），位置该不该动按位置整体偏离判断，要动才按 `share` 拆到各基金。
  - 老的 `{"code": ...}` 单只结构在 `HG.load()/save()` 里自动迁移成 `funds` 单元素，别写第二套读取逻辑。
  - 市值/涨跌用复权单位净值：8 个默认代码读 `data/nav_detail/`，其他基金读 `fund_lookup` 缓存（`HG.nav_series`）。
  - 场内按股（100 股一手）、场外按份额（金额申购，`min_amount`）；`HG.order_quantity` 统一处理，**入参是"某只基金"的配置 dict，不是位置 dict**。
  - 持仓换过基金后，账上旧代码的份额要按**旧代码自己的净值**估值（`_nav_of_code`），不能拿新基金净值去乘；浮亏判断同理（`AL.compute(nav_by_code=...)`），不能用「位置市值 ÷ 该只份额」。
  - 两条基准不要混：`BM.strategy_curve`（回测长历史）vs `BM.replay_target`（同起点、同权重、用默认基金重放）。
- **「项目原来的操作 / 月年收益」在「回测表现」页**：上半部分是三策略对比与调频影响（多年/年度/月度），
  最下方「历史调仓」用 `output/weight_history_{策略}.csv` 给出每月目标权重、当月/当年收益
  （`output/nv_curves.csv`）和当月触发的信号（`output/signal_log.csv`）。
  我自己持仓的收益在「我的持仓」，不要和这里的回测混着看。
- **记账是份额制**：成交记录的是「多少份 × 每份净值」，键是**基金代码**不是策略资产 key（`_replay_holdings`）；老格式（asset/price）会自动迁移一次。转入/转出按上一交易日净值折算份额，所以外部资金进出不会虚增收益。

### 账户相关的四个页面（职责严格分开，禁止互相塞内容）
- **「我的持仓」= 我有什么 + 跑得怎么样（点开看单只）**
  - 顶部**唯一一张深蓝头卡**（`.pf-head`）：总金额大字 + 今日收益 / 持有收益 / 持有收益率 / 现金。今日收益 = Σ 份额 ×（当日净值 − 上一日净值）；持有收益 = 总资产 − 起始资金（`capital`）。
  - 中间是**一只基金一行的列表**（components v2 组件 `aw_pf_list` / `_pf_list`，`max-height:462px` 内部滚动 + 表头吸顶 + 点一行回传代码 + 选中行左侧蓝条）：基金名 + 代码·场外/场内·位置 → 金额 / 今日收益 / 持有收益 / 占比·目标（含偏离）→ 最右买卖标记（`.pf-badge`：红「买入 ¥x」、绿「卖出 ¥x」、灰「持有不动」、琥珀「不足一手」「自行处理」）。
  - 列表下面**紧接详情面板**（`.pf-detail`），只渲染被点中的那一只：6 个数字 + `_scroll_chart_html(..., trades=…)` 走势图（红上三角＝买入、绿下三角＝卖出，`store="awTrend.fund"`、默认近1年，图上方标题固定「走势与买卖点」，基金名不重复）+ **累计盈亏曲线**（`_pnl_chart_html`，`store="awPnl.fund"`、默认「全部」，元为单位、零轴以上填红以下填绿，同样标买卖点）+ 这只基金的成交小表。
  - 累计盈亏单独一个组件、**不要塞进 `_scroll_chart_html`**：那张图的三块面板是净值 / 相对起点涨跌 / 单期涨跌（百分比口径），而这张是「我赚了多少钱」（元）。口径在 `sim_account.fund_pnl()`：累计盈亏 = 持仓市值 + 累计卖出净额 − 累计买入总额（买入含费用、卖出扣费用），所以**卖出后曲线不掉下来**；没卖过时末值正好等于「持有收益」，卖出过就比它多出已实现的那部分。转入/转出不进单只基金的曲线。
  - 最后是**已清仓区块**（`_closed_section()`，列表组件 `aw_closed_list` / `_cl_list`），见下条；再下面是页底 expander（加删基金、买卖单位、位置开关）。
  - **为什么不用 st.dataframe 列表**：涨红跌绿的单元格颜色和买卖徽标给不了；**为什么不做卡片流**：平铺卡片在电脑上被用户点名"难看"，改成列表 + 点开。
- **「已清仓」= 份额归零的那一轮（回答"卖了之后当时的盈亏还查得到吗"）**
  - 数据来自 `sim_account.rounds(trades)`：把成交按「建仓 → 份额归零」切轮，**卖出后剩余份额 ≤ 0 即清仓**，之后再买是新的一轮；`pnl` = 累计卖出净额 − 累计买入总额（两头手续费都算），`days` = 建仓到清仓的天数，`ret` = pnl / 投入成本（只有卖出没有买入的补录残缺给 `None`）。转入/转出不计入单只基金。
  - 放在「我的持仓」页的**持仓列表下面**（不在新 tab），一轮一行：基金名（副标题 `代码 · 第 N 次清仓 · 仍在配置里`）/ 清仓日 / 持有天数 / 累计盈亏 / 收益率，标题右侧汇总「N 轮 · 累计兑现 ±x 元」；**没有清仓记录时也要显示这一段**（标题 + 一句「卖出后份额归零就会自动记到这里」），否则用户不知道去哪查。
  - 点一行 = `_cl_detail()`：清仓时累计盈亏 / 收益率 / 投入成本 / 卖出回收 / 持有天数 / 手续费 + `_pnl_chart_html(..., mark=清仓日, mark_label="清仓")`（竖虚线标清仓那天，之后曲线是平的）+ 这一轮日期区间内的成交小表。
  - 净值只到清仓前一天时（`len(curve) == 1`）不画图，改为一句「净值只更新到 x，清仓那天还没到」；**不要**说"缺净值数据"。
  - 仍挂在配置里、只是暂时没份额的基金，在持仓列表里是「未持有」，详情里加一句指路「清仓当时的盈亏在下方已清仓」——**两处都保留**（前者说明这个位置现在是空的，后者是历史结果）。
- **「买卖提醒」= 只出计划 + 一键登记**：结论条（这一轮动不动、买多少卖多少，`.pf-summary`）→ 差额清单（当前市值 / 当前权重 / 目标权重·位置级 / 偏离 / 操作标记）→「把这份清单登记成 N 笔成交」。**不放补录表单、不放台账**（用户明确说提醒和补录不是一回事）。
  - **不要恢复「按账户调仓 / 从零建仓」双模式**（用户明确说没必要）：永远按账户真实持仓算；没有账户 / 没有资金就提示先去「交易记录」。
- **「交易记录」= 只记账**：建账户（无账户时）/ 补录一笔（买入 / 卖出 / 转入 / 转出）/ 台账（按**录入顺序**列出全部成交）。这里是"实际做了什么"，和「买卖提醒」的计划分开。
  - **用「转入 / 转出」，不要写「入金 / 出金」**（用户看不懂券商术语）：转入 = 从银行卡或支付宝再放钱进来（记入本金、不算收益）；转出 = 取钱出去。旧数据里的「入金 / 出金」仍兼容（`sim_account.MONEY_SIDES`），判断一律用这个常量，别在别处硬写字符串。
  - **转到「转入 / 转出」时不该问基金**：类型用 `st.segmented_control`（容器 `tr_mode_switch`）放在 `st.form` **外面**（form 内控件改动不触发 rerun，字段换不掉），选中转入/转出后只留「金额（元）」一栏。
  - **台账每行行尾直接「改 / 删」**（components v2 组件 `aw_trade_list` / `_trade_list`，铅笔 + 垃圾桶图标）：**不要再放"删除第几笔"输入框**（用户明确说要在每一行后面改、删）。点铅笔 → 表单进入修改态（标题「正在修改第 N 笔 · 日期 · 类型 · 基金」+ 右上「取消修改」+ 提交按钮变「保存修改」+ 该行左侧蓝条），保存时按索引 `update` 覆盖那一笔、`pop(_tr_edit_idx)` 退回新建。回传值是 `"行号:时间戳"`——只回传行号的话，连点同一行第二次值没变就不会触发 rerun；Python 侧用 `_tr_del_sig` / `_tr_edit_sig` 去重，避免 rerun 后把同一笔删两遍。
  - **表单必须装在 `.st-key-tr_card` 一个容器里，列宽一律 `[1, 1, 1]` 三列**（日期 | 类型 | 空 / 基金 | 数量 | 净值 / 手续费 | 按钮）：外层容器画卡片，CSS 里把内层 `[data-testid="stForm"]` 的 border 与 padding 清零——否则 form 内的列比 form 外窄 2 个 padding，日期和下面的字段右端对不齐（用户点名"页面太乱、没对齐"）。**日期也留在 form 外**：改日期要立刻刷新下面的净值提示，而 form 内改动不触发 rerun。日期/基金/数量/净值/手续费都**不给 key、只传 value**——切到另一笔编辑时 value 变了控件自动跟着变，用户手改时又不会被覆盖；净值在「同一只 + 同一天」时优先用原来记下的成交净值（真实成交价未必等于当日净值）。
- **「收益对比」= 独立 tab**：我的账户 vs 项目默认基金 vs 策略理论三线（`_compare_chart_html`，都归一到 1.0）+ 三个差距指标 + 区间指标表。**不要再塞回持仓页**（用户要求单独一页）。
- **买卖计算只有一份**：`_hg_plan()`（定义在 tab 之前，rerun 即算）返回 `rows / orders / by_code / buy / sell / today / pnl`，持仓页的列表徽标和「买卖提醒」的清单**都读它**。别再各写一遍差额循环——两处口径一旦分叉，页面之间的数字就会对不上。
- 调仓基数用账户真实总资产（`_acct_daily["equity"]`），**不是** `_hg_mv + 现金`：换过基金后旧代码不在 `_hg_mv` 里，基数会偏小、算出的买入金额偏大。
- **「其他」= 不在启用位置里、账上还有份额的代码**（`_hg_other_mv`）：判断基准是 `_hg_active_slot_codes`（`HG.active()` 里的基金），**不是** `HG.all_codes()`——用后者会把「位置被关掉但还拿着」的基金漏掉，这些钱既不在列表里也不进总金额，头卡的总金额和持有收益会凭空少掉一大截（实测少 28 万、收益率从 +0.04% 变成 −54%）。总金额 = 启用位置的持仓 `mv` + 其他 `mv_all − mv` + 现金；「买卖提醒」的合计与「调仓基数 = 持仓 + 现金」说明都用 `mv_all`。
  - 这类行同样走 `_pf_row(_hg_other_item(code, why))`（`w_tgt=None` → 目标权重和偏离显示「—」），买卖标记换成「位置已关闭 / 不在配置里」；**点开要有完整详情**（走势图 + 累计盈亏 + 成交），不能只给一句说明。详情里的净值用 `_nav_of_code(code)` 取，**不要用 `_hg_panel[code]`**——关掉的位置不在面板里，会假报"没有净值数据"。
- `_compare_chart_html`、`_trend_chart_data`、`_scroll_chart_html` 全部定义在 tab 之前（持仓页详情图要用），改它们时注意别移回 tab 之后，否则 tab3 执行时 `NameError`。

### 自检清单（每次写完新页面/新区块必须逐项过，过不了不交付）
1. 日期：具体日 `2026/09/24`、期间 `2026年10月`/`2026年`，`grep -n ':T\|%Y-%m\|%Y/%m"' streamlit_app/*.py` 无展示层违规。
2. 结构：区块是否在共享卡片容器里，是否用了 `.sec-head` / `.sec-note`，与基金检索页并排看是否一致；**用无头 Chrome 打开真实页面截图检查重叠和对齐**（AppTest 与 jsdom 都看不出布局问题）。
3. 图表：时间序列是否用了 iframe 组件体系，控件是否 tab + select 同行。
4. 颜色：涨红跌绿方向正确，无新增硬编码色（iframe 组件 CSS 常量除外）。
5. 空态与默认值：placeholder 文案、无数据提示是否齐全；有无重复控件。

- 适用范围：`streamlit_app/`、`rebal/*.py` 生成的 HTML 报告、`docs/`、Excel/Markdown 报告。

## 线上部署（手机外网访问）
- **必须用个人 WorkBuddy 账号发布**：公司账号发出来的域名是 `*.app-tencent.workbuddy.host`，公网 DNS 解析到 21.x 内网地址，只有公司内网能打开（手机走 5G 会连接超时）。个人账号发布的手机外网可直接访问，已验证。
- 打包：`./myenv/bin/python scripts/build_web.py` → `deploy_web_pub/`（只含代码、streamlit_app/static/fund_names.json、data/、output/nv_curves.csv、自选基金净值缓存 data/fund_nav/，约 19MB；不含 myenv）。`--password` 生成新访问密码（明文只存本机 `.workbuddy/web_password.txt`，线上只放哈希）。
- 发布：用 WorkBuddy「发布应用」，**目录固定为 `deploy_web_pub/`**（目录决定线上应用，换目录就变成另一个应用、网址也变），启动 `sh start.sh`（Streamlit 监听 $PORT、绑定 0.0.0.0）。每次发布前必须重新打包，且要用户明确说"发布/同步到线上"。
- 访问密码：`_password_gate()` 只在有密码哈希时启用，本机运行不受影响；登录后网址带 `?k=` 令牌，手机收藏该网址免输密码，换密码后令牌失效。
- 线上数据：发布时带上本机快照；线上「更新数据」写在云端沙箱，重新发布会被本机快照覆盖；线上录入的持仓成交不回传本机 —— **真实记账以本机为准**，线上主要用来看和核对。
- 线上沙箱拉估值可能失败（akshare 接口变更 / 无外网），`valuation.py` 已兜底：源不可用时沿用本地数据，不弹红字。行情 `data/*.csv` 照常可拉。
- 管理入口：设置 → 数据管理 → 发布的应用。

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
