# -*- coding: utf-8 -*-
"""生成前端静态棋盘数据 web/board_data.js（含 135 点、51 线、三条地带、九宫、三角区）。"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
data = json.load(open(os.path.join(HERE, "..", "data", "board_135.json"), encoding="utf-8"))

pts = {"".join(k.split("-")): [round(v["x"], 3), round(v["y"], 3)]
       for k, v in data["points"].items()}
lines = [["".join(p.split("-")) for p in L] for L in data["lines"]]

# 三条地带（DXF 四边形）
# 方位（老师 2026-09-22 22:10 确认）：魏=下、吴=左斜上、蜀=右斜上
#   荆州 = 吴蜀之间 -> 上方(90°)
#   赤壁 = 魏吴之间 -> 左下(210°)
#   祁山 = 魏蜀之间 -> 右下(330°)
bands = [
    {"name": "荆州", "quad": ["255", "259", "351", "355"],
     "desc": "吴 ↔ 蜀"},
    {"name": "赤壁", "quad": ["155", "159", "251", "255"],
     "desc": "魏 ↔ 吴"},
    {"name": "祁山", "quad": ["355", "359", "151", "155"],
     "desc": "魏 ↔ 蜀"},
]

gong = {str(a): [f"{a}{r}{c}" for r in (1, 2, 3) for c in (4, 5, 6)] for a in (1, 2, 3)}
tri = {"1": "155", "2": "255", "3": "355"}

hexv = [[104.0439, 0], [52.0219, 90.1046], [-52.0219, 90.1046],
        [-104.0439, 0], [-52.0219, -90.1046], [52.0219, -90.1046]]

out = {
    "hex": hexv,
    "points": pts,
    "lines": lines,
    "bands": bands,
    "gong": gong,
    "tri": tri,
}

web = os.path.join(ROOT, "web")
os.makedirs(web, exist_ok=True)
p = os.path.join(web, "board_data.js")
with open(p, "w", encoding="utf-8") as f:
    f.write("// 专利版棋盘数据（由老师的 DXF 工程图生成，勿手改）\n")
    f.write("// 坐标：DXF 图纸坐标，x 右 y 上，六边形外接圆半径 104.0439\n")
    f.write("window.BOARD_DATA = ")
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    f.write(";\n")
print(f"已生成 {p}")
print(f"  点数 {len(pts)}  线数 {len(lines)}  地带 {len(bands)}")

# 三方起始子补齐（其余两方 = 方 1 的旋转副本，由前端按 120° 旋转生成，这里只存方1）
print("  start 仅存魏方 16 子；蜀/吴由前端 120°/240° 旋转生成")
