/* 一键推荐下一步 · UI 专项验证（Node + DOM 桩 + mock fetch）

   老师 2026-10-01 原话：
     「加一个功能，可以一键推荐人类玩家走一下一步在棋盘上示意，但不帮他落子。
       你可以用蓝色虚线箭头加文字示意，推荐下一步必须专业，
       用上你最高档的 15 plies 的下棋智商」
     （★ 当天二次改口径：先说 12 plies，后改 15 —— 本测试按**最终口径 15** 守）

   本脚本守三条线：
     ★ **不落子**（红线）：整条链路只允许出现 /api/hint，**绝不允许** /api/move、
       /api/undo、/api/new 被发出 —— 推荐是"给建议"，不是"替老师下棋"。
     ★ **看得见**：棋盘上真的多了一层 `lyr-hint`，里面有
       蓝虚线（stroke-dasharray）+ 实心箭头（polygon）+ 终点方框（rect）+ 文字。
     ★ **过期即灭**：局面手数一变，蓝线自动消失（画一条基于旧局面的建议会诱导走错）。

   运行：node tests/_verify_hint_ui.js
*/
const fs = require('fs');
const path = require('path');
const ROOT = path.join(__dirname, '..');
const HINT_BLUE = '#1a73e8';

let ok = 0, bad = 0;
function chk(cond, msg, extra) {
  if (cond) { ok++; console.log(`  [OK]   ${msg} ${extra || ''}`); }
  else { bad++; console.log(`  [FAIL] ${msg} ${extra || ''}`); }
}
function sect(n, t) {
  console.log('\n' + '='.repeat(74));
  console.log(`第 ${n} 节 · ${t}`);
  console.log('='.repeat(74));
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

// ---------------------------------------------------------------- DOM 桩
function _matchOne(el, sel) {
  if (!sel) return false;
  const m = /^([a-zA-Z][\w-]*)?((?:[.#][\w-]+)*)$/.exec(sel);
  if (!m) return false;
  const tag = m[1];
  if (tag && el.tag !== tag) return false;
  const parts = (m[2] || '').match(/[.#][\w-]+/g) || [];
  for (const p of parts) {
    if (p[0] === '.') {
      if (!String(el.attrs.class || '').split(/\s+/).includes(p.slice(1))) return false;
    } else if (el.attrs.id !== p.slice(1)) return false;
  }
  return true;
}
function _match(el, sel) {
  return String(sel || '').split(',').some(s => _matchOne(el, s.trim()));
}
class El {
  constructor(tag) {
    this.tag = tag; this.children = []; this.attrs = {};
    this.style = {}; this.listeners = {}; this._text = '';
    this.disabled = false; this.parent = null;
  }
  setAttribute(k, v) { this.attrs[k] = v; }
  getAttribute(k) { return this.attrs[k]; }
  appendChild(c) { this.children.push(c); c.parent = this; return c; }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  set innerHTML(v) {
    this._html = String(v == null ? '' : v);
    this.children = [];
    const s = this._html;
    if (!s) return;
    const tagRe = /<([a-zA-Z][\w-]*)((?:\s+[\w:-]+="[^"]*")*)\s*\/?>/g;
    let m;
    while ((m = tagRe.exec(s))) {
      const e = new El(m[1]);
      const attrRe = /([\w:-]+)="([^"]*)"/g;
      let a;
      while ((a = attrRe.exec(m[2] || ''))) e.attrs[a[1]] = a[2];
      this.appendChild(e);
    }
  }
  get innerHTML() { return this._html || ''; }
  get childElementCount() { return this.children.length; }
  get dataset() {
    const d = {};
    Object.keys(this.attrs).forEach(k => {
      if (k.startsWith('data-')) {
        d[k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = this.attrs[k];
      }
    });
    return d;
  }
  set textContent(v) { this._text = v; }
  get textContent() { return this._text; }
  fire(t, ev) { (this.listeners[t] || []).forEach(f => f(ev || { target: this })); }
  find(pred, out) {
    out = out || [];
    if (pred(this)) out.push(this);
    this.children.forEach(c => c.find(pred, out));
    return out;
  }
  querySelector(sel) {
    const r = []; this.children.forEach(c => c.find(e => _match(e, sel), r));
    return r[0] || null;
  }
  querySelectorAll(sel) {
    const r = []; this.children.forEach(c => c.find(e => _match(e, sel), r));
    return r;
  }
  closest(sel) { let n = this; while (n) { if (_match(n, sel)) return n; n = n.parent; } return null; }
  get classList() {
    const self = this;
    const list = () => String(self.attrs.class || '').split(/\s+/).filter(Boolean);
    return {
      add(c) { const s = new Set(list()); s.add(c); self.attrs.class = [...s].join(' '); },
      remove(c) { const s = new Set(list()); s.delete(c); self.attrs.class = [...s].join(' '); },
      contains(c) { return list().includes(c); },
    };
  }
  get offsetLeft() { return 0; }
  get offsetTop() { return 0; }
  get offsetWidth() { return 0; }
  get offsetHeight() { return 0; }
}

const _byId = {};
const _domL = {};
global.document = {
  createElementNS: (ns, tag) => new El(tag),
  querySelector: () => null,
  querySelectorAll: () => [],
  getElementById: id => (_byId[id] = _byId[id] || new El('div#' + id)),
  addEventListener: (t, f) => { (_domL[t] = _domL[t] || []).push(f); },
  activeElement: null,
  readyState: 'loading'
};
global.window = global;
global.addEventListener = (t, f) => { (_domL[t] = _domL[t] || []).push(f); };
global.innerWidth = 1200;
global.innerHeight = 800;
global.sessionStorage = { getItem: () => null, setItem: () => { }, removeItem: () => { } };
const _ls = {};
global.localStorage = {
  getItem: k => (k in _ls ? _ls[k] : null),
  setItem: (k, v) => { _ls[k] = String(v); },
  removeItem: k => { delete _ls[k]; }
};
global.setInterval = () => 0;          // 不跑轮询，测试自己控制节奏
global.location = { reload: () => { } };

// ---------------------------------------------------------------- mock fetch
const REQS = [];
let CUR = null;                        // 当前 state
let HINT_RES = null;                   // /api/hint 的返回值（测试可改）
let HINT_DELAY = 0;                    // /api/hint 的"长考"耗时（测 busy 用）
function mkState(over) {
  return Object.assign({
    build: '',
    pieces: [{ pos: '132', kind: 'cannon', army: 1, home: 1 }],
    status: {
      turn: 1, ply: 30, alive: [1, 2, 3], eliminated: [], annexed: {},
      winner: null, checks: {}, frozen: [], generals_facing: [], last: [],
      passed: [], deputies: {}, vitality: {}, combat: {}, out: [],
      declared_lose: [], resigned: [], stale_total_rounds: 9,
      steps_per_turn: 1, turn_steps: 0
    },
    material: { 1: 0, 2: 0, 3: 0 }, scores: { 1: 0, 2: 0, 3: 0 },
    ranks: {}, order: [1, 2, 3], kills: { 1: 0, 2: 0, 3: 0 },
    slain: { 1: 0, 2: 0, 3: 0 }, wrong: { 1: 0, 2: 0, 3: 0 },
    grades: { 1: {}, 2: {}, 3: {} }, grade_on: false, grade_plies: 6,
    grade_exact: true, arena_mode: 'choice',
    allow_undo: true, undo_per_side: 3, undo_left: { 1: 3, 2: 3, 3: 3 },
    undo_used: { 1: 0, 2: 0, 3: 0 }, can_undo: false,
    undo_who: 1, undo_rollback: 1,
    autosave: true, saved_at: 0, restored: false, restored_from: null, save_error: '',
    chain_limit: null, chain: {}, steps_per_turn: 1, turn_steps: 0,
    human_armies: [1], resigned: [],
    agents: { 1: {}, 2: {}, 3: {} },
    log: [], legal: [], auto: false, thinking: null,
    elapsed: 0, finished: false, drawn: false, max_ply: 300,
    replay_total: 30
  }, over || {});
}
CUR = mkState();
HINT_RES = {
  ok: true, army: 1, from: '156', to: '255',
  captured: null, captured_army: null, ply: 30, epoch: 1,
  depth: 5, plies: 13, nodes: 300000000, score: 12.5, latency: 275.4,
  reason: '搜索13步(上限5层·JIT) 估值+12.5'
};

global.fetch = async function (url, opt) {
  REQS.push({ url: url, opt: opt || {}, body: (opt || {}).body });
  if (url === '/api/state') return { json: async () => CUR };
  if (url === '/api/hint') {
    if (HINT_DELAY) await sleep(HINT_DELAY);
    return { json: async () => HINT_RES };
  }
  return { json: async () => ({ ok: true }) };
};
const reqCount = u => REQS.filter(r => r.url === u).length;
// 所有"会改对局"的写接口 —— 推荐链路里一个都不许出现
const WRITE_APIS = ['/api/move', '/api/undo', '/api/new', '/api/resign',
                    '/api/takeover', '/api/step', '/api/difficulty',
                    '/api/human_config', '/api/rule_config', '/api/discard_save'];

// ------------------------------------------------------------- 加载被测源码
const _fbar = document.getElementById('floatBar');
const _grip = new El('span'); _grip.attrs.class = 'fb-grip'; _fbar.appendChild(_grip);
['btnBack', 'btnFwd', 'btnLive'].forEach(id => {
  const b = document.getElementById(id); b.tag = 'button'; _fbar.appendChild(b);
});
eval(fs.readFileSync(path.join(ROOT, 'web', 'board_data.js'), 'utf8'));
const boardSrc = fs.readFileSync(path.join(ROOT, 'web', 'board.js'), 'utf8');
eval(boardSrc);
const appSrc = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
const htmlSrc = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
eval(appSrc);

// 棋盘层：从 SVG 桩里按语义 class 找（**不按索引** —— 见铁律 148）
const svg = document.getElementById('board');
const hintLayer = () => svg.children.filter(c => c.attrs && c.attrs.class === 'lyr-hint')[0];
const hintKids = () => (hintLayer() ? hintLayer().children : []);

(async function main() {
  const alerts = () => _byId['alerts'].textContent;

  // ==========================================================================
  sect(1, '① 源码接线：按钮存在、事件真绑、只有 /api/hint');

  chk(/id="btnHint"/.test(htmlSrc), 'index.html 有 `#btnHint`（💡 推荐下一步）');
  chk(/id="btnHintClear"/.test(htmlSrc), 'index.html 有 `#btnHintClear`（✖ 清除）');
  chk(/id="hintInfo"/.test(htmlSrc), 'index.html 有 `#hintInfo`（说明文字位）');
  chk(/id="chkAutoHint"/.test(htmlSrc), '★ index.html 有 `#chkAutoHint`（自动推荐开关）');
  chk(/plies/.test(htmlSrc) && /15 plies/.test(htmlSrc) && /12 plies/.test(htmlSrc),
    '页面上写明三档（9 / 12 / 15 plies）里的 12 与 15');
  chk(/不替你落子/.test(htmlSrc), '页面上写明「不替你落子」（老师最关心的一条）');
  chk(/lyr-hint/.test(boardSrc), 'board.js 有独立图层 class `lyr-hint`（可按名查，不靠索引）');
  chk(/const HINT_BLUE = '#1a73e8'/.test(boardSrc),
    'board.js 定义了推荐专用蓝 `#1a73e8`（与红/橙/金/琥珀都不撞）');
  chk(/setHint,\s*clearHint/.test(boardSrc), 'board.js 导出了 setHint / clearHint');
  chk(/function askHint/.test(appSrc), 'app.js 有 askHint()');
  chk(/function dropHint/.test(appSrc), 'app.js 有 dropHint()');
  chk(/fetch\('\/api\/hint'/.test(appSrc), 'app.js 只打 /api/hint');
  // ★ 档位**不再写死**：请求体的 plies 来自下拉框 `#selHintPly`（9/12/15，默认 9）
  chk(/function hintPlyWanted/.test(appSrc) && /selHintPly/.test(appSrc),
    '★ 请求体的 plies 由 `#selHintPly` 决定（不再写死某一档）');
  chk(/JSON\.stringify\(\{ plies: want \}\)/.test(appSrc),
    '★ 请求体是 `{plies: want}`（want = 下拉框档位，默认 9）');
  chk(/HINT_PLIES = \[9, 12, 15\]/.test(appSrc),
    '★ 白名单 = [9, 12, 15]（非法值退回 9，别把 9 静默吞成 12）');
  chk(/parseInt\(el\.value, 10\) : 9/.test(appSrc) &&
    /HINT_PLIES\.includes\(v\) \? v : 9/.test(appSrc),
    '★ **默认档 = 9 plies**（两处兜底都改了；2026-10-02 老师定）');
  chk(/function maybeAutoHint/.test(appSrc) && /function autoHintWanted/.test(appSrc),
    '★ app.js 有自动推荐（maybeAutoHint / autoHintWanted）');
  // 「不落子」在源码层面也不能有：askHint 函数体里不许出现 /api/move
  const askBody = appSrc.slice(appSrc.indexOf('async function askHint'),
                               appSrc.indexOf('function dropHint'));
  chk(!/\/api\/move/.test(askBody),
    '★★ askHint() 函数体内**没有任何** /api/move 调用（红线）');
  chk(!/\/api\/move/.test(appSrc.slice(appSrc.indexOf('function dropHint'),
                                       appSrc.indexOf('async function post'))),
    '★★ dropHint() 也不碰 /api/move');

  // ==========================================================================
  sect(2, '② 真跑 boot → 点「推荐下一步」→ 只发 /api/hint');

  chk((_domL['DOMContentLoaded'] || []).length === 1, 'DOMContentLoaded 已注册 boot');
  // ⚠️ 本测试的 ①~⑨ 节守的是**手动链路**，必须先把自动推荐关掉 ——
  //   否则 boot 一 poll 就自动发一次 /api/hint，后面"新增 1 次请求"的计数断言
  //   会被自动推荐打乱（不是功能坏了，是夹具没隔离）。自动推荐本身在第 ⑩ 节单独守。
  _ls['wb3chess.autoHint'] = '0';
  (_domL['DOMContentLoaded'] || []).forEach(f => f());
  await sleep(60);
  chk(reqCount('/api/state') >= 1, 'boot 后已拉到一次 /api/state');

  const nHint0 = reqCount('/api/hint');
  const btnH = _byId['btnHint'];
  chk(!!btnH && (btnH.listeners['click'] || []).length === 1,
    '★ #btnHint 真的绑了 1 个 click 回调（防"只写函数忘了绑按钮"的老坑）');

  btnH.fire('click');
  await sleep(80);
  chk(reqCount('/api/hint') === nHint0 + 1, '★ 点击后发出了 1 次 /api/hint');
  const hReq = REQS.filter(r => r.url === '/api/hint').slice(-1)[0];
  chk(!!hReq && /"plies":9/.test(hReq.body || ''),
    '★ 请求体默认是 `{"plies":9}`（下拉框的 selected 档）', `实际：${hReq && hReq.body}`);

  // ==========================================================================
  sect(3, '③ ★ 只读红线：整条链路没有任何写接口被调用');

  const writes = WRITE_APIS.map(u => [u, reqCount(u)]).filter(x => x[1] > 0);
  chk(writes.length === 0,
    '★★ 推荐全流程中 /api/move 等**所有写接口调用数 = 0**（不替他落子）',
    writes.length ? `违规：${JSON.stringify(writes)}` : '实测 全部为 0');
  chk(reqCount('/api/move') === 0, '★★ 特别是 /api/move —— 一次都没有');

  // ==========================================================================
  sect(4, '④ 棋盘上真的出现了蓝色虚线示意（line + 箭头 + 方框 + 文字）');

  const kids = hintKids();
  const kLine = kids.filter(c => c.tag === 'line');
  const kTip = kids.filter(c => c.tag === 'polygon');
  const kBox = kids.filter(c => c.tag === 'rect');
  // ⚠️ 文字是 `_lab()` 造的：返回的是 `<g class="mv-lab"><text/></g>`，
  //   text **不是** lyr-hint 的直接子元素 ⇒ 必须递归查，不能只 filter 第一层
  //   （第一版就栽在这：kids.filter(tag==='text') 恒为 0）。
  const kTxt = hintLayer() ? hintLayer().querySelectorAll('text') : [];
  chk(!!hintLayer(), '★ SVG 里出现 `lyr-hint` 图层');
  chk(kLine.length === 1, '★ 有 1 条推荐线', `实测 ${kLine.length}`);
  const L = kLine[0] || { attrs: {} };
  chk(L.attrs.stroke === HINT_BLUE, '★ 线是**蓝色** #1a73e8', `实测 ${L.attrs.stroke}`);
  chk(/\d/.test(L.attrs['stroke-dasharray'] || ''),
    '★ 线是**虚线**（stroke-dasharray 非空）', `实测 ${L.attrs['stroke-dasharray']}`);
  chk(L.attrs.x1 === '156' || (+L.attrs.x1 === +L.attrs.x1),
    '线的起点坐标是数字（xy() 解析成功）', `实测 x1=${L.attrs.x1}`);
  chk(kTip.length === 1 && kTip[0].attrs.fill === HINT_BLUE,
    '★ 有 1 个**实心蓝箭头**（polygon，fill=蓝）');
  chk(kBox.length === 1 && kBox[0].attrs.stroke === HINT_BLUE,
    '★ 终点是**方框** rect（与红/橙手的圆环刻意区分：建议落点 ≠ 已走过的点）');
  chk(kTxt.length >= 2, '★ 有文字标签（起点 + 终点）', `实测 ${kTxt.length}`);
  const txts = kTxt.map(t => t.textContent);
  chk(txts.some(s => /^推荐 起 /.test(s)), '起点文字形如「推荐 起 A4」',
    `实测 ${JSON.stringify(txts)}`);
  chk(txts.some(s => /^到 /.test(s)), '终点文字形如「到 K5」', `实测 ${JSON.stringify(txts)}`);
  // 坐标标签必须来自 coordLabel（156 → A4 / 255 → K5），不是原始引擎号
  chk(txts.some(s => /推荐 起 A4/.test(s)) && txts.some(s => /^到 K5/.test(s)),
    '★ 文字用的是**棋盘坐标标签**（156→A4、255→K5），与走子痕迹同一套写法',
    `实测 ${JSON.stringify(txts)}`);
  chk(kTxt.every(t => t.attrs.fill === HINT_BLUE),
    '文字也是蓝色（整条示意同一色系）',
    `实测 ${kTxt.map(t => t.attrs.fill).join('/')}`);
  chk(kTxt.every(t => t.attrs.stroke === 'none' || t.attrs.stroke == null),
    '★ 文字**无描边**（沿用老师 2026-10-01 定稿的透明字口径，不在这里另起一套）');
  chk(kTxt.every(t => t.attrs['font-weight'] === 'normal'),
    '★ 文字字重 normal（同上，别又变回"黑体"）');
  chk(hintLayer() && hintLayer().attrs['pointer-events'] === 'none',
    '★★ 推荐层 `pointer-events:none`（绝不吃掉 135 个点击热区）');

  // 「目标深度 / 实到深度 / 估值」副标：老师要"专业"，这些就是凭据，必须显示出来
  chk(txts.some(s => /15 plies/.test(s)) && txts.some(s => /估值/.test(s)),
    '★ 副标如实写出「AI 15 plies · 估值 +12.5」（专业度凭据）',
    `实测 ${JSON.stringify(txts)}`);
  chk(txts.some(s => /实到 13/.test(s)),
    '★ **目标档位（15）与实到深度（13）分开显示** —— 不虚标（老师最恨名不副实）',
    `实测 ${JSON.stringify(txts)}`);
  chk(!/12 plies/.test(_byId['hintInfo'].textContent || ''),
    '说明文字已从 12 plies 改为 15 plies（口径不留旧值）',
    `实测 ${_byId['hintInfo'].textContent}`);
  chk(/12 plies/.test(_byId['hintInfo'].textContent || '')
      || /A4\s*→\s*K5/.test(_byId['hintInfo'].textContent || ''),
    '控件行的说明文字同步显示"已示意：A4 → K5"',
    `实测 ${_byId['hintInfo'].textContent}`);

  // ==========================================================================
  sect(5, '⑤ 「✖ 清除」按钮：有推荐才可点，点完图层清空');

  chk(_byId['btnHintClear'].disabled === false, '有推荐时清除按钮可用');
  _byId['btnHintClear'].fire('click');
  await sleep(30);
  chk(hintKids().length === 0, '★ 点清除后 `lyr-hint` 内元素清空',
    `实测 ${hintKids().length}`);
  chk(reqCount('/api/move') === 0, '清除也只是重画，仍然没碰 /api/move');

  // ==========================================================================
  sect(6, '⑥ ★ 过期即灭：局面手数一变，蓝线自动消失');

  btnH.fire('click');
  await sleep(80);
  chk(hintKids().length > 0, '重新推荐后图层又有了', `实测 ${hintKids().length}`);
  // 模拟"老师自己落子了"：state.ply 变了（30 → 31）
  CUR = mkState({ status: Object.assign(mkState().status, { ply: 31 }) });
  _byId['btnUndo'].fire('click');        // 走 post() → poll() → render()
  await sleep(80);
  chk(hintKids().length === 0,
    '★★ 手数一变（30→31）→ 蓝线**自动消失**（不画基于旧局面的建议）',
    `实测 ${hintKids().length}`);
  chk(/局面已变|不再示意|清除/.test(alerts() || '') || hintKids().length === 0,
    '过期时不会静默留一条错误的建议线');

  // ==========================================================================
  sect(7, '⑦ 长考期间重复点击：不会堆起 N 个 15 plies 搜索');

  CUR = mkState();                       // 回到 ply=30，与 HINT_RES 匹配
  // ⚠️ 必须**真拉一次 state**：askHint 会拿返回的 `ply` 与 `state.status.ply` 比对
  //   （防"基于旧局面的建议"），若这里只改 CUR 不 poll，state 还停在第 6 节的
  //   ply=31 ⇒ 推荐会被**正确地**丢弃，测试反而误判成功能坏了。
  _byId['btnUndo'].fire('click'); await sleep(60);
  chk(/第\s*30\s*手|30\s*\/\s*300/.test(_byId['plyBadge'].textContent || ''),
    '前置：state 已刷新回 ply=30', `实测 ${_byId['plyBadge'].textContent}`);
  HINT_DELAY = 120;                      // 模拟"还在算"
  const nH = reqCount('/api/hint');
  btnH.fire('click');
  await sleep(20);
  btnH.fire('click');                    // 长考中再点
  btnH.fire('click');
  await sleep(40);
  chk(reqCount('/api/hint') === nH + 1,
    '★ 长考中连点 3 次，只发出 **1** 个 /api/hint 请求（`_hint_busy` 挡住）',
    `实测新增 ${reqCount('/api/hint') - nH}`);
  chk(btnH.disabled === true, '长考中按钮置灰（老师能看出"正在算"）');
  chk(/长考中/.test(btnH.textContent || ''), '按钮文案变成「长考中…」');
  await sleep(160);
  HINT_DELAY = 0;
  chk(btnH.disabled === false && /推荐下一步/.test(btnH.textContent || ''),
    '算完后按钮恢复可点、文案还原');
  chk(hintKids().length > 0, '算完后蓝线画上了');
  chk(reqCount('/api/move') === 0, '★★ 全程仍然一次 /api/move 都没有');

  // ==========================================================================
  sect(8, '⑧ 边界：对局已结束 / 后端报错 → 明确提示，不画线');

  _byId['btnHintClear'].fire('click'); await sleep(20);
  CUR = mkState({ finished: true });
  _byId['btnUndo'].fire('click'); await sleep(80);
  chk(/终局/.test(alerts() || ''), '前置：state 已刷新为「终局」',
    `实测 ${alerts()}`);
  const nEnd = reqCount('/api/hint');
  btnH.fire('click');
  await sleep(40);
  chk(reqCount('/api/hint') === nEnd, '对局已结束 → 不发请求（省一次长考）');
  // ⚠️ `setMsg()` 只改模块里的 myMsg，**要等下一次 render 才会拼进提示条**
  //   （#alerts 的内容是 render() 里重建的）⇒ 想断言文案就必须再 poll 一次。
  //   第一版直接读 alerts，测到的是上一轮的旧文案 ⇒ 假失败。
  _byId['btnUndo'].fire('click'); await sleep(80);
  chk(/对局已结束/.test(alerts() || ''), '并且给出「对局已结束」的明确提示',
    `实际：${alerts()}`);

  CUR = mkState();
  _byId['btnUndo'].fire('click'); await sleep(80);
  chk(!/终局/.test(alerts() || ''), '前置：state 已刷新回未终局',
    `实测 ${alerts()}`);
  HINT_RES = { ok: false, error: '上一次推荐还在长考中，请稍候' };
  btnH.fire('click'); await sleep(60);
  _byId['btnUndo'].fire('click'); await sleep(80);      // 同上：等一次 render
  chk(/推荐失败/.test(alerts() || ''), '后端 ok:false → 提示条写明「推荐失败：原因」',
    `实际：${alerts()}`);
  chk(hintKids().length === 0, '失败时不画线（不留半截示意）');

  // ==========================================================================
  sect(9, '⑨ ★ 长考进度必须**实时可见**（老师报「点了没画线」的真因）');

  // 现场：老师 2026-10-01 说「我点了上面的一键推荐，为何没有示意在图上画出路径」。
  //   真实网页回读 DOM（tests/_shot_hint.js）证明**绘制层完全正常**：
  //     直接 setHint 画出 line.hint-path / polygon.hint-tip / circle.hint-src /
  //     rect.hint-dst + 3 段文字，蓝色 #1a73e8、无描边、normal，且 .lyr-hint 就是最上层。
  //   ⇒ 真因是**"还在算"而界面没有任何进度**：12 plies ≈ 60s、15 plies 目标 5 分钟，
  //     而"正在长考"那句走的是 setMsg()，要等下一次 render() 才进 #alerts。
  //   本节就守两件事：① 长考期间 #hintInfo 按秒显示进度；
  //                 ② 轮询 render() **不许**把它覆盖掉（否则等于没做）。
  CUR = mkState();
  _byId['btnUndo'].fire('click'); await sleep(80);
  HINT_RES = {
    ok: true, army: 1, from: '156', to: '255', captured: null, ply: 30,
    depth: 5, plies: 12, score: 6.1, latency: 62, reason: 'x'
  };
  HINT_DELAY = 1500;                     // 模拟"分钟级长考"
  btnH.fire('click');
  await sleep(1150);                     // 让 1s 计时器至少跳一次
  chk(/已等\s*\d+s/.test(_byId['hintInfo'].textContent || ''),
    '★ 长考中 #hintInfo 按秒显示「已等 Ns」',
    `实测 ${_byId['hintInfo'].textContent}`);
  chk(/长考中\s*\d+s/.test(btnH.textContent || ''),
    '按钮上也带秒数（一眼看出"在动"）', `实测 ${btnH.textContent}`);
  // ★★ 关键守卫：轮询 800ms 一次，render() 里若不加 `if (!hintBusy)` 就会把进度抹平
  _byId['btnUndo'].fire('click'); await sleep(60);
  chk(/已等\s*\d+s/.test(_byId['hintInfo'].textContent || ''),
    '★★ 轮询 render() **不会**覆盖长考进度（#hintInfo 有 hintBusy 守卫）',
    `实测 ${_byId['hintInfo'].textContent}`);
  await sleep(700);                      // 等请求返回
  chk(/已在棋盘上画出蓝虚线/.test(_byId['hintInfo'].textContent || ''),
    '算完后 #hintInfo 明确写「已在棋盘上画出蓝虚线」（不必翻提示条）',
    `实测 ${_byId['hintInfo'].textContent}`);
  chk(hintKids().length > 0, '并且蓝线真的画上了', `实测 ${hintKids().length}`);
  chk(/推荐下一步/.test(btnH.textContent || ''), '按钮文案已还原',
    `实测 ${btnH.textContent}`);
  chk(!reqCount('/api/move'), '★ 全程依然一次 /api/move 都没有（未替老师落子）');
  HINT_DELAY = 0;

  // ==========================================================================
  sect(10, '⑩ ★★ 自动推荐：轮到人类接管的方就自动铺线，**不用点按钮**');
  //   老师 2026-10-01 二次追加：「AI 推荐 下一步 要自动 推荐（默认 12piles），
  //   不需要我点击 推荐下一步」。
  //   本节守 5 条：
  //     ① 打开开关 ⇒ **立刻**为当前局面自动发一次 /api/hint（不用点按钮）
  //     ② 轮询反复 render ⇒ **不重复发**（key = ply-turn 去重；否则 800ms 一次会把服务打爆）
  //     ③ 局面一变（ply 30 → 31）⇒ 自动再推荐一次，且**默认 12 plies**
  //     ④ 轮到 Bot 的方（turn ∉ human_armies）⇒ **不自动**（不跟真 Bot 抢 JIT 搜索锁）
  //     ⑤ 老师点「✖ 清除」后，**不会**被自动推荐立刻顶回来
  //     ⑥ 红线不变：全程 0 次 /api/move

  _byId['btnHintClear'].fire('click'); await sleep(20);

  // --- 前置：开关关着时不自动发（夹具隔离有效）---
  CUR = mkState();                       // ply=30, turn=1, human_armies=[1]
  const nOff = reqCount('/api/hint');
  _byId['btnUndo'].fire('click'); await sleep(80);      // poll → render（此时自动还关着）
  chk(reqCount('/api/hint') === nOff,
    '前置：开关关着时轮询**不自动**发推荐（夹具隔离有效）',
    `实测新增 ${reqCount('/api/hint') - nOff}`);

  const nA0 = reqCount('/api/hint');
  const cAH = _byId['chkAutoHint'];
  chk(!!cAH && (cAH.listeners['change'] || []).length === 1,
    '★ #chkAutoHint 真绑了 change 回调（防"只写函数忘了绑"的老坑）');
  cAH.checked = true;
  cAH.fire('change');
  await sleep(80);
  chk(reqCount('/api/hint') === nA0 + 1,
    '★★ 打开「自动推荐」⇒ **不用点按钮**就自动发出 1 次 /api/hint',
    `实测新增 ${reqCount('/api/hint') - nA0}`);
  chk(hintKids().length > 0, '并且蓝虚线自动铺上了', `实测 ${hintKids().length}`);
  const aReq = REQS.filter(r => r.url === '/api/hint').slice(-1)[0];
  chk(/"plies":9/.test(aReq.body || ''), '★ 自动推荐走的是**下拉框默认档 9 plies**',
    `实际：${aReq && aReq.body}`);
  chk(hintLayer() && hintLayer().attrs['pointer-events'] === 'none',
    '★★ 自动铺的线同样 `pointer-events:none`（不吃掉点击热区，老师照样能点子）');

  // --- ② 轮询不重复发 ---
  const nA1 = reqCount('/api/hint');
  for (let i = 0; i < 4; i++) { _byId['btnUndo'].fire('click'); await sleep(30); }
  chk(reqCount('/api/hint') === nA1,
    '★★ 连续 4 轮 render（同一手）⇒ **一次都不重发**（key = ply-turn 去重）',
    `实测新增 ${reqCount('/api/hint') - nA1}`);

  // --- ⑤ 清除后不会被立刻顶回来 ---
  _byId['btnHintClear'].fire('click'); await sleep(20);
  const nA2 = reqCount('/api/hint');
  _byId['btnUndo'].fire('click'); await sleep(60);
  chk(reqCount('/api/hint') === nA2,
    '★ 老师点「✖ 清除」后，同一下**不会**被自动推荐立刻顶回来（尊重手动清除）',
    `实测新增 ${reqCount('/api/hint') - nA2}`);
  chk(hintKids().length === 0, '清除确实清干净了', `实测 ${hintKids().length}`);

  // --- ③ 局面一变 ⇒ 自动再推荐一次 ---
  HINT_RES = {
    ok: true, army: 2, from: '221', to: '231', captured: null, ply: 31,
    depth: 4, plies: 12, score: 3.3, latency: 31, reason: 'x'
  };
  CUR = mkState({ status: Object.assign(mkState().status, { ply: 31, turn: 2 }),
                  human_armies: [1, 2] });
  const nA3 = reqCount('/api/hint');
  _byId['btnUndo'].fire('click'); await sleep(80);
  chk(reqCount('/api/hint') === nA3 + 1,
    '★★ 局面一变（ply 30→31）⇒ **自动**再推荐一次（下一手接着有建议）',
    `实测新增 ${reqCount('/api/hint') - nA3}`);
  chk(hintKids().length > 0, '新一手的蓝线也自动铺上了', `实测 ${hintKids().length}`);

  // --- ④ 轮到 Bot 的方 ⇒ 不自动 ---
  CUR = mkState({ status: Object.assign(mkState().status, { ply: 32, turn: 3 }),
                  human_armies: [1, 2] });
  const nA4 = reqCount('/api/hint');
  _byId['btnUndo'].fire('click'); await sleep(80);
  chk(reqCount('/api/hint') === nA4,
    '★★ 轮到 **Bot 接管的方**（turn=3 ∉ human_armies）⇒ **不自动**推荐'
    + '（否则要跟真 Bot 抢 JIT 搜索锁，平白拖慢对局）',
    `实测新增 ${reqCount('/api/hint') - nA4}`);

  // --- ⑥ 红线不变 ---
  //   ⚠️ 不在这里断 `/api/undo` —— 本节的 `btnUndo.fire('click')` 只是**借它触发一次
  //      post()→poll()**（沿用本文件既有的"拉一次 state"技巧），那几次 /api/undo
  //      是夹具自己发的，不是自动推荐发的。红线只看 /api/move。
  chk(reqCount('/api/move') === 0,
    '★★ 自动推荐全程 **0 次 /api/move** —— 自动 ≠ 替他落子（红线不变）');
  chk(!/\/api\/move/.test(appSrc.slice(appSrc.indexOf('function autoHintWanted'),
                                       appSrc.indexOf('async function post'))),
    '★★ 自动推荐的源码段（autoHintWanted / maybeAutoHint）里没有 /api/move');

  // --- ⑦ ★ 请求风暴守卫（真实事故，2026-10-01 由 tests/_shot_autohint.js 抓到）---
  //   现场：老师浏览器开着两个标签页，A 页在跑 12 plies 长考（30s），
  //   B 页自动推荐拿到后端 `busy` **立即返回** ⇒ 若清掉去重 key 让 800ms 轮询无脑重试，
  //   就变成每 800ms 一次 /api/hint（实测 90 秒发了 **70 次**，两边互相踩谁都算不完）。
  //   修法：busy/网络错误一律走 `scheduleAutoRetry()`（setTimeout 退避，上限 4 次），
  //   **不再由轮询驱动重试**。本节就守这一点：
  //     造一次 busy ⇒ 之后连拉 20 轮 render，**一帧都不许再发请求**。
  HINT_RES = { ok: false, busy: true, error: '上一次推荐还在长考中，请稍候' };
  CUR = mkState({ status: Object.assign(mkState().status, { ply: 40, turn: 1 }),
                  human_armies: [1] });
  _byId['btnUndo'].fire('click'); await sleep(80);      // 新局面 ⇒ 自动发一次（拿到 busy）
  const nB0 = reqCount('/api/hint');
  chk(nB0 >= 1, '前置：新局面自动发出了一次请求（拿到 busy）');
  for (let i = 0; i < 20; i++) { _byId['btnUndo'].fire('click'); await sleep(15); }
  chk(reqCount('/api/hint') === nB0,
    '★★★ **busy 之后连拉 20 轮 render，一次都不再发**（修掉"每 800ms 重试一次"的风暴）',
    `实测新增 ${reqCount('/api/hint') - nB0}`);
  chk(!/autoHintKey = '';/.test(appSrc.slice(appSrc.indexOf('if (hintBusy)'),
                                           appSrc.indexOf('if (hintBusy)') + 220)),
    '★★ busy 分支里**不再**直接清 key（改走带退避的 scheduleAutoRetry）');
  chk(/function scheduleAutoRetry/.test(appSrc) && /AH_RETRY_DELAY/.test(appSrc),
    '★★ 存在带**上限**的退避重试 scheduleAutoRetry（AH_RETRY_DELAY）');

  // ==========================================================================
  console.log('\n' + '='.repeat(74));
  console.log(`一键推荐下一步 · UI 专项验证：${ok} 通过 / ${bad} 失败`);
  console.log('='.repeat(74));
  process.exit(bad ? 1 : 0);
})();
