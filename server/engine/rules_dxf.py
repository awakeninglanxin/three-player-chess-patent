# -*- coding: utf-8 -*-
"""专利版走法生成（基于 DXF 几何的「射线」模型）—— 预计算表版本。

核心思路：
  - 「车」= 沿射线方向连续前进（不拐弯）→ 射线由 geometry_dxf.Board 预计算
  - 「马」= 走**传统「日」8 步**（位移 (Δr,Δc) ∈ {(±1,±2), (±2,±1)}），定义在 (行,列) **拓扑坐标**上，
          不是几何射线 → 蹩腿点 = 「走 2 格」那一方向的第一步；
           另有三角区回跳（A4↔F5 等 6 对）作为**独立条款**单独补回
  - 「象」= 沿两条不同直线各走 2 格，且不过河（落点须在本方领地）
  - 「士」= 九宫内斜走 1 格；「帅」= 九宫内横竖走 1 格
  - 「兵」= 向心前进 1 格；过河（进入对方领地）后可横走，不可后退、不可退回本方；
           到达己方营点（5-5）后可沿三角区边进入邻方营点（只过一次界）

【本版关键改动：把「几何」与「局面」彻底分离】
    踩过的坑：改前 cProfile 一次 6 plies 搜索，ray_walk / _angle / math.acos
    被调用约 40 万次、占总时长 ~30%，而它们算的全是**棋盘常量**。

    走法生成的真正变量只有两样：① 谁站在哪（board）② 谁停走（frozen）。
    棋子形状（马的 L、象的田、车的直线……）纯粹是几何，与局面无关，
    因此全部在模块载入时预计算成表（约 0.03s），运行时只做「查表 + 判空」。

    预计算表：
        RAYS[p]        车/炮：每条射线的沿途点序列
        HORSE_T[p]     马：(蹩腿点, 落点) 全部组合 = 传统「日」8 步 + 三角区回跳独立条款
        ELE_T[p]       象：(落点, 田中心, 落点所在方)
        ADVISOR[(h,p)] 士：九宫斜线相邻点（h = 归属方）
        GENERAL[(h,p)] 帅：九宫横竖相邻点
        PAWN[p]        兵：(邻点, 邻点方, 邻点行, 邻点列)
        RC[p]          p 自身的 (方, 行, 列)，取代反复 parse()
    反向攻击表（用于「是否被将军」的快速判定，见本文件末尾）：
        LINE_ATTACK[t]   能沿直线打到 t 的点 + 中间点序列（车/炮）
        HORSE_ATTACK[t]  能跳到 t 的点 + 蹩腿点
        ELE_ATTACK[t]    能飞到 t 的点 + 田中心
        SIMPLE_ATTACK[t] 兵/士/帅 一步踩到 t 的 (点, 归属方, 子种)
"""
from . import geometry_dxf as D

B = D.BOARD

# 棋盘中心 = 全部 135 点的质心（三方共享的对称中心，≈ 原点）
# 【历史遗留 · 无规则用途】它以前只被 `_leg_rank`（**已删除**的几何排序）用来判
# 「第一步是否朝向中心」。规则层改用纯拓扑后，**没有任何走法判据依赖 CENTER**。
# 保留不删，仅为可能的外部诊断脚本引用；run-time 走法生成完全不看它（零成本）。
CENTER = (sum(B.xy[p][0] for p in B.ids) / len(B.ids),
          sum(B.xy[p][1] for p in B.ids) / len(B.ids))

ROOK, HORSE, ELEPHANT, ADVISOR, GENERAL, CANNON, PAWN = (
    "rook", "horse", "elephant", "advisor", "general", "cannon", "pawn")

KIND_CN = {ROOK: "車", HORSE: "馬", ELEPHANT: "象", ADVISOR: "士",
           GENERAL: "帥", CANNON: "炮", PAWN: "兵"}
VALUE = {GENERAL: 1000.0, ROOK: 9.0, CANNON: 4.5, HORSE: 4.0,
         ELEPHANT: 2.0, ADVISOR: 2.0, PAWN: 1.0}

# 结构常量：每方 5 行 × 9 列；row5 = 最内层（前沿），col5 = 纵向中线
ROW_INNER = 5
COL_MID = 5
ROWS_TERR = 5      # 每方领地的行数
COLS_TERR = 9      # 每方领地的列数

# 常用空集（默认参数用）。定义在这里是因为 `snipe_targets` 等函数在
# 文件靠前处就要拿它当默认值 —— 原先它写在 `moves_of` 之前，会造成
# "默认参数引用尚未定义的名字"（模块载入即 NameError）。
_EMPTY = frozenset()

# ================================================================ 拓扑网格
# 马走**传统「日」8 步**。
#   UNIT_DIRS   = 网格边方向 = **4 邻域**（行 ±1、列 ±1）
#   HORSE_MOVES = 位移 (Δr,Δc) ∈ {(±1,±2), (±2,±1)}  →  恰好 8 步
#   HORSE_LEGS  = 马腿方向 u，使 mv = 2u + w（u、w 均为网格边方向）
#
# ---- 判据：**数格点数**，不是量长度、不是比夹角 ----
#   马 = 一个方向走 1 格 + 另一个方向走 2 格，两个方向各可正可负 → 8 个方向。
#   规则依据（docs/三人中国象棋的游戏规则.md §二.1 原文）：
#     「马在其它地方行进方式与传统象棋行进方式（**起、终点相对坐标**）完全相符」
#     传统象棋马的「起、终点相对坐标」就是这 8 个，与格子是 90° 还是 120° 无关。
#
# ---- 网格依据：本棋盘是 4 连通的四边形（菱形）网格 ----
#   实测每个内部点只有 **4 个邻居**（行 ±1、列 ±1）：
#     145 → {135, 155, 144, 146}；全盘 135 点中 60 个内部点**全是** 4 邻居。
#   ⚠️ 因此**不要**用「几何长度 / 夹角 / 距离公式」去推导马步：
#     这个棋盘是变形的 —— 155 处三线夹角 66.2°（非 60°）；
#     行线在列5 折角 16.31° / 29.20° / 39.41° / 47.58°；
#     邻接边长有 11.56 ~ 20.53 共 6 种。任何几何判据都会误杀。
#     (行,列) 是纯拓扑坐标 —— 只数格点。
#
# ---- 马腿 ----
#   Δ = 2u + w（u、w ∈ UNIT_DIRS），腿 = 起点 + u，
#   即「马走 2 格那一方向的正前方一格」，与传统象棋一致。
#   8 步口径下每个落点的 u 唯一 → 全盘多腿 0 个（纯拓扑，唯一性不成立即报错）。
UNIT_DIRS = ((0, 1), (0, -1), (1, 0), (-1, 0))

HORSE_MOVES = tuple((dr, dc) for dr in (-2, -1, 1, 2) for dc in (-2, -1, 1, 2)
                    if sorted((abs(dr), abs(dc))) == [1, 2])


def _horse_legs():
    """为每个「日」步求马腿方向 u（该步 = 2u + w，u、w 均为网格边方向）

    8 步口径下每个 mv 的 u **唯一**（|Δr| 与 |Δc| 一奇一偶，2u 必占掉那个偶数分量），
    所以每个落点的腿天然唯一 —— 与传统象棋「马腿只由正前方那一格决定」完全同构。
    """
    out = {}
    for mv in HORSE_MOVES:
        for u in UNIT_DIRS:
            w = (mv[0] - 2 * u[0], mv[1] - 2 * u[1])
            if w in UNIT_DIRS:
                out[mv] = u
                break
    return out


HORSE_LEGS = _horse_legs()


def _row(p):
    return D.parse(p)[1]


def _col(p):
    return D.parse(p)[2]


def _army(p):
    return D.parse(p)[0]


# ★【2026-09-24 铁律 · 规则层禁止几何判据】★★★
#   这里曾经有 `_same_angle()` / `_same_line()`（用方向角差判「共线」）。
#   它们已被**彻底删除**，因为用几何角度判「是否共线 / 是否拐弯」在本变形的
#   三方棋盘上是**错的**（本盘行线在「纵向中线 列5」处有折角 16.31°~47.58°，
#   远超 ANG_TOL=2.0°，几何会把**同一条行**判成两条不同直线）。
#   由此曾一次引爆两个 bug：① 车/炮横穿列5 被切断；② 象把「沿行多走 2 格」
#   误判成「拐弯」，产生 24 条非法象步。
#
#   老师 2026-09-24 原话：「你不要用几何去判断，我说了很多次了。」
#   ⇒ 一切「共线 / 同向 / 是否拐弯 / 腿取向 / 田中心方向」的**规则判据**，
#      一律用 **(方, 行, 列) 拓扑坐标**表达（见本文件顶部「拓扑网格」注释块）；
#      几何（`B.xy` / `_angle` / `atan2`）**只允许**出现在
#      `geometry_dxf`（坐标 → 邻接 → 射线 的基础设施）里，
#      且其产物必须由 `_splice_front_rays()` / `_splice_row_rays()` 用拓扑补正。
#   ⇒ 规则层（本文件）不得再出现 `math.atan2` / `_angle` / `ANG_TOL` 判据。
#      `tests/_verify_rays_topology.py` 第 ⑤ 节会**静态扫描**本文件，一旦复现即红灯。


