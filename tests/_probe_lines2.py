# -*- coding: utf-8 -*-
"""用已验证的仿射映射（残差 3.61 DXF 单位，叠加图红点落在交点上）做线存在性判定。

映射方向（由 _probe_chars 的日志反推确认）：
    dxf = A @ px + t     =>     px = A^-1 @ (dxf - t)
其中 px = (x_img, y_img) 直接是图片像素（y 向下）。
"""
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
IMG = os.path.join(HERE, "..", "docs", "专利版棋盘原图.jpg")

A = np.array([[0.13707205105284648, 0.001743574092299277],
              [-0.00139043887368098, -0.1530652955328367]])
T = np.array([-105.86090797823952, 98.94778353255116])
Ainv = np.linalg.inv(A)

GREY = cv2.cvtColor(cv2.imdecode(np.fromfile(IMG, dtype=np.uint8),
                                 cv2.IMREAD_COLOR), cv2.COLOR_BGR2GRAY)


def to_px(dxf):
    v = Ainv @ (np.asarray(dxf, float) - T)
    return v


def seg_stats(a_id, b_id, half=8, n=60):
    import engine.geometry_dxf as G
    a = np.array(G.BOARD.xy[a_id], float)
    b = np.array(G.BOARD.xy[b_id], float)
    pa, pb = to_px(a), to_px(b)
    d = pb - pa
    L = np.linalg.norm(d)
    if L < 1:
        return 255.0, 0.0
    u = d / L
    nv = np.array([-u[1], u[0]])
    offs = np.arange(-half, half + 1)
    dark = []
    for i in range(n):
        t = i / n
        p = pa + (pb - pa) * t
        X = np.clip(np.round(p[0] + nv[0] * offs).astype(int), 0, GREY.shape[1] - 1)
        Y = np.clip(np.round(p[1] + nv[1] * offs).astype(int), 0, GREY.shape[0] - 1)
        dark.append(GREY[Y, X].min())
    dark = np.array(dark)
    return dark.mean(), float((dark < 170).mean())


def main():
    sys.path.insert(0, os.path.join(HERE, "..", "server"))
    from engine.geometry_dxf import Board, parse, ARMY_CN
    import engine.geometry_dxf as G
    G.BOARD = Board()

    print("=== 映射自检：几个格点应落在格点上")
    for pid in ["111", "119", "211", "219", "311", "319", "255", "155", "355", "234"]:
        px = to_px(G.BOARD.xy[pid])
        print(f"  {pid} -> px({px[0]:7.1f},{px[1]:7.1f})")

    print("\n=== 对照组 A：原图一定有的线")
    for a, b in [("119", "111"), ("219", "211"), ("319", "311"), ("211", "119"),
                 ("111", "319"), ("311", "219"), ("155", "255"), ("155", "355"),
                 ("255", "355"), ("115", "155"), ("215", "255"), ("315", "355"),
                 ("234", "244"), ("234", "224"), ("234", "235"), ("234", "233")]:
        m, r = seg_stats(a, b)
        print(f"  {a}--{b}: 平均最暗={m:6.1f}  暗占比={r*100:5.1f}%")

    print("\n=== 对照组 B：绝不可能有的线（穿棋盘内部）")
    for a, b in [("111", "219"), ("119", "311"), ("211", "319"), ("115", "315"),
                 ("234", "155"), ("236", "156"), ("119", "211")]:
        m, r = seg_stats(a, b)
        print(f"  {a}--{b}: 平均最暗={m:6.1f}  暗占比={r*100:5.1f}%")

    print("\n=== 关键待测：M6(234) -> 魏 4 线")
    for a, b in [("234", "156"), ("234", "146"), ("234", "136"), ("234", "126"),
                 ("234", "116"),
                 ("254", "156"), ("254", "155"),
                 ("252", "158"), ("253", "157"), ("251", "159"),
                 ("256", "154"), ("257", "153"), ("258", "152"), ("259", "151")]:
        m, r = seg_stats(a, b)
        print(f"  {a}--{b}: 平均最暗={m:6.1f}  暗占比={r*100:5.1f}%")


if __name__ == "__main__":
    main()
