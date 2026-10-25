# -*- coding: utf-8 -*-
"""实时对局重放核验（对弈台 8771 观战用）

作用：
  1. 从 /api/state 拉当前对局的全部走法，用引擎**逐手重放**，每手先比对
     legal_moves() 是否包含该着法 → 若不包含即报「非法」。
  2. 把 row5 上的跨方走法分三类打印：
        · 门      = 本方 row5 中点 ↔ 邻方 row5 中点（155/255/355 三者相连）
        · 脖颈    = row5 列1 / 列9 的跨方邻接
        · 原文回跳 = 起点 row5 列∈{4,6} → 邻方 row5 中点（规则.md §二.1 的 6 对）
  3. 打印当前战况摘要。

口径提醒：标签 = 「行字母 + 10−引擎列」，见 docs/三人中国象棋的游戏规则.md §二.1。
"""
import sys, os, json, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "server"))

from engine import game_dxf as GD          # noqa: E402
from engine import rules_dxf as R          # noqa: E402
from engine import geometry_dxf as G       # noqa: E402

CN = {1: "魏", 2: "吴", 3: "蜀"}
LETTER = {(1, 1): "E", (1, 2): "D", (1, 3): "C", (1, 4): "B", (1, 5): "A",
          (2, 1): "O", (2, 2): "N", (2, 3): "M", (2, 4): "L", (2, 5): "K",
          (3, 1): "J", (3, 2): "I", (3, 3): "H", (3, 4): "G", (3, 5): "F"}


def lab(p):
    a, r, c = G.parse(p)
    return "%s%s%d" % (LETTER.get((a, r), "?"), CN.get(a, "?"), 10 - c)


def fetch(url="http://127.0.0.1:8771/api/state"):
    """显式禁用代理，否则会被系统代理拦成假 502。"""
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return json.loads(op.open(url, timeout=15).read().decode("utf-8"))


def classify(f, t):
    """给一个走法分类：返回 None 或 类别字符串。"""
    af, rf, cf = G.parse(f)
    at, rt, ct = G.parse(t)
    if af == at:
        return None                     # 同方走法
    if rf != 5 or rt != 5:
        return "跨方非row5"
    if cf == 5 and ct == 5:
        return "门"
    if cf in (1, 9) and ct in (1, 9):
        return "脖颈"
    if cf in (4, 6) and ct == 5:
        return "原文回跳"
    return "其他row5跨方"


def main():
    d = fetch()
    moves = [it for it in (d.get("log") or []) if it.get("type") == "move"]
    print("=" * 66)
    print("实时对局重放核验  ——  ply=%s  走法条数=%d" % (d["status"]["ply"], len(moves)))
    print("=" * 66)

    s = GD.new_game(first=1)
    bad = []
    cross = []
    replayable = bool(moves) and moves[0].get("ply") == 1
    if replayable:
        for it in moves:
            f, t, who = it["from"], it["to"], it["army"]
            legal = GD.legal_moves(s, army=who, frozen=None)
            if (f, t) not in legal:
                bad.append((it["ply"], f, t, lab(f), lab(t)))
            k = classify(f, t)
            if k:
                cross.append((it["ply"], f, t, lab(f), lab(t), k))
            # 注意：apply() 返回的是走法记录(note)，不是 state；它会**原地**改 s 并自动推进轮次
            GD.apply(s, f, t, frozen=None)
    else:
        # 日志只在 /api/state 下发最近 80 条（match.py:489），对局超长时起点局面已不可知
        for it in moves:
            k = classify(it["from"], it["to"])
            if k:
                cross.append((it["ply"], it["from"], it["to"],
                              lab(it["from"]), lab(it["to"]), k))

    # ---- 合法性 ----
    print()
    if replayable:
        print("【一】合法性：%d / %d 手全部落在 legal_moves 内" % (len(moves) - len(bad), len(moves)))
        for b in bad:
            print("   ✗ 非法 ply%-3d %s(%s) -> %s(%s)" % b)
    else:
        print("【一】合法性：本局 ply=%s > 80 手窗口，/api/state 只下发最近 %d 条 → 无法从初始局面重放。"
              % (d["status"]["ply"], len(moves)))
        print("     改由「进程启动时间晚于规则文件修改时间」证明服务端加载的是新规则（见命令行核验）。")

    # ---- 跨方走法分类 ----
    print()
    print("【二】跨方走法（共 %d 手）" % len(cross))
    by = {}
    for c in cross:
        by.setdefault(c[5], []).append(c)
    for k in ("门", "脖颈", "原文回跳", "其他row5跨方", "跨方非row5"):
        if k not in by:
            continue
        print("   %s：%d 手" % (k, len(by[k])))
        for c in by[k]:
            print("      ply%-3d %s -> %s   (%s -> %s)" % (c[0], c[1], c[2], c[3], c[4]))

    # ---- 战况 ----
    st = d["status"]
    print()
    print("【三】战况")
    print("   ply=%s  轮次=%s方  存活=%s  胜者=%s"
          % (st["ply"], CN[st["turn"]], [CN[x] for x in st["alive"]], st["winner"]))
    print("   子力=%s" % {CN.get(int(k), k): v for k, v in (d.get("material") or {}).items()})
    print("   吃子=%s" % {CN.get(int(k), k): v for k, v in (d.get("kills") or {}).items()})
    if st.get("checks"):
        print("   将军=%s" % st["checks"])
    if st.get("frozen"):
        print("   停走=%s" % [CN.get(x, x) for x in st["frozen"]])
    print()
    print("【四】终局状态：finished=%s drawn=%s" % (d.get("finished"), d.get("drawn")))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
