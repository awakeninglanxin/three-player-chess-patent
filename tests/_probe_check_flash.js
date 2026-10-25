/* 探针：真跑 app.js 的 flashCheck()，看**大字**（主标题）实际写的是什么。
 *
 * 老师 2026-10-01：「『副标题写明哪一方被哪一方将』要显示在屏幕前**大字**」
 *   ⇒ 断言主标题 = 「X方主帅被Y方、Z方将军」，副标题 = 「将军!!!」。
 *
 * 手法沿用项目既定铁律：前端 IIFE 内部函数没法直接测 ⇒
 *   把源码尾部 `})();` 换成 `window.__t = {...}; })();` 再 eval（**只改内存字符串，不动生产代码**），
 *   配合最小 DOM 桩（按 id 缓存元素），**真调用**函数看结果。
 *
 * 用法：node tests/_probe_check_flash.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const SRC = path.join(__dirname, '..', 'web', 'app.js');
let code = fs.readFileSync(SRC, 'utf8');

// ---- 暴露内部函数（只改内存字符串） ----
if (!/window\.__t\s*=/.test(code)) {
  code = code.replace(/\}\)\(\);\s*$/,
    '  window.__t = { flashCheck: flashCheck, checkAlarm: checkAlarm, ARMY: ARMY };\n})();');
}

// ---- 最小 DOM 桩：按 id 缓存元素 ----
const els = {};
function mkEl(id) {
  return {
    id: id, textContent: '', innerHTML: '', hidden: true, checked: false,
    value: '', dataset: {}, style: {}, offsetWidth: 100,
    classList: { _s: new Set(), add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); },
                 contains(c) { return this._s.has(c); }, toggle() {} },
    addEventListener() {}, removeEventListener() {}, appendChild() {}, setAttribute() {},
    querySelector() { return null; }, querySelectorAll() { return []; },
    getBoundingClientRect() { return { left: 0, top: 0, width: 100, height: 100 }; },
    focus() {}, blur() {}, closest() { return null; },
  };
}
const document = {
  getElementById(id) { return els[id] || (els[id] = mkEl(id)); },
  querySelector() { return null; }, querySelectorAll() { return []; },
  createElement(tag) { return mkEl('#' + tag); },
  addEventListener() {}, removeEventListener() {},
  body: mkEl('body'), documentElement: mkEl('html'),
};
const window = { document, ChessBoard: { label: p => p }, localStorage: undefined,
                 AudioContext: undefined, webkitAudioContext: undefined,
                 addEventListener() {} };

const ctx = { window, document, console, setTimeout, clearTimeout, setInterval: () => 0,
              clearInterval: () => {}, Math, Date, JSON, Object, Array, String, Number, RegExp };
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(code, ctx);

if (!ctx.window.__t || !ctx.window.__t.flashCheck) {
  console.log('FAIL 未能暴露 flashCheck —— 尾部替换失败');
  process.exit(1);
}
const T = ctx.window.__t;

let ok = 0, fail = 0;
function eq(actual, expect, label) {
  const good = actual === expect;
  good ? ok++ : fail++;
  console.log(`${good ? '  OK  ' : ' FAIL '} ${label}\n        实际 = ${JSON.stringify(actual)}`);
  if (!good) console.log(`        期望 = ${JSON.stringify(expect)}`);
}

const CASES = [
  { army: 1, atk: [2], label: '魏被吴单方将军' },
  { army: 3, atk: [1, 2], label: '蜀被魏、吴两方同时将军' },
  { army: 2, atk: [1], label: '吴被魏将军' },
  { army: 1, atk: [], label: '异常兜底：叫将方为空时不能出现「被方将军」' },
];

console.log('=== flashCheck() 主标题（屏幕大字）实测 ===\n');
for (const c of CASES) {
  T.flashCheck(c.army, c.atk.slice());
  const main = (els['checkFlashMain'] || {}).textContent;
  const sub = (els['checkFlashSub'] || {}).textContent;
  const CN = { 1: '魏', 2: '吴', 3: '蜀' };
  const expMain = CN[c.army] + '方主帅被'
    + (c.atk.length ? c.atk.map(x => CN[x]).join('、') : '?') + '方将军';
  console.log(`【${c.label}】`);
  eq(main, expMain, '大字 = 哪一方被哪一方将');
  eq(sub, '将军!!!', '副标题 = 固定「将军!!!」');
  eq(!!els['checkFlash'].hidden === false, true, '弹窗已显示（hidden=false）');
  console.log(`        弹窗文案渲染为： 「${main}」 / 小字「${sub}」`);
  console.log();
}

console.log('=== 关键回归：主标题不再恒为「将军!!!」 ===');
T.flashCheck(3, [1, 2]);
eq(els['checkFlashMain'].textContent !== '将军!!!', true, '大字已随被将方变化（不是固定的将军!!!）');
eq(els['checkFlashSub'].textContent === '将军!!!', true, '「将军!!!」确实降到了副标题');

console.log(`\n结果：OK=${ok}  FAIL=${fail}`);
process.exit(fail ? 1 : 0);
