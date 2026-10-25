# -*- coding: utf-8 -*-
"""生成三张结论图（light 主题）：
  F1 坐标体系：行字母 A..O + 底边数字 1..9 + 行线在「列5」的折角
  F2 过河接线：每方「行5列k」→ 对面「行5列(10-k)」，数字和恒为 10
  F3 例③ M6 的完整走线（原来对不上、现在对上的那一条）
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_chars_out")
sys.path.insert(0, os.path.join(HERE, "..", "server"))
from engine.geometry_dxf import Board, parse  # noqa: E402

B = Board()
CN = {1: "魏", 2: "吴", 3: "蜀"}
LET = {}
for a, base in ((1, "E"), (2, "O"), (3, "J")):
    for r in range(1, 6):
        LET[(a, r)] = chr(ord(base) - (r - 1))

W, S, CX, CY = 680, 2.85, 340.0, 300.0
TXT = "system-ui,-apple-system,Segoe UI,sans-serif"


def P(p):
    x, y = B.xy[p]
    return CX + x * S, CY - y * S


def d(ids, col, w=2.6, dash=None, op=1.0):
    pts = " L ".join(f"{x:.1f} {y:.1f}" for p in ids for x, y in [P(p)])
    da = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<path d="M {pts}" fill="none" stroke="{col}" stroke-width="{w}"'
            f'{da} opacity="{op}" stroke-linecap="round"/>')


def all_dots(r=1.5, col="#B4B2A9"):
    return "\n".join(f'<circle cx="{P(p)[0]:.1f}" cy="{P(p)[1]:.1f}" r="{r}" '
                     f'fill="{col}"/>' for p in B.ids)


def outn(p):
    x, y = B.xy[p]
    L = np.hypot(x, y) or 1
    return x / L, y / L


def open_svg(title, desc, h):
    return (f'<svg viewBox="0 0 {W} {h}" width="100%" '
            f'xmlns="http://www.w3.org/2000/svg" role="img" font-family="{TXT}">\n'
            f'<title>{title}</title>\n<desc>{desc}</desc>\n')


HEX = ["111", "319", "311", "219", "211", "119", "111"]
E6 = ["119", "118", "117", "116", "115", "114", "113", "112", "111"]
E4 = ["219", "218", "217", "216", "215", "214", "213", "212", "211"]
E2 = ["319", "318", "317", "316", "315", "314", "313", "312", "311"]


def labels(dcol="#A32D2D", lcol="#185FA5", ds=12.5, ls=12.5, do=25, lo=21):
    s = []
    for base in (E6, E4, E2):
        for i, pid in enumerate(base):
            x, y = P(pid)
            ox, oy = outn(pid)
            s.append(f'<text x="{x + ox * do:.1f}" y="{y - oy * do:.1f}" fill="{dcol}" '
                     f'font-size="{ds}" font-weight="500" text-anchor="middle" '
                     f'dominant-baseline="central">{i + 1}</text>')
    for a in (1, 2, 3):
        for r in range(1, 6):
            pid = f"{a}{r}9"
            x, y = P(pid)
            ox, oy = outn(pid)
            s.append(f'<text x="{x + ox * lo:.1f}" y="{y - oy * lo:.1f}" fill="{lcol}" '
                     f'font-size="{ls}" font-weight="500" text-anchor="middle" '
                     f'dominant-baseline="central">{LET[(a, r)]}</text>')
    return "\n".join(s)


def note(y, lines):
    s = [f'<rect x="40" y="{y}" width="600" height="{16 * len(lines) + 16}" rx="8" '
         f'fill="#F1EFE8" stroke="#B4B2A9" stroke-width="0.5"/>']
    for i, (t, c, w) in enumerate(lines):
        s.append(f'<text x="52" y="{y + 26 + i * 16}" fill="{c}" font-size="12.5" '
                 f'font-weight="{w}">{t}</text>')
    return "\n".join(s)


# ------------------------------------------------------------------ F1
def f1():
    h = 640
    s = [open_svg("三人象棋坐标体系", "行字母 A 到 O、底边数字 1 到 9、行线在列 5 的折角", h)]
    s.append(d(HEX, "#5F5E5A", 1.2))
    s.append(all_dots())
    for L in (E6, E4, E2):
        s.append(d(L, "#E24B4A", 2.4))
    s.append(labels())
    s.append(d(B.rows[(2, 3)], "#639922", 3.0))
    bx, by = P("235")
    s.append(f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="5" fill="#3B6D11"/>')
    s.append(f'<text x="{bx - 14:.1f}" y="{by + 18:.1f}" fill="#3B6D11" font-size="12.5" '
             f'font-weight="500" text-anchor="end">行线在此折 29.2°</text>')
    s.append(note(16, [
        ("红数字＝三方底边数字 1–9（图1＝车 … 图5＝帅 … 图9＝车）", "#A32D2D", 500),
        ("蓝字母＝行标：魏行1＝E、吴行1＝O、蜀行1＝J（贴在各行「列9」端）", "#185FA5", 500),
        ("绿线＝吴行M（行3）；行1（E/J/O）是直线，行2–5 在列5 处折角 16.3°/29.2°/39.4°/47.6°", "#3B6D11", 500),
    ]))
    s.append(f'<text x="340" y="{h - 20}" fill="#5F5E5A" font-size="12" '
             f'text-anchor="middle">老师的坐标＝行字母＋图中数字：吴O1＝吴行1第9列；吴M6＝吴行3第4列</text>')
    s.append("</svg>")
    return "\n".join(s)


# ------------------------------------------------------------------ F2
def f2():
    h = 640
    s = [open_svg("过河接线（数字和恒为 10）", "每方行5列k 沿本方列1或列9方向过河，命中对方行5列10减k", h)]
    s.append(d(HEX, "#5F5E5A", 1.2))
    s.append(all_dots(1.4))
    want = {1: 9, 2: 8, 3: 7, 4: 6, 5: 5, 6: 4, 7: 3, 8: 2, 9: 1}
    for k in range(1, 10):
        q = want[k]
        if k <= 5:
            a, b = f"2 5{k}".replace(" ", ""), f"1 5{q}".replace(" ", "")
            col = "#1D9E75"
        if k >= 5:
            a2, b2 = f"2 5{k}".replace(" ", ""), f"3 5{q}".replace(" ", "")
            col2 = "#BA7517"
        if k <= 5:
            s.append(d([a, b], col, 2.6))
        if k >= 5:
            s.append(d([a2, b2], col2, 2.6))
    s.append(d(B.rows[(2, 5)], "#0F6E56", 2.0, op=0.85))
    s.append(d(B.rows[(1, 5)], "#0F6E56", 2.0, op=0.85))
    s.append(d(B.rows[(3, 5)], "#BA7517", 2.0, op=0.85))
    for pid, col, t, dx, dy, an in (
            ("259", "#1D9E75", "k=9→蜀列1 (1+9=10)", 12, -10, "start"),
            ("255", "#0F6E56", "k=5→魏列5 且 蜀列5", 0, -20, "middle"),
            ("251", "#1D9E75", "k=1→魏列9 (9+1=10)", -12, 4, "end")):
        x, y = P(pid)
        s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{col}"/>')
        s.append(f'<text x="{x + dx:.1f}" y="{y + dy:.1f}" fill="{col}" font-size="12" '
                 f'font-weight="500" text-anchor="{an}">{t}</text>')
    s.append(note(16, [
        ("每方 9 个前沿点(行5列k)，各自向【就近那一侧】的对手过河，接到对方行5列(10−k)", "#2C2C2A", 500),
        ("绿＝吴→魏过河段；橙＝吴→蜀过河段（同一结构在魏方、蜀方各旋转 120° 复制一份）", "#5F5E5A", 400),
        ("三处天然共线：k=9→蜀列1、k=1→魏列9、k=5↔5 —— 也就是您说的「只有 1↔9 天然共线」", "#993C1D", 500),
    ]))
    s.append(f'<text x="340" y="{h - 20}" fill="#5F5E5A" font-size="12" '
             f'text-anchor="middle">全盘 3 方 × 9 列 × 2 侧 = 54 条过河段，逐条数值验证全部精确命中</text>')
    s.append("</svg>")
    return "\n".join(s)


# ------------------------------------------------------------------ F3
def f3():
    h = 640
    s = [open_svg("例③ M6 的完整走线", "吴车在 M6 沿吴列4 到前沿，过河接魏列6（魏图4线）", h)]
    s.append(d(HEX, "#5F5E5A", 1.2))
    s.append(all_dots(1.4))
    s.append(d(["214", "224", "234", "244", "254"], "#1D9E75", 3.2))
    s.append(d(["254", "156"], "#0F6E56", 3.2, dash="7 5"))
    s.append(d(["156", "146", "136", "126", "116"], "#A32D2D", 3.2))
    s.append(d(B.rows[(2, 3)], "#C0DD97", 2.4))
    for pid, col, r, t, dx, dy, an in (
            ("234", "#0F6E56", 6, "M6 = 234", 15, -10, "start"),
            ("254", "#0F6E56", 5, "254 前沿", -12, 6, "end"),
            ("156", "#A32D2D", 5, "156", 13, -4, "start"),
            ("115", "#A32D2D", 5, "魏图4线(116…156)", 24, 2, "start")):
        x, y = P(pid)
        s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{col}"/>')
        s.append(f'<text x="{x + dx:.1f}" y="{y + dy:.1f}" fill="{col}" font-size="12.5" '
                 f'font-weight="500" text-anchor="{an}">{t}</text>')
    mx = (P("254")[0] + P("156")[0]) / 2
    my = (P("254")[1] + P("156")[1]) / 2
    s.append(f'<text x="{mx - 6:.1f}" y="{my + 16:.1f}" fill="#0F6E56" font-size="12" '
             f'font-weight="500" text-anchor="end">过河 24.9</text>')
    s.append(note(16, [
        ("M6 在图上的数字是 6，自身列是「列4」；6+4=10 → 对应魏的 4 线＝魏列6（116…156）", "#2C2C2A", 500),
        ("走线：234 →244 →254（吴前沿）→ 过河 →156 →146 →136 →126 →116，吃路上第一个挡子", "#0F6E56", 500),
        ("浅绿＝吴行M（行3）的横向线，有折角；本走线不用它，只用「列」方向", "#5F5E5A", 400),
    ]))
    s.append(f'<text x="340" y="{h - 20}" fill="#5F5E5A" font-size="12" '
             f'text-anchor="middle">吴列4 与 魏列6 在 DXF 里没有画连线；过河段是网格构造自带的方向（−60°）</text>')
    s.append("</svg>")
    return "\n".join(s)


if __name__ == "__main__":
    for i, f in enumerate((f1, f2, f3), 1):
        p = os.path.join(OUT, f"fig{i}.svg")
        open(p, "w", encoding="utf-8").write(f())
        print("已写", p, os.path.getsize(p))
