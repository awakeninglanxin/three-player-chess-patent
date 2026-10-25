/* AI 推荐示意（蓝虚线）· 真实网页自查 —— 老师 2026-10-01 报「点了推荐但图上没画路径」
   运行：node tests/_shot_hint.js
   输出：tests/_hint_live.png   （截全页）
        tests/_hint_dom.txt   （.lyr-hint 图层内每个元素的真实属性回读）

   本脚本做两件事，把"到底是哪一环断了"分开：
     ① **纯绘制**测试：**绕过按钮与网络**，直接调 `ChessBoard.setHint(...)`，
        再回读 SVG DOM。若这一步就画不出来 ⇒ 绘制层有 bug。
     ② **图层可见性**：回读 `lyr-hint` 的 class / pointer-events / 叠放次序，
        以及目标点位在 SVG 里的实际坐标（防"画到画面外"）。
   注意：`?v=` 防缓存对浏览器有效 ⇒ 脚本里带 cache-bust 参数强制取最新 board.js。
*/
const fs = require('fs');
const path = require('path');
const ROOT = path.join(__dirname, '..');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const URL = 'http://127.0.0.1:8771/?cb=' + Date.now();

const puppeteer = require('puppeteer-core');

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: ['--no-sandbox', '--disable-gpu', '--hide-scrollbars',
           '--force-device-scale-factor=2']
  });
  const log = [];
  const say = s => { log.push(s); console.log(s); };
  try {
    const page = await browser.newPage();
    page.on('console', m => say('  [console.' + m.type() + '] ' + m.text()));
    page.on('pageerror', e => say('  [pageerror] ' + e.message));
    await page.setViewport({ width: 1360, height: 1000, deviceScaleFactor: 2 });
    await page.goto(URL, { waitUntil: 'networkidle2', timeout: 30000 });
    await page.waitForSelector('.board-svg polygon', { timeout: 15000 });
    await new Promise(r => setTimeout(r, 2000));
    await page.addStyleTag({
      content: '*{animation:none !important;transition:none !important}'
    });

    // ---- 前置：ChessBoard 是否可达、setHint 是否导出 ----
    const pre = await page.evaluate(() => ({
      hasCB: typeof window.ChessBoard === 'object' && !!window.ChessBoard,
      hasSetHint: !!(window.ChessBoard && typeof window.ChessBoard.setHint === 'function'),
      hasClear: !!(window.ChessBoard && typeof window.ChessBoard.clearHint === 'function'),
      hasLayer: !!document.querySelector('.lyr-hint'),
      btnHint: !!document.getElementById('btnHint'),
      hintInfo: (document.getElementById('hintInfo') || {}).textContent || null,
      // 棋盘点位 → SVG 坐标 是否拿得到（画不出来的常见原因）
      xy111: (window.__xy_probe = null)
    }));
    say('前置：' + JSON.stringify(pre));

    // ---- ① 纯绘制：直接调 setHint（111 魏車 → 121）----
    const draw = await page.evaluate(() => {
      window.ChessBoard.setHint({
        from: '111', to: '121', army: 1, ply: 0, captured: null,
        note: 'AI 12 plies（实到 12） · 估值 +6.1'
      });
      const layer = document.querySelector('.lyr-hint');
      if (!layer) return { err: 'no .lyr-hint layer' };
      const kids = Array.from(layer.children);
      const txts = Array.from(layer.querySelectorAll('text')).map(t => ({
        t: t.textContent, fill: t.getAttribute('fill'),
        stroke: t.getAttribute('stroke'), w: t.getAttribute('font-weight')
      }));
      return {
        n: kids.length,
        tags: kids.map(c => c.tagName + '.' + (c.getAttribute('class') || '')),
        textCount: layer.querySelectorAll('text').length,
        texts: txts,
        pe: layer.getAttribute('pointer-events'),
        // 图层可见性：祖先链上有 display:none / visibility:hidden 吗
        visible: !!(layer.getBoundingClientRect && layer.getBoundingClientRect().height > 0),
        bbox: (() => { const b = layer.getBBox ? layer.getBBox() : null;
                       return b ? [Math.round(b.x), Math.round(b.y),
                                   Math.round(b.width), Math.round(b.height)] : null; })(),
        parentOrder: Array.from(layer.parentNode.children)
          .filter(c => c.tagName === 'g')
          .map(c => c.getAttribute('class')),
        strokeOfLine: (() => { const l = layer.querySelector('line');
                               return l ? l.getAttribute('stroke') : null; })()
      };
    });
    say('① 直接调 setHint 后 .lyr-hint：' + JSON.stringify(draw, null, 1));

    await page.screenshot({ path: path.join(ROOT, 'tests', '_hint_live.png') });

    // ---- ② 走真实链路：点按钮 → 等长考 → 看图层 ----
    //   长考 12~15 plies 要 1 分钟以上，这里只等到 12s 采样一次，
    //   目的是分清"按钮没发出请求"和"请求没回来"。
    const reqs = [];
    page.on('request', r => { if (r.url().includes('/api/hint')) reqs.push(r.url()); });
    await page.evaluate(() => { window.ChessBoard.clearHint(); });
    await page.click('#btnHint');
    await new Promise(r => setTimeout(r, 12000));
    const mid = await page.evaluate(() => ({
      btnTxt: (document.getElementById('btnHint') || {}).textContent,
      msg: (document.getElementById('alerts') || {}).textContent,
      layerKids: (document.querySelector('.lyr-hint') || { children: [] }).children.length
    }));
    say('② 点按钮 12s 后：' + JSON.stringify(mid));
    say('   捕获到的 /api/hint 请求数 = ' + reqs.length + ' ' + JSON.stringify(reqs));

    fs.writeFileSync(path.join(ROOT, 'tests', '_hint_dom.txt'),
                     log.join('\n'), 'utf-8');
    console.log('\n已写 tests/_hint_dom.txt 与 tests/_hint_live.png');
  } finally {
    await browser.close();
  }
})();
