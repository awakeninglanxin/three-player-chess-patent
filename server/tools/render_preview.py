# -*- coding: utf-8 -*-
"""专利版棋盘对照渲染器 v6（正交方格网 + 窄中心地带）

v5 仍不对，根因是**网格类型判错**：
  原图里每方的格子是**正方形**（正交的横竖线），三方各是一个标准中国象棋式的
  方格网，整体旋转 120 度拼成正六边形。
  我之前一直画「菱格（斜交 60 度）」，所以格子形状、密度、地带宽度全都对不上。

本版结构（对照老师红色标注图）：
  · 正六边形边长 8 格（格宽 1）
  · 每方：正交方格网，底线 9 点（8 格），行高 = 格宽 = 1
  · 区域为梯形，向中心收窄，每行两侧各内移 INSET 格
  · 三条中心地带：窄带（宽约 1 格）——赤壁 / 荆州 / 祁山
  · 中央三角区：小三角形（边长约 1 格），三条地带的交汇中心

跑法：cd 中国三人象棋_专利版/server && python tools/render_preview.py
"""
import math
import os

A6 = 8.0                    # 六边形边长（格）
H6 = A6 * math.sqrt(3) / 2
N_ROW = 6                   # 行数（经叠加自检校准）
INSET = 0.40                # 每行两侧各内移格数（经叠加自检校准）
ROW_H = 0.866               # 行高 = 格宽 × sin60（原图格子略扁）
BAND_W = 1.0                # 中心地带宽度（格）= 中央三角区边长

COLORS = {1: "#2b6cb0", 2: "#c53030", 3: "#2f855a"}
BANDC = "#d9532c"
ARMY_CN = {1: "魏", 2: "蜀", 3: "吴"}

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
C = (A6, 0.0)


def hexagon():
    """0=左上 1=右上 2=右 3=右下 4=左下 5=左"""
    return [(A6 / 2, H6), (3 * A6 / 2, H6), (2 * A6, 0.0),
            (3 * A6 / 2, -H6), (A6 / 2, -H6), (0.0, 0.0)]


HEXP = hexagon()


def unit(v):
    L = math.hypot(*v) or 1.0
    return (v[0] / L, v[1] / L)


def frame(army):
    """底线中点 / 底线方向 / 内向法向（正交基，ex·ey=0）"""
    idx = {1: 3, 2: 1, 3: 5}[army]
    p1, p2 = HEXP[idx], HEXP[(idx + 1) % 6]
    o = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
    ex = unit((p2[0] - p1[0], p2[1] - p1[1]))
    ey = unit((C[0] - o[0], C[1] - o[1]))
    return o, ex, ey


def to_world(army, x, y):
    o, ex, ey = frame(army)
    return (o[0] + x * ex[0] + y * ey[0], o[1] + x * ex[1] + y * ey[1])


def army_rows(army):
    rows = []
    for k in range(N_ROW):
        left = -A6 / 2 + INSET * k
        right = A6 / 2 - INSET * k
        n = int(round(right - left)) + 1
        if n < 2:
            break
        step = (right - left) / (n - 1)
        rows.append([to_world(army, left + step * i, k * ROW_H) for i in range(n)])
    return rows


def tri_verts():
    r = BAND_W / math.sqrt(3)
    return [(C[0] + r * math.cos(math.radians(a)), C[1] + r * math.sin(math.radians(a)))
            for a in (-90, 30, 150)]


def band_polys():
    tv = tri_verts()
    spec = [("荆州", 2, (tv[2], tv[1]), 0),
            ("祁山", 3, (tv[1], tv[0]), 2),
            ("赤壁", 1, (tv[0], tv[2]), 4)]
    out = []
    for name, army, (p, q), ei in spec:
        e1, e2 = HEXP[ei], HEXP[(ei + 1) % 6]
        out.append((name, army, [p, q, e2, e1]))
    return out


