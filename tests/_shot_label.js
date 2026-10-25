/* 走子痕迹标签 · 透明背景 截图自查（puppeteer-core + 本机 Chrome）
   运行：node tests/_shot_label.js
   输出：tests/_lab_full.png（整页）、tests/_lab_zoom.png（走子痕迹局部放大）

   为什么必须截图：老师 2026-10-01 的要求是**去掉文字白底**（「到H5吃炮」那类标签）。
   改完是不是真的"透明"、字在木色棋盘与色带上还读不读得清 —— DOM 断言不出来，只能看图。
*/
const path = require('path');
const ROOT = path.join(__dirname, '..');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const URL = 'http://127.0.0.1:8771/';

const puppeteer = require('puppeteer-core');

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--disable-gpu', '--hide-scrollbars', '--force-device-scale-factor=2']
  });
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1360, height: 1000, deviceScaleFactor: 2 });
    await page.goto(URL, { waitUntil: 'networkidle2', timeout: 30000 });
    await page.waitForSelector('.board-svg polygon', { timeout: 15000 });
    await new Promise(r => setTimeout(r, 2200));
    await page.addStyleTag({
      content: '*{animation:none !important;transition:none !important}'
    });

    // 等真实局面里出现走子痕迹标签（自动对弈在跑，很快就有）
    let ok = false;
    for (let i = 0; i < 40; i++) {
      ok = await page.evaluate(() => document.querySelectorAll('.mv-lab').length > 0);
      if (ok) break;
      await new Promise(r => setTimeout(r, 500));
    }
    if (!ok) {
      // 兜底：手动铺一组典型的痕迹（含吃子），确保能拍到
      await page.evaluate(() => window.ChessBoard.setMoveTrail([
        { from: '132', to: '137', army: 1 },
        { from: '245', to: '125', army: 3, captured: 'advisor' }
      ]));
      await new Promise(r => setTimeout(r, 300));
    }

    const info = await page.evaluate(() => {
      const labs = [...document.querySelectorAll('.mv-lab')];
      return labs.map(g => {
        const t = g.querySelector('text');
        const cs = getComputedStyle(t);
        return {
          text: t.textContent,
          fill: cs.fill, stroke: cs.stroke, strokeWidth: cs.strokeWidth,
          textFill: cs.textFill,               // 现代浏览器把填充映射到 text-fill？
          opacity: cs.opacity
        };
      });
    });
    console.log('页面上的走子痕迹标签：');
    info.forEach(x => console.log('  ', JSON.stringify(x)));

    const out = p => path.join(ROOT, 'tests', p);
    await page.screenshot({ path: out('_lab_full.png') });
    console.log('已出图 _lab_full.png');

    // 局部放大：包住所有痕迹标签 + 它们的箭头/圆圈
    const box = await page.evaluate(() => {
      const g = document.querySelector('g[class*="lyr-focus"], .board-svg g:last-child');
      const svg = document.querySelector('.board-svg');
      const r = svg.getBoundingClientRect();
      const k = Math.min(r.width / 248, r.height / 216);
      const px = (x, y) => [r.left + (x + 124) * k, r.top + (y + 108) * k];
      // 取所有 text 标签位置，向外扩
      const labs = [...document.querySelectorAll('.mv-lab text')];
      if (!labs.length) return null;
      const rects = labs.map(t => t.getBoundingClientRect());
      const x0 = Math.min(...rects.map(x => x.left)) - 40;
      const y0 = Math.min(...rects.map(x => x.top)) - 40;
      const x1 = Math.max(...rects.map(x => x.right)) + 40;
      const y1 = Math.max(...rects.map(x => x.bottom)) + 40;
      return { x: Math.max(0, x0), y: Math.max(0, y0), width: x1 - x0, height: y1 - y0 };
    });
    if (box) {
      await page.screenshot({ path: out('_lab_zoom.png'), clip: box });
      console.log('已出图 _lab_zoom.png  clip=', JSON.stringify(box));
    } else {
      console.log('没找到标签，跳过局部放大');
    }
  } finally {
    await browser.close();
  }
})();
