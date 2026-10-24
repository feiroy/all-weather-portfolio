// 新版回测比较的真实浏览器回归；仅访问独立只读入口。
const { chromium } = require('playwright-core');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const ROOT = path.resolve(__dirname, '..');
const URL = process.env.PERFORMANCE_TEST_URL || 'http://127.0.0.1:8501/?view=performance';
const out = path.join(ROOT, 'outputs');
function digestFiles() {
  const files = fs.readdirSync(path.join(ROOT, 'data')).filter(n => n.endsWith('.csv'));
  const accounts = ['data/sim_account.json', 'data/live_state.json'];
  return Object.fromEntries([...files.map(n => `data/${n}`), ...accounts].map(name => {
    const p = path.join(ROOT, name);
    return [name, fs.existsSync(p) ? crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex') : null];
  }));
}
async function settled(page, title, granularity) {
  await page.getByRole('heading', { name: title }).waitFor({ timeout: 60000 });
  await page.waitForFunction(({ pattern, scale }) => {
    const state = document.querySelector('.perf-render-state');
    return state && new RegExp(pattern).test(state.dataset.summary) && (!scale || state.dataset.granularity === scale);
  }, { pattern: title.source, scale: granularity });
  await page.locator('.perf-table').first().waitFor({ timeout: 60000 });
  await page.waitForFunction(() => document.querySelectorAll('[data-testid="stVegaLiteChart"] svg.marks').length >= 2);
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  assert.equal(await page.locator('[data-testid="stVegaLiteChart"]').count(), 2);
  assert.equal(await page.locator('[data-testid="stException"]').count(), 0);
  assert.equal(await page.locator('.perf-kpi').count(), 3);
}
async function select(page, label, option) {
  const group = page.locator('[data-testid="stSelectbox"]').filter({ has: page.getByText(label, { exact: true }) });
  await group.getByRole('combobox').click();
  await page.getByRole('option', { name: option, exact: true }).click();
}
(async () => {
  const before = digestFiles(), errors = [];
  let browser;
  try {
    browser = await chromium.launch({ channel: 'chrome', headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1200 }, colorScheme: 'light' });
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    await page.goto(URL);
    await settled(page, /^指标对比/);
    assert.equal(await page.getByRole('radio', { name: '三策略对比', exact: true }).isChecked(), true);
    assert.equal(await page.getByRole('radio', { name: '多年', exact: true }).isChecked(), true);
    await page.screenshot({ path: path.join(out, 'performance_overview.png'), fullPage: true });
    await page.getByText('年度', { exact: true }).click();
    await settled(page, /^指标对比.*2026/);
    await page.screenshot({ path: path.join(out, 'performance_yearly.png'), fullPage: true });
    await page.getByText('月度', { exact: true }).click();
    await settled(page, /^指标对比.*2026年10月/, '月度');
    await page.waitForFunction(() => [...document.querySelectorAll('[data-testid="stVegaLiteChart"] svg text')].some(e => e.textContent === '10月'));
    const ticks = await page.locator('[data-testid="stVegaLiteChart"]').first().locator('.role-axis-label text').allTextContents();
    const monthTicks = ticks.filter(t => /^\d+月$/.test(t));
    assert.equal(monthTicks.length, 10, '只展示已存在的10个自然月');
    assert.equal(new Set(monthTicks).size, monthTicks.length, '月份坐标不能重复');
    await page.screenshot({ path: path.join(out, 'performance_monthly.png'), fullPage: true });
    await select(page, '查看年份', '2025');
    await settled(page, /^指标对比.*2025年/);
    await select(page, '指标月份', '1月');
    await settled(page, /^指标对比.*2025年1月/);
    await page.getByText('调频影响', { exact: true }).click();
    await settled(page, /^月频 → 双周频/);
    await select(page, '对比月频的调仓频率', '周频');
    await settled(page, /^月频 → 周频/);
    await page.getByText('多年', { exact: true }).click();
    await settled(page, /^月频 → 周频.*2005-04-11/);
    await page.getByText('比较区间', { exact: true }).waitFor();
    await page.screenshot({ path: path.join(out, 'performance_frequency.png'), fullPage: true });
    await page.getByText('年度', { exact: true }).click();
    await settled(page, /^月频 → 周频.*2026/);
    await page.getByText('三策略对比', { exact: true }).click();
    await select(page, '调仓频率', '周频');
    await settled(page, /^指标对比/);
    await page.getByText('多年', { exact: true }).click();
    await select(page, '比较区间', '近3年');
    await settled(page, /^指标对比/);
    await settled(page, /^指标对比/, '多年');
    const tableValues = await page.locator('.perf-table tbody tr').evaluateAll(rows => rows.map(r => Number(r.querySelector('td').textContent)));
    const cardValues = await page.locator('.perf-kpi-number').evaluateAll(nodes => nodes.map(n => Number(Number(n.dataset.value).toFixed(2))));
    assert.deepEqual(cardValues, tableValues, '卡片与精确表的数值必须一致');
    const widths = [320, 375, 768, 1024, 1440];
    for (const width of widths) {
      await page.setViewportSize({ width, height: 1000 });
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      const result = await page.evaluate(() => ({
        viewport: innerWidth, pageWidth: document.documentElement.scrollWidth,
        cards: [...document.querySelectorAll('.perf-kpi')].map(el => ({ width: el.clientWidth, content: el.scrollWidth })),
        titleSize: parseFloat(getComputedStyle(document.querySelector('.perf-header h1')).fontSize),
        childSize: parseFloat(getComputedStyle(document.querySelector('.perf-kpi h3')).fontSize),
        fontVariant: getComputedStyle(document.querySelector('.perf-kpi-number')).fontVariantNumeric,
      }));
      assert.ok(result.pageWidth <= result.viewport + 1, `${width}px 页面不能横向溢出`);
      assert.ok(result.cards.every(c => c.content <= c.width + 1), `${width}px 卡片不能截断`);
      assert.ok(result.titleSize > result.childSize, '页标题必须大于卡片标题');
      assert.ok(result.fontVariant.includes('tabular-nums'), '数字使用等宽数位');
    }
    await page.setViewportSize({ width: 1440, height: 1200 });
    await page.evaluate(() => { document.documentElement.style.zoom = '2'; });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), '200%缩放不能撑宽页面');
    await page.evaluate(() => { document.documentElement.style.zoom = ''; });
    await page.getByRole('radio', { name: '多年', exact: true }).focus();
    await page.keyboard.press('ArrowRight');
    await settled(page, /^指标对比/, '年度');
    assert.equal(await page.getByRole('radio', { name: '年度', exact: true }).isChecked(), true);
    await page.getByText('多年', { exact: true }).click();
    await settled(page, /^指标对比/, '多年');
    await select(page, '调仓频率', '月频');
    await select(page, '比较区间', '全部历史');
    await settled(page, /^指标对比.*2005-04-11/, '多年');
    await page.screenshot({ path: path.join(out, 'performance_design_desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 375, height: 900 });
    await page.screenshot({ path: path.join(out, 'performance_design_mobile.png'), fullPage: true });
    assert.deepEqual(errors, [], '浏览器JS、图表编译或运行错误');
    assert.deepEqual(digestFiles(), before, '浏览器核验不应修改数据或账户');
    console.log('PASS: 两张图、三张卡片、时间频率切换、卡片数值对账；320/375/768/1024/1440px及200%缩放无页面溢出，键盘切换通过，JS错误=0，数据账户sha256不变。');
  } finally {
    if (browser) await browser.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
