# -*- coding: utf-8 -*-
"""核实老师的说法：字母=各方「横向行线」，只有 E/J/O（行1）是直线，
其余行（行2-5）在「纵向中线5」处有拐点。"""
import sys, os, math
# 【2026-09-24 夜修】原来写 `os.path.join("..","server")` —— 依赖**当前工作目录**，
# 从项目根或别处跑就会 ModuleNotFoundError。改成基于 __file__ 的绝对路径（任意 cwd 可用）。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))
from engine.geometry_dxf import Board, parse
B = Board()
CN = {1:"魏",2:"吴",3:"蜀"}
LETTER = {}
for a, base in ((1,"E"),(2,"O"),(3,"J")):
    for r in range(1,6):
        LETTER[(a,r)] = chr(ord(base)-(r-1))

def ang(p,q):
    dx,dy = B.xy[q][0]-B.xy[p][0], B.xy[q][1]-B.xy[p][1]
    return math.degrees(math.atan2(dy,dx))

print(f"{'行':4s} {'字母':4s}  各段方向(°)          拐点位置   最大折角  是否直线")
for a in (1,2,3):
    for r in range(1,6):
        row = B.rows[(a,r)]          # 列1..列9
        dirs = [ang(row[i], row[i+1]) for i in range(len(row)-1)]
        # 找拐点：相邻段方向差最大的位置
        dmax, kbest = -1, -1
        for i in range(len(dirs)-1):
            d = abs(((dirs[i+1]-dirs[i]+180) % 360) - 180)
            if d > dmax: dmax, kbest = d, i
        bend = row[kbest+1]
        ar, ac = parse(bend)[1], parse(bend)[2]
        straight = "✔直线" if dmax < 2 else f"✘ 拐点在第{ac}列"
        print(f"行{r}  {LETTER[(a,r)]:4s}  " +
              " ".join(f"{d:7.2f}" for d in dirs) +
              f"   折于{bend}(列{ac})  {dmax:6.2f}   {straight}")
    print()
