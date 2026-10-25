# -*- coding: utf-8 -*-
"""三方棋盘「拓扑优先」专项自检 —— 把老师 2026-09-24 的「举一反三」要求固化成断言。

【背景：老师一口气报了四个 bug，全部同源】
    ① 魏国的马不会过河
    ② 人类点了棋子却没动（前端两处）
    ③ 魏C2 的炮到不了 C6/C7 —— 合法落点在 C5 处被切断
    ④ 象出现 24 条非法步（如 123→127，Δ=(0,4)，根本不是「田」）
    （老师原话：「同理你要检查其它方是否也有这样的bug，你要举一反三，不能只修魏国的bug」）

【根因】本盘是**变形网格**：内部行线在「纵向中线 列5」处有折角（实测 16.31°~47.58°），
    远超 `ANG_TOL = 2.0°`。凡是用**几何角度**去判「共线 / 是否拐弯」的地方都会出错 ——
    几何把**同一条行**切成两段，于是车/炮横穿不了列5，象把「沿行多走 2 格」误判成「拐弯」。

【铁律】老师 2026-09-24：「你不要用几何去判断，我说了很多次了。」
    ⇒ 一切「共线 / 同向 / 是否拐弯 / 腿取向 / 田中心方向」的**规则判据**，一律用
      **(方, 行, 列) 拓扑坐标**表达；几何（`B.xy` / `_angle` / `atan2`）只允许出现在
      `geometry_dxf`（坐标→邻接→射线 的基础设施），且其产物必须由
      `_splice_front_rays()` / `_splice_row_rays()` 用**拓扑**补正。

【本测试覆盖】
    §1 行线完整性：15 条行（3 方 × 5 行）每条都是完整 9 点
    §2 车 / 炮横穿列5：每行两端出发覆盖同行全部 8 个同伴
    §3 象步合法性：全部象步必须 |Δr|=2 且 |Δc|=2，不过河、不跨方、田中心是格点
    §4 马：腿拓扑唯一 + 三方都能过河（跨方腿数相等）
    §5 三方针对称：士/帅/象/马/兵 着法数三方完全相等
    §6 静态扫描：`rules_dxf.py` 的 **AST** 里不得再出现几何判据（注释/docstring 不算）

跑法：cd 中国三人象棋_专利版 && python tests/_verify_rays_topology.py
"""
import ast
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "server"))

from engine import geometry_dxf as D        # noqa: E402
from engine import rules_dxf as R           # noqa: E402

B = D.BOARD
ARMIES = D.ARMIES
ROWS, COLS = R.ROWS_TERR, R.COLS_TERR
OK = FAIL = 0


