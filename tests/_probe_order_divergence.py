# -*- coding: utf-8 -*-
"""探针：宽度截断分歧是不是「_order 同分平局」造成的？

【假设】
    Python `_order` 用 `out.sort(reverse=True)`（**稳定排序**）
      ⇒ 分数相同的着法保持**生成顺序**；而生成顺序 = `board.items()` 的
        **dict 插入顺序**（会随吃子/悔子的 `del`/重新插入而改变）
    JIT `_order` 用插入排序 + `MVB[base+j] < m`
      ⇒ 同分强制**打包整数（from<<8|to）降序**

    两者只在"同分"时分歧 —— 而首次进入某层时，所有安静着法的历史分都是 0.0，
    **全部分数相同** ⇒ 平局极多 ⇒ 宽度截断截掉的就是不同的一批着法
    ⇒ 深层 minimax 值不同 ⇒ 根分数差 0.2~0.5（遇到杀棋就是 1e6 级差）。

【怎么验】
    把 Python 侧的 `_order` 猴补丁成"先按分数降序、同分按打包整数降序"
    （= JIT 的口径），再跑同一批局面的对拍：
      · 若分数立刻一致到 1e-14 ⇒ 假设成立（分歧源就是平局口径）
      · 若仍差 ⇒ 假设不成立，另有原因

另附：直接打印两边 `_order` 的结果做逐项对照（最直观）。
"""
import os
import random
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))
sys.path.insert(0, os.path.join(HERE, "..", "server", "agents"))

import eval_dxf as E                          # noqa: E402
from engine import game_dxf as GA             # noqa: E402
from engine import geometry_dxf as D          # noqa: E402
from engine import nb_core as NB              # noqa: E402
from engine import rules_dxf as R             # noqa: E402
from search_bot import SearchBot              # noqa: E402

POS = NB.POS                                   # '154' -> 0..134（= D.BOARD.ids 序号）


def packed(mv):
    return (POS[mv[0]] << 8) | POS[mv[1]]


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


def py_side_moves(board, army):
    """按 Python `_search` 的口径生成某一方的着法（含顺序）"""
    out = []
    for pos, pc in board.items():
        if pc["army"] != army:
            continue
        for q in R.moves_of(board, pos, pc):
            out.append((pos, q))
    return out


def jit_side_moves(board, army):
    code = NB.encode_board(board)
    n = int(NB.gen_side(code, np.int32(army), NB._SEARCHSCR.mvb,
                        NB._SEARCHSCR.stamp, NB._SEARCHSCR.ctr))
    return [(NB.IDX2POS[int(NB._SEARCHSCR.mvb[i]) >> 8],
             NB.IDX2POS[int(NB._SEARCHSCR.mvb[i]) & 255]) for i in range(n)]


def sec1_generation_order(pos_list):
    """① 两边的**原始生成顺序**是否一致（不含排序）"""
    print("=" * 72)
    print("① 原始生成顺序对照（Python board.items() vs JIT range(N)）")
    print("=" * 72)
    n_diff = 0
    for tag, s in pos_list:
        board = dict(s["board"])
        for army in (1, 2, 3):
            a = py_side_moves(board, army)
            b = jit_side_moves(board, army)
            if set(a) != set(b):
                print(f"  ✗ {tag}·{D.ARMY_CN[army]} 集合就不一致！")
                n_diff += 1
                continue
            if a != b:
                n_diff += 1
                i = next(i for i in range(len(a)) if a[i] != b[i])
                print(f"  · {tag}·{D.ARMY_CN[army]} 顺序不同 "
                      f"(共{len(a)}手, 首个不同在第{i}位) "
                      f"Py={a[i][0]}-{a[i][1]} JIT={b[i][0]}-{b[i][1]}")
    print(f"  → 生成顺序不一致的「局面·方」共 {n_diff} 处"
          f"（{'存在 ⇒ 平局口径必不同' if n_diff else '完全一致'}）")


def sec2_order_compare(pos_list):
    """② 直接对比一次 `_order` 的结果（root 层，hist/kill 全空）"""
    print()
    print("=" * 72)
    print("② 一次 `_order`（root 层，历史/杀手全空）结果逐项对照")
    print("=" * 72)
    bot = SearchBot(depth=1)
    sc = NB._SEARCHSCR
    cx = 0
    for tag, s in pos_list[:4]:
        for army in (1, 2, 3):
            bot._hist = {}
            bot._killers = {}
            board = dict(s["board"])
            pyr = bot._order(board, py_side_moves(board, army), army, 3)
            code = NB.encode_board(board)
            n = int(NB.gen_side(code, np.int32(army), sc.mvb, sc.stamp, sc.ctr))
            NB._order(code, sc.mvb, sc.scb, 0, n, np.int32(army), np.int32(3),
                      sc.hist, sc.kill)
            jit = [(NB.IDX2POS[int(sc.mvb[i]) >> 8], NB.IDX2POS[int(sc.mvb[i]) & 255])
                   for i in range(n)]
            same = (pyr == jit)
            cx += 0 if same else 1
            firsts = ""
            if not same:
                i = next(i for i in range(len(pyr)) if pyr[i] != jit[i])
                firsts = f" 首个不同第{i}位 Py={pyr[i][0]}-{pyr[i][1]} JIT={jit[i][0]}-{jit[i][1]}"
            print(f"  {'✓' if same else '✗'} {tag}·{D.ARMY_CN[army]}  "
                  f"n={len(pyr)} 排序{'一致' if same else '不同'}{firsts}")
    print(f"  → 排序不一致 {cx} 处")


