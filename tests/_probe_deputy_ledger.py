# -*- coding: utf-8 -*-
"""副帅登记表不变量探针 —— 「账本 == 盘面」

【问题（2026-10-02 老师那局 ply 64 暴露）】
  `state["deputies"]` 是**派生表**：`{代表方: {"pos": 点位, "owner": 控制方}}`。
  当一枚副帅**自己跑去斩帅**、就地升格为代表新方的副帅时，旧登记条目无人注销 ⇒
  盘上只剩 1 枚副帅、登记表却有 2 条。前端状态条（app.js）按"每条登记"渲染一段
  文字 ⇒ 多出一条**幽灵副帅**（"吴方军帐（归蜀）"，可吴军帐里早已没有副帅）。

【修法】`patent.refresh_combat()` 以**盘面为唯一真相**重算登记表（幂等）。
  ⚠️ 判据必须是「盘上有没有 home == rep 的 deputy 棋子」，**不能用 `pos`** ——
     副帅在军帐内走动后 `pos` 从不更新（全工程无一处维护它），拿它判会误注销活副帅。

【本文件做什么】
  §1 定向场景：4 种会让账本漂移的路径，逐条断言修复后的不变量；
  §2 随机对局：N 局 × 每步断言（覆盖罕见分支，如主帅互吃、副帅易主链）；
  §3 ★证伪自检：把 `refresh_combat` 换回**修复前的版本**，断言同一场景真的会
      产生 2 条幽灵登记 —— 证明本探针抓得到真问题（不是"永远绿"的摆设）。
"""
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "server"))

from engine import game_dxf as GA      # noqa: E402
from engine import rules_dxf as R      # noqa: E402
from engine import patent as P         # noqa: E402

CN = {1: "魏", 2: "吴", 3: "蜀"}
GENERAL = R.GENERAL
OK = FAIL = 0


def chk(name, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  [OK]   {name}" + (f"  {extra}" if extra else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {extra}")


def ledger_ok(s):
    """不变量：登记表的键集 == 盘上副帅的 home 集；owner 集 == 盘上副帅的 army 集"""
    on = {q["home"]: q["army"] for q in s["board"].values() if q.get("deputy")}
    keys = set(s.get("deputies") or ())
    ownr = {d["owner"] for d in (s.get("deputies") or {}).values()}
    return (keys == set(on)) and (ownr == set(on.values())), (keys, on)


def pc(kind, home, army=None, deputy=False):
    d = {"kind": kind, "army": army or home, "home": home}
    if deputy:
        d["deputy"] = True
    return d


def mk(board, turn=1, out=(), deputies=None):
    s = GA.new_game(first=turn)
    s["board"] = {k: dict(v) for k, v in board.items()}
    s["out"] = list(out)
    s["eliminated"] = list(out)
    s["annexed"] = {}
    s["declared_lose"] = []
    s["resigned"] = []
    s["deputies"] = dict(deputies or {})
    for k in list(out):
        s["vitality"][k] = False
    P.refresh_combat(s)
    return s


# ---------------------------------------------------------------------------
print("=" * 78)
print("§1 定向场景：4 条会让账本漂移的路径")
print("=" * 78)

# --- (1) 副帅当射手斩帅（老师那局 ply 64：驻吴帐的蜀方副帅 225 → 魏帥 115）---
print("\n(1) 副帅射杀主帅 ⇒ 旧登记（吴方）必须注销、新登记（魏方）owner=蜀")
s1 = mk({
    "115": pc(GENERAL, 1),
    "225": pc(GENERAL, 2, army=3, deputy=True),
    "315": pc(GENERAL, 3),
}, turn=3, deputies={2: {"pos": "225", "owner": 3}})
_ok, _why = ledger_ok(s1)
chk(" 前提：动手前账本自洽（1 条 ↔ 盘上 1 枚）", _ok, f"{_why}")
GA.apply(s1, "225", "115")
_ok, _why = ledger_ok(s1)
chk(" ★ 斩帅后账本仍自洽（不是 2 条）", _ok, f"{_why}")
chk(" 旧登记 key=2 已消失", 2 not in s1["deputies"], f"{s1['deputies']}")
chk(" 新登记 key=1、owner=蜀", s1["deputies"].get(1, {}).get("owner") == 3,
    f"{s1['deputies']}")

# --- (2) 副帅被吃：整条登记注销 + 残兵易主 ---
print("\n(2) 副帅被吃 ⇒ 该条登记注销（盘上不再有代表该方的副帅）")
s2 = mk({
    "125": pc(GENERAL, 1, army=2, deputy=True),   # 驻魏帐的吴方副帅
    "135": pc(R.ROOK, 3),
    "215": pc(GENERAL, 2),
    "315": pc(GENERAL, 3),
}, turn=3, out=(1,), deputies={1: {"pos": "125", "owner": 2}})
chk(" 前提：动手前账本自洽", ledger_ok(s2)[0], f"{ledger_ok(s2)[1]}")
GA.apply(s2, "135", "125")
_ok, _why = ledger_ok(s2)
chk(" ★ 吃副帅后账本自洽（key=1 已注销）", _ok, f"{_why}")
chk(" key=1 不在登记表", 1 not in s2["deputies"], f"{s2['deputies']}")

