# -*- coding: utf-8 -*-
"""验证：某方出局后，是否还能"轮到它动棋子"（走真实的 GA.apply 流程）

场景：魏車吃吴帅 -> 魏拿到吴的副帅；蜀車再吃魏帅 -> 魏出局
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from server.engine import geometry_dxf as G     # noqa: E402
from server.engine import rules_dxf as R        # noqa: E402
from server.engine import game_dxf as GA        # noqa: E402

CN = G.ARMY_CN          # 1魏 2吴 3蜀


def show(tag, s):
    st = GA.status(s)
    by_army = {}
    for pos, pc in s["board"].items():
        by_army.setdefault(pc["army"], []).append(
            f"{pos}({R.KIND_CN[pc['kind']]}{'/副帅' if pc.get('deputy') else ''})")
    dep = {CN[int(k)]: f"{v['pos']}归{CN[v['owner']]}" for k, v in st["deputies"].items()}
    print(f"\n--- {tag}")
    print(f"    轮到 = {CN.get(st['turn'])}   存活 = {[CN[a] for a in st['alive']]}   "
          f"出局 = {[CN[a] for a in st['eliminated']]}   winner = {st['winner']}")
    print(f"    副帅表 = {dep}")
    for a in (1, 2, 3):
        items = by_army.get(a, [])
        print(f"    army={CN[a]}: {len(items)} 子 {items[:6]}{' ...' if len(items) > 6 else ''}")


s = GA.new_game()

# 魏(1)車 从 214 吃 吴(2)帥 215
s["board"]["214"] = {"kind": R.ROOK, "army": 1, "home": 1}
n = GA.apply(s, "214", "215")
show(f"魏車吃吴帅（{n.get('eliminated') and CN[n['eliminated']]}出局）", s)

# 蜀(3)車 从 116 吃 魏(1)帥 115
s["board"]["116"] = {"kind": R.ROOK, "army": 3, "home": 3}
n2 = GA.apply(s, "116", "115")
show(f"蜀車吃魏帅（{n2.get('eliminated') and CN[n2['eliminated']]}出局）", s)

print("\n=== 检查 ===")
st = GA.status(s)
out = st["eliminated"]

# 1) 盘上还有多少「army 属于已出局方」的棋子
orphan = [(pos, pc) for pos, pc in s["board"].items() if pc["army"] in out]
print(f"1) 盘上仍属已出局方的棋子：{len(orphan)} 个 "
      f"{[(p, CN[c['army']], R.KIND_CN[c['kind']]) for p, c in orphan][:8]}")

# 2) 存活方能否动这些棋子
alive = [a for a in (1, 2, 3) if a not in out]
for a in alive:
    mv_all = GA.legal_moves(s, a)
    touch = [f"{f}-{t}" for f, t in mv_all
             if any(s["board"].get(f) is c for _p, c in orphan)]
    print(f"2) 存活方 {CN[a]}：总着法 {len(mv_all)} 步，能碰到orphan 的 = {touch}")
    if mv_all:
        print(f"     着法样例 {mv_all[:8]}")

# 3) 出局方是否还会被轮到 / 还能走子
print(f"3) 当前轮到的方 = {CN.get(st['turn'])}（已出局方 {[CN[a] for a in out]}）")
for a in out:
    print(f"   {CN[a]} 出局后 legal_moves = {len(GA.legal_moves(s, a))} 步")

# 4) 终局
print(f"4) 存活方 {len(alive)} 个，winner = {st['winner']} "
      f"（应为 {CN[alive[0]] if len(alive) == 1 else '未定'}）")
