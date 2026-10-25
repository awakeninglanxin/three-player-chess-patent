# -*- coding: utf-8 -*-
"""把规则图 §9 的 6 条「帅见面线路」原文，逐条翻译成引擎编号并验证。

规则图 §9 原文（`docs/三人中国象棋的游戏规则.md` 第 120-122 行）：
    对战时，不可把己方帅和对手的帅（主帅和副帅）放在没有棋子阻隔的线路（如图）
    【E5-A5-F5-J5】、【J5-F5-K5-O5】、【O5-K5-A5-E5】、
    【E6-A6-F4-J4】、【J6-F6-K4-O4】、【O6-K6-A4-E4】上。

标签口径：图中数字 d = 10 − 引擎列（`_map_letters.py`，已由棋盘原图 + 引擎坐标双方证实）
"""
import sys
sys.path.insert(0, 'server')
from engine import rules_dxf as R
from engine import geometry_dxf as G
from engine.geometry_dxf import Board as _Board

B = _Board()
CN = {1: '魏', 2: '吴', 3: '蜀'}
P2L = {}
LETTER = {(1, 1): 'E', (1, 2): 'D', (1, 3): 'C', (1, 4): 'B', (1, 5): 'A',
          (2, 1): 'O', (2, 2): 'N', (2, 3): 'M', (2, 4): 'L', (2, 5): 'K',
          (3, 1): 'J', (3, 2): 'I', (3, 3): 'H', (3, 4): 'G', (3, 5): 'F'}
L2P = {}          # 纯标签（如 'E5'） -> 引擎编号
for (a, r), ch in LETTER.items():
    for c in range(1, 10):
        pid = '%d%d%d' % (a, r, c)
        tagname = '%s%d' % (ch, 10 - c)
        P2L[pid] = '%s%s' % (tagname, CN[a])      # 显示用：'E5魏'
        L2P[tagname] = pid                         # 反查用：'E5'


def lab(p):
    return P2L.get(p) or ('?%s' % p)


# 规则图 §9 原文的 6 条线路（图中标签）
LINES_LABEL = [
    ['E5', 'A5', 'F5', 'J5'],
    ['J5', 'F5', 'K5', 'O5'],
    ['O5', 'K5', 'A5', 'E5'],
    ['E6', 'A6', 'F4', 'J4'],
    ['J6', 'F6', 'K4', 'O4'],
    ['O6', 'K6', 'A4', 'E4'],
]

print('=' * 74)
print('【一】§9 六条线路：原文标签 → 引擎编号')
print('=' * 74)
engine_lines = []
for ln in LINES_LABEL:
    ids = [L2P[x] for x in ln]
    engine_lines.append(ids)
    print('  %-22s → %s' % ('-'.join(ln), ' - '.join(ids)))

print()
print('=' * 74)
print('【二】逐条验证：首尾两点是否「共线」（line_of_sight，空盘）')
print('=' * 74)
empty = {'board': {}, 'turn': 1, 'eliminated': [], 'annexed': {}, 'history': [],
         'passed': [], 'winner': None, 'ply': 0, 'first': 1,
         'deputies': {}, 'vitality': {1: True, 2: True, 3: True},
         'combat': {1: True, 2: True, 3: True}, 'out': [], 'declared_lose': []}
ok = 0
for ln, ids in zip(LINES_LABEL, engine_lines):
    a, b = ids[0], ids[-1]
    # 逐段验证相邻点共线
    segs = []
    for i in range(len(ids) - 1):
        segs.append(R.line_of_sight(empty, ids[i], ids[i + 1]))
    both = R.line_of_sight(empty, a, b)
    good = all(segs) and both
    ok += 1 if good else 0
    print('  %-22s 相邻段=%s  首尾(%s-%s)=%s  %s'
          % ('-'.join(ln), segs, a, b, both, '✓' if good else '✗'))
print('  → 6 条线路全部成立：%d / 6' % ok)

print()
print('=' * 74)
print('【三】这 6 条线路落在哪些"军帐内点"上？（决定哪些帅位之间可能见面）')
print('=' * 74)
TENT = {a: set('%d%d%d' % (a, r, c) for r in (1, 2, 3) for c in (4, 5, 6)) for a in (1, 2, 3)}
for ln, ids in zip(LINES_LABEL, engine_lines):
    heads = [p for p in (ids[0], ids[-1])]
    for p in heads:
        a, _r, _c = G.parse(p)
        if p in TENT[a]:
            print('  线路 %-22s 端点 %s(%s) 落在 %s军帐内' % ('-'.join(ln), p, lab(p), CN[a]))

print()
print('=' * 74)
print('【四】★ 完整枚举：军帐内点两两照见（2026-09-24 深夜修正）')
print('=' * 74)
print('  ⚠️ 旧版本这里只取「六条线路的两端」→ 得出"只有 6 对"，**是错的**。')
print('     线路是**整条贯通直线**，军帐里落在其上的点远不止两端：')
print('     列5 贯通线穿过三方军帐的行1/行2/行3，仅列5 上就有 9 个军帐点两两照见。')
print()
# 旧口径（只取端点）—— 保留打印以便对照，但不再作为结论
pairs = []
for ln, ids in zip(LINES_LABEL, engine_lines):
    for x in (ids[0], ids[-1]):
        ax, _rx, _cx = G.parse(x)
        if x not in TENT[ax]:
            continue
        for y in (ids[0], ids[-1]):
            if y == x:
                continue
            ay, _ry, _cy = G.parse(y)
            if y not in TENT[ay] or ax == ay:
                continue
            key = tuple(sorted((x, y)))
            if key not in [tuple(sorted(p)) for p in pairs]:
                pairs.append([key[0], key[1]])
print('  【旧口径·仅端点】%d 对（仅供对照，**不是全部**）' % len(pairs))
# 新口径：完整枚举军帐内所有点对
allp = sorted(p for a in (1, 2, 3) for p in TENT[a])
full = [(allp[i], allp[j]) for i in range(len(allp)) for j in range(i + 1, len(allp))
        if R.line_of_sight(empty, allp[i], allp[j])]
_same = [p for p in full if G.parse(p[0])[0] == G.parse(p[1])[0]]
_cross = [p for p in full if G.parse(p[0])[0] != G.parse(p[1])[0]]
c5 = [p for p in allp if G.parse(p)[2] == 5]
n5 = sum(1 for i in range(len(c5)) for j in range(i + 1, len(c5))
         if R.line_of_sight(empty, c5[i], c5[j]))
print()
print('  【新口径·完整枚举】军帐内点 %d 个' % len(allp))
print('    两两照见 = %d 对（同方 %d / **跨方 %d**）' % (len(full), len(_same), len(_cross)))
print('    其中列5 的 %d 个军帐点 → 照见 %d 对（两两全通）' % (len(c5), n5))
print()
print('  ⇒ 旧结论「帅走到军帐行2 / 行3 时永远不会见面」**被证伪**：')
print('     反例（老师 2026-09-24 实际局面）：I5(325) ↔ O5(215) 照见 = %s'
      % R.line_of_sight(empty, '325', '215'))
print('  ⇒ 完整断言见 tests/_verify_facing_lines.py（34 项 / 9 节）')
print('  ⇒ 「哪些点在同一条线上」一律用 RAYS 实测枚举，不要照抄文档里的旧枚举结论。')