# ================================================================ 预计算表
RAYS = {}          # p -> (沿途点序列1, 沿途点序列2, ...) 与 B.rays[p] 同序
HORSE_T = {}       # p -> ((蹩腿点, 落点), ...)  传统「日」8 步 + 三角区回跳（独立条款）
HORSE_LEG = {}     # p -> {落点: 允许通过的腿点元组}  「日」8 步恒 1 条（纯拓扑，>1 即报错）
ELE_T = {}         # p -> ((落点, 田中心, 落点方), ...)  专利版：卡腿只看唯一「田中心」
ADV_T = {}         # (home, p) -> (落点, ...)
GEN_T = {}         # (home, p) -> (落点, ...)
PAWN_T = {}        # p -> ((邻点, 邻点方, 邻点行, 邻点列), ...)
# ★【2026-10-01 老师新规】中心三角区三格点 = 三方各自的 row5 中点
#   （魏 A5=155 / 吴 K5=255 / 蜀 F5=355）。三点两两之间的跨方直连就是
#   `B.tri_edges`（"三角区的三条边"）。三个点的 (行,列) **恒为 (5,5)**
#   —— 全盘只有这 3 个点满足，JIT 内核据此判三角区，无需另建数组。
TRI_PTS = frozenset(B.tri.values())
SPLICE_STAT = (0, 0)   # 战线直通统计 (替换条数, 新增条数)，由 _build_tables() 填
ROW_SPLICE_STAT = (0, 0)   # 行线缝合统计 (剔除半截条数, 新增条数)，由 _build_tables() 填
RC = {}            # p -> (方, 行, 列)

# 反向攻击表
LINE_ATTACK = {}   # t -> ((点, 中间点序列), ...)   车/炮
HORSE_ATTACK = {}  # t -> ((点, 蹩腿点), ...)
ELE_ATTACK = {}    # t -> ((点, 田中心), ...)
SIMPLE_ATTACK = {}  # t -> ((点, 归属方, 子种), ...) 兵/士/帅
ATK_BY = {}        # t -> {点: ((子种, 附加信息), ...)}  ★按「我的子」查的快速版


def _pawn_homes(p, q):
    """兵站在 p 时，哪些「归属方」能让它走到 q（只看几何规则，不看棋盘）

    兵是唯一走法依赖归属方（home）的子，所以反向索引要逐个 home 试。
    【必须与 `_pawn()` 完全同构】—— 这张表喂给 `attacked()`（将军判定），
    两者不一致会导致「将军判得出来但走不了」之类的鬼故事。
    """
    pa, r0, c0 = RC[p]
    qa, qr, qc = D.parse(q)
    out = []
    for home in D.ARMIES:
        in_own = (pa == home)
        # 【2026-09-25】过河 = 跨过中心地带进入对方领地（不是「走到本方 row5」）
        crossed = not in_own
        if qa == pa:
            if in_own:
                # 本方领地：只能向心（行号递增）；不可后退、未过河不可横走
                if qr < r0 or (qr > r0 and qc != c0) or (qr == r0 and not crossed):
                    continue
            else:
                # 敌方领地：只能朝敌方底线推进（行号递减），或同行横走
                if qr > r0 or (qr < r0 and qc != c0):
                    continue
            out.append(home)
        else:
            # ★【2026-10-01】三角区回跳：任何归属方的兵都能在三点间往返。
            #   必须与 `_pawn()` 同构 —— 否则出现「将军判得出来却走不了」的鬼故事。
            if p in TRI_PTS and q in TRI_PTS:
                out.append(home)
                continue
            # 过河：从本方最内层 row5 沿**纵向路线**（底边数字和=10）正对对面 row5
            #   （列5 = 5+5 自映射 ⇒ 三角区三顶点之间也走这一条，无需另设分支）
            if not in_own:
                continue
            if r0 == 5 and qr == 5 and qc == 10 - c0:
                out.append(home)
    return out


def _tian_center(p, dest):
    """象的「田中心」= 起点→终点连线的中点所对应的那个格点

    【为什么是「中点」】
    传统象棋象走田：从 (0,0) 跨到 (2,2)，中间 (1,1) 就是田中心 ——
    它正是这条连线的**中点**（正方形格点上，中点恰好也是格点）。
    六边形棋盘同理。老师 2026-09-24 定夺：
        「象若在 113，往 135 走，田中心 124 若有子则卡腿；
          往 131 走，田中心 122 若有子则卡腿」
    实测锚点全部吻合：
        (26.01,-90.10)→(63.58,-70.08) 中点最近格点 = 122 ✅
        (26.01,-90.10)→( 0.00,-53.52) 中点最近格点 = 124 ✅

    【为什么不再用「沿折线判象眼」】
    旧口径把「象眼」定义成**起点旁边的第一格**（112 / 114 / 123），
    于是开局 112 处有己方馬、114 处有己方士，魏方的象被**自己的邻子**堵死，
    与「跨田字对角」的手感不符。田中心是跨越区域的中点，
    起点旁边的邻子本就不该影响它 —— 这才是传统象棋「塞象眼」的原义。

    【唯一性】
    全盘 276 个象步实测：首选格点与次选格点的距离差**最小 1.61**
    （格距 13~18），零并列，任何局面下都可唯一确定。
    """
    mx = (B.xy[p][0] + B.xy[dest][0]) * 0.5
    my = (B.xy[p][1] + B.xy[dest][1]) * 0.5
    best, bd = None, 1e18
    for q in B.ids:
        if q == p or q == dest:
            continue
        dx = B.xy[q][0] - mx
        dy = B.xy[q][1] - my
        d = dx * dx + dy * dy
        if d < bd:
            bd, best = d, q
    return best


def _triangle_rebound(p):
    """三角区回跳 —— 马的**独立特殊条款**，不属于「马走日」的常规走法

    【唯一依据】规则原文（`docs/三人中国象棋的游戏规则.md` §二.1，逐字）：
        A5 处没有棋子时，A4 到 F5 可来回跳、A6 到 K5 可来回跳；
        F5 处没有棋子时，F4 到 K5 可来回跳、F6 到 A5 可来回跳；
        K5 处没有棋子时，K4 到 A5 可来回跳、K6 到 F5 可来回跳；
        马在其它地方行进方式与传统象棋行进方式（起、终点相对坐标）完全相符。

    这段话是**两个并列的条款**：
      · 「马在其它地方……与传统象棋……完全相符」→ 常规马步走传统「日」8 步
        （定义在 (行,列) 相对坐标上，见本文件顶部「拓扑网格」注释块）
      · 「三角区特定的回跳点位规则」→ 上面 6 对是**例外**，必须在这里单独补回来。

    【实现口径：原文穷举 —— 不推导、不扩档、不算几何】
    ⚠️ 原文给的就是 **6 对 / 双向 12 个方向**，照抄即可。判据只有一条：
       起点必须是「本方 row5 且引擎列 ∈ {4, 6}」。
    ⚠️ 本棋盘是**变形网格**（相邻点格距 13~24 不等），**几何长度 / 夹角没有判据意义**：
       A4(156) 到本应对面的 F5(355) 距离 47.47，反倒比到"几何更近"的 K5(255) 的
       33.93 更远 —— 若拿距离当判据，必然把 6 对全部判反。
       （老师 2026-09-24 明确：不算距离，以原文穷举为准。）

    【标签 -> 引擎编号】字母 = 行（每方 row5 = A/F/K，row1 = E/J/O）；
    底边数字 = 纵线，且 **图中数字 d = 10 - 引擎列**。依据是棋盘原图标签的物理位置：
    魏底边的「1」贴在左下角（最左），而引擎里魏 row1 的列 9 在最左 → 数字 1 = 列 9。
    于是：  A4=156  A5=155  A6=154    F4=356  F5=355  F6=354    K4=256  K5=255  K6=254

    【为什么蹩腿点是本方 row5 中点】
    原文每个分句的前半都是「X5 处没有棋子时」——X5 正是**起点那一方**的 row5 中点：
      · "A5 处没有棋子时，A4 到 F5 / A6 到 K5"   → 起点 A4/A6 都在魏，腿 = A5
      · "F5 处没有棋子时，F4 到 K5 / F6 到 A5"   → 起点 F4/F6 都在蜀，腿 = F5
      · "K5 处没有棋子时，K4 到 A5 / K6 到 F5"   → 起点 K4/K6 都在吴，腿 = K5
    所以 `m = D.pid(起点方, ROW_INNER, COL_MID)`，不需要额外参数。
    这也意味着**同一方的两条回跳共用一条腿**：堵住 A5，A4→F5 与 A6→K5 同时被蹩。

    【6 对 = 三方 120° 旋转对称】
    每方 2 对（列 4 与列 6），三方共 6 对；每对"可来回跳"→ 双向，合计 12 个方向。
    落到 REBOUND 表上是 9 个起点（3 个中点各带 2 条）。

    返回 ((蹩腿点, 落点), ...)，格式与常规条款一致。
    """
    a, r, c = D.parse(p)
    if r != ROW_INNER or (a, c) not in _REBOUND_SELF:
        return []
    m = D.pid(a, ROW_INNER, COL_MID)      # 蹩腿点 = 本方 row5 中点（原文的「X5」）
    return [(m, D.pid(_REBOUND_SELF[(a, c)], ROW_INNER, COL_MID))]


