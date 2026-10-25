/* 每方主控（本地Bot / API 大模型）· UI 专项验证（Node + DOM 桩 + mock fetch）

   老师 2026-10-02 原话：
     「有没有可能选择让魏国给人类，另外两个接入 deepseek 和 hy4 api？」
     「做成可选的选项，用本地 bot 或者 api」

   本脚本守四条线：
     ★ **不落子**（红线）：这条链路只允许出现 `/api/seat`，**绝不允许** /api/move、
       /api/undo、/api/new —— 换主控是"换个脑子"，不是"替老师走棋"。
     ★ **看得见**：三个下拉（魏/吴/蜀）真的被后端下发的目录填满，且**选中态回显**；
       选了 API 的席位加金边（一眼看出哪几方不受难度档影响）。
     ★ **点不动就是点不动**：未配置的 API 条目（缺 url/密钥，例如 HY4）必须
       `disabled` + 文案写明「（未配置）」—— 老师最烦"选了没反应"。
     ★ **不瞎重建**：`/api/state` 每 ~800ms 一帧，选项没变时**不许**重建 <option>
       （重建会把正在展开的下拉打断、丢焦点）。

   运行：node tests/_verify_seat_ui.js
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
  set innerHTML(v) { this._html = String(v == null ? '' : v); this.children = []; }
  get innerHTML() { return this._html || ''; }
  get childElementCount() { return this.children.length; }
  /* ★ 真实的 <option> 用 `el.title` / `el.disabled` / `el.dataset.x`；
     桩必须**忠实**，否则"设了却读不到"会被误判成产品 bug。
     · className ⇄ attrs.class（app.js 用 `si.className = 'undocnt on'` 高亮）
     · dataset 用 Proxy：读时从 attrs 现算，写时落回 attrs['data-*'] */
  set className(v) { this.attrs.class = String(v == null ? '' : v); }
  get className() { return this.attrs.class || ''; }
  get dataset() {
    const self = this, out = {};
    Object.keys(this.attrs).forEach(k => {
      if (k.startsWith('data-')) {
        out[k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = this.attrs[k];
      }
    });
    return new Proxy(out, {
      get(t, k) { return t[k]; },
      set(_, k, v) { self.attrs['data-' + k] = String(v); out[k] = String(v); return true; },
    });
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
      toggle(c, on) { if (on === undefined) { list().includes(c) ? this.remove(c) : this.add(c); } else if (on) { this.add(c); } else { this.remove(c); } },
    };
  }
  get offsetLeft() { return 0; }
  get offsetTop() { return 0; }
  get offsetWidth() { return 0; }
  get offsetHeight() { return 0; }
}

/* ★ <select> 必须真实现 value / selectedOptions —— 否则"选中态回显"根本测不了
   （只测到"DOM 里有 option"，漏掉"到底选中了哪一个"这一层）。 */
class Sel extends El {
  constructor() { super('select'); this._val = ''; }
  get value() { return this._val; }
  set value(v) { this._val = String(v); }
  get selectedOptions() {
    // ⚠️ 必须搜**后代**：API 那些 option 挂在 <optgroup> 底下，不是 select 的直接子节点。
    //    只搜直接子节点 ⇒ 选了 API 也读不到 ⇒ `api` 金边永远加不上（假失败）。
    const hit = this.querySelectorAll('option').filter(c => String(c.value) === String(this._val));
    return hit.length ? [hit[0]] : [];
  }
}

