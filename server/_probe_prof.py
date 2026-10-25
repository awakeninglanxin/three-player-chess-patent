# -*- coding: utf-8 -*-
import sys, cProfile, pstats, io, time
sys.path.insert(0, ".")
from engine import game_dxf as GA
from agents.search_bot import SearchBot

s = GA.new_game()
b = SearchBot(depth=2, time_limit=30, seed=3)
lg = GA.legal_moves(s, s["turn"])
pr = cProfile.Profile(); pr.enable(); b.choose(s, lg, "", "X"); pr.disable()
st = io.StringIO()
pstats.Stats(pr, stream=st).sort_stats("tottime").print_stats(14)
print(st.getvalue()[:2600])
print("nodes =", b.nodes, " lat =", b.stats["latency"][-1], "ms")
