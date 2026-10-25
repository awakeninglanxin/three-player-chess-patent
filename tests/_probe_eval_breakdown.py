# -*- coding: utf-8 -*-
"""探针 3：把「为什么引擎觉得『车进一步、白丢一马』是划算的」算到分量级

老师 2026-10-01 质疑的那手：魏车 E9→D9（引擎推荐，估值 +69.1）。
实测事实（_probe_rook_horse.py）：
  · 车在 E9 时，蜀炮 H2 吃 魏马 E8 只是**兑子**（车吃得回）；
  · 车走开之后，魏**吃不回来** ⇒ 马**净丢**（老师的判断正确）。

那引擎为什么还推荐？本探针把 eval_dxf.evaluate 的**每一项**拆出来对比，
用数字说话（权重见 eval_dxf.DEFAULT_W）。

运行：python tests/_probe_eval_breakdown.py
"""
import os
import sys
import copy

HERE = os.path.dirname(os.path.abspath(__file__))
SRV = os.path.join(HERE, "..", "server")
sys.path.insert(0, os.path.abspath(SRV))
sys.path.insert(0, os.path.abspath(os.path.join(SRV, "engine")))

from engine import game_dxf as GA            # noqa: E402
from engine import rules_dxf as R            # noqa: E402
from agents import eval_dxf as EV            # noqa: E402

LETTER = {1: "ABCDE", 2: "KLMNO", 3: "FGHIJ"}
CN = {"general": "帅", "advisor": "士", "elephant": "象",
      "horse": "马", "rook": "车", "cannon": "炮", "pawn": "兵"}
ARMY = {1: "魏", 2: "吴", 3: "蜀"}
W = EV.DEFAULT_W


def lab(p):
    p = str(p)
    a, r, c = int(p[0]), int(p[1]), int(p[2])
    return LETTER[a][5 - r] + str(10 - c)


def breakdown(s, me, ply=0):
    gens, deputies, pieces, mat = EV._split(s)
    dist = EV.distances()
    my_gen = gens[me]
    my_pieces = pieces.get(me, [])
    ur = 1.0 + ply * W["urgency"]
    d = {"pressure": 0.0, "check": 0, "close1": 0, "close2": 0,
         "danger": 0.0, "material": 0.0, "deputy": 0.0, "mobility": 0}
    shim = {"board": s["board"]}
    for enemy, gpos in gens.items():
        if enemy == me:
            continue
        d["pressure"] += ur * W["pressure"] * EV.pressure_of(my_pieces, gpos, dist)
        if R.attacked(shim, gpos, {me}):
            d["check"] += 1
        dmap = dist[gpos]
        for pos, _k in my_pieces:
            dd = dmap.get(pos)
            if dd is None:
                continue
            if dd <= 1:
                d["close1"] += 1
            elif dd == 2:
                d["close2"] += 1
    for enemy in gens:
        if enemy == me:
            continue
        d["danger"] += W["danger"] * EV.pressure_of(pieces.get(enemy, []), my_gen, dist)
    my_mat = mat.get(me, 0.0)
    top_enemy = max([mat.get(e, 0.0) for e in gens if e != me] or [0.0])
    d["material"] = my_mat - top_enemy
    d["deputy"] = len(deputies.get(me, []))
    mob = sum(len(R.pseudo_moves(s, p)) for p, _ in my_pieces)
    d["mobility"] = mob
    return d, mat, gens


def fmt(tag, d):
    val = (d["pressure"] - d["danger"]
           + d["check"] * W["check"]
           + d["close1"] * W["close1"] + d["close2"] * W["close2"]
           + d["material"] * W["material"] + d["deputy"] * W["deputy"]
           + d["mobility"] * W["mobility"])
    print(f"  {tag}")
    print(f"    pressure(进攻压强)   {d['pressure']:+9.2f}")
    print(f"    danger (被压压强)    {-d['danger']:+9.2f}")
    print(f"    check  ×{W['check']:.0f} ×{d['check']} = {d['check'] * W['check']:+9.2f}")
    print(f"    close1 ×{W['close1']:.0f} ×{d['close1']} = {d['close1'] * W['close1']:+9.2f}")
    print(f"    close2 ×{W['close2']:.0f} ×{d['close2']} = {d['close2'] * W['close2']:+9.2f}")
    print(f"    material×{W['material']} ×{d['material']:+.0f} = "
          f"{d['material'] * W['material']:+9.2f}")
    print(f"    deputy ×{W['deputy']:.0f} ×{d['deputy']} = {d['deputy'] * W['deputy']:+9.2f}")
    print(f"    mobility×{W['mobility']} ×{d['mobility']} = "
          f"{d['mobility'] * W['mobility']:+9.2f}")
    print(f"    ─────────────────────────  合计 {val:+9.2f}")
    return val


