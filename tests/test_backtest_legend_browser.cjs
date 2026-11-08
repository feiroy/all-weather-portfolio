// 回测页图例「隐藏 → 恢复」的真实浏览器回归（H5，不是 8501 旧版）。
// 前置：8600 的 H5 服务已启动、web/dist 是最新构建。不会自己起服务，也不写任何数据文件。
//   NODE_PATH=<playwright-core 所在 node_modules> node tests/test_backtest_legend_browser.cjs
// 覆盖过的三个坑：隐藏后回撤面板还留线 / 隐藏后悬浮卡死 / 隐藏后再也点不回来。
const { chromium } = require('playwright-core');
const assert = require('node:assert/strict');

const BASE = process.env.BACKTEST_LEGEND_BASE || 'http://127.0.0.1:8600/a/main';
const BACKTEST = BASE + '/market/backtest';
const SIGNALS = BASE + '/market/signals';

// ECharts canvas 没有 DOM 图例项：从 zrender 显示列表里找 tspan 文字，换算成页面坐标后真实点击
async function legendPoint(page, name, idx = 0) {
  return page.evaluate(({ n, idx }) => {
    const box = document.querySelectorAll('.aw-chart')[idx];
    const chart = box && box.__awChart;
    if (!chart) return { found: false };
    const list = chart.getZr().storage.getDisplayList(true);
    const hit = list.find(e => e.type === 'tspan' && e.style && e.style.text === n && !e.silent);
    if (!hit) return { found: false };
    const r = hit.getBoundingRect().clone();
    if (hit.transform) r.applyTransform(hit.transform);
    const b = box.getBoundingClientRect();
    return { found: true, x: b.left + r.x + r.width / 2, y: b.top + r.y + r.height / 2 };
  }, { n: name, idx });
}
async function clickLegend(page, name, idx = 0) {
  const p = await legendPoint(page, name, idx);
  assert.equal(p.found, true, '找不到可点击的图例项：' + name);
  await page.mouse.click(p.x, p.y);
  await page.waitForTimeout(300);
}
async function snap(page, name, idx = 0) {
  return page.evaluate(({ n, idx }) => {
    const c = document.querySelectorAll('.aw-chart')[idx]?.__awChart;
    if (!c) return null;
    const o = c.getOption();
    const main = o.series.find(s => s.name === n);
    const sec = o.series.find(s => s.name === n + ' 回撤');
    return {
      selected: o.legend[0].selected[n],
      mainHasValue: !!main && main.data.some(v => v != null),
      mainAllNull: !!main && main.data.every(v => v == null),
      secPresent: !!sec,
      secHasValue: !!sec && sec.data.some(v => v != null),
    };
  }, { n: name, idx });
}
async function hover(page, idx = 0, times = 12) {
  const box = await page.locator('.aw-chart').nth(idx).boundingBox();
  for (let k = 0; k < times; k++) {
    await page.mouse.move(box.x + 60 + k * 22, box.y + 100);
    await page.waitForTimeout(18);
  }
  await page.waitForTimeout(150);
}
// tooltip 是挂在 .aw-chart 内的 div，最外层那个同时含日期与所有数值行
async function tip(page, idx = 0) {
  return page.evaluate(idx => {
    const box = document.querySelectorAll('.aw-chart')[idx];
    const all = Array.from(box.querySelectorAll('div')).filter(d => /\d{4}\/\d{2}\/\d{2}/.test(d.textContent || ''));
    return all.length ? all[0].textContent : '';
  }, idx);
}
async function openPage(browser, url, errors, viewport) {
  const page = await browser.newPage({ viewport, colorScheme: 'light' });
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForFunction(() => {
    const c = document.querySelectorAll('.aw-chart')[0]?.__awChart;
    return c && c.getOption().series.length >= 3;
  }, { timeout: 60000 });
  await page.waitForTimeout(500);
  return page;
}
const legendNames = page => page.evaluate(() =>
  document.querySelectorAll('.aw-chart')[0].__awChart.getOption().legend[0].data);

(async () => {
  const errors = [];
  let browser;
  try {
    browser = await chromium.launch({ channel: 'chrome', headless: true });

    // 1) 桌面双面板：隐藏 1 条 → 恢复，主图 / 回撤线 / tooltip 全部联动
    let page = await openPage(browser, BACKTEST, errors, { width: 1440, height: 1100 });
    let names = await legendNames(page);
    const t = names[1] || names[0];
    assert.equal((await snap(page, t)).secPresent, true, '初始应有回撤线');
    await clickLegend(page, t);
    let s = await snap(page, t);
    assert.equal(s.selected, false); assert.equal(s.mainAllNull, true); assert.equal(s.secPresent, false);
    await hover(page);
    assert.equal((await tip(page)).includes(t), false, '隐藏后 tooltip 不能再报该策略的值');
    await clickLegend(page, t);
    s = await snap(page, t);
    assert.equal(s.selected, true, '★ 再次点击图例必须能恢复');
    assert.equal(s.mainHasValue, true, '★ 恢复后主图必须有数据');
    assert.equal(s.secPresent, true, '★ 恢复后回撤线必须回来');
    assert.equal(s.secHasValue, true, '★ 恢复后回撤线必须有值');
    await hover(page);
    assert.equal((await tip(page)).includes(t), true, '★ 恢复后 tooltip 必须重新出现该策略');

    // 2) 连隐 2 条，再逐条恢复（隐藏项的图例不能被渲染成不可点）
    await clickLegend(page, names[0]); await clickLegend(page, names[2]);
    assert.equal((await snap(page, names[0])).selected, false);
    assert.equal((await snap(page, names[2])).secPresent, false);
    await clickLegend(page, names[0]);
    assert.equal((await snap(page, names[0])).mainHasValue, true);
    assert.equal((await snap(page, names[2])).selected, false, '另一条应保持隐藏');
    await clickLegend(page, names[2]);
    assert.equal((await snap(page, names[2])).secPresent, true);
    await page.close();

    // 3) 单面板（Signals）：没有下方面板时隐藏/恢复同样生效，tooltip 不能多出一行「—」
    page = await openPage(browser, SIGNALS, errors, { width: 1440, height: 1100 });
    names = await legendNames(page);
    await clickLegend(page, names[0]);
    assert.equal((await snap(page, names[0])).mainAllNull, true);
    await hover(page);
    assert.equal((await tip(page)).includes(names[0]), false);
    await clickLegend(page, names[0]);
    assert.equal((await snap(page, names[0])).mainHasValue, true);
    await hover(page);
    assert.equal((await tip(page)).includes(names[0]), true);
    await page.close();

    // 4) 手机窄屏：图例可能换行，点击坐标仍要命中
    page = await openPage(browser, BACKTEST, errors, { width: 390, height: 844 });
    names = await legendNames(page);
    await page.locator('.aw-chart').first().scrollIntoViewIfNeeded();
    await page.waitForTimeout(250);
    await clickLegend(page, names[1]);
    assert.equal((await snap(page, names[1])).secPresent, false);
    await clickLegend(page, names[1]);
    assert.equal((await snap(page, names[1])).secHasValue, true);
    await page.close();

    assert.equal(errors.length, 0, '页面报错：' + errors.join(' | '));
    console.log('✅ 图例隐藏/恢复回归通过：桌面双面板 / 连隐两条 / 单面板 / 手机窄屏，页面报错 0');
  } catch (e) {
    console.error('❌ 图例回归失败：', e.message);
    if (errors.length) console.error('页面报错：', errors.slice(0, 6));
    process.exitCode = 1;
  } finally {
    browser && await browser.close();
  }
})();
