# -*- coding: utf-8 -*-
"""探针：剖析「开局推荐 魏右车 111→121 是否白送马给蜀炮」（老师 2026-10-01）

老师原话：
  「我认为你一开始推荐让右车往前走了一步，不对，这样，马里面就容易被蜀的炮干掉，
    相当于马白送。你分析一下为何这样，给我理由」

本脚本只做**事实**采集，不下结论：
  ① 初始局面里 魏/蜀/吴 的车马炮到底在哪（用棋盘标签说，不用引擎号）
  ② 走完 111→121 之后，蜀方**合法着法**里有没有「炮吃魏马」
  ③ 若真有，把**炮架是谁**、路径上每一格的占位逐格列出来（这是老师说的"机理"）
  ④ 让引擎在 3/6/9/12 plies 各跑一次，看它**每层的选招与分差** —— 回答"为什么推荐它"
  ⑤ 同一局面用不同深度看「蜀会不会吃马」，判断是不是超出视野

运行：python tests/_probe_rook_horse.py
"""
import os
import sys
import copy

HERE = os.path.dirname(os.path.abspath(__file__))
SRV = os.path.join(HERE, "..", "server")
sys.path.insert(0, os.path.abspath(SRV))
sys.path.insert(0, os.path.abspath(os.path.join(SRV, "engine")))

from engine import game_dxf as GA          # noqa: E402
from engine import rules_dxf as R          # noqa: E402
from agents.search_bot import SearchBot    # noqa: E402

LETTER = {1: "ABCDE", 2: "KLMNO", 3: "FGHIJ"}
CN = {"general": "帅", "advisor": "士", "elephant": "象",
      "horse": "马", "rook": "车", "cannon": "炮", "pawn": "兵"}
ARMY = {1: "魏", 2: "吴", 3: "蜀"}


def lab(p):
    p = str(p)
    a, r, c = int(p[0]), int(p[1]), int(p[2])
    return LETTER[a][5 - r] + str(10 - c)


def board_lines(board):
    out = []
    for p in sorted(board):
        v = board[p]
        out.append(f"  {lab(p):>3}({p}) {ARMY[v['army']]}{CN[v['kind']]}"
                   + ("（副帥）" if v.get("deputy") else ""))
    return out


def cannon_hits_horse(s, shooter=3, victim=1):
    """列出 shooter 方**能吃 victim 方马**的全部着法（含炮与其他子）"""
    out = []
    for frm, to in GA.legal_moves(s, shooter):
        vic = s["board"].get(to)
        if vic and vic["army"] == victim and vic["kind"] == "horse":
            out.append((f"{frm}-{to}", frm, to, s["board"][frm], vic))
    return out


def ray_between(frm, to):
    """在 RAYS 里找 frm 射向 to 的那条射线（可能是**接线后**的贯通线）"""
    for w in (R.RAYS.get(frm) or ()):
        if to in w:
            return tuple(w)
    return None


