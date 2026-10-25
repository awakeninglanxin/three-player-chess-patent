# -*- coding: utf-8 -*-
"""本地兜底 Bot：LLM 调用失败或不想烧钱时的替补，也可当"对照组"跑基准

统一接口：choose(state, legal, text, army_name) -> {"move","reason","ok","raw","latency","usage"}
"""
import math
import random
import time
try:
    from ..engine import geometry_dxf as G
    from ..engine import rules_dxf as R
except ImportError:                      # 以 server/ 为工作目录时走这条
    from engine import geometry_dxf as G
    from engine import rules_dxf as R

VALUE = {R.ROOK: 9.0, R.CANNON: 4.5, R.HORSE: 4.0, R.ELEPHANT: 2.0,
         R.ADVISOR: 2.0, R.PAWN: 1.0, R.GENERAL: 1000.0}
B = G.BOARD


def _dist(a, b):
    if not a or not b:
        return 0.0
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _row(p):
    return G.parse(p)[1]


def _sig(board):
    """局面签名（用于识别"来回抖动"的重复局面）"""
    return tuple(sorted((p, pc["kind"], pc["army"]) for p, pc in board.items()))


class LocalBot:
    """一步贪心 + 反吃估计 + 叫将激励；不调用任何网络"""

    kind = "local"

    def __init__(self, mode="greedy", seed=None):
        self.mode = mode
        self.rng = random.Random(seed)
        self.label = {"greedy": "本地贪心Bot", "random": "本地随机Bot"}.get(mode, "本地Bot")
        self.stats = {"calls": 0, "ptokens": 0, "ctokens": 0, "latency": [],
                      "fallbacks": 0, "retries": 0, "netfail": 0}
        self.offline = False          # 与 LLMAgent 保持同一套字段，前端统一渲染

    def choose(self, state, legal, text="", army_name=""):
        """对外统一入口：包一层计时，让「均耗时」这一列对本地 Bot 也有意义"""
        t0 = time.time()
        res = self._choose(state, legal, text, army_name)
        dt = round((time.time() - t0) * 1000, 3)      # 本地 Bot 用毫秒更直观
        self.stats["latency"].append(dt)
        if isinstance(res, dict):
            res["latency"] = dt
        return res

    def _choose(self, state, legal, text="", army_name=""):
        self.stats["calls"] += 1
        if not legal:
            return {"move": None, "reason": "无合法着法", "ok": False, "raw": "",
                    "latency": 0.0, "usage": {}}
        if self.mode == "random":
            a, b = self.rng.choice(legal)
            return {"move": f"{a}-{b}", "reason": "随机", "ok": True, "raw": "",
                    "latency": 0.0, "usage": {}}
        best, best_sc = [], -1e18
        # 残局引导：子少时（残局）温和地朝敌方帅推进，避免几百手不收敛；
        # 子多时（开局/中局）不启用，保证走位像正常象棋。
        n_alive = len(state["board"])
        guide = {}
        if n_alive <= 22:
            for pos, p in state["board"].items():
                if p["kind"] == R.GENERAL and p["army"] != state["turn"] \
                        and not p.get("deputy"):
                    guide[pos] = self._bfs(pos)
        for frm, to in legal:
            sc = self._score(state, frm, to)
            me = state["board"][frm]
            # 残局引导只对"进攻型"子生效：士/帅在九宫里会因此来回抖（实测 700 次）
            if guide and me["kind"] in (R.ROOK, R.CANNON, R.HORSE, R.PAWN):
                for gpos, topo in guide.items():
                    d0, d1 = topo.get(frm), topo.get(to)
                    if d0 is not None and d1 is not None:
                        sc += (d0 - d1) * 0.35          # 每靠近一步 + 0.35
            # 禁止"立刻走回去"的无意义往返
            hist = state.get("history") or []
            if hist and hist[-1] == f"{to}-{frm}":
                sc -= 0.7
            if sc > best_sc + 1e-9:
                best_sc, best = sc, [(frm, to)]
            elif abs(sc - best_sc) < 1e-9:
                best.append((frm, to))
        a, b = self.rng.choice(best)
        return {"move": f"{a}-{b}", "reason": f"估值 {best_sc:+.1f}", "ok": True,
                "raw": "", "latency": 0.0, "usage": {}}

    @staticmethod
    def _bfs(src):
        """从 src 出发的图中最少步数（忽略棋子阻挡，纯拓扑）"""
        from collections import deque
        dist = {src: 0}
        q = deque([src])
        while q:
            cur = q.popleft()
            for nb in B.adj.get(cur, ()):
                if nb not in dist:
                    dist[nb] = dist[cur] + 1
                    q.append(nb)
        return dist

    def _score(self, s, frm, to):
        """本地 Bot 评分 —— 遵循象棋常识（不要用"疯狂逼近敌帅"这类激进引导，
        否则会出现"只动一个兵、在中心三点来回横跳"的荒谬走位）。

          ① 吃子（主项，吃帅直接封顶）
          ② 反吃风险（吃子时才算）
          ③ 将军
          ④ 保住自己的帅
          ⑤ 出子展开 + 兵向前（横走扣分，避免原地打转）
        """
        board = s["board"]
        me = board[frm]
        my_army = me["army"]
        victim = board.get(to)
        sc = 0.0

        # ① 吃子
        if victim:
            sc += VALUE[victim["kind"]]
            if victim["army"] != my_army:
                sc += 1.0
                if victim["kind"] == R.GENERAL:
                    sc += 900.0

        nxt = dict(board)
        nxt.pop(frm, None)
        nxt[to] = me
        hyp = {"board": nxt}

        # ② 反吃风险（只在吃子时权衡，避免吓住正常推进）
        if victim:
            for pos, p in nxt.items():
                if p["army"] == my_army:
                    continue
                try:
                    if to in R.pseudo_moves(hyp, pos):
                        sc -= VALUE[me["kind"]] * 0.6
                        break
                except Exception:
                    pass

        # ③ 将军
        for pos, p in nxt.items():
            if p["kind"] == R.GENERAL and p["army"] != my_army:
                try:
                    if pos in R.pseudo_moves(hyp, to):
                        sc += 8.0
                except Exception:
                    pass

        # ④ 保帅
        my_gen = None
        for pos, p in nxt.items():
            if p["kind"] == R.GENERAL and p.get("home") == my_army \
                    and not p.get("deputy"):
                my_gen = pos
                break
        if my_gen is not None:
            for pos, p in nxt.items():
                if p["army"] == my_army:
                    continue
                try:
                    if my_gen in R.pseudo_moves(hyp, pos):
                        sc -= 6.0
                        break
                except Exception:
                    pass

        # ⑤ 出子展开：优先让车马炮动起来（像象棋的开局），兵其次
        r0 = _row(frm)
        r1 = _row(to)
        if me["kind"] in (R.ROOK, R.CANNON, R.HORSE):
            if r1 > r0:
                sc += 0.8                      # 大子向前，鼓励出动
        if me["kind"] == R.PAWN:
            if r1 > r0:
                sc += 0.35
            elif r1 == r0:
                sc -= 0.15                     # 横走（含跨国）不宜反复
            if G.parse(to)[0] != me["home"]:
                sc += 0.2                      # 过界有小收益，但别一窝蜂冲
        return sc + self.rng.random() * 0.05
