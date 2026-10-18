// 先由 Python 生成 fixture，并用 --serve-readonly 启动只读测试入口。
// 保留 playwright-core + 系统 Chrome；不点击更新行情、账户或交易控件。
const { chromium } = require('playwright-core');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const ROOT = path.resolve(__dirname, '..');
const RANGES = ['近1月', '近3月', '近1年', '今年来', '全部'];
const PERIODS = ['日', '月', '年'];
const STAGES = ['近1月', '近3月', '近1年', '今年来'];
const URL = process.env.CHART_TEST_URL || 'http://127.0.0.1:8511';

function digest(file) {
  return fs.existsSync(file) ? crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex') : null;
}
function readonlyHashes() {
  const names = ['sim_account.json', ...fs.readdirSync(path.join(ROOT, 'data')).filter(name => name.endsWith('.csv'))].sort();
  return Object.fromEntries(names.map(name => [name, digest(path.join(ROOT, 'data', name))]));
}
function closeNumber(actual, expected, message, tolerance = 1e-7) {
  assert.ok(Number.isFinite(actual), `${message}：实际值不是有限数 ${actual}`);
  assert.ok(Math.abs(actual - expected) <= tolerance * Math.max(1, Math.abs(expected)),
    `${message}：实际 ${actual}，预期 ${expected}`);
}
function shownNumber(text) {
  const match = text.replace(/,/g, '').replace(/−/g, '-').match(/[+-]?\d+(?:\.\d+)?/);
  assert.ok(match, `缺少显示数值：${text}`);
  return Number(match[0]);
}
function shownReturn(text, expected, description) {
  const cleaned = text.replace(/,/g, '').replace(/−/g, '-');
  const match = cleaned.match(/[+-]?\d+(?:\.(\d+))?/);
  assert.ok(match, `${description}：缺少显示数值`);
  const tolerance = .5 * 10 ** -(match[1]?.length || 0) + 1e-8;
  assert.ok(Math.abs(shownNumber(text) - expected) <= tolerance, `${description}：${text}，预期 ${expected}`);
}

async function settled(scope) {
  await scope.locator('#wrap').evaluate(() => new Promise(resolve =>
    requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(resolve)))));
}
async function state(scope) {
  return scope.locator('#wrap').evaluate(element => ({ ...element.dataset }));
}
async function waitPreset(scope, period, range, expected) {
  await scope.locator(`#wrap[data-period="${period}"][data-range="${range}"][data-start="${expected.start}"][data-rendered="${expected.count}"]`).waitFor();
  await settled(scope);
}

