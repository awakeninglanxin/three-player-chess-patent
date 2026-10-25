# -*- coding: utf-8 -*-
"""验证「数字和=10 共线」规则与当前射线模型是否一致。

坐标约定（由原图标注映射推得，见 _probe_chars.py）：
    每方底线外侧标数字 1..9（从该方视角的左到右 / 图上位置）
    · 魏底线 1-1-x：图上数字 n 落在 DXF 列 (10-n)
    · 吴底线 2-1-x：同上
    · 蜀底线 3-1-x：同上
"""
import sys

sys.path.insert(0, "server")
from engine import geometry_dxf as G          # noqa: E402
from engine import rules_dxf as R             # noqa: E402

B = G.BOARD
CN = G.ARMY_CN

BASE = {}
for a in (1, 2, 3):
    for c in range(1, 10):
        BASE[f"{a}1{c}"] = (a, c)             # 点 -> (方, DXF列)


def pic_num(pid):                             # DXF 点 -> 图上数字
    a, r, c = G.parse(pid)
    return 10 - c


print("=" * 78)
print("① 底线点之间是否共线（沿射线可达）")
print("=" * 78)
lines = {}
for p in BASE:
    a, c = BASE[p]
    reach = []
    for path in R.RAYS.get(p, ()):
        for q in path:
            if q in BASE:
                reach.append(q)
            if q in BASE or True:
                pass
    lines[p] = reach
    txt = ", ".join(f"{q}(图{pic_num(q)})" for q in reach)
    print(f"  {p} 图{pic_num(p)} [{CN[a]}]  →  {txt or '无'}")

print()
print("=" * 78)
print("② 检查规律：图数字 n 的点，能否直达「对面图数字 10-n」的点")
print("=" * 78)
ok = bad = 0
for p in sorted(BASE, key=lambda z: (BASE[z][0], -pic_num(z))):
    a, c = BASE[p]
    n = pic_num(p)
    targets = {q for q in lines[p]}
    tnums = sorted({pic_num(q) for q in targets})
    match = [q for q in targets if pic_num(q) == 10 - n]
    other = [q for q in targets if pic_num(q) != 10 - n]
    flag = "✅" if match else "❌"
    if match:
        ok += 1
    else:
        bad += 1
    print(f"  {flag} {CN[a]}图{n}({p}) → 直达数字 {tnums}"
          + (f"   其中 10-n={10 - n} ✓" if match else f"   ✗ 缺 {10 - n}"))
    if other:
        print(f"       ⚠️ 另有非 10-n 的底线点: "
              + ", ".join(f"{CN[BASE[q][0]]}图{pic_num(q)}({q})" for q in other))
print(f"\n  合计: 命中 {ok} / 缺 {bad}")
