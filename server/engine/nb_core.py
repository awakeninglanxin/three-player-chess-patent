# -*- coding: utf-8 -*-
"""三人象棋 · numba JIT 内核（方案 ①）—— 热路径机器码化

【为什么要它 —— 实测数据】
    cProfile 一次 6 plies 搜索：`SearchBot._leaf` **独占 74%**，
    着法生成（`moves_of` → `_rook`/`_horse`/…）再占约 20%。
    两者加起来 >94%，而它们做的事情极其机械：
        · 着法生成 = 查预计算表 + 判「这点有没有子」
        · 叶评估   = 三重循环查距离表 + 少数几次攻击判定
    全是 Python 解释器开销在拖后腿（每次 `board.get(q)` 一次 dict 查找、
    每个 `pc["army"]` 一次哈希）。CPython 下 nps 卡在 3~4 万。

【本模块做什么】
    把「棋盘」从 `dict[str, dict]` 换成**定长 numpy 数组**，把上面两块热路径
    用 numba 编译成机器码。棋盘表示：

        CODE[135]  int32 —— 每个点一个整数编码（0 = 空）
            位域： kind(5..7) | army(3..4) | home(1..2) | deputy(0)
            kind: 0=空 1=车 2=马 3=象 4=士 5=帅 6=炮 7=兵
            army/home: 1=魏 2=吴 3=蜀
        整盘状态 = 540 字节，正好躺在 L1 缓存里；
        make/unmake 变成两次 int 赋值（旧版是两次 dict pop + 一次插入）。

    着法也压成一个 int32：`(from << 8) | to`（点位 < 256，移位即解）。

【铁律 · 对拍门禁（老师 2026-09-25 定的规矩）】
    **新内核必须与现有 Python 引擎随机局面对拍，逐点比对「着法集合完全一致」**。
    覆盖：马蹩腿、过河不跨中线、三角区回跳、兵过河、炮翻山、帅见面射杀、
    副帅、连吃上限…… 全绿才允许接入。
    对拍器：`tests/_verify_numba_parity.py`。

【本文件不做的事】
    · 不碰规则判据本身 —— 所有判据仍由 `rules_dxf` 的预计算表**原样搬过来**，
      本模块只换「怎么查」，不换「查什么」。
    · 不改任何游戏规则、不新增规则。
"""
import time                                  # objmode 块内要用（顶层 import）
import numpy as np

try:
    from . import geometry_dxf as D
    from . import rules_dxf as R
except ImportError:                          # 以 server/ 为工作目录时走这条
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from engine import geometry_dxf as D
    from engine import rules_dxf as R

N = len(D.BOARD.ids)                         # 135
SHIFT = 8                                    # 着法编码位移（点位 < 256）

# ---------------------------------------------------------------- 点位索引
POS = {p: i for i, p in enumerate(D.BOARD.ids)}      # '154' -> 0..134
IDX2POS = list(D.BOARD.ids)

# ---------------------------------------------------------------- 子种编码
K_ROOK, K_HORSE, K_ELEPHANT, K_ADVISOR, K_GENERAL, K_CANNON, K_PAWN = 1, 2, 3, 4, 5, 6, 7
KIND_ID = {R.ROOK: K_ROOK, R.HORSE: K_HORSE, R.ELEPHANT: K_ELEPHANT,
           R.ADVISOR: K_ADVISOR, R.GENERAL: K_GENERAL, R.CANNON: K_CANNON,
           R.PAWN: K_PAWN}
KIND_NAME = {v: k for k, v in KIND_ID.items()}

SH_KIND, SH_ARMY, SH_HOME = 5, 3, 1


def pack(kind_id, army, home, deputy):
    """把一枚子打成整数（与 njit 里的解码严格互逆）"""
    return (int(kind_id) << SH_KIND) | (int(army) << SH_ARMY) | \
           (int(home) << SH_HOME) | (1 if deputy else 0)


def unpack(code):
    """解码 → (kind_id, army, home, deputy)"""
    return (code >> SH_KIND, (code >> SH_ARMY) & 3,
            (code >> SH_HOME) & 3, code & 1)


def mv(frm, to):
    return (int(frm) << SHIFT) | int(to)


def mv_from(m):
    return m >> SHIFT


def mv_to(m):
    return m & 255


# ================================================================ 表构建
def _offsets(counts):
    off = np.zeros(len(counts) + 1, dtype=np.int32)
    for i, c in enumerate(counts):
        off[i + 1] = off[i] + c
    return off


def _build():
    T = {}

    # ---------- 点位属性：方 / 行 / 列 ----------
    T["rc_army"] = np.asarray([D.parse(p)[0] for p in IDX2POS], dtype=np.int32)
    T["rc_row"] = np.asarray([D.parse(p)[1] for p in IDX2POS], dtype=np.int32)
    T["rc_col"] = np.asarray([D.parse(p)[2] for p in IDX2POS], dtype=np.int32)

    # ---------- 射线（车 / 炮 / 帅射杀）----------
    # ⚠️ **营点分叉**：各方的 row5-5（营点 155/255/355）是纵向射线的分叉口 ——
    #    它的射线**分成两条支线**，分别接另两方的 row5-5，于是两条射线都以
    #    **同一个第一落点**开头：
    #        RAYS[145] = [['155','255','245',…], ['155','355','345',…]]
    #    ⇒ 车/炮沿列5 推进时，155 会被两条射线各生成一次，**必须去重**
    #      （Python 版靠 `seen` 集合；JIT 版靠 STAMP 时间戳，见 `_g_rook`）。
    #    ⚠️ 手写探针曾用「短序列整段等于长序列前缀」判共享前缀，会漏掉这种
    #      **部分共享**，误判成「不需要去重」—— 见 tests/_probe_nb_tables.py §②。
    ray_seg = []                                     # 每条射线的点序列
    seg_cnt = []
    for p in IDX2POS:
        paths = R.RAYS.get(p) or ()
        seg_cnt.append(len(paths))
        for path in paths:
            ray_seg.append([POS[q] for q in path])
    ray_off = _offsets(seg_cnt)
    ray_start = np.zeros(len(ray_seg), dtype=np.int32)
    ray_cnt = np.zeros(len(ray_seg), dtype=np.int32)
    ray_pts = []
    for k, seg in enumerate(ray_seg):
        ray_start[k] = len(ray_pts)
        ray_cnt[k] = len(seg)
        ray_pts.extend(seg)
    T["ray_off"], T["ray_start"], T["ray_cnt"] = ray_off, ray_start, ray_cnt
    T["ray_pts"] = np.asarray(ray_pts, dtype=np.int32)

    # ---------- 马（传统「日」8 步 + 三角区回跳）----------
    # ⚠️ 落点**去重**：`_horse` 里用 `seen` 保证同一落点只判一次。
    #    实测 HORSE_LEG 键数 == HORSE_T 总步数（768）⇒ 落点本就唯一，
    #    去重是零成本保险（对拍会验证集合仍完全一致）。
    h_dest, h_leg_start, h_leg_cnt, h_leg_pts, h_cnt = [], [], [], [], []
    for p in IDX2POS:
        seen = set()
        n = 0
        for _leg, dest in R.HORSE_T.get(p, ()):
            if dest in seen:
                continue
            seen.add(dest)
            n += 1
            legs = R.HORSE_LEG[p][dest]
            h_dest.append(POS[dest])
            h_leg_start.append(len(h_leg_pts))
            h_leg_cnt.append(len(legs))
            h_leg_pts.extend(POS[l] for l in legs)
        h_cnt.append(n)
    T["horse_off"] = _offsets(h_cnt)
    T["horse_dest"] = np.asarray(h_dest, dtype=np.int32)
    T["horse_leg_start"] = np.asarray(h_leg_start, dtype=np.int32)
    T["horse_leg_cnt"] = np.asarray(h_leg_cnt, dtype=np.int32)
    T["horse_leg_pts"] = np.asarray(h_leg_pts, dtype=np.int32)

    # ---------- 象 ----------
    e_dest, e_tian, e_army, e_cnt = [], [], [], []
    for p in IDX2POS:
        rows = R.ELE_T.get(p, ())
        e_cnt.append(len(rows))
        for dest, tian, darmy in rows:
            e_dest.append(POS[dest])
            e_tian.append(POS[tian])
            e_army.append(darmy)
    T["ele_off"] = _offsets(e_cnt)
    T["ele_dest"] = np.asarray(e_dest, dtype=np.int32)
    T["ele_tian"] = np.asarray(e_tian, dtype=np.int32)
    T["ele_army"] = np.asarray(e_army, dtype=np.int32)

    # ---------- 士 / 帅（常规 1 格）—— 键 = home*N + pos ----------
    NV = 4 * N
    adv_seg, adv_cnt = [[] for _ in range(NV)], [0] * NV
    gen_seg, gen_cnt = [[] for _ in range(NV)], [0] * NV
    for home in (1, 2, 3):
        for i, p in enumerate(IDX2POS):
            key = home * N + i
            adv_seg[key] = [POS[q] for q in R.ADV_T.get((home, p), ())]
            gen_seg[key] = [POS[q] for q in R.GEN_T.get((home, p), ())]
            adv_cnt[key] = len(adv_seg[key])
            gen_cnt[key] = len(gen_seg[key])
    T["adv_off"] = _offsets(adv_cnt)
    T["gen_off"] = _offsets(gen_cnt)
    adv_pts, gen_pts = [], []
    for k in range(NV):
        adv_pts.extend(adv_seg[k])
        gen_pts.extend(gen_seg[k])
    T["adv_pts"] = np.asarray(adv_pts, dtype=np.int32)
    T["gen_pts"] = np.asarray(gen_pts, dtype=np.int32)

    # ---------- 兵 ----------
    p_q, p_qa, p_qr, p_qc, p_cnt = [], [], [], [], []
    for p in IDX2POS:
        rows = R.PAWN_T.get(p, ())
        p_cnt.append(len(rows))
        for q, qa, qr, qc in rows:
            p_q.append(POS[q])
            p_qa.append(qa)
            p_qr.append(qr)
            p_qc.append(qc)
    T["pawn_off"] = _offsets(p_cnt)
    T["pawn_q"] = np.asarray(p_q, dtype=np.int32)
    T["pawn_qa"] = np.asarray(p_qa, dtype=np.int32)
    T["pawn_qr"] = np.asarray(p_qr, dtype=np.int32)
    T["pawn_qc"] = np.asarray(p_qc, dtype=np.int32)

    # ---------- 全源距离矩阵（评估用）----------
    dm = np.full(N * N, 15, dtype=np.int32)
    from collections import deque
    for si, src in enumerate(IDX2POS):
        dd = {src: 0}
        q = deque([src])
        while q:
            cur = q.popleft()
            for nb in D.BOARD.adj.get(cur, ()):
                if nb not in dd:
                    dd[nb] = dd[cur] + 1
                    q.append(nb)
        for ti, t in enumerate(IDX2POS):
            dm[si * N + ti] = dd[t]
    T["dist"] = dm

    # ---------- 反向攻击表 ATK_BY（将军判定 / 攻击判定）----------
    a_pos, a_kind, a_ex_start, a_ex_cnt, a_ex = [], [], [], [], []
    cnt_by_t = [0] * N
    for ti, t in enumerate(IDX2POS):
        for pos, specs in (R.ATK_BY.get(t) or {}).items():
            for kind, extra in specs:
                a_pos.append(POS[pos])
                a_kind.append(KIND_ID[kind])
                start = len(a_ex)
                if kind in (R.ROOK, R.CANNON):
                    a_ex.extend(POS[q] for q in extra)          # 中间点序列
                elif kind == R.HORSE:
                    a_ex.append(POS[extra])                     # 蹩腿点
                elif kind == R.ELEPHANT:
                    tian, darmy = extra
                    a_ex.append(POS[tian])
                    a_ex.append(int(darmy))
                else:                                           # 帅/士/兵：home
                    a_ex.append(int(extra))
                a_ex_start.append(start)
                a_ex_cnt.append(len(a_ex) - start)
                cnt_by_t[ti] += 1
    T["atk_off"] = _offsets(cnt_by_t)
    T["atk_pos"] = np.asarray(a_pos, dtype=np.int32)
    T["atk_kind"] = np.asarray(a_kind, dtype=np.int32)
    T["atk_ex_start"] = np.asarray(a_ex_start, dtype=np.int32)
    T["atk_ex_cnt"] = np.asarray(a_ex_cnt, dtype=np.int32)
    T["atk_ex"] = np.asarray(a_ex, dtype=np.int32)

    # ---------- 子力价值（按 kind_id 索引，0 号位补 0）----------
    v = np.zeros(8, dtype=np.float64)
    for kid, kname in KIND_NAME.items():
        v[kid] = R.VALUE[kname]
    T["value"] = v
    T["sqrt_value"] = np.sqrt(v)
    return T