# 三角区回跳表 = **原文 6 对穷举**，按「(起点方, 起点列) -> 落点方的 row5 中点」记账。
# 键里的 c 是**引擎列**（图中数字 d = 10 - 列，见函数 docstring 的「标签 -> 引擎编号」）。
# 每对「可来回跳」，反方向由 _build_rebound() 补出。
#
# ⚠️ 不要扩档、不要推导：原文就 6 对，列 3 / 列 7 等**不在**原文里。
# ⚠️ 这 6 对的落点方与"几何上更近的那个邻方"**恰好相反**——原文要的就是这个穷举结果。
#    曾误用「距离 / 转角」去"纠正"它，方向刚好判反（老师 2026-09-24 指出）。
_REBOUND_SELF = {
    (1, 6): 3,      # 魏 A4(156) <-> 蜀 F5(355)   腿 A5(155)
    (1, 4): 2,      # 魏 A6(154) <-> 吴 K5(255)   腿 A5(155)
    (3, 6): 2,      # 蜀 F4(356) <-> 吴 K5(255)   腿 F5(355)
    (3, 4): 1,      # 蜀 F6(354) <-> 魏 A5(155)   腿 F5(355)
    (2, 6): 1,      # 吴 K4(256) <-> 魏 A5(155)   腿 K5(255)
    (2, 4): 3,      # 吴 K6(254) <-> 蜀 F5(355)   腿 K5(255)
}


def _build_rebound():
    """把 6 对展开成双向表：p -> ((腿, 落点), ...)

    每对 (起点 x, 中点 m, 落点 y) 同时给出 x->y 与 y->x 两条（原文"可来回跳"）。
    两个方向的蹩腿点都是 m（即原文里的"X5"）。
    """
    tbl = {}
    for (a, c), b in _REBOUND_SELF.items():
        m = D.pid(a, ROW_INNER, COL_MID)
        x = D.pid(a, ROW_INNER, c)
        y = D.pid(b, ROW_INNER, COL_MID)
        tbl.setdefault(x, []).append((m, y))
        tbl.setdefault(y, []).append((m, x))
    return {k: tuple(v) for k, v in tbl.items()}


REBOUND = _build_rebound()


# ================================================================ 战线直通（车 / 炮）
# 【老师规则 2026-09-24】「凡是自己底边对应的数字与对面的数字相合为10 就代表共线」
#   → 本方的「底边数字 n」纵线，与对面方的「底边数字 10-n」纵线 **是同一条线**。
#     例：吴方 M6（图数字 6）= 吴行3列4，其纵线对面就是魏方的「图4线」（魏行?列6）。
#
# 【原图为什么看不出来】老师原话：「他们战线上是不画线的吧」——
#   原图每方的纵线只画到自己的「最内层 row5」为止，中间那条「战线」不画线。
#   实测证据（把 DXF 的 51 条线合并成 66 条无限直线后统计）：
#     · 真正连成一整条的跨方直线只有 3 条，正是「图1 ↔ 图9」那三对
#       （魏列1↔蜀列9、魏列9↔吴列1、吴列9↔蜀列1），最大偏离直线 = 0.000；
#     · 其余 9 条接线（列2/3/4 ↔ 对面列8/7/6，以及 列6/7/8 ↔ 对面列4/3/2）
#       在 DXF 中**根本不存在**——把两半强行当一条直线，最大偏离 27.4 ~ 39.2，
#       而相邻格距只有 11 ~ 20 → 它们是**规则共线**，不是几何共线。
#
# 【本段做什么】按数字规则把「本方纵线（行1→行5） + 对面纵线（行5→行1）」拼成
#   一条**贯通纵线**，再把这半截射线（走到 row5 就断）替换成长版本。
#   只影响走射线的 **车 / 炮**；马 / 象 / 士 / 帅 / 兵 仍走原几何，完全不受影响。
FRONT_NEXT = {1: 3, 2: 1, 3: 2}     # 本方「列1 端」面对的方：魏列1↔蜀列9、吴列1↔魏列9、蜀列1↔吴列9


def _front_partner(a, c):
    """(方, 引擎列) → 该纵线在战线另一侧属于哪一方；列5 = 三角区顶点，返回 None"""
    if c < COL_MID:
        return FRONT_NEXT[a]
    if c > COL_MID:
        for k, v in FRONT_NEXT.items():
            if v == a:
                return k
    return None


def _cross_sides(a, c0):
    """朝中心方向**越过本方 row5（过河）**后进入哪一方 —— 马也走这条路。

    依据（老师已确认的「过河接线：数字和恒为 10」）：
      本方「行5 列c」朝中心的过河方向，逐点镜像命中对面「行5 列(10−c)」。
      ⇒ 整条**纵线**（列 c）属于哪一方，与所在行无关 → 判据取**起点列 c0**。

    · c0 < 5 → FRONT_NEXT[a]（例：魏列1..4 接蜀）
    · c0 > 5 → 反查（例：魏列6..9 接吴）
    · c0 = 5 → 三角区三岔点，**两个对面都接**
      （与 `_front_lanes()` 对 `c == COL_MID` 取 `所有对方` 的处理完全一致）
    """
    b = _front_partner(a, c0)
    return (b,) if b else tuple(x for x in D.ARMIES if x != a)


def _front_lane(a, c, b):
    """贯通纵线 = [本方 行1..行5] + [对面 行5..行1]；有点不在盘上则返回 None"""
    own = [D.pid(a, r, c) for r in range(1, ROWS_TERR + 1)]
    oth = [D.pid(b, r, 2 * COL_MID - c) for r in range(1, ROWS_TERR + 1)]
    if any(p not in B.ids for p in own + oth):
        return None
    return own + oth[::-1]


def _front_lanes():
    """全部贯通纵线（含重复生成，由 _splice_front_rays 去重）"""
    out = []
    for a in D.ARMIES:
        for c in range(1, COLS_TERR + 1):
            bs = [b for b in D.ARMIES if b != a] if c == COL_MID else [_front_partner(a, c)]
            for b in bs:                                      # 列5 = 三角区顶点，接两个对面
                ln = _front_lane(a, c, b)
                if ln:
                    out.append((a, c, b, ln))
    return out


def _splice_front_rays():
    """把贯通纵线接进 RAYS：半截射线（走到 row5 断掉）→ 长射线

    返回 (替换条数, 新增条数) 供自检打印。
    """
    rep = add = 0
    done = set()
    for _a, _c, _b, lane in _front_lanes():
        key = tuple(sorted(lane))                # 同一条贯通线两侧各生成一次 → 去重
        if key in done:
            continue
        done.add(key)
        for i, p in enumerate(lane):
            fwd = tuple(lane[i + 1:])            # 朝另一端（跨战线那一侧）
            back = tuple(lane[:i][::-1])         # 朝起点端
            keep = []
            hit_f = hit_b = False
            for path in (RAYS.get(p) or ()):
                path = tuple(path)
                if not hit_f and fwd and path == fwd[:len(path)]:
                    keep.append(fwd)
                    hit_f = True
                    rep += 1
                    continue
                if not hit_b and back and path == back[:len(path)]:
                    keep.append(back)
                    hit_b = True
                    rep += 1
                    continue
                keep.append(path)
            if fwd and not hit_f:
                keep.append(fwd)
                add += 1
            if back and not hit_b:
                keep.append(back)
                add += 1
            RAYS[p] = tuple(keep)
    return rep, add


def _row_lanes():
    """每方每一行 = 「(方, 行, 列1..9)」，共 15 条（3 方 × 5 行）"""
    out = []
    for a in D.ARMIES:
        for r in range(1, ROWS_TERR + 1):
            ln = [D.pid(a, r, c) for c in range(1, COLS_TERR + 1)]
            if all(p in B.ids for p in ln):
                out.append(ln)
    return out