def sec3_patched_parity(pos_list):
    """③ 猴补丁 Python `_order` 用 JIT 口径 → 看分数是否立刻一致"""
    print()
    print("=" * 72)
    print("③ 猴补丁：Python `_order` 改成「同分按打包整数降序」（= JIT 口径）")
    print("=" * 72)

    orig = SearchBot._order

    def order_jit_style(self, board, moves, viewer, plies=0):
        """与 JIT `_order` 同口径：先按分数降序、同分按 (from<<8|to) 降序"""
        hist = self._hist
        k = self._killers.get(plies)
        k1 = k[0] if k else None
        k2 = k[1] if k and len(k) > 1 else None
        out = []
        for mv in moves:
            vic = board.get(mv[1])
            if vic is None:
                h = hist.get(mv, 0.0)
                if mv == k1:
                    s = 500000.0 + h
                elif mv == k2:
                    s = 400000.0 + h
                else:
                    s = h
            elif vic["kind"] == R.GENERAL:
                s = 1e9
            elif vic["army"] == viewer:
                s = -1e5
            else:
                s = 1e6 + R.VALUE[vic["kind"]] * 100.0
            out.append((s, packed(mv), mv))
        # 分数降序 → 打包整数降序（与 JIT 插入排序的判据逐字一致）
        out.sort(key=lambda x: (-x[0], -x[1]))
        return [mv for _s, _p, mv in out]

    SearchBot._order = order_jit_style
    try:
        bot = SearchBot(depth=1)
        w = bot.w
        for plies in (3, 6):
            print(f"\n  --- plies={plies} ---")
            worst = 0.0
            n_same = 0
            n_tot = 0
            nsame_set = 0
            for tag, s in pos_list:
                for me in (1, 2, 3):
                    legal = list(GA.legal_moves(s, me))
                    if not legal:
                        continue
                    bot._deadline = 1e18
                    bot.nodes = 0
                    bot._hist = {}
                    bot._killers = {}
                    bot._ply = int(s.get("ply", 0) or 0)
                    bot._ur = 1.0 + bot._ply * bot.w.get("urgency", 0.0)
                    alive = frozenset(bot._gen_alive(s["board"]))
                    board = dict(s["board"])
                    pmv, psc, pranked = bot._root_search(
                        board, legal, alive, plies, me, E.distances(), exact=True)
                    bmv, bsc, branked, bnodes, ab = NB.search_plies(
                        s["board"], me, plies, w, legal,
                        ply_no=int(s.get("ply", 0) or 0),
                        time_limit=600.0, exact=True, reset=True)
                    if ab:
                        print(f"    ✗ {tag}·{D.ARMY_CN[me]} JIT 超时")
                        continue
                    n_tot += 1
                    d = abs(psc - bsc)
                    worst = max(worst, d)
                    n_same += 1 if pmv == bmv else 0
                    pmap = {(f, t): v for v, (f, t) in pranked}
                    bmap = {(f, t): v for f, t, v in branked}
                    if set(pmap) == set(bmap):
                        nsame_set += 1
                    print(f"    {tag}·{D.ARMY_CN[me]}  "
                          f"Py={psc:14.6f} JIT={bsc:14.6f}  Δ={d:.3e}  "
                          f"{'best一致' if pmv == bmv else 'best不同'}")
            print(f"  → plies={plies}: 最大分数偏差 {worst:.3e}，"
                  f"best 完全一致 {n_same}/{n_tot}，"
                  f"根着法集合一致 {nsame_set}/{n_tot}")
    finally:
        SearchBot._order = orig


def main():
    pos_list = random_positions(8)
    pos_list.insert(0, ("开局", GA.new_game(first=1)))
    print(f"局面数：{len(pos_list)}")
    print()
    sec1_generation_order(pos_list)
    sec2_order_compare(pos_list)
    sec3_patched_parity(pos_list)
    print()
    print("=" * 72)
    print("结论判读：")
    print("  · 若 ③ 的最大偏差降到 ~1e-14 ⇒ 分歧源 = `_order` 平局口径（假设成立）")
    print("  · 此时正确做法：把 JIT 的平局口径**改成与 Python 一致**，")
    print("    或者（更稳）给 Python 侧也加一条**确定性**平局键 ——")
    print("    因为 Python 的 `board.items()` 插入顺序会随吃子/悔子变化，")
    print("    本身就不是稳定口径，靠它做对拍基线是不可复现的。")
    print("=" * 72)


if __name__ == "__main__":
    main()
