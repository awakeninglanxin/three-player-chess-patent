# -*- coding: utf-8 -*-
"""图像「线存在性」检测：
把候选线段映射回原图，沿线段密集采样灰度（横向 ±6px 取最暗），
若整条都暗 → 原图确实画了这条线。

用来回答：M6(234) 与魏的 4 线之间，棋盘上到底有没有画连线。
"""
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
IMG = os.path.join(HERE, "..", "docs", "专利版棋盘原图.jpg")
H_IMG = 1279.0

VERT = [
    ((351.0, 1216.0), (-52.02, -90.10)),
    ((1149.0, 1248.0), (52.02, -90.10)),
    ((1528.0, 616.0), (104.04, 0.00)),
    ((1140.0, 48.0), (52.02, 90.10)),
    ((391.0, 63.0), (-52.02, 90.10)),
    ((26.0, 646.0), (-104.04, 0.00)),
]


def fit_homography():
    """DXF -> 图像像素 的单应（6 组顶点，最小二乘）"""
    src, dst = [], []
    for (ix, iy), (dx, dy) in VERT:
        src.append([dx, dy, 1.0])
        dst.append([ix, H_IMG - iy])          # 图 y 向下
    src = np.array(src, float)
    dst = np.array(dst, float)
    # 直接解 H：src @ H_row = dst_x / dst_y
    A = []
    b = []
    for (x, y, w), (X, Y) in zip(src, dst):
        A.append([x, y, w, 0, 0, 0, -X * x, -X * y, -X * w]); b.append(0)
        A.append([0, 0, 0, x, y, w, -Y * x, -Y * y, -Y * w]); b.append(0)
    # 这里用更稳的 DLT（含归一化）
    Hm = cv2.findHomography(src[:, :2], dst, 0)[0]
    return Hm


def to_px(H, pt):
    v = H @ np.array([pt[0], pt[1], 1.0])
    return v[0] / v[2], v[1] / v[2]


def darkness(img, H, a, b, half=6.0, n=160):
    """沿 a->b 采样，返回平均最暗灰度与「暗像素占比」"""
    g = img
    rec = []
    for i in range(n + 1):
        t = i / n
        x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        # 横向法向
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = np.hypot(dx, dy) or 1.0
        nx, ny = -dy / L, dx / L
        vals = []
        for s in np.linspace(-half, half, int(2 * half) + 1):
            px = int(round(x + nx * s))
            py = int(round(y + ny * s))
            if 0 <= py < g.shape[0] and 0 <= px < g.shape[1]:
                vals.append(g[py, px])
        if vals:
            rec.append(min(vals))
    rec = np.array(rec)
    return rec.mean(), float((rec < 150).mean())


def main():
    sys.path.insert(0, os.path.join(HERE, "..", "server"))
    from engine.geometry_dxf import Board, parse, ARMY_CN
    B = Board()
    Hm = fit_homography()
    img = cv2.imdecode(np.fromfile(IMG, dtype=np.uint8), cv2.IMREAD_COLOR)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 先核对：已知存在的线
    print("=== 对照组（这些线原图一定有）")
    KNOWN = [("119", "111"), ("219", "211"), ("319", "311"),
             ("211", "119"), ("111", "319"), ("311", "219"),
             ("155", "255"), ("155", "355"), ("255", "355"),
             ("115", "155"), ("215", "255"), ("315", "355"),
             ("234", "244"), ("234", "224")]
    for a, b in KNOWN:
        pa, pb = to_px(Hm, B.xy[a]), to_px(Hm, B.xy[b])
        m, r = darkness(img, Hm, pa, pb)
        print(f"  {a}--{b}: 平均最暗={m:6.1f}  暗占比={r*100:5.1f}%")

    print("\n=== 对照组（这些线原图一定没有：斜穿棋盘）")
    NEG = [("111", "219"), ("119", "311"), ("211", "319"),
           ("115", "115"), ("234", "155"), ("236", "156")]
    for a, b in NEG:
        pa, pb = to_px(Hm, B.xy[a]), to_px(Hm, B.xy[b])
        m, r = darkness(img, Hm, pa, pb)
        print(f"  {a}--{b}: 平均最暗={m:6.1f}  暗占比={r*100:5.1f}%")

    print("\n=== 关键待测：M6(234) 通往魏的各候选连线")
    CAND = [("234", "156"),   # 吴列4内端 -> 魏列6内端（数字和=10 的对应）
            ("234", "146"), ("234", "136"), ("234", "126"), ("234", "116"),
            ("254", "156"),   # 内端之间的直接连线
            ("254", "155"),
            ("234", "155")]
    for a, b in CAND:
        pa, pb = to_px(Hm, B.xy[a]), to_px(Hm, B.xy[b])
        m, r = darkness(img, Hm, pa, pb)
        print(f"  {a}--{b}: 平均最暗={m:6.1f}  暗占比={r*100:5.1f}%")


if __name__ == "__main__":
    main()
