# -*- coding: utf-8 -*-
"""对拍器：numba 内核 vs Python 引擎 —— **方案 ① 的硬门禁**

【老师 2026-09-25 定的规矩】
    「新内核必须与现有引擎**随机局面对拍**，逐点比对**着法集合完全一致**
      （含马蹩腿、过河不跨中线、三角区回跳、兵过河、炮翻山、帅见面、副帅、
        连吃上限），全绿才接入。」

【本脚本查什么】
    第 1 节  开局/随机局面 —— 逐点伪合法着法（有序列表完全一致）
    第 2 节  随机局面 —— 整方着法集合
    第 3 节  反向攻击表 under_attack —— 全 135 点全方比对
    第 4 节  叶节点评估 leaf —— 与 SearchBot._leaf 逐局面比对（容差 1e-6）
    第 5 节  专项构造局面 —— 逐条覆盖老师列出的规则点
    第 6 节  编码往返（encode → decode）无损

【为什么必须做「逐点」而不只是「整方」】
    整方比对只保证「并集」一致，可能掩盖「A 点多一步、B 点少一步」的对冲。
    逐点比对能把偏差钉到具体点位，出问题时能直接定位到是哪条规则抄错了。
"""
import os
import random
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "server"))
sys.path.insert(0, os.path.join(HERE, "..", "server", "agents"))

import eval_dxf as E                         # noqa: E402
from engine import game_dxf as GA            # noqa: E402
from engine import geometry_dxf as D         # noqa: E402
from engine import nb_core as NB             # noqa: E402
from engine import rules_dxf as R            # noqa: E402
from search_bot import SearchBot             # noqa: E402

OK = 0
FAIL = 0
FAILS = []


def chk(cond, msg, detail=""):
    global OK, FAIL
    if cond:
        OK += 1
    else:
        FAIL += 1
        FAILS.append(msg + (f"  [{detail}]" if detail else ""))
        if len(FAILS) <= 25:
            print(f"  ✗ {msg}  {detail}")


def sec(t):
    print(f"\n=== {t} ===")


# ---------------------------------------------------------------- 局面构造
def make_board(specs):
    """按规格直接摆一个棋盘 —— specs: [(pos, kind, army, home, deputy?)]"""
    board = {}
    for it in specs:
        pos, kind, army, home = it[0], it[1], it[2], it[3]
        pc = {"kind": kind, "army": army, "home": home}
        if len(it) > 4 and it[4]:
            pc["deputy"] = True
        board[pos] = pc
    return board


def move_str(frm, to):
    return f"{frm}-{to}"


# ---------------------------------------------------------------- 1/2 随机局面
def random_positions(n, seed=20260925, steps=(6, 42)):
    """用 Python 引擎随机走子生成 n 个随机局面（覆盖中残局各种子力状态）"""
    rng = random.Random(seed)
    out = []
    s = GA.new_game(first=1)
    out.append(("开局", GA.clone(s)))
    for i in range(n - 1):
        s = GA.new_game(first=1 + (i % 3))
        target = rng.randint(*steps)
        for _ in range(target):
            lm = GA.legal_moves(s, s["turn"])
            if not lm:
                break
            frm, to = rng.choice(lm)
            try:
                GA.apply(s, frm, to)
            except Exception:
                break
            if GA.status(s).get("winner"):
                break
        out.append((f"随机#{i + 1}（{target} 步内）", GA.clone(s)))
    return out


def check_position(tag, s):
    board = s["board"]
    have = [p for p, _pc in board.items()]

    # ---- 1. 逐点伪合法着法：**有序列表完全一致** ----
    for p in have:
        py = R.pseudo_moves(s, p)
        nb = NB.gen_point_py(board, p)
        if py != nb:
            only_py = [x for x in py if x not in nb]
            only_nb = [x for x in nb if x not in py]
            chk(False, f"{tag} · 点 {p} 着法不一致",
                f"仅Python有={only_py} 仅numba有={only_nb}")
        elif set(py) != set(nb):
            chk(False, f"{tag} · 点 {p} 顺序不同（集合相同）",
                f"{py} vs {nb}")
        else:
            chk(True, f"{tag} · 点 {p}")

    # ---- 2. 整方伪合法着法：集合一致 ----
    for a in (1, 2, 3):
        py = set(R.side_moves(s, a))
        nb = set(NB.gen_side_py(board, a))
        chk(py == nb, f"{tag} · {D.ARMY_CN[a]}方整方着法集合",
            f"仅Python={sorted(py - nb)[:6]} 仅numba={sorted(nb - py)[:6]}")

    # ---- 3. 反向攻击表：全 135 点全方比对 ----
    for t in D.BOARD.ids:
        for a in (1, 2, 3):
            py = R.under_attack(board, t, a)
            nb = bool(NB.under_attack(NB.encode_board(board), np.int32(NB.POS[t]),
                                      np.int32(a)))
            if py != nb:
                chk(False, f"{tag} · under_attack({t}, {D.ARMY_CN[a]})",
                    f"Python={py} numba={nb}")

    # ---- 6. 编码往返无损 ----
    code = NB.encode_board(board)
    back = NB.decode_board(code)
    norm = lambda d: {p: (pc["kind"], pc["army"], pc["home"],
                          bool(pc.get("deputy"))) for p, pc in d.items()}
    chk(norm(board) == norm(back), f"{tag} · 棋盘编码往返无损")


