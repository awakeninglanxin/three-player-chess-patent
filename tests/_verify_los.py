# -*- coding: utf-8 -*-
"""验证：帅见面判定 line_of_sight 用旧射线（B.rays）会漏判规则图第 9 条的跨方线路。"""
import os, sys
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "server"))
from engine import geometry_dxf as G
from engine import rules_dxf as R

B = G.BOARD
OLD = {p: tuple(r.walk for r in rs) for p, rs in B.rays.items()}
NEW = R.RAYS


def los(table, p1, p2, board=None):
    board = board or {}
    for path in table.get(p1) or ():
        if p2 in path:
            idx = path.index(p2)
            if all(q not in board for q in path[:idx]):
                return True
    return False


# 规则图第 9 条明列的六条线路（两两配对）
CASES = [
    ("E5-J5  【E5-A5-F5-J5】", "115", "315"),
    ("O5-E5  【O5-K5-A5-E5】", "215", "115"),
    ("J5-O5  【J5-F5-K5-O5】", "315", "215"),
    ("E6-J4  【E6-A6-F4-J4】", "114", "316"),
    ("J6-O4  【J6-F6-K4-O4】", "314", "216"),
    ("O6-E4  【O6-K6-A4-E4】", "214", "116"),
    # DXF 里本来就画成一条的 3 对（图1↔图9）
    ("魏1-吴1 (图1↔9)", "119", "211"),
    ("魏9-蜀9 (图1↔9)", "111", "319"),
    ("吴9-蜀9 (图1↔9)", "219", "311"),
    # 其余贯通线抽样。注意"图号"与"引擎列号"互为 10 的补数，别混：
    #   魏列8=魏图2 → 吴列2=吴图8    (118 ↔ 212)
    #   魏列7=魏图3 → 吴列3=吴图7    (117 ↔ 213)
    #   蜀列6=蜀图4 → 魏列4=魏图6    (316 ↔ 114) ← 不是 116（116 是魏列6=魏图4）
    ("魏2-吴8", "118", "212"),
    ("魏3-吴7", "117", "213"),
    ("蜀4-魏6", "316", "114"),
]

print("=" * 74)
print("%-28s %-8s %-8s" % ("线路", "旧(B.rays)", "新(RAYS)"))
print("=" * 74)
miss_old = miss_new = 0
for name, a, b in CASES:
    o = los(OLD, a, b)
    n = los(NEW, a, b)
    miss_old += (not o)
    miss_new += (not n)
    print("%-28s %-8s %-8s" % (name, "通" if o else "✗漏判", "通" if n else "✗漏判"))
print("=" * 74)
print("旧口径漏判 %d / %d 条；新口径漏判 %d / %d 条" % (miss_old, len(CASES), miss_new, len(CASES)))

# 对称性：15 条贯通线全部两两可达？
lanes = {tuple(sorted(ln)) for _a, _c, _b, ln in R._front_lanes()}
bad = 0
for ln in lanes:
    ends = [ln[0], ln[-1]]
    if not los(NEW, ends[0], ends[1]):
        bad += 1
print("15 条贯通线中「首尾可达」失败 %d 条" % bad)

# 中间有子时应当阻断
board = {"135": {"kind": "pawn", "army": 2, "home": 2}}
print("中间放一子(135)后 115→315：", los(NEW, "115", "315", board), "(应为 False)")