def chk(name, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  [OK]   {name} {extra}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


def pc(kind, army):
    return {"kind": kind, "army": army, "home": army}


def mv(board, pos):
    return sorted(R.moves_of(board, pos, board[pos]))


def lane(a, r):
    """第 a 方的第 r 行，按列 1..9 排列"""
    return [D.pid(a, r, c) for c in range(1, COLS + 1)]


def terr(a):
    """第 a 方全部 45 个领地点"""
    return [D.pid(a, r, c) for r in range(1, ROWS + 1) for c in range(1, COLS + 1)]


print("=" * 68)
print("三方棋盘「拓扑优先」专项自检（老师 2026-09-24『举一反三』要求）")
print("=" * 68)

# ============================================================ §1 行线完整性
print("\n== 1. 行线完整性：15 条行（3 方 × 5 行）必须都是完整 9 点 ==")
bad1 = []
for _a in ARMIES:
    for _r in range(1, ROWS + 1):
        _ln = lane(_a, _r)
        for _i, _p in enumerate(_ln):
            _walks = set(R.RAYS.get(_p) or ())
            _fwd = tuple(_ln[_i + 1:])          # 朝列大那端
            _back = tuple(_ln[:_i][::-1])       # 朝列小那端
            if _fwd and _fwd not in _walks:
                bad1.append((_p, "朝C9端", _fwd))
            if _back and _back not in _walks:
                bad1.append((_p, "朝C1端", _back))
chk("全部 15 条行线的每个点都能一次直达本行两端（无列5 断裂）",
    not bad1, f"断裂 {len(bad1)} 处" + (f"，样例 {bad1[:3]}" if bad1 else ""))

# ============================================================ §2 车/炮横穿列5
print("\n== 2. 车 / 炮横穿列5（纵向中线）：每行两端出发覆盖同行全部 8 个同伴 ==")
for _kind, _cn in ((R.ROOK, "车"), (R.CANNON, "炮")):
    bad2 = []
    for _a in ARMIES:
        for _r in range(1, ROWS + 1):
            _ln = lane(_a, _r)
            for _end in (_ln[0], _ln[-1]):
                _board = {_end: pc(_kind, _a)}
                _got = set(mv(_board, _end))
                _miss = set(_ln) - {_end} - _got
                if _miss:
                    bad2.append((_end, sorted(_miss)))
    chk(f"{_cn}：15 条行 × 两端 = 30 例，空盘均可横穿列5 到同行所有点",
        not bad2, f"异常 {len(bad2)} 例" + (f"，样例 {bad2[:2]}" if bad2 else ""))

# 显式点检老师报的那一手：魏C2 的炮必须能到 C6 / C7
_b = {"132": pc(R.CANNON, 1)}
_g132 = mv(_b, "132")
chk("魏C2(132) 空盘炮可达 136(C6) / 137(C7) / 138(C8) / 139(C9)",
    {"136", "137", "138", "139"} <= set(_g132), f"实际 {_g132}")

# ============================================================ §3 象步合法性
print("\n== 3. 象步合法性：必须是「田」(|Δr|=2 且 |Δc|=2)，不过河、不跨方、田中心是格点 ==")
bad3 = []
for _p, _lst in R.ELE_T.items():
    _pa, _r0, _c0 = R.RC[_p]
    for _dest, _eye, _da in _lst:
        _qa, _r2, _c2 = R.RC[_dest]
        if (abs(_r2 - _r0), abs(_c2 - _c0)) != (2, 2):
            bad3.append((_p, _dest, f"位移({_r2 - _r0},{_c2 - _c0})非田"))
        if _qa != _pa:
            bad3.append((_p, _dest, "跨方"))
        if _da != _pa:
            bad3.append((_p, _dest, "落点方错"))
        if _eye not in B.ids:
            bad3.append((_p, _dest, "田中心不是格点"))
chk("全部象步都是 (2,2) 田字对角（三方全扫，含田中心为格点）",
    not bad3, f"非法 {len(bad3)} 条" + (f"，样例 {bad3[:3]}" if bad3 else ""))
_ele = {_a: sum(len(v) for _p, v in R.ELE_T.items() if R.RC[_p][0] == _a) for _a in ARMIES}
chk("象步数三方相等", len(set(_ele.values())) == 1, f"{_ele}")

# ============================================================ §4 马
print("\n== 4. 马：腿拓扑唯一 + 三方都能过河 ==")
_multi = [(_p, _d, _v) for _p, _dic in R.HORSE_LEG.items()
          for _d, _v in _dic.items() if len(_v) != 1]
chk("全盘马腿拓扑唯一（多腿 0 个，纯拓扑无几何兜底）",
    not _multi, f"多腿 {len(_multi)} 个" + (f"，样例 {_multi[:2]}" if _multi else ""))

_cross = {_a: 0 for _a in ARMIES}
for _p, _lst in R.HORSE_T.items():
    _pa = R.RC[_p][0]
    for _leg, _dest in _lst:
        if R.RC[_dest][0] != _pa:
            _cross[_pa] += 1
chk("三方马都能过河（跨方落点数 > 0 且三方相等）",
    min(_cross.values()) > 0 and len(set(_cross.values())) == 1, f"{_cross}")

_badm = []
for _p, _lst in R.HORSE_T.items():
    _pa, _r0, _c0 = R.RC[_p]
    for _leg, _dest in _lst:
        _qa, _r2, _c2 = R.RC[_dest]
        if _qa == _pa and (abs(_r2 - _r0), abs(_c2 - _c0)) not in ((1, 2), (2, 1)):
            _badm.append((_p, _dest, f"位移({_r2 - _r0},{_c2 - _c0})不是日"))
chk("本国境内马步位移全部是传统「日」(1,2)/(2,1)（跨方三角区回跳不在此列）",
    not _badm, f"异常 {len(_badm)} 条" + (f"，样例 {_badm[:3]}" if _badm else ""))

# ============================================================ §5 三方针对称
print("\n== 5. 三方针对称（着法数三方必须完全相等）==")


def _cnt(tmp):
    if tmp is R.ADV_T or tmp is R.GEN_T:
        return {_a: sum(len(v) for (_aa, _), v in tmp.items() if _aa == _a) for _a in ARMIES}
    return {_a: sum(len(v) for _p, v in tmp.items() if R.RC[_p][0] == _a) for _a in ARMIES}


for _tab, _name in ((R.ADV_T, "士"), (R.GEN_T, "帅"), (R.ELE_T, "象"),
                    (R.HORSE_T, "马"), (R.PAWN_T, "兵")):
    _c = _cnt(_tab)
    chk(f"{_name} 着法数三方相等", len(set(_c.values())) == 1, f"{_c}")

# ============================================================ §6 静态扫描
print("\n== 6. 静态扫描：规则层代码不得再出现几何判据（AST 级，注释不算）==")
_src_path = os.path.join(_ROOT, "server", "engine", "rules_dxf.py")
with open(_src_path, encoding="utf-8") as _f:
    _src = _f.read()
_tree = ast.parse(_src)

BANNED_ATTR = {"atan2", "acos", "asin", "cos", "sin", "tan", "degrees",
               "radians", "hypot", "ANG_TOL", "_angle", "_same_line", "_same_angle"}
BANNED_NAME = {"_same_line", "_same_angle", "_leg_rank"}
_hits = []
for _node in ast.walk(_tree):
    if isinstance(_node, ast.Attribute) and _node.attr in BANNED_ATTR:
        _hits.append((_node.lineno, f".{_node.attr}"))
    if isinstance(_node, ast.Name) and _node.id in BANNED_NAME:
        _hits.append((_node.lineno, _node.id))
    if isinstance(_node, ast.Name) and _node.id == "math":
        _hits.append((_node.lineno, "math"))
    if isinstance(_node, ast.Import):
        for _nm in _node.names:
            if _nm.name == "math":
                _hits.append((_node.lineno, "import math"))
    if isinstance(_node, ast.ImportFrom):
        for _nm in _node.names:
            if _nm.name == "math":
                _hits.append((_node.lineno, "from math import"))
_hits.sort()
chk("rules_dxf.py 中无 math / atan2 / _angle / ANG_TOL / 几何判据函数",
    not _hits, f"残留 {_hits}")

# ============================================================ 汇总
print("\n" + "=" * 68)
print(f"拓扑优先专项自检结果: {OK} 通过 / {FAIL} 失败")
print("=" * 68)
sys.exit(1 if FAIL else 0)