TAB = _build()

rc_army, rc_row, rc_col = TAB["rc_army"], TAB["rc_row"], TAB["rc_col"]
ray_off, ray_start, ray_cnt, ray_pts = (TAB["ray_off"], TAB["ray_start"],
                                        TAB["ray_cnt"], TAB["ray_pts"])
horse_off, horse_dest = TAB["horse_off"], TAB["horse_dest"]
horse_leg_start, horse_leg_cnt, horse_leg_pts = (TAB["horse_leg_start"],
                                                 TAB["horse_leg_cnt"],
                                                 TAB["horse_leg_pts"])
ele_off, ele_dest, ele_tian, ele_army = (TAB["ele_off"], TAB["ele_dest"],
                                         TAB["ele_tian"], TAB["ele_army"])
adv_off, adv_pts, gen_off, gen_pts = (TAB["adv_off"], TAB["adv_pts"],
                                      TAB["gen_off"], TAB["gen_pts"])
pawn_off, pawn_q, pawn_qa = TAB["pawn_off"], TAB["pawn_q"], TAB["pawn_qa"]
pawn_qr, pawn_qc = TAB["pawn_qr"], TAB["pawn_qc"]
DIST = TAB["dist"]
ATK_OFF, ATK_POS, ATK_KIND = TAB["atk_off"], TAB["atk_pos"], TAB["atk_kind"]
ATK_EX_START, ATK_EX_CNT, ATK_EX = (TAB["atk_ex_start"], TAB["atk_ex_cnt"],
                                    TAB["atk_ex"])
VALUE_BY_KIND, SQRT_VALUE = TAB["value"], TAB["sqrt_value"]

# 单层着法上限（安全上界：48 子 × 单子最多 ~20 步 → 960；取 1024 更稳）
MAX_MOVES = 1024
MAX_PIECES = 64                              # 单方非帅子上限（一盘每方 16 子）

# ================================================================ njit 内核
from numba import njit, objmode               # noqa: E402


@njit(inline="always")
def _army_of(c):
    return (c >> SH_ARMY) & 3


@njit(inline="always")
def _home_of(c):
    return (c >> SH_HOME) & 3


@njit(inline="always")
def _kind_of(c):
    return c >> SH_KIND


@njit(inline="always")
def _is_deputy(c):
    return (c & 1) == 1


@njit(inline="always")
def _land_ok(CODE, army, q):
    """能否落到 q：空点可、敌子可、己子不可（搜索场景 frozen 恒为空集，故省略）"""
    t = CODE[q]
    return t == 0 or _army_of(t) != army


# ---------------------------------------------------------------- 各子走法
@njit(inline="always")
def _g_rook(CODE, pos, army, OUT, n, STAMP, CTR):
    CTR[0] += 1
    s = CTR[0]
    for k in range(ray_off[pos], ray_off[pos + 1]):
        st = ray_start[k]
        for i in range(ray_cnt[k]):
            q = ray_pts[st + i]
            t = CODE[q]
            if t == 0:
                if STAMP[q] != s:
                    STAMP[q] = s
                    OUT[n] = (pos << SHIFT) | q
                    n += 1
                continue
            if _army_of(t) != army and STAMP[q] != s:
                STAMP[q] = s
                OUT[n] = (pos << SHIFT) | q
                n += 1
            break
    return n


@njit(inline="always")
def _g_cannon(CODE, pos, army, OUT, n, STAMP, CTR):
    CTR[0] += 1
    s = CTR[0]
    for k in range(ray_off[pos], ray_off[pos + 1]):
        jumped = False
        st = ray_start[k]
        for i in range(ray_cnt[k]):
            q = ray_pts[st + i]
            t = CODE[q]
            if not jumped:
                if t == 0:
                    if STAMP[q] != s:
                        STAMP[q] = s
                        OUT[n] = (pos << SHIFT) | q
                        n += 1
                else:
                    jumped = True                        # 炮架
            else:
                if t == 0:
                    continue
                if _army_of(t) != army and STAMP[q] != s:
                    STAMP[q] = s
                    OUT[n] = (pos << SHIFT) | q
                    n += 1                               # 隔一子吃
                break
    return n


@njit(inline="always")
def _g_horse(CODE, pos, army, OUT, n, STAMP, CTR):
    """马：传统「日」8 步 + 三角区回跳。

    ⚠️ 蹩腿语义必须与 `rules_dxf._horse` **逐字一致**：
        腿点有子即蹩（敌我一视同仁），且原码写的是 `all(l in board for l in legs)`
        —— 「**所有**腿都被占才跳过」，不是 any。
        实测腿数恒为 1（768/768），两者等价；这里照抄 all 语义，零风险。
    """
    for k in range(horse_off[pos], horse_off[pos + 1]):
        all_occ = True
        for j in range(horse_leg_start[k], horse_leg_start[k] + horse_leg_cnt[k]):
            if CODE[horse_leg_pts[j]] == 0:
                all_occ = False
                break
        if all_occ:
            continue                                     # 蹩马腿
        dest = horse_dest[k]
        if _land_ok(CODE, army, dest):
            OUT[n] = (pos << SHIFT) | dest
            n += 1
    return n


@njit(inline="always")
def _g_elephant(CODE, pos, home, army, OUT, n, STAMP, CTR):
    """象：跨田字对角，卡腿只看田中心（不分敌我），且不过河（限本方领地）"""
    for k in range(ele_off[pos], ele_off[pos + 1]):
        if ele_army[k] != home:
            continue                                     # 象不过河
        if CODE[ele_tian[k]] != 0:
            continue                                     # 田中心有子 → 卡腿
        dest = ele_dest[k]
        if _land_ok(CODE, army, dest):
            OUT[n] = (pos << SHIFT) | dest
            n += 1
    return n


@njit(inline="always")
def _g_advisor(CODE, pos, home, army, OUT, n, STAMP, CTR):
    key = home * N + pos
    for k in range(adv_off[key], adv_off[key + 1]):
        q = adv_pts[k]
        if _land_ok(CODE, army, q):
            OUT[n] = (pos << SHIFT) | q
            n += 1
    return n