def _splice_row_rays():
    """把每方每一行（列1..9）缝成**一条完整行线** —— 车 / 炮必须能沿行横穿列5。

    【老师 2026-09-24 深夜报的】「魏国位于 C2 的炮试图移到 C6 或 C7 —— 它同样属于 C 这一行」
      实测：`138`(C2) 的合法着法只有 `137/136/135`(C3/C4/C5)，
      **到不了同行的 `134`(C6) / `133`(C7)**。

    【根因】**不是规则问题，是几何判定越界使用了**：
      本盘是**变形网格**，内部行线在「纵向中线 列5」处有**折角**（实测 16.31° / 29.20° /
      39.41° / 47.58° —— 老师早前已核实过这个几何事实，见 `tests/_verify_rows.py`：
      「只有 E/J/O（行1）是直线，其余行在列5 处有拐点」）。
      而射线是靠**角度**分组的（`ANG_TOL = 2.0°`），装不下这个折角
      → 每条内部行被**切成两段**。实测受影响 **12 条**（三方 × row2~row5；
      row1 在最外圈是直边，不受影响）。列方向全部完好。

    【修法】行是**拓扑**概念（`(方, 行, 列±1)`），不该由几何角度决定。
      像 `_splice_front_rays` 处理跨方纵线那样手工缝回来：
      对行上每个点，**先剔除**原先把它切开的半截射线（`set(walk) ⊆ 该行`），
      再补上「朝两端」的两条完整射线 —— 不会重复，也不会残留半截。

    ⚠️ **不能靠放宽 `ANG_TOL` 解决**：折角最大 47.58° > 不同方向族的最小夹角 35.412°，
      一放宽就会把「行」和「列」并成同一条射线（车会斜着走），错得更离谱。

    返回 (剔除的半截条数, 新增条数) 供自检打印。
    """
    rep = add = 0
    for lane in _row_lanes():
        rowset = set(lane)
        n = len(lane)
        for i, p in enumerate(lane):
            fwd = tuple(lane[i + 1:])                 # 朝「列大」那端
            back = tuple(lane[:i][::-1])              # 朝「列小」那端
            keep = []
            for w in (RAYS.get(p) or ()):
                if set(w) <= rowset:                  # 半截行射线 → 丢掉，下面统一补
                    rep += 1
                    continue
                keep.append(w)
            if fwd:
                keep.append(fwd)
                add += 1
            if back:
                keep.append(back)
                add += 1
            RAYS[p] = tuple(keep)
    return rep, add


def _is_tent_diag(a, b):
    """`a → b` 是不是「军帐米字斜线」的一步 —— **纯拓扑判据，一个角度都不碰**

    【老师 2026-10-01 报的 bug】
      「车在米字格魏国军帐内为何能走斜线去吃魏国的帅？不对的。」

    【根因】军帐（九宫）在几何上是**米字格**：中心点有 8 个邻接点 ⇒
      `Board._build_rays()` 按**角度**分组时，除了横竖两族，还额外产出
      4 条**斜向射线**（通向九宫四角，如 D5 → E4 / E6 / C4 / C6）。
      而 `_rook` / `_cannon` / `PAWN_T` / `LINE_ATTACK` 全都消费 `RAYS`
      ⇒ **车、炮都获得了斜走能力**，攻击表也跟着多出一批斜向威胁。
      斜线本是**士**的走法（`ADV_T` / `B.gong_diag`），不该混进通用射线。

    【判据】同一方内部，**行与列同时发生变化**：
      · 方不变 ＋ 行变 ＋ 列变   ⇒ 军帐斜线（全盘实测 **24 步**，无一例外）
      · **方变**（跨方接线 / 战线直通）⇒ 放行 —— 那一步的形态是
        (方变, 行不变, 列变)，**不会**行列同变
      · 方不变 ＋ 只变一个分量   ⇒ 正常行线 / 列线

    ⚠️ 不能用「两个分量同时变」当判据：跨方接线（如 `A4 156 → K6 254`）
       也是两个分量同时变，那样会把**合法的贯通线**一起砍掉。
       必须先看**方**是否变。
    """
    if a[0] != b[0]:
        return False                     # 跨方 → 不是军帐斜线
    return a[1] != b[1] and a[2] != b[2]


def _drop_tent_diag(p, walk):
    """把一条射线沿途序列在**军帐斜线**处截断（斜线不是直线走法，不能延伸）"""
    cur = D.parse(p)
    out = []
    for q in walk:
        qa = D.parse(q)
        if _is_tent_diag(cur, qa):
            break
        out.append(q)
        cur = qa
    return tuple(out)


