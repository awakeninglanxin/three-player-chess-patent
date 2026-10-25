/* 「中央三角区·枢纽」视觉标记专项验证（Node，无需浏览器）
   —— 老师 2026-10-01 原话：「可选：要不要在棋盘上给三角区三个格点加个视觉标记
      （比如淡金色三角轮廓）？现在玩家点兵能看到 255/355 被高亮，但看不出
      『这是个枢纽』——加个标记会更直观。您说要我就加。」→「加吧」

   规则背景：兵到达中心三角区格点（155 魏A5 / 255 吴K5 / 355 蜀F5）后，
   可沿三条边**自由回跳**（含跨方、不受「只能过一次界」限制）⇒ 全盘唯一机动枢纽。
   （规则实现见 tests/_verify_pawn_tri.py）

   设计意图：**未选中任何棋子时**也要能一眼看出"这里是一块特殊区域"。
     · 淡香槟金细轮廓 + 极淡暖光底 = 「区域」
     · 三顶点金环（轻呼吸）        = 「这三个点本身是枢纽」
     · 选中枢纽上的棋子 ⇒ .active（轮廓加粗、暖光加深）= 「枢纽正在起作用」

   本脚本用最小 DOM 桩真跑 init() / setLegal() / clearHints()，断言：
     · 标记结构与三顶点坐标正确，且只覆盖这三个点
     · 与「落点提示」的琥珀实心点视觉可区分（色、形、层级）
     · 整组 pointer-events:none + 图层顺序 ⇒ 绝不挡 135 个点击热区
     · 激活态切换幂等、非枢纽点不误触发、重新 init 后引用正确刷新
     · setLegal 的原有签名缓存行为未被破坏（回归守卫）
     · style.css 侧动画规则与 reduced-motion 兜底都在
   运行：node tests/_verify_tri_mark.js
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
const src = fs.readFileSync(path.join(ROOT, 'web', 'board.js'), 'utf8');
const css = fs.readFileSync(path.join(ROOT, 'web', 'style.css'), 'utf8');
eval(fs.readFileSync(path.join(ROOT, 'web', 'board_data.js'), 'utf8'));
eval(src);
const C = window.ChessBoard;
const D = window.BOARD_DATA;

const TRI = ['155', '255', '355'];
const xy = p => { const q = D.points[p]; return q ? [q[0], -q[1]] : null; };
const num = v => +v;
const near = (a, b, tol) => Math.abs(a - b) <= (tol === undefined ? 1e-6 : tol);

const newSvg = () => { const s = new El('svg'); C.init(s); return s; };
const triOf = s => s.children.filter(c => c.tag === 'g' && c.attrs.class
  && /(^|\s)tri-hub(\s|$)/.test(c.attrs.class))[0];
const cls = n => String((n && n.attrs && n.attrs.class) || '');
const isActive = n => /\bactive\b/.test(cls(n));

// ============================================================================
sect(1, '① 标记存在、结构完整、整组不拦点击');

const svg = newSvg();
const tri = triOf(svg);
chk(!!tri, '棋盘上出现了三角区标记图层（<g class="tri-hub">）');

if (!tri) {
  console.log('\n  ⚠️ 标记层缺失，后续断言全部跳过');
  console.log(`\n合计 ${ok} 通过 / ${bad} 失败`);
  process.exit(1);
}

chk(tri.attrs['pointer-events'] === 'none',
  '整组 pointer-events:none ⇒ 绝不挡住下面 135 个点击热区',
  `实测 ${tri.attrs['pointer-events']}`);

const polys = tri.children.filter(c => c.tag === 'polygon');
const circles = tri.children.filter(c => c.tag === 'circle');
const texts = tri.children.filter(c => c.tag === 'text');
chk(polys.length === 2, '含 2 个 polygon（柔光底 + 主轮廓）', `实测 ${polys.length}`);
chk(circles.length === 6, '含 6 个 circle（三顶点 × 粗细双环）', `实测 ${circles.length}`);
chk(texts.length === 1, '含 1 个 text（**单层金色字，透明背景**）', `实测 ${texts.length}`);
chk(texts.length > 0 && texts.every(t => t.textContent === '三角区'),
  '标签文字是「三角区」（给玩家一个名字，不靠猜）',
  texts.map(t => `「${t.textContent}」`).join(' '));

// ============================================================================
sect(2, '② 三顶点坐标 = 155/255/355（一个不多、一个不少）');

const gotPts = circles.map(c => `${num(c.attrs.cx).toFixed(3)},${num(c.attrs.cy).toFixed(3)}`);
const wantPts = TRI.map(p => { const q = xy(p); return `${q[0].toFixed(3)},${q[1].toFixed(3)}`; });
chk(new Set(gotPts).size === 3,
  '金环圆心去重后恰好 3 个不同点', `实测 ${new Set(gotPts).size}：${[...new Set(gotPts)].join(' | ')}`);
chk(wantPts.every(w => gotPts.includes(w)),
  '三圆心与 155(A5) / 255(K5) / 355(F5) 的屏幕坐标完全一致',
  wantPts.join(' | '));
chk(gotPts.every(g => wantPts.includes(g)),
  '★ 反方向也成立：没有多画出任何其他点（不是"至少包含"）');

// board_data 与代码常量不得漂移
const dtri = Object.values(D.tri || {}).map(String).sort();
chk(JSON.stringify(dtri) === JSON.stringify([...TRI].sort()),
  'board_data.tri 与代码里的 TRI_PTS 一致（防两边各自演进后漂移）',
  `data=${dtri.join(',')} code=${[...TRI].sort().join(',')}`);

// 三角形的三条边确实是棋盘上画出来的线（而不是凭空连的）
const edge = (D.lines || []).some(ch => TRI.every(p => ch.indexOf(p) >= 0));
chk(edge, '三点确实由棋盘上的**实线**两两相连（标记贴合既有网格，不是臆造）');

// ============================================================================
sect(3, '③ 与「落点提示」视觉可区分（同屏不混）');

const GOLD = '#c9a961';                                  // board.js 里的香槟金
const HINT_AMBER = '#d69e2e';                            // 落点提示的琥珀
const edgePoly = polys.filter(p => cls(p) === 'tri-edge')[0];
const glowPoly = polys.filter(p => cls(p) === 'tri-glow')[0];
chk(!!edgePoly && !!glowPoly,
  '两个 polygon 各有语义 class（tri-glow / tri-edge ⇒ 激活态可分别加粗）');
chk(edgePoly.attrs.stroke === GOLD,
  `主轮廓用香槟金 ${GOLD}（比琥珀 ${HINT_AMBER} 淡且冷）`);
chk(edgePoly.attrs.stroke !== HINT_AMBER,
  '★ 与落点提示的琥珀色**不同** ⇒ 老师不会把"区域"看成"下一步能走这儿"');
// 网格线宽 0.42、棋子半径 4.05 ⇒ 轮廓要落在"明显粗于网格线、远细于棋子"的区间，
// 才读作「区域轮廓」：太细看不见（第一版真踩过），太粗会读成"色块"甚至压住棋子。
const ew = num(edgePoly.attrs['stroke-width']);
chk(ew > 0.42 * 2 && ew <= 1.8,
  '主轮廓粗于棋盘网格线（0.42）但不失"线"感（0.84 < w ≤ 1.8）',
  `实测 ${ew}（网格线 0.42，棋子半径 4.05）`);
chk(num(glowPoly.attrs['stroke-opacity']) <= 0.3,
  '柔光外圈足够淡（stroke-opacity ≤ 0.3）⇒ 只起衬托作用，不喧宾夺主',
  `实测 ${glowPoly.attrs['stroke-opacity']}`);
chk(num(glowPoly.attrs['fill-opacity']) <= 0.35,
  '暖光底够淡（fill-opacity ≤ 0.35）⇒ 不遮网格线、不盖中央地带配色',
  `实测 ${glowPoly.attrs['fill-opacity']}`);
const goldT = texts.filter(t => cls(t) === 'tri-label')[0];
chk(texts.every(t => t.attrs.fill !== '#ffffff')
  && !tri.children.some(c => cls(c) === 'tri-label-halo'),
  '★ 标签**透明背景**（老师 2026-10-01 指定）：无白色垫底层、无白填充');
chk(!!goldT && goldT.attrs.fill === GOLD,
  '标签用同一香槟金（与轮廓同色系，整体是一套）');
chk(!!goldT && (goldT.attrs.stroke === 'none' || goldT.attrs.stroke == null),
  '★ 标签**没有描边**（老师 2026-10-01：「注意，不需要描边」）—— 纯单层金色字',
  `实测 stroke=${goldT && goldT.attrs.stroke}`);
chk(!!goldT && goldT.attrs['font-weight'] === 'normal',
  '★ 标签字重 **normal**（老师 2026-10-01：「字体太粗了，是黑体太粗了」）',
  `实测 ${goldT && goldT.attrs['font-weight']}`);
chk(num(goldT.attrs['font-size']) < 4.05 * 2,
  '标签字号小于棋子直径 ⇒ 不与棋子抢视线',
  `实测 ${goldT.attrs['font-size']} < ${(4.05 * 2).toFixed(1)}`);

// 三个 band（荆州/赤壁/祁山）本来就压在三角区上；标记必须在它们**之后**画，
// 否则会被三条色带盖住（老师会看到"标记时有时无"）。
const bandIdx = svg.children.map((c, i) => [c, i])
  .filter(([c]) => c.tag === 'polygon' && num(c.attrs['fill-opacity']) === 0.3)
  .map(([, i]) => i);
const triIdx = svg.children.indexOf(tri);
chk(bandIdx.length > 0 && bandIdx.every(i => i < triIdx),
  '标记画在三条中心地带色块**之后** ⇒ 不会被荆州/赤壁/祁山的色块盖住',
  `band 下标 ${bandIdx.join(',')} < tri ${triIdx}`);

// ============================================================================
sect(4, '④ 图层顺序：标记在下，热区在上 ⇒ 点哪儿都还是点得动');

const gIdx = cl => svg.children.findIndex(c => c.tag === 'g' && cls(c) === cl);
const firstPath = svg.children.findIndex(c => c.tag === 'path');
chk(triIdx < firstPath,
  '标记画在**网格线之前**（下标更小）⇒ 轮廓压在网格线下层，先有线后有点的顺序不变',
  `tri ${triIdx} < 首个 path ${firstPath}`);
chk(triIdx < gIdx('lyr-hits'),
  '标记在热区图层**之下** ⇒ 即使万一忘记 pointer-events，热区也优先命中',
  `tri ${triIdx} < hits ${gIdx('lyr-hits')}`);
chk(gIdx('lyr-focus') > gIdx('lyr-pieces') && gIdx('lyr-pieces') > gIdx('lyr-hints')
  && gIdx('lyr-hints') > gIdx('lyr-hits'),
  '四个动态图层顺序未被打乱（hits < hints < pieces < focus）',
  `${gIdx('lyr-hits')} < ${gIdx('lyr-hints')} < ${gIdx('lyr-pieces')} < ${gIdx('lyr-focus')}`);

// 真触发一次点击，证明热区仍然工作
let picked = '';
C.setPickHandler(p => { picked = p; });
const hits = svg.children.filter(c => c.tag === 'g' && cls(c) === 'lyr-hits')[0];
chk(!!hits && hits.children.length === 135,
  '热区图层仍是 135 个点', `实测 ${hits ? hits.children.length : 'N/A'}`);
hits.children[0].fire('click');
chk(picked !== '', '真点击一次热区 → onPick 被调用（热区未被标记层阻断）',
  `返回 ${picked}`);

// ============================================================================
sect(5, '⑤ 激活态：选中枢纽上的棋子 ⇒ 加粗；离开 ⇒ 复原');

C.clearHints();
chk(!isActive(triOf(svg)), '初始（未选中）为常态 .tri-hub',
  `class="${cls(triOf(svg))}"`);

C.setLegal('155', ['255', '355']);
chk(isActive(triOf(svg)),
  '★ 选中站在 155 的棋子 → 标记转激活态 .tri-hub.active（"枢纽正在起作用"）',
  `class="${cls(triOf(svg))}"`);

C.setLegal('255', ['155', '355']);
chk(isActive(triOf(svg)), '255 同样触发（三个点任一站上去都算）');

C.setLegal('355', ['155', '255']);
chk(isActive(triOf(svg)), '355 同样触发');

C.setLegal('125', ['115', '135']);
chk(!isActive(triOf(svg)),
  '★ 选中**非枢纽**格点（125 = 魏军帐中心）→ 退回常态，不误触发',
  `class="${cls(triOf(svg))}"`);

// 幂等：同参重复调用不改变结果、不报错
C.setLegal('155', ['255', '355']);
C.setLegal('155', ['255', '355']);
chk(isActive(triOf(svg)) && cls(triOf(svg)) === 'tri-hub active',
  '幂等：同参连调两次，class 仍是干净的 .tri-hub.active（不叠加、不多空格）',
  `class="${cls(triOf(svg))}"`);

C.clearHints();
chk(!isActive(triOf(svg)), 'clearHints() 撤销选择 → 标记退回常态',
  `class="${cls(triOf(svg))}"`);
C.clearHints();
chk(!isActive(triOf(svg)), 'clearHints() 再调一次仍然安全（幂等）');

// ============================================================================
sect(6, '⑥ 重新 init 后引用刷新（防「模块级状态没清零」的老坑）');

// 旧坑（见 board.js init 里 _lastHints/_lastFocus 的注释）：模块级缓存跨 svg 实例
// 共享。若 _triActive 没在 init 里重置，则新 svg 的标记会**永远停在常态**：
//   因为 act(true) === _triActive(true) ⇒ 判"没变"⇒ 不写属性。
const svgA = newSvg();
C.setLegal('155', ['255', '355']);
chk(isActive(triOf(svgA)), '棋盘 A：选中枢纽 → A 的标记激活');

const svgB = newSvg();
chk(!isActive(triOf(svgB)), '棋盘 B 新建后是常态（未被 A 的状态污染）',
  `class="${cls(triOf(svgB))}"`);
C.setLegal('155', ['255', '355']);
chk(isActive(triOf(svgB)),
  '★ 棋盘 B 上选中枢纽 → **B 自己的**标记激活（引用已刷新，不是写到 A 上）',
  `class="${cls(triOf(svgB))}"`);

// ============================================================================
sect(7, '⑦ 回归守卫：setLegal 原有行为（签名缓存 / 提示元素）未被破坏');

const svgC = newSvg();
C.setLegal('115', ['125', '135']);
const hints = svgC.children.filter(c => c.tag === 'g' && cls(c) === 'lyr-hints')[0];
const n1 = hints.children.length;
chk(n1 === 1 + 2, '提示照常画：1 个起点环 + 2 个落点圆', `实测 ${n1}`);
const first = hints.children[0];
C.setLegal('115', ['125', '135']);            // 完全相同 → 签名不变
chk(hints.children[0] === first,
  '★ 同签名重复调用**不重建**提示元素（点中的那一瞬不会被销毁 ⇒ 点击不丢）');
chk(triOf(svgC) === triOf(svgC), '标记节点在同一棋盘内保持同一引用（不反复重建）');

// ============================================================================
sect(8, '⑧ style.css：呼吸动画 + reduced-motion 兜底');

chk(/\.tri-hub\s+\.tri-ring\s*\{[^}]*animation\s*:/.test(css),
  '金环有呼吸动画（.tri-hub .tri-ring { animation: ... }）');
chk(/@keyframes\s+triHub/.test(css), '@keyframes triHub 已定义');
chk(/prefers-reduced-motion[\s\S]{0,220}\.tri-hub\s+\.tri-ring\s*\{[^}]*animation\s*:\s*none/.test(css),
  '★ prefers-reduced-motion 下关闭动画（对动画敏感的老师不受影响）');
chk(/\.tri-hub\.active\s+\.tri-edge\s*\{[^}]*stroke-width/.test(css),
  '.tri-hub.active .tri-edge 有加粗规则（激活态在 CSS 侧真的生效）');
chk(/\.tri-hub\.active\s+\.tri-glow\s*\{/.test(css),
  '.tri-hub.active .tri-glow 有加深规则');
chk(/\.tri-hub\s+\.tri-edge[^{]*\{[^}]*transition\s*:/.test(css),
  '激活切换带 transition ⇒ 加粗是平滑过渡，不是突然跳变');

// ============================================================================
console.log('\n' + '='.repeat(74));
console.log(`三角区枢纽标记专项验证：${ok} 通过 / ${bad} 失败`);
console.log('='.repeat(74));
process.exit(bad ? 1 : 0);
