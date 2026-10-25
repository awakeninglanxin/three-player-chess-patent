# -*- coding: utf-8 -*-
"""验证：三方同时无合法着法时，match.step() 的「判和」是否真的会终止对局。

背景：match.py:167
    def _finished(self):
        return self.state["winner"] or self.state["ply"] >= self.opts.get("max_ply", 240)

match.py:317-324（step 开头）
    legal = GA.legal_moves(s, army)
    if not legal:
        GA._advance(s)                     # 换下一方
        legal = GA.legal_moves(s, s["turn"])
        self.log.append({"type": "pass", ...})
        if not legal:
            self.log.append({"type": "draw", "text": "三方均无法取胜，判和"})
            return                          # ← 只 log，不写 winner、不推 ply

疑点：draw 之后 _finished() 仍为 False，_loop() 会再次 step() → 是否无限刷 draw？
"""
import os
import sys

_ROOT = r"D:/AAA我的文件/中国三人象棋_专利版"
sys.path.insert(0, os.path.join(_ROOT, "server"))

import match as M                                     # noqa: E402
import engine.game_dxf as GA                          # noqa: E402

m = M.Match(auto=False)
m.alive = False                                       # 停掉后台循环，纯手动驱动

print("初始: ply=%d winner=%r finished=%r" % (
    m.state["ply"], m.state["winner"], m._finished()))

# 让任何一方都查不到合法着法 → 模拟「三方均无法取胜」
# 循环体复刻 match._loop() 的守卫顺序（这才是真实被调用的路径）
_orig = GA.legal_moves
GA.legal_moves = lambda s, a: []
try:
    for i in range(4):
        if m._finished() or m.state["winner"]:         # ← _loop() 的守门条件
            print("第 %d 次进入循环：_finished()=True → 不再 step()，循环退出 ✓" % (i + 1))
            break
        n0 = len(m.log)
        m.step()
        added = m.log[-1] if len(m.log) > n0 else None
        print("第 %d 次 step(): log +%d | 末条=%s | finished=%r | drawn=%r | ply=%d"
              % (i + 1, len(m.log) - n0,
                 (added or {}).get("type"), m._finished(), m.drawn,
                 m.state["ply"]))
finally:
    GA.legal_moves = _orig

n_draw = sum(1 for e in m.log if e.get("type") == "draw")
print("\n判和日志条数 =", n_draw, "（修复后应为 1，不再无限重复刷）")
print("_finished() =", m._finished(), "| snapshot['drawn'] =", m.snapshot().get("drawn"))

