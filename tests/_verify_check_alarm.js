/* 将军告警 UI 专项验证（Node + DOM 桩 + mock fetch + AudioContext 桩）
   —— 锁住「人类方被将军却毫无提示」这类静默 bug。

   老师 2026-09-25 需求：「人类控棋的这方要是被将军，你要有一个提示音和屏幕中心闪现 "将军!!!"」

   本脚本**不**看函数是否存在，而是真跑一遍 app.js：
     · 真触发 DOMContentLoaded → boot()
     · 真点「单步」按钮驱动 poll → render（这是页面上唯一的 render 入口链）
     · 真观察 #checkFlash 的 hidden / class / 文案变化，以及 AudioContext 的振荡器创建次数

   断言清单：
     ① 静态接线：index.html 有 #checkFlash / #checkFlashSub / #btnSound；
        style.css 的 .check-flash 是 fixed 全屏、居中、pointer-events:none、[hidden] 会隐藏
     ② 三方全 Bot（human_armies 为空）被将军 → **不**提醒
     ③ 非人类方被将军 → **不**提醒
     ④ 人类方（蜀）被将军 → 闪现 + 文案「将军!!!」+ 副标题写明谁被谁将 + 真发声
     ⑤ 持续被将军（连续 render）→ **不**重复闪现
     ⑥ 叫将方变化（1 → 1、2）→ 视为新的一次 → 再闪现
     ⑦ 解除后再被将 → 再闪现
     ⑧ 回看中不响；回到最新局面才补响（不吞状态）
     ⑨ 终局不响
     ⑩ 提示音开关：关掉后仍闪现但**不发声**；状态写入 localStorage
     ⑪ 音频解锁：pointerdown / keydown 上挂了一次性 resume
   运行：node tests/_verify_check_alarm.js
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
  if (sel[0] === '.') return String(el.attrs.class || '').split(/\s+/).includes(sel.slice(1));
  if (sel[0] === '#') return el.attrs.id === sel.slice(1);
  return el.tag === sel;
}
function _match(el, sel) {
  return String(sel || '').split(',').some(s => _matchOne(el, s.trim()));
}
class El {
  constructor(tag) {
    this.tag = tag; this.children = []; this.attrs = {};
    this.style = {}; this.listeners = {}; this._text = '';
    this.disabled = false; this.parent = null;
    this.hidden = false;
    this.showCount = 0;              // classList.add('show') 的次数 ⇒「闪了几次」
  }
  setAttribute(k, v) { this.attrs[k] = v; }
  getAttribute(k) { return this.attrs[k]; }
  appendChild(c) { this.children.push(c); c.parent = this; return c; }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  set innerHTML(v) { if (v === '') this.children = []; }
  get innerHTML() { return ''; }
  set textContent(v) { this._text = v; }
  get textContent() { return this._text; }
  fire(t) { (this.listeners[t] || []).forEach(f => f({ target: this, key: 'Enter' })); }
  find(pred, out) {
    out = out || [];
    if (pred(this)) out.push(this);
    this.children.forEach(c => c.find(pred, out));
    return out;
  }
  querySelector(sel) { const r = []; this.children.forEach(c => c.find(e => _match(e, sel), r)); return r[0] || null; }
  // ⚠️ 元素级的 querySelectorAll 必须也提供：app.js 的 render() 里用
  //   `dBox.querySelectorAll('button.diff')` 渲染难度档按钮，桩缺这个方法会
  //   在 render 阶段直接 TypeError（表现为"测试跑到一半崩掉"，不是断言失败）。
  querySelectorAll(sel) { const r = []; this.children.forEach(c => c.find(e => _match(e, sel), r)); return r; }
  closest(sel) { let n = this; while (n) { if (_match(n, sel)) return n; n = n.parent; } return null; }
  get classList() {
    const self = this;
    const list = () => String(self.attrs.class || '').split(/\s+/).filter(Boolean);
    return {
      add(c) {
        const s = new Set(list()); s.add(c); self.attrs.class = [...s].join(' ');
        if (c === 'show') self.showCount++;        // 闪现计数（供"是否重复"断言）
      },
      remove(c) { const s = new Set(list()); s.delete(c); self.attrs.class = [...s].join(' '); },
      contains(c) { return list().includes(c); },
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
  querySelector: () => null,                 // meta[name=build] 查不到 → MY_BUILD='' → 不 reload
  querySelectorAll: () => [],
  getElementById: id => (_byId[id] = _byId[id] || new El('div#' + id)),
  addEventListener: (t, f, o) => { (_domL[t] = _domL[t] || []).push(f); },
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

// ---------------------------------------------------- AudioContext 桩（只数数）
let OSC_COUNT = 0, GAIN_COUNT = 0, RESUME_COUNT = 0;
global.__AC_STATE = 'running';
global.AudioContext = class {
  constructor() { this.destination = {}; this._t = 0; }
  get state() { return global.__AC_STATE; }
  get currentTime() { return (this._t += 0.001); }
  // 真实浏览器里没有用户手势时 resume() 不会真的把 state 变 running —— 桩也这样模拟
  resume() { RESUME_COUNT++; return Promise.resolve(); }
  createOscillator() {
    OSC_COUNT++;
    return {
      type: '', frequency: { value: 0 },
      connect() { }, start() { }, stop() { }
    };
  }
  createGain() {
    GAIN_COUNT++;
    return {
      gain: {
        setValueAtTime() { }, linearRampToValueAtTime() { }, exponentialRampToValueAtTime() { }
      },
      connect() { }
    };
  }
};

// ---------------------------------------------------------------- mock fetch
const REQS = [];
function mkState(ply) {
  return {
    build: '', pieces: PIECES_LIVE, status: {
      turn: 1, ply: ply, alive: [1, 2, 3], eliminated: [], annexed: {},
      winner: null, checks: {}, frozen: [], generals_facing: [], last: [],
      passed: [], deputies: {}, vitality: {}, combat: {}, out: [],
      declared_lose: [], resigned: [], stale_total_rounds: 9,
      steps_per_turn: 1, turn_steps: 0, snipe: [], pending_judge: null,
      only_ele_adv: false, stale_rounds: 0, chain: {}
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
    log: [], legal: [], auto: false, thinking: null,
    elapsed: 0, finished: false, drawn: false, max_ply: 240,
    replay_total: ply
  };
}
const PIECES_LIVE = [
  { pos: '115', kind: 'general', army: 1, home: 1 },
  { pos: '215', kind: 'general', army: 2, home: 2 },
  { pos: '315', kind: 'general', army: 3, home: 3 }
];
const CUR = mkState(5);

global.fetch = async function (url, opt) {
  REQS.push({ url: url, opt: opt || {} });
  if (url === '/api/state') return { json: async () => CUR };
  if (url === '/api/replay') {
    let body = {};
    try { body = JSON.parse((opt && opt.body) || '{}'); } catch (e) { }
    return {
      json: async () => ({
        ok: true, i: body.i, total: 5, ply: body.i, turn: 1, pieces: PIECES_LIVE,
        last: { from: '115', to: '125', army: 1, captured: null }
      })
    };
  }
  return { json: async () => ({ ok: true }) };
};

// ------------------------------------------------------------- 加载被测源码
// 预置真实页面会提供的节点（app.js 全程走 $()，必须与 getElementById 同一对象）
const _flash = document.getElementById('checkFlash');
_flash.hidden = true;                        // 与 index.html 的 hidden 初始态一致
const _flashSub = document.getElementById('checkFlashSub');
const _flashMain = document.getElementById('checkFlashMain');   // ★ 大字（谁被谁将）
const _soundBtn = document.getElementById('btnSound');
_soundBtn.tag = 'button';                    // 让 closest('button') 能命中
const _btnStep = document.getElementById('btnStep');
_btnStep.tag = 'button';
const _btnBack = document.getElementById('btnBack');
_btnBack.tag = 'button';
const _btnFwd = document.getElementById('btnFwd');
_btnFwd.tag = 'button';
const _btnLive = document.getElementById('btnLive');
_btnLive.tag = 'button';
const _fbar = document.getElementById('floatBar');
const _grip = new El('span');
_grip.attrs.class = 'fb-grip';
_fbar.appendChild(_grip);
['btnBack', 'btnFwd', 'btnLive'].forEach(id => _fbar.appendChild(_byId[id]));

eval(fs.readFileSync(path.join(ROOT, 'web', 'board_data.js'), 'utf8'));
eval(fs.readFileSync(path.join(ROOT, 'web', 'board.js'), 'utf8'));
const appSrc = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8');
eval(appSrc);
const htmlSrc = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
const cssSrc = fs.readFileSync(path.join(ROOT, 'web', 'style.css'), 'utf8');

// 驱动一次 render：改 CUR → 点「单步」→ post('/api/step') → poll() → render()
async function tick() {
  _btnStep.fire('click');
  await sleep(40);
}

(async function main() {
  // ==========================================================================
  sect(1, '① 静态接线：DOM 节点 / CSS 层 / 源码关键点');

  chk(htmlSrc.includes('id="checkFlash"') && /class="check-flash"/.test(htmlSrc),
    'index.html 里有告警层 #checkFlash.check-flash');
  chk(htmlSrc.includes('id="checkFlashSub"'), 'index.html 里有副标题 #checkFlashSub');
  // 【2026-10-01 老师改口径】大字不再固定写「将军!!!」，而是由 flashCheck()
  //   写成「X方主帅被Y方将军」。静态 HTML 里那句只是**占位**（首帧不会露出来）。
  //   ⇒ 这里断言"有 #checkFlashMain 这个大字容器"，动态文案交给 §动态小节验。
  chk(/<div class="cf-main" id="checkFlashMain">/.test(htmlSrc),
    '★ 主文案容器 #checkFlashMain 存在（老师 2026-10-01：大字写「X方主帅被Y方将军」）');
  chk(/\shidden[\s>]/.test(htmlSrc.slice(htmlSrc.indexOf('id="checkFlash"'), htmlSrc.indexOf('id="checkFlash"') + 120)),
    '告警层初始 hidden（未将军时不该露出）');
  chk(htmlSrc.includes('id="btnSound"'), 'index.html 里有提示音开关 #btnSound');
  chk(/\.check-flash\s*\{[\s\S]*?position\s*:\s*fixed[\s\S]*?inset\s*:\s*0/.test(cssSrc),
    'style.css 里 .check-flash 是 fixed 全屏（屏幕中心）');
  chk(/\.check-flash\s*\{[\s\S]*?align-items\s*:\s*center[\s\S]*?justify-content\s*:\s*center/.test(cssSrc),
    '.check-flash 用 flex 居中 ⇒ 字确实在页面正中');
  chk(/\.check-flash\s*\{[\s\S]*?pointer-events\s*:\s*none/.test(cssSrc),
    '★ pointer-events:none —— 闪现不挡棋盘点击');
  chk(/\.check-flash\[hidden\]\s*\{\s*display\s*:\s*none/.test(cssSrc),
    '★ 显式写 .check-flash[hidden]{display:none}（否则被 display:flex 盖掉，字会一直挂着）');
  chk(/@keyframes\s+checkPop/.test(cssSrc), '有 checkPop 动画（弹出→停留→淡出）');

  chk(/function\s+checkAlarm\s*\(/.test(appSrc), 'app.js 有 checkAlarm()');
  chk(/checkAlarm\s*\(\s*st\s*,\s*showHist\s*\)/.test(appSrc), 'render() 里真的调用了 checkAlarm(st, showHist)');
  chk(/function\s+playCheckAlarm\s*\(/.test(appSrc), 'app.js 有 playCheckAlarm()');
  chk(/createOscillator/.test(appSrc) && /AudioContext/.test(appSrc),
    '提示音用 Web Audio 现场合成（无音频文件依赖）');
  chk(/wb3chess\.checkAlarm\.sound/.test(appSrc), '提示音开关状态存 localStorage');

  // ==========================================================================
  sect(2, '② boot + 首次 render（人类方为空、无人被将）');

  chk((_domL['DOMContentLoaded'] || []).length === 1, 'DOMContentLoaded 回调已注册 1 个（boot）');
  (_domL['DOMContentLoaded'] || []).forEach(f => f());
  await sleep(40);
  chk(_flash.showCount === 0 && _flash.hidden === true, '开局：没有闪现，告警层仍隐藏');
  chk(_soundBtn.textContent.includes('开'), '#btnSound 初始文案为「开」', `实际 ${_soundBtn.textContent}`);

  // ==========================================================================
  sect(3, '③ 三方全 Bot / 非人类方被将军 → 不打扰');

  CUR.human_armies = [];
  CUR.status.checks = { 3: [1] };
  await tick();
  chk(_flash.showCount === 0, 'human_armies 为空（纯观战）→ 即使有将军也不提醒');

  CUR.human_armies = [1];                       // 人类只接管魏
  CUR.status.checks = { 3: [1] };               // 被将的是蜀（Bot 方）
  await tick();
  chk(_flash.showCount === 0, '被将方不是人类接管的方 → 不提醒');

  // ==========================================================================
  sect(4, '④ 人类方（蜀）被魏将军 → 闪现 + 文案 + 真发声');

  const osc0 = OSC_COUNT;
  CUR.human_armies = [3];
  CUR.status.checks = { 3: [1] };
  await tick();
  chk(_flash.showCount === 1, '★ 新出现的一次将军 ⇒ 闪现 1 次', `实际 ${_flash.showCount}`);
  chk(_flash.hidden === false, '告警层已显示（hidden=false）');
  chk(_flash.classList.contains('show'), '带上了 .show（动画 class）');
  chk(_flashMain.textContent.includes('蜀') && _flashMain.textContent.includes('魏'),
    '★ 大字写明「蜀方主帅被魏方将军」（老师 2026-10-01：这句要显示在屏幕前大字）',
    `实际 ${_flashMain.textContent}`);
  chk(OSC_COUNT > osc0, '★ 真的创建了振荡器（有提示音，不是静默）',
    `${osc0} → ${OSC_COUNT}`);
  chk(OSC_COUNT - osc0 === 6, '三声"铛" × 双层（基音+泛音）= 6 个振荡器', `实际 ${OSC_COUNT - osc0}`);

  // ==========================================================================
  sect(5, '⑤ 持续被将军 → 不重复闪（去重）');

  await tick();
  await tick();
  chk(_flash.showCount === 1, '同一方持续被同一方将 → 仍只闪过 1 次', `实际 ${_flash.showCount}`);

  // ==========================================================================
  sect(6, '⑥ 叫将方变化 → 视为新的一次');

  CUR.status.checks = { 3: [1, 2] };            // 吴也加入叫将
  await tick();
  chk(_flash.showCount === 2, '叫将方由「魏」变为「魏、吴」⇒ 再闪一次', `实际 ${_flash.showCount}`);
  chk(_flashMain.textContent.includes('魏') && _flashMain.textContent.includes('吴'),
    '★ 大字同步为两方叫将', `实际 ${_flashMain.textContent}`);
  chk(_flashSub.textContent.includes('将军'),
    '副标题保留「将军!!!」（老师的原始记忆点，降为小字陪衬）',
    `实际 ${_flashSub.textContent}`);

  // ==========================================================================
  sect(7, '⑦ 解除后再被将 → 再闪');

  CUR.status.checks = {};
  await tick();
  chk(_flash.showCount === 2, '将军解除本身不触发闪现', `实际 ${_flash.showCount}`);
  CUR.status.checks = { 3: [1] };
  await tick();
  chk(_flash.showCount === 3, '★ 解除后再次被将 ⇒ 又闪一次', `实际 ${_flash.showCount}`);

  // ==========================================================================
  sect(8, '⑧ 回看中不响；回到最新局面才补响（不吞状态）');

  CUR.human_armies = [1];
  CUR.status.checks = { 1: [2] };               // 魏（人类）被吴将 —— 全新的一次
  _btnBack.fire('click');                       // 进入回看（backOffset=1）
  await sleep(40);
  const n1 = _flash.showCount;
  chk(n1 === 3, '进入回看那一刻不响（回看是只读视图）', `实际 ${n1}`);
  await tick();                                 // 回看中继续 render
  chk(_flash.showCount === 3, '★ 回看期间即使发生将军也不闪烁', `实际 ${_flash.showCount}`);
  _btnLive.fire('click');                       // 回到最新局面
  await sleep(40);
  chk(_flash.showCount === 4, '★ 回到最新局面后立刻补响（没有把状态吞掉）', `实际 ${_flash.showCount}`);

  // ==========================================================================
  sect(9, '⑨ 终局不响');

  CUR.status.checks = {};
  await tick();
  CUR.finished = true;
  CUR.status.checks = { 1: [2] };
  await tick();
  chk(_flash.showCount === 4, '终局局面不响铃', `实际 ${_flash.showCount}`);
  CUR.finished = false;

  // ==========================================================================
  sect(10, '⑩ 提示音开关：关掉后仍闪但不发声');

  _soundBtn.fire('click');                      // 开 → 关
  chk(_soundBtn.textContent.includes('关'), '按钮文案切到「关」', `实际 ${_soundBtn.textContent}`);
  chk(_ls['wb3chess.checkAlarm.sound'] === '0', '开关状态写入 localStorage（刷新后保持）',
    `实际 ${_ls['wb3chess.checkAlarm.sound']}`);
  const osc1 = OSC_COUNT, sc1 = _flash.showCount;
  CUR.status.checks = {}; await tick();
  CUR.status.checks = { 1: [2] }; await tick();
  chk(_flash.showCount === sc1 + 1, '关掉声音后「闪现」照旧', `${sc1} → ${_flash.showCount}`);
  chk(OSC_COUNT === osc1, '★ 关掉声音后**不再创建振荡器**（真的静音了）',
    `${osc1} → ${OSC_COUNT}`);

  // ==========================================================================
  sect(11, '⑪ autoplay 拦截 + 音频解锁 + 无人接管时不打扰');

  chk((_domL['pointerdown'] || []).length >= 1, 'document 上挂了 pointerdown 解锁回调');
  chk((_domL['keydown'] || []).length >= 1, 'document 上挂了 keydown 解锁回调');

  // 模拟「老师从头到尾没点过页面」→ AudioContext 被 autoplay 策略压在 suspended
  _soundBtn.fire('click');                      // 先把 §10 关掉的提示音重新打开
  chk(_soundBtn.textContent.includes('开') && _ls['wb3chess.checkAlarm.sound'] === '1',
    '再点一次开关 → 恢复「开」并回写 localStorage', `实际 ${_soundBtn.textContent}`);
  global.__AC_STATE = 'suspended';
  CUR.human_armies = [1];
  CUR.status.checks = {};
  await tick();
  const sc3 = _flash.showCount, osc2 = OSC_COUNT;
  CUR.status.checks = { 1: [2] };
  await tick();
  chk(_flash.showCount === sc3 + 1, '★ 未解锁时**仍然闪屏**（视觉提醒不受 autoplay 限制）',
    `${sc3} → ${_flash.showCount}`);
  chk(OSC_COUNT === osc2, '未解锁时不发声（不抛异常、也不静默吞掉）', `${osc2} → ${OSC_COUNT}`);
  chk(/拦截/.test(String(_byId['alerts'].textContent || '')),
    '提示条明确告知原因（点一下页面即可开启）',
    `实际 ${String(_byId['alerts'].textContent).slice(0, 80)}`);

  const r0 = RESUME_COUNT;
  (_domL['pointerdown'] || []).forEach(f => f());
  chk(RESUME_COUNT > r0, '★ 用户一点页面就 resume AudioContext（否则浏览器不许发声）',
    `${r0} → ${RESUME_COUNT}`);
  global.__AC_STATE = 'running';

  CUR.human_armies = [];                        // 三方全 Bot
  const sc2 = _flash.showCount;
  CUR.status.checks = { 1: [2], 3: [1] };
  await tick();
  chk(_flash.showCount === sc2, 'human_armies 清空后再有将军也不提醒');

  // ==========================================================================
  console.log('\n' + '='.repeat(74));
  console.log(`将军告警专项验证：${ok} 通过 / ${bad} 失败`);
  console.log('='.repeat(74));
  process.exit(bad ? 1 : 0);
}());
