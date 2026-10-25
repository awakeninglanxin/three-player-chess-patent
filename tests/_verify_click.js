/* 前端交互专项验证（Node，无需浏览器）
   —— 老师 2026-09-24 深夜报的「点亮棋子后点落点，棋子不动」。

   根因：`board.js` 旧实现**只给棋子**绑了 click，**空格落点没有事件**
   （`renderPieces` 里那一句是唯一的 addEventListener），于是：
     · 走子（目标为空点）→ 永远点不动  ← 老师遇到的就是这个
     · 吃子（目标有对方棋子）→ 碰巧能走
   修法：① 给全部 135 个格点铺透明热区；② 提示层的金色落点圆本身可点击；
        ③ 提示层加签名缓存，避免 500ms 轮询把正在点的元素销毁掉。

   本脚本用一个**最小 DOM 桩**真跑 `init()` / `setLegal()`，
   再**真的触发 click 事件**，断言回调收到了正确点位。
   运行：node tests/_verify_click.js
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

// ---------------------------------------------------------------- 最小 DOM 桩
class El {
  constructor(tag) {
    this.tag = tag; this.children = []; this.attrs = {};
    this.style = {}; this.listeners = {}; this._text = '';
  }
  setAttribute(k, v) { this.attrs[k] = v; }
  getAttribute(k) { return this.attrs[k]; }
  appendChild(c) { this.children.push(c); return c; }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  set innerHTML(v) { if (v === '') this.children = []; }
  get innerHTML() { return ''; }
  set textContent(v) { this._text = v; }
  get textContent() { return this._text; }
  fire(t) { (this.listeners[t] || []).forEach(f => f({ target: this })); }
  find(pred, out) {
    out = out || [];
    if (pred(this)) out.push(this);
    this.children.forEach(c => c.find(pred, out));
    return out;
  }
}
global.document = {
  createElementNS: (ns, tag) => new El(tag),
  querySelector: () => null,
  querySelectorAll: () => [],
  getElementById: () => new El('div'),
  addEventListener: () => { },          // DOMContentLoaded 不触发 → boot() 不跑
  readyState: 'loading'
};
global.window = global;
global.sessionStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
global.setInterval = () => 0;

// ------------------------------------------------------------- 加载被测源码
eval(fs.readFileSync(path.join(ROOT, 'web', 'board_data.js'), 'utf8'));
eval(fs.readFileSync(path.join(ROOT, 'web', 'board.js'), 'utf8'));
const C = window.ChessBoard;
const D = window.BOARD_DATA;
const NPT = Object.keys(D.points).length;

// ---- app.js：IIFE 内部函数拿不到，测试时把尾部 `})();` 换成一个导出钩子再 eval
//      （只改内存里的字符串，不动磁盘上的生产代码）
const appSrc = fs.readFileSync(path.join(ROOT, 'web', 'app.js'), 'utf8')
  .replace(/\}\)\(\);\s*$/, 'window.__t = { legalTargets, onPick };\n})();');
eval(appSrc);
const T = window.__t || {};

const svg = new El('svg');
C.init(svg);

// ============================================================================
sect(1, `① 全部 ${NPT} 个格点都有点击热区（旧实现是 0 个）`);

const clickables = svg.find(n => n.listeners && n.listeners.click);
chk(NPT === 135, `棋盘共 135 个点`, `实测 ${NPT}`);
chk(clickables.length === NPT,
  `init() 后带 click 监听的元素 = ${NPT}（每个格点一个透明热区）`,
  `实测 ${clickables.length}`);

// ============================================================================
sect(1.5, '★ ①.5 legal 解析：`/api/state` 的 legal 是**字符串**「from-to」数组');

const LEGAL = ['111-121', '111-131', '112-131', '112-133', '113-131', '113-135',
  '114-125', '115-125', '116-125', '117-135', '117-139', '118-137', '118-139',
  '119-129', '119-139', '132-122', '132-131'];

chk(typeof T.legalTargets === 'function', 'legalTargets 已就绪');
const t118 = T.legalTargets({ legal: LEGAL }, '118');
chk(JSON.stringify(t118) === '["137","139"]',
  'legal 里 118 的落点 = 137 / 139（旧代码 `m[0]` 取到单个字符 → 恒为空）',
  `实测 ${JSON.stringify(t118)}`);
chk(T.legalTargets({ legal: LEGAL }, '132').join() === '122,131',
  '132 的落点为 122 / 131');
chk(T.legalTargets({ legal: LEGAL }, '999').length === 0,
  '不存在的起点返回空数组');
chk(T.legalTargets({}, '111').length === 0, 'legal 缺失时不报错');

// ============================================================================
sect(2, '② 真触发 click → 回调收到正确点位（走子：目标为空点）');

let picked = [];
C.setPickHandler(p => picked.push(p));

// 找一个空格点（没棋子的图层里全是空的，随便挑一个）
const target = Object.keys(D.points)[40];
clickables[40].fire('click');
chk(picked.length === 1 && picked[0] === target,
  `点空点 ${target} → onPick('${target}') 被调用`,
  `实测 picked=${JSON.stringify(picked)}`);

// ============================================================================
sect(3, '③ setLegal 的金色落点圆也可点击（棋盘被提示层覆盖时仍能落子）');

picked = [];
C.setLegal('156', ['243', '245', '252', '256']);
const hintDots = svg.find(n => n.listeners && n.listeners.click && n.tag === 'circle'
  && String(n.attrs.fill) === '#d69e2e');
chk(hintDots.length === 4,
  '4 个落点圆各自绑了 click', `实测 ${hintDots.length}`);
hintDots[1].fire('click');
chk(picked.length === 1 && picked[0] === '245',
  `点落点圆 → onPick('245')`, `实测 picked=${JSON.stringify(picked)}`);

// ============================================================================
sect(4, '④ 提示层签名缓存：相同提示不重建（避免轮询销毁正在点的元素）');

const before = svg.find(n => n.tag === 'circle' && String(n.attrs.fill) === '#d69e2e');
C.setLegal('156', ['243', '245', '252', '256']);        // 同签名再调一次
const after = svg.find(n => n.tag === 'circle' && String(n.attrs.fill) === '#d69e2e');
chk(before.length === after.length && before[0] === after[0],
  '同签名重复调用 **不重建** 元素（元素对象仍是同一个）');

C.setLegal('156', ['243', '245']);                       // 签名变了 → 该重建
const shrunk = svg.find(n => n.tag === 'circle' && String(n.attrs.fill) === '#d69e2e');
chk(shrunk.length === 2, '签名变化时才重建（落点 2 个）', `实测 ${shrunk.length}`);

C.clearHints();
const cleared = svg.find(n => n.tag === 'circle' && String(n.attrs.fill) === '#d69e2e');
chk(cleared.length === 0, 'clearHints() 清空落点圆');

// ============================================================================
sect(5, '⑤ 点位标签函数可用（app.js 的反馈文案要用）');

chk(typeof C.label === 'function', 'ChessBoard.label 已导出');
chk(C.label('156') === 'A4', "156 → 'A4'（魏 row5 列6，图中数字 10−6=4）", C.label('156'));
chk(C.label('154') === 'A6', "154 → 'A6'", C.label('154'));
chk(C.label('115') === 'E5', "115 → 'E5'", C.label('115'));
chk(C.label('245') === 'L5', "245 → 'L5'（吴 row4 列5）", C.label('245'));
chk(C.label('252') === 'K8', "252 → 'K8'（吴 row5 列2）", C.label('252'));

console.log('\n' + '='.repeat(74));
console.log(`合计 ${ok} 通过 / ${bad} 失败`);
console.log('='.repeat(74));
process.exit(bad ? 1 : 0);
