# -*- coding: utf-8 -*-
"""DXF 引擎自检（**这个才是服务真正在跑的引擎**）

为什么单独建一套：
    旧的 tests/test_basic.py / test_patent.py 导入的是 `geometry` / `rules` / `game`
    —— 那是老师给出 DXF 工程图**之前**的废弃几何。服务（match.py / app.py）、
    Arena、SearchBot、eval 全部走的是 `*_dxf`。所以旧测试跑绿跑红都不能说明
    线上引擎的状态（实测：旧测试期望「炮沿行滑到 133~137」「B.palace」，
    DXF 的 Board 连 palace 都没有，只有 gong）。

覆盖：
    §1 几何结构（135 点 / 度数分布 / 九宫方位 / 三条中心地带）
    §2 初始局面
    §3 单子走法点检
    §4 蹩马腿 / 塞象眼（马走传统「日」8 步，腿唯一；另有三角区回跳独立条款）
    §5 兵：一步一格 / 过河前不横走 / 过河跨国
    §6 走法无重复（2026-09-24 修复的回归闸门）
    §7 将军 / 停走
    §8 吃帅 / 出局 / 收编 / 副帅（专利版机制）
    §9 几何预计算与现场重算等价
    §10 随机对局冒烟

跑法：cd 中国三人象棋_专利版 && python tests/test_dxf.py
"""
import os
import sys
import time
import random
import collections

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "server"))

from engine import geometry_dxf as G        # noqa: E402
from engine import rules_dxf as R           # noqa: E402
from engine import game_dxf as GA           # noqa: E402

B = G.BOARD
OK = FAIL = 0