@njit(inline="always")
def _g_general(CODE, pos, home, army, OUT, n, STAMP, CTR):
    """帅 / 副帅：军帐内横竖走 1 格 ＋ 射杀（常规着法在前，顺序与 Python 版一致）

    射杀与常规落点**共用同一个 stamp**，所以天然去重 ——
    与 `rules_dxf._general` 里「两类可能重叠（相邻敌帅既走得到也射得到）故用 seen」
    的处理完全一致。
    """
    CTR[0] += 1
    s = CTR[0]
    key = home * N + pos
    for k in range(gen_off[key], gen_off[key + 1]):
        q = gen_pts[k]
        if _land_ok(CODE, army, q) and STAMP[q] != s:
            STAMP[q] = s
            OUT[n] = (pos << SHIFT) | q
            n += 1
    for k in range(ray_off[pos], ray_off[pos + 1]):      # 射杀：沿见面线照见敌帅
        st = ray_start[k]
        for i in range(ray_cnt[k]):
            q = ray_pts[st + i]
            t = CODE[q]
            if t == 0:
                continue                                 # 视线继续延伸
            if _kind_of(t) == K_GENERAL and _army_of(t) != army and STAMP[q] != s:
                STAMP[q] = s
                OUT[n] = (pos << SHIFT) | q
                n += 1                                   # ★ 照见即可吃
            break                                        # 第一个子 —— 到此为止
    return n


@njit(inline="always")
def _g_pawn(CODE, pos, home, army, OUT, n, STAMP, CTR):
    """兵：向心前进 1 格；**过河**（跨过中心地带进入对方领地）后才可横走；
    到达**中心三角区格点**后可在三点间自由回跳（不受「只能过一次界」限制）。

    ⚠️ 与 `rules_dxf._pawn` 逐分支同构。三处最易抄错的语义：
      · `crossed = not in_own` —— 「过河」是**进了对方领地**，不是「走到本方 row5」
        （老师 2026-09-25 原话：「魏国的兵 A7 在没有过河之前不能横向左右行走」）
      · 过河落点 = 本方 row5 沿纵向路线正对的对面 row5 ⇒ 列号满足 **和恒为 10**
      · 三角区回跳（老师 2026-10-01）：「允许各方兵在中心三角区回跳」——
        三角区三点 (行,列) 恒为 (5,5)，该分支必须放在 `not in_own` **之前**
    """
    pa = rc_army[pos]
    r0 = rc_row[pos]
    c0 = rc_col[pos]
    in_own = (pa == home)
    crossed = not in_own
    for k in range(pawn_off[pos], pawn_off[pos + 1]):
        q = pawn_q[k]
        if not _land_ok(CODE, army, q):
            continue
        qa = pawn_qa[k]
        qr = pawn_qr[k]
        qc = pawn_qc[k]
        if qa == pa:
            if in_own:
                if qr < r0:
                    continue                             # 不可后退
                if qr > r0 and qc != c0:
                    continue                             # 向心必须同列
                if qr == r0 and not crossed:
                    continue                             # 未过界不可横走
                OUT[n] = (pos << SHIFT) | q
                n += 1
            else:
                if qr > r0:
                    continue                             # 不可朝中心方向退
                if qr < r0 and qc != c0:
                    continue                             # 深入须同列
                OUT[n] = (pos << SHIFT) | q
                n += 1
        else:
            # ★【2026-10-01 老师新规】三角区回跳（与 `rules_dxf._pawn` 逐字同构）：
            #   三角区三格点 = 三方各自的 row5 中点（魏A5/吴K5/蜀F5），
            #   其 (行,列) **恒为 (5,5)** —— 全盘只有这 3 个点满足，故直接判坐标。
            #   任何归属方的兵站上去 → 可走到另两点，且**不算过界**（可反复穿梭）。
            #   本分支必须在 `if not in_own` 之前：对「已在他国营点」的兵同样开放。
            if r0 == 5 and c0 == 5 and qr == 5 and qc == 5:
                OUT[n] = (pos << SHIFT) | q
                n += 1
                continue
            if not in_own:
                continue                                 # 只能过一次界
            if r0 == 5 and qr == 5 and qc == 10 - c0:
                OUT[n] = (pos << SHIFT) | q
                n += 1
    return n


@njit
def gen_side(CODE, army, OUT, STAMP, CTR):
    """一方的全部伪合法着法（写入 OUT，返回条数）

    顺序与 `rules_dxf.side_moves` 一致：按点索引升序、点内按子种自己的表序。
    """
    n = 0
    for pos in range(N):
        c = CODE[pos]
        if c == 0 or _army_of(c) != army:
            continue
        k = _kind_of(c)
        home = _home_of(c)
        if k == K_ROOK:
            n = _g_rook(CODE, pos, army, OUT, n, STAMP, CTR)
        elif k == K_HORSE:
            n = _g_horse(CODE, pos, army, OUT, n, STAMP, CTR)
        elif k == K_CANNON:
            n = _g_cannon(CODE, pos, army, OUT, n, STAMP, CTR)
        elif k == K_ELEPHANT:
            n = _g_elephant(CODE, pos, home, army, OUT, n, STAMP, CTR)
        elif k == K_ADVISOR:
            n = _g_advisor(CODE, pos, home, army, OUT, n, STAMP, CTR)
        elif k == K_GENERAL:
            n = _g_general(CODE, pos, home, army, OUT, n, STAMP, CTR)
        else:
            n = _g_pawn(CODE, pos, home, army, OUT, n, STAMP, CTR)
    return n


@njit
def gen_point(CODE, pos, OUT, STAMP, CTR):
    """单点的伪合法着法（对拍用：逐点比对）"""
    c = CODE[pos]
    if c == 0:
        return 0
    army = _army_of(c)
    home = _home_of(c)
    k = _kind_of(c)
    if k == K_ROOK:
        return _g_rook(CODE, pos, army, OUT, 0, STAMP, CTR)
    if k == K_HORSE:
        return _g_horse(CODE, pos, army, OUT, 0, STAMP, CTR)
    if k == K_CANNON:
        return _g_cannon(CODE, pos, army, OUT, 0, STAMP, CTR)
    if k == K_ELEPHANT:
        return _g_elephant(CODE, pos, home, army, OUT, 0, STAMP, CTR)
    if k == K_ADVISOR:
        return _g_advisor(CODE, pos, home, army, OUT, 0, STAMP, CTR)
    if k == K_GENERAL:
        return _g_general(CODE, pos, home, army, OUT, 0, STAMP, CTR)
    return _g_pawn(CODE, pos, home, army, OUT, 0, STAMP, CTR)


# ================================================================ 攻击判定
@njit(inline="always")
def _hit(CODE, pos, kind_id, ex_start, ex_cnt, target):
    """spec 是否命中 target —— 与 `rules_dxf._hit` 逐分支同构

    extra 的含义随子种变化（见 `_build()` 的打包口径）：
        车/炮        中间点序列（车要求全空；炮要求恰 1 子）
        马           蹩腿点（空则可跳）
        象           (田中心, 落点方) —— 还要求 home == 落点方（不过河）
        帅/士/兵     home
    """
    if kind_id == K_ROOK:
        for j in range(ex_cnt):
            if CODE[ATK_EX[ex_start + j]] != 0:
                return False
        return True
    if kind_id == K_CANNON:
        c = 0
        for j in range(ex_cnt):
            if CODE[ATK_EX[ex_start + j]] != 0:
                c += 1
        return c == 1
    if kind_id == K_HORSE:
        return CODE[ATK_EX[ex_start]] == 0
    if kind_id == K_ELEPHANT:
        return (_home_of(CODE[pos]) == ATK_EX[ex_start + 1]
                and CODE[ATK_EX[ex_start]] == 0)
    if kind_id == K_GENERAL:
        if pos == target and not _is_deputy(CODE[pos]):
            return False                                 # 帅不"攻击"自己所在点
        return _home_of(CODE[pos]) == ATK_EX[ex_start]
    return _home_of(CODE[pos]) == ATK_EX[ex_start]        # 兵 / 士


@njit
def under_attack(CODE, target, by_army):
    """by_army 方是否攻击 target —— 反向查表版（与 `rules_dxf.under_attack` 等价）"""
    t = CODE[target]
    if t != 0 and _army_of(t) == by_army:
        return False                                     # 己方占着 target，不算攻击
    for j in range(ATK_OFF[target], ATK_OFF[target + 1]):
        pos = ATK_POS[j]
        c = CODE[pos]
        if c == 0 or _army_of(c) != by_army:
            continue
        if ATK_KIND[j] == _kind_of(c) and _hit(CODE, pos, ATK_KIND[j],
                                               ATK_EX_START[j], ATK_EX_CNT[j],
                                               target):
            return True
    return False


# ================================================================ 叶节点评估
W_KEYS = ("pressure", "danger", "urgency", "material", "check",
          "close1", "close2", "mobility", "deputy", "gen_lost")
W_IDX = {k: i for i, k in enumerate(W_KEYS)}

# ⚠️ **numba 不支持在 nopython 里索引全局 dict**（`W_IDX["pressure"]` 会报
#    `Untyped global name`）。所以 `leaf` 里一律用**字面量下标**：
#        0=pressure  1=danger  4=check  5=close1  6=close2  3=material  8=deputy
#    下标与 W_KEYS 的绑定是隐式的 —— 所以在导入时**钉死**顺序：
#    谁改动 W_KEYS，这里立刻 AssertionError，而不是静默算错分。
assert W_KEYS == ("pressure", "danger", "urgency", "material", "check",
                  "close1", "close2", "mobility", "deputy", "gen_lost"), \
    "W_KEYS 顺序被改动 —— nb_core.leaf 里的字面量下标必须同步更新！"