async function assertNumbers(scope, history, description) {
  const s = await state(scope);
  for (const key of ['start', 'end', 'count', 'total', 'rendered', 'initialCount', 'bars', 'stepBars']) {
    assert.ok(s[key] !== undefined && s[key] !== '' && Number.isFinite(Number(s[key])), `${description} 缺少 ${key}`);
  }
  const start = Number(s.start), end = Number(s.end), count = end - start + 1;
  assert.ok(Number.isInteger(start) && Number.isInteger(end), '可见边界必须是记录索引');
  assert.ok(start >= 0 && end < history.prices.length && count >= 1, `${description} 可见索引越界`);
  assert.ok(Number(s.count) >= 1 && Number(s.count) <= history.prices.length, '缩放边界为 1 到全历史');
  assert.ok(Math.abs(Number(s.count) - count) <= 1, '连续缩放的视窗宽度与实际可见点数应一致');
  assert.equal(Number(s.total), history.prices.length);
  assert.equal(Number(s.rendered), count);
  assert.equal(s.firstDate, history.dates[start]);
  assert.equal(s.lastDate, history.dates[end]);
  assert.match(s.firstDate, /^\d{4}\/\d{2}\/\d{2}$/);
  assert.match(s.lastDate, /^\d{4}\/\d{2}\/\d{2}$/);
  const rangeText = await scope.locator('#range').innerText();
  assert.ok(rangeText.includes(history.dates[start]) && rangeText.includes(history.dates[end]), '范围展示完整真实日期');
  const snapshot = await scope.locator('#chart').evaluate(svg => ({
    points: [...svg.querySelectorAll('circle[data-index]')].map(e => Number(e.dataset.index)),
    bars: [...svg.querySelectorAll('rect[data-bar]')].map(e => ({value: e.getAttribute('data-value'), height: Number(e.getAttribute('height'))})),
    steps: [...svg.querySelectorAll('rect[data-step]')].map(e => ({value: e.getAttribute('data-value'), height: Number(e.getAttribute('height'))})),
    extremes: [...svg.querySelectorAll('g[data-extreme]')].map(e => ({kind: e.dataset.extreme, date: e.dataset.date, price: e.getAttribute('data-price'), text: e.textContent})),
  }));
  // 不使用泛化的 [data-index]，极值标注也可能有该属性。
  assert.deepEqual(snapshot.points, Array.from({length: count}, (_, i) => start + i));
  assert.equal(Number(s.bars), count);
  assert.equal(snapshot.bars.length, count, '起点为 0% 仍然存在一根柱');
  const prices = history.prices.slice(start, end + 1);
  for (let i = 0; i < snapshot.bars.length; i++) {
    const bar = snapshot.bars[i];
    assert.ok(bar.value !== null && bar.value.trim() !== '', '相对起点柱必须有原始百分比');
    closeNumber(Number(bar.value), (prices[i] / prices[0] - 1) * 100, `${description} 相对柱 ${i}`);
    assert.ok(Number.isFinite(bar.height) && bar.height >= 0, '允许 0% 柱高度为 0');
  }
  const steps = Array.from({length: count}, (_, i) => start + i).filter(i => history.rets[i] !== null);
  assert.equal(Number(s.stepBars), steps.length);
  assert.equal(snapshot.steps.length, steps.length);
  for (const [offset, bar] of snapshot.steps.entries()) {
    assert.ok(bar.value !== null && bar.value.trim() !== '', '单期柱必须有原始百分比');
    closeNumber(Number(bar.value), history.rets[steps[offset]], `${description} 单期柱 ${steps[offset]}`);
    assert.ok(Number.isFinite(bar.height) && bar.height >= 0);
  }
  const first = prices[0], last = prices.at(-1), high = Math.max(...prices), low = Math.min(...prices);
  const metrics = {'#change': (last / first - 1) * 100, '#start-price': first, '#end-price': last, '#amplitude': (high / low - 1) * 100};
  for (const [selector, value] of Object.entries(metrics)) {
    const raw = await scope.locator(selector).getAttribute('data-value');
    assert.ok(raw !== null && raw.trim() !== '', `${selector} 缺少原始数值`);
    closeNumber(Number(raw), value, `${description} ${selector}`);
    shownReturn(await scope.locator(selector).innerText(), value, `${description} ${selector} 显示数值`);
  }
  // 同时验证显示值，避免 data-value 正确而摘要仍展示错误的基准。
  shownReturn(await scope.locator('#change').innerText(), metrics['#change'], `${description} 可见区间变化`);
  shownReturn(await scope.locator('#amplitude').innerText(), metrics['#amplitude'], `${description} 可见振幅`);
  assert.equal(snapshot.extremes.length, 2);
  for (const [kind, price] of [['high', high], ['low', low]]) {
    const markers = snapshot.extremes.filter(marker => marker.kind === kind);
    assert.equal(markers.length, 1, `${kind} 极值标注唯一`);
    const marker = markers[0];
    assert.notEqual(marker.price, null);
    closeNumber(Number(marker.price), price, `${description} ${kind}`);
    const index = history.dates.indexOf(marker.date);
    assert.ok(index >= start && index <= end, '极值必须来自可见窗口的真实交易日');
    closeNumber(history.prices[index], price, '极值日期与价格必须匹配');
    assert.ok(marker.text.trim(), '极值应在图上显示而非只有隐藏属性');
  }
  const texts = await scope.locator('#chart text').allTextContents();
  assert.ok(texts.some(text => text.includes('相对起点')), '保留相对起点面板');
  assert.ok(texts.some(text => /单[日月年]涨跌幅/.test(text)), '保留随周期命名的单期面板');
  assert.ok(texts.includes('0%'), '保留 0% 基准');
  return s;
}

