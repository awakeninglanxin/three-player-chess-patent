# -*- coding: utf-8 -*-
"""验证「**马可以过河**」+「**过河落点方由落点列决定**」。

【老师口径 · 两轮】
  ① 2026-09-24 深夜：「魏国的马不会过河」
     传统象棋里**马是可以过河的**（只有象/士不过河）。规则图「棋子运行逻辑」第 1 条
     最后半句「马在其它地方行进方式与传统象棋行进方式（起、终点相对坐标）完全相符」
     —— 传统象棋马的日字步**不分领地**，照此解释。
  ② 2026-09-25：「马不能从 L5 到 F4 …要遵守游戏规则」
     过河落点落在**哪一方**，由**落点所在列 c2** 决定，**不是起点列 c0**。
  ③ 2026-09-25（第二轮）：「马应该不能从 A6 到 K6，你为何会允许」
     ★ 过河马步**不得跨过本方中线 col5** —— 起点列 c0 与落点列 c2 必须在本方
     中线的**同一侧**（恰在中线上算同侧）。依据：过河接线**一对一**
     （底边数字和恒为 10，一条纵线只通向一个对面）；横移跨中线 =
     「先换接线再过河」，一步用了两条接线，规则无据。
     加上这条后：**单向步 6 → 0**（完全可逆）、**120° 对称 0 处破坏**，
     且 ② 的结论（L5→F4 禁）原样保留。

【过河落点怎么算】（复用老师已确认的「过河接线：数字和恒为 10」）
  把 (行,列) 读成世界坐标 (t, u)：
    t = 距本方底线的格数（本方 1..5；过河后 6..10 = 对面 row5..row1）
    u = 列（本方列 c 与对面列 10−c 是世界上的同一条线）
  ⇒ **落点方 = `_front_partner(本方, c2)`**（c2 = c0 + Δc，即「本条纵线通向谁」）
  ⇒ 对面行 = 11 − r2，对面列 = 10 − c2
  ⇒ 马腿若也落在河外，同样按这一方映射（对面 row5）。

  ⚠️ c2 恰在本方中线（=5）时，c2 自己分不出左右，退回用**起点列 c0**
     （横向位移的方向由 c0→c2 决定）。c2 = c0 不可能（日字步 Δc ≠ 0）。

【为什么必须用 c2（老师原话的口径落地）】
  `_front_lane(a, c)` 的对面方 = `_front_partner(a, c)`
    FRONT_NEXT = {1:3, 2:1, 3:2}（纯规则表，无几何）
    · 本方列 1..4 → FRONT_NEXT[方]；列 6..9 → 反向那一个；列 5 = 三角区顶点（None）
  **车 / 炮沿列直走**（c2 ≡ c0），用起点列还是落点列都一样；
  **马步会改列**（Δc = ±1/±2），用起点列就把「落点所在那条纵线」张冠李戴：
    · c0 = 5（本方中线）时 `_cross_sides` 把**两个对面都接上** ⇒ 凭空多给一半落点
      （吴 L5(245) 走 (2,−1) 本应只到魏 A4(156)，却把蜀 F4(356) 也生成出来）；
    · 反向落点查不到 ⇒ 全盘 **30 条单向马步**（传统象棋马步必然可逆，同方内部 0 条）。

标签口径：图中数字 d = 10 − 引擎列；字母 魏 A-E / 吴 K-LMNO / 蜀 F-J（行 row5→row1）。
"""
import sys

sys.path.insert(0, "server")
from engine import rules_dxf as R      # noqa: E402
from engine import geometry_dxf as D   # noqa: E402

B = D.BOARD
ok = bad = 0


def chk(cond, msg, extra=""):
    global ok, bad
    if cond:
        ok += 1
        print(f"  [OK]   {msg} {extra}")
    else:
        bad += 1
        print(f"  [FAIL] {msg} {extra}")


def sect(n, title):
    print()
    print("=" * 78)
    print(f"第 {n} 节 · {title}")
    print("=" * 78)