# 复用工作区：⚠️ **必须由调用方作为参数传入**，不能在 njit 里直接读写模块级
# 全局数组 —— numba 会把全局 numpy 数组编译成 `readonly array`，
# 一旦在其中赋值就是 `Cannot modify readonly array`（实测踩过）。
_LEAF_GP = np.zeros(4, dtype=np.int32)
_LEAF_MAT = np.zeros(4, dtype=np.float64)
_LEAF_BP = np.zeros((4, MAX_PIECES), dtype=np.int32)
_LEAF_BK = np.zeros((4, MAX_PIECES), dtype=np.int32)
_LEAF_BN = np.zeros(4, dtype=np.int32)


@njit
def leaf(CODE, me, W, ur, gp, mat, bp, bk, bn):
    """叶节点评估 —— 与 `SearchBot._leaf` / `eval_dxf.evaluate` 同公式

    返回从 me 方视角的分数。逐项对应：
        ① 我离敌帅的进攻压强（Σ sqrt(子力)×逼近量，带 urgency）
        ② 贴脸奖励（≤1 步 / ==2 步）+ 将军（强制对手应对，三人棋唯一破僵机制）
        ③ 敌对我帅的压强（负分，不带 urgency）
        ④ 斩帅奖励（对手主帅已被斩 → 该方出局）
        ⑤ 子力（只与**最强**的对手比）
        ⑥ 副帅（专利版：主帅失守仍保有战斗力）
    """
    for a in range(4):
        gp[a] = -1
        mat[a] = 0.0
        bn[a] = 0
    deputies = 0
    for pos in range(N):
        c = CODE[pos]
        if c == 0:
            continue
        a = _army_of(c)
        k = _kind_of(c)
        if k == K_GENERAL:
            if _is_deputy(c):
                if _home_of(c) == me:
                    deputies += 1
            else:
                gp[_home_of(c)] = pos
            continue
        if bn[a] < MAX_PIECES:
            bp[a, bn[a]] = pos
            bk[a, bn[a]] = k
            bn[a] += 1
        mat[a] += VALUE_BY_KIND[k]

    my_gen = gp[me]
    if my_gen < 0:
        return -1e6                                      # 我方主帅已失 → 出局

    wprs = ur * W[0]                                     # pressure
    dgr = W[1]                                           # danger
    c1 = ur * W[5]                                       # close1
    c2 = ur * W[6]                                       # close2
    wchk = ur * W[4]                                     # check
    sc = 0.0

    # ① + ② 我对各敌帅的进攻压强与贴脸奖励（含将军判定）
    for enemy in range(1, 4):
        gpos = gp[enemy]
        if gpos < 0 or enemy == me:
            continue
        base = gpos * N
        chk = False
        if wchk != 0.0:
            for j in range(bn[me]):
                pos = bp[me, j]
                d = DIST[base + pos]
                sc += wprs * SQRT_VALUE[bk[me, j]] * (15 - d)
                if d <= 1:
                    sc += c1
                elif d == 2:
                    sc += c2
                if not chk:
                    # 只用「这一轮已经遍历到的子」顺手判将军（不另开一遍扫描）
                    for jj in range(ATK_OFF[gpos], ATK_OFF[gpos + 1]):
                        if ATK_POS[jj] != pos or ATK_KIND[jj] != bk[me, j]:
                            continue
                        if _hit(CODE, pos, ATK_KIND[jj], ATK_EX_START[jj],
                                ATK_EX_CNT[jj], gpos):
                            chk = True
                            break
        else:
            for j in range(bn[me]):
                pos = bp[me, j]
                d = DIST[base + pos]
                sc += wprs * SQRT_VALUE[bk[me, j]] * (15 - d)
                if d <= 1:
                    sc += c1
                elif d == 2:
                    sc += c2
        if chk:
            sc += wchk

    # ③ 各敌对我帅的压强（负分，不带 urgency）
    # ⚠️⚠️ 同样只算「主帅还在盘上」的方（Python 版 `for enemy in gens`）。
    #    出局方的残兵虽然还能吃子，但**不计入压强** —— 与 Python 版逐字对齐。
    dbase = my_gen * N
    for enemy in range(1, 4):
        if enemy == me or gp[enemy] < 0:
            continue
        for j in range(bn[enemy]):
            d = DIST[dbase + bp[enemy, j]]
            sc -= dgr * VALUE_BY_KIND[bk[enemy, j]] * (15 - d)

    # ④ 对手主帅已被斩 → 我离"只剩一方"更近一步
    for a in range(1, 4):
        if a != me and gp[a] < 0:
            sc += 4000.0

    # ⑤ 子力：只与**最强的对手**比（三人棋里最强者才是最终对手）
    # ⚠️⚠️ 必须排除「主帅已被斩」的方 —— Python 版是 `for enemy in gens`，
    #    而 `gens` 只装**主帅还在盘上**的方。若把出局方也算进来，
    #    它那堆留在盘上的残兵会被当成"最强对手" ⇒ `top` 偏大 ⇒ 我的分被压低。
    #    实测：吃掉魏帅的那一手，Python=4038.319627 / JIT=4015.969627，**Δ=22.35**。
    top = 0.0
    for a in range(1, 4):
        if a != me and gp[a] >= 0 and mat[a] > top:
            top = mat[a]
    sc += W[3] * (mat[me] - top)                         # material

    # ⑥ 副帅
    sc += W[8] * deputies                                # deputy
    return sc


# ================================================================ Python 包装
def encode_board(board):
    """dict 棋盘 → CODE 数组（对拍 / 接入用的桥）"""
    code = np.zeros(N, dtype=np.int32)
    for pos, pc in board.items():
        code[POS[pos]] = pack(KIND_ID[pc["kind"]], pc["army"], pc["home"],
                              bool(pc.get("deputy")))
    return code


def decode_board(CODE):
    """CODE 数组 → dict 棋盘（与 `encode_board` 严格互逆）"""
    out = {}
    for i in range(N):
        c = int(CODE[i])
        if c == 0:
            continue
        kid, a, h, dep = unpack(c)
        pc = {"kind": KIND_NAME[kid], "army": a, "home": h}
        if dep:
            pc["deputy"] = True
        out[IDX2POS[i]] = pc
    return out


class Scratch:
    """复用的工作区。

    `out` 分 `MAX_PLY + 1` 段：搜索递归时第 d 层用第 d 段，
    这样内层调用不会覆写外层的着法列表（旧版靠 Python 列表天然隔离）。
    """

    MAX_PLY = 20

    def __init__(self):
        self.out = np.zeros((self.MAX_PLY + 1, MAX_MOVES), dtype=np.int32)
        self.stamp = np.zeros(N, dtype=np.int32)
        self.ctr = np.zeros(1, dtype=np.int32)

    def seg(self, depth):
        return self.out[min(depth, self.MAX_PLY)]


_SCR = Scratch()


def gen_side_py(board, army, scratch=None):
    """一方的全部伪合法着法 → [('111','121'), ...]（对拍 / 接入共用）"""
    sc = scratch or _SCR
    code = encode_board(board)
    n = int(gen_side(code, np.int32(army), sc.out[0], sc.stamp, sc.ctr))
    return [(IDX2POS[int(sc.out[0][i]) >> SHIFT], IDX2POS[int(sc.out[0][i]) & 255])
            for i in range(n)]


def gen_point_py(board, pos, scratch=None):
    """单点伪合法着法 → ['121', ...]（对拍逐点比对用）"""
    sc = scratch or _SCR
    code = encode_board(board)
    n = int(gen_point(code, np.int32(POS[pos]), sc.out[0], sc.stamp, sc.ctr))
    return [IDX2POS[int(sc.out[0][i]) & 255] for i in range(n)]


def leaf_py(board, me, w, ply=0):
    """叶节点评估（Python 侧包装）"""
    code = encode_board(board)
    W = np.zeros(len(W_KEYS), dtype=np.float64)
    for k, i in W_IDX.items():
        W[i] = float(w.get(k, 0.0))
    ur = 1.0 + ply * float(w.get("urgency", 0.0))
    return float(leaf(code, np.int32(me), W, ur, _LEAF_GP, _LEAF_MAT,
                      _LEAF_BP, _LEAF_BK, _LEAF_BN))


@njit
def _node(CODE, turn, mask, plies, alpha, beta, me, W, ur, WIDTH,
          QSMAX, QMVB, QSCB, MVB, SCB, STAMP, CTR, HIST, KILL, CTX,
          LGP, LMAT, LBP, LBK, LBN):
    """`_search` 的**非递归包装** —— 只做一件事：转手调 `_search`

    ⚠️ 为什么必须有这一层：
       `_search` 是**递归** njit。从 Python 解释器**直接**调它（哪怕经一层普通
       Python 函数转手）会踩 numba 的两个坑：
         · 报 `RuntimeError: numba jitted function aborted due to unresolved symbol`
         · 或者更糟 —— **跑一阵后整进程 Segmentation fault**（实测：连续 44 次
           plies=5 调用后必崩，即便开了 `NUMBA_BOUNDSCHECK=1` 也不抛 IndexError，
           因为根本不是下标越界，是递归入口的栈/符号解析问题）。
       `search_root` 之所以一直没事，就是因为它本身就是 njit ——
       **njit 调 njit 是受支持的正常路径**。这里照抄同样的结构即可。
    """
    return _search(CODE, turn, mask, plies, alpha, beta, me, W, ur, WIDTH,
                   QSMAX, QMVB, QSCB, MVB, SCB, STAMP, CTR, HIST, KILL, CTX,
                   LGP, LMAT, LBP, LBK, LBN)