async function assertGeometry(scope, description) {
  const result = await scope.locator('#chart').evaluate(svg => {
    const box = element => {
      const r = element.getBoundingClientRect();
      return {x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width, height: r.height};
    };
    const extremeNodes = [...svg.querySelectorAll('g[data-extreme] text')];
    const dateNodes = [...svg.querySelectorAll('[data-date-label]')];
    return {svg: box(svg),
      labels: extremeNodes.map(e => ({...box(e), text: e.textContent, kind: e.closest('g[data-extreme]').dataset.extreme})),
      callouts: [...svg.querySelectorAll('g[data-extreme] rect')].map(e => ({...box(e), kind: e.closest('g[data-extreme]').dataset.extreme})),
      otherTexts: [...svg.querySelectorAll('text')].filter(e => !e.closest('g[data-extreme]')).map(e => ({...box(e), text: e.textContent})),
      dates: dateNodes.map(e => ({...box(e), text: e.textContent})),
      clips: extremeNodes.flatMap(e => {
        const entries = [];
        for (let ancestor = e.parentElement; ancestor && ancestor !== svg; ancestor = ancestor.parentElement) {
          const match = (ancestor.getAttribute('clip-path') || '').match(/url\(#([^\)]+)\)/);
          const rect = match && svg.querySelector(`#${CSS.escape(match[1])} rect`);
          if (rect) {
            const b = rect.getBBox(), transform = ancestor.getScreenCTM();
            const p1 = new DOMPoint(b.x, b.y).matrixTransform(transform);
            const p2 = new DOMPoint(b.x + b.width, b.y + b.height).matrixTransform(transform);
            entries.push({label: box(e), clip: {x: p1.x, y: p1.y, right: p2.x, bottom: p2.y}});
          }
        }
        return entries;
      }),
      nonfinite: /(?:NaN|Infinity)/.test(svg.innerHTML),
    };
  });
  const inside = (box, bounds) => box.x >= bounds.x - 1 && box.y >= bounds.y - 1 && box.right <= bounds.right + 1 && box.bottom <= bounds.bottom + 1;
  const overlaps = (a, b) => Math.min(a.right, b.right) - Math.max(a.x, b.x) > .5 && Math.min(a.bottom, b.bottom) - Math.max(a.y, b.y) > .5;
  assert.equal(result.nonfinite, false, `${description} SVG 不能包含非法坐标`);
  assert.ok(result.labels.some(x => x.kind === 'high') && result.labels.some(x => x.kind === 'low'), '高低极值都有可见文本');
  for (const label of [...result.labels, ...result.dates]) {
    assert.ok(label.width > 0 && label.height > 0, `${description} 标签不可见：${label.text}`);
    assert.ok(inside(label, result.svg), `${description} 标签超出 SVG：${label.text}`);
  }
  for (const {label, clip} of result.clips) assert.ok(inside(label, clip), `${description} 极值标签被 plot clip 裁切`);
  for (const callout of result.callouts) assert.ok(inside(callout, result.svg), `${description} 极值标注背景超出 SVG`);
  for (const high of result.callouts.filter(box => box.kind === 'high')) {
    for (const low of result.callouts.filter(box => box.kind === 'low')) assert.ok(!overlaps(high, low), `${description} 极值标注背景重叠`);
  }
  for (const label of result.labels) {
    for (const other of result.otherTexts) assert.ok(!overlaps(label, other), `${description} 极值遮挡刻度或标题：${other.text}`);
  }
  const labels = [...result.labels, ...result.dates];
  for (let i = 0; i < labels.length; i++) {
    for (let j = i + 1; j < labels.length; j++) {
      assert.ok(!overlaps(labels[i], labels[j]), `${description} 标签重叠：${labels[i].text} / ${labels[j].text}`);
    }
  }
  assert.ok(result.dates.length > 0, '至少有一个真实日期刻度');
  assert.equal(new Set(result.dates.map(d => d.text)).size, result.dates.length, '日期刻度不重复');
}

async function assertFrameLayout(scope) {
  const layout = await scope.locator('#wrap').evaluate(wrap => {
    const ids = ['range', 'selection', 'change', 'start-price', 'end-price', 'amplitude'];
    return {width: innerWidth, height: innerHeight, scrollWidth: document.documentElement.scrollWidth,
      boxes: ids.map(id => {
        const e = document.getElementById(id), r = e.getBoundingClientRect(), clips = [];
        for (let p = e.parentElement; p && p !== document.documentElement; p = p.parentElement) {
          const style = getComputedStyle(p), b = p.getBoundingClientRect();
          if (['hidden', 'clip'].includes(style.overflowY)) clips.push({top: b.top, bottom: b.bottom});
        }
        return {id, left: r.left, right: r.right, top: r.top, bottom: r.bottom, height: r.height, clips};
      }), wrapWidth: wrap.getBoundingClientRect().width};
  });
  assert.ok(layout.scrollWidth <= layout.width + 2, 'iframe 内不应有横向溢出');
  for (const box of layout.boxes) {
    assert.ok(box.height > 0 && box.top >= -1 && box.bottom <= layout.height + 1, `${box.id} 摘要被 iframe 裁切`);
    assert.ok(box.left >= -1 && box.right <= layout.width + 1, `${box.id} 摘要横向溢出`);
    for (const clip of box.clips) assert.ok(box.top >= clip.top - 1 && box.bottom <= clip.bottom + 1, `${box.id} 被祖先容器裁切`);
  }
}

async function assertStages(panel, expected) {
  assert.equal(await panel.count(), 1, '概览内只有一个阶段摘要');
  assert.deepEqual(expected.map(stage => stage.label), STAGES);
  assert.equal(await panel.locator('.stage-summary-title').count(), 1);
  assert.equal((await panel.locator('.stage-summary-title').innerText()).trim(), '阶段表现');
  assert.equal(await panel.locator('.stage-metrics').count(), 1);
  const metrics = panel.locator('.stage-metrics .stage-metric');
  assert.equal(await metrics.count(), 4);
  assert.equal(await panel.locator('.stage-metric').count(), 4);
  assert.equal(await panel.locator('.stage-label').count(), 4);
  assert.equal(await panel.locator('.stage-return').count(), 4);
  assert.equal(await panel.locator('.stage-return[data-value]').count(), 4);
  assert.equal(await panel.locator('button, [role="button"], a, input, select, svg, rect, canvas').count(), 0, '阶段摘要只读且无柱图');
  assert.equal(await panel.locator('.stage-bars, .stage-values, .prior-return, .stage-delta, .lifetime').count(), 0, '不得保留同比或对比柱结构');
  assert.equal(await panel.evaluate(e => e.ownerDocument.querySelectorAll('.st-key-trend_stages, .stage-row').length), 0, '不得保留底部阶段卡或旧对比行');
  assert.equal(await panel.evaluate(e => e.ownerDocument.querySelectorAll('.stage-summary').length), 1, '不得在图表下方重复添加概览');
  assert.deepEqual(await metrics.evaluateAll(elements => elements.map(e => e.dataset.stage)), STAGES);
  const visible = ['阶段表现'];
  for (const stage of expected) {
    assert.deepEqual(Object.keys(stage).sort(), ['base', 'end', 'label', 'ret']);
    const metric = panel.locator(`.stage-metric[data-stage="${stage.label}"]`);
    assert.equal(await metric.locator('.stage-label').count(), 1);
    assert.equal((await metric.locator('.stage-label').innerText()).trim(), stage.label);
    const value = metric.locator('.stage-return');
    assert.equal(await value.count(), 1);
    const text = (await value.innerText()).trim(), raw = await value.getAttribute('data-value');
    const direction = stage.ret === null || stage.ret === 0 ? 'neutral' : stage.ret > 0 ? 'up' : 'down';
    const classes = (await value.getAttribute('class')).split(/\s+/);
    assert.deepEqual(classes.filter(cls => ['up', 'down', 'neutral'].includes(cls)), [direction], `${stage.label} 涨跌样式`);
    if (stage.ret === null) {
      assert.ok(raw === '' || raw === 'null', '缺失收益不伪造原始数值');
      assert.equal(text, '—');
    } else {
      assert.ok(raw !== null && raw.trim() !== '', `${stage.label} 必须有原始数值`);
      closeNumber(Number(raw), stage.ret, `${stage.label} 原始收益`);
      assert.match(text, /^[+\-−]?\d+(?:\.\d+)?%$/, '只显示百分比，不附带说明');
      shownReturn(text, stage.ret, `${stage.label} 显示收益`);
    }
    const color = await value.evaluate(e => getComputedStyle(e).color);
    const rgb = color.match(/^rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/);
    assert.ok(rgb, `${stage.label} 颜色应可解析：${color}`);
    const [red, green, blue] = rgb.slice(1).map(Number);
    if (direction === 'up') assert.ok(red > green && red > blue, `${stage.label} 上涨应为红色：${color}`);
    else if (direction === 'down') assert.ok(green > red && green > blue, `${stage.label} 下跌应为绿色：${color}`);
    else assert.ok(Math.max(red, green, blue) - Math.min(red, green, blue) < 60, `${stage.label} 零值或缺失应为中性色：${color}`);
    visible.push(stage.label, text);
  }
  assert.equal((await panel.innerText()).replace(/\s+/g, ''), visible.join(''), '阶段摘要只含标题、四个标签与数字');
}

async function assertStageLayout(panel, width) {
  await panel.scrollIntoViewIfNeeded();
  const layout = await panel.evaluate(summary => {
    const box = e => {
      const r = e.getBoundingClientRect();
      return {left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height,
        clientWidth: e.clientWidth, scrollWidth: e.scrollWidth};
    };
    const head = summary.closest('.st-key-trend_head');
    return {viewport: innerWidth, summary: box(summary), head: head && box(head),
      metrics: [...summary.querySelectorAll('.stage-metric')].map(metric => ({...box(metric),
        texts: [...metric.querySelectorAll('.stage-label, .stage-return')].map(e => {
          const range = document.createRange();
          range.selectNodeContents(e);
          const text = range.getBoundingClientRect(), clips = [];
          for (let p = e; p; p = p.parentElement) {
            const style = getComputedStyle(p);
            if (['hidden', 'clip', 'auto', 'scroll'].includes(style.overflowX)) clips.push(box(p));
          }
          return {...box(e), value: e.textContent, text: {left: text.left, right: text.right, top: text.top, bottom: text.bottom},
            lines: [...range.getClientRects()].map(r => r.top), clips};
        })
      }))};
  });
  assert.ok(layout.head, '阶段摘要必须位于基金概览卡内');
  for (const box of [layout.summary, layout.head]) {
    assert.ok(box.width > 0 && box.scrollWidth <= box.clientWidth + 2, `${width}px 概览不能横向溢出`);
    assert.ok(box.left >= -1 && box.right <= layout.viewport + 1, `${width}px 概览不能超出屏幕`);
  }
  assert.equal(layout.metrics.length, 4);
  for (const [index, metric] of layout.metrics.entries()) {
    assert.ok(Math.abs(metric.top - layout.metrics[0].top) <= 1, `${width}px 阶段仍需保持一行四列`);
    assert.ok(metric.width > 0 && metric.height > 0);
    if (index) assert.ok(metric.left >= layout.metrics[index - 1].right - 1, `${width}px 阶段列不能重叠`);
    assert.ok(metric.left >= layout.summary.left - 1 && metric.right <= layout.summary.right + 1);
    for (const text of metric.texts) {
      assert.ok(text.width > 0 && text.height > 0 && text.scrollWidth <= text.clientWidth + 1, `${width}px 数字或标签截断：${text.value}`);
      assert.ok(text.text.left >= metric.left - 1 && text.text.right <= metric.right + 1, `${width}px 文本越过所在列：${text.value}`);
      assert.ok(text.text.top >= text.top - 1 && text.text.bottom <= text.bottom + 1, `${width}px 文本垂直裁切：${text.value}`);
      assert.ok(text.lines.length > 0 && text.lines.every(top => Math.abs(top - text.lines[0]) <= 1), `${width}px 数字或标签不得折行：${text.value}`);
      for (const clip of text.clips) assert.ok(text.text.left >= clip.left - 1 && text.text.right <= clip.right + 1, `${width}px 祖先容器裁切文本：${text.value}`);
    }
  }
}

async function mouseAnchor(page, scope, fraction = .55) {
  const chart = scope.locator('#chart');
  await chart.scrollIntoViewIfNeeded();
  const box = await chart.boundingBox();
  assert.ok(box && box.width > 100);
  // 价格面板内部，避开左坐标轴和下方两个柱面板。
  return {box, x: box.x + box.width * fraction, y: box.y + Math.min(100, box.height * .18)};
}

(async () => {
  const before = readonlyHashes();
  let browser;
  let failure;
  try {
    const fixtures = JSON.parse(fs.readFileSync(path.join(ROOT, 'outputs/trend-test-cases.json'), 'utf8'));
    assert.equal(fixtures.version, 3, '先用新版 Python 测试生成四项概览 fixture');
    assert.equal(fixtures.sourceSha256, digest(path.join(ROOT, fixtures.source)), 'CSV 已变化，须重新生成 fixture');
    assert.deepEqual(fixtures.ranges, RANGES);
    assert.deepEqual(fixtures.periods, PERIODS);
    browser = await chromium.launch({executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true});
    const page = await browser.newPage({viewport: {width: 1600, height: 1100}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    const panel = () => page.getByRole('tabpanel', {name: /基金走势/});
    const host = () => panel().locator('iframe');
    const frame = () => panel().frameLocator('iframe');
    const stages = () => page.locator('.st-key-trend_head .stage-summary');
    let period = '日', preset = '近1月';
    let readonlyStages;

    async function stageSnapshot() { return stages().innerHTML(); }
    async function assertReadonly(snapshot) {
      assert.equal(await stageSnapshot(), snapshot, '主图交互不可改变概览阶段标签、数值或日期属性');
    }
    async function checkPreset(p = period, range = preset) {
      const h = fixtures.histories[p], expected = h.windows[range];
      await waitPreset(frame(), p, range, expected);
      const s = await assertNumbers(frame(), h, `${range}/${p}`);
      assert.equal(Number(s.count), expected.count);
      assert.equal(Number(s.initialCount), expected.count);
      assert.equal(Number(s.end), h.prices.length - 1);
      assert.equal(await frame().locator('#period').inputValue(), p);
      const selected = frame().locator('button[data-range][aria-pressed="true"]');
      assert.equal(await selected.count(), 1);
      assert.equal(await selected.getAttribute('data-range'), range);
      assert.ok((await frame().locator('#selection').innerText()).includes(range));
      if (readonlyStages !== undefined) await assertReadonly(readonlyStages);
      console.log('PASS 范围与数值', range, p, s.firstDate, s.lastDate, s.rendered);
    }
    async function selectRange(range) {
      const previousPeriod = period;
      await frame().getByRole('button', {name: range, exact: true}).click();
      preset = range;
      await checkPreset();
      assert.equal((await state(frame())).period, previousPeriod, '切换范围不改变粒度');
    }
    async function selectPeriod(next) {
      const previousRange = preset;
      await frame().locator('select#period[aria-label="周期"]').selectOption(next);
      period = next;
      await checkPreset();
      assert.equal((await state(frame())).range, previousRange, '切换粒度不改变预设范围');
    }
    async function custom() {
      await settled(frame());
      const s = await assertNumbers(frame(), fixtures.histories[period], `自选/${period}`);
      assert.equal(s.range, '自选区间');
      assert.equal(await frame().locator('button[data-range][aria-pressed="true"]').count(), 0, '自选区间清除预设选中态');
      assert.ok((await frame().locator('#selection').innerText()).includes('自选区间'));
      assert.equal(Number(s.initialCount), fixtures.histories[period].windows[preset].count, '记住上次预设');
      await assertReadonly(readonlyStages);
      return s;
    }
    async function wheel(dx, dy, zoom = false) {
      const a = await mouseAnchor(page, frame());
      await page.mouse.move(a.x, a.y);
      if (zoom) await page.keyboard.down('Control');
      try { await page.mouse.wheel(dx, dy); }
      finally { if (zoom) await page.keyboard.up('Control'); }
      await settled(frame());
    }
    async function reset() {
      const a = await mouseAnchor(page, frame());
      await page.mouse.dblclick(a.x, a.y);
      await settled(frame());
      await checkPreset();
    }
    async function openTab() {
      await page.getByRole('tab', {name: /基金走势/}).click();
      await page.locator('#chart-readonly-test').waitFor({state: 'attached'});
      await host().first().waitFor({state: 'attached'});
      assert.equal(await host().count(), 1, '基金走势仅一个图表 iframe');
      await frame().locator('#chart circle[data-index]').first().waitFor({state: 'attached'});
      assert.equal(await frame().locator('#chart').count(), 1);
      assert.equal(await page.locator('[data-testid="stException"], [data-testid="stError"]').count(), 0);
    }

    await page.goto(URL);
    await openTab();
    await checkPreset();
    assert.equal(await frame().locator('button[data-range]').count(), 5);
    assert.deepEqual((await frame().locator('button[data-range]').allTextContents()).map(text => text.trim()), RANGES);
    const options = await frame().locator('#period option').evaluateAll(es => es.map(e => [e.value, e.textContent.trim()]));
    assert.deepEqual(options, [['日', '日线'], ['月', '月线'], ['年', '年线']]);
    assert.equal(await frame().locator('.toolbar').count(), 0);
    assert.equal(await frame().getByRole('button', {name: /^(重置|复位|放大|缩小)$/}).count(), 0);
    assert.equal(await frame().locator('button:not([data-range])').count(), 0, '只留下范围按钮，删除工具栏');
    await assertStages(stages(), fixtures.stages);
    readonlyStages = await stageSnapshot();

    // 先切近1年验证所有粒度，避免把默认年线单点误当作异常。
    await selectRange('近1年');
    for (const p of PERIODS) {
      await selectPeriod(p);
      assert.ok(Number((await state(frame())).rendered) > 1, `近1年/${p} 应有多个点`);
      await assertGeometry(frame(), `近1年/${p}`);
    }
    for (const range of RANGES) {
      await selectRange(range);
      for (const p of PERIODS) {
        await selectPeriod(p);
        await assertGeometry(frame(), `${range}/${p}`);
      }
    }
    await selectRange('近1月');
    await selectPeriod('年');
    assert.equal(Number((await state(frame())).rendered), 1, '默认近1月配年线仅一个真实点，不扩成5年');
    closeNumber(Number(await frame().locator('#change').getAttribute('data-value')), 0, '单点区间变化');
    closeNumber(Number(await frame().locator('#amplitude').getAttribute('data-value')), 0, '单点振幅');
    await assertGeometry(frame(), '默认近1月年线单点');
    await assertReadonly(readonlyStages);

    // 点击每个只读数字项，主图及概览内容均不得改变。
    await stages().scrollIntoViewIfNeeded();
    await page.mouse.move(0, 0);
    await settled(frame());
    const chartBeforeStageClicks = await state(frame());
    const drawingBeforeStageClicks = await frame().locator('#chart').innerHTML();
    for (const label of STAGES) {
      await stages().locator(`.stage-metric[data-stage="${label}"]`).click();
      await settled(frame());
      await assertReadonly(readonlyStages);
      assert.deepEqual(await state(frame()), chartBeforeStageClicks);
      assert.equal(await frame().locator('#chart').innerHTML(), drawingBeforeStageClicks, '点击只读数字不得重绘或切换主图');
    }

    await selectRange('近1年');
    await selectPeriod('日');
    const initial = await state(frame());
    const anchor = await mouseAnchor(page, frame(), .32);
    await page.mouse.move(anchor.x, anchor.y);
    await page.mouse.down();
    await page.mouse.move(anchor.x + anchor.box.width * .4, anchor.y, {steps: 12});
    await page.mouse.up();
    const dragged = await custom();
    assert.ok(Number(dragged.start) < Number(initial.start), '拖动显示更早的真实历史');
    closeNumber(Number(dragged.count), Number(initial.count), '拖动不缩放');
    assert.equal(await frame().locator('#tip').isVisible(), false, '拖动不固定提示');
    await assertGeometry(frame(), '拖动后极值');
    await assertReadonly(readonlyStages);
    await wheel(0, 180, true);
    const zoomedOut = await custom();
    assert.ok(Number(zoomedOut.count) > Number(dragged.count), '缩小后展示更多历史');
    await wheel(0, -160, true);
    assert.ok(Number((await custom()).count) < Number(zoomedOut.count), '放大后展示更少历史');
    await wheel(-1000000, 0);
    assert.equal(Number((await custom()).start), 0, '左侧不能越过数据起始');
    await assertGeometry(frame(), '最早边界极值');
    await wheel(1000000, 0);
    assert.equal(Number((await custom()).end), fixtures.histories[period].prices.length - 1, '右侧不能超出真实最后记录');

    // 有限次真实滚轮事件覆盖缩放上下限，不改 DOM 或应用状态。
    const limit = Math.ceil(Math.log(fixtures.histories[period].prices.length) / .3) + 10;
    for (let i = 0; i < limit && Number((await state(frame())).count) < fixtures.histories[period].prices.length; i++) await wheel(0, 400, true);
    let s = await custom();
    assert.equal(Number(s.count), Number(s.total));
    assert.equal(Number(s.start), 0);
    await wheel(0, 400, true);
    assert.equal(Number((await custom()).count), Number(s.total), '全历史缩小边界稳定');
    for (let i = 0; i < limit && Number((await state(frame())).count) > 1; i++) await wheel(0, -400, true);
    s = await custom();
    assert.equal(Number(s.count), 1, '最小视窗允许1点');
    assert.equal(Number(s.rendered), 1);
    await wheel(0, -400, true);
    assert.equal(Number((await custom()).count), 1, '单点放大边界稳定');
    await assertGeometry(frame(), '缩放到单点');
    const singleDate = (await state(frame())).firstDate;
    await frame().locator('#period').selectOption('年');
    await settled(frame());
    const expectedYearPoints = fixtures.histories['年'].dates.includes(singleDate) ? 1 : 0;
    assert.equal(Number((await state(frame())).rendered), expectedYearPoints, '自选单日切年线不扩大范围');
    assert.equal((await state(frame())).range, '自选区间');
    if (!expectedYearPoints) assert.match(await frame().locator('#notice').innerText(), /暂无/);
    await frame().locator('#period').selectOption('日');
    await settled(frame());
    assert.equal((await state(frame())).firstDate, singleDate, '从无数据粒度切回仍保留自选日期');
    await reset();
    assert.equal((await state(frame())).range, '近1年', '双击恢复最后使用的预设，而不是默认近1月');
    await assertReadonly(readonlyStages);

    // 悬浮显示真实日期、价格和两种收益；点击固定后移动鼠标不改变提示。
    const a = await mouseAnchor(page, frame());
    await page.mouse.move(a.x, a.y);
    await frame().locator('#tip').waitFor({state: 'visible'});
    const tip = await frame().locator('#tip').innerText();
    assert.match(tip, /\d{4}\/\d{2}\/\d{2}/);
    assert.match(tip, /收盘价/);
    assert.match(tip, /涨跌幅/);
    assert.match(tip, /相对起点/);
    await page.mouse.click(a.x, a.y);
    const pinned = await frame().locator('#tip').innerText();
    await page.mouse.move(a.box.x + a.box.width * .72, a.y + 10);
    assert.equal(await frame().locator('#tip').innerText(), pinned, '点击固定后不随鼠标改变');
    await page.mouse.move(a.box.x + a.box.width * .7, a.box.y + a.box.height + 8);
    assert.equal(await frame().locator('#tip').innerText(), pinned, '离开图表仍保留固定提示');
    await page.mouse.click(a.x, a.y);
    await page.mouse.move(a.box.x + a.box.width * .72, a.y + 10);
    assert.notEqual(await frame().locator('#tip').innerText(), pinned, '再次点击取消固定');
    await assertReadonly(readonlyStages);

    // 在真实圆点/柱子上移动鼠标，而非只检查提示display:block。
    // 还需验证提示矩形在父页面可视区内，避免SVG.offsetTop=undefined导致auto落底而被裁。
    async function actualPointTip(selector, index, description, tap = false) {
      const mark = frame().locator(`${selector}[${selector.includes('circle') ? 'data-index' : selector.includes('data-step') ? 'data-step' : 'data-bar'}="${index}"]`);
      await mark.scrollIntoViewIfNeeded();
      const box = await mark.boundingBox();
      assert.ok(box && box.width > 0);
      const px = box.x + box.width/2, py = box.y + box.height/2;
      await page.mouse.move(0, 0);
      await page.mouse.move(px, py);
      await frame().locator(`#tip[data-index="${index}"]`).waitFor({state: 'visible'});
      if (tap) await page.mouse.click(px, py);
      const geom = await frame().locator('#tip').evaluate(e => {
        const r = e.getBoundingClientRect();
        return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,w:innerWidth,h:innerHeight,
                cssTop:getComputedStyle(e).top,text:e.innerText,index:Number(e.dataset.index)};
      });
      const iframe = await host().boundingBox(), viewport = page.viewportSize();
      assert.ok(Number.isFinite(parseFloat(geom.cssTop)), `${description} top必须是有限坐标`);
      assert.ok(geom.left >= 0 && geom.right <= geom.w && geom.top >= 0 && geom.bottom <= geom.h, `${description} iframe内提示不裁切`);
      assert.ok(iframe.y+geom.top >= 0 && iframe.y+geom.bottom <= viewport.height+1, `${description} 提示必须在父页面可视范围内（top=${iframe.y+geom.top}, bottom=${iframe.y+geom.bottom}, height=${viewport.height}）`);
      assert.equal(geom.index,index,`${description}提示点位正确`);
      const expected = fixtures.histories[period], s = await state(frame());
      assert.ok(geom.text.includes(expected.dates[index]),`${description}真实日期`);
      assert.ok(geom.text.includes(expected.prices[index].toFixed(4)),`${description}价格`);
      assert.ok(geom.text.includes(`单${period}涨跌幅`));
      assert.ok(geom.text.includes(expected.rets[index].toFixed(2)+'%'), `${description}单期值`);
      assert.ok(geom.text.includes(((expected.prices[index]/expected.prices[Number(s.start)]-1)*100).toFixed(2)+'%'),`${description}累计值`);
      if (tap) {
        assert.match(geom.text,/已固定/);
        await page.mouse.move(px+30,py);
        assert.equal(await frame().locator('#tip').innerText(),geom.text,`${description}点击固定有效`);
        await page.mouse.click(px,py);
      }
    }
    await page.setViewportSize({width:1440,height:650});
    await selectRange('近1月');
    for (const nextPeriod of PERIODS) {
      await selectPeriod(nextPeriod);
      const now = await state(frame());
      for (const index of [...new Set([Number(now.start), Math.floor((Number(now.start)+Number(now.end))/2), Number(now.end)])]) {
        await actualPointTip('#chart circle[data-index]',index,`${nextPeriod}线实际点${index}`);
      }
      const index = Number(now.end);
      await actualPointTip('#chart rect[data-bar]',index,`${nextPeriod}线累计柱`,true);
      await actualPointTip('#chart rect[data-step]',index,`${nextPeriod}线单期柱`,true);
    }
    await selectPeriod('日');
    const finalPoint = Number((await state(frame())).end);
    await actualPointTip('#chart circle[data-index]',finalPoint,'截图点位');
    const pointCard = page.locator('.st-key-trend_chart');
    await pointCard.screenshot({path:path.join(ROOT,'outputs/point-data-restored.png')});
    await page.mouse.move(0,0);
    await page.setViewportSize({width:1600,height:1100});

    // 周期变化后再自选并复位，确认记忆的是范围而非旧日线点数。
    await selectRange('近3月');
    await selectPeriod('月');
    await wheel(-1000000, 0);
    await custom();
    await reset();
    assert.equal((await state(frame())).period, '月');
    await selectPeriod('日');
    await selectRange('近1月');
    for (const width of [390, 980, 1600]) {
      await page.setViewportSize({width, height: 1100});
      if (width === 390) {
        const collapseSidebar = page.getByRole('button', {name: 'keyboard_double_arrow_left', exact: true});
        if (await collapseSidebar.isVisible()) await collapseSidebar.click();
      }
      await settled(frame());
      await checkPreset();
      await assertGeometry(frame(), `${width}px 默认视窗`);
      await assertFrameLayout(frame());
      await assertReadonly(readonlyStages);
      await assertStages(stages(), fixtures.stages);
      await assertStageLayout(stages(), width);
      const pointIndex = Number((await state(frame())).end);
      await actualPointTip('#chart circle[data-index]', pointIndex, `${width}px实际点`, true);
      await actualPointTip('#chart rect[data-step]', pointIndex, `${width}px单期柱`, true);
      await selectRange('近1年');
      await selectPeriod('月');
      await assertGeometry(frame(), `${width}px 月线`);
      await assertFrameLayout(frame());
      await selectPeriod('年');
      await assertGeometry(frame(), `${width}px 年线`);
      await assertFrameLayout(frame());
      await selectRange('近1月');
      await assertGeometry(frame(), `${width}px 单点`);
      await selectPeriod('日');
      if (width === 390 || width === 1600) {
        await page.mouse.move(0, 0);
        const card = page.locator('.st-key-trend_chart');
        await card.scrollIntoViewIfNeeded();
        await settled(frame());
        await card.screenshot({path: path.join(ROOT, 'outputs', width === 390 ? 'chart-redesign-mobile.png' : 'chart-redesign-desktop.png')});
        const overview = page.locator('.st-key-trend_head');
        await overview.scrollIntoViewIfNeeded();
        await settled(frame());
        await assertStageLayout(stages(), width);
        await overview.screenshot({path: path.join(ROOT, 'outputs', width === 390 ? 'stage-summary-mobile.png' : 'stage-summary-desktop.png')});
      }
    }
    await page.getByRole('tab', {name: /信号仪表盘/}).click();
    await page.getByRole('tab', {name: /基金走势/}).click();
    await checkPreset();
    await selectRange('全部');
    await selectPeriod('年');
    await page.reload();
    period = '日'; preset = '近1月';
    await openTab();
    await checkPreset();
    await assertStages(stages(), fixtures.stages);
    await assertFrameLayout(frame());
    await assertGeometry(frame(), '刷新默认视窗');
    await assertReadonly(readonlyStages);

    // Python 生成的真实生产 HTML，包含单点、零收益、正负收益、相邻极值。
    const syntheticPage = await browser.newPage({viewport: {width: 980, height: 1100}});
    syntheticPage.on('pageerror', e => errors.push(e.message));
    for (const fixture of fixtures.synthetic) {
      for (const width of [390, 980, 1600]) {
        await syntheticPage.setViewportSize({width, height: 1100});
        await syntheticPage.setContent('<iframe title="合成数据图表" style="border:0;width:100%;height:1000px"></iframe>');
        await syntheticPage.locator('iframe').evaluate((element, markup) => { element.srcdoc = markup; }, fixture.html);
        const scope = syntheticPage.frameLocator('iframe');
        await scope.locator('#chart circle[data-index]').first().waitFor({state: 'attached'});
        await settled(scope);
        const s = await assertNumbers(scope, fixture.history, `${fixture.name}/${width}`);
        assert.equal(Number(s.count), fixture.win);
        assert.equal(Number(s.start), fixture.history.prices.length - fixture.win);
        await assertGeometry(scope, `${fixture.name}/${width}`);
        await assertFrameLayout(scope);
        if (fixture.name === 'mixed') {
          const expected = (90 / 99 - 1) * 100;
          closeNumber(Number(await scope.locator('#change').getAttribute('data-value')), expected, '合成数据必须用首个可见价格99，而不是窗口前价格110');
        }
      }
    }
    // 合成样本只有日线时，不能选择不存在的月/年数据。
    const monthlySource = fixtures.synthetic.find(f => f.name === 'mixed');
    await syntheticPage.setContent('<iframe style="border:0;width:100%;height:1000px"></iframe>');
    await syntheticPage.locator('iframe').evaluate((e, markup) => {e.srcdoc = markup;}, monthlySource.html);
    const isolated = syntheticPage.frameLocator('iframe');
    await isolated.locator('#change').waitFor({state: 'attached'});
    assert.equal(await isolated.locator('option[value="月"]').isDisabled(), true, '合成单数据集不可选不存在的周期');
    await syntheticPage.close();
    assert.deepEqual(errors, [], '主页面及图表 iframe 不应有 JS 错误');
    console.log('PASS：5×3范围周期、概览四项只读数字、交互与边界、数值、极值布局、四列响应式及刷新回归');
  } catch (error) {
    failure = error;
  } finally {
    // 无论 fixture、启动、断言或浏览器关闭是否失败，均检查磁盘字节哈希；绝不覆盖恢复。
    try { if (browser) await browser.close(); }
    catch (error) { failure = failure ? new AggregateError([failure, error], '测试与浏览器清理均失败') : error; }
    try {
      const after = readonlyHashes();
      assert.deepEqual(after, before, '只读浏览器测试改变了账户或行情文件，不进行恢复覆盖');
      console.log('账户 SHA256（前/后相同）：', after['sim_account.json']);
    } catch (error) {
      failure = failure ? new AggregateError([failure, error], '测试失败且只读哈希检查失败') : error;
    }
  }
  if (failure) throw failure;
})().catch(error => { console.error(error); process.exitCode = 1; });
