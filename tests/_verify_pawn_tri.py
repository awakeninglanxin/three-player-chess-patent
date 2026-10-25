# -*- coding: utf-8 -*-
"""兵「中心三角区自由回跳」专项验证（2026-10-01 · 老师新规）

老师原话：
  「让游戏更有趣，修改规则 当兵到达中心三角区格点后可以自由往任一方向走」
  「对，允许各方兵在中心三角区回跳」

【规则】中心三角区 = 三方各自的 row5 中点，共 **3 个格点**
        魏 A5(155) / 吴 K5(255) / 蜀 F5(355)；
        三点两两之间的跨方直连 = `B.tri_edges`（"三角区的三条边"）。

  · 兵**站在**三角区任一格点上 → 可走到**另两个**格点（双向）；
  · **不分归属方** —— 任何方的兵都行（这是"各方兵…回跳"的字面含义）；
  · 属于「回跳」，**不算过界** ⇒ 不受「兵只能过一次界」约束，可反复穿梭
    （含"回到自己营点"）；
  · 只在**三角区格点上**生效：一旦离开，立即恢复普通兵（本门禁 §④ 钉住）；
  · 其余走法**一字不改**（§③ 用平行实现对拍逐点证明"只增不减"）。

【为什么这条必须两处同构】
  `rules_dxf._pawn`（解析层）与 `nb_core._g_pawn`（JIT 内核）是**各写一遍**的，
  加上 `_pawn_homes()`（喂 `attacked()` 将军判定的反向表）共 **三处**。
  漏任何一处都会出现「走得了但判不出将军」或「搜索下出的棋人类走不了」。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

from engine import game_dxf as GA       # noqa: E402
from engine import rules_dxf as R       # noqa: E402
from engine import geometry_dxf as G    # noqa: E402
from engine import patent as P          # noqa: E402

CN = {1: "魏", 2: "吴", 3: "蜀"}
TRI = sorted(R.TRI_PTS)                      # ['155', '255', '355']
ARMIES = (1, 2, 3)
PASS = FAIL = 0


def chk(desc, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [OK]   %s" % desc)
    else:
        FAIL += 1
        print("  [FAIL] %s   %s" % (desc, extra))


def lab(p):
    a, r, c = G.parse(p)
    return "%s%s%d" % ({1: "E", 2: "D", 3: "C"}.get(r, "?") if a == 1 else
                       {1: "J", 2: "I", 3: "H"}.get(r, "?") if a == 3 else
                       {1: "O", 2: "N", 3: "M"}.get(r, "?"), CN[a], 10 - c)


def mk(board, turn=1):
    s = {"board": board, "turn": turn, "eliminated": [], "annexed": {},
         "history": [], "passed": [], "winner": None, "ply": 0, "first": 1}
    s.update(P.new_fields())
    return s


def pawn_board(pos, army=1, home=1):
    """空盘 + 一枚兵（其余全空 ⇒ `_can_land` 恒真，便于纯规则对拍）"""
    return {pos: {"kind": "pawn", "army": army, "home": home}}


def new_moves(board, pos, army):
    """改造后的走法（升序）"""
    return sorted(t for f, t in R.side_moves(mk(board), army) if f == pos)


def old_moves(board, pos, army, home):
    """**平行实现**：改造前的兵规则（逐字照抄旧 `_pawn`），用于证明"只增不减"。

    ⚠️ 本函数是**测试专用的历史快照**，不得被生产代码引用。
       将来若再改兵的规则，请同步更新这里的意图说明（而不是删掉它）。
    """
    pa, r0, c0 = R.RC[pos]
    in_own = (pa == home)
    crossed = not in_own
    out = []
    for q, qa, qr, qc in R.PAWN_T.get(pos, ()):
        if not R._can_land(board, army, R._EMPTY, q):
            continue
        if qa == pa:
            if in_own:
                if qr < r0:
                    continue
                if qr > r0 and qc != c0:
                    continue
                if qr == r0 and not crossed:
                    continue
                out.append(q)
            else:
                if qr > r0:
                    continue
                if qr < r0 and qc != c0:
                    continue
                out.append(q)
        else:
            if not in_own:
                continue
            if r0 == 5 and qr == 5 and qc == 10 - c0:
                out.append(q)
    return out


print("=" * 74)
print("① 三角区的几何事实")
print("=" * 74)
print("     TRI_PTS = %s" % TRI)
chk("三角区 = 恰好 3 个格点", len(TRI) == 3, "实际 %s" % TRI)
chk("三点 = 三方各自的 row5 中点（155/255/355）", set(TRI) == {"155", "255", "355"})
chk("三点的 (行,列) 恒为 (5,5) —— 全盘只有这 3 个点满足",
    all(G.parse(p)[1:] == (5, 5) for p in TRI)
    and sum(1 for p in R.B.ids if G.parse(p)[1:] == (5, 5)) == 3,
    "实际 %d 个" % sum(1 for p in R.B.ids if G.parse(p)[1:] == (5, 5)))
chk("三条边 = set(tri_edges)，且就是三点两两组合（3 条）",
    len(R.B.tri_edges) == 3
    and {frozenset(e) for e in R.B.tri_edges}
    == {frozenset((a, b)) for i, a in enumerate(TRI) for b in TRI[i + 1:]},
    "实际 %s" % R.B.tri_edges)

print()
print("=" * 74)
print("② 覆盖：任意方、任意归属的兵，站在任一三角区格点，都能到另两点")
print("=" * 74)
bad = []
for pos in TRI:
    for army in ARMIES:
        for home in ARMIES:
            got = set(new_moves(pawn_board(pos, army, home), pos, army))
            want = set(TRI) - {pos}
            if not want <= got:
                bad.append((pos, CN[army], CN[home], sorted(want - got)))
print("     样例：魏兵(魏)在 155 → %s" % new_moves(pawn_board("155"), "155", 1))
print("           蜀兵(蜀)在 255 → %s" % new_moves(pawn_board("255", 3, 3), "255", 3))
print("           吴兵(吴)在 355 → %s" % new_moves(pawn_board("355", 2, 2), "355", 2))
chk("3 格点 × 3 兵方 × 3 归属 = 27 种组合，三角区落点全部齐全",
    not bad, "缺失 %s" % bad[:6])

print()
print("=" * 74)
print("③ 平行实现对拍：新走法 == 旧走法 ∪ 三角区边（逐点证明「只增不减」）")
print("=" * 74)
added = removed = changed = 0
mismatch = []
detail = []
for p in R.B.ids:
    for army in ARMIES:
        for home in ARMIES:
            b = pawn_board(p, army, home)
            got = set(new_moves(b, p, army))
            old = set(old_moves(b, p, army, home))
            extra = (set(TRI) - {p}) if p in R.TRI_PTS else set()
            # 三角区落点必须本来就在 PAWN_T 里（否则新规则也补不上）
            extra_ok = extra <= {n[0] for n in R.PAWN_T.get(p, ())}
            want = old | (extra if extra_ok else set())
            if got != want:
                changed += 1
                if len(mismatch) < 4:
                    mismatch.append((p, CN[army], CN[home],
                                     sorted(got - want), sorted(want - got)))
            added += len(got - old)
            removed += len(old - got)
            if p in R.TRI_PTS and extra and len(extra) == 2:
                detail.append((p, CN[army], CN[home], len(got - old)))
chk("全盘 135 点 × 3 兵方 × 3 归属 = 1215 组，走法集合与「旧 ∪ 三角区边」完全一致",
    changed == 0, "不一致 %d 组 %s" % (changed, mismatch))
chk("**没有减少任何一步**（旧走法全部保留）", removed == 0, "被删 %d 步" % removed)
# 每组的「新增步数」∈ {0, 2}：
#   · 兵归属 == 该点所在方（兵站在自己营点）⇒ 三角区边本就在"过河"旧走法里 ⇒ +0
#   · 否则（兵站在他国营点）⇒ 旧走法用 `not in_own` 拦掉了跨方步 ⇒ +2
# 3 个格点 × 3 个兵方 = 9 组合；每组的 3 个归属里恰有 1 个 +0、2 个 +2
#   ⇒ 合计新增 = 9 × (2×2) = 36
chk("每组新增步数 ∈ {0, 2}，且合计 == 36（= 9 组合 × 2 个非本营归属 × 2 条边）",
    all(d[3] in (0, 2) for d in detail) and added == 36,
    "样例 %s  合计新增 %d" % (detail[:4], added))
print("     新增步数合计 = %d（只在「兵站在三角区格点」时出现）" % added)

print()
print("=" * 74)
print("④ 只在三角区格点上生效：非三角区点走法一字未变")
print("=" * 74)
untouched = 0
diffs = []
for p in R.B.ids:
    if p in R.TRI_PTS:
        continue
    for army in ARMIES:
        for home in ARMIES:
            b = pawn_board(p, army, home)
            if set(new_moves(b, p, army)) != set(old_moves(b, p, army, home)):
                diffs.append((p, CN[army], CN[home]))
            untouched += 1
chk("非三角区点（132 点 × 9 组 = %d 组）走法完全未变" % untouched,
    not diffs, "变了 %s" % diffs[:6])

print()
print("=" * 74)
print("⑤ 将军判定同步：SIMPLE_ATTACK / attacked() 必须认得这条新通道")
print("=" * 74)
miss = []
for q in TRI:
    entries = R.SIMPLE_ATTACK.get(q, ())
    for p in set(TRI) - {q}:
        homes = {h for (pp, h, k) in entries if pp == p and k == R.PAWN}
        if homes != set(ARMIES):
            miss.append((p, q, sorted(homes)))
chk("三角区另一端点的兵，各归属方（3 个 home）都登记进了 SIMPLE_ATTACK",
    not miss, "缺失 %s" % miss)

hit = []
for pos in TRI:
    for army in ARMIES:
        for home in ARMIES:
            b = pawn_board(pos, army, home)
            for q in set(TRI) - {pos}:
                if not R.attacked(mk(b), q, [army]):
                    hit.append((pos, CN[army], CN[home], q))
chk("attacked() 判得出「兵在三角区可攻击另一端」（27 组合 × 2 落点）",
    not hit, "判不出 %s" % hit[:6])

print()
print("=" * 74)
print("⑥ JIT 内核逐点对拍（改造最容易漏的一处）")
print("=" * 74)
try:
    from engine import nb_core as NB    # noqa: E402
    jbad = []
    for p in R.B.ids:
        for army in ARMIES:
            for home in ARMIES:
                b = pawn_board(p, army, home)
                a = sorted(NB.gen_point_py(b, p))
                c = sorted(t for f, t in NB.gen_side_py(b, army) if f == p)
                d = new_moves(b, p, army)
                if not (a == d and c == d):
                    jbad.append((p, CN[army], CN[home], a, d))
    chk("JIT `gen_point` / `gen_side` 与解析层逐点一致（1215 组）",
        not jbad, "不一致 %s" % jbad[:4])
except Exception as e:      # pragma: no cover
    chk("JIT 对拍可运行", False, "异常 %s" % e)

print()
print("=" * 74)
print("⑦ 「回跳」不算过界：可在三点之间反复穿梭")
print("=" * 74)
cur = "155"
b = pawn_board("155", 1, 1)
seq = ["255", "355", "155", "255"]
ok_seq = []
for nxt in seq:
    legal = new_moves(b, cur, 1)
    ok_seq.append((cur, nxt, nxt in legal))
    b = {nxt: {"kind": "pawn", "army": 1, "home": 1}}
    cur = nxt
print("     魏兵行程：%s" % " → ".join(["155"] + seq))
chk("魏兵可 155→255→355→155→255 连走 4 步（含退回自己营点 355→155）",
    all(x[2] for x in ok_seq), "失败 %s" % [x for x in ok_seq if not x[2]])

# 对照组：离开三角区后立即失去该能力
b2 = pawn_board("245", 1, 1)          # 魏兵深入吴境（row4，已过河）
got2 = new_moves(b2, "245", 1)
tri_from_245 = [q for q in got2 if q in R.TRI_PTS]
chk("（对照）兵在非三角区点 245 时，三角区通道无效（不能隔空回跳）",
    not tri_from_245, "实际 %s" % tri_from_245)

print()
print("=" * 74)
print("⑧ 三方 120° 旋转对称（保 (行,列)、只轮换方号）")
print("=" * 74)


def rot(p):
    a, r, c = G.parse(p)
    return G.pid(a % 3 + 1, r, c)


asym = []
for p in R.B.ids:
    for army in ARMIES:
        for home in ARMIES:
            b = pawn_board(p, army, home)
            lo = sorted(rot(t) for t in new_moves(b, p, army))
            b2 = pawn_board(rot(p), army % 3 + 1, home % 3 + 1)
            hi = new_moves(b2, rot(p), army % 3 + 1)
            if lo != hi:
                asym.append((p, CN[army], CN[home], lo, hi))
chk("全盘兵走法在 120° 旋转下不变（1215 组）", not asym, "破坏 %s" % asym[:4])

print()
print("=" * 74)
print("⑨ 与既有「过河」规则共存（只增不减的旁证）")
print("=" * 74)
A7 = new_moves(pawn_board("153", 1, 1), "153", 1)
chk("魏兵在 A7(153) 仍唯一正解 = 过河到 F3(357)",
    A7 == ["357"], "实际 %s" % A7)
cross_n = sum(1 for a in ARMIES for c in range(1, 10)
              if [q for q in new_moves(pawn_board("%d5%d" % (a, c), a, a),
                                       "%d5%d" % (a, c), a) if q[0] != str(a)])
chk("三方在 row5 上仍有 27 条跨方过河通道（9 点 × 3 方）",
    cross_n == 27, "实际 %d" % cross_n)

print()
print("=" * 74)
print("合计 %d 通过 / %d 失败" % (PASS, FAIL))
print("=" * 74)
sys.exit(1 if FAIL else 0)