def search_node(board, turn, mask, plies, me, w, ur, alpha=-1e9, beta=1e9,
                width=None, scratch=None, code=None, reset=True, qs=0):
    """**单节点**求值（Python 桥）—— 只做一次 `_search`，且历史/杀手表**从空开始**

    用途：对拍 / 逐层下降解剖。
    `search_plies` 是「根节点 + 迭代加深 + 根着法排名」的完整入口，
    它天然只会算 **max 节点**（替 `me` 找最优）。
    要比较搜索树**中间**某个 min 节点（对手视角）的值，就必须能直接调 `_search`。

    ⚠️ 为什么不在测试里直接调 `NB._search`：
       `_search` 是**递归** njit，内部有 `with objmode()` 调 `_now_ns()`。
       从 Python 解释器**直接**调它的 dispatcher 会抛
       `RuntimeError: numba jitted function aborted due to unresolved symbol`
       （numba 的 objmode 交互坑；另注：2026-09-26 起本模块已**全面禁用
         `cache=True`**，原因见 `QS_CAP` 上方那段"读缓存必 SEGV"的说明）。
       包一层普通 Python 函数即可绕过 ——
       因为走的是 dispatcher 的正常调用路径，与 `search_plies` 内部完全一样。

    返回 float（从 `me` 方视角的分数）。

    reset=True（默认）：清空历史/杀手表后开搜（等价于"独立一次搜索"）。
    reset=False：**保留**历史/杀手表 —— 供「锁步复刻 `search_root` 的根循环」
        使用（逐手棋累积同一份表，才能和 Python 版逐手对照状态）。
    """
    sc = scratch or _SEARCHSCR
    if reset:
        sc.reset_tables()
    CODE = sc.code if code is None else code
    if code is None:
        CODE[:] = encode_board(board)
    W = np.zeros(len(W_KEYS), dtype=np.float64)
    for k, i in W_IDX.items():
        W[i] = float(w.get(k, 0.0))
    sc.ctx[0] = 0
    sc.ctx[1] = 0
    sc.ctx[2] = np.int64(1 << 62)                 # 远未来：解剖时不需要超时
    wd = WIDTH_T if width is None else width
    return float(_node(CODE, np.int32(turn), np.int32(mask), np.int32(plies),
                       float(alpha), float(beta), np.int32(me), W, float(ur), wd,
                       np.int32(qs), sc.qmv, sc.qsc,
                       sc.mvb, sc.scb, sc.stamp, sc.ctr, sc.hist, sc.kill,
                       sc.ctx, sc.lgp, sc.lmat, sc.lbp, sc.lbk, sc.lbn))


def alive_mask_py(board):
    """盘上还有主帅的方 → 位掩码（`_alive_mask` 的 Python 等价，供测试用）"""
    m = 0
    for _pos, pc in board.items():
        if pc["kind"] == "general" and not pc.get("deputy"):
            m |= 1 << pc["home"]
    return m


def next_turn_py(mask, turn):
    """按 1→2→3→1 推进、跳过出局方的 Python 等价"""
    a = turn
    for _ in range(3):
        a = a % 3 + 1
        if mask & (1 << a):
            return a
    return a


def warmup():
    """预热编译（服务启动时调一次，避免首手卡顿）"""
    code = np.zeros(N, dtype=np.int32)
    sc = _SCR
    for a in (1, 2, 3):
        gen_side(code, np.int32(a), sc.out[0], sc.stamp, sc.ctr)
    leaf(code, np.int32(1), np.zeros(len(W_KEYS)), 1.0, _LEAF_GP, _LEAF_MAT,
         _LEAF_BP, _LEAF_BK, _LEAF_BN)
    under_attack(code, np.int32(0), np.int32(1))


# ================================================================ 搜索内核
# paranoid minimax + alpha-beta 剪枝 + PVS + 宽度限制 + 历史/杀手启发
#
# 【为什么是 paranoid】三人棋非零和，严格解要 Max-n（每节点存三方分数向量）。
# paranoid 把另两方都当敌人 —— 规则上任何一方吃掉我的帅我都立刻出局，
# 所以「两个对手都在想办法弄死我」不是保守假设，而是对局面的忠实近似。
# 于是博弈重新变回零和，alpha-beta 可直接用。
#
# 【与 `SearchBot._search` 的**逐行对应关系**】
#   本函数是 Python 版的直译，剪枝/排序/PVS 窗口/历史表口径完全一致。
#   已核对的易错点（对拍脚本会覆盖）：
#     · PVS 零窗口宽度用 EPS=1e-3（必须远小于 INF，否则浮点舍入使窗口退化为 0）
#     · 历史分封顶 90000（否则安静着法会挤到吃子档前面，剪枝率反降）
#     · 杀手着法只收「安静着法」（unmake 之后目标格为空才算安静）
#     · 吃「帅」和吃「副帅」同权重 1e9（`vic["kind"] == GENERAL` 不排除 deputy）
#     · 根节点的下一方用**旧** alive 推（`_next(alive, me)`），alive 参数才用新的
MAX_PLY = 20
# 静态搜索（方案 ②）的**缓冲容量上限**（真正使用的层数由 `search_plies(qs=)` 传）。
# 吃子链长度天然有上限（每吃一次盘上子力 -1），32 是纯保险值。
QS_CAP = 32

# ⚠️⚠️ 【2026-09-26 · 重要 · 本模块的 njit **一律不加 `cache=True`**】
#   原因：方案 ② 的 `_qsearch` 是**递归** njit（且调用 `leaf`/`gen_side`/`_order`，
#   其中 `_now_ns` 走 `objmode`）。一旦把它的编译产物写进磁盘缓存，
#   **下次进程读回缓存时必然 `Segmentation fault`（exit=139）**。
#
#   实测（每次先清空 `__pycache__/nb_core.*.nbi|nbc`，再连跑 3 次）：
#     · 全部 `cache=True`（含 `_qsearch`）    → 第 1 次 OK，**第 2、3 次 SEGV**
#     · 只给 `_qsearch` 单独去 cache          → **第 2、3 次仍 SEGV**（连 `warmup()` 都过不去）
#     · **全模块去 cache**                    → **连跑 3 次 `exit=0`，结果逐位相同** ✅
#   同一模式在 `_verify_nb_search.py` / `_verify_jit_choose.py` / `_verify_difficulty.py`
#   上稳定复现（都是 `exit=139`，且崩点都在"加载缓存"而非"跑搜索"）。
#
#   代价：每次进程启动多约 15 s 的全量编译。
#     · 服务：`app.py` 用**后台线程**预热（一次性，老师完全无感）；
#     · 测试脚本：每次多 ~15 s，换来"不再随机 SEGV"，值得。
#
#   🚧 若将来想恢复 `cache=True`：必须先把 `_qsearch` 改成**非递归（显式栈）实现**，
#      并重跑 `tests/_verify_qsearch_parity.py` 全绿 + 清缓存连跑 3 次无 SEGV。
#      **不要只加回装饰器就完事** —— 这是会静默崩进程的坑。
INF = 1e9
TIE_EPS = 1e-9      # 根节点「精确并列」判定容差（与 Python 版 `_TIE_EPS` 同值）
                    #   镜像对称着法分数逐位相等 ⇒ 1e-9 足够；有实质差异则不随机。
                    #   见 SOUL.md 铁律 151（旧写法把噪声加在 alpha-beta 的**上界**上）
EPS = 1e-3
HIST_CAP = 90000.0
MVBUF_SIZE = 40000                           # HIST 用 (from<<8)|to 直接索引

WIDTH_T = np.zeros(MAX_PLY + 1, dtype=np.int32)
# ⚠️ 默认档必须是 **5** —— Python 版 `_search` 写的是
#    `lim = self.width.get(plies, 5)`（不是 `width_for()` 里的 4）。
#    两边默认值不同 ⇒ plies>6 处会截断不同数量的着法，行为悄悄发散。
#
# ⚠️⚠️ 这张表只是**默认值来源**。它必须由 `search_plies(width=...)` 传入 JIT，
#    不能指望 JIT 直接读全局名 —— numba 会把模块级全局 numpy 数组**常量折叠**
#    （编译期把元素值内联进机器码），之后 Python 侧改内容对已编译代码无效。
#    实测：把 WIDTH_T 从 0 改成 100000，JIT 节点数一模一样（62983 → 62983）。
#    作为**函数参数**传入的数组不会被折叠，读的是实时内存。
for _p in range(MAX_PLY + 1):
    WIDTH_T[_p] = {1: 14, 2: 10, 3: 8, 4: 6, 5: 5, 6: 4}.get(_p, 5)

KV_ROOK, KV_HORSE, KV_ELEPHANT, KV_ADVISOR, KV_GENERAL, KV_CANNON, KV_PAWN = (
    R.VALUE[R.ROOK], R.VALUE[R.HORSE], R.VALUE[R.ELEPHANT], R.VALUE[R.ADVISOR],
    R.VALUE[R.GENERAL], R.VALUE[R.CANNON], R.VALUE[R.PAWN])
KV = np.asarray([0.0, KV_ROOK, KV_HORSE, KV_ELEPHANT, KV_ADVISOR,
                 KV_GENERAL, KV_CANNON, KV_PAWN], dtype=np.float64)


@njit
def _now_ns():
    """单调时钟（纳秒）—— 只在周期性检查里调用，objmode 开销 ~µs 级可忽略

    ⚠️ `import time` 必须放在**模块顶层**：numba 的 nopython 前端不支持
       `IMPORT_NAME` 字节码，objmode 块里再 import 会报
       `UnsupportedBytecodeError: Use of unsupported opcode (IMPORT_NAME)`。
    """
    with objmode(t="int64"):
        t = time.perf_counter_ns()
    return t


