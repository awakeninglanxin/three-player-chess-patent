/* 回看 UI 接线专项验证（Node + DOM 桩 + mock fetch）
   —— 锁住「按钮点了没反应」这类 bug。

   背景：本轮实现回看功能时，我第一版就**漏了 boot() 里的 addEventListener**
   （只写了 `stepBack()` 函数，没绑到 `#btnBack` 上），按钮点下去毫无反应。
   光靠"函数存在"的断言抓不到这种错 —— 必须**真触发 DOMContentLoaded → 真点击**，
   再看有没有真发出 `/api/replay` 请求。

   本脚本断言：
     ① boot 后 DOMContentLoaded 回调已注册且可执行
     ② 点「⏪ 再退一步」→ 真的 POST /api/replay，且 i = total − 1
     ③ 连点两次 → i 递减（可一路往前退）
     ④ 退到开局后再点 → 不再发请求（按钮已禁用）
     ⑤ 点「⏭ 继续下」→ 回到最新（按钮状态复位、不再处于回看）
     ⑥ 回看中 onPick 拒绝走子（不发 /api/move）
     ⑦ 点「⏩ 再进一步」→ i 递增；进到最新那一步不经 /api/replay（老师 2026-09-25 新增）
     ⑧ 悬浮条可拖动 → 位置变化并写入 localStorage
     ⑨ 在按钮上按下**不**误拖；双击把手复位到左上角 (12,12)
   运行：node tests/_verify_replay_ui.js
*/
const fs = require('fs');
const path = require('path');
const ROOT = path.join(__dirname, '..');

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
// 选择器匹配（够用即止）：逗号分隔的 tag / .class / #id / **tag.class** 复合
//   ⚠️ 2026-09-25 补：难度行渲染用了 `querySelectorAll('button.diff')`，
//      旧桩只认单一 tag，会命中不到 → 补复合选择器支持。
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
  addEventListener(t, f) {
    (this.listeners[t] = this.listeners[t] || []).push(f);
  }
  set innerHTML(v) {
    this.children = [];
    const s = String(v == null ? '' : v);
    if (!s) return;
    // 【2026-09-25 补】极简 HTML 解析：只认顶层标签 + 属性
    //   app.js 的难度行是 `dBox.innerHTML = lvs.map(...).join('')` 生成的按钮串，
    //   桩若不解析，`querySelectorAll('button.diff')` 就找不到任何按钮。
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
  get innerHTML() { return ''; }
  get childElementCount() { return this.children.length; }
  // data-* ↔ dataset（app.js 用 `b.dataset.level` 读档位）
  get dataset() {
    const d = {};
    Object.keys(this.attrs).forEach(k => {
      if (k.startsWith('data-')) {
        d[k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = this.attrs[k];
      }
    });
    return d;
  }
  set dataset(o) {
    Object.keys(o || {}).forEach(k => { this.attrs['data-' + k] = o[k]; });
  }
  set textContent(v) { this._text = v; }
  get textContent() { return this._text; }
  fire(t) { (this.listeners[t] || []).forEach(f => f({ target: this, key: 'Enter' })); }
  fireEvt(t, ev) { (this.listeners[t] || []).forEach(f => f(ev)); }
  find(pred, out) {
    out = out || [];
    if (pred(this)) out.push(this);
    this.children.forEach(c => c.find(pred, out));
    return out;
  }
  querySelector(sel) {
    const r = [];
    this.children.forEach(c => c.find(e => _match(e, sel), r));
    return r[0] || null;
  }
  querySelectorAll(sel) {
    const r = [];
    this.children.forEach(c => c.find(e => _match(e, sel), r));
    return r;
  }
  closest(sel) {
    let n = this;
    while (n) { if (_match(n, sel)) return n; n = n.parent; }
    return null;
  }
  get classList() {
    const self = this;
    const list = () => String(self.attrs.class || '').split(/\s+/).filter(Boolean);
    return {
      add(c) { const s = new Set(list()); s.add(c); self.attrs.class = [...s].join(' '); },
      remove(c) { const s = new Set(list()); s.delete(c); self.attrs.class = [...s].join(' '); },
      contains(c) { return list().includes(c); },
      // 【2026-09-25 补】难度行用 classList.toggle('on', 条件) 切选中态
      toggle(c, force) {
        const has = list().includes(c);
        const want = (force === undefined) ? !has : !!force;
        if (want) this.add(c); else this.remove(c);
        return want;
      },
    };
  }
  // 悬浮条定位 / 尺寸（真实浏览器里是布局算出来的；桩里从 style 反推）
  get offsetLeft() { const v = parseFloat(this.style.left); return isFinite(v) ? v : 0; }
  get offsetTop() { const v = parseFloat(this.style.top); return isFinite(v) ? v : 0; }
  get offsetWidth() { return this._ow || 0; }
  get offsetHeight() { return this._oh || 0; }
}

const _byId = {};
const _domL = {};
global.document = {
  createElementNS: (ns, tag) => new El(tag),
  // meta[name="build"] 查不到 → MY_BUILD = ''，配合 build:'' 不会触发自动 reload
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
global.setInterval = () => 0;
global.location = { reload: () => { } };

// ---------------------------------------------------------------- mock fetch
const REQS = [];
let SNAP_I = null;                  // 最近一次 /api/replay 请求的 i
function mkState(ply, pieces, log) {
  return {
    build: '',                             // '' → poll 不触发 reload
    pieces: pieces,
    status: {
      turn: 1, ply: ply, alive: [1, 2, 3], eliminated: [], annexed: {},
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
    allow_undo: false, undo_per_side: 3, undo_left: { 1: 3, 2: 3, 3: 3 },
    undo_used: { 1: 0, 2: 0, 3: 0 }, can_undo: false,
    chain_limit: null, chain: {}, steps_per_turn: 1, turn_steps: 0,
    human_armies: [], resigned: [],
    agents: { 1: {}, 2: {}, 3: {} },
    log: log || [], legal: [], auto: false, thinking: null,
    elapsed: 0, finished: false, drawn: false, max_ply: 240,
    replay_total: ply
  };
}
const PIECES_LIVE = [
  { pos: '132', kind: 'cannon', army: 1, home: 1 },
  { pos: '238', kind: 'cannon', army: 2, home: 2 },
  { pos: '312', kind: 'rook', army: 3, home: 3 }
];
const PIECES_HIST = [
  { pos: '137', kind: 'cannon', army: 1, home: 1 },
  { pos: '238', kind: 'cannon', army: 2, home: 2 },
  { pos: '312', kind: 'rook', army: 3, home: 3 }
];
const LOG = [
  { type: 'move', army: 1, from: '132', to: '137', ply: 1, reason: '人类接管', captured: null },
  { type: 'move', army: 2, from: '232', to: '118', ply: 2, reason: '估值 +2.3', captured: 'horse' }
];

global.fetch = async function (url, opt) {
  REQS.push({ url: url, opt: opt || {} });
  if (url === '/api/state') {
    return { json: async () => mkState(5, PIECES_LIVE, LOG) };
  }
  if (url === '/api/replay') {
    let body = {};
    try { body = JSON.parse((opt && opt.body) || '{}'); } catch (e) { }
    SNAP_I = body.i;
    return {
      json: async () => ({
        ok: true, i: body.i, total: 5, ply: body.i,
        turn: 1, pieces: PIECES_HIST,
        last: { from: '132', to: '137', army: 1, captured: null }
      })
    };
  }
  return { json: async () => ({ ok: true }) };
};

// ------------------------------------------------------------- 加载被测源码
// 预置悬浮条 DOM（真实页面由 index.html 提供；桩里手工搭好，且必须与
//   `document.getElementById` 返回**同一对象** —— app.js 全程走 $()）。
const _fbar = document.getElementById('floatBar');
const _grip = new El('span');
_grip.attrs.class = 'fb-grip';
_fbar.appendChild(_grip);
['btnBack', 'btnFwd', 'btnLive'].forEach(id => {
  const b = document.getElementById(id);
  b.tag = 'button';                        // 让 closest('button') 能命中（桩默认 tag 带 id）
  _fbar.appendChild(b);
});
eval(fs.readFileSync(path.join(ROOT, 'web', 'board_data.js'), 'utf8'));
eval(fs.readFileSync(path.join(ROOT, 'web', 'board.js'), 'utf8'));
const appSrc = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
eval(appSrc);

(async function main() {
  // ==========================================================================
  sect(1, '① 源码接线：boot() 里确实绑了三个回看按钮 + 悬浮条初始化');

  chk(appSrc.includes("$('btnBack').addEventListener"),
    '源码里存在 `$(\'btnBack\').addEventListener`');
  chk(appSrc.includes("$('btnFwd').addEventListener"),
    '源码里存在 `$(\'btnFwd\').addEventListener`（老师 2026-09-25「再进一步」）');
  chk(appSrc.includes("$('btnLive').addEventListener"),
    '源码里存在 `$(\'btnLive\').addEventListener`');
  chk(/\$\(\s*'btnNew'\s*\)\.addEventListener[\s\S]{0,200}backOffset\s*=\s*0/.test(appSrc),
    '「重开一局」会复位回看位置（backOffset = 0）');
  chk(/function\s+initFloatBar\s*\(/.test(appSrc) && /initFloatBar\s*\(\s*\)\s*;/.test(appSrc),
    '有 initFloatBar() 定义、且在 boot 里被调用');

  // index.html / style.css 静态接线（悬浮条是 2026-09-25 从控制面板抽出来的）
  const htmlSrc = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
  const cssSrc = fs.readFileSync(path.join(ROOT, 'web', 'style.css'), 'utf8');
  chk(htmlSrc.includes('id="floatBar"') && htmlSrc.includes('class="float-bar"'),
    'index.html 里有悬浮条 #floatBar.float-bar');
  ['btnBack', 'btnFwd', 'btnLive'].forEach(id =>
    chk(htmlSrc.includes(`id="${id}"`), `index.html 里有 #${id}`));
  chk(htmlSrc.includes('fb-grip'), 'index.html 里有拖动把手 .fb-grip');
  chk(/再退一步/.test(htmlSrc) && /再进一步/.test(htmlSrc) && /继续下/.test(htmlSrc),
    '三按钮文案齐全（再退一步 / 再进一步 / 继续下）');
  chk(!/class="controls replay-row"/.test(htmlSrc),
    '旧的控制面板内嵌回看行已移除（避免与悬浮条重复）');
  chk(/\.float-bar\s*\{[\s\S]*?position\s*:\s*fixed[\s\S]*?left\s*:\s*12px[\s\S]*?top\s*:\s*12px/.test(cssSrc),
    'style.css 里 .float-bar 默认贴页面左上角（fixed · left/top 12px）');

  // ==========================================================================
  sect(2, '② 真触发 DOMContentLoaded → boot() 跑起来，并首次拉到 state');

  chk((_domL['DOMContentLoaded'] || []).length === 1,
    'DOMContentLoaded 回调已注册 1 个（boot）',
    `实际 ${(_domL['DOMContentLoaded'] || []).length}`);
  (_domL['DOMContentLoaded'] || []).forEach(f => f());
  await sleep(40);

  chk(REQS.some(r => r.url === '/api/state'),
    'boot() 后自动拉取 /api/state');
  chk(_byId['btnBack'] && (_byId['btnBack'].listeners.click || []).length === 1,
    '#btnBack 上已挂 1 个 click 监听',
    `实际 ${((_byId['btnBack'] && _byId['btnBack'].listeners.click) || []).length}`);
  chk(_byId['btnLive'] && (_byId['btnLive'].listeners.click || []).length === 1,
    '#btnLive 上已挂 1 个 click 监听');
  chk(_byId['btnFwd'] && (_byId['btnFwd'].listeners.click || []).length === 1,
    '#btnFwd 上已挂 1 个 click 监听',
    `实际 ${((_byId['btnFwd'] && _byId['btnFwd'].listeners.click) || []).length}`);
  chk(_byId['btnFwd'].disabled === true,
    '在最新局面时「再进一步」禁用（无意义）');
  chk(_byId['btnBack'].disabled === false,
    '有历史（replay_total=5）时「回退一步」可用');

  // ==========================================================================
  sect(3, '③ 点「⏪ 回退一步」→ 真发出 /api/replay，i = total − 1');

  const nBefore = REQS.filter(r => r.url === '/api/replay').length;
  _byId['btnBack'].fire('click');
  await sleep(40);

  const rep = REQS.filter(r => r.url === '/api/replay');
  chk(rep.length === nBefore + 1,
    '点击后**新增** 1 条 /api/replay 请求（说明按钮真的接上了）',
    `${nBefore} → ${rep.length}`);
  chk(SNAP_I === 4, '请求体 i = 5 − 1 = 4（退回一手）', `实际 ${SNAP_I}`);
  chk(rep[rep.length - 1].opt.method === 'POST', '用 POST 调 /api/replay');

  // ==========================================================================
  sect(4, '④ 连点 → i 递减（可一路往前退）');

  _byId['btnBack'].fire('click');
  await sleep(40);
  chk(SNAP_I === 3, '再退一手 → i = 3', `实际 ${SNAP_I}`);
  _byId['btnBack'].fire('click');
  await sleep(40);
  chk(SNAP_I === 2, '再退一手 → i = 2', `实际 ${SNAP_I}`);

  chk(/已退 3/.test(_byId['btnBack'].textContent),
    '按钮文案显示已退手数', `实际 ${_byId['btnBack'].textContent}`);
  chk(_byId['btnLive'].disabled === false,
    '回看中「继续下」变为可用');

  // ==========================================================================
  sect(5, '⑤ 退到开局（i=0）后再点 → 不再发请求');

  for (let k = 0; k < 2; k++) { _byId['btnBack'].fire('click'); await sleep(30); }
  chk(SNAP_I === 0, '已退到 i = 0（开局）', `实际 ${SNAP_I}`);
  const nAtZero = REQS.filter(r => r.url === '/api/replay').length;
  chk(_byId['btnBack'].disabled === true,
    '退到开局后「回退一步」自动禁用');
  _byId['btnBack'].fire('click');
  await sleep(30);
  chk(REQS.filter(r => r.url === '/api/replay').length === nAtZero,
    '禁用状态下再点**不会**再发请求',
    `${nAtZero} → ${REQS.filter(r => r.url === '/api/replay').length}`);

  // ==========================================================================
  sect(6, '⑥ 点「⏩ 继续下」→ 回到最新，按钮状态复位');

  _byId['btnLive'].fire('click');
  await sleep(40);
  chk(_byId['btnLive'].disabled === true,
    '回到最新后「继续下」自动禁用');
  chk(_byId['btnBack'].disabled === false,
    '「回退一步」恢复可用');
  chk(!/已退/.test(_byId['btnBack'].textContent),
    '按钮文案复位为「⏪ 回退一步」', `实际 ${_byId['btnBack'].textContent}`);
  chk(/共 5 手可回看/.test(_byId['replayInfo'].textContent),
    '状态文案显示「共 5 手可回看」', `实际 ${_byId['replayInfo'].textContent}`);

  // ==========================================================================
  sect(7, '⑦ 回看中点击棋盘 → 拒绝走子（不发 /api/move）');

  _byId['btnBack'].fire('click');            // 先进回看
  await sleep(40);
  const nMove0 = REQS.filter(r => r.url === '/api/move').length;
  const board = _byId['board'];
  // ⚠️ 只数「热区图层」（svg 的第 1 个 <g>）。
  //   不能用「所有带 click 的元素」——棋子自身也绑了 click（board.js 里
  //   `g.addEventListener('click', ...)`），会多算当前棋子数（实测 135+3=138）。
  const gs = board.children.filter(c => c.tag === 'g');
  const hits = gs[0] ? gs[0].children : [];
  chk(hits.length === 135, '热区图层有 135 个可点热点（gHits）', `实际 ${hits.length}`);
  chk(board.find(n => n.listeners && n.listeners.click).length === 135 + 3,
    '含棋子自身的 click 共 138 个（135 热区 + 3 棋子）—— 说明棋子也仍可点');
  hits[20].fire('click');
  await sleep(30);
  chk(REQS.filter(r => r.url === '/api/move').length === nMove0,
    '回看中点击**不会**发出 /api/move（只读视图）');
  chk(/回看中/.test(_byId['alerts'].textContent),
    '顶部提示条明确写出「回看中」（不让老师以为点了没反应）',
    `实际 ${String(_byId['alerts'].textContent).slice(0, 60)}`);

  // ==========================================================================
  sect(8, '⑧ 「⏩ 再进一步」→ i 递增（往最新方向，老师 2026-09-25 新增）');

  _byId['btnLive'].fire('click');                 // 先回到最新
  await sleep(30);
  chk(_byId['btnFwd'].disabled === true, '最新局面下「再进一步」禁用');
  for (let k = 0; k < 3; k++) { _byId['btnBack'].fire('click'); await sleep(30); }
  chk(SNAP_I === 2, '连退 3 手 → i = 2（backOffset = 3）', `实际 ${SNAP_I}`);
  chk(_byId['btnFwd'].disabled === false, '回看中「再进一步」变为可用');
  const nF = REQS.filter(r => r.url === '/api/replay').length;
  _byId['btnFwd'].fire('click');
  await sleep(40);
  chk(REQS.filter(r => r.url === '/api/replay').length === nF + 1,
    '点「再进一步」→ 新增 1 条 /api/replay（按钮真的接上了）');
  chk(SNAP_I === 3, 'i = 2 → 3（前进一手）', `实际 ${SNAP_I}`);
  chk(/已退 2/.test(_byId['btnBack'].textContent),
    '「已退 N」随之前进减少到 2', `实际 ${_byId['btnBack'].textContent}`);
  // 继续前进到 backOffset = 1
  _byId['btnFwd'].fire('click'); await sleep(40);
  chk(SNAP_I === 4 && /已退 1/.test(_byId['btnBack'].textContent),
    '再进一手 → i = 4、已退 1', `i=${SNAP_I} txt=${_byId['btnBack'].textContent}`);
  // 从 backOffset=1 前进 → next=0 → 直接回到最新（不再发 /api/replay）
  const nF2 = REQS.filter(r => r.url === '/api/replay').length;
  _byId['btnFwd'].fire('click'); await sleep(40);
  chk(REQS.filter(r => r.url === '/api/replay').length === nF2,
    '前进到最新这一步**不经** /api/replay（直接回最新局面）');
  chk(!/已退/.test(_byId['btnBack'].textContent) && _byId['btnFwd'].disabled === true,
    '回到最新：「已退」消失、「再进一步」重新禁用',
    `txt=${_byId['btnBack'].textContent}`);

  // ==========================================================================
  sect(9, '⑨ 悬浮条：按住拖动 → 位置变化 + 写入 localStorage');

  const bar = _byId['floatBar'];
  chk(!!bar && bar.querySelector('.fb-grip') === _grip,
    '#floatBar 能找到拖动把手 .fb-grip');
  chk(bar.classList.contains('dragging') === false, '初始不在拖动态');
  // 事件落在条体（非交互区）→ 应启动拖动
  bar.fireEvt('pointerdown', { pointerId: 7, clientX: 200, clientY: 100,
                               target: bar, preventDefault() { } });
  chk(bar.classList.contains('dragging') === true,
    '按住条体 → 进入拖动态（dragging 类）');
  (_domL['pointermove'] || []).forEach(f =>
    f({ pointerId: 7, clientX: 260, clientY: 160 }));
  chk(bar.offsetLeft === 60 && bar.offsetTop === 60,
    '拖到 (260,160)：起点偏移 200/100 ⇒ 条移到 (60,60)',
    `实际 (${bar.offsetLeft},${bar.offsetTop})`);
  (_domL['pointerup'] || []).forEach(f => f({ pointerId: 7 }));
  chk(bar.classList.contains('dragging') === false, '松手 → 退出拖动态');
  let saved = null;
  try { saved = JSON.parse(_ls['wb3chess.replayBar.pos'] || 'null'); } catch (e) { }
  chk(!!saved && saved.x === 60 && saved.y === 60,
    '拖动后的位置已写入 localStorage（刷新不跑回原位）', JSON.stringify(saved));

  // ==========================================================================
  sect(10, '⑩ 悬浮条：点按钮不误拖 + 双击把手复位到左上角');

  const posBefore = [bar.offsetLeft, bar.offsetTop];
  // 事件落在按钮上 → 交给按钮，不启动拖动
  bar.fireEvt('pointerdown', { pointerId: 8, clientX: 300, clientY: 300,
                               target: _byId['btnFwd'], preventDefault() { } });
  chk(bar.classList.contains('dragging') === false,
    '在按钮上按下 → **不**启动拖动（不影响按钮自己的 click）');
  (_domL['pointermove'] || []).forEach(f =>
    f({ pointerId: 8, clientX: 500, clientY: 500 }));
  chk(bar.offsetLeft === posBefore[0] && bar.offsetTop === posBefore[1],
    '未拖动状态下移动指针，位置不变',
    `实际 (${bar.offsetLeft},${bar.offsetTop})`);
  // 双击把手 → 复位
  _grip.fire('dblclick');
  chk(bar.offsetLeft === 12 && bar.offsetTop === 12,
    '双击「⠿ 回看」把手 → 复位到页面左上角 (12,12)',
    `实际 (${bar.offsetLeft},${bar.offsetTop})`);
  let saved2 = null;
  try { saved2 = JSON.parse(_ls['wb3chess.replayBar.pos'] || 'null'); } catch (e) { }
  chk(!!saved2 && saved2.x === 12 && saved2.y === 12,
    '复位后的位置也写回 localStorage', JSON.stringify(saved2));

  // ==========================================================================
  console.log('\n' + '='.repeat(74));
  console.log(`合计 ${ok} 通过 / ${bad} 失败`);
  console.log('='.repeat(74));
  process.exit(bad ? 1 : 0);
})();