def cross_dests(p, exclude_rebound=False):
    """p 的跨方落点；exclude_rebound=True 时剔掉三角区回跳（只留「过河」）"""
    pa = int(D.parse(p)[0])
    out = {d for _l, d in R.HORSE_T[p] if int(d[0]) != pa}
    if exclude_rebound:
        out -= {d for _l, d in R.REBOUND.get(p, ()) if int(d[0]) != pa}
    return out


def dest_sides(pa, c0, c2):
    """本次修正后的「落点方」判据（供逐条重算用）

    ① 落点方由**落点列 c2** 决定（c2 = 本方中线时退回 c0）；
    ② ★ 若 c2 与 c0 **分居本方中线 col5 两侧**（跨中线）→ 该步**不成立**（返回空）。
       依据：过河接线一对一（数字和恒为 10），一条纵线只通向一个对面；
       横移跨中线 = 先换接线再过河，同时用了两条接线，规则无据。
    """
    if (c0 - R.COL_MID) * (c2 - R.COL_MID) < 0:
        return ()
    return R._cross_sides(pa, c2 if c2 != R.COL_MID else c0)


# ============================================================================
sect(1, "① 被砍的 162 条「朝中心」候选，现在都有落点（或明确落在盘外）")

all_pts = [p for p in B.ids]
cross_expect, cross_off, cross_got, cross_banned = [], [], [], []
for p in sorted(all_pts):
    pa, r0, c0 = D.parse(p)
    t = set(R.HORSE_T[p])
    for mv in R.HORSE_MOVES:
        r2, c2 = r0 + mv[0], c0 + mv[1]
        if r2 <= R.ROWS_TERR:
            continue                                  # 不是「朝中心越界」
        if not (1 <= c2 <= R.COLS_TERR):
            cross_off.append((p, mv, r2, c2))         # 同时越出六边形左右外侧
            continue
        if (c0 - R.COL_MID) * (c2 - R.COL_MID) < 0:
            cross_banned.append((p, mv, c2))          # ★ 跨本方中线 → 该步不成立
            continue
        cross_expect.append((p, mv, r2, c2))
        for pb in dest_sides(pa, c0, c2):
            d = D.pid(pb, 11 - r2, 10 - c2)
            if d in B.ids and any(dd == d for _l, dd in t):
                cross_got.append((p, mv, d))

chk(len(cross_expect) + len(cross_off) + len(cross_banned) == 162,
    "朝中心越界的候选合计 = 162 条（54 个起点 × 3）",
    f"实测 {len(cross_expect)} 合法 + {len(cross_off)} 越外侧"
    f" + {len(cross_banned)} 跨中线被禁")
chk(len(cross_expect) == 132,
    "其中列号合法、且未跨本方中线的候选 = 132 条",
    f"实测 {len(cross_expect)}")
chk(len(cross_got) == 132,
    "…132 条映射出 **132** 个过河落点 —— **一候一对**"
    "（旧口径的「+18 三岔双份」正是多给的那批，已剔除）",
    f"落点 {len(cross_got)} / 候选 {len(cross_expect)}")
chk(len(cross_off) == 24,
    "列号同时越出六边形外侧的 24 条被正确剔除"
    "（c0=1/2/8/9 各 1~2 条，如 151 的 Δc=−2）",
    f"实测 {len(cross_off)}")
chk(len(cross_banned) == 6,
    "★ 跨本方中线的 6 条被剔除（c0=4 走 Δ=(1,+2) / c0=6 走 Δ=(1,−2)，每方各 1 个起点 × 2 mv）"
    "—— 老师报的 A6(154)→K6(254) 就在这里",
    f"实测 {len(cross_banned)} 条 {sorted(x[0] for x in cross_banned)}")

n_cross_edges = sum(
    1 for p in B.ids for _l, d in R.HORSE_T[p] if d[0] != p[0])
chk(n_cross_edges == 144,
    "全盘跨方马步 = 144 条（= **132** 条过河 + **12** 条三角区回跳 = 6 对 × 双向）",
    f"共 {n_cross_edges} 条")


# ============================================================================
sect(2, "② 落点公式逐条重算：对面(行 11−r2, 列 10−c2)，方 = _front_partner(本方, c2)")