@njit(inline="always")
def _alive_mask(CODE):
    """盘上还有主帅的方 → 位掩码（1|2|4）"""
    m = 0
    for pos in range(N):
        c = CODE[pos]
        if c != 0 and _kind_of(c) == K_GENERAL and not _is_deputy(c):
            m |= 1 << _home_of(c)
    return m


@njit(inline="always")
def _next_turn(mask, turn):
    """按 1→2→3→1 推进，跳过主帅已不在盘上的方"""
    a = turn
    for _ in range(3):
        a = a % 3 + 1
        if mask & (1 << a):
            return a
    return a


@njit
def _order(CODE, MVB, SCB, base, n, viewer, plies, HIST, KILL):
    """着法排序（原地，插入排序）—— alpha-beta 剪枝率的最大杠杆

    ⚠️ 排序口径必须与 Python 版 `SearchBot._order` 的
       `out.sort(reverse=True)`（对 `(score, mv)` 元组降序）**完全一致**：
       先按分数降序，**同分按 mv 降序**。
    分值档（尺度刻意拉开，保证互不串档）：
        吃敌方主帅 1e9 · 其它吃子 1e6 + 子力×100
        杀手1 5e5+h · 杀手2 4e5+h · 安静着法 h（h ≤ 9e4）
    """
    k1 = KILL[plies * 2]
    k2 = KILL[plies * 2 + 1]
    for i in range(n):
        m = MVB[base + i]
        vic = CODE[m & 255]
        if vic == 0:
            h = HIST[m]
            if m == k1:
                SCB[base + i] = 500000.0 + h
            elif m == k2:
                SCB[base + i] = 400000.0 + h
            else:
                SCB[base + i] = h
        elif _kind_of(vic) == K_GENERAL:
            SCB[base + i] = 1e9
        elif _army_of(vic) == viewer:
            SCB[base + i] = -1e5                       # 送自己的子：最差
        else:
            SCB[base + i] = 1e6 + KV[_kind_of(vic)] * 100.0
    # 插入排序（n ≤ ~50，比快排快且无递归）
    for i in range(1, n):
        s = SCB[base + i]
        m = MVB[base + i]
        j = i - 1
        while j >= 0 and (SCB[base + j] < s
                          or (SCB[base + j] == s and MVB[base + j] < m)):
            SCB[base + j + 1] = SCB[base + j]
            MVB[base + j + 1] = MVB[base + j]
            j -= 1
        SCB[base + j + 1] = s
        MVB[base + j + 1] = m


@njit
def _qsearch(CODE, turn, mask, alpha, beta, me, W, ur, qs,
             QMVB, QSCB, STAMP, CTR, HIST, KILL, CTX,
             LGP, LMAT, LBP, LBK, LBN):
    """静态搜索（quiescence）—— 与 `SearchBot._qsearch` 逐字同构（方案 ②）

    ⚠️⚠️ **本函数刻意不加 `cache=True`**（2026-09-26 实测踩坑）：
       它是**递归** njit，且会调 `leaf` / `gen_side` / `_order`（其中 `_now_ns`
       走 `objmode`）。**把它的编译产物写进磁盘缓存、下次进程读回时
       必然 `Segmentation fault`（exit=139）** —— 实测：
          · 清空 `__pycache__/nb_core.*.nbi` 后第 1 次运行（现场编译）→ **正常**
          · 第 2 次运行（读缓存）→ **连 `warmup_search()` 都没打印就 SEGV**
        同一模式在 `_verify_nb_search.py` / `_verify_jit_choose.py` /
        `_verify_difficulty.py` 三个脚本上稳定复现（都是 `exit=139`）。
       去掉 `cache=True` 后：每次进程启动会多花几秒重新编译它，
       **但服务是一次性启动 + 后台线程预热，老师完全无感**（见 `app.py`）。
       实测进一步发现：**只给本函数去 cache 不够，必须"全模块"去 cache** ——
       `_search` / `_node` / `search_root` 等在同一条调用链上的函数同样会崩。
       故 2026-09-26 起本模块 **9 处 `@njit(cache=True)` 已全部改为 `@njit`**
       （完整对照实验表见 `QS_CAP` 上方那段注释）。

    只展开**吃子**着法，直到盘面安静（无吃子可走）或吃满 `qs` 层，
    消除「固定深度边界上"我刚吃了个大子"被系统性高估」的水平线效应
    （对手下一步能反吃回来，真实分数要低得多）。

    stand-pat：不动手的分数 = `leaf(...)`
        · max 节点 `stand >= beta` 直接返回
        · min 节点 `stand <= alpha` 直接返回
      （吃子**不是义务** —— 这正是静态搜索与"强制延伸"的本质区别）

    排序**复用 `_order`**（plies 传 0，取吃子档位）：与 `_search` 同一套口径，
    且 `_order` 同分按 mv 降序 ⇒ 与输入顺序无关 ⇒ 与 Python 的 `_order` 逐位可对拍。
    （吃子着法在 `_order` 里走 `1e9` / `1e6+KV*100` 两档，**不会**触碰杀手分支，
      所以对 KILL[0]/KILL[1] 是只读的 —— 不会污染杀手表。）

    ⚠️ `qs` 必须**逐次递减**并在 `qs <= 0` 时硬返回：三方棋里"你吃我、我吃回"
       的长链条若不设上限，递归会一路拖到爆栈。
    """
    CTX[1] += 1
    if (CTX[1] & 4095) == 0 and _now_ns() > CTX[2]:
        CTX[0] = 1
    if CTX[0]:
        return 0.0

    if qs <= 0:
        return leaf(CODE, me, W, ur, LGP, LMAT, LBP, LBK, LBN)

    stand = leaf(CODE, me, W, ur, LGP, LMAT, LBP, LBK, LBN)

    qbase = qs * MAX_MOVES
    n = gen_side(CODE, turn, QMVB[qbase:], STAMP, CTR)
    nc = 0
    for i in range(n):
        m = QMVB[qbase + i]
        if CODE[m & 255] != 0:                        # 目标有子 = 吃子
            QMVB[qbase + nc] = m
            nc += 1
    if nc == 0:
        return stand                                  # 安静节点
    _order(CODE, QMVB, QSCB, qbase, nc, turn, 0, HIST, KILL)

    nxt_turn = _next_turn(mask, turn)

    if turn == me:                                    # ---------------- max 节点
        best = stand
        if best >= beta:
            return best
        if best > alpha:
            alpha = best
        for i in range(nc):
            m = QMVB[qbase + i]
            frm = m >> SHIFT
            to = m & 255
            vic = CODE[to]
            CODE[to] = CODE[frm]
            CODE[frm] = 0
            nm = mask
            # 吃子 ⇒ vic 恒非 0，无需判空；只判"是否斩了主帅"
            if _kind_of(vic) == K_GENERAL and not _is_deputy(vic):
                nm = mask & ~(1 << _home_of(vic))
            v = _qsearch(CODE, nxt_turn, nm, alpha, beta, me, W, ur, qs - 1,
                         QMVB, QSCB, STAMP, CTR, HIST, KILL, CTX,
                         LGP, LMAT, LBP, LBK, LBN)
            CODE[frm] = CODE[to]
            CODE[to] = vic
            if CTX[0]:
                return 0.0
            if v > best:
                best = v
            if v > alpha:
                alpha = v
            if alpha >= beta:
                break
        return best

    best = stand                                      # ---------------- min 节点
    if best <= alpha:
        return best
    if best < beta:
        beta = best
    for i in range(nc):
        m = QMVB[qbase + i]
        frm = m >> SHIFT
        to = m & 255
        vic = CODE[to]
        CODE[to] = CODE[frm]
        CODE[frm] = 0
        nm = mask
        if _kind_of(vic) == K_GENERAL and not _is_deputy(vic):
            nm = mask & ~(1 << _home_of(vic))
        v = _qsearch(CODE, nxt_turn, nm, alpha, beta, me, W, ur, qs - 1,
                     QMVB, QSCB, STAMP, CTR, HIST, KILL, CTX,
                     LGP, LMAT, LBP, LBK, LBN)
        CODE[frm] = CODE[to]
        CODE[to] = vic
        if CTX[0]:
            return 0.0
        if v < best:
            best = v
        if v < beta:
            beta = v
        if alpha >= beta:
            break
    return best


