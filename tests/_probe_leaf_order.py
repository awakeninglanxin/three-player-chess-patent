# -*- coding: utf-8 -*-
"""探针⑩：**根因验证** —— `leaf` 的浮点求和顺序就是最后那点分歧的来源

【推理链（前九个探针依次排除后剩下的唯一解释）】
    · 排除：着法生成（3514/0）、编码往返、攻击表、权重表、KV 表
    · 排除：排序平局口径（6900 次随机状态试验，0 处不同）
    · 排除：下标越界（NUMBA_BOUNDSCHECK=1 全绿）
    · 排除：`_order` 的状态依赖（同上）
    · 现象：**只有「开局」这种 120° 完全对称的棋形**在 plies=6 分歧；
            不对称的「局1/15步」在 plies=6 三方全一致
    · 而且：分歧是**跑完第 1 手就出现**（HIST/KILL 状态已不同）

    ⇒ 唯一剩下的：两边 `leaf` 的**浮点求和顺序**不同。
      Python 按 `board.items()`（**字典插入顺序**，会吃子/悔子历史影响）
      JIT    按 `range(N)`（**点位序号顺序**，恒定）
      两者差 ~1e-13。在**完全对称**的棋形里，大量着法的叶值**精确相等**，
      这 1e-13 就足以翻转 `alpha >= beta` / `v > best` 这类等值比较
      ⇒ 剪枝路径分岔 ⇒ HIST/KILL 分岔 ⇒ 宽度截断截掉的着法不同 ⇒ 值出现差异。
      这与"不同编译器给出不同浮点结果"是同一类现象，**不是逻辑抄错**。

【验证做法】
    把 Python 的 `_leaf` 猴补丁成「先 `sorted(board.items())` 再累加」
    —— 也就是 JIT 的求和顺序 —— 重跑 plies=6 对照：
      · 若偏差立刻降到 ~1e-13 ⇒ 根因确认，且**修法明确**：
        把 `SearchBot._leaf` 的遍历顺序定死（顺便让 Python 引擎自身
        的结果不再依赖"吃子历史造成的字典顺序"，可复现性也一并提升）
      · 若还差 ⇒ 推理链还有洞，继续查
"""
import collections
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

INF = 1e9


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


def leaf_sorted(self, board, me, dist):
    """与 `SearchBot._leaf` 逐行相同，**只把遍历顺序改成按点位排序**

    与 JIT 的 `for pos in range(N)` 一致 ⇒ 浮点加法顺序一致 ⇒ 结果逐位一致。
    """
    w = self.w
    gens = {}
    by_army = {}
    mat = {}
    deputies = 0
    for pos, pc in sorted(board.items()):          # ★ 唯一改动
        a = pc["army"]
        k = pc["kind"]
        if k == "general":
            if pc.get("deputy"):
                if pc["home"] == me:
                    deputies += 1
            else:
                gens[pc["home"]] = pos
            continue
        by_army.setdefault(a, []).append((pos, k))
        mat[a] = mat.get(a, 0.0) + R.VALUE[k]

    my_gen = gens.get(me)
    if my_gen is None:
        return -1e6

    mine = by_army.get(me, [])
    dgr = w["danger"]
    maxd = E.MAX_DIST
    ur = self._ur
    wprs = ur * w["pressure"]
    sc = 0.0
    c1 = ur * w.get("close1", 0.0)
    c2 = ur * w.get("close2", 0.0)
    wchk = ur * w.get("check", 0.0)
    sv = E._SQRT_VALUE
    for enemy, gpos in gens.items():
        if enemy == me:
            continue
        dmap = dist[gpos]
        atk = R.ATK_BY.get(gpos) if wchk else None
        chk = False
        for pos, k in mine:
            d = dmap[pos]
            sc += wprs * sv[k] * (maxd - d)
            if d <= 1:
                sc += c1
            elif d == 2:
                sc += c2
            if atk is not None and not chk:
                specs = atk.get(pos)
                if specs is not None:
                    pc = board[pos]
                    for kind, extra in specs:
                        if kind == k and R._hit(board, pos, pc, kind, extra,
                                                gpos):
                            chk = True
                            break
        if chk:
            sc += wchk

    dmap = dist[my_gen]
    for enemy in gens:
        if enemy == me:
            continue
        for pos, k in by_army.get(enemy, []):
            sc -= dgr * R.VALUE[k] * (maxd - dmap[pos])

    for a in (1, 2, 3):
        if a != me and a not in gens:
            sc += 4000.0

    my_mat = mat.get(me, 0.0)
    top = 0.0
    for enemy in gens:
        if enemy != me:
            m = mat.get(enemy, 0.0)
            if m > top:
                top = m
    sc += w["material"] * (my_mat - top)
    sc += w["deputy"] * deputies
    return sc


def run(pos_list, plies, label):
    bot = SearchBot(depth=1, noise=0.0)
    w = bot.w
    worst = 0.0
    n_bad = 0
    n_tot = 0
    details = []
    for tag, s in pos_list:
        for me in (1, 2, 3):
            legal = list(GA.legal_moves(s, me))
            if not legal:
                continue
            bot.width = dict(SearchBot(depth=1, noise=0.0).width)   # ⚠️ 是**宽度表**
            # ⚠️ 早先写成 `dict(w)`（w 是权重表）⇒ Python 侧 `width.get(plies, 5)`
            #    全部回落到 5，而 JIT 用 14/10/8/6/5/4 ⇒ 整轮对比报废（已踩）。
            bot._deadline = 1e18
            bot.nodes = 0
            bot._hist = {}
            bot._killers = {}
            bot._ply = int(s.get("ply", 0) or 0)
            bot._ur = 1.0 + bot._ply * w.get("urgency", 0.0)
            alive = frozenset(bot._gen_alive(s["board"]))
            _pmv, psc, _pr = bot._root_search(
                dict(s["board"]), legal, alive, plies, me, E.distances(),
                exact=True)
            _bmv, bsc, _br, _bn, ab = NB.search_plies(
                s["board"], me, plies, w, legal, ply_no=bot._ply,
                time_limit=600.0, exact=True, reset=True)
            if ab:
                continue
            n_tot += 1
            d = abs(psc - bsc)
            worst = max(worst, d)
            if d > 1e-6:
                n_bad += 1
                details.append(f"{tag}·{D.ARMY_CN[me]} Py={psc:.6f} "
                               f"JIT={bsc:.6f} Δ={d:.3e}")
    print(f"  [{label}] plies={plies}: 最大偏差 {worst:.3e}   "
          f"不一致 {n_bad}/{n_tot}")
    for x in details[:5]:
        print("      ✗ " + x)
    return worst


def main():
    pos_list = [("开局", GA.new_game(first=1))] + random_positions(8)
    print("=" * 76)
    print("A. 原样（Python `_leaf` 按 dict 顺序求和）")
    print("=" * 76)
    for plies in (4, 6):
        run(pos_list, plies, "原样")

    print()
    print("=" * 76)
    print("B. 猴补丁：Python `_leaf` 改成**按点位排序**求和（= JIT 口径）")
    print("=" * 76)
    orig = SearchBot._leaf
    SearchBot._leaf = leaf_sorted
    try:
        for plies in (4, 6):
            run(pos_list, plies, "排序求和")
    finally:
        SearchBot._leaf = orig

    print()
    print("=" * 76)
    print("判读：B 若降到 ~1e-13 ⇒ 根因确认 = `leaf` 浮点求和顺序")
    print("=" * 76)


if __name__ == "__main__":
    main()
