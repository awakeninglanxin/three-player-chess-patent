# -*- coding: utf-8 -*-
"""专利版棋盘几何（数据驱动版）—— 以老师的 DXF 为唯一权威来源。

与旧 geometry.py 的区别：
  - 旧版：三角网格 + 整数格坐标（r,c），适合 1 号版本
  - 本版：直接加载 server/data/board_135.json 的 135 个精确坐标 + 邻接 + 51 条线，
          并以「射线（ray）」为基础抽象实现「车沿直线走」

坐标约定：DXF 图纸坐标（x 右、y 上），单位 ≈ 1 格。
点位编号：'方-行-列'，方 1=魏(下) 2=吴(左上) 3=蜀(右上)；行 1=底线 .. 5=最内层；列 1=最右 .. 9=最左。
  （方号 ↔ 方位实测：`115` 魏帥 xy=(0, −90.1)、`225` 吴帥 xy=(−62.2, 35.9)、`325` 蜀帥 xy=(62.2, 35.9)。
    2026-09-24 修正：旧注释把 2/3 写成「蜀/吴」，与 `ARMY_CN` 和行棋顺序 1→2→3 矛盾。）
"""
import collections
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data", "board_135.json")

ARMIES = (1, 2, 3)
ARMY_CN = {1: "魏", 2: "吴", 3: "蜀"}
# 行棋顺序（沿用 1 号版本）：魏 → 吴 → 蜀（与本图左→右一致；
#   旧注释误写成「魏 → 蜀 → 吴」，与 TURN_ORDER=[1,2,3] 和 ARMY_CN 矛盾，2026-09-24 修正）
TURN_ORDER = [1, 2, 3]

# 度：判定「同方向」的角度容差
#
# 【为什么是 2.0 而不是 0.6 —— 2026-09-24 实测修复】
# DXF 点距天然不均匀（底边 13.0055 / 斜边 11.5615 / 另有 16.43 等），
# 使**同一条几何直线**上的相邻段方向出现最大 0.84° 的跳变。实例：
#     131→132 = 165.40°，132→133 = 165.82°，133→134 = 164.98°
# 容差 0.6° 装不下这个跳变 → 車在 132 沿该直线只能走到 133 就断，
# 走不到 134/135（空盘实测：車132 走不到 134；象 112→134 也因此少了第二条路径）。
# 全场共 **12 条射线**被误截断，且三方完全对称：
#     131/231/331、132/232/332、134/234/334、135/235/335
# 射线总长由 1392 修复为 1416（+24 = 12×2）。
#
# 安全区间：必须 > 0.84°（同线跳变），且远小于 35.412°（不同方向族的最小夹角）。
# 取 2.0 既有 2.4× 余量，又不可能把两个方向族并成一条射线（实测射线数 492 不变）。
ANG_TOL = 2.0


def _norm(v):
    L = math.hypot(*v)
    return (v[0] / L, v[1] / L) if L else (0.0, 0.0)


def _angle(u, v):
    d = max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1]))
    return math.degrees(math.acos(d))


def pid(army, row, col):
    """3 位数字编号：方(1-3) 行(1-5) 列(1-9)，如 345 = 吴方第4行第5列。
    用纯数字避免与着法分隔符 '-' 冲突（着法写作 111-121）。"""
    return f"{army}{row}{col}"


def parse(pid_str):
    return int(pid_str[0]), int(pid_str[1]), int(pid_str[2])


def _conv_old(key):
    """把 DXF 数据里的 '1-1-1' 键转换为 '111'"""
    a, r, c = key.split("-")
    return f"{a}{r}{c}"


class Ray:
    """一个点的某条射线：从自身出发、沿固定方向的相邻点（可能多点）

    walk 是「沿该方向一直走」的沿途点序列，**只取决于棋盘几何**（与局面无关），
    因此在棋盘载入时算一次就够，之后所有走法生成直接读缓存。
    """
    __slots__ = ("o", "dir", "nbrs", "walk")

    def __init__(self, o, d, nbrs):
        self.o = o
        self.dir = d
        self.nbrs = nbrs
        self.walk = None            # 由 Board._build_walks() 填充

    def __repr__(self):
        return f"Ray({self.o} -> {[n for n in self.nbrs]})"


