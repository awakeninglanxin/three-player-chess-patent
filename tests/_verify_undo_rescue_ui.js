/* 终局自救悔棋 · UI 专项验证（Node + DOM 桩 + mock fetch）

   背景：老师 2026-10-02
     「虽然是游戏结束了，但是魏国还剩一次悔棋机会，
       应该允许魏国退回到将军之前」

   后端放行了（`undo_last` 的终局自救分支 + `snapshot().undo_rescue`），
   但老师**实际看到的是「悔棋键禁止点击」** —— 因为前端 app.js 写死：
       btnU.disabled = !(st.allow_undo && st.can_undo && !st.finished)
   本脚本要钉死的正是这条：终局 + 有可自救方 ⇒ 按钮**必须能点**；
   终局 + 无可自救方 ⇒ 维持禁用（不能把悔棋变成取消终局的万能钥匙）。

   本脚本断言：
     ① 源码接线：读了 st.undo_rescue，disabled 表达式放行「终局但可自救」
     ② ★ 真跑 render：终局 + undo_rescue=1 ⇒ btnUndo.disabled === false
     ③ 终局时 title / 提示条 / 计数条都如实说明"还剩几次、能退回将军之前"
     ④ 终局 + undo_rescue=0 ⇒ 仍禁用；非终局行为不变（回归）
     ⑤ ★★ 真点按钮 ⇒ 发出 POST /api/undo（按钮不是"点亮了却没接线"）

   运行：node tests/_verify_undo_rescue_ui.js
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
let CUR = null;
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
    undo_rescue: 0,
    autosave: true, saved_at: 1790821386, restored: false,
    restored_from: 0, save_error: '',
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

// 用 #btnStep 触发 post → poll → 真拉一次 /api/state 重绘（不带副作用）
async function repaint() {
  const n = REQS.filter(r => r.url === '/api/state').length;
  _byId['btnStep'].fire('click');
  for (let i = 0; i < 20 && REQS.filter(r => r.url === '/api/state').length === n; i++) {
    await sleep(10);
  }
  await sleep(20);
}
const btnU = () => _byId['btnUndo'];
const alerts = () => _byId['alerts'].textContent;

(async function main() {
  // ==========================================================================
  sect(1, '① 源码接线：读了 undo_rescue，按钮放行「终局但可自救」');

  chk(/st\.undo_rescue/.test(appSrc), 'app.js 读了 st.undo_rescue');
  chk(/\(!st\.finished \|\| rescue\)/.test(appSrc),
    '★ disabled 表达式含 `(!st.finished || rescue)`（终局自救时不禁用）');
  chk(/悔棋自救|退回被将军之前/.test(appSrc), 'app.js 有终局自救的提示文案');

  (_domL['DOMContentLoaded'] || []).forEach(f => f());
  await sleep(50);

  // ==========================================================================
  sect(2, '② ★ 真跑 render：终局 + 魏方还剩 1 次 ⇒ 悔棋键**能点**');

  const base = mkState();
  CUR = mkState({
    status: Object.assign({}, base.status, {
      turn: 3, ply: 64, winner: 3, eliminated: [2, 1], out: [2, 1]
    }),
    finished: true, drawn: false, legal: [],
    undo_left: { 1: 1, 2: 3, 3: 3 }, undo_used: { 1: 2, 2: 0, 3: 0 },
    can_undo: true, undo_who: 1, undo_rollback: 2, undo_rescue: 1
  });
  await repaint();

  chk(btnU().disabled === false,
    '★★ btnUndo.disabled === false（终局不再一律禁用 —— 老师要的就是这条）',
    `实际 disabled=${btnU().disabled}`);
  chk(/对局已结束/.test(btnU().title) && /还剩\s*1\s*次/.test(btnU().title),
    '★ title 说明"对局已结束，但还剩几次"', `实际：${btnU().title}`);
  chk(/被将军之前/.test(btnU().title),
    '★ title 说明点下去会"退回被将军之前"', `实际：${btnU().title}`);
  chk(/魏方还剩\s*1\s*次悔棋机会/.test(alerts()),
    '★ 顶部提示条写明魏方还剩 1 次且可退回将军之前', `实际：${alerts()}`);
  chk(/悔棋自救/.test(_byId['undoCnt'].innerHTML),
    '★ 计数条写明「可悔棋自救」', `实际：${_byId['undoCnt'].innerHTML}`);

  // ==========================================================================
  sect(3, '③ 终局但**没有**可自救方 ⇒ 维持禁用（不开后门）');

  CUR = mkState({
    status: Object.assign({}, base.status, {
      turn: 3, ply: 64, winner: 3, eliminated: [2, 1], out: [2, 1]
    }),
    finished: true, und_rescue: 0,
    undo_left: { 1: 0, 2: 0, 3: 3 }, can_undo: false,
    undo_who: null, undo_rollback: 0, undo_rescue: 0
  });
  await repaint();
  chk(btnU().disabled === true,
    '★★ 无可自救方时 btnUndo 仍禁用（判和/超时终局不给悔）',
    `实际 disabled=${btnU().disabled}`);
  chk(!/悔棋自救/.test(_byId['undoCnt'].innerHTML),
    '计数条不再显示自救文案', `实际：${_byId['undoCnt'].innerHTML}`);

  // ==========================================================================
  sect(4, '④ 非终局行为不变（回归）');

  CUR = mkState({ finished: false, undo_rescue: 0, can_undo: true });
  await repaint();
  chk(btnU().disabled === false, '进行中 + 可悔 ⇒ 按钮可点（原行为）',
    `实际 disabled=${btnU().disabled}`);

  CUR = mkState({ finished: false, allow_undo: false, can_undo: true });
  await repaint();
  chk(btnU().disabled === true, '未勾选「允许悔棋」⇒ 禁用（原行为）',
    `实际 disabled=${btnU().disabled}`);

  // ==========================================================================
  sect(5, '⑤ ★★ 真点按钮 ⇒ 确实发出 POST /api/undo（不是"点亮了却没接线"）');

  CUR = mkState({
    status: Object.assign({}, base.status, {
      turn: 3, ply: 64, winner: 3, eliminated: [2, 1], out: [2, 1]
    }),
    finished: true, legal: [],
    undo_left: { 1: 1, 2: 3, 3: 3 }, can_undo: true,
    undo_who: 1, undo_rollback: 2, undo_rescue: 1
  });
  await repaint();
  const n0 = REQS.filter(r => r.url === '/api/undo').length;
  btnU().fire('click');
  await sleep(60);
  const undoReqs = REQS.filter(r => r.url === '/api/undo');
  chk(undoReqs.length === n0 + 1,
    '点击后新增 1 条 POST /api/undo', `实际新增 ${undoReqs.length - n0}`);
  const last = undoReqs[undoReqs.length - 1];
  chk(!!last && last.opt && last.opt.method === 'POST',
    'POST 方法正确', `实际 ${last && last.opt && last.opt.method}`);
  chk(!!last && JSON.parse(last.opt.body || '{}') && true,
    '请求体是可解析的 JSON（不传 army ⇒ 由后端推定被斩方）',
    `实际 ${last && last.opt && last.opt.body}`);

  console.log('\n' + '='.repeat(74));
  console.log(`终局自救悔棋 · UI 专项验证：${ok} 通过 / ${bad} 失败`);
  console.log('='.repeat(74));
  process.exit(bad ? 1 : 0);
})();
