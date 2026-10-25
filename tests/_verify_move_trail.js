/* 「上两手走子痕迹」专项验证（Node，无需浏览器）
   —— 老师 2026-09-25 原话：「目前你会用红色虚线显示前一次走棋，但不够，我需要
      前两次，分别用红色和橙色虚线表示前一次和前两次」。

   设计意图：**吃子往往只是结果，根因常在上上一步**（对方刚把子送到这里 /
   自己刚让开炮架）。所以要把最近两手都钉在盘面上：
     · 最近一手（红 #c02626）＝ 完全保留老师已认可的样式
     · 再往前一手（橙 #e07a10）＝ 同款标记 + 「前」前缀小标签，环整体大一圈

   本脚本用最小 DOM 桩真跑 `init()` / `setMoveTrail()`，断言：
     · 两条虚线、两种颜色、**红色压橙色之上**（新的一手更醒目）
     · 橙色环整体大于红色环 → 两手共用格点时是同心双环、不糊成一团
     · 橙标签带「前」前缀且外推更远 → 不与红标签叠字
     · 橙手吃子也要写「吃士」
     · 签名缓存认「两手整体」而不是只看最近一手
     · 单手 / 空 / 非法值时行为与旧版完全一致（向后兼容）
   运行：node tests/_verify_move_trail.js
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
const RED = '#c02626', ORANGE = '#e07a10';

const svg = new El('svg');
C.init(svg);
// 【2026-10-01】改按 class 查找：svg 里现在有 5 个 <g>（三角区标记 .tri-hub
//   + 四个动态图层 lyr-*）。旧写法用 gs[gs.length-1] / gs.length===4 定位，
//   一加图层就集体失效 —— 本轮加视觉标记时三个前端测试同时误取图层。
const byCls = cl => svg.children.filter(c => c.tag === 'g' && c.attrs.class === cl)[0];
const gFocus = byCls('lyr-focus');

// 真实场景（老师报的那一手 + 它的上一手）：
//   橙 ply10 魏士 D6(124) → D5(125)     ※ 图中数字 d = 10 − 引擎列 ⇒ 列4 = 数字6
//   红 ply12 蜀炮 L5(245) → D5(125) 吃掉魏士
const PREV = { from: '124', to: '125', army: 1 };
const LAST = { from: '245', to: '125', army: 3, captured: 'advisor' };
const pick = (tag) => gFocus.find(x => x.tag === tag);
const texts = () => gFocus.find(x => x.tag === 'text').map(t => t.textContent);

// ============================================================================
sect(1, '① 接口：setMoveTrail 已导出，setLastMove 保留（向后兼容）');

chk(typeof C.setMoveTrail === 'function', 'setMoveTrail 已导出');
chk(typeof C.setLastMove === 'function', 'setLastMove 仍保留（旧调用点不会崩）');
chk(['lyr-hits', 'lyr-hints', 'lyr-pieces', 'lyr-focus'].every(cl => !!byCls(cl)),
  '四个动态图层齐全（按 class 查找，不再依赖 children 索引）',
  'hits/hints/pieces/focus');

// ============================================================================
sect(2, '② 两条虚线：一红一橙，且**红色压橙色之上**');

C.setMoveTrail([LAST, PREV]);
const lines = pick('line');
chk(lines.length === 2, '虚线 2 条（最近一手 + 再往前一手）', `实测 ${lines.length}`);

const idxRed = lines.findIndex(l => l.attrs.stroke === RED);
const idxOrg = lines.findIndex(l => l.attrs.stroke === ORANGE);
chk(idxRed >= 0 && idxOrg >= 0, '两条线分别用了红色与橙色',
  `实测 ${lines.map(l => l.attrs.stroke).join(' / ')}`);

const PL = xy('124'), QL = xy('125'), PP = xy('245');
const redL = lines[idxRed], orgL = lines[idxOrg];
chk(+redL.attrs.x1 === PP[0] && +redL.attrs.y1 === PP[1]
  && +redL.attrs.x2 === QL[0] && +redL.attrs.y2 === QL[1],
  '红线 = **最近一手** L5(245) → D5(125)');
chk(+orgL.attrs.x1 === PL[0] && +orgL.attrs.y1 === PL[1]
  && +orgL.attrs.x2 === QL[0] && +orgL.attrs.y2 === QL[1],
  '橙线 = **再往前一手** D4(124) → D5(125)');

const ciRed = gFocus.children.indexOf(redL), ciOrg = gFocus.children.indexOf(orgL);
chk(ciOrg < ciRed,
  '橙色（更早）先绘制 → 红色（最近）在 SVG 上层，最近一手更醒目',
  `橙 idx=${ciOrg} < 红 idx=${ciRed}`);

chk(String(redL.attrs['stroke-dasharray'] || '').split(' ').length >= 2
  && String(orgL.attrs['stroke-dasharray'] || '').split(' ').length >= 2,
  '两条都是**虚线**（stroke-dasharray 至少两段）');
chk(+redL.attrs['stroke-width'] > +orgL.attrs['stroke-width'],
  '红线比橙线粗（层级：最近 > 更早）',
  `红 ${redL.attrs['stroke-width']} / 橙 ${orgL.attrs['stroke-width']}`);
chk(+redL.attrs['stroke-opacity'] > +orgL.attrs['stroke-opacity'],
  '红线不透明度更高',
  `红 ${redL.attrs['stroke-opacity']} / 橙 ${orgL.attrs['stroke-opacity']}`);

// ============================================================================
sect(3, '③ 箭头：两个，各自指向自己的终点');

const polys = pick('polygon');
chk(polys.length === 2, '箭头 2 个', `实测 ${polys.length}`);
const aRed = polys.find(p => p.attrs.fill === RED);
const aOrg = polys.find(p => p.attrs.fill === ORANGE);
chk(!!aRed && !!aOrg, '两个箭头分别红 / 橙');
function tipDist(poly, Q) {
  const pts = String(poly.attrs.points).split(' ').map(s => s.split(',').map(Number));
  return { tip: pts[0], d: Math.hypot(pts[0][0] - Q[0], pts[0][1] - Q[1]), pts };
}
const tRed = tipDist(aRed, QL), tOrg = tipDist(aOrg, QL);
chk(tRed.d > 4.5 && tRed.d < 7.0, '红箭头尖停在红终点环之前',
  `实测 ${tRed.d.toFixed(2)}`);
chk(tOrg.d > 6.0 && tOrg.d < 8.0, '橙箭头尖停在橙终点环之前（比红更外，避免两箭头撞一起）',
  `实测 ${tOrg.d.toFixed(2)}`);
chk(tOrg.d > tRed.d, '橙箭头尖比红箭头尖更靠后（不重叠）');

// ============================================================================
sect(4, '④ 环形：橙整体大一圈 → 两手共用格点时是**同心双环**');

const circles = pick('circle');
chk(circles.length === 6, '圆 6 个（每手：起点虚线圈 1 + 终点实双环 2）',
  `实测 ${circles.length}`);
const cRed = circles.filter(c => c.attrs.stroke === RED);
const cOrg = circles.filter(c => c.attrs.stroke === ORANGE);
chk(cRed.length === 3 && cOrg.length === 3, '红 3 / 橙 3', `红 ${cRed.length} 橙 ${cOrg.length}`);

// 两手在 D5(125) 交汇：橙终点双环 vs 红终点双环 圆心相同 → 直接比半径
const orgAtQ = cOrg.filter(c => +c.attrs.cx === QL[0] && +c.attrs.cy === QL[1]);
const redAtQ = cRed.filter(c => +c.attrs.cx === QL[0] && +c.attrs.cy === QL[1]);
chk(orgAtQ.length === 2 && redAtQ.length === 2, '两手终点都在 D5（共用格点场景）');
const maxRed = Math.max(...redAtQ.map(c => +c.attrs.r));
const minOrg = Math.min(...orgAtQ.map(c => +c.attrs.r));
chk(minOrg > maxRed,
  '橙终点环**整体在红终点环之外** → 同心双环，两色都看得见',
  `红最大 r=${maxRed} / 橙最小 r=${minOrg}`);

// 起点：橙 D4 虚线圈 vs 红 L5 虚线圈 —— 都比棋子半径 4.05 大，否则被盖住
const dashC = circles.filter(c => c.attrs['stroke-dasharray']);
chk(dashC.length === 2, '起点虚线圈 2 个', `实测 ${dashC.length}`);
chk(dashC.every(c => +c.attrs.r >= 4.6),
  '两个起点虚线圈半径都 ≥ 4.6（棋子半径 4.05，小了会被完全盖住）',
  `实测 ${dashC.map(c => c.attrs.r).join('/')}`);
const orgStart = dashC.find(c => c.attrs.stroke === ORANGE);
const redStart = dashC.find(c => c.attrs.stroke === RED);
chk(+orgStart.attrs.r > +redStart.attrs.r,
  '橙起点圈比红起点圈大（同心时可辨）',
  `橙 ${orgStart.attrs.r} / 红 ${redStart.attrs.r}`);

// ============================================================================
sect(5, '⑤ 文字：红「起 L5 / 到 D5 吃士」，橙带「前」前缀且外推更远');

const tx = texts();
// 每手 2 个标签（起点 / 终点），**每个标签 1 层彩色字**（透明背景）⇒ 每手 2 个 text
chk(tx.length === 4, '文字 4 个（两手 × 起点/终点 × 各 1 层）', `实测 ${tx.length}`);
chk(tx.filter(s => s === '起 L5').length === 1, '红起点「起 L5」');
chk(tx.filter(s => s === '到 D5 吃士').length === 1,
  '红终点「到 D5 吃士」——最近一手吃了什么，一眼看清', `实测 ${JSON.stringify(tx)}`);
chk(tx.filter(s => s === '前起 D6').length === 1, '橙起点「前起 D6」（带「前」前缀）');
chk(tx.filter(s => s === '前到 D5').length === 1, '橙终点「前到 D5」');

const allTextEls = pick('text');
const orgTexts = allTextEls.filter(t => t.attrs.fill === ORANGE);
const redTexts = allTextEls.filter(t => t.attrs.fill === RED);
chk(orgTexts.length === 2 && redTexts.length === 2,
  '每人 2 个彩色字（起点 1 + 终点 1）',
  `橙 ${orgTexts.length} 红 ${redTexts.length}`);
chk(allTextEls.every(t => t.attrs.fill !== '#ffffff'),
  '★ 文字背景**透明**（老师 2026-10-01 指定）：没有任何白色填充层',
  `实测白色层 ${allTextEls.filter(t => t.attrs.fill === '#ffffff').length} 个`);
chk(allTextEls.every(t => t.attrs.stroke === 'none' || t.attrs.stroke == null),
  '★ 文字**没有描边**（老师 2026-10-01：「注意，不需要描边」）—— 纯单层彩色字',
  `实测 stroke=${allTextEls.map(t => t.attrs.stroke).join('/')}`);
chk(allTextEls.every(t => t.attrs['font-weight'] === 'normal'),
  '★ 字重 **normal**（老师 2026-10-01：「去白底后字体太粗了，是黑体太粗了」）',
  `实测 ${allTextEls.map(t => t.attrs['font-weight']).join('/')}`);
chk(orgTexts.every(t => +t.attrs['font-size'] < +redTexts[0].attrs['font-size']),
  '橙字**更小**（不与红字抢视线）',
  `橙 ${orgTexts[0].attrs['font-size']} / 红 ${redTexts[0].attrs['font-size']}`);

// 外推距离：橙终点字与红终点字同指 D5，但橙更远 → 不同心圆上叠字
const txtAtD5 = allTextEls.filter(t => t.textContent.includes('D5') && t.attrs.fill !== '#ffffff');
const dOf = t => Math.hypot(+t.attrs.x - QL[0], +t.attrs.y - QL[1]);
const dOrg = dOf(txtAtD5.find(t => t.attrs.fill === ORANGE));
const dRed = dOf(txtAtD5.find(t => t.attrs.fill === RED));
chk(dOrg > dRed + 1.5,
  '橙「到 D5」比红「到 D5」外推更远 → 两个标签不叠字',
  `橙 ${dOrg.toFixed(1)} vs 红 ${dRed.toFixed(1)}`);
chk(Math.abs(+txtAtD5[0].attrs.x) <= 112 && Math.abs(+txtAtD5[0].attrs.y) <= 100,
  '标签仍被夹在可视区内（防贴边被裁）');

// ============================================================================
sect(6, '⑥ 橙手吃子也要写清楚（「前到 XX 吃XX」）');

C.setMoveTrail([{ from: '132', to: '137', army: 1 },
                { from: '245', to: '125', army: 3, captured: 'advisor' }]);
const tx2 = texts();
chk(tx2.includes('前到 D5 吃士'),
  '橙手吃子 → 「前到 D5 吃士」', `实测 ${JSON.stringify(tx2)}`);
chk(tx2.includes('到 C3') && !tx2.some(s => s.startsWith('到 C3') && s.includes('吃')),
  '红手没吃子 → 「到 C3」不带「吃」字');

// ============================================================================
sect(7, '⑦ 签名缓存：认「两手整体」，不是只看最近一手');

C.setMoveTrail([LAST, PREV]);
const l0 = pick('line')[0];
C.setMoveTrail([LAST, PREV]);
chk(pick('line')[0] === l0, '两手完全相同 → **不重建**（元素对象仍是同一个）');

C.setMoveTrail([LAST, { from: '124', to: '126', army: 1 }]);
const l1 = pick('line')[0];
chk(l1 !== l0, '只改**橙手**（最近一手没动）也会重建 → 橙手变化不会被缓存吞掉');

C.setMoveTrail([{ from: '245', to: '125', army: 3 }, PREV]);
chk(pick('line')[0] !== l1, '只改红手也会重建');

C.setMoveTrail([LAST]);
const n1 = pick('line').length;
chk(n1 === 1, '从两手 → 单手会重建（否则残留橙色痕迹）', `实测 ${n1} 条线`);

// ============================================================================
sect(8, '⑧ 向后兼容：单手 / 空 / 非法值 —— 与旧版行为一致');

C.setLastMove(LAST);
chk(pick('line').length === 1 && pick('line')[0].attrs.stroke === RED,
  'setLastMove(单参数) 等价于「只有最近一手」→ 只有红线');
chk(texts().length === 2, '单手时文字 2 个（起 / 到，各 1 层）', `实测 ${texts().length}`);
chk(texts().every(s => !s.startsWith('前')), '单手时**没有**「前」前缀');

C.setMoveTrail([]);
chk(gFocus.children.length === 0, 'setMoveTrail([]) → 清空（新局不留旧痕迹）');
C.setMoveTrail(null);
chk(gFocus.children.length === 0, 'setMoveTrail(null) → 清空、不报错');
C.setMoveTrail([null, null]);
chk(gFocus.children.length === 0, '[null, null] → 清空、不报错');
C.setMoveTrail([LAST, null]);
chk(pick('line').length === 1, '红手有值 + 橙手为 null → 只画红线（缺手安全）',
  `实测 ${pick('line').length} 条`);

let threw = false;
try { C.setMoveTrail([{ from: '999', to: '888', army: 2 }, { from: '', to: '', army: 1 }]); }
catch (e) { threw = true; }
chk(!threw && gFocus.children.length === 0,
  '两手都是非法点位/空值 → 静默跳过，不抛异常');

threw = false;
try { C.setMoveTrail([{ from: '115', to: '115', army: 1 }, LAST]); } catch (e) { threw = true; }
chk(!threw && pick('line').length === 1,
  '红手零长度（起点=终点）→ 跳过该手，橙手照常画', `实测 ${pick('line').length} 条`);

// ============================================================================
sect(9, '⑨ 不干扰既有交互：热区仍 135 个、gFocus 仍是纯视觉层');

C.setMoveTrail([LAST, PREV]);
const clickables = svg.find(n => n.listeners && n.listeners.click);
chk(NPT === 135, '棋盘共 135 个点', `实测 ${NPT}`);
chk(clickables.length === NPT,
  `加了上两手标记后，带 click 的热区仍是 ${NPT} 个`, `实测 ${clickables.length}`);
chk(gFocus.attrs['pointer-events'] === 'none',
  'gFocus 设了 pointer-events:none → 绝不挡住点击');
chk(gFocus.find(n => n.listeners && Object.keys(n.listeners).length).length === 0,
  'gFocus 内部 0 个元素带事件监听 → 纯视觉层');

// ============================================================================
sect(10, '⑩ 重新 init 后签名缓存清零（否则"换棋盘/重画"会什么都不画）');

// 背景：签名缓存是模块级的。若 C.init() 重置了 svg，但缓存没清零，
//       下一句 setMoveTrail(同样的两手) 会误判"内容没变"→ 直接 return → 空白。
//       （2026-09-25 生成配色预览时真踩到：第二张图整块没有痕迹。）
const svg2 = new El('svg');
C.init(svg2);
// 【2026-10-01 改】原来用 `.filter(g).pop()` 取"最后一个 g" ⇒ 索引式隐式契约
//   （铁律 #148）：新增 AI 推荐层 `lyr-hint` 后，最后一个 g 变成了空的推荐层，
//   于是本节假失败（实测 0 条线）。⇒ 一律**按语义 class 查**。
const g2 = svg2.children.filter(c => c.tag === 'g' && c.attrs.class === 'lyr-focus')[0];
chk(!!g2, '新棋盘能按 class 找到 lyr-focus 图层');
chk(g2.children.length === 0, '新棋盘初始为空（干净起点）');
C.setMoveTrail([LAST, PREV]);          // 与第 2 节**完全相同**的两手
chk(g2.find(x => x.tag === 'line').length === 2,
  '★ 重新 init 后，**同签名**的两手仍会被画出来（缓存已清零）',
  `实测 ${g2.find(x => x.tag === 'line').length} 条线`);
chk(g2.find(x => x.tag === 'circle').length === 6,
  '重画后 6 个环都在', `实测 ${g2.find(x => x.tag === 'circle').length}`);
// 顺带验证 setLegal 的缓存也一并清零
C.setLegal('115', ['125']);
const gHints2 = svg2.children.filter(c => c.tag === 'g' && c.attrs.class === 'lyr-hints')[0];
chk(gHints2.children.length > 0, 'setLegal 的提示也照常画出（提示缓存同样清零）',
  `实测 ${gHints2.children.length} 个子元素`);

// ============================================================================
console.log('\n' + '='.repeat(74));
console.log(`合计 ${ok} 通过 / ${bad} 失败`);
console.log('='.repeat(74));
process.exit(bad ? 1 : 0);
