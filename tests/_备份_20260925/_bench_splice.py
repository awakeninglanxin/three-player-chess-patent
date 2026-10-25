# -*- coding: utf-8 -*-
"""战线直通（splice）落地后的实测基准：射线 / 车炮着法空间 / 走法生成吞吐。

用法：python _bench_splice.py
"""
import collections
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "server"))

from engine import geometry_dxf as G          # noqa: E402
from engine import rules_dxf as R             # noqa: E402
from engine import game_dxf as GA             # noqa: E402

B = G.BOARD

print("=" * 70)
print("1. 战线直通统计")
print("=" * 70)
print("SPLICE_STAT (替换, 新增) =", R.SPLICE_STAT)
lanes = R._front_lanes()
uniq = {tuple(sorted(ln)) for _a, _c, _b, ln in lanes}
print("贯通纵线：生成 %d 条 → 去重后 %d 条（规则图「纵向路线」为 3 组 x 5 = 15 条）"
      % (len(lanes), len(uniq)))

print()
print("=" * 70)
print("2. 射线表：新 RAYS（含贯通） vs 旧 B.rays（原始几何）")
print("=" * 70)


def hist(tb, name, unwrap=False):
    h = collections.Counter()
    tot = 0
    for _p, paths in tb.items():
        for w in paths:
            if unwrap:
                w = w.walk
            h[len(w)] += 1
            tot += len(w)
    print("%-12s 路径数=%4d  总点数=%5d  最长=%2d" % (name, sum(h.values()), tot, max(h)))
    print("             长度分布 %s" % dict(sorted(h.items())))


hist(R.RAYS, "RAYS(新)")
hist(B.rays, "B.rays(旧)", unwrap=True)

print()
print("=" * 70)
print("3. 空盘：车 / 炮 的全盘落点总数（新 vs 旧）")
print("=" * 70)
EMPTY = {}


def count_rc(table, unwrap=False):
    bak = R.RAYS
    if unwrap:
        R.RAYS = {p: tuple(r.walk for r in rs) for p, rs in table.items()}
    else:
        R.RAYS = table
    try:
        r = sum(len(R._rook(EMPTY, p, 1, 1, set())) for p in B.ids)
        c = sum(len(R._cannon(EMPTY, p, 1, 1, set())) for p in B.ids)
    finally:
        R.RAYS = bak
    return r, c


r_new, c_new = count_rc(R.RAYS)
r_old, c_old = count_rc(B.rays, unwrap=True)
print("车：新 %5d 着法 / 旧 %5d → 增加 %d（%.1f%%）"
      % (r_new, r_old, r_new - r_old, 100.0 * (r_new - r_old) / max(r_old, 1)))
print("炮：新 %5d 着法 / 旧 %5d → 增加 %d（%.1f%%）"
      % (c_new, c_old, c_new - c_old, 100.0 * (c_new - c_old) / max(c_old, 1)))

print()
print("=" * 70)
print("4. 开局着法数（三方）与走法生成吞吐")
print("=" * 70)
try:
    g = GA.new_game()
    st = g.snapshot() if hasattr(g, "snapshot") else g
except Exception as e:                       # noqa: BLE001
    st = None
    print("new_game() 不可用：%r" % (e,))

if st is not None:
    board = st.get("board", st)
    print("初始局面子数 =", len(board))
    t0 = time.perf_counter()
    tot = 0
    for a in (1, 2, 3):
        mv = R.side_moves(st, a)
        tot += len(mv)
        print("  方 %d 开局合法着法 = %d" % (a, len(mv)))
    dt = time.perf_counter() - t0
    print("三方合计 = %d 步；耗时 %.4f s（%.1f 次着法/秒）"
          % (tot, dt, tot / max(dt, 1e-9)))

    # 走法生成热路径吞吐
    N = 2000
    t0 = time.perf_counter()
    for _ in range(N):
        R.side_moves(st, 1)
    dt = time.perf_counter() - t0
    print("side_moves(方1) x%d 耗时 %.3f s → %.1f 次/秒（%.1f us/次）"
          % (N, dt, N / dt, 1e6 * dt / N))
