# -*- coding: utf-8 -*-
"""绕过迭代加深的时间外推，硬搜 9 / 12 plies，测真实耗时与节点。"""
import sys, time, random
sys.path.insert(0, ".")
from engine import game_dxf as GA
from agents.search_bot import SearchBot
from agents import eval_dxf as E

def hard(plies, warm=0, tl=900):
    s = GA.new_game()
    rng = random.Random(7)
    for _ in range(warm):
        lg = GA.legal_moves(s, s["turn"])
        if not lg: break
        m = rng.choice(lg); GA.apply(s, m[0], m[1])
    b = SearchBot(depth=3, time_limit=tl, seed=11)
    me = s["turn"]; lg = GA.legal_moves(s, me)
    b._deadline = time.time() + tl; b._hist = {}; b._killers = {}
    b._ply = warm; b._ur = 1.0 + warm * b.w.get("urgency", 0.0); b.nodes = 0
    board = dict(s["board"]); alive = frozenset(b._gen_alive(board))
    t0 = time.time()
    try:
        mv, sc, ranked = b._root_search(board, list(lg), alive, plies, me, E.distances())
        dt = time.time() - t0
        print(f"  plies={plies:<3} warm={warm:<3} {dt:>7.2f}s  节点={b.nodes:<9} "
              f"nps={int(b.nodes/max(dt,1e-6)):>7}  着法={mv[0]}-{mv[1]} 估值={sc:+.1f}")
    except Exception as ex:
        print(f"  plies={plies} warm={warm} 失败 {type(ex).__name__}: {ex}")

print("=== 开局 ===")
for p in (3, 6, 9):
    hard(p)
print("=== 开局 12 plies（深度4层）===")
hard(12)
print("=== 中局 24 手 ===")
for p in (6, 9):
    hard(p, warm=24)
