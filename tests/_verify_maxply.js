/* ═══ _verify_maxply.js — 专利版「手数上限可调」验收探针（2026-10-25）═══

   验的不是「下拉框画出来了」，而是**它真的改得动对局**：
   ① 网页选 48 → 服务端 opts.max_ply 真变 48；
   ② 点「自动对弈」→ 这一局**真的在第 48 手停住**（不是只改了个显示数字）；
   ③ 徽章 / 小字 / 战报三处口径一致，且「打满」只在真碰到上限时才说；
   ④ 接口挡得住乱传（999 / "abc" / {}）；
   ⑤ **sharecode 透传**：带 ?sharecode= 打开页面时，所有 /api/* 请求都要带上它
      —— 平台反代不带就 403，页面空白（这个坑在标准版上踩过一次）；
   ⑥ 1440 / 390 两档排版。

   用法： node tests/_verify_maxply.js
          URL=http://127.0.0.1:8773/ CDC=9793 node tests/_verify_maxply.js
*/
'use strict';
const { spawn } = require('child_process');
const path = require('path'), os = require('os'), fs = require('fs');
const sleep = ms => new Promise(r => setTimeout(r, ms));

const URL_ = process.env.URL || 'http://127.0.0.1:8773/';
const PORT = parseInt(process.env.CDC || '9793', 10);
const W = parseInt(process.env.W || '1440', 10);
const H = parseInt(process.env.H || '1250', 10);
const SHARE = 'ABC123xyz';

let pass = 0, fail = 0;
const fails = [];
function chk(ok, label, extra) {
  if (ok) { pass++; console.log('  ✓ ' + label + (extra !== undefined ? '  [' + extra + ']' : '')); }
  else { fail++; fails.push(label); console.log('  ✗ ' + label + (extra !== undefined ? '  [' + extra + ']' : '')); }
}
const head = t => console.log('\n' + t);

