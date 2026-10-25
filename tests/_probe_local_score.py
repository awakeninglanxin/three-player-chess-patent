# -*- coding: utf-8 -*-
"""实证探针：把**当前真实对局**的合法着法逐条丢给 LocalBot._score()，
看清「新手档」到底按什么排序 —— 验证「是不是只看吃子、吃最高价值」。

用法：服务在跑时  python tests/_probe_local_score.py
只读，不改任何状态。
"""
import json
import sys
import urllib.request

sys.path.insert(0, "server")
from agents.bots import LocalBot, VALUE          # noqa: E402
from engine import rules_dxf as R                 # noqa: E402

URL = "http://127.0.0.1:8771/api/state"
CN = {1: "魏", 2: "吴", 3: "蜀"}
KIND_CN = {R.ROOK: "车", R.CANNON: "炮", R.HORSE: "马",
           R.ELEPHANT: "象", R.ADVISOR: "士", R.PAWN: "兵", R.GENERAL: "帅"}


def fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": "probe"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    d = fetch()
    st = d["status"]
    board = {p["pos"]: {"kind": p["kind"], "army": p["army"], "home": p["home"]}
             for p in d["pieces"]}
    turn = st["turn"]
    legal_s = d["legal"]
    state = {"board": board, "turn": turn, "history": []}

    print(f"局面来源：/api/state   ply={st['ply']}  轮到 {turn}({CN[turn]}) 方")
    print(f"盘面棋数 = {len(board)}   合法着法 = {len(legal_s)} 条")
    print(f"难度档 = {d.get('difficulty')} {(d.get('difficulty_meta') or {}).get('name')}")
    print()

    bot = LocalBot()
    rows = []
    for s in legal_s:
        a, b = s.split("-")
        sc = bot._score(state, a, b)
        vic = board.get(b)
        tag = "—"
        if vic:
            tag = f"吃{CN[vic['army']]}{KIND_CN[vic['kind']]}"
        rows.append((sc, a, b, tag, board[a]["kind"]))
    rows.sort(key=lambda x: -x[0])

    print("=== 得分 Top 10（新手档就是在这里挑最高的，同分随机） ===")
    print(f"{'得分':>9}  {'着法':<11} {'类型':<12} {'走的子':<6} 什么在得分")
    for sc, a, b, tag, k in rows[:10]:
        # 拆解得分构成
        parts = []
        if tag != "—":
            v = board[b]
            parts.append(f"吃子+{VALUE[v['kind']]:.1f}")
            if v["army"] != board[a]["army"]:
                parts.append("敌方+1.0")
            if v["kind"] == R.GENERAL:
                parts.append("吃帅+900")
        parts.append(f"抖动+{sc - sum([VALUE[board[b]['kind']]] if tag != '—' else [0]):.2f}")
        print(f"{sc:>+9.2f}  {a}->{b:<6} {tag:<12} {KIND_CN[k]:<6} {' '.join(parts)}")

    print()
    print("=== 得分 Bottom 3（最不想走的） ===")
    for sc, a, b, tag, k in rows[-3:]:
        print(f"{sc:>+9.2f}  {a}->{b:<6} {tag:<12} {KIND_CN[k]}")

    print()
    print("=== 关键判据 ===")
    eat = [r for r in rows if r[3] != "—"]
    no_eat = [r for r in rows if r[3] == "—"]
    print(f"吃子着法 {len(eat)} 条，最高 {max(e[0] for e in eat):+.2f} / 最低 {min(e[0] for e in eat):+.2f}")
    if no_eat:
        print(f"不吃子   {len(no_eat)} 条，最高 {max(e[0] for e in no_eat):+.2f} / 最低 {min(e[0] for e in no_eat):+.2f}")
    top = rows[0]
    print(f"\n最高分着法 = {top[1]}->{top[2]}  {top[3]}  得分 {top[0]:+.2f}")
    print(f"⇒ 是否吃子：{'是' if top[3] != '—' else '否 —— 证明「有吃必吃」不成立'}")
    if eat and no_eat and max(e[0] for e in no_eat) > min(e[0] for e in eat):
        print("⇒ 存在「不吃子」的走法得分高于某些「吃子」走法 —— 吃子不是唯一判据")
    print()
    print("=== 里子：LocalBot 的价值表 vs 搜索档价值表 ===")
    print("bots.VALUE      =", {KIND_CN[k]: v for k, v in VALUE.items()})
    print("rules_dxf.VALUE =", {KIND_CN[k]: v for k, v in R.VALUE.items()})


if __name__ == "__main__":
    main()