class Board:
    def __init__(self, path=DATA):
        raw = json.load(open(path, encoding="utf-8"))
        self.xy = {_conv_old(k): (v["x"], v["y"]) for k, v in raw["points"].items()}
        self.adj = {_conv_old(k): [_conv_old(t) for t in v] for k, v in raw["adj"].items()}
        self.lines = [[_conv_old(p) for p in L] for L in raw["lines"]]
        self.ids = list(self.xy)

        # 行 / 列 / 九宫 / 三角区 / 过河通道
        self.rows = collections.defaultdict(list)      # (army,row) -> [pid]（按列 1..9 排序）
        self.cols = collections.defaultdict(list)      # (army,col) -> [pid]（按行 1..5 排序）
        for p in self.ids:
            a, r, c = parse(p)
            self.rows[(a, r)].append(p)
            self.cols[(a, c)].append(p)
        for k in self.rows:
            self.rows[k].sort(key=lambda p: parse(p)[2])
        for k in self.cols:
            self.cols[k].sort(key=lambda p: parse(p)[1])

        # 九宫：行 1-3 × 列 4-6
        self.gong = {a: [pid(a, r, c) for r in (1, 2, 3) for c in (4, 5, 6)] for a in ARMIES}
        self.gong_center = {a: pid(a, 2, 5) for a in ARMIES}
        # 九宫两条对角线（士的走法）：1-4→2-5→3-6 与 1-6→2-5→3-4
        self.gong_diag = {a: [[pid(a, 1, 4), pid(a, 2, 5), pid(a, 3, 6)],
                              [pid(a, 1, 6), pid(a, 2, 5), pid(a, 3, 4)]] for a in ARMIES}

        # 中央三角区顶点 = 各方 5-5
        self.tri = {a: pid(a, 5, 5) for a in ARMIES}
        self.tri_edges = [(self.tri[1], self.tri[2]), (self.tri[1], self.tri[3]),
                          (self.tri[2], self.tri[3])]

        # 过河通道（跨方相邻对）
        self.gates = self._find_gates()

        # 射线（车/炮/马/象的走法基础）
        self.rays = {}
        self._build_rays()
        self._build_walks()                 # 沿途序列预计算（一次性）

    # ---------------------------------------------------------------- 过河通道
    def _find_gates(self):
        out = []
        for p in self.ids:
            a = parse(p)[0]
            for q in self.adj[p]:
                if parse(q)[0] != a and p < q:
                    out.append((p, q))
        return out

    # ---------------------------------------------------------------- 射线
    def _build_rays(self):
        for p in self.ids:
            px, py = self.xy[p]
            groups = []          # [[dir, [nbr...]]]
            for q in self.adj[p]:
                d = _norm((self.xy[q][0] - px, self.xy[q][1] - py))
                hit = None
                for g in groups:
                    if _angle(g[0], d) < ANG_TOL:
                        hit = g
                        break
                if hit:
                    hit[1].append(q)
                else:
                    groups.append([d, [q]])
            rays = []
            for d, ns in groups:
                ns.sort(key=lambda q: math.hypot(self.xy[q][0] - px, self.xy[q][1] - py))
                rays.append(Ray(p, d, ns))
            self.rays[p] = rays

    # ---------------------------------------------------------------- 沿途序列预计算
    def _build_walks(self):
        """把每条射线的「沿途点序列」一次性算好。

        【为什么要预计算 —— 实测数据】
            cProfile 显示：一次 6 plies 搜索里 ray_walk / _angle / math.acos
            共被调用约 40 万次，占总时长约 30%。
            但 walk 只依赖几何（棋盘 + DXF 坐标），与棋盘状态**完全无关**，
            每次生成着法都重算是纯粹的浪费。预计算后这一步开销归零。
        """
        for p in self.ids:
            for ray in self.rays[p]:
                ray.walk = self._ray_walk_raw(p, ray.dir)

    def _ray_walk_raw(self, start, d):
        """原始的逐步行走实现（只在预计算时调用一次）"""
        out = []
        cur = start
        guard = 0
        while guard < 40:
            guard += 1
            nxt = None
            for r2 in self.rays.get(cur) or ():
                if _angle(r2.dir, d) < ANG_TOL:
                    nxt = r2.nbrs[0]
                    break
            if nxt is None:
                break
            out.append(nxt)
            # 更新方向（用实际步向量，抗微小形变）
            d = _norm((self.xy[nxt][0] - self.xy[cur][0],
                       self.xy[nxt][1] - self.xy[cur][1]))
            cur = nxt
        return tuple(out)

    # ---------------------------------------------------------------- 沿射线连续前进
    def ray_walk(self, start, ray):
        """从 start 沿 ray.dir 连续走，返回沿途点序列（不含 start）

        命中缓存时 O(1)；只有 start 与射线归属点不一致时才现场重算
        （正常调用不会发生 —— 射线总是从自己的起点取）。
        """
        if ray.walk is not None and ray.o == start:
            return ray.walk
        return self._ray_walk_raw(start, ray.dir)

    def straight_paths(self, p):
        """点 p 的所有「直线方向」及其沿途点序列"""
        return [(r.dir, r.walk if r.walk is not None
                 else self._ray_walk_raw(p, r.dir)) for r in self.rays.get(p, ())]

    # ---------------------------------------------------------------- 归属与邻域
    def army_of(self, p):
        return parse(p)[0]

    def row_of(self, p):
        return parse(p)[1]

    def col_of(self, p):
        return parse(p)[2]

    def in_territory(self, army, p):
        """p 是否在该方的领地（本方 45 点内）"""
        return parse(p)[0] == army

    def to_gong(self, army):
        return set(self.gong[army])

    # ---------------------------------------------------------------- 自检
    def summary(self):
        deg = collections.Counter(len(v) for v in self.adj.values())
        return {
            "点数": len(self.ids),
            "邻接边": sum(len(v) for v in self.adj.values()) // 2,
            "行线": len(self.rows), "列线": len(self.cols),
            "度数分布": dict(sorted(deg.items())),
            "过河通道": len(self.gates),
            "三角区边": len(self.tri_edges),
            "射线总数": sum(len(v) for v in self.rays.values()),
        }