def _build_tables():
    # ---------- 单向表 ----------
    for p in B.ids:
        pa, r0, c0 = D.parse(p)
        RC[p] = (pa, r0, c0)
        rays = B.rays.get(p) or ()
        # ★ 剔除**军帐米字斜线**（老师 2026-10-01 报的「车在军帐内斜走」）：
        #   几何分组产出的斜向射线不是直线走法，斜线只有「士」走（走 ADV_T）。
        #   必须在这里（**所有缝合之前**）过滤 —— 缝合函数会把未过滤的斜线
        #   原样保留下来（`_splice_row_rays` 只丢"整条落在同一行内"的半截行射线）。
        #   过滤掉空序列：`_splice_front_rays()` 用 `path == fwd[:len(path)]`
        #   匹配半截射线，空 tuple 会**无条件命中**（`fwd[:0] == ()`）⇒ 误算替换数。
        RAYS[p] = tuple(w for w in (_drop_tent_diag(p, r.walk) for r in rays) if w)
        PAWN_T[p] = tuple((q, *D.parse(q))
                          for r in rays for q in (r.nbrs[0],))

        # 马走**传统「日」8 步** —— 定义在 **(行,列) 拓扑坐标** 上：
        #   位移 (Δr,Δc) ∈ {(±1,±2), (±2,±1)} → 恰好 8 步
        #   蹩腿点 = 沿「走 2 格」那一方向的第一步（mv = 2u + w，u 即腿方向），
        #   与传统象棋「马腿在马正前方那一格」一致。
        #
        #   腿唯一性：8 步口径全盘**多腿 0 个**，与传统象棋同构（纯拓扑，无几何兜底）。
        #
        # ★【2026-09-24 深夜修 · 老师报的「魏国的马不会过河」】
        #   旧写法把落点**硬锁在本方领地**（`1 <= r2 <= ROWS_TERR`），于是马一走到
        #   row4/row5，所有朝中心方向（r2 > 5）的步子被整条砍掉 —— 全盘 **162 条**
        #   候选（54 个起点 × 3）静默失效，表现就是「马永远跳不过河」。
        #   传统象棋**马是可以过河的**（只有象/士不过河），规则图第 1 条最后半句
        #   「马在其它地方行进方式与传统象棋行进方式完全相符」也照此解释。
        #   ⇒ r2 > ROWS_TERR 时改走**过河分支**：落点落在对面领地里。
        #
        #   过河落点怎么算 —— 复用老师已确认的「过河接线：数字和恒为 10」：
        #     把 (行,列) 读成世界坐标 (t,u)：
        #       t = 距本方底线的格数（本方 1..5；过河后 6..10 = 对面 row5..row1）
        #       u = 列（本方列 c 与对面列 10−c 是世界上的同一条线）
        #     ⇒ 对面行 = 11 − r2，对面列 = 10 − c2
        #     马腿若也落在河外，同样按这一方映射（对面 row5）。
        hs = []
        for mv in HORSE_MOVES:
            r2, c2 = r0 + mv[0], c0 + mv[1]
            u = HORSE_LEGS[mv]
            if not (1 <= c2 <= COLS_TERR):
                continue                             # 越出六边形左右外边界 → 该步不成立
            if r2 < 1:
                continue                             # 越过本方底线 → 棋盘外
            if r2 <= ROWS_TERR:                      # ---- 本国领地内 ----
                dest = D.pid(pa, r2, c2)
                if dest not in B.ids:
                    continue
                leg = D.pid(pa, r0 + u[0], c0 + u[1])    # 马腿 = 走 2 格方向的第一步
                hs.append((leg, dest))
                continue
            # ---- 越过本方 row5 = 过河 → 落点在对面领地 ----
            # ★【2026-09-25 第二轮 · 老师报「马应该不能从 A6 到 K6，你为何会允许」】
            #   马过河时**不得跨过本方的中线 col5** —— 起点列 c0 与落点列 c2
            #   必须在本方中线的**同一侧**（恰落在中线上也算同侧）。
            #
            #   规则依据（不需要几何，纯接线表）：规则图的「过河接线」是
            #   **一对一**的 —— 底边数字和恒为 10，**一条纵线只通向一个对面**
            #   （§二.2 的三组边对：魏列6..9↔吴列1..4、魏列1..4↔蜀列6..9）。
            #   日字步的「横移 2 格」若跨过中线，就等于
            #   「**先换到另一条接线，再沿新接线过河**」—— 一步同时用了两条接线，
            #   落点落在起点列**并不面对**的那一方领地里，规则里没有依据。
            #
            #   实测（见 tests/_verify_horse_cross.py §10）：
            #     · 加上这一条后马表**单向步 = 0 条**（完全可逆，与传统象棋一致）；
            #     · 120° 旋转对称**0 处破坏**；
            #     · 删掉的正是上一版残留的 6 条「3-环单向步」，
            #       含老师指出的 `A6(154) → K6(254)`
            #       （`A4(156)→F4(356)`、`K6(254)→F6(354)`、`K4(256)→A4(156)`、
            #         `F6(354)→A6(154)`、`F4(356)→K4(256)`），且**无新增**。
            #   注：c0 = 5（起点在本方中线上）时不构成"跨"，两个对面都可达 ——
            #       这正是老师 2026-09-24 让 `156→245 吃吴兵` 成立的那条路。
            if (c0 - COL_MID) * (c2 - COL_MID) < 0:
                continue
            lr, lc = r0 + u[0], c0 + u[1]
            # ★【2026-09-25 铁律 · 马步必须可逆（老师报「马不能从 L5 到 F4」）】
            #   落点方必须由**落点所在列 c2** 决定，**不是**起点列 c0。
            #
            #   为什么：纵向通道 `_front_lane(a, c)` 的对面方是 `_front_partner(a, c)`
            #   ——「本方列 c 的整条纵线通向哪一方」。**车/炮沿列直走**（c2 ≡ c0），
            #   所以用起点列还是落点列都一样；**但马步会改列**（Δc = ±1/±2），
            #   再用起点列就把"落点所在的那条纵线"张冠李戴了。两处后果：
            #     ① c0 = 5（本方中线 = 三角区三岔）时 `_cross_sides` 把**两个对面
            #        都接上** ⇒ 凭空多给一半落点：吴 L5(245) 走 (2,−1) 本应只到
            #        魏 A4(156)，却把蜀 F4(356) 也生成出来（实测 245→356 的物理
            #        距离 65.30，是正常跨方马步 44.40 的 1.47 倍 —— 它根本不该存在）。
            #     ② 反向落点查不到（那条步是从"另一条纵线"长出来的）
            #        ⇒ 全盘 **30 条单向马步**（传统象棋马步必然可逆，同方内部 0 条）。
            #
            #   落点列恰在本方中线（c2 = COL_MID）时，c2 自己分不出左右，
            #   退回用**起点列 c0**：横向位移的方向本就由 c0→c2 决定
            #   （从 6 侧进中线落在魏侧通道、从 4 侧进中线落在吴侧通道）。
            #   c2 = c0 不可能（日字步 Δc ≠ 0），故两者必有一可用。
            #   （再加上上面那条「不得跨中线」的约束后，跨方马步已 **100% 可逆**。）
            for pb in _cross_sides(pa, c2 if c2 != COL_MID else c0):
                dest = D.pid(pb, 11 - r2, 10 - c2)
                if dest not in B.ids:
                    continue
                leg = (D.pid(pa, lr, lc) if 1 <= lr <= ROWS_TERR
                       else D.pid(pb, 11 - lr, 10 - lc))   # 腿也过河 → 对面 row5
                hs.append((leg, dest))
        # ★ 三角区回跳是马的**独立条款**（说明书："A5 无子时 A4 与 F5 可来回跳"），
        #   它是**跨方**的走法，(行,列) 拓扑坐标表达不了，必须单独补回。
        #   ⚠️【2026-09-25 修 · 用 REBOUND（双向表），不用 _triangle_rebound】
        #     原文 6 对全部写的是「可**来回**跳」⇒ 每个方向都是**双向**，
        #     落到表上是 **9 个起点**（6 个列4/6 点 + 3 个中点各带 2 条）。
        #     旧写法用 `_triangle_rebound(p)`，它只认 `_REBOUND_SELF` 的 6 个键
        #     ⇒ **中点（A5/K5/F5）的反向一条都没生成**，6 对里 6 个方向静默失效：
        #       实测 `A4(156)->F5(355)` 有、`F5(355)->A4(156)` 没有（6 条单向）。
        #     `REBOUND` 表本来就是照着"可来回跳"建的（x->y 与 y->x 各一条，
        #     两个方向共用同一条腿 m = 原文的「X5」），直接用它即可。
        hs.extend(REBOUND.get(p, ()))
        HORSE_T[p] = tuple(hs)

        # 腿表：p -> {落点: 允许通过的腿点元组}
        #   「日」8 步口径下**每个落点的腿天然唯一**（mv = 2u+w 的 u 唯一，实测全盘多腿 0.0%）。
        #
        # ★【2026-09-24 铁律 · 规则判据禁止几何】
        #   这里原来还有一支 `sorted(_legs, key=lambda _l: _leg_rank(p, _l))` 的
        #   **几何兜底**：万一某落点出现多条腿，就按「第一步与棋盘中心夹角更小者」排序，
        #   夹角相同则「任一腿通」。这条兜底**已删除**，因为：
        #     ① 老师 2026-09-24：「你不要用几何去判断，我说了很多次了。」
        #     ② 它会把**拓扑上的 bug 悄悄掩盖**（几何随手挑一条腿，走法照样生成，
        #        但可能是错的，且不可复现）。正确做法是**让不唯一直接报错**。
        #   下面改用 `set` 去重（同一腿可能由常规条款与三角区回跳各算一次），
        #   去重后仍 >1 条 ⇒ 抛 AssertionError 暴露 —— 「日」8 步下这永不发生，
        #   一旦发生必是拓扑表本身写错（HORSE_MOVES / _horse_legs / 过河映射）。
        _by_dest = {}
        for _leg, _dest in hs:
            _by_dest.setdefault(_dest, set()).add(_leg)
        HORSE_LEG[p] = {}
        for _dest, _legs in _by_dest.items():
            _uniq = tuple(sorted(_legs))
            if len(_uniq) != 1:
                raise AssertionError(
                    "马腿拓扑不唯一（这是拓扑表构建 bug，不要用几何兜底）: "
                    f"起点 {p} 落点 {_dest} 候选腿 {_uniq}")
            HORSE_LEG[p][_dest] = _uniq                 # 「日」8 步下恒 1 条腿

        # 象：走「田字对角」—— 落点与田中心**完全用拓扑** (±2,±2) / (±1,±1) 枚举，
        #     一个射线都不碰。卡腿只看**田中心**，按落点天然唯一。
        #
        # ★【2026-09-24 深夜 · 第二轮修复（比"改判据"更根本）】
        #   旧实现 `for ray1 in rays`（rays = B.rays，**几何**射线）+「两段各走 2 格 +
        #   判是否拐弯」。这条路上有两个**独立**的坑：
        #     坑A（上一轮以为修好了）：「是否拐弯」曾用几何角度 `_same_line(ray1.dir,
        #       ray2.dir)`。列5 折角（16.31°~47.58°）让它把"沿行再走 2 格"误判成
        #       "拐弯" ⇒ 生出 Δ=(0,4) 非法步（`123 → 127`）。
        #     坑B（本轮才发现，**光改判据治不好**）：**几何射线在「跨方接缝」处方向突变**。
        #       例：魏列1 的射线 walk = `('131','141','151','359','349',…)` ——
        #       151(魏E1) → 359(蜀E9) 是**斜跳**（底边"数字和=10"接线，不是网格边）。
        #       于是 `p→mid` 是纵、`mid→dest` 是**斜**（拓扑上既不同行也不同列），
        #       判据 `(False,True) != (False,False)` 照样放行 ⇒ 产生**跨方飞象**
        #       （实测 `141 → 359` 这类，全盘 **48 条**，且只在魏方那几条跨方纵线上）。
        #   ⇒ 结论：象的落点必须**纯拓扑枚举**。射线（几何的或缝合后的）都带着
        #     「接缝处方向突变」的噪声，**不能**用于"两格 + 拐弯"这类**形状**判定。
        #   规则依据：规则图《一》原句「象走格子交点，不存在射线；田中心有子就卡腿，
        #     不能跨到田字对角」。老师铁律：「你不要用几何去判断，我说了很多次了。」
        es = []
        for _dr, _dc in ((-2, -2), (-2, 2), (2, -2), (2, 2)):
            _r2, _c2 = r0 + _dr, c0 + _dc
            if not (1 <= _r2 <= ROWS_TERR and 1 <= _c2 <= COLS_TERR):
                continue                        # 越界 / 过河（象不过河）
            _dest = D.pid(pa, _r2, _c2)
            if _dest not in B.ids:
                continue
            _eye = D.pid(pa, r0 + _dr // 2, c0 + _dc // 2)   # 田中心 = 拓扑中点
            # 自检：拓扑中点必须与老师定夺的「几何中点最近格点」一致。
            # 实测全盘 228 步零分歧；若不一致，说明棋盘形变到"拓扑中点偏离格点"，
            # 必须报警（而不是悄悄用一个口径）。
            _geo = _tian_center(p, _dest)
            if _eye != _geo:
                raise AssertionError(
                    f"田中心拓扑口径与几何口径不一致: {p}→{_dest} "
                    f"拓扑 {_eye} 几何 {_geo}")
            es.append((_dest, _eye, pa))
        ELE_T[p] = tuple(es)

    # 车 / 炮：按「底边数字和=10」把 9 条**图上没画**的战线接线接进射线表
    # （必须在下面「反向攻击表」之前跑——那里要按接好的 RAYS 登记 LINE_ATTACK）
    global SPLICE_STAT, ROW_SPLICE_STAT
    SPLICE_STAT = _splice_front_rays()
    # 每方每一行（列1..9）：在本变形网格上**不是**几何直线（列5 处折角 16.31°~47.58°，
    # 远超 ANG_TOL=2.0°）→ 几何建射线时被切成两段，车/炮**横穿不了列5**。
    # 行是**拓扑**概念，必须手工缝回来（详见 `_splice_row_rays`）。
    ROW_SPLICE_STAT = _splice_row_rays()

    # ★【2026-09-25 修 · 老师报的「魏兵在 A7 过不了祁山」】
    #   上面第 492 行生成 PAWN_T 时，`B.rays[p]` 还是**没接线**的原始射线，
    #   于是兵只认得「图上真画出来」的跨方通道（斜边 6 条 + 三角区 3 条，
    #   共 9 个 row5 点），而 `_splice_front_rays()` 按「底边数字和=10」补出来的
    #   那 18 条跨方纵线**一条都没进兵的表** ——
    #   表现：车/炮/马都能沿纵线过河，**只有兵不能**（A7 的兵只能左右挪）。
    #   老师 2026-09-25 口径：「兵没过河（没过地带）之前不能横走」+
    #   「往前 = 过地带，到对面 row5 的对应列」⇒ 兵必须看到**接线后**的 RAYS。
    #   在 row5 上，「每条射线的第一个点」正好就是「沿纵向路线过河的那一格」。
    for _p in B.ids:
        _seen_ = set()
        _lst_ = []
        for _ray in RAYS.get(_p, ()):
            if not _ray:
                continue
            _q = _ray[0]
            # 接线/缝合可能让两条射线的**首点重合**（实测如 115 的 125 出现两次），
            # 必须去重，否则兵的落点表会带重复项（`test_dxf.py` 有"落点无重复"自检）。
            if _q in _seen_:
                continue
            _seen_.add(_q)
            _lst_.append((_q, *D.parse(_q)))
        PAWN_T[_p] = tuple(_lst_)

    # 士 / 帅（按归属方分开：收编后 home 与所在领地可能不同）
    for home in D.ARMIES:
        gong = set(B.gong[home])
        for p in B.ids:
            ad = []
            for diag in B.gong_diag[home]:
                if p in diag:
                    i = diag.index(p)
                    for j in (i - 1, i + 1):
                        if 0 <= j < len(diag):
                            ad.append(diag[j])
            ADV_T[(home, p)] = tuple(ad)

            gd = []
            _, r0, c0 = D.parse(p)
            for ray in B.rays.get(p) or ():
                q = ray.nbrs[0]
                if q not in gong:
                    continue
                _, qr, qc = D.parse(q)
                if (abs(qr - r0) == 1 and qc == c0) or (qr == r0 and abs(qc - c0) == 1):
                    gd.append(q)
            GEN_T[(home, p)] = tuple(gd)

    # ---------- 反向攻击表 ----------
    # 「谁能打到 t」：把上面的正向表倒过来索引，避免叶节点里逐个棋子试走法。
    # 中间点序列/象眼/蹩腿点也一并存下，判空即可确认，无需再生成着法。
    def _add(tbl, t, item):
        lst = tbl.get(t)
        if lst is None:
            tbl[t] = [item]
        else:
            lst.append(item)

    # 按「目标点」倒排（外面那层是 t，里面那层是 p）—— 供 under_attack 候选驱动使用
    atk_by = {}

    def _ab(t, pos, item):
        d = atk_by.get(t)
        if d is None:
            atk_by[t] = {pos: [item]}
            return
        lst = d.get(pos)
        if lst is None:
            d[pos] = [item]
        else:
            lst.append(item)

    for p in B.ids:
        for w in RAYS.get(p) or ():          # 用接好「战线直通」的 RAYS（不是 B.rays）
            for i, t in enumerate(w):
                _add(LINE_ATTACK, t, (p, w[:i]))
                _ab(t, p, (ROOK, w[:i]))
                _ab(t, p, (CANNON, w[:i]))
        for leg, dest in HORSE_T[p]:
            if dest == p or leg not in HORSE_LEG.get(p, {}).get(dest, ()):
                continue                        # 只登记允许的腿（与走法生成同口径）
            _add(HORSE_ATTACK, dest, (p, leg))
            _ab(dest, p, (HORSE, leg))
        for dest, tian, da in ELE_T[p]:
            _add(ELE_ATTACK, dest, (p, tian))
            _ab(dest, p, (ELEPHANT, (tian, da)))        # 象不过河：落点须在归属方领地
        for q, _qa, _qr, _qc in PAWN_T[p]:
            for home in _pawn_homes(p, q):
                _add(SIMPLE_ATTACK, q, (p, home, PAWN))
                _ab(q, p, (PAWN, home))
        for home in D.ARMIES:
            for q in ADV_T[(home, p)]:
                _add(SIMPLE_ATTACK, q, (p, home, ADVISOR))
                _ab(q, p, (ADVISOR, home))
            for q in GEN_T[(home, p)]:
                _add(SIMPLE_ATTACK, q, (p, home, GENERAL))
                _ab(q, p, (GENERAL, home))

    for tbl in (LINE_ATTACK, HORSE_ATTACK, ELE_ATTACK, SIMPLE_ATTACK):
        for k in tbl:
            tbl[k] = tuple(tbl[k])
    for t, d in atk_by.items():
        ATK_BY[t] = {p: tuple(v) for p, v in d.items()}


_build_tables()


# ================================================================ 落点判定
def _can_land(board, army, frozen, q):
    """能否落到 q：空点可；敌子可（除非对方停走，其子不可被吃）；己子不可"""
    t = board.get(q)
    if t is None:
        return True
    if frozen and t["army"] in frozen:              # 停走方的子不可被吃
        return False
    return t["army"] != army


def snipe_targets(board, pos, army, frozen=_EMPTY):
    """帅 / 副帅的【射杀】目标 —— 沿见面线照见到的**对方帅 / 副帅**

    【大规则 · 老师 2026-09-25 定夺】
      原始提问：「魏国控制的副帅已经照见 I5 的主帅，并且这时轮到魏国走，
                 为何魏国控制的副帅不能射杀 I5 的主帅」
      老师确认的新规则（四问四答）：
        · **谁**：主帅与副帅都能射杀（出局方那枚"就地变色"的副帅同样有这能力）
        · **打谁**：**只能**射杀对方的「帅 / 副帅」（普通棋子打不动，视作被挡）
        · **旧条款**：废除《一、9》「禁止照面」+《一、10》「被动见面判负」，
          改为「**轮到谁，谁能吃**」—— 照面从"违规禁忌"变成"互为人质"的战术关系
        · **线路**：沿**见面线**（规则图那六条跨方贯通线，两两对称于列4/5/6）

    【实现为什么是"扫 RAYS 的第一个子"就够】
      `RAYS` 里每方自己的**行线 / 军帐斜线**都不跨方 ⇒ 扫到底也遇不到别方的帅；
      只有**跨方贯通线**才可能把两个帅串起来。于是"沿 RAYS 扫描、第一个子若是敌帅"
      **精确等价于**"两点共线且中间无子（= 照见）且终点是敌帅"。
      这正是 `line_of_sight()` 的口径 —— 二者互为充要条件（见 tests/_verify_snipe.py §4）。

    【判据必须纯拓扑】同 `_row_lanes` / `_splice_row_rays` 的教训：本盘行线在列5 有折角、
      跨方处方向突变，任何基于几何角度的"是否共线"都会把贯通线切断。
      这里**一个角度都不碰**：只按 RAYS（已由拓扑缝合补正）走点序。

    扫描规则（三个分支，与「照见」逐字对应）：
      · 空点          → 继续延伸（中间无子才可能照见）
      · 第一个子=敌帅 → **射杀**（记入 out）
      · 其余（己方子 / 敌方普通子）→ 该方向被挡死，`break`

    与 `_rook` 的区别：车是"遇子止步"（走到该子前一格），帅是"遇子判定"（够得着直接吃）。
    """
    out = []
    seen = set()
    for path in RAYS.get(pos) or ():
        for q in path:
            t = board.get(q)
            if t is None:
                continue                    # 空点：视线继续延伸
            if (t["kind"] == GENERAL and t["army"] != army
                    and not (frozen and t["army"] in frozen)
                    and q not in seen):
                seen.add(q)
                out.append(q)               # ★ 射杀：照见即可吃
            break                           # 第一个子 —— 射杀或被挡，本方向到此为止
    return out


# ================================================================ 各子走法
def _rook(board, pos, home, army, frozen):
    """车：沿射线直行，遇子止步。

    注：三角区顶点（各方 row5-5）的纵线在顶点处**分成两支**
    （分别接另两方的 row5-5），两条射线共享同一段前缀 →
    必须 `seen` 去重，否则同一落点会被登记两次。
    """
    out = []
    ap = out.append
    seen = set()
    for path in RAYS[pos]:
        for q in path:
            t = board.get(q)
            if t is None:
                if q not in seen:
                    seen.add(q)
                    ap(q)
                continue
            if t["army"] != army and t["army"] not in frozen and q not in seen:
                seen.add(q)
                ap(q)
            break
    return out


def _cannon(board, pos, home, army, frozen):
    out = []
    ap = out.append
    seen = set()                                    # 同上：跨战线分支会共享前缀
    for path in RAYS[pos]:
        jumped = False
        for q in path:
            t = board.get(q)
            if not jumped:
                if t is None:
                    if q not in seen:
                        seen.add(q)
                        ap(q)
                else:
                    jumped = True                       # 炮架
            else:
                if t is None:
                    continue
                if t["army"] != army and t["army"] not in frozen and q not in seen:
                    seen.add(q)
                    ap(q)                               # 隔一子吃
                break
    return out


def _horse(board, pos, home, army, frozen):
    """马：走**传统「日」8 步** —— 位移 (Δr,Δc) ∈ {(±1,±2), (±2,±1)}。

    【权威依据】规则图「棋子运行逻辑」第 1 条原文最后一句：
        「马在其它地方行进方式与传统象棋行进方式（**起、点相对坐标**）完全相符」
    判据 = **数格点数**（一个方向 1 格 + 另一方向 2 格），定义在 (行,列) 拓扑网格上
    （见本文件顶部「拓扑网格」注释块）。

    【蹩马腿】位移写成 mv = 2u + w（u、w 都是网格边方向），腿点 = pos + u，
    即传统象棋「马腿在马走 2 格那一方向的正前方一格」。u 对每个 mv 唯一
    → **每个落点的腿唯一**，不需要任何人为口径（旧的几何 `_leg_rank` 已删除）。

    【为什么逐个 dest 判一次】同一落点可能同时来自常规条款与三角区回跳
    （实测无重叠，但保留去重以保稳）。遍历走 HORSE_T 以固定落点顺序
    （顺序会影响着法表与排名分位）。

    【蹩腿语义】腿点有子即被蹩，**敌子己子一视同仁**；一条腿管几个落点就
    一起砍掉（例如 112 的腿 122 一占，131 与 133 同时走不到 —— 与传统象棋
    「b2 腿一占，a3 与 c3 同时走不到」同构）。
    """
    out = []
    seen = set()
    ap = out.append
    for _leg, dest in HORSE_T[pos]:
        if dest in seen:
            continue                                    # 同一落点只判一次
        seen.add(dest)
        legs = HORSE_LEG[pos][dest]                     # 该落点允许通过的腿（恒 1 条）
        if all(l in board for l in legs):
            continue                                    # 腿被占 → 蹩马腿（不分敌我）
        if _can_land(board, army, frozen, dest):
            ap(dest)
    return out


def _elephant(board, pos, home, army, frozen):
    """象：跨「田字对角」，卡腿只看**田中心**（不分敌我），且不过河。

    老师 2026-09-24 定夺：「象走格子交点，不存在射线；田中心有子就卡腿，
    不能跨到田字对角」—— 113→135 田中心 124，113→131 田中心 122。

    与旧口径的区别：旧口径要求「起点旁边的象眼（112 / 114 / 123）为空」，
    会把开局魏方的象被自家馬/士堵死；新口径只判跨越区域的中点，
    与传统象棋「田中心有子才塞象眼」一致。
    """
    out = []
    ap = out.append
    for dest, tian, dest_army in ELE_T[pos]:
        if dest_army != home:
            continue                                    # 象不过河（限本方领地）
        if tian in board:
            continue                                    # 田中心有子 → 卡腿（不分敌我）
        if _can_land(board, army, frozen, dest):
            ap(dest)
    return out


def _advisor(board, pos, home, army, frozen):
    out = []
    ap = out.append
    for q in ADV_T.get((home, pos), ()):
        if _can_land(board, army, frozen, q):
            ap(q)
    return out


def _general(board, pos, home, army, frozen):
    """帅 / 副帅：军帐内横竖走 1 格（斜走是士的走法）＋ **射杀**

    【射杀 · 老师 2026-09-25 新规则】见 `snipe_targets` 的完整说明。
    顺序：先列军帐内 1 格（传统走法），再补射杀落点 ——
      保持"常规着法在前"，使着法表顺序稳定（排名分位依赖顺序）。
    两类可能重叠（相邻的敌帅既走得到、也射得到，例如副帅 215 与蜀帅 225），
    故用 `seen` 去重。
    """
    out = []
    ap = out.append
    seen = set()
    for q in GEN_T.get((home, pos), ()):
        if q in seen:
            continue
        if _can_land(board, army, frozen, q):
            seen.add(q)
            ap(q)
    for q in snipe_targets(board, pos, army, frozen):
        if q in seen:
            continue
        seen.add(q)
        ap(q)
    return out


def _pawn(board, pos, home, army, frozen):
    """兵（老师 2026-09-22 22:42 初版；2026-09-25 修正「过河」口径）：
      · 向心前进 1 格，不可后退、不可退回本方；
      · **过河** = 跨过中心地带（祁山/赤壁/荆州）进入对方领地。
        **没过河之前不能横走**；过河之后可以横走（同行 + 继续朝对方底线推进）；
      · 过河落点 = 从本方最内层 row5 沿**纵向路线**正对的对面 row5 点
        （底边数字和恒为 10：本方列 c ⇔ 对面列 10−c）。
        例：魏 A7(153，列3) → 蜀 F3(357，列7)；3+7=10 ✓
        三角区三顶点(155/255/355)的列号**都是 5**，所以
        「营点沿三角区边进入邻方营点」就是这条纵向路线在列5 上的特例；
      · 兵只能过一次界（进入他国领地后不再可跨）。

      【2026-09-25 修 · 老师报的「魏兵在 A7 走不了，是什么规则限制」】
        老师原话：「魏国的兵 A7 在**没有过河（就是过祁山这个地带）之前
        不能横向左右行走的**」。
        旧实现有两处偏差，正好互相掩盖：
          ① `crossed = (r0 >= 5) or ...` 把「走到本方最内层 row5」当成过河
             ⇒ A7 的兵被**错误地允许**左右横走 152/154；
          ② `PAWN_T` 是在 `_splice_front_rays()` **之前**用原始 `B.rays` 生成的
             ⇒ 只有图上真画线的 9 个 row5 点带跨方通道，A7 这种列3 的点
             **看不到**过河落点 357 ⇒ 于是它也走不了。
        ⇒ 改后 A7 的魏兵唯一正解 = **一步过河到 F3(357)**，
          横走被禁（与老师口径一致）。
    """
    out = []
    ap = out.append
    pa, r0, c0 = RC[pos]
    in_own = (pa == home)
    # 【2026-09-25 老师口径】「过河」= **跨过中心地带（祁山/赤壁/荆州）进入对方领地**，
    #   而不是「走到本方最内层 row5」。旧写法 `(r0 >= 5) or (not in_own)` 把后者
    #   也误当成过河，于是兵一进 row5 就能横走 —— 老师实战发现：
    #   「魏国的兵 A7 在**没有过河（就是过祁山这个地带）之前不能横向左右行走**」。
    crossed = not in_own
    for q, qa, qr, qc in PAWN_T[pos]:
        if not _can_land(board, army, frozen, q):
            continue
        if qa == pa:
            # ---- 同领地内的步（注意：这里的"pa"是**兵当前所在点**的方，
            #      不一定等于它的 home —— 过界之后兵就站在邻方领地里了）
            if in_own:
                # 本方领地：向心 = 行号递增
                if qr < r0:
                    continue                                # 不可后退
                if qr > r0 and qc != c0:
                    continue                                # 向心必须同列
                if qr == r0 and not crossed:
                    continue                                # 未过界不可横走
                ap(q)
            else:
                # 【2026-09-24 修 · 老师报的「兵不会过河」】
                # 兵已进入**邻方领地**：此时它的"前进"是**朝邻方底线**，
                # 即行号**递减**（邻方 row1 才是人家的底线）。
                # 旧实现沿用"行号递减 = 后退"的口径 → 兵一过界就只能在对方 row5
                # 上横走，永远进不了敌境纵深，看起来就是"过不了河"。
                # 传统象棋：兵过河后可横走**也可继续前进**，只是不能后退、
                # 且本棋盘规定「只能过一次界」（再跨方由下面 else 分支拦住）。
                if qr > r0:
                    continue                                # 不可朝中心方向退
                if qr < r0 and qc != c0:
                    continue                                # 深入须同列
                ap(q)
        else:
            # ---- 跨方步 = **过河**（跨过中心地带，进对方领地）
            # ★【2026-10-01 老师新规】兵在**中心三角区格点**上可自由回跳。
            #   老师原话：「当兵到达中心三角区格点后可以自由往任一方向走」
            #            ＋「允许各方兵在中心三角区回跳」。
            #   ⇒ 任何**归属方**的兵站在 155/255/355 任一点，都能走到另两点；
            #     这属于「回跳」，**不算过界** —— 不受「兵只能过一次界」约束，
            #     可以三方营点之间反复穿梭（含"回到自己营点"）。
            #   注意：本分支在 `if not in_own` 之前 —— 三角区通道对
            #   「已在他国营点」的兵同样开放（否则他就被锁死在别人营地里了）。
            if pos in TRI_PTS and q in TRI_PTS:
                ap(q)
                continue
            if not in_own:
                continue                    # 只能过一次界（已在邻方领地就不能再跨）
            # 过河落点 = 从本方最内层 row5 沿**纵向路线**正对的对面 row5 点。
            #   纵向路线判据 = 「底边数字和恒为 10」：本方列 c0 ⇔ 对面列 10−c0
            #   （老师 2026-09-24 确认的接线口径，2026-09-25 明确同样适用于兵）。
            #   例：魏 A7（153，列3）→ 蜀 F3（357，列7）；3+7=10 ✓
            #      魏 A5（155，列5）→ 蜀 F5（355）/ 吴 K5（255）；5+5=10 ✓
            #   三角区三个顶点的列号**都是 5**，所以「营点跨三角区」本来就是
            #   这条纵向路线的特例（155↔255↔355 正好是列5 那条线），
            #   此处不再单列 `pos == B.tri[home]` 分支。
            if r0 == 5 and qr == 5 and qc == 10 - c0:
                ap(q)
            continue
    return out


def _forward_deltas(home):
    """兵的"前方"（向心）相邻点（供 LLM 文本提示用）"""
    out = []
    for c in (4, 5):
        p = D.pid(home, 4, c)
        q = D.pid(home, 5, c)
        if p in B.xy and q in B.xy:
            out.append((q,))
    return out


BUILDERS = {ROOK: _rook, CANNON: _cannon, HORSE: _horse, ELEPHANT: _elephant,
            ADVISOR: _advisor, GENERAL: _general, PAWN: _pawn}

# 注：`_EMPTY` 已上移到文件顶部常量区（snipe_targets 的默认参数要用）。


def moves_of(board, pos, pc, frozen=_EMPTY):
    """**热路径入口**：直接给定棋子对象，省掉 board.get() 与一次字典查找。

    搜索内部用它（每次调用都要走几百万次），外部继续用 pseudo_moves(s, ...)。
    """
    return BUILDERS[pc["kind"]](board, pos, pc["home"], pc["army"], frozen)


def pseudo_moves(s, pos, frozen=_EMPTY):
    """某点的所有伪合法着法（不检查送将/将见面）"""
    board = s["board"]
    pc = board.get(pos)
    if pc is None:
        return []
    if frozen and pc["army"] in frozen:
        return []
    return BUILDERS[pc["kind"]](board, pos, pc["home"], pc["army"], frozen)


def side_moves(s, army, frozen=_EMPTY):
    """某方全部伪合法着法 (from, to)"""
    board = s["board"]
    out = []
    ap = out.append
    for pos, pc in board.items():
        if pc["army"] != army:
            continue
        fn = BUILDERS[pc["kind"]]
        for q in fn(board, pos, pc["home"], pc["army"], frozen):
            ap((pos, q))
    return out


def attacked(s, target, by_armies, frozen=_EMPTY):
    """target 是否被 by_armies 中任一方攻击"""
    board = s["board"]
    for pos, pc in board.items():
        if pc["army"] not in by_armies:
            continue
        if pc["kind"] == GENERAL and not pc.get("deputy") and pos == target:
            continue                                    # 帅不"攻击"自己所在点
        if target in BUILDERS[pc["kind"]](board, pos, pc["home"], pc["army"], frozen):
            return True
    return False


def _hit(board, pos, pc, kind, extra, target):
    """棋子 pc（站在 pos、子种 kind）依据附加信息 extra，是否攻击 target"""
    if kind == ROOK:
        for q in extra:
            if q in board:
                return False
        return True
    if kind == CANNON:
        n = 0
        for q in extra:
            if q in board:
                n += 1
        return n == 1
    if kind == HORSE:
        return extra not in board                       # 蹩腿
    if kind == ELEPHANT:
        tian, dest_army = extra
        return pc["home"] == dest_army and tian not in board  # 象不过河 + 田中心无子
    if kind == GENERAL:
        if pos == target and not pc.get("deputy"):
            return False                                # 帅不"攻击"自己所在点
        return pc["home"] == extra
    return pc["home"] == extra                          # 兵 / 士


def attacks(board, pos, pc, target):
    """站在 pos 的棋子 pc 是否攻击 target —— 单子版（搜索叶节点热路径用它）

    与 moves_of() 的语义严格一致：落到 target 必须合法，
    即 target 为空或是敌子（己方占着 target 时不算"攻击"）。
    """
    t = board.get(target)
    if t is not None and t["army"] == pc["army"]:
        return False
    d = ATK_BY.get(target)
    if d is None:
        return False
    specs = d.get(pos)
    if specs is None:
        return False
    k = pc["kind"]
    for kind, extra in specs:
        if kind == k and _hit(board, pos, pc, kind, extra, target):
            return True
    return False


def under_attack(board, target, by_army):
    """by_army 方是否攻击 target —— **反向查表版**，比 attacked() 快一个量级。

    与 attacked() 的区别：
      · attacked() 是「遍历攻击方的每颗子、生成它的全部着法、看 target 在不在里面」；
      · 本函数是「取出能打到 target 的候选点，逐个验证阻挡条件」。
    二者逻辑等价，但后者不需要为每颗子生成完整着法列表，
    并且**没有距离限制** —— 旧版漏判「车/炮远距离同线将军」的问题一并修掉。
    """
    d = ATK_BY.get(target)
    if d is None:
        return False
    t = board.get(target)
    if t is not None and t["army"] == by_army:
        return False                                    # 己方占着 target，不算攻击
    for pos, specs in d.items():
        pc = board.get(pos)
        if pc is None or pc["army"] != by_army:
            continue
        k = pc["kind"]
        for kind, extra in specs:
            if kind == k and _hit(board, pos, pc, kind, extra, target):
                return True
    return False


def line_of_sight(s, p1, p2):
    """p1 与 p2 是否在同一条射线（直线）上且中间无子

    【2026-09-24 夜 修正 · 原来是错的】
    旧实现走 `B.rays`（DXF 原始几何射线）—— 那是**没接「战线直通」**的版本：
    每方的纵线只画到自己的 row5 就断（原图战线上不画线）。
    而规则图《一、9. 帅不见面》明列的六条线路
    【E5-A5-F5-J5】【J5-F5-K5-O5】【O5-K5-A5-E5】
    【E6-A6-F4-J4】【J6-F6-K4-O4】【O6-K6-A4-E4】
    **全部是跨方贯通线** —— 用 B.rays 判定时六条**一条都命中不了**
    （实测 12 条样本漏判 9 条，只有 DXF 恰好画成一整条的「图1↔图9」三对能通）
    → 「帅不见面」规则**形同虚设**。

    改用 `RAYS`（已接战线直通，15 条贯通纵线首尾可达，实测失败 0 条）。
    """
    board = s["board"]
    for path in RAYS.get(p1) or ():          # 用接好「战线直通」的 RAYS（不是 B.rays）
        if p2 in path:
            idx = path.index(p2)
            if all(q not in board for q in path[:idx]):
                return True
    return False


def generals_facing(s):
    """互相"见面"的【主帅】对（副帅不参与此判定）"""
    gens = [(p, pc) for p, pc in s["board"].items()
            if pc["kind"] == GENERAL and not pc.get("deputy")]
    out = []
    for i in range(len(gens)):
        for j in range(i + 1, len(gens)):
            if line_of_sight(s, gens[i][0], gens[j][0]):
                out.append((gens[i][0], gens[j][0]))
    return out


# ---------------------------------------------------------------- 自检
if __name__ == "__main__":
    import time
    t0 = time.time()
    print(f"预计算表构建耗时 {time.time() - t0:.3f}s（模块载入时一次性）")
    print(f"  射线表 {len(RAYS)} 点 / 马表 {sum(len(v) for v in HORSE_T.values())} 步"
          f" / 象表 {sum(len(v) for v in ELE_T.values())} 步"
          f" / 反向攻击表 {len(LINE_ATTACK)} 点有线攻击、{len(SIMPLE_ATTACK)} 点有近身攻击")
    from . import game_dxf as GA
    s = GA.new_game(first=1)
    for a in (1, 2, 3):
        print(f"  {D.ARMY_CN[a]}方开局伪合法着法 {len(side_moves(s, a))} 步")
