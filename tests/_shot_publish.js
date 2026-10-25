// 专利版参赛截图（三张同帧）：CDP 驱动到指定手数 → 暂停 → 同帧裁三块
// 用法: node _shot_patent3.cjs [ply]
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');

const BASE = 'http://127.0.0.1:8773';
const OUT = 'D:/AAA我的文件/_publish_chess';
const TARGET = parseInt(process.argv[2] || '55', 10);
const PORT = 9333;
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function api(p, body) {
  const opt = body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  };
  const r = await fetch(BASE + p, opt);
  return r.json();
}

function launch() {
  const udd = path.join(os.tmpdir(), 'cdp-shot-' + Date.now());
  const args = [
    '--headless=new', '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + udd, '--window-size=1440,2000',
    '--hide-scrollbars', '--disable-gpu', '--no-first-run',
    '--no-default-browser-check', '--disable-extensions',
    'about:blank'
  ];
  const p = spawn(CHROME, args, { stdio: 'ignore', detached: false });
  return { proc: p, udd };
}

async function wsUrl() {
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const list = await r.json();
      const pg = list.find(t => t.type === 'page');
      if (pg && pg.webSocketDebuggerUrl) return pg.webSocketDebuggerUrl;
    } catch (e) { /* not up yet */ }
    await sleep(200);
  }
  throw new Error('CDP 未就绪');
}

function conn(url) {
  const ws = new WebSocket(url);
  let id = 0;
  const pend = new Map();
  const ready = new Promise((res, rej) => {
    ws.addEventListener('open', res);
    ws.addEventListener('error', rej);
  });
  ws.addEventListener('message', (ev) => {
    let m;
    try { m = JSON.parse(ev.data); } catch (e) { return; }
    if (m.id && pend.has(m.id)) {
      const { res, rej } = pend.get(m.id);
      pend.delete(m.id);
      if (m.error) rej(new Error(JSON.stringify(m.error)));
      else res(m.result);
    }
  });
  const send = (method, params) => new Promise((res, rej) => {
    const mid = ++id;
    pend.set(mid, { res, rej });
    ws.send(JSON.stringify({ id: mid, method, params: params || {} }));
  });
  return { ws, ready, send };
}