BOARD = Board()


def initial_position():
    """每方 16 子，布局与传统象棋半盘一致（底线 9 子 + 炮 2 + 兵 5）"""
    layout = [(ROOK, 1, 1), (HORSE, 1, 2), (ELEPHANT, 1, 3), (ADVISOR, 1, 4),
              (GENERAL, 1, 5), (ADVISOR, 1, 6), (ELEPHANT, 1, 7),
              (HORSE, 1, 8), (ROOK, 1, 9),
              (CANNON, 3, 2), (CANNON, 3, 8),
              (PAWN, 4, 1), (PAWN, 4, 3), (PAWN, 4, 5), (PAWN, 4, 7), (PAWN, 4, 9)]
    out = []
    for army in ARMIES:
        for kind, r, c in layout:
            out.append({"army": army, "kind": kind, "pos": pid(army, r, c)})
    return out


ROOK, HORSE, ELEPHANT, ADVISOR, GENERAL, CANNON, PAWN = (
    "rook", "horse", "elephant", "advisor", "general", "cannon", "pawn")

if __name__ == "__main__":
    import pprint
    pprint.pprint(BOARD.summary())
    print("\n过河通道：")
    for p, q in BOARD.gates:
        print(f"  {p} <-> {q}   ({ARMY_CN[BOARD.army_of(p)]}-{ARMY_CN[BOARD.army_of(q)]})")
    print("\n三角区顶点：", {ARMY_CN[a]: v for a, v in BOARD.tri.items()})
    print("\n【验证】1-1-1（魏底线右端）的直线方向与沿途：")
    for d, path in BOARD.straight_paths("1-1-1"):
        ang = math.degrees(math.atan2(d[1], d[0]))
        print(f"  方向 {ang:7.2f}°  ->  {' → '.join(path) if path else '(无)'}")
    print("\n【验证】1-5-1（魏最内右端，过河点）的直线方向：")
    for d, path in BOARD.straight_paths("1-5-1"):
        ang = math.degrees(math.atan2(d[1], d[0]))
        print(f"  方向 {ang:7.2f}°  ->  {' → '.join(path) if path else '(无)'}")
    print("\n【验证】1-2-5（魏九宫中心）的直线方向：")
    for d, path in BOARD.straight_paths("1-2-5"):
        ang = math.degrees(math.atan2(d[1], d[0]))
        print(f"  方向 {ang:7.2f}°  ->  {' → '.join(path) if path else '(无)'}")