def main():
    s0 = GA.new_game(first=1)
    s1 = copy.deepcopy(s0)
    GA.apply(s1, "111", "121")

    print("=" * 78)
    print("权重表（eval_dxf.DEFAULT_W）—— 先看量纲差距")
    print("=" * 78)
    for k in ("material", "pressure", "danger", "urgency",
              "check", "close1", "close2", "mobility", "deputy"):
        print(f"    {k:<10} {W[k]}")
    print(f"\n  一个马的价值 VALUE['horse'] = {R.VALUE.get('horse')}")
    print(f"  ⇒ 丢一个马，material 项只掉 {R.VALUE.get('horse') * W['material']:.2f} 分"
          f"（= 4 × 0.1）")
    print(f"  而「将军一次」= {W['check']:.0f} 分，"
          f"「有子贴到敌帅 1 步」= {W['close1']:.0f} 分")
    print(f"  ⇒ 后两项分别是「一个马」的 "
          f"{W['check'] / (R.VALUE.get('horse') * W['material']):.0f} 倍 / "
          f"{W['close1'] / (R.VALUE.get('horse') * W['material']):.0f} 倍")

    print("\n" + "=" * 78)
    print("① 站在「魏」的视角：走 111→121 前后，各分项怎么变")
    print("=" * 78)
    d0, m0, _ = breakdown(s0, 1)
    d1, m1, _ = breakdown(s1, 1)
    v0 = fmt("【走之前】魏车在 E9", d0)
    v1 = fmt("【走之后】魏车在 D9（引擎推荐的）", d1)
    print(f"\n  ⇒ 魏方视角：{v0:+.2f} → {v1:+.2f}   边际 {v1 - v0:+.2f}")
    print(f"     其中 material 项的边际 = "
          f"{(d1['material'] - d0['material']) * W['material']:+.2f}"
          f"（丢掉一个马也只值这么点）")

    print("\n" + "=" * 78)
    print("② 站在「蜀」的视角：白吃这个马，eval 只涨多少？")
    print("=" * 78)
    s2 = copy.deepcopy(s1)
    s2["turn"] = 3                        # ⚠️ GA.apply 的走子方取自 s["turn"]，必须显式设
    d2, m2, g2 = breakdown(s2, 3)
    GA.apply(s2, "338", "112")            # 蜀炮 H2 吃 魏马 E8
    d3, m3, g3 = breakdown(s2, 3)
    v2 = fmt("【吃之前】蜀方视角", d2)
    v3 = fmt("【吃之后】蜀炮吃掉魏马 E8", d3)
    print(f"\n  ⇒ 蜀方视角：{v2:+.2f} → {v3:+.2f}   边际 {v3 - v2:+.2f}")
    print(f"     其中 material 项：{d2['material']:+.0f} → {d3['material']:+.0f}"
          f"（涨 {d3['material'] - d2['material']:+.0f} 分 ⇒"
          f" ×{W['material']} = {(d3['material'] - d2['material']) * W['material']:+.2f}）")
    print(f"     ★ 也就是说：蜀方**白得一个马**，它自己的估值只涨 "
          f"{(d3['material'] - d2['material']) * W['material']:+.2f} 分")

    print("\n" + "=" * 78)
    print("③ ★★ 更要命的一点：material 项是「我 − **最强的那个**对手」")
    print("=" * 78)
    print(f"  三方子力：走之前 魏 {m2.get(1, 0):.0f} / 吴 {m2.get(2, 0):.0f} / "
          f"蜀 {m2.get(3, 0):.0f}")
    print(f"            吃之后 魏 {m3.get(1, 0):.0f} / 吴 {m3.get(2, 0):.0f} / "
          f"蜀 {m3.get(3, 0):.0f}")
    print("  ⇒ 蜀**自己的子力没变**（吃子只是移动了一门炮），而「最强对手」仍是吴方"
          f"（{max([m3.get(2, 0), m3.get(1, 0)]):.0f}）")
    print("  ⇒ material 项 = 蜀 − max(对手) = 0 → 0，**完全不动**")
    print("  ⇒ 结论：在这套估值下，「吃弱者的子」对**吃子方**的分数贡献是 **0**；")
    print("     它只在**被吃方**那边扣 0.4 分/马。这就是老师看到的「马白送」的算术根源。")


if __name__ == "__main__":
    main()
