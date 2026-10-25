# -*- coding: utf-8 -*-
"""探针⑤：逐层下降解剖器 —— 定位 JIT↔Python 搜索在**哪个节点**第一次分岔

【为什么需要它】
    根层面只知道"某几个根着法的分数不同"，但那只是**症状**。
    真正要抓的是"从哪一层、哪一个节点开始两边算的不是同一个值"。

【做法】
    锁步下降（lockstep descent）：
      ① 在节点 N（全窗口 (−INF,+INF)，两边都从**空** HIST/KILL 开始）
         分别调 Python `_search` 与 JIT `_search`，比返回值；
      ② 若相等 ⇒ 这个子树没问题，换下一个兄弟；
      ③ 若不等 ⇒ 打印这个节点的关键信息（turn / plies / mask / 盘面摘要），
         然后**按同一顺序**枚举本节点被保留（宽度截断后）的着法，
         对每个子节点递归回到 ①，直到触到底（plies=0）或找到"叶子值不同"。

    为什么全窗口 + 空表：这样两边的比较是**与搜索历史无关的绝对量**，
    排除了 alpha/beta 与历史表状态的干扰 —— 如果这样都比不出来，
    说明分歧只可能来自「窗口/PVS 交互」或「历史表演化」，那是另一类问题。

【判读】
    下降到底停在 plies=0 且 leaf 不同 ⇒ leaf 又有隐藏分支
    下降停在某个子节点值不同但 leaf 相同 ⇒ 该节点的『着法集合/顺序/截断』不同
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
BIG = 10 ** 6
WIDTH_OFF = np.full(NB.MAX_PLY + 1, BIG, dtype=np.int32)


class Ctx:
    """一次锁步比较的全部共享状态"""

    def __init__(self, w, width_jit, width_py, use_width):
        self.bot = SearchBot(depth=1, noise=0.0)
        self.bot.w = dict(w)
        self.w = dict(w)
        self.width_jit = width_jit
        self.use_width = use_width
        self.sc = NB._SEARCHSCR
        self.dist = E.distances()
        self.W = np.zeros(len(NB.W_KEYS), dtype=np.float64)
        for k, i in NB.W_IDX.items():
            self.W[i] = float(w.get(k, 0.0))
        self.ur = 1.0
        self.log = []

    # ---- Python 节点 ----
    def py_node(self, board, turn, alive, plies, me, alpha=-INF, beta=INF):
        bot = self.bot
        bot._hist = {}
        bot._killers = {}
        bot.nodes = 0
        bot._deadline = 1e18
        return bot._search(board, turn, alive, plies, alpha, beta, me, self.dist)

    # ---- JIT 节点 ----
    def nb_node(self, board, code, turn, mask, plies, me, alpha=-INF, beta=INF):
        """⚠️ 必须走 `NB.search_node`（Python 桥）—— 直接调 `NB._search`
           会因 numba 缓存 + objmode 抛 `unresolved symbol`。
        ⚠️ `width` 恒传 `self.width_jit`（关宽度时它是 WIDTH_OFF 大表）——
           早先写成 `... if use_width else None`，`None` 会回落到默认 WIDTH_T，
           等于"关宽度"根本没生效，白跑一轮（已踩）。"""
        return NB.search_node(board, turn, mask, plies, me, self.w,
                              self.ur, alpha=alpha, beta=beta,
                              width=self.width_jit, code=code)

    # ---- 枚举某节点「被保留的着法」（同一顺序）----
    def kept_moves(self, board, code, turn, plies):
        """返回 (py_list, jit_list, py_set, jit_set)"""
        bot = self.bot
        bot._hist = {}
        bot._killers = {}
        moves = []
        for pos, pc in board.items():
            if pc["army"] != turn:
                continue
            for q in R.moves_of(board, pos, pc):
                moves.append((pos, q))
        py = bot._order(board, moves, turn, plies)
        sc = self.sc
        n = int(NB.gen_side(code, np.int32(turn), sc.mvb, sc.stamp, sc.ctr))
        NB._order(code, sc.mvb, sc.scb, 0, n, np.int32(turn), np.int32(plies),
                  sc.hist, sc.kill)
        jit = [(NB.IDX2POS[int(sc.mvb[i]) >> 8], NB.IDX2POS[int(sc.mvb[i]) & 255])
               for i in range(n)]
        return py, jit, set(py), set(jit)


def make_case(idx):
    rng = random.Random(777)
    for i in range(idx + 1):
        s = GA.new_game(first=1 + (i % 3))
        target = rng.randint(8, 34)
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
    return s, target


def descend(ctx, board, code, turn, mask, plies, me, path, limit, out):
    """锁步下降。out 收集前若干条"第一次分岔"的证据。"""
    if plies <= 0 or len(out) >= limit:
        return
    alive = set(a for a in (1, 2, 3) if mask & (1 << a))
    py = ctx.py_node(board, turn, alive, plies, me)
    nb = ctx.nb_node(board, code, turn, mask, plies, me)
    d = abs(py - nb)
    tag = "→".join(path) if path else "(根)"
    if d < 1e-6:
        return
    out.append((tag, plies, turn, py, nb, d))
    print(f"  分岔 {tag}  plies={plies} turn={D.ARMY_CN[turn]}  "
          f"Py={py:.6f} JIT={nb:.6f}  Δ={d:.3e}")
    if plies == 1:
        print("     ⚠️ 已到 plies=1 ⇒ 子节点就是叶，问题在 **leaf**")
        return
    py_mv, jit_mv, py_set, jit_set = ctx.kept_moves(board, code, turn, plies)
    lim = int(ctx.width_jit[plies]) if ctx.use_width else 10 ** 9
    if py_set != jit_set:
        print(f"     ★★ 着法集合不同！仅Py={sorted(py_set - jit_set)[:5]} "
              f"仅JIT={sorted(jit_set - py_set)[:5]}")
        return
    if py_mv[:lim] != jit_mv[:lim]:
        i = next(i for i in range(min(lim, len(py_mv))) if py_mv[i] != jit_mv[i])
        print(f"     ★★ 截断后顺序不同（第 {i} 位）Py={py_mv[i]} JIT={jit_mv[i]}")
        # 仍然继续，只是顺序不同
    nxt_mask = mask
    for (frm, to) in py_mv[:lim]:
        b2 = dict(board)
        pc = b2.pop(frm)
        vic = b2.pop(to, None)
        b2[to] = pc
        nm = mask
        if vic is not None and vic["kind"] == R.GENERAL and not vic.get("deputy"):
            nm = mask & ~(1 << vic["home"])
        c2 = NB.encode_board(b2)
        nxt = int(NB._next_turn(np.int32(mask), np.int32(turn)))
        descend(ctx, b2, c2, nxt, nm, plies - 1, me, path + [f"{frm}-{to}"],
                limit, out)
        if len(out) >= limit:
            return


def main():
    print("=" * 78)
    print("逐层下降解剖：JIT ↔ Python 搜索在哪里第一次分岔")
    print("=" * 78)

    bot0 = SearchBot(depth=1, noise=0.0)
    w = bot0.w

    cases = [(0, "开局", GA.new_game(first=1))]
    for i in (6,):
        s, t = make_case(i)
        cases.append((i, f"局{i + 1}/{t}步", s))

    for idx, tag, s in cases:
        for me in (1, 2, 3):
            print(f"\n---- {tag} · me={D.ARMY_CN[me]} · plies=6 ----")
            for use_width in (True, False):
                wj = NB.WIDTH_T if use_width else WIDTH_OFF
                ctx = Ctx(w, wj, None, use_width)
                code = NB.encode_board(s["board"])
                mask = int(NB._alive_mask(code))
                # 直接比 plies=6 的整棵树值（用 root 接口，全窗口）
                legal = list(GA.legal_moves(s, me))
                b = dict(s["board"])
                ctx.bot._ply = int(s.get("ply", 0) or 0)
                ctx.bot._ur = 1.0 + ctx.bot._ply * w.get("urgency", 0.0)
                ctx.bot._deadline = 1e18          # ⚠️ 忘了设会 AttributeError
                ctx.bot._hist = {}
                ctx.bot._killers = {}
                ctx.bot.nodes = 0
                ctx.ur = ctx.bot._ur
                _mv, psc, pr = ctx.bot._root_search(
                    b, legal, set(a for a in (1, 2, 3) if mask & (1 << a)),
                    6, me, ctx.dist, exact=True)
                out = []
                # 从根的第一个分岔着法开始下降
                branked = NB.search_plies(
                    s["board"], me, 6, w, legal, ply_no=ctx.bot._ply,
                    time_limit=600.0, exact=True, reset=True,
                    width=wj)[2]
                bmap = {(f, t): v for f, t, v in branked}
                pmap = {(f, t): v for v, (f, t) in pr}
                diffs = [k for k in pmap if abs(pmap[k] - bmap.get(k, -1e18)) > 1e-6]
                print(f"  宽度={'开' if use_width else '关'}："
                      f"根着法分数不同的有 {len(diffs)} / {len(pmap)} 个"
                      f"  最大Δ={max((abs(pmap[k] - bmap[k]) for k in diffs), default=0):.3e}")
                if diffs:
                    for k in diffs[:2]:
                        print(f"     着法 {k[0]}-{k[1]}: Py={pmap[k]:.6f} "
                              f"JIT={bmap[k]:.6f}")
                    # 下降
                    k = diffs[0]
                    b2 = dict(s["board"])
                    pc = b2.pop(k[0])
                    vic = b2.pop(k[1], None)
                    b2[to := k[1]] = pc
                    nm = mask
                    if vic is not None and vic["kind"] == R.GENERAL \
                            and not vic.get("deputy"):
                        nm = mask & ~(1 << vic["home"])
                    nxt = int(NB._next_turn(np.int32(mask), np.int32(me)))
                    ctx2 = Ctx(w, wj, None, use_width)
                    ctx2.bot._ply = ctx.bot._ply
                    desc = []
                    descend(ctx2, b2, NB.encode_board(b2), nxt, nm, 5, me,
                            [f"{k[0]}-{k[1]}"], 3, desc)
                    if not desc:
                        print("     （子节点全窗口下两边一致 ⇒ 分歧来自"
                              "『窗口/PVS 交互』或『历史表演化』，不是节点值本身）")

    print()
    print("=" * 78)


if __name__ == "__main__":
    main()