def build():
    rows = {a: army_rows(a) for a in (1, 2, 3)}
    bands = band_polys()
    pts = [p for a in rows for row in rows[a] for p in row]
    allp = pts + [p for _, _, poly in bands for p in poly]
    xs = [p[0] for p in allp]
    ys = [p[1] for p in allp]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    S, PAD = 30.0, 60
    W, H = (x1 - x0) * S + PAD * 2, (y1 - y0) * S + PAD * 2

    def px(p):
        return (PAD + (p[0] - x0) * S, PAD + (y1 - p[1]) * S)

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H:.0f}" '
         f'width="{W:.0f}" height="{H:.0f}" style="background:#fff">']
    hp = " ".join(f"{px(p)[0]:.1f},{px(p)[1]:.1f}" for p in HEXP)
    o.append(f'<polygon points="{hp}" fill="#fdfcfa" stroke="#202124" stroke-width="3"/>')

    for a in (1, 2, 3):
        poly = rows[a][-1] + list(reversed(rows[a][0]))
        pp = " ".join(f"{px(p)[0]:.1f},{px(p)[1]:.1f}" for p in poly)
        o.append(f'<polygon points="{pp}" fill="{COLORS[a]}" fill-opacity=".06" stroke="none"/>')

    for name, army, poly in bands:
        pp = " ".join(f"{px(p)[0]:.1f},{px(p)[1]:.1f}" for p in poly)
        o.append(f'<polygon points="{pp}" fill="{BANDC}" fill-opacity=".18" '
                 f'stroke="{BANDC}" stroke-width="1.8"/>')
        mx = sum(p[0] for p in poly) / 4
        my = sum(p[1] for p in poly) / 4
        dx = (poly[2][0] + poly[3][0]) / 2 - mx
        dy = (poly[2][1] + poly[3][1]) / 2 - my
        c = px((mx + dx * 0.5, my + dy * 0.5))
        o.append(f'<text x="{c[0]:.1f}" y="{c[1]:.1f}" font-size="15" font-weight="700" '
                 f'fill="#b8441f" text-anchor="middle" dominant-baseline="central">{name}</text>')

    tv = tri_verts()
    tp = " ".join(f"{px(p)[0]:.1f},{px(p)[1]:.1f}" for p in tv)
    o.append(f'<polygon points="{tp}" fill="#2b6cb0" fill-opacity=".3" '
             f'stroke="#2b6cb0" stroke-width="2.2"/>')

    # 正交方格网：横线 + 竖线
    o.append('<g stroke="#9aa0a6" stroke-width="1.2" fill="none">')
    for a in (1, 2, 3):
        rr = rows[a]
        for row in rr:
            A_, B_ = px(row[0]), px(row[-1])
            o.append(f'<line x1="{A_[0]:.1f}" y1="{A_[1]:.1f}" x2="{B_[0]:.1f}" y2="{B_[1]:.1f}"/>')
        for k in range(len(rr) - 1):
            for p in rr[k]:
                for q in rr[k + 1]:
                    if abs(p[0] - q[0]) < 0.02 or math.dist(p, q) < 1.05:
                        A_, B_ = px(p), px(q)
                        o.append(f'<line x1="{A_[0]:.1f}" y1="{A_[1]:.1f}" '
                                 f'x2="{B_[0]:.1f}" y2="{B_[1]:.1f}"/>')
    o.append('</g>')

    for a in (1, 2, 3):
        for row in rows[a]:
            for p in row:
                c = px(p)
                o.append(f'<circle cx="{c[0]:.1f}" cy="{c[1]:.1f}" r="2.3" fill="#6b7280"/>')
        mid = rows[a][0][len(rows[a][0]) // 2]
        c = px(mid)
        o.append(f'<text x="{c[0]:.1f}" y="{c[1]:.1f}" font-size="26" font-weight="700" '
                 f'fill="{COLORS[a]}" fill-opacity=".38" text-anchor="middle" '
                 f'dominant-baseline="central">{ARMY_CN[a]}</text>')

    o.append('</svg>')
    n = len({(round(p[0], 5), round(p[1], 5)) for p in pts})
    return "\n".join(o), n, [len(rows[a]) for a in (1, 2, 3)]


svg, n, nr = build()
print(f"三方落子点合计 {n}（每方 {n // 3}）  各方行数 {nr}")

html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>专利版棋盘对照 v6</title><style>
body{{margin:0;padding:16px;background:#f4f1ea;font:14px/1.6 "Microsoft YaHei",sans-serif;color:#1f2430}}
h1{{font-size:18px;margin:0 0 4px}} .sub{{color:#6b7280;font-size:12.5px;margin-bottom:12px}}
.row{{display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap}}
.card{{background:#fff;border:1px solid #e2ddd2;border-radius:12px;padding:10px;flex:1;min-width:400px}}
.card h2{{font-size:12.5px;color:#6b7280;margin:0 0 8px}}
.card img,.card svg{{width:100%;height:auto;display:block;border-radius:6px}}
</style></head><body>
<h1>专利版棋盘对照 v6 · 正交方格网</h1>
<div class="sub">左：老师标注的原图　｜　右：重建（每方格网 + 窄中心地带）</div>
<div class="row">
  <div class="card"><h2>原图</h2>
    <img src="专利版棋盘原图 - 去掉字母数字 -红色区域是中间地带.jpg"></div>
  <div class="card"><h2>重建（每方 {n // 3} 点 · {nr[0]} 行）</h2>{svg}</div>
</div>
</body></html>"""

out = os.path.join(ROOT, "docs", "棋盘对照.html")
with open(out, "w", encoding="utf-8") as f:
    f.write(html)
print(f"已生成 {out}")
