# -*- coding: utf-8 -*-
"""探针 5：量化「博弈树里的重复局面占比」—— 决定置换表(TT)值不值得做

做法：从真实中局出发，做**有界 DFS**（穷举到 N plies），
      过程中统计：
        · nodes      = 访问到的「路径数」（= 朴素 alpha-beta 会重复展开的次数上界）
        · distinct   = 去重后的「局面签名」数（board+turn）
      distinct / nodes 越低 ⇒ 置换表能省掉的重复计算越多。

注意：三人棋里「合法着法」依赖历史（长将判负 / 重复判罚），
      所以这不完全等价于真正的 TT（严格 TT 需要把相关历史并入 key）。
      本探针只测**结构性重复**（同一个 board+turn 由不同顺序到达），
      这已经是 TT 能拿到的**保守下界**。
"""
import os
import sys
import copy
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRV = os.path.join(HERE, "..", "server")
sys.path.insert(0, os.path.abspath(SRV))
sys.path.insert(0, os.path.abspath(os.path.join(SRV, "engine")))

from engine import game_dxf as GA            # noqa: E402
from agents.search_bot import SearchBot      # noqa: E402

ARMY = {1: "魏", 2: "吴", 3: "蜀"}


def sig(state):
    """局面签名：棋盘 + 行棋方。棋盘用排序后的 (点, 方, 兵种) 串。"""
    b = state["board"]
    parts = []
    for p in sorted(b):
        v = b[p]
        parts.append(f"{p}{v['army']}{v['kind']}")
    return "|".join(parts) + f"#{state['turn']}"


def walk(state, depth, seen, stat, t_end):
    """有界 DFS：穷举到 depth plies"""
    if time.time() > t_end:
        stat["timeout"] = True
        return
    stat["nodes"] += 1
    s = sig(state)
    if s in seen:
        stat["repeats"] += 1
    else:
        seen.add(s)
    if depth <= 0:
        return
    turn = state["turn"]
    legal = GA.legal_moves(state, turn)
    for frm, to in legal:
        if time.time() > t_end:
            stat["timeout"] = True
            return
        nxt = copy.deepcopy(state)
        GA.apply(nxt, frm, to)
        walk(nxt, depth - 1, seen, stat, t_end)


def main():
    # ---- 造一个真实中局：让 3 plies 的 Bot 自走 24 手 ----
    print("=" * 74)
    print("① 造中局（3 plies Bot 自走 24 手）")
    print("=" * 74)
    st = GA.new_game(first=1)
    bot = SearchBot(depth=1, time_limit=1.0, seed=20261001)
    for _ in range(24):
        if st.get("winner") is not None:
            break
        turn = st["turn"]
        legal = GA.legal_moves(st, turn)
        if not legal:
            GA._advance(st)
            continue
        r = bot.choose(st, legal)
        mv = (r or {}).get("move")
        if not mv:
            GA._advance(st)
            continue
        frm, to = mv.split("-")
        GA.apply(st, frm, to)
    print(f"  中局：ply={st['ply']}  轮到 {ARMY[st['turn']]}  盘上 {len(st['board'])} 子")

    b0 = st["board"]
    import collections
    cnt = collections.Counter((v["army"], v["kind"]) for v in b0.values())
    for (a, k), n in sorted(cnt.items()):
        print(f"     {ARMY[a]} {k:<8} × {n}")

    # ---- 逐层穷举，统计重复率 ----
    print("\n" + "=" * 74)
    print("② 逐层穷举：nodes（路径数） vs distinct（不同局面）")
    print("=" * 74)
    print(f"  {'plies':>5} {'nodes':>10} {'distinct':>10} {'重复率':>9} {'可省':>9}  说明")
    for d in (1, 2, 3, 4):
        seen = set()
        stat = {"nodes": 0, "repeats": 0, "timeout": False}
        t_end = time.time() + 120
        t0 = time.time()
        walk(st, d, seen, stat, t_end)
        dt = time.time() - t0
        n = stat["nodes"]
        dis = len(seen)
        rate = (n - dis) / n * 100 if n else 0
        note = "（超时截断，非全量）" if stat["timeout"] else f"{dt:.1f}s"
        print(f"  {d:>5} {n:>10} {dis:>10} {rate:>8.1f}% {rate:>8.1f}%  {note}")
        if stat["timeout"]:
            print("        → 后续层跳过（穷举太慢）")
            break

    print("\n" + "=" * 74)
    print("③ 结论口径")
    print("=" * 74)
    print("  · 重复率 = (nodes - distinct) / nodes")
    print("    ⇒ 这部分是「同一局面被不同着法顺序反复展开」的浪费。")
    print("  · 置换表(TT)按 zobrist 键缓存 (分数, 深度, 标志) 可直接吃掉这部分。")
    print("  · ⚠️ 本测法是**保守下界**：还没算上「不同深度到达同一局面」的跨层重复")
    print("    （真正的 TT 连那种也能省），也还没算上排序改善带来的剪枝增益。")


if __name__ == "__main__":
    main()
