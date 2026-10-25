/* 续局提示 UI 专项验证（Node + DOM 桩 + mock fetch）

   背景：老师 2026-10-01「如何设计能否重启网页后继续之前的棋局继续下？」
   后端每手落盘 + 启动恢复已实现；但**前端必须明说"这是接着上次那局"**——
   否则老师打开页面看到棋盘上已经有 44 手，会以为程序出错了（或以为棋局被谁动过）。

   本脚本断言：
     ① 源码接线：app.js 里有 resumeShown / fmtTime / 「已恢复上次对局」文案
     ② restored=true 时首屏提示出现，含「存档于 MM-DD HH:MM」与「第 N 手」
     ③ ★ 只提示一次（第二次 render 不再塞进提示条，不长期占位）
     ④ restored=false 时不提示（正常新局）
     ⑤ 悔棋新口径：按钮 title / 计数条写明「连带退回 N 手、只扣自己」
     ⑥ 无 restored_from（老后端）时不崩、不提示

   运行：node tests/_verify_resume_ui.js
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
  // ⚠️ 本桩的 getter **返回原始串**（与浏览器一致）：本节要断言的
  //   `#undoCnt` 里那段「下一次悔棋：…」是 innerHTML 拼出来的纯文本，
  //   若 getter 恒返回 ''（早期几个桩的写法），就**读不到任何东西**，
  //   断言会永远失败 —— 那不是被测代码的错，是桩的错。
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
  set dataset(o) { Object.keys(o || {}).forEach(k => { this.attrs['data-' + k] = o[k]; }); }
  set textContent(v) { this._text = v; }
  get textContent() { return this._text; }
  fire(t) { (this.listeners[t] || []).forEach(f => f({ target: this, key: 'Enter' })); }
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
      toggle(c, force) {
        const has = list().includes(c);
        const want = (force === undefined) ? !has : !!force;
        if (want) this.add(c); else this.remove(c);
        return want;
      },
    };
  }
  get offsetLeft() { const v = parseFloat(this.style.left); return isFinite(v) ? v : 0; }
  get offsetTop() { const v = parseFloat(this.style.top); return isFinite(v) ? v : 0; }
  get offsetWidth() { return this._ow || 0; }
  get offsetHeight() { return this._oh || 0; }
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
global.setInterval = () => 0;
global.location = { reload: () => { } };

// ---------------------------------------------------------------- mock fetch
const REQS = [];
let CUR = null;                     // 当前被返回的 state（测试可改）
function mkState(over) {
  return Object.assign({
    build: '',
    pieces: [{ pos: '132', kind: 'cannon', army: 1, home: 1 }],
    status: {
      turn: 1, ply: 12, alive: [1, 2, 3], eliminated: [], annexed: {},
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
    allow_undo: true, undo_per_side: 3, undo_left: { 1: 2, 2: 3, 3: 3 },
    undo_used: { 1: 1, 2: 0, 3: 0 }, can_undo: true,
    undo_who: 1, undo_rollback: 3,
    autosave: true, saved_at: 1790821386, restored: true,
    restored_from: 1790821386, save_error: '',
    chain_limit: null, chain: {}, steps_per_turn: 1, turn_steps: 0,
    human_armies: [1], resigned: [],
    agents: { 1: {}, 2: {}, 3: {} },
    log: [], legal: [], auto: false, thinking: null,
    elapsed: 0, finished: false, drawn: false, max_ply: 240,
    replay_total: 12
  }, over || {});
}
CUR = mkState();

global.fetch = async function (url, opt) {
  REQS.push({ url: url, opt: opt || {} });
  if (url === '/api/state') return { json: async () => CUR };
  return { json: async () => ({ ok: true }) };
};

// ------------------------------------------------------------- 加载被测源码
const _fbar = document.getElementById('floatBar');
const _grip = new El('span');
_grip.attrs.class = 'fb-grip';
_fbar.appendChild(_grip);
['btnBack', 'btnFwd', 'btnLive'].forEach(id => {
  const b = document.getElementById(id);
  b.tag = 'button';
  _fbar.appendChild(b);
});
eval(fs.readFileSync(path.join(ROOT, 'web', 'board_data.js'), 'utf8'));
eval(fs.readFileSync(path.join(ROOT, 'web', 'board.js'), 'utf8'));
const appSrc = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
eval(appSrc);

(async function main() {
  const alerts = () => _byId['alerts'].textContent;

  // ==========================================================================
  sect(1, '① 源码接线：resumeShown / fmtTime / 文案');

  chk(/let\s+resumeShown\s*=\s*false/.test(appSrc),
    'app.js 有 `let resumeShown = false`（首屏只提示一次的闸门）');
  chk(/function\s+fmtTime\s*\(/.test(appSrc), 'app.js 有 fmtTime() 时间格式化');
  chk(/已恢复上次对局/.test(appSrc), 'app.js 有「已恢复上次对局」文案');
  chk(/st\.restored\s*&&\s*st\.restored_from/.test(appSrc),
    '触发条件是 `st.restored && st.restored_from`（缺一不显示）');
  chk(/想从头下/.test(appSrc) && /重开一局/.test(appSrc),
    '提示里告诉老师怎么开新局（否则他不知道怎么从头下）');

  // ==========================================================================
  sect(2, '② 真跑 boot → 首屏出现续局提示（含存档时间与手数）');

  chk((_domL['DOMContentLoaded'] || []).length === 1,
    'DOMContentLoaded 回调已注册 1 个（boot）');
  (_domL['DOMContentLoaded'] || []).forEach(f => f());
  await sleep(50);

  const a1 = alerts();
  chk(/已恢复上次对局/.test(a1), '★ 提示条出现「已恢复上次对局」', `实际：${a1}`);
  chk(/存档于\s*10-01\s*10:23/.test(a1),
    '★ 写明存档时间（1790821386 → 10-01 10:23，MM-DD HH:MM）', `实际：${a1}`);
  chk(/第\s*12\s*手/.test(a1), '★ 写明恢复到了第几手', `实际：${a1}`);
  chk(/重开一局/.test(a1), '提示里给出「重开一局」的指引');

  // ==========================================================================
  sect(3, '③ ★ 只提示一次：下一次 render 不再占位');

  // ⚠️ 用 #btnUndo 触发，**不要**用 #btnLive：
  //   goLive() 只做 `render(state)`，用的是**上一次 poll 缓存的对象**
  //   （改 CUR 不会生效，因为它返回的是新对象）⇒ 断言会测到旧数据。
  //   #btnUndo → post() → poll() → 真拉一次 /api/state ✓
  const n1 = REQS.filter(r => r.url === '/api/state').length;
  _byId['btnUndo'].fire('click');
  await sleep(60);
  chk(REQS.filter(r => r.url === '/api/state').length > n1,
    '确实又拉了一次 /api/state 并重绘（否则下面这条断言无意义）');
  chk(!/已恢复上次对局/.test(alerts()),
    '★★ 第二次 render **不再**出现续局提示（不长期占着提示条）',
    `实际：${alerts()}`);

  // ==========================================================================
  sect(4, '④ restored=false（正常新局）→ 不提示');

  CUR = mkState({ restored: false, restored_from: null });
  _byId['btnUndo'].fire('click');
  await sleep(60);
  chk(!/已恢复上次对局/.test(alerts()),
    '新局不提示续局（不会误报）', `实际：${alerts()}`);

  // ==========================================================================
  sect(5, '⑤ 悔棋新口径：按钮提示写明「连带退回 N 手、只扣自己」');

  CUR = mkState();
  _byId['btnUndo'].fire('click');
  await sleep(60);
  const btnU = _byId['btnUndo'];
  chk(btnU && /连带退回/.test(btnU.title || ''),
    '★ 按钮 title 写明「连带退回」（不是旧的"撤回最后一步"）', `实际：${btnU.title}`);
  chk(/只扣魏方\s*1\s*次/.test(btnU.title || ''),
    '★ title 写明「只扣魏方 1 次」（老师口径的核心）', `实际：${btnU.title}`);
  const uc = _byId['undoCnt'].innerHTML;
  chk(/下一次悔棋/.test(uc) && /回到魏方上次落子前/.test(uc),
    '★ 计数条预告「下一次悔棋：回到魏方上次落子前」', `实际：${uc}`);
  chk(/连带退回\s*2\s*手/.test(uc),
    '预告的"连带退回手数" = 总手数 − 1 = 2', `实际：${uc}`);

  // 单步（rollback=1）时不显示"连带"，避免噪音
  CUR = mkState({ undo_rollback: 1, undo_who: 1 });
  _byId['btnUndo'].fire('click');
  await sleep(60);
  chk(!/连带退回/.test(_byId['btnUndo'].title || ''),
    '单步悔棋（rollback=1）不说"连带"，提示不啰嗦',
    `实际：${_byId['btnUndo'].title}`);
  chk(!/下一次悔棋/.test(_byId['undoCnt'].innerHTML),
    '单步时不显示预告文案', `实际：${_byId['undoCnt'].innerHTML}`);

  // ==========================================================================
  sect(6, '⑥ 老后端（无 restored_from 字段）→ 不崩、不提示');

  CUR = mkState({ restored: true, restored_from: null });
  let threw = '';
  try {
    _byId['btnUndo'].fire('click');
    await sleep(60);
  } catch (e) { threw = String(e); }
  chk(threw === '', '不抛异常', `实际：${threw}`);
  chk(!/已恢复上次对局/.test(alerts()), '无 restored_from ⇒ 不提示', `实际：${alerts()}`);

  // ==========================================================================
  console.log('\n' + '='.repeat(74));
  console.log(`续局提示专项验证：${ok} 通过 / ${bad} 失败`);
  console.log('='.repeat(74));
  process.exit(bad ? 1 : 0);
})();
