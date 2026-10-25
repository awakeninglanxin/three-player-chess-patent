/* 三角区枢纽标记 · 真实网页截图自查（puppeteer-core + 本机 Chrome）
   运行：node tests/_shot_tri.js
   输出：tests/_tri_normal.png（常态）、tests/_tri_active.png（选中枢纽棋子 → 激活态）
        tests/_tri_zoom.png  （三角区局部放大）

   为什么必须截图：老师反复强调过「能看就真看，不能看就不许编」。
   本标记的成败全在**观感**（淡金是否够显眼但不刺眼、会不会与琥珀落点提示混淆、
   会不会被荆州/赤壁/祁山三条色带盖住）—— 这些用 DOM 桩断言不出来，只能看图。
   注：headless 里 CSS 动画会停在某一帧，故截图前先禁用动画取稳定态。
*/
const fs = require('fs');
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
    // 等首屏 state 拉回来 + 棋盘渲染完成
    await page.waitForSelector('.board-svg polygon', { timeout: 15000 });
    await new Promise(r => setTimeout(r, 2200));

    // 动画会让 headless 截图取到随机帧（同一份代码两张图不一样）⇒ 先冻住
    await page.addStyleTag({
      content: '*{animation:none !important;transition:none !important}'
    });

    const out = p => path.join(ROOT, 'tests', p);

    // ① 常态（未选中任何棋子）
    await page.evaluate(() => window.ChessBoard.clearHints());
    await new Promise(r => setTimeout(r, 400));
    await page.screenshot({ path: out('_tri_normal.png') });
    console.log('已出图 _tri_normal.png');

    // ② 激活态：强制把「选中的棋子」放在枢纽顶点上（不依赖当前局面有兵在 155）
    await page.evaluate(() => window.ChessBoard.setLegal('155', ['255', '355']));
    await new Promise(r => setTimeout(r, 400));
    await page.screenshot({ path: out('_tri_active.png') });
    console.log('已出图 _tri_active.png');

    // ③ 局部放大：三角区在 SVG 里的位置 → 换算到页面像素
    const box = await page.evaluate(() => {
      const s = document.querySelector('.board-svg');
      const r = s.getBoundingClientRect();
      // viewBox = '-124 -108 248 216'；棋盘坐标 (x,y) → 页面像素
      const k = Math.min(r.width / 248, r.height / 216);
      const px = (x, y) => [r.left + (x + 124) * k, r.top + (y + 108) * k];
      // 三角区三点：155(0,16.93) 255(-14.67,-8.47) 355(14.67,-8.47)
      const pts = [px(0, 16.93), px(-14.67, -8.47), px(14.67, -8.47)];
      const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
      const pad = 34 * k;                    // 留出顶点金环与标签的余量
      return {
        x: Math.min(...xs) - pad, y: Math.min(...ys) - pad,
        width: Math.max(...xs) - Math.min(...xs) + pad * 2,
        height: Math.max(...ys) - Math.min(...ys) + pad * 2
      };
    });
    const clip = {
      x: Math.max(0, box.x), y: Math.max(0, box.y),
      width: box.width, height: box.height
    };
    await page.screenshot({ path: out('_tri_zoom.png'), clip });
    console.log('已出图 _tri_zoom.png  clip=', JSON.stringify(clip));

    // 顺带把关键 CSS 的**实际生效值**打出来（避免"以为改了其实没生效"）
    const eff = await page.evaluate(() => {
      const g = document.querySelector('.tri-hub');
      if (!g) return null;
      const edge = g.querySelector('.tri-edge');
      const ring = g.querySelector('.tri-ring');
      const cs = n => n ? getComputedStyle(n) : null;
      return {
        hasHub: true,
        edgeStroke: cs(edge).stroke, edgeWidth: cs(edge).strokeWidth,
        edgeOpacity: cs(edge).strokeOpacity,
        ringAnim: cs(ring).animationName, ringDur: cs(ring).animationDuration,
        pointerEvents: cs(g).pointerEvents, cls: g.getAttribute('class')
      };
    });
    console.log('生效样式 =', JSON.stringify(eff, null, 2));
  } finally {
    await browser.close();
  }
})();
