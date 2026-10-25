# -*- coding: utf-8 -*-
"""
三人象棋 · 棋盘几何（鼎棋 / 三人中国象棋，135 点位）

几何模型
--------
* 基底：三角（菱形）网格。每方半盘 = 9 列 × 5 行 = 45 点，三方共 135 名义点位。
* 半盘内坐标 (r, c)：r=1 底线（9 点，自右向左 1..9），r=5 河线。
  局部坐标 = (c-1)*û + (r-1)*v̂，  û=(1,0)，v̂=(0.5,√3/2)。
* 三方按 120° 环绕中央"赤壁"三角区，三角边长恰为 8（9 点/边）。
* 三处角落被两方共用 -> 135 名义 / 132 物理点。
  实测 151=359、159=251、259=351，与鼎棋原文 "151(259)、251(359)、351(159)" 同构。
* 跨方关键：本方第 5 行的直线延伸接的是邻方第 1 列。
  实测横线 y=3.4641 上依次 151..159(魏第5行) 241 231 221 211(蜀第1列)。

格坐标（整数，用于精确判线）
    任一点 = a*û + b*v̂ ，a,b 为整数。
    方向 A(0°)   : a 变 b 恒定   -> 直线族 = 按 b 分组
    方向 B(60°)  : b 变 a 恒定   -> 直线族 = 按 a 分组
    方向 C(120°) : v̂-û => a-1,b+1 -> 直线族 = 按 a+b 分组
"""
import math

SQ3_2 = math.sqrt(3) / 2

ARMIES = {
    1: {"key": "wei", "name": "魏", "color": "#2b6cb0", "light": "#dbeafe",
        "general": "帥", "pawn": "卒"},
    2: {"key": "shu", "name": "蜀", "color": "#c53030", "light": "#fee2e2",
        "general": "將", "pawn": "兵"},
    3: {"key": "wu", "name": "吴", "color": "#2f855a", "light": "#dcfce7",
        "general": "王", "pawn": "勇"},
}
SHARED_CHARS = {"rook": "車", "horse": "馬", "elephant": "象",
                "advisor": "士", "cannon": "炮"}

ROWS, COLS = 5, 9
_C0 = (6.0, 3.4641 + 2.3094)          # 中央三角重心 = 全局旋转中心
UNIT_DIRS = [(0, 1), (0, -1), (1, 0), (-1, 0), (1, -1), (-1, 1)]   # (Δr,Δc)
LINE_DIRS = {"A": "b", "B": "a", "C": "s"}                          # 分组键


def _rot(p, deg):
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    x, y = p[0] - _C0[0], p[1] - _C0[1]
    return (_C0[0] + x * ca - y * sa, _C0[1] + x * sa + y * ca)


def _lattice(x, y):
    """平面坐标 -> 整数格坐标 (a, b):  point = a*û + b*v̂"""
    return (round(x - y / math.sqrt(3)), round(2 * y / math.sqrt(3)))


# ⚠️【本文件已废弃】活代码请用 `rules_dxf.py` / `geometry_dxf.py`（基于老师给的 DXF 工程图）。
#   本文件按"60° 三角网格 + 6 邻域"建模，与 DXF 实测不符：DXF 里每个内部点只有
#   **4 个邻居**（145 → 135/155/144/146；全盘 60 个内部点皆然）→ 4 连通四边形（菱形）网格。
#   因此马步的正确口径是**传统「日」8 步**（(Δr,Δc) ∈ {(±1,±2), (±2,±1)}），
#   见 `rules_dxf.HORSE_MOVES`。下面的 12 步写法已作废，保留仅供历史参照。
HORSE_MOVES = [(dr, dc) for dr in range(-3, 4) for dc in range(-3, 4)
               if dr * dr + dc * dc + dr * dc == 7 and (dr or dc)]


def _horse_legs():
    """为每个马步求"蹩马腿"方向 u（该步 = 2u + w，u,w 均为单位方向）"""
    out = {}
    for mv in HORSE_MOVES:
        for u in UNIT_DIRS:
            w = (mv[0] - 2 * u[0], mv[1] - 2 * u[1])
            if w in UNIT_DIRS:
                out[mv] = u
                break
    return out


HORSE_LEGS = _horse_legs()


