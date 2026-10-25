# -*- coding: utf-8 -*-
"""探针：价值网络接入后，「送马」局面是否会改手（方案 c 验收）

    python tests/_probe_value_integration.py
    python tests/_probe_value_integration.py --plies 12 --tl 20

只读探针：只跑 SearchBot.choose，不写任何生产文件、不改权重。
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRV = os.path.join(ROOT, "server")
for _p in (SRV, os.path.join(SRV, "engine"), os.path.join(SRV, "agents")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from engine import game_dxf as GA                          # noqa: E402
from agents import features_dxf as F                       # noqa: E402
from agents.search_bot import SearchBot                    # noqa: E402
from agents import value_advisor as VA                     # noqa: E402

ARMY_CN = {1: "魏", 2: "吴", 3: "蜀"}


def probe_position(first=1, plies=12, tl=20.0, seed=12345):
    s = GA.new_game(first=first)
    me = s["turn"]
    legal = GA.legal_moves(s, me)
    print(f"起手方 {ARMY_CN[me]}   ply={s['ply']}   合法着法 {len(legal)} 手")

    rows = []
    for use in (False, True):
        bot = SearchBot(depth=max(1, plies // 3), time_limit=tl, seed=seed,
                        use_value=use, use_jit=True)
        t0 = time.time()
        r = bot.choose(s, legal, "", ARMY_CN[me])
        dt = time.time() - t0
        adv = bot.advisor()
        rows.append((use, r.get("move"), r.get("reason", ""), dt,
                     bot.last_info.get("value"),
                     adv.describe() if adv else "(无)"))

    print("\n" + "=" * 78)
    print(f"{'价值网络':<10}{'选着':<12}{'耗时':<9}{'说明'}")
    print("-" * 78)
    for use, mv, rs, dt, vp, desc in rows:
        print(f"{'开' if use else '关':<10}{str(mv):<12}{dt:6.2f}s  {rs}")
    print("=" * 78)
    changed = rows[0][1] != rows[1][1]
    print(f"\n结论：{'★ 改手了' if changed else '未改手（与纯搜索一致）'}")
    print(f"  关：{rows[0][1]}   开：{rows[1][1]}")
    print(f"\n顾问状态：{rows[1][5]}")
    return rows


def attack_report(first=1):
    """把「谁在攻击谁的什么子」打出来，方便人工核对悬子。"""
    s = GA.new_game(first=first)
    me = s["turn"]
    amap = F.attack_map(s["board"])
    print(f"\n--- 局面攻击关系（{ARMY_CN[me]} 视角）---")
    for q, lst in sorted(amap.items()):
        pc = s["board"].get(q)
        if not pc:
            continue
        if pc["army"] != me:
            continue
        enemies = [(p, a) for p, a in lst if a != me]
        friends = [(p, a) for p, a in lst if a == me]
        if enemies:
            kind = "悬子(无人保)" if not friends else "被攻击(有人保)"
            print(f"  {q} {ARMY_CN[pc['army']]}{pc['kind']}  ← 敌方攻击者 "
                  f"{[f'{p}{ARMY_CN[a]}' for p, a in enemies]}   {kind}")
    feat = F.extract(s, me)
    for k in ("my_hanging_val", "my_hanging_cnt", "my_attacked_val", "my_bad_trade"):
        print(f"  特征 {k:<18} = {feat[F.IDX[k]]:.3f}")


def songma_report(plies=6, tl=20.0, seed=12345, demo_move="111-121",
                  kind="mlp", wfile=""):
    """★「送马」专项：看 `111→121`（走车弃马）在榜单上的位移。

    老师 2026-10-01 报的那手：开局魏方走车 E9→(行2列1)，把自家马 112 露给敌炮。
    · 旧 `eval_dxf` 口径：+36.96 → **+37.87（涨了！）** ⇒ 搜索当然选它。
    · 悬子值 0.0 → 4.0（一个马 = 4.0）。
    ⇒ 这里直接量"搜索榜单排名"和"价值网络排名"，比看分数直观。
    """
    s = GA.new_game(first=1)
    me = s["turn"]
    legal = GA.legal_moves(s, me)
    bot = SearchBot(depth=max(1, plies // 3), time_limit=tl, seed=seed,
                    use_value=False, use_jit=True)
    sr = bot.rank_root(s, legal, plies=plies)
    sr = sr if isinstance(sr[0], tuple) else sr
    moves = [m for m, _sc in sr]
    pos_s = moves.index(demo_move) + 1 if demo_move in moves else -1

    adv = VA.ValueAdvisor.load(enabled=True, kind=kind, path=wfile)
    vr = adv.rerank(s, me, sr)
    v_moves = [m for m, _sc in vr]
    pos_v = v_moves.index(demo_move) + 1 if demo_move in v_moves else -1

    print(f"\n{'=' * 78}")
    print(f"★ 送马专项   plies={plies}   候选 {len(moves)} 手   探针着法 = {demo_move}")
    print("-" * 78)
    print(f"  搜索榜单排名   : 第 {pos_s} / {len(moves)}   榜首 {moves[0]}")
    print(f"  价值网络重排后 : 第 {pos_v} / {len(v_moves)}   榜首 {v_moves[0]}")
    d = pos_v - pos_s
    print(f"  位移           : {'↓ 降' if d > 0 else ('↑ 升' if d < 0 else '— 不变')} "
          f"{abs(d)} 名（排名越大越差）")
    print("-" * 78)
    print(f"  搜索榜前 6 : {[f'{m}({sc:+.1f})' for m, sc in sr[:6]]}")
    print(f"  重排后前 6 : {[f'{m}({sc:+.3f})' for m, sc in vr[:6]]}")
    if demo_move in dict(sr):
        frm, to = demo_move.split("-")
        print(f"  该手网络胜率 : {adv.prob_after(s, me, frm, to):.3f}   （越低越差）")
    print(f"  顾问状态   : {adv.describe()}")
    print("=" * 78)
    return pos_s, pos_v


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--plies", type=int, default=12)
    ap.add_argument("--tl", type=float, default=20.0)
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--scenario", default="all",
                    choices=("all", "songma", "pos", "attack"))
    ap.add_argument("--kind", default="mlp", help="mlp | logi")
    ap.add_argument("--wfile", default="", help="指定权重文件名（留空=按 kind 取默认）")
    a = ap.parse_args()
    print("权重文件：", VA.weights_path(a.kind, a.wfile))
    print("配置    ：", VA.load_conf())
    if a.scenario in ("all", "attack"):
        attack_report(1)
    if a.scenario in ("all", "songma"):
        songma_report(a.plies, a.tl, a.seed, kind=a.kind, wfile=a.wfile)
    if a.scenario in ("all", "pos"):
        probe_position(1, a.plies, a.tl, a.seed)