# ---------------------------------------------------------------- 4 叶节点评估
_WEIGHTS = None


def check_leaf(tag, s, ply=0):
    global _WEIGHTS
    if _WEIGHTS is None:
        _WEIGHTS = SearchBot(depth=1).w
    bot = SearchBot(depth=1, weights=_WEIGHTS)
    dist = E.distances()
    # ⚠️ `_leaf` 用的是实例状态 `self._ur`（正常由 `_choose` 按 ply 设好），
    #    而直接调 `_leaf` 时它还是 `__init__` 里的 1.0。
    #    不显式对齐就会得到「numba 系统性偏大」的假红灯
    #    （偏大量 ≈ ply×urgency×压强项，ply 越大越离谱）—— 这是对拍器踩过的坑。
    bot._ur = 1.0 + ply * float(_WEIGHTS.get("urgency", 0.0))
    for me in (1, 2, 3):
        py = bot._leaf(dict(s["board"]), me, dist)
        nb = NB.leaf_py(s["board"], me, _WEIGHTS, ply=ply)
        chk(abs(py - nb) < 1e-6, f"{tag} · leaf({D.ARMY_CN[me]})",
            f"Python={py!r} numba={nb!r} Δ={py - nb:+.3e}")


# ---------------------------------------------------------------- 5 专项局面
def special_cases():
    """老师点名的规则点逐条构造 —— 每条都是「规则原文 → 期望着法集合」"""
    cases = []

    # ① 马蹩腿：魏马在 A2(121)，A1(111)/A3(131) 是它的腿？
    #    直接用真实引擎算期望，这里只负责把子摆上去（期望值由 Python 引擎给）
    cases.append(("马-空旷", make_board([
        ("121", R.HORSE, 1, 1), ("115", R.GENERAL, 1, 1),
        ("225", R.GENERAL, 2, 2), ("325", R.GENERAL, 3, 3)])))
    cases.append(("马-蹩腿(111占)", make_board([
        ("121", R.HORSE, 1, 1), ("111", R.PAWN, 1, 1),
        ("115", R.GENERAL, 1, 1), ("225", R.GENERAL, 2, 2),
        ("325", R.GENERAL, 3, 3)])))
    cases.append(("马-蹩腿(122占)", make_board([
        ("121", R.HORSE, 1, 1), ("122", R.PAWN, 1, 1),
        ("115", R.GENERAL, 1, 1), ("225", R.GENERAL, 2, 2),
        ("325", R.GENERAL, 3, 3)])))
    # ② 过河不跨中线（老师报的 A6→K6）：马在 A6(154)
    cases.append(("马-过河不跨中线 A6", make_board([
        ("154", R.HORSE, 1, 1), ("115", R.GENERAL, 1, 1),
        ("225", R.GENERAL, 2, 2), ("325", R.GENERAL, 3, 3)])))
    cases.append(("马-过河不跨中线 A4", make_board([
        ("144", R.HORSE, 1, 1), ("115", R.GENERAL, 1, 1),
        ("225", R.GENERAL, 2, 2), ("325", R.GENERAL, 3, 3)])))
    cases.append(("马-过河不跨中线 K4", make_board([
        ("244", R.HORSE, 2, 2), ("115", R.GENERAL, 1, 1),
        ("225", R.GENERAL, 2, 2), ("325", R.GENERAL, 3, 3)])))
    # ③ 三角区回跳：A4(144) ↔ F5(355) 等 6 对
    for pos, army in (("144", 1), ("355", 3), ("244", 2), ("155", 1)):
        cases.append((f"马-三角区回跳 @{pos}", make_board([
            (pos, R.HORSE, army, army),
            ("115", R.GENERAL, 1, 1), ("225", R.GENERAL, 2, 2),
            ("325", R.GENERAL, 3, 3)])))
    # ④ 兵过河：A7(153) 未过河 → 不可横走，唯一正解是过河到 F3(357)
    cases.append(("兵-未过河 A7", make_board([
        ("153", R.PAWN, 1, 1), ("115", R.GENERAL, 1, 1),
        ("225", R.GENERAL, 2, 2), ("325", R.GENERAL, 3, 3)])))
    cases.append(("兵-已过河(在蜀领地)", make_board([
        ("357", R.PAWN, 1, 1), ("115", R.GENERAL, 1, 1),
        ("225", R.GENERAL, 2, 2), ("325", R.GENERAL, 3, 3)])))
    cases.append(("兵-营点 155", make_board([
        ("155", R.PAWN, 1, 1), ("115", R.GENERAL, 1, 1),
        ("225", R.GENERAL, 2, 2), ("325", R.GENERAL, 3, 3)])))
    cases.append(("兵-底线 111", make_board([
        ("111", R.PAWN, 1, 1), ("115", R.GENERAL, 1, 1),
        ("225", R.GENERAL, 2, 2), ("325", R.GENERAL, 3, 3)])))
    # ⑤ 炮翻山：炮 + 炮架 + 目标；以及无架/双架
    cases.append(("炮-翻山(有架)", make_board([
        ("111", R.CANNON, 1, 1), ("131", R.PAWN, 1, 1), ("151", R.PAWN, 2, 2),
        ("115", R.GENERAL, 1, 1), ("225", R.GENERAL, 2, 2),
        ("325", R.GENERAL, 3, 3)])))
    cases.append(("炮-无架", make_board([
        ("111", R.CANNON, 1, 1), ("151", R.PAWN, 2, 2),
        ("115", R.GENERAL, 1, 1), ("225", R.GENERAL, 2, 2),
        ("325", R.GENERAL, 3, 3)])))
    cases.append(("炮-双架", make_board([
        ("111", R.CANNON, 1, 1), ("121", R.PAWN, 1, 1), ("131", R.PAWN, 1, 1),
        ("151", R.PAWN, 2, 2), ("115", R.GENERAL, 1, 1),
        ("225", R.GENERAL, 2, 2), ("325", R.GENERAL, 3, 3)])))
    # ⑥ 帅见面射杀：魏帅 E5(155) 与蜀帅 F5(355) 同列5 贯通线、中间无子
    cases.append(("帅-照面射杀(无阻挡)", make_board([
        ("155", R.GENERAL, 1, 1), ("355", R.GENERAL, 3, 3),
        ("225", R.GENERAL, 2, 2)])))
    cases.append(("帅-照面被挡", make_board([
        ("155", R.GENERAL, 1, 1), ("255", R.PAWN, 2, 2),
        ("355", R.GENERAL, 3, 3), ("225", R.GENERAL, 2, 2)])))
    # ⑦ 副帅：就地升格、army≠home（收编后）
    cases.append(("副帅-deputy", make_board([
        ("155", R.GENERAL, 1, 1, True), ("355", R.GENERAL, 3, 3),
        ("225", R.GENERAL, 2, 2)])))
    cases.append(("副帅-易主(army≠home)", make_board([
        ("155", R.GENERAL, 2, 1, True), ("355", R.GENERAL, 3, 3),
        ("225", R.GENERAL, 2, 2)])))
    # ⑧ 象：田中心卡腿 / 不过河
    cases.append(("象-田中心空", make_board([
        ("113", R.ELEPHANT, 1, 1), ("115", R.GENERAL, 1, 1),
        ("225", R.GENERAL, 2, 2), ("325", R.GENERAL, 3, 3)])))
    cases.append(("象-田中心占", make_board([
        ("113", R.ELEPHANT, 1, 1), ("124", R.PAWN, 1, 1),
        ("115", R.GENERAL, 1, 1), ("225", R.GENERAL, 2, 2),
        ("325", R.GENERAL, 3, 3)])))
    cases.append(("象-跨中线", make_board([
        ("155", R.ELEPHANT, 1, 1), ("115", R.GENERAL, 1, 1),
        ("225", R.GENERAL, 2, 2), ("325", R.GENERAL, 3, 3)])))
    # ⑨ 车：沿射线到棋盘尽头、遇子止步
    cases.append(("车-九宫中心", make_board([
        ("125", R.ROOK, 1, 1), ("115", R.GENERAL, 1, 1),
        ("225", R.GENERAL, 2, 2), ("325", R.GENERAL, 3, 3)])))
    cases.append(("车-过河点 E5", make_board([
        ("155", R.ROOK, 1, 1), ("115", R.GENERAL, 1, 1),
        ("225", R.GENERAL, 2, 2), ("325", R.GENERAL, 3, 3)])))
    # ⑩ 士：九宫斜走
    cases.append(("士-军帐中心", make_board([
        ("124", R.ADVISOR, 1, 1), ("115", R.GENERAL, 1, 1),
        ("225", R.GENERAL, 2, 2), ("325", R.GENERAL, 3, 3)])))
    # ⑪ 营点分叉（列5 纵向射线在营点一分为二）—— 车/炮 seen 去重的关键路径。
    #    老师 2026-09-25 报的「吴炮 G5 / 魏炮 A5」正是这条线：
    #    RAYS[145] 有两条支线，都以 155 开头 ⇒ 落点必须去重，否则会重复生成。
    cases.append(("车-分叉口 B5(145) 155空", make_board([
        ("145", R.ROOK, 1, 1), ("115", R.GENERAL, 1, 1),
        ("225", R.GENERAL, 2, 2), ("325", R.GENERAL, 3, 3)])))
    cases.append(("车-分叉口 B5(145) 155有子", make_board([
        ("145", R.ROOK, 1, 1), ("155", R.PAWN, 1, 1), ("115", R.GENERAL, 1, 1),
        ("225", R.GENERAL, 2, 2), ("325", R.GENERAL, 3, 3)])))
    cases.append(("炮-分叉口 B5(145) 隔155打E5", make_board([
        ("145", R.CANNON, 2, 2), ("155", R.PAWN, 1, 1), ("115", R.GENERAL, 1, 1),
        ("225", R.GENERAL, 2, 2), ("325", R.GENERAL, 3, 3)])))
    cases.append(("炮-G5(345) 隔魏炮A5打魏帅E5", make_board([
        ("345", R.CANNON, 2, 2), ("155", R.CANNON, 1, 1), ("115", R.GENERAL, 1, 1),
        ("225", R.GENERAL, 2, 2), ("325", R.GENERAL, 3, 3)])))
    cases.append(("炮-G5(345) 中间无架(355空)", make_board([
        ("345", R.CANNON, 2, 2), ("115", R.GENERAL, 1, 1),
        ("225", R.GENERAL, 2, 2), ("325", R.GENERAL, 3, 3)])))
    cases.append(("炮-B5(145) 155空+115帅", make_board([
        ("145", R.CANNON, 1, 1), ("115", R.GENERAL, 1, 1),
        ("225", R.GENERAL, 2, 2), ("325", R.GENERAL, 3, 3)])))
    # ⑫ 营点顶点本身（三条纵线的公共端点，分叉最密集处）
    for v, a in (("155", 1), ("255", 2), ("355", 3)):
        cases.append((f"车-营点顶点 {v}", make_board([
            (v, R.ROOK, a, a), ("115", R.GENERAL, 1, 1),
            ("225", R.GENERAL, 2, 2), ("325", R.GENERAL, 3, 3)])))
        cases.append((f"炮-营点顶点 {v}", make_board([
            (v, R.CANNON, a, a), ("115", R.GENERAL, 1, 1),
            ("225", R.GENERAL, 2, 2), ("325", R.GENERAL, 3, 3)])))
    # ⑬ ★【2026-09-25 新增】「主帅已被斩、残兵仍在盘」—— **搜索内部**状态
    #
    #    为什么要专门造这一类盘面：
    #      搜索的轻量 `_make/_unmake` **不做副帅变换**（那是引擎的专利逻辑），
    #      所以搜索树里到处是"某方帅没了、它那 15 个残兵还杵在盘上"的局面。
    #      而 JIT 的 `leaf` 原来 ⑤子力/③敌方压强 写的是 `for a in range(1, 4)`，
    #      把**出局方**也算进去了；Python 版是 `for enemy in gens`，
    #      而 `gens` 只装"主帅还在盘上"的方 ⇒ 出局方那堆残兵被当成"最强对手"，
    #      导致 JIT 分数系统性偏低。
    #      实测（局4/16步·吴，吃掉魏帅的那一手 235-125）：
    #          Python = 4038.319627 ／ JIT = 4015.969627，**Δ = 22.350000**
    #      ⇒ 这两条分支必须逐字对齐，否则搜索值全盘偏。
    cases.append(("帅已被斩-吴帅消失(残兵仍在)", make_board([
        ("115", R.GENERAL, 1, 1), ("325", R.GENERAL, 3, 3),
        ("221", R.ROOK, 2, 2), ("223", R.CANNON, 2, 2),
        ("231", R.HORSE, 2, 2), ("241", R.PAWN, 2, 2)])))
    cases.append(("帅已被斩-魏吴双斩(只余蜀帅)", make_board([
        ("325", R.GENERAL, 3, 3),
        ("111", R.ROOK, 1, 1), ("113", R.CANNON, 1, 1),
        ("221", R.ROOK, 2, 2), ("223", R.CANNON, 2, 2)])))
    cases.append(("帅已被斩-我方(魏)帅被斩", make_board([
        ("225", R.GENERAL, 2, 2), ("325", R.GENERAL, 3, 3),
        ("111", R.ROOK, 1, 1), ("221", R.ROOK, 2, 2)])))
    return cases


