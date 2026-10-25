# -*- coding: utf-8 -*-
"""重放老师当前局面的 14 步，逐步用引擎复算合法性。

背景：老师报「魏国的士凭空消失了」。从 /api/state 的 log 看，魏士的生命轨迹是
    ply10  114 → 125   （人类自己走的）
    ply12  245 → 125   （被蜀方棋子吃掉，captured=advisor/captured_army=1）
本脚本的目的：确认这 14 步**每一步都在 legal 里**（= 引擎认为合法），
并打印 ply12 那一步的**射线路径与炮架数量**，判定「炮吃子」是否符合传统炮规则。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))

from engine import game_dxf as GA          # noqa: E402
from engine import geometry_dxf as D       # noqa: E402
from engine import rules_dxf as R          # noqa: E402

KIND = {"general": "帅", "advisor": "士", "elephant": "象",
        "horse": "马", "rook": "车", "cannon": "炮", "pawn": "兵"}
NAME = {1: "魏", 2: "吴", 3: "蜀"}

MOVES = [
    ("132", "137"), ("238", "312"), ("311", "312"), ("147", "157"),
    ("232", "118"), ("332", "248"), ("119", "118"), ("218", "239"),
    ("248", "245"), ("114", "125"), ("212", "233"), ("245", "125"),
    ("233", "245"), ("125", "245"),
]


def cnt(s):
    out = {}
    for a in (1, 2, 3):
        n = sum(1 for pc in s["board"].values() if pc["home"] == a)
        out[a] = n
    return out


def shot_path(p, dest):
    """在 RAYS[p] 里找包含 dest 的那条射线，返回 (整条射线, 中间隔子列表)。"""
    for w in R.RAYS.get(p) or ():
        if dest in w:
            k = w.index(dest)
            seg = w[:k]
            return w, [q for q in seg if q in s_global["board"]]
    return None, None


print("=" * 78)
print("重放老师的 14 步")
print("=" * 78)
s = GA.new_game()
s_global = s

print(f"开局：{cnt(s)}  (魏16/吴16/蜀16)")
print()

ok = bad = 0
for i, (frm, to) in enumerate(MOVES, 1):
    turn = s["turn"]
    lm = GA.legal_moves(s)
    legal = (frm, to) in set(lm)
    actor = s["board"].get(frm)
    victim = s["board"].get(to)
    tag = "OK " if legal else "!!非法!!"
    if legal:
        ok += 1
    else:
        bad += 1
    an = KIND.get(actor["kind"], "?") if actor else "空!"
    vn = f"{KIND.get(victim['kind'], '?')}({NAME.get(victim['home'], '?')})" if victim else "-"
    print(f"[{tag}] ply{i:2d} {NAME[turn]}(a{turn}) {frm}→{to}  走:{an}  吃:{vn}"
          f"   legal总数={len(lm)}")

    # 特别关注 ply10/11/12/13/14
    if i in (10, 11, 12):
        print(f"        ↳ {frm} 上实际是 {actor}")
        if i == 11:
            # 下一步就是 245→125 吃士，先把现场钉住
            print("        ↳ 此刻棋盘关键点：")
            for q in ("245", "235", "225", "215", "155", "145", "135", "125"):
                print(f"            {q} = {s['board'].get(q)}")
            p = R.RAYS.get("245") or ()
            print(f"        ↳ RAYS[245] 共 {len(p)} 条射线：")
            for w in p:
                print(f"            {w}")
            c3 = [m for m in GA.legal_moves(s, 3) if m[0] == "245"]
            print(f"        ↳ 蜀方 245 的 legal 落点 = {[b for a, b in c3]}")

    if legal:
        GA.apply(s, frm, to)
        s_global = s
    else:
        print("        ↳ 引擎不接受这一步，重放终止（说明日志里有非法着法！）")
        break

print()
print(f"结果：合法 {ok} 步 / 非法 {bad} 步")
print(f"终局：{cnt(s)}  (魏14/吴12/蜀15)")
print()

# ---- 单独复算 ply12：245 → 125 的炮吃子 ----
print("=" * 78)
print("专项：ply12 `245 → 125`（吃魏士）是否符合传统炮规则")
print("=" * 78)
w, blockers = shot_path("245", "125")
if w is None:
    print("  ⚠️ RAYS[245] 里没有任何射线包含 125 → 炮根本不该能打到这里")
else:
    print(f"  射线（245 出发）：{w}")
    print(f"  中间隔子共 {len(blockers)} 个：{blockers}")
    for q in blockers:
        print(f"      {q} = {s['board'].get(q)}")
    verdict = "合法（恰 1 个炮架）" if len(blockers) == 1 else f"★非法★（应为 1 个炮架，实为 {len(blockers)} 个）"
    print(f"  结论：{verdict}")

print()
print("=" * 78)
print("专项：ply5 `232 → 118`（吴方吃魏马）")
print("=" * 78)
w2, b2 = shot_path("232", "118")
print(f"  射线：{w2}")
print(f"  中间隔子共 {len(b2) if b2 is not None else 'N/A'} 个：{b2}")