class Board:
    """棋盘拓扑（只读）"""

    def __init__(self):
        self.xy, self.aliases, self.nominal = {}, {}, {}
        raw = {}
        for k in (1, 2, 3):
            for r in range(1, ROWS + 1):
                for c in range(1, COLS + 1):
                    raw[f"{k}{r}{c}"] = (_rot((_lc(r, c)), 120 * (k - 1)), (r, c))

        buckets = {}
        for pid, (p, rc) in raw.items():
            key = (round(p[0], 3), round(p[1], 3))
            buckets.setdefault(key, []).append((pid, rc))

        for key, items in buckets.items():
            items.sort()
            canon = items[0][0]
            self.xy[canon] = key
            self.nominal[canon] = {int(pid[0]): rc for pid, rc in items}
            for pid, _ in items[1:]:
                self.aliases[pid] = canon

        self.lattice = {p: _lattice(*xy) for p, xy in self.xy.items()}

        # 邻接
        self.adj = {p: set() for p in self.xy}
        for i, a in enumerate(sorted(self.xy)):
            A = self.lattice[a]
            for b in sorted(self.xy):
                if a >= b:
                    continue
                B = self.lattice[b]
                d = (B[0] - A[0], B[1] - A[1])
                if d in UNIT_DIRS:
                    self.adj[a].add(b)
                    self.adj[b].add(a)
        # 邻接偏移表: (p, Δ格坐标) -> neighbor
        self.movenb = {}
        for p in self.xy:
            for q in self.adj[p]:
                A, B = self.lattice[p], self.lattice[q]
                self.movenb[(p, (B[0] - A[0], B[1] - A[1]))] = q

        # 直线族
        self.lines = {}
        for d, key in LINE_DIRS.items():
            groups = {}
            for p, (a, b) in self.lattice.items():
                g = {"a": a, "b": b, "s": a + b}[key]
                groups.setdefault(g, []).append(p)
            segs = []
            for g, pts in groups.items():
                pts.sort(key=lambda p: self.lattice[p])
                run = [pts[0]]
                for prev, cur in zip(pts, pts[1:]):
                    if self.lattice[cur] in [(self.lattice[prev][0] + dd[0],
                                              self.lattice[prev][1] + dd[1])
                                             for dd in UNIT_DIRS]:
                        run.append(cur)
                    else:
                        if len(run) >= 2:
                            segs.append(run)
                        run = [cur]
                if len(run) >= 2:
                    segs.append(run)
            self.lines[d] = segs

        # 本方领地 / 王宫
        self.territory = {k: {self.canon(f"{k}{r}{c}")
                              for r in range(1, ROWS + 1)
                              for c in range(1, COLS + 1)} for k in (1, 2, 3)}
        self.palace = {k: {self.canon(f"{k}{r}{c}")
                           for r in (1, 2) for c in (4, 5, 6)} for k in (1, 2, 3)}
        # 各方河线（第 5 行）
        self.river = {k: {self.canon(f"{k}5{c}") for c in range(1, COLS + 1)}
                      for k in (1, 2, 3)}

    def canon(self, pid):
        pid = str(pid).upper()
        if pid in self.xy:
            return pid
        if pid in self.aliases:
            return self.aliases[pid]
        raise KeyError(f"未知点位: {pid}")

    def lines_through(self, pid):
        """返回该点所在的三条直线 (A/B/C)"""
        out = {}
        for d, segs in self.lines.items():
            for s in segs:
                if pid in s:
                    out[d] = s
                    break
        return out

    def to_json(self):
        ys = [v[1] for v in self.xy.values()]
        pts = []
        for pid in sorted(self.xy):
            x, y = self.xy[pid]
            pts.append({"id": pid, "x": round(x, 4), "y": round(max(ys) - y, 4),
                        "owners": sorted(self.nominal[pid]),
                        "alias": sorted(n for n, c in self.aliases.items() if c == pid)})
        return {
            "armies": ARMIES, "chars": SHARED_CHARS,
            "points": pts,
            "lines": {d: [[str(p) for p in s] for s in segs] for d, segs in self.lines.items()},
            "palace": {str(k): sorted(v) for k, v in self.palace.items()},
            "territory": {str(k): sorted(v) for k, v in self.territory.items()},
            "river": {str(k): sorted(v) for k, v in self.river.items()},
            "initial": initial_position(),
        }


def _lc(r, c):
    return ((c - 1) + (r - 1) * 0.5, (r - 1) * SQ3_2)


def initial_position():
    """每方 16 子布于各自半盘（与传统象棋半盘一致）"""
    layout = {("rook", 1, 1), ("horse", 1, 2), ("elephant", 1, 3), ("advisor", 1, 4),
              ("general", 1, 5), ("advisor", 1, 6), ("elephant", 1, 7),
              ("horse", 1, 8), ("rook", 1, 9),
              ("cannon", 3, 2), ("cannon", 3, 8),
              ("pawn", 4, 1), ("pawn", 4, 3), ("pawn", 4, 5),
              ("pawn", 4, 7), ("pawn", 4, 9)}
    out = []
    for k in (1, 2, 3):
        for kind, r, c in sorted(layout):
            out.append({"army": k, "kind": kind, "pos": f"{k}{r}{c}"})
    return out


BOARD = Board()

if __name__ == "__main__":
    for d, segs in BOARD.lines.items():
        ln = sorted(len(s) for s in segs)
        k = sorted(((len(s), s) for s in segs), reverse=True)[:2]
        print(f"方向 {d}: {len(segs)} 条, 长度 {ln[0]}~{ln[-1]}")
        for n, s in k:
            print(f"    最长 {n:2d}: {' '.join(s)}")
    print("王宫 1:", sorted(BOARD.palace[1]))
    print("河线 1:", sorted(BOARD.river[1]))
    print("点位", len(BOARD.xy), "别名", BOARD.aliases)
    print("马的 12 步:", HORSE_MOVES)
    print("马腿表:", {k: v for k, v in HORSE_LEGS.items() if k in ((3, -1), (2, 1))})