(async () => {
  const udd = fs.mkdtempSync(path.join(os.tmpdir(), 'ply-'));
  const chrome = spawn('C:/Program Files/Google/Chrome/Application/chrome.exe',
    ['--headless=new', '--disable-gpu', '--no-first-run', '--hide-scrollbars',
      '--remote-debugging-port=' + PORT, '--user-data-dir=' + udd,
      '--window-size=' + W + ',' + H, URL_], { stdio: 'ignore' });

  let ws = null;
  for (let i = 0; i < 60; i++) {
    await sleep(250);
    try {
      const l = await (await fetch('http://127.0.0.1:' + PORT + '/json/list')).json();
      const t = l.find(x => x.type === 'page' && x.webSocketDebuggerUrl);
      if (t) { ws = new WebSocket(t.webSocketDebuggerUrl); break; }
    } catch (e) { }
  }
  if (!ws) { console.log('探针失败：连不上 Chrome（端口 ' + PORT + '）'); process.exit(2); }
  await new Promise(r => { ws.onopen = r; });

  let id = 0; const waits = new Map(); const reqs = [];
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.id && waits.has(m.id)) { waits.get(m.id)(m); waits.delete(m.id); return; }
    if (m.method === 'Network.requestWillBeSent') {
      reqs.push(m.params.request.url);
    }
  };
  const send = (method, params) => new Promise(res => {
    const i = ++id; waits.set(i, res);
    ws.send(JSON.stringify({ id: i, method: method, params: params || {} }));
  });
  const ev = async expr => {
    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.result && r.result.exceptionDetails) return { __err: String(JSON.stringify(r.result.exceptionDetails)).slice(0, 300) };
    return r.result && r.result.result ? r.result.result.value : null;
  };
  const state = () => ev('fetch("/api/state").then(r=>r.json())');
  const post = (url, body) => ev('fetch(' + JSON.stringify(url) + ',{method:"POST",' +
    'headers:{"Content-Type":"application/json"},body:' + JSON.stringify(JSON.stringify(body)) +
    '}).then(r=>r.json())');

  try {
    await send('Page.enable');
    await send('Runtime.enable');
    await send('Network.enable');

    /* ---------- 〇、sharecode 透传（先做：后面所有请求都在这个带参页面上发） ---------- */
    head('〇、sharecode 透传（平台反代不带就 403）');
    await send('Page.navigate', { url: URL_ + (URL_.indexOf('?') >= 0 ? '&' : '?') + 'sharecode=' + SHARE });
    for (let i = 0; i < 40; i++) {
      await sleep(300);
      const ok = await ev('!!(document.getElementById("selMaxPly") && document.getElementById("selMaxPly").options.length)');
      if (ok === true) break;
    }
    await sleep(800);
    const apiReqs = reqs.filter(u => u.indexOf('/api/') >= 0);
    const withShare = apiReqs.filter(u => u.indexOf('sharecode=' + SHARE) >= 0);
    chk(apiReqs.length >= 2, '/api/* 请求确实发出去了（否则页面是白的）', apiReqs.length + ' 条');
    chk(apiReqs.length > 0 && withShare.length === apiReqs.length,
      '每一条 /api/* 都带上了 sharecode', withShare.length + '/' + apiReqs.length);
    const bad = apiReqs.filter(u => u.indexOf('sharecode=') < 0).slice(0, 2);
    if (bad.length) console.log('     ↳ 漏带的：' + bad.join(' , '));

    /* ---------- 一、初始状态 ---------- */
    head('一、初始状态（默认 120，演示模式三方全 Bot）');
    const s0 = await state();
    chk(s0 && s0.max_ply === 120, '服务端默认 max_ply = 120', s0 && s0.max_ply);
    chk(s0 && Array.isArray(s0.human_armies) && s0.human_armies.length === 0,
      '演示模式：人类接管为空（三方全 Bot）', s0 && JSON.stringify(s0.human_armies));
    const init = await ev(`(function(){
      var sel=document.getElementById('selMaxPly');
      return { val: sel.value, n: sel.options.length,
               opts: [].map.call(sel.options, function(o){return +o.value;}),
               txt: sel.options[sel.selectedIndex] ? sel.options[sel.selectedIndex].text : '',
               badge: document.getElementById('plyBadge').textContent,
               info: document.getElementById('plyInfo').textContent };
    })()`);
    chk(init && init.val === '120', '下拉框初值 = 120', init && init.val);
    chk(init && init.n >= 4, '选项数量 ≥ 4', init && init.n);
    chk(init && [48, 120, 300].every(v => init.opts.includes(v)), '选项含 48 / 120 / 300', init && init.opts.join(','));
    chk(init && init.txt.includes('每方 40 手'), '选项文字写清每方手数', init && init.txt);
    chk(init && /\/\s*120$/.test(init.badge), '顶部徽章显示 x / 120', init && init.badge);
    chk(init && /每方 40 手/.test(init.info), '小字提示跟着 120 走', init && init.info);

    /* ---------- 二、页面上改 48 ---------- */
    head('二、在网页上把上限改成 48');
    await post('/api/new', {});
    await sleep(900);
    await ev(`(function(){ var s=document.getElementById('selMaxPly');
      s.value='48'; s.dispatchEvent(new Event('change',{bubbles:true})); return s.value; })()`);
    await sleep(1000);
    const s1 = await state();
    chk(s1 && s1.max_ply === 48, '服务端 opts.max_ply 真的变成 48', s1 && s1.max_ply);
    const ui1 = await ev(`({ val: document.getElementById('selMaxPly').value,
      badge: document.getElementById('plyBadge').textContent,
      info: document.getElementById('plyInfo').textContent })`);
    chk(ui1 && ui1.val === '48', '下拉框停在 48', ui1 && ui1.val);
    chk(ui1 && /\/\s*48$/.test(ui1.badge), '顶部徽章变成 x / 48', ui1 && ui1.badge);
    chk(ui1 && /每方 16 手/.test(ui1.info), '小字提示变成每方 16 手', ui1 && ui1.info);
    await sleep(1800);
    chk((await ev(`document.getElementById('selMaxPly').value`)) === '48',
      '两个轮询周期后没被弹回旧值');
    const logTxt = await ev(`document.getElementById('log').textContent`);
    chk(/手数上限\s*120\s*→\s*48/.test(logTxt || ''), '战报里留下一行「120 → 48」',
      (logTxt || '').split('\n').filter(l => l.includes('手数上限')).slice(-1)[0]);

    /* ---------- 三、真的在 48 手停住（核心） ---------- */
    head('三、自动对弈，验证这一局真的在第 48 手停住（一局约 50~70 秒）');
    // ⚠️ 不能假设「每局都打满」：三方混战里提前斩帅是合法的终局。
    //   真跑下来第一版就在这里假红过 —— 有人斩帅提前结束，ply 当然不等于 48。
    //   所以最多换 3 局，专门等一局「打满判和」的；提前分胜负的如实计数。
    let done = null, earlyWin = 0;
    for (let t = 1; t <= 3 && !done; t++) {
      await post('/api/new', {});
      await sleep(700);
      await ev(`document.getElementById('btnAuto').click()`);
      let st = null; const t0 = Date.now();
      for (let i = 0; i < 260; i++) {               // 单局最多等 130 s
        await sleep(500);
        st = await state();
        if (st && (st.finished || (st.status && st.status.winner))) break;
      }
      if (!st || !st.finished) { console.log('    ↳ 第 ' + t + ' 局没跑完，再试'); continue; }
      if (st.status.winner) {
        earlyWin++;
        console.log('    ↳ 第 ' + t + ' 局第 ' + st.status.ply + ' 手就斩帅分胜负（合法终局），换一局');
        continue;
      }
      done = st;
      console.log('    ↳ 第 ' + t + ' 局打满判和，用时 ' + ((Date.now() - t0) / 1000).toFixed(1) + ' s');
    }
    chk(!!done, '能等到一局「打满上限判和」的终局', '提前分胜负 ' + earlyWin + ' 局');
    // 页面轮询 800ms 一拍，判据要读屏上的字，就得等它把终局画出来
    for (let i = 0; i < 14; i++) {
      const b = await ev(`document.getElementById('plyBadge').textContent`);
      if (/48\s*\/\s*48/.test(b || '')) break;
      await sleep(300);
    }
    if (done) {
      chk(done.status.ply === 48, '停在第 48 手（不是 47 也不是 49）', done.status.ply);
      chk(done.finished === true, 'finished = true', done.finished);
      chk(done.max_ply === 48, '终局快照里 max_ply 仍是 48', done.max_ply);
      const ui3 = await ev(`document.getElementById('plyBadge').textContent`);
      chk(/48\s*\/\s*48/.test(ui3 || ''), '顶部徽章显示 48 / 48', ui3);
      const alertTxt = await ev(`document.getElementById('alerts').textContent`);
      chk(/打满\s*48\s*手/.test(alertTxt || ''), '告警条写明「打满 48 手」', alertTxt);
      chk(/按综合分排名/.test(alertTxt || ''), '告警条同时说明按综合分排名');
    }

    /* ---------- 四、接口边界 ---------- */
    head('四、接口挡得住乱传');
    const bad1 = await post('/api/options', { max_ply: 999 });
    chk(bad1 && bad1.ok === false && /24–300/.test(bad1.error || ''), '999 被拒且说明范围', bad1 && bad1.error);
    const bad2 = await post('/api/options', { max_ply: 'abc' });
    chk(bad2 && bad2.ok === false, '非数字被拒', bad2 && bad2.error);
    const bad3 = await post('/api/options', {});
    chk(bad3 && bad3.ok === false, '空字段被拒', bad3 && bad3.error);
    chk((await state()).max_ply === 48, '三次非法请求之后仍是 48（没被改成脏值）');
    const ok300 = await post('/api/options', { max_ply: 300 });
    chk(ok300 && ok300.ok === true && ok300.max_ply === 300, '300 可以设', ok300 && ok300.max_ply);
    await sleep(1000);
    const ui4 = await ev(`(function(){var s=document.getElementById('selMaxPly');
      return {val:s.value, txt:s.options[s.selectedIndex].text};})()`);
    chk(ui4 && ui4.val === '300', '下拉框跟上 300', ui4 && ui4.val);
    chk(ui4 && /每方 100 手/.test(ui4.txt), '300 的说明是每方 100 手', ui4 && ui4.txt);

    /* ---------- 五、排版 ---------- */
    head('五、排版（1440 宽）');
    const box = await ev(`(function(){
      var s=document.getElementById('selMaxPly');
      var r=s.getBoundingClientRect();
      var pan=s.closest('.ctrl-panel').getBoundingClientRect();
      var row=s.closest('.ply-row').getBoundingClientRect();
      var hint=document.getElementById('ctrlHint').getBoundingClientRect();
      return {h:r.height, w:r.width, right:r.right, panRight:pan.right,
              rowBottom:row.bottom, hintTop:hint.top,
              rowW:row.width, panW:pan.width};
    })()`);
    chk(box && box.h >= 18, '下拉框高度正常（没被压扁）', box && box.h.toFixed(1));
    chk(box && box.right <= box.panRight + 1, '下拉框在面板内，没溢出', box && (box.panRight - box.right).toFixed(1) + ' px');
    chk(box && box.rowW >= box.panW - 40, '这一行占满面板宽度（没和别的行挤在一起）',
      box && box.rowW.toFixed(0) + '/' + box.panW.toFixed(0));
    chk(box && box.hintTop >= box.rowBottom - 1, '提示文字在单独一行、不挤在同一行',
      box && (box.hintTop - box.rowBottom).toFixed(1) + ' px');

    /* ---------- 六、窄屏 ---------- */
    head('六、390 宽窄屏');
    await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
    await sleep(900);
    const m = await ev(`(function(){
      var s=document.getElementById('selMaxPly');
      var r=s.getBoundingClientRect();
      return {w:r.width, h:r.height,
              ov: document.documentElement.scrollWidth - document.documentElement.clientWidth};
    })()`);
    chk(m && m.w > 0 && m.h >= 18, '窄屏下拉框仍有正常尺寸', m && (m.w.toFixed(0) + '×' + m.h.toFixed(0)));
    chk(m && m.ov <= 1, '整页无横向滚动条', m && m.ov + ' px');
    if (m && m.ov > 1) {                          // 溢出就点名，别让人瞎猜
      const who = await ev(`(function(){
        var cw=document.documentElement.clientWidth, out=[];
        var all=[].slice.call(document.querySelectorAll('body *')).filter(function(e){
          var r=e.getBoundingClientRect(); return r.right>cw+1&&r.width>0; });
        // 只报「最深层」：没有子元素也在溢出列表里的那些，才是有问题的那个
        var deep=all.filter(function(e){
          return !all.some(function(c){ return c!==e && e.contains(c); }); });
        (deep.length?deep:all).forEach(function(e){
          var r=e.getBoundingClientRect();
          out.push((e.tagName+'.'+(e.className||'')+'#'+(e.id||'')).slice(0,46)
            +'→'+r.right.toFixed(0)+' w='+r.width.toFixed(0)
            +' "'+((e.textContent||'').trim().slice(0,18))+'"');
        });
        return out.slice(0,6).join(' ; ');
      })()`);
      console.log('     ↳ 溢出元素：' + who);
    }
    await send('Emulation.clearDeviceMetricsOverride');

    /* ---------- 收尾 ---------- */
    await post('/api/options', { max_ply: 120 });
    await post('/api/new', {});
    await sleep(600);
    chk((await state()).max_ply === 120, '收尾：默认值复位到 120');

  } catch (e) {
    fail++; fails.push('探针自身异常');
    console.log('  ✗ 探针自身异常：' + (e && e.stack || e));
  }

  console.log('\n' + '─'.repeat(52));
  console.log('  ' + pass + ' 项通过 / ' + fail + ' 项失败');
  if (fail) console.log('  失败：' + fails.join(' ｜ '));
  try { chrome.kill(); } catch (e) { }
  process.exit(fail ? 1 : 0);
})();
