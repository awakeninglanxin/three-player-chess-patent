# -*- coding: utf-8 -*-
"""探针 4：默认档 12 plies 下，蜀方会不会白吃这匹马"""
import os, sys, copy
HERE = os.path.dirname(os.path.abspath(__file__)); SRV = os.path.join(HERE, "..", "server")
sys.path.insert(0, os.path.abspath(SRV)); sys.path.insert(0, os.path.abspath(os.path.join(SRV, "engine")))
from engine import game_dxf as GA
from agents.search_bot import SearchBot
L = {1:"ABCDE",2:"KLMNO",3:"FGHIJ"}
def lab(p):
    a,r,c = int(p[0]),int(p[1]),int(p[2]); return L[a][5-r]+str(10-c)
s = GA.new_game(first=1); GA.apply(s,"111","121"); s["turn"]=3
legal = GA.legal_moves(s,3)
bot = SearchBot(depth=4, time_limit=300.0, seed=20261001, label="蜀 12p")
res = bot._jit_search(copy.deepcopy(s["board"]), 3, 12, list(legal), 300.0, True)
print("蜀 12 plies 选招 =", res[0], " 根分 =", round(float(res[1]),2), " 节点 =", res[3], " aborted =", res[4])
items = list(res[2]) if res[2] is not None else []
names = [tuple(x)[:2] for x in items]
for i,x in enumerate(items[:10]): print("   #%d %s→%s  %.2f"%(i+1, lab(x[0]), lab(x[1]), x[2]))
try: print("「炮H2吃E8马」排名 =", names.index(("338","112"))+1, "/", len(names))
except ValueError: print("「炮H2吃E8马」不在榜上")
