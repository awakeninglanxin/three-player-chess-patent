/* 「上一步走子」红色标记专项验证（Node，无需浏览器）
   —— 老师 2026-09-24 夜报「魏国的士凭空消失」+「用红色虚线标记前一手的下棋路径，
      从哪到哪位置、吃了什么都要直观讲清楚」。

   查证结论（见 tests/_replay_probe.py）：士**没丢**，是 ply10 被走到 D5、
   ply12 被蜀方一门炮**从棋盘另一端**（L5）吃掉，而炮 ply14 又走了 ⇒
   静态盘面完全看不出"谁吃的"。缺失的正是**上一手的视觉痕迹**。

   本脚本用最小 DOM 桩真跑 `init()` / `setLastMove()`，断言：
     · 红色虚线 + 红色箭头（方向指向终点）
     · 起点红虚线圈 + 终点红双实环
     · 文字「起 L5」/「到 D5 吃士」，红字白边双层
     · 签名缓存、健壮性、不挡点击
   运行：node tests/_verify_lastmove.js
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
  addEventListener: () => { },
  readyState: 'loading'
};
global.window = global;
global.sessionStorage = { getItem: () => null, setItem: () => { }, removeItem: () => { } };
global.setInterval = () => 0;

// ------------------------------------------------------------- 加载被测源码
eval(fs.readFileSync(path.join(ROOT, 'web', 'board_data.js'), 'utf8'));
eval(fs.readFileSync(path.join(ROOT, 'web', 'board.js'), 'utf8'));
const C = window.ChessBoard;
const D = window.BOARD_DATA;
const NPT = Object.keys(D.points).length;
const xy = p => { const q = D.points[p]; return q ? [q[0], -q[1]] : null; };
const RED = '#c02626';

const svg = new El('svg');
C.init(svg);
const gs = svg.children.filter(c => c.tag === 'g');
const gFocus = gs[gs.length - 1];

// ============================================================================
sect(1, '① 接口与图层：gFocus 在最上层、不挡点击');

chk(typeof C.setLastMove === 'function', 'setLastMove 已导出');
chk(gs.length === 4, '动态图层共 4 个（hits/hints/pieces/focus）', `实测 ${gs.length}`);
chk(svg.children[svg.children.length - 1] === gFocus,
  'gFocus 是 svg 的**最后一个**子节点 → 叠放在棋子之上（否则标记会被棋子盖住）');
chk(gFocus.attrs['pointer-events'] === 'none',
  'gFocus 设了 pointer-events:none → 绝不挡住棋子/热区的点击',
  `实测 ${gFocus.attrs['pointer-events']}`);

// ============================================================================
sect(2, '② 红色虚线 + 箭头：路径与方向');

// 真实场景：ply12 蜀炮 L5 → D5 吃掉魏士（老师报的那一手）
C.setLastMove({ from: '245', to: '125', army: 3, captured: 'advisor' });

const lines = gFocus.find(x => x.tag === 'line');
const polys = gFocus.find(x => x.tag === 'polygon');
const circles = gFocus.find(x => x.tag === 'circle');
const texts = gFocus.find(x => x.tag === 'text');
const P = xy('245'), Q = xy('125');

chk(lines.length === 1, '虚线 1 条', `实测 ${lines.length}`);
const L = lines[0];
chk(+L.attrs.x1 === P[0] && +L.attrs.y1 === P[1]
  && +L.attrs.x2 === Q[0] && +L.attrs.y2 === Q[1],
  '虚线两端 = L5(245) / D5(125) 的真实棋盘坐标');
chk(L.attrs.stroke === RED,
  `虚线是**红色** ${RED}（老师指定；不再是走子方的颜色）`, `实测 ${L.attrs.stroke}`);
chk(String(L.attrs['stroke-dasharray'] || '').split(' ').length >= 2,
  '虚线样式（stroke-dasharray 至少两段）', `实测 ${L.attrs['stroke-dasharray']}`);

chk(polys.length === 1, '箭头 1 个', `实测 ${polys.length}`);
const A = polys[0];
chk(A.attrs.fill === RED, '箭头是红色的', `实测 ${A.attrs.fill}`);
// 箭头尖应落在"终点方向、终点环之前"
const pts = String(A.attrs.points).split(' ').map(s => s.split(',').map(Number));
const tip = pts[0];
const dPQ = Math.hypot(Q[0] - P[0], Q[1] - P[1]);
const dTip = Math.hypot(tip[0] - Q[0], tip[1] - Q[1]);
chk(dTip > 4.5 && dTip < 7.0,
  '箭头尖停在终点环之前（距离终点 4.5~7.0，不盖住终点）', `实测 ${dTip.toFixed(2)}`);
// 尖端应比两个底点更靠近 Q
chk(Math.min(...pts.slice(1).map(p => Math.hypot(p[0] - Q[0], p[1] - Q[1]))) > dTip,
  '箭头**指向**终点（尖端比底边两点更靠 Q）');
chk(Math.abs(dPQ - 0) > 0, '（记录）L5→D5 两点距离 = ' + dPQ.toFixed(2) + '（跨方长距离吃子）');

// ============================================================================
sect(3, '③ 起点虚线圈 + 终点双实环（全红）');

const dashRing = circles.find(c => c.attrs['stroke-dasharray']);
const solidRings = circles.filter(c => !c.attrs['stroke-dasharray']);
chk(circles.length === 3, '圆 3 个（起点虚线圈 1 + 终点实双环 2）', `实测 ${circles.length}`);
chk(!!dashRing && +dashRing.attrs.cx === P[0] && +dashRing.attrs.cy === P[1],
  '起点是**虚线圈**且圆心在 L5');
chk(!!dashRing && dashRing.attrs.stroke === RED, '起点虚线圈是红色');
chk(solidRings.length === 2, '终点是**双实环**', `实测 ${solidRings.length}`);
chk(solidRings.every(c => +c.attrs.cx === Q[0] && +c.attrs.cy === Q[1]),
  '两个实环圆心都在终点 D5');
chk(solidRings.every(c => c.attrs.stroke === RED), '终点双环是红色');
chk(circles.every(c => +c.attrs.r >= 4.6),
  '所有环半径 ≥ 4.6（棋子半径 4.05，小了会被完全盖住）',
  `实测 ${circles.map(c => c.attrs.r).join('/')}`);

// ============================================================================
sect(4, '④ 文字标注：「起 L5」/「到 D5 吃士」——从哪到哪、吃了什么');

chk(texts.length === 4, '文字 4 个（起点 2 层 + 终点 2 层：白底 + 红字）',
  `实测 ${texts.length}`);
const contents = texts.map(t => t.textContent);
chk(contents.filter(c => c === '起 L5').length === 2,
  '起点标注「起 L5」', `实测 ${JSON.stringify(contents)}`);
chk(contents.filter(c => c === '到 D5 吃士').length === 2,
  '终点标注**含吃子**「到 D5 吃士」', `实测 ${JSON.stringify(contents)}`);
chk(texts.filter(t => t.attrs.fill === RED).length === 2,
  '每个标签有一个红色填充层（第二层）');
chk(texts.filter(t => t.attrs.fill === '#ffffff').length === 2,
  '每个标签有一个白色描边层（垫底，保证任意背景可读）');
chk(texts.every(t => +t.attrs['stroke-width'] === undefined
  || +t.attrs['stroke-width'] >= 2.4 || t.attrs.fill === RED),
  '白底层的描边足够粗（≥2.4）');

// 无吃子时不应出现「吃」字
C.setLastMove({ from: '132', to: '137', army: 1 });
const c2 = gFocus.find(x => x.tag === 'text').map(t => t.textContent);
chk(c2.every(s => !s.includes('吃')),
  '没吃子时不显示「吃」字', `实测 ${JSON.stringify(c2)}`);
chk(c2.includes('起 C8') && c2.includes('到 C3'),
  '魏炮 132→137 标注为「起 C8」「到 C3」', `实测 ${JSON.stringify(c2)}`);

// ============================================================================
sect(5, '⑤ 标签夹进可视区（viewBox = -124 -108 248 216，防贴边被裁）');

// 找一个离原点最远、且方向朝外的走法：151(E1?) 与 359 之类
const far = Object.keys(D.points).sort((a, b) => {
  const pa = D.points[a], pb = D.points[b];
  return (pb[0] ** 2 + pb[1] ** 2) - (pa[0] ** 2 + pa[1] ** 2);
})[0];
const farQ = xy(far);
C.setLastMove({ from: '115', to: far, army: 1 });
const lt = gFocus.find(x => x.tag === 'text');
chk(lt.every(t => Math.abs(+t.attrs.x) <= 112 && Math.abs(+t.attrs.y) <= 100),
  '最外侧点的标签仍被夹在可视区内',
  `最远点 ${far} 坐标 (${farQ.map(v => v.toFixed(1))}) → 文字 x=${lt.map(t => t.attrs.x).join('/')}`);

// ============================================================================
sect(6, '⑥ 签名缓存：同签名不重建（避免 800ms 轮询把正在看的标记抽掉）');

C.setLastMove({ from: '245', to: '125', army: 3, captured: 'advisor' });
const lineObj = gFocus.find(x => x.tag === 'line')[0];
C.setLastMove({ from: '245', to: '125', army: 3, captured: 'advisor' });
chk(gFocus.find(x => x.tag === 'line')[0] === lineObj,
  '同签名重复调用 **不重建**（元素对象仍是同一个）');
C.setLastMove({ from: '245', to: '125', army: 3 });
const lineObj2 = gFocus.find(x => x.tag === 'line')[0];
chk(lineObj2 !== lineObj, '吃子信息变化（captured 不同）也会重建');

// ============================================================================
sect(7, '⑦ 健壮性：null / 空值 / 不存在的点位');

C.setLastMove(null);
chk(gFocus.children.length === 0, 'setLastMove(null) → 清空（新局时不该留旧标记）',
  `实测 ${gFocus.children.length} 个子元素`);
C.setLastMove({ from: '', to: '', army: 1 });
chk(gFocus.children.length === 0, '空 from/to → 不画、不报错');
let threw = false;
try { C.setLastMove({ from: '999', to: '888', army: 2 }); } catch (e) { threw = true; }
chk(!threw && gFocus.children.length === 0,
  '不存在的点位（999/888）→ 静默跳过，不抛异常');
threw = false;
try { C.setLastMove({ from: '115', to: '115', army: 1 }); } catch (e) { threw = true; }
chk(!threw && gFocus.children.length === 0, '起点=终点（零长度）→ 不画、不报错');

// ============================================================================
sect(8, '⑧ 不干扰既有交互：热区仍是 135 个、gFocus 无任何监听');

C.setLastMove({ from: '245', to: '125', army: 3, captured: 'advisor' });
const clickables = svg.find(n => n.listeners && n.listeners.click);
chk(NPT === 135, '棋盘共 135 个点', `实测 ${NPT}`);
chk(clickables.length === NPT,
  `加了上一手标记后，带 click 的热区仍是 ${NPT} 个`, `实测 ${clickables.length}`);
chk(gFocus.find(n => n.listeners && Object.keys(n.listeners).length).length === 0,
  'gFocus 内部 0 个元素带事件监听 → 纯视觉层');

// ============================================================================
console.log('\n' + '='.repeat(74));
console.log(`合计 ${ok} 通过 / ${bad} 失败`);
console.log('='.repeat(74));
process.exit(bad ? 1 : 0);