@njit
def _search(CODE, turn, mask, plies, alpha, beta, me, W, ur, WIDTH,
            QSMAX, QMVB, QSCB, MVB, SCB, STAMP, CTR, HIST, KILL, CTX,
            LGP, LMAT, LBP, LBK, LBN):
    """核心搜索（递归）—— 返回从 me 方视角的分数

    CTX[0] = 中止标志（超时 → 置 1，逐层立即返回，整层结果由调用方丢弃）
    CTX[1] = 节点计数      CTX[2] = 绝对截止时刻（ns）

    ⚠️ `WIDTH` 必须**作为参数**传进来，不能读模块级的 `WIDTH_T`：
       numba 会把模块级全局 numpy 数组**常量折叠**（编译期把元素值内联），
       之后 Python 侧再改数组内容对已编译代码**完全无效**
       （实测：把 WIDTH_T 从 0 改成 100000，节点数一模一样 62983）。

    QSMAX（≥ 0）= 静态搜索最大额外吃子层数（方案 ②，`_qsearch`）：
        · 0   → plies 用尽后直接 `leaf`（方案②之前的旧行为）
        · > 0 → 转 `_qsearch`，继续只搜吃子到安静为止
        ⚠️ 同 `WIDTH`，必须**作参数**传，不能做成模块级常量 —— 否则改不动。
    QMVB / QSCB = 静态搜索**专属**的着法缓冲与排序缓冲，与 `MVB`/`SCB` 分开：
        静态搜索发生在 `_search(plies=0)` 的分支里，此时 `_search(plies=1)`
        仍占着 `MVB[1*MAX_MOVES : ]` 段且**还在循环里读它**
        （`m = MVB[base+i]`）；若共用同一块缓冲，静态搜索一递归就把
        上一层的着法表**就地改掉** ⇒ 后续轮次读到脏着法。分开最省心。
    """
    CTX[1] += 1
    if (CTX[1] & 4095) == 0 and _now_ns() > CTX[2]:
        CTX[0] = 1
    if CTX[0]:
        return 0.0

    if plies <= 0:
        # ---- 方案 ② 静态搜索：固定深度用尽后继续只搜吃子（QSMAX=0 退回旧行为）
        if QSMAX > 0:
            return _qsearch(CODE, turn, mask, alpha, beta, me, W, ur, QSMAX,
                            QMVB, QSCB, STAMP, CTR, HIST, KILL, CTX,
                            LGP, LMAT, LBP, LBK, LBN)
        return leaf(CODE, me, W, ur, LGP, LMAT, LBP, LBK, LBN)

    base = plies * MAX_MOVES
    # 用**切片视图**给出该层的着法段：递归时内层用更高的 base，
    # 深度优先 ⇒ 同一时刻只有一个节点在用某个 plies，天然隔离。
    n = gen_side(CODE, turn, MVB[base:], STAMP, CTR)
    if n == 0:
        # 无着法 → 跳过这一方（与 Python 版一致：alive 不变，只推 turn）
        return _search(CODE, _next_turn(mask, turn), mask, plies - 1,
                       alpha, beta, me, W, ur, WIDTH, QSMAX, QMVB, QSCB, MVB, SCB, STAMP, CTR,
                       HIST, KILL, CTX, LGP, LMAT, LBP, LBK, LBN)

    _order(CODE, MVB, SCB, base, n, turn, plies, HIST, KILL)
    lim = WIDTH[plies]
    if n > lim:
        n = lim                                        # 宽度限制（根节点不限宽）
    nxt_turn = _next_turn(mask, turn)

    if turn == me:                                     # ---------------- max 节点
        best = -INF
        first = True
        for i in range(n):
            m = MVB[base + i]
            frm = m >> SHIFT
            to = m & 255
            vic = CODE[to]
            CODE[to] = CODE[frm]
            CODE[frm] = 0
            nm = mask
            if vic != 0 and _kind_of(vic) == K_GENERAL and not _is_deputy(vic):
                nm = mask & ~(1 << _home_of(vic))
            if first:
                v = _search(CODE, nxt_turn, nm, plies - 1, alpha, beta, me,
                            W, ur, WIDTH, QSMAX, QMVB, QSCB, MVB, SCB, STAMP, CTR,
                            HIST, KILL, CTX, LGP, LMAT, LBP, LBK, LBN)
                first = False
            else:
                # PVS：先用零窗口试探「能不能超过已知最好」，绝大多数在此被否
                v = _search(CODE, nxt_turn, nm, plies - 1, alpha, alpha + EPS,
                            me, W, ur, WIDTH, QSMAX, QMVB, QSCB, MVB, SCB, STAMP, CTR,
                            HIST, KILL, CTX, LGP, LMAT, LBP, LBK, LBN)
                if alpha < v < beta:
                    v = _search(CODE, nxt_turn, nm, plies - 1, v, beta, me,
                                W, ur, WIDTH, QSMAX, QMVB, QSCB, MVB, SCB, STAMP, CTR,
                                HIST, KILL, CTX, LGP, LMAT, LBP, LBK, LBN)
            CODE[frm] = CODE[to]
            CODE[to] = vic
            if CTX[0]:
                return 0.0
            if v > best:
                best = v
            if v > alpha:
                alpha = v
            if alpha >= beta:
                h = HIST[m] + plies * plies
                HIST[m] = h if h < HIST_CAP else HIST_CAP
                if CODE[to] == 0:                      # 安静着法才进杀手表
                    # ⚠️ 与 Python 版 `elif (frm, to) not in k:` 逐字对齐 ——
                    #    Python 是「已在表内（k1 **或** k2）就不动」，
                    #    只比 k1 的话会把 k2 重插成 k1，两边的排序从此分岔。
                    if KILL[plies * 2] != m and KILL[plies * 2 + 1] != m:
                        KILL[plies * 2 + 1] = KILL[plies * 2]
                        KILL[plies * 2] = m
                break
        return best

    best = INF                                         # ---------------- min 节点
    first = True
    for i in range(n):
        m = MVB[base + i]
        frm = m >> SHIFT
        to = m & 255
        vic = CODE[to]
        CODE[to] = CODE[frm]
        CODE[frm] = 0
        nm = mask
        if vic != 0 and _kind_of(vic) == K_GENERAL and not _is_deputy(vic):
            nm = mask & ~(1 << _home_of(vic))
        if first:
            v = _search(CODE, nxt_turn, nm, plies - 1, alpha, beta, me,
                        W, ur, WIDTH, QSMAX, QMVB, QSCB, MVB, SCB, STAMP, CTR,
                        HIST, KILL, CTX, LGP, LMAT, LBP, LBK, LBN)
            first = False
        else:
            v = _search(CODE, nxt_turn, nm, plies - 1, beta - EPS, beta, me,
                        W, ur, WIDTH, QSMAX, QMVB, QSCB, MVB, SCB, STAMP, CTR,
                        HIST, KILL, CTX, LGP, LMAT, LBP, LBK, LBN)
            if alpha < v < beta:
                v = _search(CODE, nxt_turn, nm, plies - 1, alpha, v, me,
                            W, ur, WIDTH, QSMAX, QMVB, QSCB, MVB, SCB, STAMP, CTR,
                            HIST, KILL, CTX, LGP, LMAT, LBP, LBK, LBN)
        CODE[frm] = CODE[to]
        CODE[to] = vic
        if CTX[0]:
            return 0.0
        if v < best:
            best = v
        if v < beta:
            beta = v
        if alpha >= beta:
            h = HIST[m] + plies * plies
            HIST[m] = h if h < HIST_CAP else HIST_CAP
            if CODE[to] == 0:
                if KILL[plies * 2] != m and KILL[plies * 2 + 1] != m:
                    KILL[plies * 2 + 1] = KILL[plies * 2]
                    KILL[plies * 2] = m
            break
    return best


@njit
def search_root(CODE, army, plies, W, ur, exact, ROOT, NROOT, WIDTH, noise,
                QSMAX, QMVB, QSCB,
                MVB, SCB, STAMP, CTR, HIST, KILL, CTX,
                LGP, LMAT, LBP, LBK, LBN,
                OUT_MV, OUT_SC, OUT_N):
    """根节点搜索 —— 返回最佳分数；全部根着法按分数降序写入 OUT_MV/OUT_SC

    ⚠️ **根着法由调用方给定，且必须是引擎过滤后的「合法着法」**
       （`game_dxf.legal_moves`：已排除送将 / 将见面等）。
       搜索树**内部**才用伪合法着法（`gen_side`）—— 与 Python 版
       `_choose(root=list(legal))` + `_search(moves_of…)` 的口径完全一致。
       若根节点直接用伪合法着法，就会生成"送帅"这种自毁着法，bot 立刻变傻。
    ⚠️ `ranked.sort(key=lambda x: -x[0])` 是**稳定排序**（同分保持相遇顺序），
       与 `_order` 内部「同分按 mv 降序」是**两条不同的规则**，已分别实现。
    ⚠️ exact=False（选着法）：根着法用 (alpha, INF) 窗口，没超过 alpha 的分数是
       **上界不是精确值**；exact=True（当尺子用，失误谱）才用全窗口。
    """
    CTX[0] = 0
    CTX[1] = 0
    mask = _alive_mask(CODE)
    n = NROOT
    for i in range(n):
        MVB[i] = ROOT[i]
    _order(CODE, MVB, SCB, 0, n, army, plies, HIST, KILL)

    alpha = -INF
    best, best_mv = -INF, -1
    ties = 0
    for i in range(n):
        m = MVB[i]
        frm = m >> SHIFT
        to = m & 255
        vic = CODE[to]
        CODE[to] = CODE[frm]
        CODE[frm] = 0
        nm = mask
        if vic != 0 and _kind_of(vic) == K_GENERAL and not _is_deputy(vic):
            nm = mask & ~(1 << _home_of(vic))
        # ⚠️ 下一方用**旧** mask 推（与 Python 版 `_next(alive, me)` 一致）
        sc = _search(CODE, _next_turn(mask, army), nm, plies - 1,
                     -INF if exact else alpha, INF, army, W, ur, WIDTH,
                     QSMAX, QMVB, QSCB,
                     MVB, SCB, STAMP, CTR, HIST, KILL, CTX,
                     LGP, LMAT, LBP, LBK, LBN)
        CODE[frm] = CODE[to]
        CODE[to] = vic
        if CTX[0]:
            OUT_N[0] = -1                              # 超时：整层结果作废
            return -INF
        OUT_MV[i] = m
        OUT_SC[i] = sc
        if sc > alpha:
            alpha = sc
        # ★ 探索噪声（2026-10-02 重写，与 Python 版 `_root_search` **同口径**）：
        #   **只在"精确并列"时才随机**（水库抽样：第 k 个并列者以 1/k 概率顶替）。
        #
        #   旧写法 `sel = sc + np.random.random() * noise` 把噪声加在
        #   alpha-beta 返回的**上界**上 —— 全部根着法分值被压成一坨
        #   （实测 22.46 / 22.77 / 22.95），0.5 的抖动足以让"一坨里任意一手"胜出。
        #   实测后果：默认 noise=0.5 时 3 / 9 / 12 plies 全走「送马手」。
        #   详见 SOUL.md 铁律 151。
        #
        #   ⚠️ 对拍脚本 `tests/_verify_nb_search.py` 强制 noise=0，所以旧写法
        #      在 noise=0 下两条路径仍然一致、测试全绿 —— 这个坑必须靠"默认参数矩阵"
        #      才能测出来（铁律 151 第 3 条）。
        if sc > best + TIE_EPS:
            best, best_mv = sc, m
            ties = 1
        elif noise > 0.0 and sc >= best - TIE_EPS:
            ties += 1
            if np.random.random() < 1.0 / ties:
                best_mv = m
    OUT_N[0] = n
    # 稳定排序：按分数降序（同分保持相遇顺序）
    for i in range(1, n):
        s = OUT_SC[i]
        m = OUT_MV[i]
        j = i - 1
        while j >= 0 and OUT_SC[j] < s:
            OUT_SC[j + 1] = OUT_SC[j]
            OUT_MV[j + 1] = OUT_MV[j]
            j -= 1
        OUT_SC[j + 1] = s
        OUT_MV[j + 1] = m
    OUT_N[1] = best_mv
    return best