# --- (3) 副帅在军帐内走动 ⇒ 账本**不能**被误注销（pos 不更新不是判据）---
print("\n(3) 副帅在军帐内走动 ⇒ 账本必须保持不变（严防「按 pos 误杀活副帅」）")
s3 = mk({
    "115": pc(GENERAL, 1),
    "225": pc(GENERAL, 2, army=3, deputy=True),   # 驻吴帐的蜀方副帅（军帐中心 N5）
    "315": pc(GENERAL, 3),
}, turn=3, deputies={2: {"pos": "225", "owner": 3}})
# ⚠️ 必须挑**军帐内 1 格**的走法（GEN_T），`225→115` 是跨方射杀、不是走动
_gen225 = set(R.GEN_T.get((2, "225"), ()))
_mv = [m for m in GA.legal_moves(s3, 3)
       if m[0] == "225" and m[1] in _gen225]
chk(" 前提：副帅 225 有**军帐内 1 格**走法", len(_mv) > 0,
    f"{_mv[:4]}（GEN_T = {sorted(_gen225)}）")
chk(" 前提：`225→115` 是射杀而非走动（不在 GEN_T 里）",
    "115" not in _gen225)
if _mv:
    GA.apply(s3, *_mv[0])
    _ok, _why = ledger_ok(s3)
    chk(" ★ 副帅走动后账本仍自洽（pos 过期不算错，key 必须还在）",
        _ok and 2 in s3["deputies"], f"{_why} / {s3['deputies']}")
    chk(" ★ 走动后登记 key=2 还在（严防「按 pos 误杀活副帅」）",
        2 in s3["deputies"], f"{s3['deputies']}")

# --- (4) 握着副帅的一方被斩帅 ⇒ owner 随残兵一并改判 ---
print("\n(4) 握有副帅的方被斩帅 ⇒ 该副帅 owner 跟着易主")
s4 = mk({
    "115": pc(GENERAL, 1),
    "125": pc(GENERAL, 2, army=1, deputy=True),   # 驻魏帐的**吴方**副帅，归魏控制
    "116": pc(R.ROOK, 3),                         # 蜀車贴魏帥
    "315": pc(GENERAL, 3),
}, turn=3, deputies={2: {"pos": "125", "owner": 1}})
chk(" 前提：动手前账本自洽", ledger_ok(s4)[0], f"{ledger_ok(s4)[1]}")
GA.apply(s4, "116", "115")                        # 蜀吃魏帥 ⇒ 魏的全部（含那枚副帅）归蜀
_ok, _why = ledger_ok(s4)
chk(" ★ 斩帅后账本自洽", _ok, f"{_why}")
chk(" ★ 吴方副帅的 owner 已改判为蜀（3）",
    s4["deputies"].get(2, {}).get("owner") == 3, f"{s4['deputies']}")

# ---------------------------------------------------------------------------
print()
print("=" * 78)
print("§2 随机对局：每步断言不变量（覆盖罕见分支）")
print("=" * 78)
ROUNDS = int(os.environ.get("LEDGER_ROUNDS", "60"))
MAXPLY = 90
rng = random.Random(20261002)
bad = []
steps = 0
for g in range(ROUNDS):
    s = GA.new_game(first=rng.choice((1, 2, 3)))
    for _ in range(MAXPLY):
        if s.get("winner") is not None or s.get("repeat_draw"):
            break
        t = s["turn"]
        mv = GA.legal_moves(s, t)
        if not mv:
            break
        GA.apply(s, *rng.choice(mv))
        steps += 1
        ok, why = ledger_ok(s)
        if not ok:
            bad.append((g, s.get("ply"), why, dict(s["deputies"])))
            break
chk(f"★ {ROUNDS} 局随机对局 / 共 {steps} 步：每一步账本都自洽",
    not bad, f"不一致 {len(bad)} 处，例：{bad[:2]}")

# ---------------------------------------------------------------------------
print()
print("=" * 78)
print("§3 ★ 证伪自检：换回「修复前」的 refresh_combat，必须重现幽灵登记")
print("=" * 78)


def _old_refresh_combat(s):        # 修复前版本：没有 prune
    P.refresh_vitality(s)
    out_of = set(s.get("out") or ())
    owners = {d["owner"] for d in s.get("deputies", {}).values()}
    for k in (1, 2, 3):
        s["combat"][k] = False if k in out_of else (bool(s["vitality"].get(k)) or k in owners)


_new = P.refresh_combat
P.refresh_combat = _old_refresh_combat
try:
    s5 = mk({
        "115": pc(GENERAL, 1),
        "225": pc(GENERAL, 2, army=3, deputy=True),
        "315": pc(GENERAL, 3),
    }, turn=3, deputies={2: {"pos": "225", "owner": 3}})
    GA.apply(s5, "225", "115")
    chk("★ 旧版本下**确实**留下 2 条（1 条真 + 1 条幽灵）",
        len(s5["deputies"]) == 2, f"{s5['deputies']}")
    chk("★ 旧版本下账本与盘面**不一致**（本探针验的就是这个）",
        not ledger_ok(s5)[0], f"{ledger_ok(s5)[1]}")
finally:
    P.refresh_combat = _new

# 换回新版本，同一场景必须自洽 —— 证明修复有效（A/B 对照）
s6 = mk({
    "115": pc(GENERAL, 1),
    "225": pc(GENERAL, 2, army=3, deputy=True),
    "315": pc(GENERAL, 3),
}, turn=3, deputies={2: {"pos": "225", "owner": 3}})
GA.apply(s6, "225", "115")
chk("★ 新版本下同一场景只有 1 条（A/B 对照确认修复点）",
    len(s6["deputies"]) == 1 and ledger_ok(s6)[0], f"{s6['deputies']}")

print()
print("=" * 78)
print(f"副帅账本不变量探针：{OK} 通过 / {FAIL} 失败")
print("=" * 78)
sys.exit(1 if FAIL else 0)