def main():
    print("=" * 74)
    print("① 初始局面")
    print("=" * 74)
    s = GA.new_game(first=1)
    b = s["board"]
    for ln in board_lines(b):
        print(ln)

    print("\n--- 只看 车 / 马 / 炮 ---")
    for p in sorted(b):
        v = b[p]
        if v["kind"] in ("rook", "horse", "cannon"):
            print(f"  {lab(p):>3}({p}) {ARMY[v['army']]}{CN[v['kind']]}")

    print("\n" + "=" * 74)
    print("② 老师说的那手：111 是哪枚子？")
    print("=" * 74)
    v = b.get("111")
    print(f"  111 = {lab('111')} 上是 {ARMY[v['army']]}{CN[v['kind']]}" if v else "  111 空")
    v2 = b.get("121")
    print(f"  121 = {lab('121')} 上是 {ARMY[v2['army']]}{CN[v2['kind']]}" if v2
          else f"  121 = {lab('121')} 空（所以是往前走一步到空格）")

    print("\n" + "=" * 74)
    print("③ 【关键对照】走这手之前 / 之后，蜀方能不能吃魏马？")
    print("=" * 74)
    before = cannon_hits_horse(s)
    print(f"  【走之前】蜀方吃魏马 的着法：{len(before)} 条")
    for mv, frm, to, actor, vic in before:
        print(f"    {ARMY[actor['army']]}{CN[actor['kind']]} {lab(frm)} → "
              f"{lab(to)} 的魏马   [{mv}]")

    s2 = copy.deepcopy(s)
    GA.apply(s2, "111", "121")
    print(f"\n  【走之后】魏车 {lab('111')}→{lab('121')}，"
          f"现在轮到 {ARMY[s2['turn']]}，第 {s2['ply']} 手")
    after = cannon_hits_horse(s2)
    print(f"  蜀方吃魏马 的着法：{len(after)} 条")
    for mv, frm, to, actor, vic in after:
        print(f"    ★ {ARMY[actor['army']]}{CN[actor['kind']]} {lab(frm)} → "
              f"吃 {lab(to)} 的魏马   [{mv}]")

    print("\n" + "=" * 74)
    print("④ 逐格列出「炮 → 马」这条线，看炮架是谁（老师要的机理）")
    print("=" * 74)
    for mv, frm, to, actor, vic in after:
        if actor["kind"] != "cannon":
            continue
        print(f"  蜀炮 {lab(frm)} → 魏马 {lab(to)}：")
        w = ray_between(frm, to)
        if w is None:
            print("    ⚠ RAYS 里没找到这条射线（跨方接线？）")
            continue
        seq = w[:w.index(to) + 1]
        mid = [q for q in seq[1:-1] if s2["board"].get(q)]
        for q in seq:
            o = s2["board"].get(q)
            who = (f"{ARMY[o['army']]}{CN[o['kind']]}" if o else "空")
            tag = ""
            if q == to:
                tag = "   ← 目标（被吃的马）"
            elif q == frm:
                tag = "   ← 炮"
            elif o:
                tag = "   ← ★炮架" if len(mid) == 1 else "   ← 中间的子"
            print(f"    {lab(q):>3}({q}) {who}{tag}")
        print(f"    中间子数 = {len(mid)} ⇒ 炮{'**能**' if len(mid) == 1 else '不能'}打")

    print("\n" + "=" * 74)
    print("④b ★★ 决定性的一问：蜀炮吃了马之后，魏方**能不能吃回这门炮**？")
    print("      —— 「白送」与「兑子」的分界线就在这里")
    print("=" * 74)

    def recapture_test(state0, rook_moved):
        """在 state0（魏该走）走法：蜀炮 338 吃 112 的马，再看魏能否吃回 338"""
        st = copy.deepcopy(state0)
        if rook_moved:
            GA.apply(st, "111", "121")     # 魏先走：车 E9→D9
        else:
            GA.apply(st, "141", "151")     # 魏先走：随便一步（对照）
        # 手动把 112 的马拿掉、把炮放到 112（模拟蜀炮吃马）
        st["board"].pop("338", None)
        st["board"]["112"] = {"army": 3, "kind": "cannon", "home": 3,
                              "deputy": False}
        rec = [(f, t) for f, t in GA.legal_moves(st, 1) if t == "112"]
        return rec

    for moved, tag in ((False, "【车还在 E9（未走这手）】"),
                       (True, "【车已走 E9→D9（引擎推荐的）】")):
        rec = recapture_test(s, moved)
        print(f"\n  {tag} 蜀炮吃马后，魏方能吃 112 这枚炮的着法：{len(rec)} 条")
        for f, t in rec:
            o = s["board"][f]
            print(f"    {CN[o['kind']]} {lab(f)} → 吃 {lab(t)}   [{f}-{t}]")
        if not rec:
            print("    ⇒ **吃不回来** ⇒ 这马是净丢（老师说的『白送』）")
        else:
            print("    ⇒ 吃得回来 ⇒ 那只是**兑子**，不是白送")

    print("\n" + "=" * 74)
    print("⑤ 引擎逐层选招（3 / 6 / 9 / 12 plies）—— 为什么它推荐这一手")
    print("=" * 74)
    legal = GA.legal_moves(s, 1)
    for plies in (3, 6, 9, 12):
        bot = SearchBot(depth=plies // 3, time_limit=90.0, seed=20261001,
                        label=f"探针 {plies}")
        board = copy.deepcopy(s["board"])
        res = bot._jit_search(board, 1, plies, list(legal), 90.0, True)
        mv, sc, ranked, nodes, aborted = res[:5]
        print(f"\n  ── {plies} plies ──  选招 {mv}  估值 {sc:+.2f}  "
              f"节点 {nodes}  aborted={aborted}")
        try:
            items = list(ranked)
        except TypeError:
            items = []
        for i, it in enumerate(items[:8]):
            try:
                mm, ss = it[0], it[1]
            except Exception:
                mm, ss = it, None
            star = "  ★" if str(mm) == str(mv) else ""
            try:
                ss_txt = f"{float(ss):+.2f}"
            except Exception:
                ss_txt = str(ss)
            print(f"      #{i+1} {mm}  {ss_txt}{star}")

    print("\n" + "=" * 74)
    print("⑥ 走完 111→121 后，蜀方自己 12 plies 会怎么走？")
    print("=" * 74)
    s3 = copy.deepcopy(s2)
    s3["turn"] = 3
    legal3 = GA.legal_moves(s3, 3)
    bot3 = SearchBot(depth=4, time_limit=120.0, seed=20261001, label="蜀探针 12")
    r3 = bot3._jit_search(copy.deepcopy(s3["board"]), 3, 12, list(legal3),
                          None, True)
    mv3 = r3[0]
    print(f"  蜀（12 plies）想走：{mv3}  估值 {r3[1]:+.2f}")
    if mv3:
        tgt = s3["board"].get(str(mv3).split("-")[1])
        if tgt:
            print(f"    → 吃 {ARMY[tgt['army']]}{CN[tgt['kind']]}"
                  + ("　★就是老师说的马" if tgt["kind"] == "horse" else ""))
        else:
            print("    → 不吃子")


if __name__ == "__main__":
    main()

