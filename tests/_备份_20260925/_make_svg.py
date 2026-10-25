# -*- coding: utf-8 -*-
"""生成三张 SVG 示意图（给老师指认用）：
  1) 棋盘标签体系全图（字母行标 A..O + 三底边数字 1..9）
  2) 例① O1 、例② O5 的射线（与模型吻合）
  3) 例③ M6 的实际情况（与模型不吻合，需要老师定夺）
坐标：DXF -> SVG： sx = CX + x*S ; sy = CY - y*S
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
LETTER = {}
for a, base in ((1, "E"), (2, "O"), (3, "J")):
    for r in range(1, 6):
        LETTER[(a, r)] = chr(ord(base) - (r - 1))

W, S = 680, 2.85
CX, CY = 340.0, 296.0


def P(p):
    x, y = B.xy[p]
    return CX + x * S, CY - y * S


def path_of(ids):
    pts = [P(p) for p in ids]
    return "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in pts)


def outward(p):
    x, y = B.xy[p]
    L = np.hypot(x, y) or 1
    return x / L, y / L


def dots(ids=None):
    s = []
    for p in (ids or B.ids):
        x, y = P(p)
        s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1.6" fill="#888780"/>')
    return "\n".join(s)


def outline(ids_line):
    return (f'<path d="{path_of(ids_line)}" fill="none" stroke="#5F5E5A" '
            f'stroke-width="1.2" stroke-linejoin="round"/>')


E6 = ["119", "118", "117", "116", "115", "114", "113", "112", "111"]
E4 = ["219", "218", "217", "216", "215", "214", "213", "212", "211"]
E2 = ["319", "318", "317", "316", "315", "314", "313", "312", "311"]
E5 = ["211", "221", "231", "241", "251", "159", "149", "139", "129", "119"]
E1 = ["111", "121", "131", "141", "151", "359", "349", "339", "329", "319"]
E3 = ["311", "321", "331", "341", "351", "259", "249", "239", "229", "219"]
HEX = ["111", "319", "311", "219", "211", "119", "111"]


def digits_and_letters(show_digits=True, show_letters=True, dcol="#A32D2D",
                       lcol="#185FA5", dsize=12.5, lsize=13):
    s = []
    if show_digits:
        for row, base in ((1, E6), (2, E4), (3, E2)):
            for i, pid in enumerate(base):
                x, y = P(pid)
                ox, oy = outward(pid)
                tx, ty = x + ox * 25, y - oy * 25
                s.append(f'<text x="{tx:.1f}" y="{ty:.1f}" fill="{dcol}" '
                         f'font-size="{dsize}" font-weight="500" '
                         f'text-anchor="middle" dominant-baseline="central">'
                         f'{i + 1}</text>')
    if show_letters:
        for a in (1, 2, 3):
            for r in range(1, 6):
                pid = f"{a}{r}9"
                x, y = P(pid)
                ox, oy = outward(pid)
                tx, ty = x + ox * 21, y - oy * 21
                s.append(f'<text x="{tx:.1f}" y="{ty:.1f}" fill="{lcol}" '
                         f'font-size="{lsize}" font-weight="500" '
                         f'text-anchor="middle" dominant-baseline="central">'
                         f'{LETTER[(a, r)]}</text>')
    return "\n".join(s)


HEAD = ('<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" '
        'role="img" font-family="system-ui,-apple-system,Segoe UI,sans-serif">')


def svg_open(title, desc, h):
    return (HEAD.format(W=W, H=h) + f"\n<title>{title}</title>\n<desc>{desc}</desc>\n")


# ---------------------------------------------------------------- 图 1
def fig1():
    h = 600
    s = [svg_open("三人象棋棋盘标签体系", "六边形棋盘、135 个格点、三方底边数字 1-9 与行字母 A-O", h)]
    s.append(outline(HEX))
    s.append(dots())
    for L, col in ((E6, "#E24B4A"), (E4, "#E24B4A"), (E2, "#E24B4A")):
        s.append(f'<path d="{path_of(L)}" fill="none" stroke="{col}" '
                 f'stroke-width="2.2"/>')
    s.append(digits_and_letters())
    s.append('<rect x="40" y="20" width="600" height="46" rx="8" fill="#F1EFE8" '
             'stroke="#B4B2A9" stroke-width="0.5"/>')
    s.append('<text x="52" y="38" fill="#2C2C2A" font-size="13" font-weight="500">'
             '红数字＝三方底边数字 1–9（图1=车 … 图5=帅 … 图9=车）</text>')
    s.append('<text x="52" y="56" fill="#185FA5" font-size="13" font-weight="500">'
             '蓝字母＝行标 A–O：魏行1=E、吴行1=O、蜀行1=J（贴在各行「列9」端）</text>')
    s.append('<text x="340" y="580" fill="#5F5E5A" font-size="12" '
             'text-anchor="middle">老师的坐标 = 行字母 + 图中数字，例：吴O1 = 吴行1第9列</text>')
    s.append("</svg>")
    return "\n".join(s)


# ---------------------------------------------------------------- 图 2
def fig2():
    h = 600
    s = [svg_open("O1 与 O5 两条例子", "吴左车在 O1 沿直线吃蜀 9 线；吴车在 O5 直射过河后兼顾魏5蜀5", h)]
    s.append(outline(HEX))
    s.append(dots())
    s.append('<path d="%s" fill="none" stroke="#1D9E75" stroke-width="3"/>'
             % path_of(["219", "229", "239", "249", "259", "351", "341", "331", "321", "311"]))
    s.append('<path d="%s" fill="none" stroke="#BA7517" stroke-width="3"/>'
             % path_of(["215", "225", "235", "245", "255"]))
    s.append('<path d="%s" fill="none" stroke="#BA7517" stroke-width="3" '
             'stroke-dasharray="6 4"/>' % path_of(["255", "155", "145", "135", "125", "115"]))
    s.append('<path d="%s" fill="none" stroke="#BA7517" stroke-width="3" '
             'stroke-dasharray="6 4"/>' % path_of(["255", "355", "345", "335", "325", "315"]))
    for pid, col, r in (("219", "#0F6E56", 6), ("311", "#0F6E56", 5),
                        ("215", "#854F0B", 6), ("155", "#854F0B", 5),
                        ("355", "#854F0B", 5)):
        x, y = P(pid)
        s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{col}"/>')
    for pid, txt, col, dx, dy, anc in (
            ("219", "O1 吴左车", "#0F6E56", 16, -12, "start"),
            ("311", "蜀图9", "#0F6E56", -12, -14, "end"),
            ("215", "O5", "#854F0B", -18, 6, "end"),
            ("155", "魏5(155)", "#854F0B", -14, 4, "end"),
            ("355", "蜀5(355)", "#854F0B", 14, -6, "start")):
        x, y = P(pid)
        s.append(f'<text x="{x + dx:.1f}" y="{y + dy:.1f}" fill="{col}" '
                 f'font-size="12.5" font-weight="500" text-anchor="{anc}">{txt}</text>')
    s.append('<rect x="40" y="20" width="600" height="64" rx="8" fill="#F1EFE8" '
             'stroke="#B4B2A9" stroke-width="0.5"/>')
    s.append('<text x="52" y="39" fill="#0F6E56" font-size="13" font-weight="500">'
             '例① 吴左车在 O1(219)：直射到蜀的 9 线（图9＝蜀311）—— 1+9=10，与模型一致</text>')
    s.append('<text x="52" y="58" fill="#854F0B" font-size="13" font-weight="500">'
             '例② 吴车在 O5(215)：经吴5线到 255(吴5-5)，再分两路 155(魏5-5)/355(蜀5-5)</text>')
    s.append('<text x="52" y="77" fill="#5F5E5A" font-size="12">'
             '255 处的「两条路」＝中央小三角（155-255-355）的两条边，与您说的完全吻合</text>')
    s.append('<text x="340" y="580" fill="#5F5E5A" font-size="12" '
             'text-anchor="middle">实线＝同一条直射线；虚线＝过河后的两条分岔</text>')
    s.append("</svg>")
    return "\n".join(s)


# ---------------------------------------------------------------- 图 3
def fig3():
    h = 620
    s = [svg_open("M6 与魏 4 线不连通", "吴车在 M6(234) 的实际射线，和魏的 4 线之间没有棋盘连线", h)]
    s.append(outline(HEX))
    s.append(dots())
    s.append('<path d="%s" fill="none" stroke="#1D9E75" stroke-width="3"/>'
             % path_of(["214", "224", "234", "244", "254"]))
    s.append('<path d="%s" fill="none" stroke="#639922" stroke-width="2.4"/>'
             % path_of(["231", "232", "233", "234", "235", "236", "237", "238", "239"]))
    s.append('<path d="%s" fill="none" stroke="#A32D2D" stroke-width="3"/>'
             % path_of(["116", "126", "136", "146", "156"]))
    s.append('<path d="%s" fill="none" stroke="#A32D2D" stroke-width="2" '
             'stroke-dasharray="5 5"/>' % path_of(["254", "156"]))
    x1, y1 = P("254")
    x2, y2 = P("156")
    s.append(f'<text x="{(x1 + x2) / 2:.1f}" y="{(y1 + y2) / 2 - 8:.1f}" fill="#A32D2D" '
             f'font-size="12" font-weight="500" text-anchor="middle">缺口 24.9 单位（DXF 无此线）</text>')
    for pid, col, r, txt, dx, dy, anc in (
            ("234", "#0F6E56", 6, "M6(234) 吴行3列4", 14, -10, "start"),
            ("254", "#1D9E75", 4.5, "254 吴列4 内端", -12, 4, "end"),
            ("156", "#A32D2D", 4.5, "156 魏列6 内端", 14, -4, "start"),
            ("115", "#A32D2D", 4.5, "魏图4线", 26, 0, "start")):
        x, y = P(pid)
        s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{col}"/>')
        s.append(f'<text x="{x + dx:.1f}" y="{y + dy:.1f}" fill="{col}" '
                 f'font-size="12.5" font-weight="500" text-anchor="{anc}">{txt}</text>')
    s.append('<rect x="40" y="20" width="600" height="84" rx="8" fill="#F1EFE8" '
             'stroke="#B4B2A9" stroke-width="0.5"/>')
    s.append('<text x="52" y="39" fill="#0F6E56" font-size="13" font-weight="500">'
             'M6=234(吴行3列4)，数字和 6+4=10 → 对应「魏图4线」＝魏列6(116…156)</text>')
    s.append('<text x="52" y="58" fill="#5F5E5A" font-size="12.5">'
             '234 自身只有两条直线：吴列4 与 吴行3（全在吴方境内，跨不过河）</text>')
    s.append('<text x="52" y="77" fill="#A32D2D" font-size="12.5" font-weight="500">'
             '吴列4 内端(254) 与 魏列6 内端(156) 相距 24.9，且方向差 130°——DXF 里没有连线</text>')
    s.append('<text x="52" y="96" fill="#5F5E5A" font-size="12">'
             '结论：现有射线模型下，吴方任何中间列的车都到不了魏方；只有列1/列9/列5 能过河</text>')
    s.append('<text x="340" y="600" fill="#5F5E5A" font-size="12" '
             'text-anchor="middle">绿＝234 的射线（吴列4 / 吴行3）；红＝魏图4线（魏列6）</text>')
    s.append("</svg>")
    return "\n".join(s)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for i, f in enumerate((fig1, fig2, fig3), 1):
        p = os.path.join(OUT, f"svg_{i}.svg")
        open(p, "w", encoding="utf-8").write(f())
        print("已写", p, os.path.getsize(p), "字节")
