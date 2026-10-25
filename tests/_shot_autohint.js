/* 自动推荐 · 真实网页自查 —— 老师 2026-10-01：
     「AI 推荐 下一步 要自动 推荐（默认 12piles），不需要我点击 推荐下一步」

   本脚本**一次都不点按钮**，只打开页面然后观察：
     ① 页面是否有一个勾选着的「自动推荐」开关（#chkAutoHint）
     ② 是否**自发**发出 /api/hint 请求（证明是"自动"，不是"点了才有"）
     ③ 长考完成后 `.lyr-hint` 图层里是否真的有元素（蓝虚线真的铺上了）
     ④ 提示位 #hintInfo 是否写着「已在棋盘上画出蓝虚线」
     ⑤ 全程 0 次 /api/move（自动 ≠ 替老师落子）

   运行：node tests/_shot_autohint.js       （约需 40~70 秒，12 plies 长考）
   输出：tests/_autohint_live.png（截全页）、tests/_autohint_dom.txt（回读记录）
*/
const fs = require('fs');
const path = require('path');
const ROOT = path.join(__dirname, '..');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const CB = Date.now();
// 默认打老师的 8771；做**隔离自查**时用
//   `SANCHI_URL=http://127.0.0.1:8772/ node tests/_shot_autohint.js`
//   （另起 `app.py --port 8772 --fresh --nosave` 的干净实例，
//    这样不会有别的标签页在抢同一把 JIT 搜索锁，也不会动老师那一局）
const URL = (process.env.SANCHI_URL || 'http://127.0.0.1:8771/') + '?cb=' + CB;

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
  let bad = 0;
  const chk = (c, msg, extra) => {
    if (c) say(`  [OK]   ${msg} ${extra || ''}`);
    else { bad++; say(`  [FAIL] ${msg} ${extra || ''}`); }
  };
  try {
    const page = await browser.newPage();
    page.on('pageerror', e => say('  [pageerror] ' + e.message));
    const reqs = [];
    page.on('request', r => { if (r.url().includes('/api/')) reqs.push(r.url()); });
    await page.setViewport({ width: 1360, height: 1000, deviceScaleFactor: 2 });
    await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForSelector('.board-svg polygon', { timeout: 15000 });

    // 记录"起点"计数：从打开页面到这一刻，/api/hint 应该已经自发了
    await new Promise(r => setTimeout(r, 2500));
    const hintReqs0 = reqs.filter(u => u.includes('/api/hint')).length;
    const s0 = await page.evaluate(() => {
      const c = document.getElementById('chkAutoHint');
      return {
        hasChk: !!c,
        checked: c ? !!c.checked : null,
        btnTxt: (document.getElementById('btnHint') || {}).textContent,
        info: (document.getElementById('hintInfo') || {}).textContent,
        kids: ((document.querySelector('.lyr-hint') || { children: [] }).children || []).length
      };
    });
    say('打开页面 2.5s（**未点任何按钮**）：' + JSON.stringify(s0, null, 1));
    chk(s0.hasChk, '① 页面有「自动推荐」勾选框 #chkAutoHint');
    chk(s0.checked === true, '① 且**默认就是勾上的**（老师不用去开）', `实际 ${s0.checked}`);
    chk(hintReqs0 >= 1,
      '★★ ② 一个按钮都没点，就已经自发了 /api/hint —— 这就是"自动推荐"',
      `实测自发 ${hintReqs0} 次`);
    chk(hintReqs0 <= 2,
      '★★★ ② 而且**只发了一次**（不是每 800ms 一次的风暴）',
      `实测 ${hintReqs0} 次 / 2.5 秒`);
    chk(/长考中/.test(s0.btnTxt || ''),
      '② 按钮自己变成「长考中 Ns」（说明确实在算，不是卡住）', `实际 ${s0.btnTxt}`);
    chk(/已等\s*\d+s/.test(s0.info || ''),
      '② 提示位 #hintInfo 按秒报进度', `实际 ${s0.info}`);

    // 等长考完成：12 plies ≈ 30s，给足 150s（若老师另开着一页在长考，本页会退避重试）
    const t0 = Date.now();
    let done = null;
    while (Date.now() - t0 < 150000) {
      await new Promise(r => setTimeout(r, 2000));
      const s = await page.evaluate(() => ({
        info: (document.getElementById('hintInfo') || {}).textContent || '',
        kids: ((document.querySelector('.lyr-hint') || { children: [] }).children || []).length,
        btnTxt: (document.getElementById('btnHint') || {}).textContent || ''
      }));
      // ⚠️ 完成瞬间写的是「✅ 已在棋盘上画出蓝虚线…」，但下一次 render()（≤800ms）会
      //   把它换成常驻口径「已在棋盘上示意：E9 → D9（…）· 未替你落子」——
      //   两种文案都代表"算完了、线画上了"，只认前者会**假失败**（第一版就栽在这）。
      if (/已在棋盘上(画出蓝虚线|示意)/.test(s.info) && s.kids > 0) { done = s; break; }
    }
    const secs = ((Date.now() - t0) / 1000).toFixed(1);
    say(`等了 ${secs}s 后：` + JSON.stringify(done));
    chk(!!done, '★★ ③ 长考完成后提示位写着「已在棋盘上示意 / 画出蓝虚线」',
      done ? '' : '超时 150s 仍未完成');
    chk(!!done && done.kids > 0,
      '★★ ③ `.lyr-hint` 图层里**真的有元素**（蓝虚线铺上了，不用点按钮）',
      done ? `实测 ${done.kids} 个` : '');
    const nH = reqs.filter(u => u.includes('/api/hint')).length;
    chk(nH <= 6,
      '★★★ ③ 全程 /api/hint 总次数 ≤ 6（每局面最多 1 + 4 次退避重试；旧版这里是 70 次）',
      `实测 ${nH} 次`);

    // 图层细节回读（颜色 / 虚线 / 无描边 / 不吃点击）
    const det = await page.evaluate(() => {
      const layer = document.querySelector('.lyr-hint');
      if (!layer) return null;
      const kids = Array.from(layer.children);
      const line = layer.querySelector('line');
      const txts = Array.from(layer.querySelectorAll('text'));
      return {
        tags: kids.map(c => c.tagName + '.' + (c.getAttribute('class') || '')),
        lineStroke: line && line.getAttribute('stroke'),
        dash: line && line.getAttribute('stroke-dasharray'),
        pe: layer.getAttribute('pointer-events'),
        texts: txts.map(t => t.textContent),
        textStroke: txts.map(t => t.getAttribute('stroke')),
        textWeight: txts.map(t => t.getAttribute('font-weight')),
        order: Array.from(layer.parentNode.children).filter(c => c.tagName === 'g')
          .map(c => c.getAttribute('class'))
      };
    });
    say('③ 图层细节：' + JSON.stringify(det, null, 1));
    chk(!!det && det.lineStroke === '#1a73e8', '线是宝蓝 #1a73e8', det && det.lineStroke);
    chk(!!det && /\d/.test(det.dash || ''), '线是虚线', det && det.dash);
    chk(!!det && det.pe === 'none', '推荐层不吃点击（pointer-events:none）', det && det.pe);
    chk(!!det && det.textStroke.every(s => s === 'none' || s == null),
      '★ 文字无描边（沿用 2026-10-01 定稿口径）');
    chk(!!det && det.textWeight.every(w => w === 'normal'), '★ 字重 normal');
    chk(!!det && det.order.indexOf('lyr-hint') === det.order.length - 1,
      '推荐层在最上层', det && JSON.stringify(det.order));

    await page.addStyleTag({
      content: '*{animation:none !important;transition:none !important}'
    });
    await page.screenshot({ path: path.join(ROOT, 'tests', '_autohint_live.png') });

    // ④ 红线：全程不许有 /api/move
    const mv = reqs.filter(u => u.includes('/api/move')).length;
    chk(mv === 0, '★★ ④ 全程 **0 次 /api/move** —— 自动推荐≠替老师落子', `实测 ${mv}`);
    say(`   全部请求：${JSON.stringify(reqs)}`);

    say(`\n自动推荐 · 真实网页自查：${bad ? '✗ ' + bad + ' 项失败' : '✓ 全部通过'}`);
    fs.writeFileSync(path.join(ROOT, 'tests', '_autohint_dom.txt'),
                     log.join('\n'), 'utf-8');
    console.log('\n已写 tests/_autohint_dom.txt 与 tests/_autohint_live.png');
  } finally {
    await browser.close();
  }
  process.exit(bad ? 1 : 0);
})();
