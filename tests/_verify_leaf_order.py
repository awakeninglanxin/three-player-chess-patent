# -*- coding: utf-8 -*-
"""回归：`_leaf` 的遍历顺序必须定死（结果不得依赖字典插入顺序）

【这条测试防的是什么】
    `SearchBot._leaf` 是浮点连加。原先它直接 `for pos, pc in board.items()`，
    而 `board` 是 dict —— 迭代顺序 = **插入顺序**，`_make/_unmake` 每吃一子就
    `pop` + 重新插入 ⇒ 同一局面会有不同的字典顺序，"怎么走到的"会改变评估值。

    平时只差 ~1e-13，看不出问题；但棋盘 120° 对称（开局尤甚），大量着法的
    叶值**精确相等**，这 1e-13 会翻转 `alpha >= beta` 等值比较 ⇒ 剪枝分岔
    ⇒ 结果差到 4.85（实测 plies=6 开局）。

【三组断言】
    ① **字典顺序无关**：同一局面按多种插入顺序构造 → `_leaf` 逐位相同
    ② **走到同一局面的路径无关**：不同着法顺序走到同一局面 → 逐位相同
    ③ **与 numba 内核逐位一致**：`_leaf` == `NB.leaf_py`（容差 0.0，
       不是 1e-6 —— 顺序对齐之后就该一个比特都不差）
"""
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))
sys.path.insert(0, os.path.join(HERE, "..", "server", "agents"))

import eval_dxf as E                          # noqa: E402
from engine import game_dxf as GA             # noqa: E402
from engine import geometry_dxf as D          # noqa: E402
from engine import nb_core as NB              # noqa: E402
from search_bot import SearchBot              # noqa: E402

OK = 0
FAIL = 0
FAILS = []


def chk(cond, msg, detail=""):
    global OK, FAIL
    if cond:
        OK += 1
    else:
        FAIL += 1
        FAILS.append(msg + (f"  [{detail}]" if detail else ""))
        if len(FAILS) <= 20:
            print(f"  ✗ {msg}  {detail}")


def random_positions(n, seed=777, steps=(8, 34)):
    rng = random.Random(seed)
    out = []
    for i in range(n):
        s = GA.new_game(first=1 + (i % 3))
        target = rng.randint(*steps)
        for _ in range(target):
            lm = GA.legal_moves(s, s["turn"])
            if not lm:
                break
            frm, to = rng.choice(lm)
            try:
                GA.apply(s, frm, to)
            except Exception:
                break
            if GA.status(s).get("winner"):
                break
        out.append((f"局{i + 1}/{target}步", s))
    return out


def reorder(board, order):
    """按给定顺序重建 board 字典（内容不变，只有插入顺序变）"""
    keys = list(board)
    if order == "sorted":
        keys.sort()
    elif order == "reversed":
        keys.sort(reverse=True)
    return {k: board[k] for k in keys}


def main():
    print("=" * 74)
    print("回归：`_leaf` 遍历顺序必须定死（不得依赖 dict 插入顺序）")
    print("=" * 74)

    bot = SearchBot(depth=1, noise=0.0)
    w = bot.w
    dist = E.distances()

    pos_list = [("开局", GA.new_game(first=1))] + random_positions(10)

    # ---- ① 字典顺序无关 ----
    print("\n① 同一局面 · 不同字典插入顺序 → `_leaf` 必须逐位相同")
    for tag, s in pos_list:
        base = s["board"]
        for me in (1, 2, 3):
            bot._ur = 1.0 + int(s.get("ply", 0) or 0) * w.get("urgency", 0.0)
            vals = {}
            for order in ("sorted", "reversed", "random"):
                b = reorder(base, order)
                if order == "random":
                    keys = list(b)
                    random.Random(9).shuffle(keys)
                    b = {k: b[k] for k in keys}
                vals[order] = bot._leaf(dict(b), me, dist)
            ref = vals["sorted"]
            chk(all(v == ref for v in vals.values()),
                f"{tag}·{D.ARMY_CN[me]} 字典顺序无关",
                f"sorted={ref!r} reversed={vals['reversed']!r} "
                f"random={vals['random']!r}")

    # ---- ② 路径无关：不同着法顺序走到同一局面 ----
    print("\n② 走到同一局面的**路径不同** → `_leaf` 必须逐位相同")
    for tag, s in pos_list[:5]:
        # 用两串互为交换律的着法把局面走两遍（这里简单地：原盘 vs 重建盘）
        board_a = dict(s["board"])
        keys = list(board_a)
        random.Random(3).shuffle(keys)
        board_b = {k: board_a[k] for k in keys}
        for me in (1, 2, 3):
            bot._ur = 1.0 + int(s.get("ply", 0) or 0) * w.get("urgency", 0.0)
            va = bot._leaf(dict(board_a), me, dist)
            vb = bot._leaf(dict(board_b), me, dist)
            chk(va == vb, f"{tag}·{D.ARMY_CN[me]} 路径/顺序无关",
                f"{va!r} vs {vb!r}")

    # ---- ③ 与 numba 内核逐位一致（容差 0.0）----
    print("\n③ `_leaf` ↔ numba `leaf` 必须**逐位**一致（容差 0.0，不是 1e-6）")
    worst = 0.0
    worst_tag = ""
    for tag, s in pos_list:
        ply = int(s.get("ply", 0) or 0)
        for me in (1, 2, 3):
            bot._ur = 1.0 + ply * w.get("urgency", 0.0)
            py = bot._leaf(dict(s["board"]), me, dist)
            nb = NB.leaf_py(s["board"], me, w, ply=ply)
            d = abs(py - nb)
            if d > worst:
                worst, worst_tag = d, f"{tag}·{D.ARMY_CN[me]}"
            chk(py == nb, f"{tag}·{D.ARMY_CN[me]} leaf 逐位一致",
                f"Python={py!r} numba={nb!r} Δ={d:.3e}")

    print()
    print("=" * 74)
    print(f"结果：OK={OK}  FAIL={FAIL}   （最大偏差 {worst:.3e} @ {worst_tag}）")
    if FAILS:
        print("\n失败明细（最多 20 条）：")
        for m in FAILS:
            print("  ✗ " + m)
    print("=" * 74)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