const _byId = {};
const _domL = {};
/* 三个下拉：由**测试自己**建好塞进 DOM（app.js 靠 `select.seatSel` 找它们） */
const sels = [1, 2, 3].map(k => {
  const s = new Sel();
  s.attrs.class = 'seatSel';
  s.attrs['data-army'] = String(k);
  return s;
});
global.document = {
  createElementNS: (ns, tag) => new El(tag),
  createElement: (tag) => new El(tag),          // ★ app.js 用 createElement 建 <option>
  querySelector: () => null,
  querySelectorAll: (sel) => {
    const wanted = String(sel || '').split(',').map(x => x.trim());
    if (wanted.includes('select.seatSel')) return sels;
    return [];
  },
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
let POLL = null;
global.setInterval = (f) => { POLL = f; return 0; };   // 不自动轮询，测试自己拨
global.location = { reload: () => { } };

// ---------------------------------------------------------------- mock fetch
const REQS = [];
let CUR = null;
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
    difficulty: 2,
    difficulty_meta: { level: 2, name: '入门', plies: 3, brief: '3 plies', desc: 'x' },
    difficulty_levels: [], difficulty_skipped: [],
    actual_plies: { 1: 3, 2: 3, 3: 3 },
    difficulty_skipped: [],
    seats: { 1: '__search__', 2: '__search__', 3: '__search__' },
    seat_options: {
      local: [{ id: '__search__', label: '本地Bot · 搜索', brief: '3 plies', kind: 'local', local: true, ready: true, why: '' }],
      api: [
        { id: 'deepseek-v4-flash', label: 'DeepSeek-V4-Flash', brief: '≈28s/步', kind: 'api', local: false, ready: true, why: '' },
        { id: 'hy4', label: 'HY4', brief: '待配置', kind: 'api', local: false, ready: false, why: '未配置接口地址：请在 agents.json 里补 url' },
      ],
    },
    agents: { 1: {}, 2: {}, 3: {} },
    log: [], legal: [], auto: false, thinking: null,
    elapsed: 0, finished: false, drawn: false, max_ply: 300,
    replay_total: 30
  }, over || {});
}
CUR = mkState();

global.fetch = async function (url, opt) {
  REQS.push({ url: url, opt: opt || {}, body: (opt || {}).body });
  if (url === '/api/state') return { json: async () => CUR };
  return { json: async () => ({ ok: true }) };
};
const reqCount = u => REQS.filter(r => r.url === u).length;
const reqBody = u => {
  const r = REQS.filter(x => x.url === u).pop();
  try { return JSON.parse((r && r.body) || '{}'); } catch (e) { return {}; }
};
const FORBIDDEN = ['/api/move', '/api/undo', '/api/new', '/api/resign',
  '/api/takeover', '/api/step', '/api/difficulty',
  '/api/human_config', '/api/rule_config', '/api/discard_save', '/api/hint'];

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
const cssSrc = fs.readFileSync(path.join(ROOT, 'web', 'style.css'), 'utf8');
eval(appSrc);

const opts = (s) => s.querySelectorAll('option');
const optByVal = (s, v) => opts(s).find(o => String(o.value) === v);
const optgroups = (s) => s.children.filter(c => c.tag === 'optgroup');