def chk(name, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  [OK]   {name} {extra}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


def pc(kind, army, home=None, deputy=False):
    d = {"kind": kind, "army": army, "home": army if home is None else home}
    if deputy:
        d["deputy"] = True
    return d


def mv(board, pos):
    """站在 pos 的棋子能走到的落点集合"""
    return sorted(R.moves_of(board, pos, board[pos]))


def synth(pieces, turn=1):
    """用给定棋子搭一个局面（三方帅建议都给，否则 legal_moves 会被过滤空）"""
    s = GA.new_game(first=turn)
    s["board"] = {p: dict(q) for p, q in pieces.items()}
    s["eliminated"] = []
    s["annexed"] = {}
    s["out"] = []
    s["history"] = []
    s["ply"] = 0
    return s


BLOCK = pc(R.PAWN, 1)          # 用来堵路的己方兵


# ============================================================ §1 几何结构
print("== 1. 几何结构（DXF 权威）==")
chk("落子点 135 个", len(B.ids) == 135, f"实际 {len(B.ids)}")
chk("POLYLINE 51 条", len(B.lines) == 51, f"实际 {len(B.lines)}")

deg = collections.Counter(len(B.adj[p]) for p in B.ids)
want_deg = {2: 6, 3: 57, 4: 60, 5: 9, 8: 3}
chk("度数分布 = 每方原图的 3 倍（{2:6,3:57,4:60,5:9,8:3}）",
    dict(sorted(deg.items())) == want_deg, f"实际 {dict(sorted(deg.items()))}")

chk("九宫共 3 座（每方一座）", len(B.gong) == 3, f"实际 {sorted(B.gong)}")
chk("九宫 = 行1-3 × 列4-6", all(
    sorted(B.gong[a]) == sorted(f"{a}{r}{c}" for r in (1, 2, 3) for c in (4, 5, 6))
    for a in (1, 2, 3)), f"魏九宫 {B.gong[1]}")
chk("九宫中心度 = 8（米字格）", all(len(B.adj[f"{a}25"]) == 8 for a in (1, 2, 3)),
    f"125 度={len(B.adj['125'])}")

# 方位：老师的指定是 D5=魏 / I5=吴 / N5=蜀
chk("方位 D5(125)=魏 / I5(225)=吴 / N5(325)=蜀",
    G.ARMY_CN == {1: "魏", 2: "吴", 3: "蜀"}
    and B.gong[1][4] == "125" and B.gong[2][4] == "225" and B.gong[3][4] == "325",
    f"ARMY_CN={G.ARMY_CN} 中心={B.gong[1][4]},{B.gong[2][4]},{B.gong[3][4]}")

tri_pts = {p for p in B.ids if G.parse(p)[1] == 5 and G.parse(p)[2] in (1, 9)}
chk("三条中心地带（赤壁/荆州/祁山）内部无落子点", bool(B.tri),
    f"tri 顶点={sorted(B.tri.items())}")
chk("每方领地 45 点（3×45 = 135）",
    all(sum(1 for p in B.ids if G.parse(p)[0] == a) == 45 for a in (1, 2, 3)),
    f"实际 {[sum(1 for p in B.ids if G.parse(p)[0] == a) for a in (1, 2, 3)]}")


# ============================================================ §2 初始局面
print("\n== 2. 初始局面 ==")
s0 = GA.new_game()
chk("棋子总数 48", len(s0["board"]) == 48, f"实际 {len(s0['board'])}")
cnt = collections.Counter(p["army"] for p in s0["board"].values())
chk("三方各 16 子", dict(cnt) == {1: 16, 2: 16, 3: 16}, f"实际 {dict(cnt)}")
chk("帅位 115 / 215 / 315",
    [GA.general_pos(s0, a) for a in (1, 2, 3)] == ["115", "215", "315"],
    f"实际 {[GA.general_pos(s0, a) for a in (1, 2, 3)]}")
firsts = [len(GA.legal_moves(s0, a)) for a in (1, 2, 3)]
chk("三方首着数相同（120° 对称）", len(set(firsts)) == 1, f"各 {firsts[0]} 步")
chk("开局无将军、无停走",
    not GA.check_map(s0) and not GA.frozen_now(s0),
    f"将军={GA.check_map(s0)} 停走={sorted(GA.frozen_now(s0))}")
chk("开局着法无重复", all(
    len(GA.legal_moves(s0, a)) == len(set(GA.legal_moves(s0, a))) for a in (1, 2, 3)))


# ============================================================ §3 走法点检
print("\n== 3. 单子走法点检（初始局面，含阻碍）==")
spot = {"111": ["121", "131"], "112": ["131", "133"], "113": ["131", "135"],
        "114": ["125"], "115": ["125"], "141": ["151"],
        # 132 = 魏C2（行3列2）；记法 = 行字母(A~E) + 列数字(1~9)。
        # 【2026-09-24 深夜 · 行线缝合】本条曾只到 135(C5) 就断 —— 因为本变形网格上
        #   「行」在 列5（纵向中线）处有折角（16.31°~47.58°），几何建射线时被切成两段，
        #   车/炮**横穿不了列5**。`_splice_row_rays()` 用**拓扑**缝回后，行 131~139 贯通：
        #   炮沿行可平移到 136(C6)、137(C7)；再往前 138(C8) 是**己方另一门炮**（挡住），
        #   炮又不吃己方子且隔子后不能落空点 → **止于 137**。
        "132": ["122", "131", "133", "134", "135", "136", "137",
                "142", "152", "318", "348", "358"]}
for pos, want in spot.items():
    got = mv(s0["board"], pos)
    chk(f"{pos} {R.KIND_CN[s0['board'][pos]['kind']]} → {want}", got == want, f"实际 {got}")

chk("炮必须隔子才能吃（132 无炮架时吃不到紧邻的 123）",
    "123" not in mv(s0["board"], "132"), f"实际 {mv(s0['board'], '132')}")

b = {"111": pc(R.ROOK, 1)}
got = mv(b, "111")
chk("空盘上车 111 沿行滑到全部 112~119", set(f"11{c}" for c in range(2, 10)) <= set(got),
    f"实际 {got}")
chk("空盘上车 111 可跨国走到蜀方 319~359（中间地带无落子点）",
    {"319", "329", "339", "349", "359"} <= set(got), f"实际 {got}")


# ============================================================ §4 马腿/象眼
print("\n== 4. 蹩马腿 / 塞象眼（马走传统「日」8 步，腿唯一）==")
# 马走**传统「日」8 步**：(Δr,Δc) ∈ {(±1,±2), (±2,±1)} → 恰好 8 步。
#   判据 = **数格点数**（一个方向 1 格 + 另一方向 2 格），不是几何长度、不是夹角。
#   规则依据 = docs/三人中国象棋的游戏规则.md §二.1 原文：
#     「马在其它地方行进方式与传统象棋行进方式（**起、终点相对坐标**）完全相符」
#   网格依据 = 本棋盘内部点只有 4 个邻居（145 → 135/155/144/146；全盘 60 个内部点皆然）
#     → 4 连通四边形网格。
#   腿唯一性：8 步口径全盘多腿 0 个，与传统象棋同构。
h = {"112": pc(R.HORSE, 1)}
chk("馬112 空盘 → 124、131、133（传统「日」8 步；另 5 步越界）",
    set(mv(h, "112")) == {"124", "131", "133"}, f"实际 {mv(h, '112')}")
chk("馬112 三个落点的腿各自唯一",
    all(len(R.HORSE_LEG["112"][d]) == 1 for d in ("124", "131", "133")),
    f"实际 {R.HORSE_LEG['112']}")
chk("馬112 的腿 = 113(→124)、122(→131 和 133) —— 一条腿管两个**对称**落点，与传统象棋同构",
    R.HORSE_LEG["112"] == {"124": ("113",), "131": ("122",), "133": ("122",)},
    f"实际 {R.HORSE_LEG['112']}")
chk("HORSE_MOVES 恰 8 步，且全满足「一个方向 1 格 + 另一方向 2 格」",
    len(R.HORSE_MOVES) == 8
    and all(sorted((abs(_a), abs(_b))) == [1, 2] for _a, _b in R.HORSE_MOVES),
    f"实际 {len(R.HORSE_MOVES)} 步：{R.HORSE_MOVES}")

# 蹩腿语义与传统象棋一致：一条腿被占，砍掉**该腿管的所有落点**，其余不受影响。
h1 = {"112": pc(R.HORSE, 1), "122": BLOCK}
chk("堵住腿 122（不分敌我）→ 131、133 同时走不到；124 不受影响",
    set(mv(h1, "112")) == {"124"}, f"实际 {mv(h1, '112')}")
h2 = {"112": pc(R.HORSE, 1), "113": BLOCK}
chk("堵住腿 113 → 124 走不到；131、133 不受影响",
    set(mv(h2, "112")) == {"131", "133"}, f"实际 {mv(h2, '112')}")

# 三角区回跳 —— 马的**独立条款**（规则原文 §二.1 逐字穷举，6 对 / 双向 12 个方向）：
#   A5 无子 → A4↔F5、A6↔K5 ;  F5 无子 → F4↔K5、F6↔A5 ;  K5 无子 → K4↔A5、K6↔F5
#   标签 -> 引擎：图中数字 d = 10 - 列（棋盘原图上魏底边的「1」贴在最左，
#   而引擎里魏 row1 的列 9 在最左 → 数字 1 = 列 9）。故：
#     A4=156  A6=154  F4=356  F6=354  K4=256  K6=254 ；A5=155  F5=355  K5=255
#   （rules_dxf._triangle_rebound，由 _REBOUND_SELF 展开为双向的 REBOUND 表）。
REBOUND_CASES = [
    ("156", "355"),   # A4  ↔ F5  (腿 A5=155)
    ("154", "255"),   # A6  ↔ K5  (腿 A5=155)
    ("356", "255"),   # F4  ↔ K5  (腿 F5=355)
    ("354", "155"),   # F6  ↔ A5  (腿 F5=355)
    ("256", "155"),   # K4  ↔ A5  (腿 K5=255)
    ("254", "355"),   # K6  ↔ F5  (腿 K5=255)
]
REBOUND_LEG = {"156": "155", "154": "155", "356": "355",
               "354": "355", "256": "255", "254": "255"}
for _p, _q in REBOUND_CASES:
    hr = {_p: pc(R.HORSE, R.RC[_p][0])}
    chk(f"空盘 馬{_p} 三角区回跳 → {_q}（{REBOUND_LEG[_p]} 空）",
        _q in mv(hr, _p), f"实际 {mv(hr, _p)}")
    hr2 = {_p: pc(R.HORSE, R.RC[_p][0]), REBOUND_LEG[_p]: BLOCK}
    chk(f"堵住 {REBOUND_LEG[_p]} → 馬{_p} 回跳 {_q} 被蹩",
        _q not in mv(hr2, _p), f"实际 {mv(hr2, _p)}")

# 双向性：REBOUND 表必须成对（原文「可来回跳」）
chk("三角区回跳 6 对全部双向（REBOUND 表 12 个方向）",
    all((REBOUND_LEG[_p], _q) in R.REBOUND.get(_p, ())
        and (REBOUND_LEG[_p], _p) in R.REBOUND.get(_q, ())
        for _p, _q in REBOUND_CASES),
    f"REBOUND 条目 {sorted((k, len(v)) for k, v in R.REBOUND.items())}")

e = {"113": pc(R.ELEPHANT, 1)}
chk("象113 空盘 → 131、135", set(mv(e, "113")) == {"131", "135"}, f"实际 {mv(e, '113')}")

# 专利版 · 象（2026-09-24 老师定夺）：
#   「象走格子交点，不存在射线；田中心有子就卡腿，不能跨到田字对角」
#   113 往 131 的田中心 = 122；113 往 135 的田中心 = 124
#   田中心 = 起点→落点连线的中点所对应的格点
chk("田中心表：113→131 是 122、113→135 是 124",
    {d: t for d, t, _a in R.ELE_T["113"]} == {"131": "122", "135": "124"},
    f"实际 {R.ELE_T['113']}")
e1 = {"113": pc(R.ELEPHANT, 1), "122": BLOCK}
chk("田中心 122 有子 → 131 走不到（135 不受影响，各有各的田中心）",
    mv(e1, "113") == ["135"], f"实际 {mv(e1, '113')}")
e2 = {"113": pc(R.ELEPHANT, 1), "124": BLOCK}
chk("田中心 124 有子 → 135 走不到（131 不受影响）",
    mv(e2, "113") == ["131"], f"实际 {mv(e2, '113')}")
e3 = {"113": pc(R.ELEPHANT, 1), "122": BLOCK, "124": BLOCK}
chk("两个田中心都有子 → 象被堵死", mv(e3, "113") == [], f"实际 {mv(e3, '113')}")
e4 = {"113": pc(R.ELEPHANT, 1), "112": BLOCK, "114": BLOCK, "123": BLOCK}
chk("起点邻格（112/114/123）有子不再算塞象眼 → 仍能跨田（旧口径会误判）",
    set(mv(e4, "113")) == {"131", "135"}, f"实际 {mv(e4, '113')}")
# 田中心表全盘体检：步数、非空、且不落在起点/终点上
# 【2026-09-24 深夜更正】旧实现走**几何射线**（`B.rays`）凑"田"，结果既多又少：
#   多 48 条**跨方飞象**（几何射线在「跨方接缝」处方向突变，如 魏E1(151)→蜀E9(359)），
#   又**漏掉 24 条**合法象步（射线在列5 折角处断裂）。
#   改成**纯拓扑枚举 (±2,±2)** 后按数学可精确复算：
#     行方向数 r=1..5 → 1,1,2,1,1 合计 6 ；列方向数 c=1..9 → 1,1,2,2,2,2,2,1,1 合计 14
#     ⇒ 每方 6×14 = **84** 步，三方 84×3 = **252**（实测吻合），且 0 条非法、0 条跨方。
_all_ele = [(p, d, t) for p, lst in R.ELE_T.items() for d, t, _a in lst]
chk("象表全盘 252 步（三方各 84）且每步都有田中心",
    len(_all_ele) == 252 and all(t for _p, _d, t in _all_ele),
    f"实际 {len(_all_ele)}")
_ele_by_army = {a: sum(1 for p, _d, _t in _all_ele if R.RC[p][0] == a) for a in (1, 2, 3)}
chk("象步三方完全对称（各 84）", len(set(_ele_by_army.values())) == 1, f"实际 {_ele_by_army}")
_bad_ele_shape = [(p, d) for p, d, _t in _all_ele
                  if (abs(R.RC[d][1] - R.RC[p][1]), abs(R.RC[d][2] - R.RC[p][2])) != (2, 2)]
chk("全部象步都是 (2,2) 田字对角（0 条 Δ=(0,4) 之类的非法步）",
    not _bad_ele_shape, f"非法 {len(_bad_ele_shape)} 条 {_bad_ele_shape[:3]}")
_bad_ele_cross = [(p, d) for p, d, _t in _all_ele if R.RC[d][0] != R.RC[p][0]]
chk("象步不跨方（0 条跨方飞象）", not _bad_ele_cross,
    f"非法 {len(_bad_ele_cross)} 条 {_bad_ele_cross[:3]}")
_bad_tian = [(p, d, t) for p, d, t in _all_ele if t in (p, d)]
chk("田中心不落在起点或终点上", not _bad_tian, f"异常 {_bad_tian[:5]}")

# 注意：ELE_T 是按**点位**建的表，不带归属方（收编后 home 可能不等于所在领地），
# 所以「象不过河」是运行时按 home 过滤的 —— 必须用运行时的落脚点来验。
bad_ele = []
for _home in (1, 2, 3):
    for _pos in B.ids:
        _b = {_pos: pc(R.ELEPHANT, _home)}
        for _d in mv(_b, _pos):
            if G.parse(_d)[0] != _home:
                bad_ele.append((_home, _pos, _d))
chk("象不过河：任意位置放象，落点都限本方领地", not bad_ele, f"越界 {bad_ele[:5]}")


# ============================================================ §5 兵
print("\n== 5. 兵：一步一格 / **未过河不横走** / 过河（跨中间地带）==")
chk("兵141（行4）只有前方 151 一个落点（一步一格）",
    mv({"141": pc(R.PAWN, 1)}, "141") == ["151"], f"实际 {mv({'141': pc(R.PAWN, 1)}, '141')}")
chk("兵143（行4）只有前方 153（不能横走）",
    mv({"143": pc(R.PAWN, 1)}, "143") == ["153"], f"实际 {mv({'143': pc(R.PAWN, 1)}, '143')}")
got = mv({"151": pc(R.PAWN, 1)}, "151")
# 【2026-09-25 老师口径】「过河」= 跨过中间地带（祁山/赤壁/荆州）进入对方领地；
#   兵在 row5 **未过河之前不能横向左右行走** ⇒ 151 唯一正解 = 过河到蜀 359。
chk("兵151（行5 **未过河**）不可横走 152", "152" not in got, f"实际 {got}")
chk("兵151 唯一正解 = 过河走到蜀方 359（跨中间地带）", got == ["359"], f"实际 {got}")
chk("兵151 不回头（不含 141）", "141" not in got, f"实际 {got}")


# ============================================================ §6 走法无重复
print("\n== 6. 走法无重复（2026-09-24 修复的回归闸门）==")
dup = []
for pos in B.ids:
    for kind in (R.ROOK, R.HORSE, R.ELEPHANT, R.ADVISOR, R.GENERAL, R.CANNON, R.PAWN):
        b1 = {pos: pc(kind, 1)}
        r = mv(b1, pos)
        if len(r) != len(set(r)):
            dup.append((pos, R.KIND_CN[kind]))
chk("空盘上 135 点 × 7 子种均无重复落点", not dup, f"重复 {dup[:5]}")

random.seed(11)
dup_games = 0
checks = 0
for _g in range(4):
    st = GA.new_game()
    for _ in range(60):
        if st["winner"]:
            break
        for a in (1, 2, 3):
            lm = GA.legal_moves(st, a)
            checks += 1
            if len(lm) != len(set(lm)):
                dup_games += 1
        lg = GA.legal_moves(st, st["turn"])
        if not lg:
            GA._advance(st)
            continue
        GA.apply(st, *random.choice(lg))
chk(f"随机对局 {checks} 个 (局面,方) 的合法着法均无重复", dup_games == 0,
    f"含重复的 {dup_games} 个")


# ============================================================ §7 将军/停走
print("\n== 7. 将军 / 停走 ==")
# 【2026-09-24 夜 调整】原来把魏車放在 255（= 吴的三角区顶点 row5-5）。
#   补上「战线直通」后，255 正好在**贯通纵线的中轴**上：它会同时打到三方底线数字 5
#   那一点，而三个帅当时都在底线列5 → 三方同时被将军，「第三方停走」这个前提就没了。
#   为保住本测试的原意，把魏車挪到 234（吴行3列4 = 吴的“图6线”）：
#     · 该贯通线只接到 魏列6 → 只能打「吴底线图6」与「魏底线图4」；
#     · 吴帅改放 214（吴底线列4 = 图6）→ 只有吴被将军；
#     · 魏帅 115（图5）、蜀帅 315（图5）都不在这条线上 → 蜀才是第三方 → 停走。
# 【2026-09-25 再调整 · 射杀规则上线】蜀帅必须**离开列5**：
#   新规则下帅能沿见面线远程攻击对方帅（`attacked` 走 BUILDERS，已含射杀），
#   若蜀帅仍放 315（列5），它会与魏帅 115 互相"将军" → 三方全卷入 →
#   就没有"第三方"可停走了。改放 **316（蜀行1列6）**：列6 与列5 不共线
#   ⇒ 蜀既不攻击谁、也不被谁攻击 ⇒ 仍然是那个干净的第三方。
sc = synth({"115": pc(R.GENERAL, 1), "214": pc(R.GENERAL, 2),
            "316": pc(R.GENERAL, 3), "234": pc(R.ROOK, 1),
            "311": pc(R.PAWN, 2), "319": pc(R.PAWN, 2)})
cm = GA.check_map(sc)
chk("魏車 234 与吴帅 214 同线 → 吴方被将军",
    2 in cm and 1 in cm.get(2, set()), f"将军表={cm}")
fz = GA.frozen_now(sc)
chk("将军期间第三方（蜀）被判停走", 3 in fz, f"停走={sorted(fz)}")
chk("被将军方（吴）与叫将方（魏）不停走", not ({1, 2} & fz), f"停走={sorted(fz)}")
chk("停走方（蜀）合法着法为空", GA.legal_moves(sc, 3) == [],
    f"实际 {GA.legal_moves(sc, 3)[:3]}")
chk("停走方（蜀）的棋子不可被吃",
    not any(b in sc["board"] and sc["board"][b]["army"] == 3
            for _a, b in GA.legal_moves(sc, 1)), f"停走方棋子位置 {GA.general_pos(sc, 3)}")


# ============================================================ §8 吃帅
print("\n== 8. 吃帅 / 出局 / 收编 / 副帅（专利版机制）==")
# ⚠️ 2026-09-24：这里必须放一个堵路兵。
#   魏帥115 与 蜀帥315 同在【E5-A5-F5-J5】这条贯通纵线上，若中间无子就是
#   **违规的"帅见面"**（规则《一、9》）。而一旦处于见面状态，《一、10》要求
#   轮到走的一方二选一（阻隔/移开帅，或把对方判负），普通吃子会被拦下 ——
#   所以本局面在用 255 的車堵住另一条线的同时，还得用 135 的兵堵住 115-315 这条线，
#   才是"合法局面"，才能用来测「吃帅」。
s8 = synth({"115": pc(R.GENERAL, 1), "215": pc(R.GENERAL, 2),
            "315": pc(R.GENERAL, 3), "255": pc(R.ROOK, 1),
            "135": pc(R.PAWN, 1),                                   # 堵 115-315
            "311": pc(R.PAWN, 2), "319": pc(R.PAWN, 2)})
chk("前提：局面本身不违反《一、9》（无违规见面）",
    not GA.facing_pairs(s8, strict=True), f"{GA.facing_pairs(s8, strict=True)}")
legal8 = GA.legal_moves(s8, 1)
chk("魏車能吃吴帅（255→215 在合法着法里）", ("255", "215") in legal8,
    f"合法 {len(legal8)} 步")
chk("合法着法无重复", len(legal8) == len(set(legal8)))

before = sum(1 for q in s8["board"].values() if q["home"] == 2)
note = GA.apply(s8, "255", "215")
chk("落子返回吃帅记录", note.get("captured") == R.GENERAL
    and note.get("eliminated") == 2, f"{note}")
chk("吴方出局", 2 in s8["eliminated"], f"出局={s8['eliminated']}")

annexed = sum(1 for q in s8["board"].values()
              if q["home"] == 2 and q["army"] == 1 and not q.get("deputy"))
chk("吴方残兵归魏方（不含副帅）", annexed == before - 1,
    f"收编 {annexed} 子（吃帅前归吴 {before} 子）")

dep = [(p, q) for p, q in s8["board"].items() if q.get("deputy")]
chk("吴方军帐内生成副帅且归魏方控制（吃帅的棋子就地升格）",
    len(dep) == 1 and dep[0][1]["army"] == 1 and dep[0][1]["home"] == 2,
    f"副帅 {dep}")
chk("副帅登记表已登记", s8["deputies"].get(2, {}).get("owner") == 1,
    f"{s8['deputies']}")
chk("出局方生命力与战斗力归零",
    s8["vitality"][2] is False and s8["combat"][2] is False,
    f"vitality={s8['vitality'][2]} combat={s8['combat'][2]}")
chk("吃帅方战斗力仍为 True（握有副帅）", s8["combat"][1] is True)
chk("回合跳过已出局的吴方", s8["turn"] == 3, f"turn={GA.ARMY_CN[s8['turn']]}")
chk("仅出局一方不算终局（还活着两方）", s8["winner"] is None,
    f"winner={s8['winner']}")

# ---- 出局方的「一切」都必须易主（2026-09-24 老师指出，修复后加的闸门）
# 场景：魏吃吴帅（魏拿到吴的副帅）-> 蜀再吃魏帅（魏出局）
# 旧 bug：魏出局时只收编「home==魏 and army==魏」的棋子，魏手里那批吴残兵
#         会留成孤儿（army 仍是已出局的魏），存活方一步也动不了它们。
s9 = GA.new_game()
s9["board"]["214"] = {"kind": R.ROOK, "army": 1, "home": 1}     # 魏車 贴吴帅
GA.apply(s9, "214", "215")                                        # 魏吃吴帅
n_ok = {"deputies": dict(s9["deputies"])}
s9["board"]["116"] = {"kind": R.ROOK, "army": 3, "home": 3}     # 蜀車 贴魏帅
GA.apply(s9, "116", "115")                                        # 蜀吃魏帅 -> 魏出局

out_armies = set(s9["eliminated"])
orphans = [(p, c) for p, c in s9["board"].items() if c["army"] in out_armies]
chk("出局方名下不留任何棋子（无孤儿）", not orphans,
    f"残留 {len(orphans)} 个 {[(p, R.KIND_CN[c['kind']]) for p, c in orphans][:6]}")

alive_side = [a for a in (1, 2, 3) if a not in out_armies]
captured = [p for p, c in s9["board"].items() if c.get("home") != c["army"]]
movable = sum(1 for f, _t in GA.legal_moves(s9, alive_side[0]) if f in captured)
chk("存活方能调动收编来的棋子", movable > 0,
    f"可动的收编子 {movable} / 收编共 {len(captured)}")

chk("前一手拿到的副帅，随原控制方出局而一并易主",
    all(d["owner"] in alive_side for d in s9["deputies"].values()),
    f"deputies={s9['deputies']}")

chk("三方出局两方后终局判定正确", len(alive_side) == 1 and s9["winner"] == alive_side[0],
    f"winner={s9['winner']} alive={alive_side}")

chk("出局方再也走不出任何着法",
    all(not GA.legal_moves(s9, a) for a in out_armies),
    f"{ {G.ARMY_CN[a]: len(GA.legal_moves(s9, a)) for a in out_armies} }")


# ============================================================ §9 几何缓存
print("\n== 9. 几何预计算与现场重算等价 ==")
bad = 0
n_ray = 0
for p in B.ids:
    for r in B.rays[p]:
        n_ray += 1
        if tuple(r.walk) != tuple(B._ray_walk_raw(p, r.dir)):
            bad += 1
chk(f"射线缓存 {n_ray} 条与逐点重算完全一致", bad == 0, f"不一致 {bad} 条")

n_sp = 0
bad_sp = 0
for p in B.ids:
    for d, w in B.straight_paths(p):
        n_sp += 1
        if list(w) != list(B._ray_walk_raw(p, d)):
            bad_sp += 1
chk(f"straight_paths {n_sp} 条与重算一致", bad_sp == 0, f"不一致 {bad_sp} 条")

t0 = time.time()
import importlib                                             # noqa: E402
importlib.reload(G)
chk("重新载入几何（含预计算）< 3s", time.time() - t0 < 3.0,
    f"{time.time() - t0:.2f}s")


# ============================================================ §10 冒烟
print("\n== 10. 随机对局冒烟 ==")
random.seed(7)
t0 = time.time()
worst = ("", 0.0)
ended = {"斩帅": 0, "手数上限": 0}
for _g in range(3):
    st = GA.new_game(first=1 + _g % 3)
    for _ply in range(120):
        if st["winner"]:
            break
        lg = GA.legal_moves(st, st["turn"])
        if not lg:
            GA._advance(st)
            continue
        t1 = time.time()
        GA.apply(st, *random.choice(lg))
        dt = time.time() - t1
        if dt > worst[1]:
            worst = (f"{st['history'][-1]}", dt)
    if st["winner"]:
        ended["斩帅"] += 1
    else:
        ended["手数上限"] += 1
chk("随机对局无异常抛出", True, f"3 局共 {time.time() - t0:.1f}s，结果 {ended}")
chk("单步落子 < 0.5s", worst[1] < 0.5, f"最慢 {worst[1] * 1000:.0f}ms @ {worst[0]}")


# ============================================================ §11 战线直通
print("\n== 11. 战线直通（底边数字和=10 ⇒ 共线；战线上不画线，必须按规则补）==")
# 老师 2026-09-24 的判据：「凡是自己底边对应的数字与对面的数字相合为10就代表共线」
#   「他们战线上是不画线的吧」→ 原图只画到各自 row5，中间的战线不画
#   → DXF 里只有「图1↔图9」三对真连成直线，其余 9 条接线必须按数字规则补出来。
chk("战线直通已生效（替换/新增条数 > 0）",
    R.SPLICE_STAT[0] + R.SPLICE_STAT[1] > 0, f"统计={R.SPLICE_STAT}")

# 老师原题：吴 M6 打魏 4线
_wu_m6 = R.RAYS["234"]                      # 234 = 吴行3列4 = 吴 M6（图6）
_chain = [p for path in _wu_m6 for p in path]
chk("吴M6(234) 的纵线贯通到魏方「图4线」魏A4/B4/C4/D4/E4",
    {"156", "146", "136", "126", "116"} <= set(_chain), f"实际 {sorted(set(_chain))}")
chk("吴M6 的贯通线顺序正确（…→吴K6→魏A4→…→魏E4）",
    any(list(path)[-5:] == ["156", "146", "136", "126", "116"] for path in _wu_m6),
    f"实际 {_wu_m6}")

# 举一反三：吴方行 M 全列的对面归属
_expect = {"231": ("魏", 1), "232": ("魏", 2), "233": ("魏", 3), "234": ("魏", 4),
           "236": ("蜀", 6), "237": ("蜀", 7), "238": ("蜀", 8), "239": ("蜀", 9)}
for _p, (_who, _num) in _expect.items():
    _far = {q for path in R.RAYS[_p] for q in path if int(q[0]) != 2}
    _want_army = 1 if _who == "魏" else 3
    chk(f"{_p}({R.RAYS[_p] and G.parse(_p)}) 打到 {_who}底线图{_num}",
        any(int(q[0]) == _want_army and int(q[1]) == 1 and 10 - int(q[2]) == _num
            for q in _far),
        f"跨方点 {sorted(_far)}")
# 235（吴 M5）= 贯通纵线中轴：同时接 魏列5 与 蜀列5
_far235 = {q for path in R.RAYS["235"] for q in path if int(q[0]) != 2}
chk("吴M5(235) 是中轴 → 同时打到魏底线图5(115) 与 蜀底线图5(315)",
    {"115", "315"} <= _far235, f"跨方点 {sorted(_far235)}")

# 每条贯通纵线都必须完整存在（不漏、不重）
_missing = 0
for _a, _c, _b, _lane in R._front_lanes():
    for _i, _p in enumerate(_lane):
        _fwd = tuple(_lane[_i + 1:])
        if _fwd and not any(tuple(_x) == _fwd for _x in R.RAYS[_p]):
            _missing += 1
chk("全部贯通纵线齐全（缺失 0 条）", _missing == 0, f"缺失 {_missing} 条")


# ============================================================ §12 帅见面（line_of_sight）口径
print("\n== 12. 帅见面判定必须走「战线直通」后的 RAYS ==")
# 规则图《一、9. 帅不见面》明列的六条线路【E5-A5-F5-J5】…【O6-K6-A4-E4】
#   全部是**跨方贯通线**；旧实现走 B.rays（未接战线直通）→ 六条一条都命中不了，
#   「帅不见面」规则形同虚设。2026-09-24 夜改为走 RAYS。
_EMPTY_S = {"board": {}}
_LOS = [("E5-J5", "115", "315"), ("O5-E5", "215", "115"), ("J5-O5", "315", "215"),
        ("E6-J4", "114", "316"), ("J6-O4", "314", "216"), ("O6-E4", "214", "116")]
_los_bad = [n for n, x, y in _LOS if not R.line_of_sight(_EMPTY_S, x, y)]
chk("规则图第 9 条六条线路全部判「通」", not _los_bad, f"不可通 {_los_bad}")
_blocked = R.line_of_sight({"board": {"135": pc(R.PAWN, 2)}}, "115", "315")
chk("中间有子则阻断（115→315 在 135 放子后不可通）", not _blocked,
    f"line_of_sight 返回 {_blocked}（期望 False）")
_g0 = GA.new_game()
chk("开局三帅不相见（各自列5 上有自家兵阻隔）",
    not R.generals_facing(_g0), f"相见 {R.generals_facing(_g0)}")


# ============================================================ 汇总
print("\n" + "=" * 52)
print(f"DXF 引擎自检结果: {OK} 通过 / {FAIL} 失败")
print("=" * 52)
sys.exit(1 if FAIL else 0)
