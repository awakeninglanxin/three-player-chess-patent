# -*- coding: utf-8 -*-
"""结论：字母 A..O 是「行」标，贴在每方「列9 端」，顺序如下（由条带 OCR 位置反算）：
   魏行5=A 行4=B 行3=C 行2=D 行1=E
   蜀行5=F 行4=G 行3=H 行2=I 行1=J
   吴行5=K 行4=L 行3=M 行2=N 行1=O
数字 1..9 贴在三条底边（行1），1 在「列9」端，9 在「列1」端。
所以：老师说的坐标 = 「行字母 + 图上数字」，图号 n ↔ DXF 列(10-n)。
"""
LETTER = {"2-1": "O", "2-2": "N", "2-3": "M", "2-4": "L", "2-5": "K",
          "1-1": "E", "1-2": "D", "1-3": "C", "1-4": "B", "1-5": "A",
          "3-1": "J", "3-2": "I", "3-3": "H", "3-4": "G", "3-5": "F"}
CN = {1: "魏", 2: "吴", 3: "蜀"}

def to_pid(army, letter, digit):
    """(方, 行字母, 底边数字) -> 引擎 3 位编号"""
    for a_r, let in LETTER.items():
        a, r = map(int, a_r.split("-"))
        if let == letter and CN[a] == CN[army]:
            col = 10 - digit
            return f"{a}{r}{col}"
    return None

print("老师们给的三个坐标 → 引擎编号 / DXF 坐标：")
import sys, os
sys.path.insert(0, os.path.join("..", "server"))
from engine.geometry_dxf import Board, parse
B = Board()
for army, let, dg in [(2, "O", 1), (2, "O", 2), (2, "O", 5), (2, "M", 6), (2, "O", 9)]:
    p = to_pid(army, let, dg)
    a, r, c = parse(p)
    print(f"  {CN[army]}{let}{dg}  ->  {p}  = {CN[a]}行{r}列{c}   xy={B.xy[p]}")