# ---------------------------------------------------------------- 搜索工作区
class SearchScratch:
    """JIT 搜索的全部工作区（一次分配、长期复用；搜索中零分配）"""

    def __init__(self):
        self.mvb = np.zeros((MAX_PLY + 2) * MAX_MOVES, dtype=np.int32)
        self.scb = np.zeros((MAX_PLY + 2) * MAX_MOVES, dtype=np.float64)
        self.stamp = np.zeros(N, dtype=np.int32)
        self.ctr = np.zeros(1, dtype=np.int32)
        self.hist = np.zeros(MVBUF_SIZE, dtype=np.float64)
        self.kill = np.zeros((MAX_PLY + 2) * 2, dtype=np.int32)
        self.ctx = np.zeros(8, dtype=np.int64)
        self.lgp = np.zeros(4, dtype=np.int32)
        self.lmat = np.zeros(4, dtype=np.float64)
        self.lbp = np.zeros((4, MAX_PIECES), dtype=np.int32)
        self.lbk = np.zeros((4, MAX_PIECES), dtype=np.int32)
        self.lbn = np.zeros(4, dtype=np.int32)
        self.out_mv = np.zeros(MAX_MOVES, dtype=np.int32)
        self.out_sc = np.zeros(MAX_MOVES, dtype=np.float64)
        self.out_n = np.zeros(4, dtype=np.int32)
        self.root = np.zeros(MAX_MOVES, dtype=np.int32)
        self.code = np.zeros(N, dtype=np.int32)
        # ---- 静态搜索（方案 ②）专属缓冲 ----
        #   必须与 mvb/scb **分开**：静态搜索在 `_search(plies=0)` 里发生，
        #   而 `_search(plies=1)` 此刻仍占着 `mvb[1*MAX_MOVES:]` 且还在循环读它。
        #   共用会把上一层的着法表就地改脏（见 `_search` 的 QMVB 说明）。
        self.qmv = np.zeros((QS_CAP + 2) * MAX_MOVES, dtype=np.int32)
        self.qsc = np.zeros((QS_CAP + 2) * MAX_MOVES, dtype=np.float64)

    def reset_tables(self):
        """每手棋开始前必须清空历史/杀手表（与 Python 版 `_choose` 一致）"""
        self.hist[:] = 0.0
        self.kill[:] = 0


_SEARCHSCR = SearchScratch()


def search_plies(board, army, plies, w, root, ply_no=0, time_limit=None,
                 exact=False, scratch=None, code=None, reset=False, width=None,
                 noise=0.0, qs=0):
    """搜到指定 plies（一次调用 = 一层，供 Python 层做迭代加深）

    root: 根着法 [(from_str, to_str), ...] —— **必须是引擎过滤后的合法着法**
          （与 `SearchBot._choose` 里 `root = list(legal)` 完全一致）。
    reset: 是否清空历史/杀手表。**迭代加深内部应传 False**
           （Python 版 `_choose` 是「每手棋清一次、各 plies 层共享」，
             中途清掉反而损失启发质量）。独立对比测试才传 True。
    width: 宽度表（int32 数组，长度 ≥ MAX_PLY+1）；None 用默认 `WIDTH_T`。
           ⚠️ 必须是**数组对象**：宽度表要作为参数传进 JIT —— 模块级全局数组
              会被 numba 常量折叠，运行时改它无效（见 `_search` 的注释）。
    qs: 静态搜索（方案 ②）最大额外吃子层数。**0 = 关闭**（旧行为）；
        > 0 = plies 用尽后继续只搜吃子到安静为止（见 `_qsearch`）。
        与 `SearchBot(qs_depth=...)` 一一对应，对拍时两边必须传同一个值。

    返回 (best_mv, best_score, ranked, nodes, aborted)
        best_mv = (from_str, to_str) 或 None
        ranked  = [(from_str, to_str, score), ...] 按分数降序
    """
    sc = scratch or _SEARCHSCR
    if reset:
        sc.reset_tables()
    CODE = sc.code if code is None else code
    if code is None:
        CODE[:] = encode_board(board)
    W = np.zeros(len(W_KEYS), dtype=np.float64)
    for k, i in W_IDX.items():
        W[i] = float(w.get(k, 0.0))
    ur = 1.0 + ply_no * float(w.get("urgency", 0.0))
    if time_limit is None:
        sc.ctx[2] = np.int64(1 << 62)
    else:
        sc.ctx[2] = np.int64(_now_ns() + int(time_limit * 1e9))
    sc.ctx[0] = 0
    nroot = len(root)
    for i, (f, t) in enumerate(root):
        sc.root[i] = mv(POS[f], POS[t])
    wd = WIDTH_T if width is None else width
    qsi = int(qs)
    if qsi < 0:
        qsi = 0
    elif qsi > QS_CAP:
        qsi = QS_CAP
    score = float(search_root(CODE, np.int32(army), np.int32(plies), W, ur,
                              bool(exact), sc.root, np.int32(nroot), wd,
                              float(noise),
                              np.int32(qsi), sc.qmv, sc.qsc,
                              sc.mvb, sc.scb, sc.stamp, sc.ctr,
                              sc.hist, sc.kill, sc.ctx,
                              sc.lgp, sc.lmat, sc.lbp, sc.lbk, sc.lbn,
                              sc.out_mv, sc.out_sc, sc.out_n))
    n = int(sc.out_n[0])
    aborted = n < 0
    if aborted:
        return None, None, [], int(sc.ctx[1]), True
    ranked = []
    for i in range(n):
        m = int(sc.out_mv[i])
        ranked.append((IDX2POS[m >> SHIFT], IDX2POS[m & 255], float(sc.out_sc[i])))
    bm = int(sc.out_n[1])
    best = (IDX2POS[bm >> SHIFT], IDX2POS[bm & 255]) if bm >= 0 else None
    return best, score, ranked, int(sc.ctx[1]), False


def warmup_search():
    """预热搜索路径（服务启动时调一次）"""
    board = {"115": {"kind": R.GENERAL, "army": 1, "home": 1},
             "225": {"kind": R.GENERAL, "army": 2, "home": 2},
             "325": {"kind": R.GENERAL, "army": 3, "home": 3}}
    code = encode_board(board)
    sc = _SEARCHSCR
    n = int(gen_side(code, np.int32(1), sc.mvb, sc.stamp, sc.ctr))
    root = [(IDX2POS[int(sc.mvb[i]) >> SHIFT], IDX2POS[int(sc.mvb[i]) & 255])
            for i in range(n)]
    # qs=2：顺带把静态搜索（`_qsearch`）也编译出来，否则首手棋里第一次
    # 真正触发静态搜索时仍要现场编译（实测能多出 1~2 秒）。
    search_plies(board, 1, 3, dict.fromkeys(W_KEYS, 0.1), root, qs=2)


# ---------------------------------------------------------------- 自检
if __name__ == "__main__":
    import time
    print(f"表构建完成：点位 {N}")
    print(f"  射线 {len(ray_start)} 条 / {len(ray_pts)} 点")
    print(f"  马 {len(horse_dest)} 步 / 象 {len(ele_dest)} 步 / 兵 {len(pawn_q)} 步")
    print(f"  攻击表 {len(ATK_POS)} 条 spec / 距离矩阵 {DIST.size}")
    print()
    print("首次编译（numba JIT）……")
    t0 = time.time()
    try:
        from ..engine import game_dxf as GA
    except ImportError:
        import os
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))))
        from engine import game_dxf as GA
    s = GA.new_game(first=1)
    for a in (1, 2, 3):
        t1 = time.time()
        mvs = gen_side_py(s["board"], a)
        print(f"  {D.ARMY_CN[a]}方 伪合法 {len(mvs)} 步  "
              f"（首次含编译 {time.time() - t1:.1f}s）")
    print(f"编译 + 首跑合计 {time.time() - t0:.1f}s")