def captured_general_cases(positions):
    """从真实局面里**拆掉某一方的帅**（不补副帅）—— 精确复刻搜索内部状态

    ⚠️ 这是 2026-09-25 那个 Δ=22.35 的 bug 的专属回归：只要 `leaf` 的
       ⑤子力 / ③敌方压强 又用上"全部三方"，这里立刻红灯。
    """
    out = []
    for tag, s in positions:
        board = s["board"]
        gens = [p for p, pc in board.items()
                if pc["kind"] == R.GENERAL and not pc.get("deputy")]
        for gp in gens[:1]:                       # 每局只拆一个，避免样本爆炸
            b2 = {p: dict(pc) for p, pc in board.items() if p != gp}
            if len(b2) < 6:
                continue
            killed = board[gp]["home"]
            out.append((f"{tag}－拆掉{D.ARMY_CN[killed]}帅（残兵仍在）", b2,
                        dict(s, board=b2)))
    return out


def check_special(tag, board):
    s = {"board": board, "turn": 1, "eliminated": [], "annexed": {},
         "history": [], "passed": [], "winner": None, "ply": 0, "first": 1}
    # 逐点比对
    for p in board:
        py = R.pseudo_moves(s, p)
        nb = NB.gen_point_py(board, p)
        chk(py == nb, f"专项[{tag}] · 点 {p}", f"Python={py} numba={nb}")
        chk(len(nb) == len(set(nb)), f"专项[{tag}] · 点 {p} 落点无重复", str(nb))
    # 整方
    for a in (1, 2, 3):
        py = set(R.side_moves(s, a))
        nb = set(NB.gen_side_py(board, a))
        chk(py == nb, f"专项[{tag}] · {D.ARMY_CN[a]}方集合",
            f"仅Python={sorted(py - nb)} 仅numba={sorted(nb - py)}")