mis = []
for p in sorted(B.ids):
    pa, r0, c0 = D.parse(p)
    for mv in R.HORSE_MOVES:
        r2, c2 = r0 + mv[0], c0 + mv[1]
        if r2 <= R.ROWS_TERR or not (1 <= c2 <= R.COLS_TERR):
            continue
        got = {d for _l, d in R.HORSE_T[p] if d[0] != pa}
        for pb in dest_sides(pa, c0, c2):
            d = D.pid(pb, 11 - r2, 10 - c2)
            if d in B.ids and d not in got:
                mis.append((p, mv, d))
chk(not mis, "公式与 HORSE_T 完全一致，无遗漏", f"不符 {len(mis)} 条 {mis[:3]}")

got156 = cross_dests("156", exclude_rebound=True)
chk(got156 == {"252", "245", "243"},
    "156（魏 A4）过河三步 = 252(吴 K8) / 245(吴 L5) / 243(吴 L7)"
    "（另有三角区回跳 →355，不计入「过河」）",
    f"实测 {sorted(got156)}")

# ★ 老师 2026-09-25 报的那两手
chk("356" not in cross_dests("245"),
    "★ L5(245) 过河落点 = A4(156 魏) / F6(354 蜀) —— **不含 F4(356)**（老师第一轮裁决）",
    f"实测 {sorted(cross_dests('245'))}")
chk("254" not in cross_dests("154"),
    "★ A6(154) 过河落点 = G5(345 蜀) / G3(347 蜀) / F2(358 蜀) —— **不含 K6(254)**"
    "（老师第二轮裁决；因 Δ=(1,+2) 的落点列 c2=6 与起点列 c0=4 分居中线两侧 → 跨中线被禁）",
    f"实测 {sorted(cross_dests('154'))}")


# ============================================================================
sect(3, "③ 落点方由**落点列 c2** 决定 + **不得跨本方中线**（两次修正的核心）")

# (a) c0=5（本方中线）不再「两个对面都接」
d245 = cross_dests("245", exclude_rebound=True)
chk(d245 == {"156", "354"},
    "L5(245)（在中线上）只接 2 条过河：魏(156) + 蜀(354)"
    "—— 旧口径在这里「两个对面都接」，凭空生成 356 / 154",
    f"{sorted(d245)}")

# (b) 反例①：c2=4 单看确实指向蜀(356)，但 156 的起点列 c0=6 在中线另一侧
#     → 跨中线，**整条步不成立**（正是老师报的 A4→F4）
p156_c2_4 = {d for _l, d in R.HORSE_T["156"] if d[0] != "1" and d in {"356", "256"}}
chk(not p156_c2_4,
    "★ 156 走 Δ=(1,−2) 已整条剔除（c2=4 与 c0=6 分居中线两侧）："
    "落点既不是蜀 F4(356)、也不是旧口径误判的吴 K4(256) —— **两条都不接**",
    f"{sorted(p156_c2_4)}")
chk(R._front_partner(1, 4) == 3,
    "…规则表本身没错：c2=4 → _front_partner(魏,4) = 蜀（被禁的是「跨中线还照用」这个前提）")

# (c) 逐条穷举：任何跨方落点，其方都必须 = _front_partner(起点方, 落点列)
wrong = []
for p in sorted(B.ids):
    pa, r0, c0 = D.parse(p)
    for _l, d in R.HORSE_T[p]:
        pb, r2, c2 = D.parse(d)
        if pb == pa:
            continue
        if any(dd == d for _l2, dd in R.REBOUND.get(p, ())):
            continue                       # 三角区回跳是独立条款，不按此判
        exp = R._front_partner(pa, 10 - c2 if (10 - c2) != R.COL_MID else c0)
        if exp is None:
            continue
        if exp != pb:
            wrong.append((p, d, exp, pb))
chk(not wrong,
    "全盘穷举：每条过河马步的落点方 = _front_partner(起点方, 落点列)",
    f"不符 {len(wrong)} 条 {wrong[:3]}")

# (d) 邻接表佐证：对面 row5 的「数字和 = 10」
chk("359" in B.adj["151"],
    "邻接表佐证：魏 row5 列1(151) 的跨方邻点是蜀 row5 列9(359)  → 10−1=9 ✅")