(async () => {
  const KEEP = process.argv.includes('--keep');
  // 1) 先把棋局驱动到目标手数（不依赖浏览器）；--keep 表示沿用当前局面，只重拍
  let st = null, ply = 0;
  if (!KEEP) {
    await api('/api/new', {});
    await api('/api/difficulty', { level: 2 });
    await api('/api/options', { max_ply: 120 });
    await api('/api/human_config', { armies: [] });
    await api('/api/auto', { on: true });

    const t0 = Date.now();
    while (Date.now() - t0 < 240000) {
      st = await api('/api/state');
      ply = (st.status || {}).ply || 0;
      if (ply >= TARGET) break;
      await sleep(150);
    }
    await api('/api/auto', { on: false });
  }
  await sleep(1200);
  st = await api('/api/state');
  ply = (st.status || {}).ply || 0;
  const sock = (st.status || {}).turn;
  const rawRank = st.ranks || st.ranking || null;
  console.log('到达 ply =', ply, ' 当前回合 =', sock, ' 战报 =', (st.log || []).length);
  if (rawRank) console.log('排名 =', JSON.stringify(rawRank));

  // 2) 起浏览器
  const { proc, udd } = launch();
  let cdp = null;
  try {
    const url = await wsUrl();
    cdp = conn(url);
    await cdp.ready;
    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: 1440, height: 2000, deviceScaleFactor: 2, mobile: false
    });
    await cdp.send('Page.navigate', { url: BASE + '/' });
    await sleep(3500);
    // 等页面把局面画出来（轮询到 ply 连续三拍不变）
    let last = '', same = 0;
    for (let i = 0; i < 40; i++) {
      const r = await cdp.send('Runtime.evaluate', {
        expression: `(document.getElementById('plyBadge')||{}).textContent||''`,
        returnByValue: true
      });
      const v = r.result.value;
      if (v === last && v && v !== '0') { if (++same >= 3) break; } else { same = 0; }
      last = v;
      await sleep(400);
    }
    console.log('页面手数徽标 =', last);

    // 关掉「自动推荐」并清掉棋盘上的蓝虚线示意：
    // 实测推荐落点常常正好是「上一手」的终点，两套标注会叠成一团（右缘'到 J2'压住'AI 推荐…'）。
    // 「自动推荐」这项能力在截图 3 的控制面板里仍有完整一行说明，不会丢信息。
    const off = await cdp.send('Runtime.evaluate', {
      expression: `(() => {
        const cb = document.getElementById('chkAutoHint');
        let was = cb ? cb.checked : null;
        if (cb && cb.checked) { cb.checked = false; cb.dispatchEvent(new Event('change', {bubbles:true})); }
        const clr = document.getElementById('btnHintClear');
        if (clr) clr.click();
        return JSON.stringify({wasChecked: was});
      })()`,
      returnByValue: true
    });
    console.log('自动推荐 =', off.result.value);
    // 「✖ 已清除 AI 推荐示意」是 4 s 自动收起的临时提示（app.js:93）——
    // 必须等它过期再拍，否则截图底部会挂着一条"我刚清除过什么东西"的痕迹。
    await sleep(5200);

    const rects = await cdp.send('Runtime.evaluate', {
      expression: `(() => {
        const g = s => { const e = document.querySelector(s); if (!e) return null;
          const r = e.getBoundingClientRect();
          return {x:r.x+window.scrollX, y:r.y+window.scrollY, w:r.width, h:r.height}; };
        return JSON.stringify({wrap:g('.wrap'), board:g('.board-panel'), bottom:g('.bottom')});
      })()`,
      returnByValue: true
    });
    const R = JSON.parse(rects.result.value);
    console.log('布局 =', JSON.stringify(R));

    const shot = async (clip, name, w, h) => {
      const r = await cdp.send('Page.captureScreenshot', {
        format: 'jpeg', quality: 92, captureBeyondViewport: true,
        clip: { x: clip.x, y: clip.y, width: clip.w, height: clip.h, scale: 1 }
      });
      const f = path.join(OUT, name);
      fs.writeFileSync(f, Buffer.from(r.data, 'base64'));
      const kb = (fs.statSync(f).size / 1024).toFixed(0);
      console.log('写出', name, w + 'x' + h, kb + 'KB');
    };

    const W = Math.round(R.wrap.w), H = Math.round(R.wrap.h);
    await shot({ x: 0, y: 0, w: W, h: H }, '参赛截图1_整页_对局与综合实力排名.jpg', W * 2, H * 2);
    const B = R.board;
    await shot({ x: B.x, y: B.y, w: B.w, h: B.h }, '参赛截图2_棋盘特写_赤壁荆州祁山与三方领地.jpg',
      Math.round(B.w * 2), Math.round(B.h * 2));
    const T = R.bottom;
    await shot({ x: T.x, y: T.y, w: T.w, h: T.h }, '参赛截图3_控制面板与战报.jpg',
      Math.round(T.w * 2), Math.round(T.h * 2));

    const meta = {
      ply, Turn: sock, logCount: (st.log || []).length,
      maxPly: st.max_ply, ranks: rawRank,
      shotAt: new Date().toISOString()
    };
    fs.writeFileSync(path.join(OUT, '_截图元数据.json'), JSON.stringify(meta, null, 2));
    console.log('元数据 =', JSON.stringify(meta));
  } finally {
    // 只关自己起的这一个进程
    try { if (cdp && cdp.ws) cdp.ws.close(); } catch (e) {}
    try { proc.kill(); } catch (e) {}
    console.log('已关闭自起的 Chrome，PID =', proc.pid);
  }
})().catch(e => { console.error('FAIL', e); process.exit(1); });