(async function main() {
  // ==========================================================================
  sect(1, '① 源码接线：三个下拉 + `#seatInfo` + 只打 /api/seat');

  chk(/id="seatInfo"/.test(htmlSrc), 'index.html 有 `#seatInfo`（当前席位说明位）');
  chk((htmlSrc.match(/class="seatSel"/g) || []).length === 3,
    '★ index.html 有**三个** `select.seatSel`（魏 / 吴 / 蜀）',
    `实测 ${(htmlSrc.match(/class="seatSel"/g) || []).length} 个`);
  chk(/class="seatSel" data-army="1"/.test(htmlSrc)
    && /class="seatSel" data-army="2"/.test(htmlSrc)
    && /class="seatSel" data-army="3"/.test(htmlSrc),
    '三个下拉各自带 `data-army="1|2|3"`（**按属性查，不按索引** —— 铁律）');
  chk(/每方主控/.test(htmlSrc), '页面上有「每方主控」这一行');
  chk(/本地 bot 或者 api|用本地 bot 或者 api/.test(htmlSrc) || /本地Bot/.test(htmlSrc),
    '页面 tooltip 写明「本地 Bot 或 API」两种选择');
  chk(/不受难度档影响/.test(htmlSrc),
    '★ 页面写明「API 那方不受难度档影响」（否则老师会以为切难度坏了）');
  chk(/置灰|灰的/.test(htmlSrc), '页面写明未配置的条目不置灰可点（"灰的"）');
  chk(/\.seat-row/.test(cssSrc) && /seatSel/.test(cssSrc), 'style.css 有 `.seat-row` / `.seatSel` 样式');
  chk(/select\.seatSel\.api/.test(cssSrc) || /\.seatSel\.api/.test(cssSrc),
    'style.css 给"该席是 API"的下拉加了区分样式（金边）');

  chk(/querySelectorAll\('select\.seatSel'\)/.test(appSrc),
    'app.js 按 class `select.seatSel` 找下拉（不按索引）');
  chk(/post\('\/api\/seat'/.test(appSrc), 'app.js 只打 `/api/seat`');
  chk(/createElement\('option'\)/.test(appSrc) && /createElement\('optgroup'\)/.test(appSrc),
    '★ 用 createElement 建 option / optgroup（不用 innerHTML 拼字符串 ⇒ 不用操心转义）');
  chk(/let seatSig = '';/.test(appSrc) && /sig !== seatSig/.test(appSrc),
    '★ 有选项签名 `seatSig`：选项没变就不重建 DOM（否则每 800ms 重建一次）');
  chk(/op\.disabled = true/.test(appSrc),
    '★ 未就绪的条目 `op.disabled = true`（点不动就是点不动）');
  chk(/o\.ready \? '' : '（未配置）'/.test(appSrc) || /（未配置）/.test(appSrc),
    '★ 未就绪的条目文案写明「（未配置）」');
  // 「已停用（欠费/下线）」和「未配置（你还没填 url/密钥）」**修法完全不同**：
  //   前者要么充钱要么等厂商恢复，后者是自己补配置。文案混成一句会让老师白折腾。
  chk(/o\.disabled \? '（已停用）'/.test(appSrc),
    '★ 源码里「已停用」与「未配置」是**两句不同文案**（原因不同、修法不同）');
  chk(/setAttribute\('data-kind', o\.kind\)/.test(appSrc) && /classList\.toggle\('api'/.test(appSrc),
    '选中项是 API 时给下拉加 `api` class（金边）；kind 用 setAttribute 落盘');

  // ==========================================================================
  sect(2, '② 下拉真的被后端目录填满（本地在前，API 包在 optgroup 里）');

  chk((_domL['DOMContentLoaded'] || []).length === 1, 'DOMContentLoaded 已注册 boot');
  _ls['wb3chess.autoHint'] = '0';                 // 关掉自动推荐，隔离夹具
  (_domL['DOMContentLoaded'] || []).forEach(f => f());
  await sleep(40);
  chk(reqCount('/api/state') >= 1, 'boot 后已拉到一次 /api/state');
  chk(!!POLL, '轮询函数已注册（测试自己拨）');

  chk(sels.every(s => opts(s).length === 3),
    '★ 三个下拉各有 3 项（1 本地 + 2 API）', sels.map(s => opts(s).length).join('/'));
  chk(sels.every(s => opts(s)[0].value === '__search__'),
    '本地 Bot 排在最前（默认项，一打开就是它）');
  chk(sels.every(s => optgroups(s).length === 1 && optgroups(s)[0].label === 'API 大模型'),
    '★ API 项包在 `<optgroup label="API 大模型">` 里（分组，不混在一起）',
    JSON.stringify(optgroups(sels[0]).map(g => g.label)));
  chk(sels.every(s => opts(s).map(o => o.value).join(',')
    === '__search__,deepseek-v4-flash,hy4'),
    '选项内容 = 本地 → DeepSeek → HY4（顺序稳定）',
    opts(sels[0]).map(o => o.value).join(','));

  // ==========================================================================
  sect(3, '③ 选中态回显：后端说谁在用哪个模型，下拉就必须停在那一项');

  CUR = mkState({ seats: { 1: '__search__', 2: '__search__', 3: 'deepseek-v4-flash' } });
  await POLL(); await sleep(10);

  chk(sels[2].value === 'deepseek-v4-flash',
    '★ 蜀方下拉停在 `deepseek-v4-flash`（= 后端 seats["3"]）', sels[2].value);
  chk(sels[0].value === '__search__' && sels[1].value === '__search__',
    '魏/吴两方仍停在本地 Bot');
  chk(sels[2].classList.contains('api'),
    '★ 蜀方下拉带 `api` class ⇒ 金边（一眼看出这方不受难度档影响）');
  chk(!sels[0].classList.contains('api'), '魏方下拉**没有** `api` class');

  // ==========================================================================
  sect(4, '④ 未配置的条目：disabled + 「（未配置）」，且**不可能是**当前选中项');

  const hyOp = optByVal(sels[0], 'hy4');
  chk(!!hyOp && hyOp.disabled === true,
    '★ HY4 那一项 `disabled`（缺 url/密钥 ⇒ 点不动）');
  chk(!!hyOp && /（未配置）/.test(hyOp.textContent || ''),
    '★ HY4 文案带「（未配置）」', (hyOp && hyOp.textContent) || '');
  chk(!!hyOp && /未配置接口地址/.test(hyOp.title || ''),
    '★ 悬停提示**写明缺什么**（不是笼统"不可用"）', (hyOp && hyOp.title) || '');
  const dsOp = optByVal(sels[0], 'deepseek-v4-flash');
  chk(!!dsOp && !dsOp.disabled, 'DeepSeek 那一项**可点**（密钥已就绪）');
  chk(!opts(sels[0]).some(o => o.value === sels[0].value && o.disabled),
    '当前选中项**不是** disabled 项（否则页面会"显示选了却不能选"）');

  // ==========================================================================
  sect(5, '⑤ 真触发 change ⇒ 只发一条 `POST /api/seat`，请求体按 data-army 取军号');

  const n0 = reqCount('/api/seat');
  const nForb = FORBIDDEN.map(u => reqCount(u));
  sels[1].value = 'deepseek-v4-flash';
  sels[1].fire('change');
  await sleep(30);

  chk(reqCount('/api/seat') === n0 + 1, '★ change 后**恰好**新增 1 条 /api/seat',
    `+${reqCount('/api/seat') - n0}`);
  const b5 = reqBody('/api/seat');
  chk(b5.army === 2 && b5.model_id === 'deepseek-v4-flash',
    '★ 请求体 = {army:2, model_id:"deepseek-v4-flash"}（按 `data-army` 取，不按索引）',
    JSON.stringify(b5));

  // ==========================================================================
  sect(6, '⑥ 只读/禁区红线：换主控**从不**落子、不悔棋、不开新局');

  chk(FORBIDDEN.every((u, i) => reqCount(u) === nForb[i]),
    '★ 整条链路没有发出任何 /api/move · /api/undo · /api/new · /api/resign …（换脑子≠替人走棋）',
    FORBIDDEN.filter((u, i) => reqCount(u) !== nForb[i]).join(',') || '无越界');

  // ==========================================================================
  sect(7, '⑦ `#seatInfo` 如实汇报当前席位（含"N 席为大模型"）');

  CUR = mkState({
    seats: { 1: '__search__', 2: 'deepseek-v4-flash', 3: 'hy4' },
    human_armies: [1],
  });
  await POLL(); await sleep(10);
  const info = _byId['seatInfo'];
  chk(/魏＊?=本地Bot/.test(info.textContent || ''),
    '`#seatInfo` 写明魏方 = 本地Bot', info.textContent);
  chk(/吴=DeepSeek-V4-Flash/.test(info.textContent || ''),
    '`#seatInfo` 写明吴方 = DeepSeek-V4-Flash');
  chk(/蜀=HY4/.test(info.textContent || ''),
    '`#seatInfo` 写明蜀方 = HY4（**如实回显**，即使它现在未配置）');
  chk(/2 席为大模型，不受难度档影响/.test(info.textContent || ''),
    '★ 汇总「2 席为大模型，不受难度档影响」', info.textContent);
  chk(info.classList.contains('on'), '有 API 席位时 `#seatInfo` 高亮（`.on`）');
  chk(/＊/.test(info.textContent || '') && /人类接管/.test(info.textContent || ''),
    '★ 人类接管的席位带 `＊` 并有图例说明（该席主控只是备用）', info.textContent);

  // ==========================================================================
  sect(8, '⑧ 选项没变 ⇒ **不重建** DOM（否则每 800ms 打断一次老师正在展开的下拉）');

  const refBefore = opts(sels[0])[0];
  await POLL(); await POLL(); await POLL(); await sleep(10);
  const refAfter = opts(sels[0])[0];
  chk(refBefore === refAfter,
    '★ 连拉 3 帧后，<option> **还是同一个对象** ⇒ 没有重建（seatSig 生效）');
  chk(sels[0].children.length === 2,
    '下拉结构不变（1 个本地 option + 1 个 optgroup）', `children=${sels[0].children.length}`);

  // ==========================================================================
  sect(9, '⑨ 选项**变了**才重建：HY4 配好之后立刻可选');

  CUR = mkState({
    seats: { 1: '__search__', 2: '__search__', 3: '__search__' },
    seat_options: {
      local: [{ id: '__search__', label: '本地Bot · 搜索', brief: '3 plies', kind: 'local', local: true, ready: true, why: '' }],
      api: [
        { id: 'deepseek-v4-flash', label: 'DeepSeek-V4-Flash', brief: '≈28s/步', kind: 'api', local: false, ready: true, why: '' },
        { id: 'hy4', label: 'HY4', brief: '≈12s/步', kind: 'api', local: false, ready: true, why: '' },
      ],
    },
  });
  await POLL(); await sleep(10);
  const ref2 = opts(sels[0])[0];
  chk(ref2 !== refAfter, '★ 目录变化 ⇒ DOM **重建**（旧 option 对象已被替换）');
  const hy2 = optByVal(sels[0], 'hy4');
  chk(!!hy2 && !hy2.disabled, '★ HY4 配好后 `disabled` 消失 ⇒ 老师在网页上直接就能选',
    `disabled=${hy2 && hy2.disabled}`);
  chk(!!hy2 && !/（未配置）/.test(hy2.textContent || ''), '「（未配置）」文案也消失',
    (hy2 && hy2.textContent) || '');
  chk(!!hy2 && /≈12s\/步/.test(hy2.textContent || ''), 'brief 跟着目录更新（≈12s/步）',
    (hy2 && hy2.textContent) || '');
  sels[2].value = 'hy4';
  sels[2].fire('change');
  await sleep(20);
  chk(reqBody('/api/seat').model_id === 'hy4' && reqBody('/api/seat').army === 3,
    '★ 选 HY4 后请求体 = {army:3, model_id:"hy4"}', JSON.stringify(reqBody('/api/seat')));

  // ==========================================================================
  sect(10, '⑩ 目录为空/后端老版本时不崩（向后兼容）');

  CUR = mkState({ seats: {}, seat_options: {} });
  let threw = '';
  try { await POLL(); await sleep(10); } catch (e) { threw = String(e && e.message); }
  chk(!threw, '★ 老后端（没有 seat_options 字段）时 render 不抛异常', threw);
  chk(sels[0].value === '' || sels[0].value === '__search__' || sels[0].value === 'deepseek-v4-flash'
    || sels[0].value === 'hy4',
    '下拉没有崩坏（值仍是合法字符串）', `value=${JSON.stringify(sels[0].value)}`);
  chk(_byId['seatInfo'].textContent !== undefined, '#seatInfo 仍可写');

  // ==========================================================================
  sect(11, '⑪ ★ 已停用条目（欠费/下线）：文案是「（已停用）」而不是「（未配置）」');

  CUR = mkState({
    seats: { 1: '__search__', 2: '__search__', 3: '__search__' },
    seat_options: {
      local: [{ id: '__search__', label: '本地Bot · 搜索', brief: '3 plies', kind: 'local', local: true, ready: true, why: '' }],
      api: [
        { id: 'deepseek-v4-flash', label: 'DeepSeek-V4-Flash', brief: '≈28s/步', kind: 'api', local: false, ready: true, why: '' },
        { id: 'zombie', label: 'DeepSeek-V4-Pro', brief: '账号欠费', kind: 'api', local: false,
          ready: false, disabled: true, hint: '欠费了', why: '已停用：账号欠费（HTTP 402）' },
        { id: 'hy4', label: 'HY4', brief: '未配置', kind: 'api', local: false,
          ready: false, disabled: false, why: '未配置接口地址：请在 agents.json 里补 url' },
      ],
    },
  });
  await POLL(); await sleep(10);
  const zOp = optByVal(sels[0], 'zombie');
  const uOp = optByVal(sels[0], 'hy4');
  chk(!!zOp && zOp.disabled === true, '★ 已停用条目同样**点不动**（disabled=true）');
  chk(!!zOp && /（已停用）/.test(zOp.textContent || ''),
    '★ 文案是「（已停用）」（**不是**「未配置」）', (zOp && zOp.textContent) || '');
  chk(!!uOp && /（未配置）/.test(uOp.textContent || ''),
    '同一次渲染里，未配置条目仍是「（未配置）」⇒ 两者分得开', (uOp && uOp.textContent) || '');
  chk(!!zOp && /欠费/.test(zOp.title || ''),
    '★ 悬停写明**为什么**停用（欠费 / 下线），老师不用去猜配置', (zOp && zOp.title) || '');
  //   （真正的"选不进去"由浏览器保证：disabled 的 <option> 无法被选中；
  //     后端 set_seat 再兜一层，拒绝理由见 _verify_seat_model.py 第 ⑤ 节。）

  // ==========================================================================
  console.log('\n' + '='.repeat(74));
  console.log(`每方主控（本地Bot / API）· UI 专项验证：${ok} 通过 / ${bad} 失败`);
  console.log('='.repeat(74));
  process.exit(bad ? 1 : 0);
})();
