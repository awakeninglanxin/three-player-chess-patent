/* 临时预览：把 board.js 的「上两手」渲染结果导成静态 SVG/HTML，供人工/截图核对配色
   运行：node tests/_render_trail_preview.js
   输出：tests/_trail_preview.html（浏览器直接打开即可看两张对照图）
   用途：颜色对比度、同心双环是否可辨、标签是否叠字 —— 只能靠看，不能靠推断。
*/
const fs = require('fs');
const path = require('path');
const ROOT = path.join(__dirname, '..');

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
  find(pred, out) {
    out = out || [];
    if (pred(this)) out.push(this);
    this.children.forEach(c => c.find(pred, out));
    return out;
  }
}
global.document = {
  createElementNS: (ns, tag) => new El(tag),
  querySelector: () => null, querySelectorAll: () => [],
  getElementById: () => new El('div'),
  addEventListener: () => { }, readyState: 'loading'
};
global.window = global;
global.sessionStorage = { getItem: () => null, setItem: () => { }, removeItem: () => { } };
global.setInterval = () => 0;

eval(fs.readFileSync(path.join(ROOT, 'web', 'board_data.js'), 'utf8'));
eval(fs.readFileSync(path.join(ROOT, 'web', 'board.js'), 'utf8'));
const C = window.ChessBoard;

const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
function ser(n) {
  const a = Object.keys(n.attrs)
    .map(k => `${k}="${esc(n.attrs[k])}"`).join(' ');
  const head = `<${n.tag}${a ? ' ' + a : ''}>`;
  const inner = n._text ? esc(n._text) : n.children.map(ser).join('');
  return head + inner + `</${n.tag}>`;
}

function fig(title, note, moves) {
  const svg = new El('svg');
  C.init(svg);
  C.renderPieces([]);          // 只看痕迹，不叠棋子（免得棋子挡住虚线）
  C.setMoveTrail(moves);
  return `<section>
  <h2>${title}</h2>
  <p>${note}</p>
  <div class="frame">${ser(svg)}</div>
</section>`;
}

// 局部放大：把 viewBox 换成"以某个格点为中心的小窗口"，专看细节
function zoom(label, moves, center, span) {
  const svg = new El('svg');
  C.init(svg);
  C.renderPieces([]);
  C.setMoveTrail(moves);
  const q = window.BOARD_DATA.points[center];
  const vb = `${(q[0] - span / 2).toFixed(1)} ${(-q[1] - span / 2).toFixed(1)} ${span} ${span}`;
  const s = ser(svg).replace('viewBox="-124 -108 248 216"', `viewBox="${vb}"`)
    .replace('<svg', '<svg class="zoomed"');
  return `<div class="zoomwrap"><div class="zlabel">${label}</div>
    <div class="frame">${s}</div></div>`;
}

// 场景 1：两手**共用格点**（士 D6→D5，随后炮 L5→D5 吃士）—— 考验同心双环是否可辨
const M1 = [{ from: '245', to: '125', army: 3, captured: 'advisor' },
            { from: '124', to: '125', army: 1 }];
const f1 = fig('场景 1 · 两手终点同在 D5（同心双环）',
  '橙色＝再往前一手（前起 D6 → 前到 D5）；红色＝最近一手（起 L5 → 到 D5 吃士）。' +
  '两手终点同格，橙色环应整体套在红色环外面，两色都看得见。',
  M1) + zoom('场景 1 局部放大（D5 四周，双臂 + 同心环）', M1, '125', 46);

// 场景 2：两手离得远（真实对局抓的那两手）—— 考验两种颜色会不会互相抢视线
const M2 = [{ from: '135', to: '345', army: 1, captured: 'pawn' },
            { from: '338', to: '122', army: 3 }];
const f2 = fig('场景 2 · 两手相距较远（红吃兵 / 橙普通走子）',
  '红＝魏 135→345 吃兵；橙＝蜀 338→122。两条虚线、两个『前』前缀标签应各自清楚。',
  M2) + zoom('场景 2 局部放大（D5 附近的红终点）', M2, '345', 46);

// 场景 3：只有一手（对局第一手后的样子）—— 应完全不出现橙色
const f3 = fig('场景 3 · 只有一手（对局刚开始）',
  '只应有红色一手，盘面上不该出现任何橙色（否则说明橙色残留）。',
  [{ from: '115', to: '125', army: 1 }]);

// 说明：--zoom-only 只输出三张局部放大图（便于截图后逐张核对细节）
const only = process.argv.includes('--zoom-only');
const body = only
  ? (zoom('场景 1 局部 · 红起点 L5（246）', M1, '245', 46)
     + zoom('场景 1 局部 · 双臂终点 D5（125，同心双环）', M1, '125', 46)
     + zoom('场景 2 局部 · 红终点 345（吃兵）', M2, '345', 46))
  : (f1 + f2 + f3);

const html = `<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>上两手走子痕迹 · 配色预览</title>
<style>
  body{margin:0;padding:24px;background:#2b2b2b;color:#eee;
       font-family:"Microsoft YaHei",sans-serif}
  h1{font-size:20px;margin:0 0 4px}
  .lead{color:#aaa;font-size:13px;margin:0 0 22px}
  section{background:#3a3a3a;border-radius:10px;padding:16px;margin-bottom:22px}
  h2{font-size:16px;margin:0 0 6px;color:#ffd479}
  p{font-size:13px;color:#bbb;margin:0 0 12px;line-height:1.7}
  .frame{background:#f6efe1;border-radius:8px;padding:8px;display:inline-block;vertical-align:top}
  svg{width:820px;height:auto;display:block}
  svg.zoomed{width:760px}
  .zoomwrap{margin-top:12px}
  .zlabel{font-size:12px;color:#ffd479;margin:0 0 6px}
</style></head>
<body>
<h1>上两手走子痕迹 · 配色预览</h1>
<p class="lead">红色 = 最近一手（老师已认可）；橙色 = 再往前一手（2026-09-25 新增）。
本页由 tests/_render_trail_preview.js 从 web/board.js 真跑生成，未叠棋子以便看清虚线。</p>
${body}
</body></html>`;

const out = path.join(__dirname, only ? '_trail_zoom.html' : '_trail_preview.html');
fs.writeFileSync(out, html, 'utf8');
console.log('已生成预览：' + out);
