# -*- coding: utf-8 -*-
"""用「沿 DXF 已知线最大化暗度」自动校准 DXF->原图 的单应映射，
然后用校准后的映射做【线存在性】判定。

思路：DXF 的 51 条线在原图上一定画着 -> 沿这些线采样应当最暗。
     以 8 个单应参数为变量，Nelder-Mead 最小化「已知线上采样点的平均最暗灰度」。
     校准后，已知线应显著变暗，未知线（斜穿棋盘）应仍亮。
"""
import os
import sys

import cv2
import numpy as np
from scipy.optimize import minimize

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
HALF = 5          # 横向搜索半径（像素）
GREY = None


def init_homography():
    src = np.array([[d[0], d[1]] for _, d in VERT], np.float32)
    dst = np.array([[i[0], H_IMG - i[1]] for i, _ in VERT], np.float32)
    return cv2.findHomography(src, dst, 0)[0]


def build_samples(B, per_seg=24):
    """所有 DXF 线上相邻点对构成的采样点 + 该段的方向"""
    pts, seg = [], []
    for L in B.lines:
        for i in range(len(L) - 1):
            p, q = L[i], L[i + 1]
            a = np.array(B.xy[p], float)
            b = np.array(B.xy[q], float)
            d = b - a
            n = np.linalg.norm(d)
            u = d / n if n else np.array([1.0, 0.0])
            nv = np.array([-u[1], u[0]])
            for t in np.linspace(0, 1, per_seg, endpoint=False):
                pts.append(a + (b - a) * t)
                seg.append(nv)
    return np.array(pts), np.array(seg)


def sample_map(H, pts, perp):
    """把 DXF 点映射到像素，并在法向 ±HALF 内取最暗灰度（向量化）"""
    v = np.hstack([pts, np.ones((len(pts), 1))]) @ H.T
    xy = v[:, :2] / v[:, 2:3]
    offs = np.arange(-HALF, HALF + 1)
    # 每个采样点的法向（在 DXF 空间 -> 近似用像素空间方向）
    v2 = np.hstack([pts + perp * 0.5, np.ones((len(pts), 1))]) @ H.T
    d2 = v2[:, :2] / v2[:, 2:3] - xy
    d2 /= (np.linalg.norm(d2, axis=1, keepdims=True) + 1e-9)
    X = xy[:, 0:1] + d2[:, 0:1] * offs
    Y = xy[:, 1:2] + d2[:, 1:2] * offs
    Xi = np.clip(np.round(X).astype(np.int32), 0, GREY.shape[1] - 1)
    Yi = np.clip(np.round(Y).astype(np.int32), 0, GREY.shape[0] - 1)
    vals = GREY[Yi, Xi]
    dark = vals.min(axis=1)
    return dark, xy


def main():
    global GREY
    sys.path.insert(0, os.path.join(HERE, "..", "server"))
    from engine.geometry_dxf import Board
    B = Board()
    GREY = cv2.cvtColor(cv2.imdecode(np.fromfile(IMG, dtype=np.uint8),
                                     cv2.IMREAD_COLOR), cv2.COLOR_BGR2GRAY)
    pts, perp = build_samples(B)
    print(f"采样点 {len(pts)} 个")

    H0 = init_homography()
    p0 = np.array([H0[0, 0], H0[0, 1], H0[0, 2],
                   H0[1, 0], H0[1, 1], H0[1, 2], H0[2, 0], H0[2, 1]], float)

    def unpack(p):
        return np.array([[p[0], p[1], p[2]], [p[3], p[4], p[5]], [p[6], p[7], 1.0]])

    calls = [0]

    def obj(p):
        calls[0] += 1
        dark, _ = sample_map(unpack(p), pts, perp)
        # 主体：已知线要暗；另加轻微锚定，防止漂走
        return dark.mean() + 3.0 * np.abs(p - p0).mean() / 40.0

    print(f"初始目标 = {obj(p0):.2f}")
    res = minimize(obj, p0, method="Nelder-Mead",
                   options={"maxiter": 4000, "xatol": 1e-4, "fatol": 1e-4})
    print(f"校准后目标 = {res.fun:.2f}  (迭代 {calls[0]} 次)")
    Hc = unpack(res.x)

    # 顶点残差检查
    print("\n校准后六边形顶点落点（应贴住原图六个角）：")
    for (ix, iy), d in VERT:
        v = Hc @ np.array([d[0], d[1], 1.0])
        px, py = v[0] / v[2], v[1] / v[2]
        print(f"  DXF({d[0]:7.2f},{d[1]:7.2f}) -> 像素({px:7.1f},{py:7.1f})"
              f"   应为({ix:6.1f},{H_IMG - iy:6.1f})")

    def seg_dark(a_id, b_id):
        a, b = np.array(B.xy[a_id]), np.array(B.xy[b_id])
        n = np.linalg.norm(b - a)
        d = (b - a) / n
        t = np.linspace(0, 1, 40, endpoint=False)[:, None]
        sp = a + (b - a) * t
        sp = np.hstack([sp, np.ones((len(sp), 1))]) @ Hc.T
        xy = sp[:, :2] / sp[:, 2:3]
        nv = np.array([-d[1], d[0]])
        offs = np.arange(-HALF, HALF + 1)
        v2 = Hc @ np.array([a[0] + nv[0], a[1] + nv[1], 1.0])
        v1 = Hc @ np.array([a[0], a[1], 1.0])
        dv = np.array([v2[0] / v2[2] - v1[0] / v1[2], v2[1] / v2[2] - v1[1] / v1[2]])
        dv = dv / (np.linalg.norm(dv) + 1e-9)
        X = np.clip(np.round(xy[:, 0:1] + dv[0] * offs).astype(int), 0, GREY.shape[1] - 1)
        Y = np.clip(np.round(xy[:, 1:2] + dv[1] * offs).astype(int), 0, GREY.shape[0] - 1)
        dark = GREY[Y, X].min(axis=1)
        return dark.mean(), float((dark < 170).mean())

    print("\n=== 对照组：原图一定有的线（校准后应显著变暗）")
    for a, b in [("119", "111"), ("219", "211"), ("319", "311"), ("211", "119"),
                 ("111", "319"), ("311", "219"), ("155", "255"), ("155", "355"),
                 ("255", "355"), ("115", "155"), ("215", "255"), ("315", "355"),
                 ("234", "244"), ("234", "224")]:
        m, r = seg_dark(a, b)
        print(f"  {a}--{b}: 平均最暗={m:6.1f}  暗占比={r*100:5.1f}%")

    print("\n=== 对照组：横穿棋盘的斜线（原图应当没有）")
    for a, b in [("111", "219"), ("119", "311"), ("211", "319"), ("234", "155"),
                 ("236", "156"), ("115", "315")]:
        m, r = seg_dark(a, b)
        print(f"  {a}--{b}: 平均最暗={m:6.1f}  暗占比={r*100:5.1f}%")

    print("\n=== 关键：M6(234) -> 魏 4 线（魏列6 = 116/126/136/146/156）候选")
    for a, b in [("234", "156"), ("234", "146"), ("234", "136"), ("234", "126"),
                 ("234", "116"), ("254", "156"), ("252", "158"), ("253", "157"),
                 ("256", "154"), ("255", "155")]:
        m, r = seg_dark(a, b)
        print(f"  {a}--{b}: 平均最暗={m:6.1f}  暗占比={r*100:5.1f}%")


if __name__ == "__main__":
    main()