# ---------------------------------------------------------------- 主流程
def main():
    print("=" * 72)
    print("对拍器：numba 内核 vs Python 引擎（方案 ① 硬门禁）")
    print("=" * 72)

    sec("1/2/3/6. 开局 + 随机局面（逐点 / 整方 / 攻击表 / 编码往返）")
    positions = random_positions(20)
    for tag, s in positions:
        check_position(tag, s)
        print(f"  · {tag}：{len(s['board'])} 子  已查 "
              f"（OK={OK} FAIL={FAIL}）")

    sec("4. 叶节点评估 leaf（与 SearchBot._leaf 比对，容差 1e-6）")
    for tag, s in positions[:12]:
        check_leaf(tag, s, ply=int(s.get("ply", 0) or 0))
    print(f"  · 已比对 12 个局面 × 3 视角  （OK={OK} FAIL={FAIL}）")

    sec("5. 专项构造局面（老师点名的规则点）")
    for tag, board in special_cases():
        check_special(tag, board)
        print(f"  · {tag}")

    sec("4b. leaf —— 「主帅已被斩、残兵仍在盘」（搜索内部状态 · 2026-09-25 回归）")
    cap = captured_general_cases(positions)
    for tag, board, s2 in cap:
        check_leaf(tag, s2, ply=int(s2.get("ply", 0) or 0))
        check_special(tag, board)
    print(f"  · 已比对 {len(cap)} 个「拆帅」局面 × 3 视角 + 着法集合 "
          f"（OK={OK} FAIL={FAIL}）")

    print()
    print("=" * 72)
    print(f"结果：OK={OK}  FAIL={FAIL}")
    if FAILS:
        print("\n失败明细（最多 25 条）：")
        for m in FAILS:
            print("  ✗ " + m)
    print("=" * 72)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