chk("251" in B.adj["159"],
    "邻接表佐证：魏 row5 列9(159) 的跨方邻点是吴 row5 列1(251)  → 10−9=1 ✅")


# ============================================================================
sect(4, "④ 过河落点只落在「本条纵线通向的那一方」（不再无脑双接）")

t155 = cross_dests("155", exclude_rebound=True)
chk(t155 == {"244", "253", "346", "357"},
    "155（魏 row5 列5）过河 4 步：列≤4 侧→蜀(346/357)，列≥6 侧→吴(244/253)"
    "—— 旧口径 8 步 = 4 mv × 2 个对面",
    f"{sorted(t155)}")

t154 = cross_dests("154", exclude_rebound=True)
chk(t154 == {"345", "347", "358"},
    "154（魏列4）过河 3 步：Δc=−2 → 蜀(358)，Δc=−1 → 蜀(347)，Δc=+1(落中线)→蜀(345)；"
    "Δc=+2 的 254(吴 K6) 因跨中线被剔",
    f"{sorted(t154)}")

t156 = cross_dests("156", exclude_rebound=True)
chk(t156 == {"252", "245", "243"},
    "156（魏列6）过河 3 步（镜像）：Δc=+2 → 吴(252)，Δc=+1 → 吴(243)，Δc=−1(落中线)→吴(245)；"
    "Δc=−2 的 356(蜀 F4) 因跨中线被剔",
    f"{sorted(t156)}")

for src, exp in (("154", "255"), ("156", "355")):
    chk(any(d == exp for _l, d in R.REBOUND.get(src, ())),
        f"…且 {src} 的三角区回跳（→{exp}）仍原样保留")


# ============================================================================
sect(5, "⑤ 三方对称：跨河马步数完全相等（旋转 120° 同构）")

cnt = {}
for a in D.ARMIES:
    cnt[a] = sum(1 for p in B.ids if D.parse(p)[0] == a
                 for _l, d in R.HORSE_T[p] if int(d[0]) != a)
chk(len(set(cnt.values())) == 1,
    "魏 / 吴 / 蜀 跨方马步数相等", f"{cnt}")
per = cnt[1]
chk(per == 48, "…每方 48 条 = 44 条过河 + 4 条三角区回跳（6 对双向 ÷ 3 方）",
    f"每方 {per} 条")
chk(per - 4 == 132 // 3,
    "过河部分每方 44 条（全盘 132 条 ÷ 3 方，三方完全对称）",
    f"每方过河 {per - 4} 条")


# ============================================================================
sect(6, "⑥ 三角区回跳 = 原文 6 对「**可来回跳**」→ 双向 12 条（本次补全）")

PAIRS = [
    ("156", "355", "155"),      # 原文：A5 处没有棋子时，A4 到 F5 可来回跳
    ("154", "255", "155"),      # 原文：…A6 到 K5 可来回跳
    ("356", "255", "355"),      # 原文：F5 处没有棋子时，F4 到 K5 可来回跳
    ("354", "155", "355"),      # 原文：…F6 到 A5 可来回跳
    ("256", "155", "255"),      # 原文：K5 处没有棋子时，K4 到 A5 可来回跳
    ("254", "355", "255"),      # 原文：…K6 到 F5 可来回跳
]
oneway = []
for x, y, leg in PAIRS:
    fx = [(l, d) for l, d in R.HORSE_T[x] if d == y]
    fy = [(l, d) for l, d in R.HORSE_T[y] if d == x]
    if not (fx and fy and fx[0][0] == fy[0][0] == leg):
        oneway.append((x, y, fx, fy))
chk(not oneway,
    "6 对全部**双向**，且两个方向共用同一条腿（原文的「X5」）",
    f"不成对 {oneway}")

t355 = {d for _l, d in R.HORSE_T["355"]}
chk("156" in t355 and "254" in t355,
    "F5(355) 能回跳 A4(156) 与 K6(254) —— 旧实现只做了单向，这条曾缺失",
    f"{sorted(t355)}")


# ============================================================================
sect(7, "⑦ 马腿跨河映射：占住对面 row5 的点能蹩掉这一步")

empty = {}
mv156 = R._horse(empty, "156", 1, 1, set())
chk("245" in mv156 and "243" in mv156,
    "空盘：156 可跳 245 / 243（吴 row4 的两个落点）",
    f"含 {sorted(x for x in mv156 if x[0] != '1')}")

legs245 = R.HORSE_LEG["156"]["245"]
legs243 = R.HORSE_LEG["156"]["243"]
chk(legs245 == legs243 == ("254",),
    "245 / 243 的马腿同为 254（对面 row5 的点）—— 与传统象棋「一条腿管两个落点」同构",
    f"245→{legs245}  243→{legs243}")

blocked = {"254": {"kind": "pawn", "army": 2}}
mv2 = R._horse(blocked, "156", 1, 1, set())
chk("245" not in mv2 and "243" not in mv2,
    "腿点 254 有子 → 245 与 243 **一起**被蹩掉",
    f"含 {sorted(x for x in mv2 if x[0] != '1')}")
chk("252" in mv2,
    "…但另一侧的 252（腿在本国 157）完全不受影响")


# ============================================================================
sect(8, "⑧ 边界：马仍然走不到棋盘外")

outside = [(p, d) for p in B.ids for _l, d in R.HORSE_T[p] if d not in B.ids]
chk(not outside, "HORSE_T 全部落点都在盘上（135 点内）", f"越界 {len(outside)} 条")

legs_out = [(p, d, l) for p in B.ids for l, d in R.HORSE_T[p]
            if l not in B.ids and D.parse(l)[1] <= R.ROWS_TERR]
chk(not legs_out,
    "本国腿点不会凭空出现在盘外（列/行越界的腿 = 天然通腿，不参与蹩腿）",
    f"{len(legs_out)} 条")

t111 = {d for _l, d in R.HORSE_T["111"]}
chk(t111 == {"123", "132"}, "111（底线角上的马）仍只有 2 步，无跨河", f"{sorted(t111)}")


# ============================================================================
sect(9, "⑨ 跨方马步 **100% 可逆** + **120° 旋转对称 0 处破坏**（老师第二轮修正的判据）")

asym = []
for u in R.HORSE_T:
    du = {d for _l, d in R.HORSE_T[u]}
    for v in du:
        if u not in {d for _l, d in R.HORSE_T.get(v, ())}:
            asym.append((u, v))
chk(not asym,
    "★ 全盘**单向马步 = 0 条** —— 每一步都能原路走回（传统象棋马步的硬性质）",
    f"实测 {len(asym)} 条 {asym[:4]}")

# 120° 旋转对称：σ 保 (行,列)、只轮换方号 魏→吴→蜀→魏
sig = {1: 2, 2: 3, 3: 1}


def rot(p):
    return D.pid(sig[int(p[0])], int(p[1]), int(p[2]))


adj = {(p, d) for p in R.HORSE_T for _l, d in R.HORSE_T[p]}
broken = [(p, d) for (p, d) in adj
          if (rot(p), rot(d)) not in adj or (rot(rot(p)), rot(rot(d))) not in adj]
chk(not broken,
    "★ 120° 旋转对称：全盘每条马步旋转 ±120° 后仍在表里（0 处破坏）",
    f"破坏 {len(broken)} 条 {broken[:3]}")

# 老师两轮报的那两手，互为「旋转镜像」，现在**两条都被剔**：
killed = [("154", "254"), ("254", "354"), ("354", "154"),
          ("156", "356"), ("256", "156"), ("356", "256")]
still = [ab for ab in killed if ab[1] in {d for _l, d in R.HORSE_T[ab[0]]}]
chk(not still,
    "★ 两组 3-环共 6 条边**整组归零**：154→254→354→154 与 156→356→256→156"
    "（含老师报的 154→254 与 156→356）",
    f"仍存在 {still}")
chk(all((rot(a), rot(b)) in set(killed) for a, b in killed),
    "…这 6 条在 120° 旋转下构成**封闭轨道**（旋转像仍在这 6 条内）"
    "—— 所以「一组有、一组无」不可能发生")


print()
print("=" * 78)
print(f"合计 {ok} 通过 / {bad} 失败")
print("=" * 78)
sys.exit(1 if bad else 0)
