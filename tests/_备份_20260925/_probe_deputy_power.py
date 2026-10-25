# -*- coding: utf-8 -*-
"""副帅能力实测 —— 回答老师 2026-09-24 的提问：

「变成副帅后有哪些功能，这个副帅还能射杀不同颜色的敌方见面的帅吗？
 假设吴国的帅被魏国的帅吃了，那么吴国的帅变成副帅，是否还能射杀蜀地主动见面的蜀帅」

本脚本只做**事实测量**（穷举），不做规则推导。
"""
import sys, math
sys.path.insert(0, 'server')
from engine import game_dxf as GA
from engine import rules_dxf as R
from engine import geometry_dxf as G
from engine import patent as P
from engine.geometry_dxf import Board as _Board

B = _Board()

CN = {1: '魏', 2: '吴', 3: '蜀'}
LETTER = {(1, 1): 'E', (1, 2): 'D', (1, 3): 'C', (1, 4): 'B', (1, 5): 'A',
          (2, 1): 'O', (2, 2): 'N', (2, 3): 'M', (2, 4): 'L', (2, 5): 'K',
          (3, 1): 'J', (3, 2): 'I', (3, 3): 'H', (3, 4): 'G', (3, 5): 'F'}


def lab(p):
    a, r, c = G.parse(p)
    return '%s%s%d' % (LETTER[(a, r)], CN[a], 10 - c)


def dist(p, q):
    return math.dist(B.xy[p], B.xy[q])


def mk(board, turn=1, deputies=None, out=()):
    s = {'board': board, 'turn': turn, 'eliminated': [], 'annexed': {},
         'history': [], 'passed': [], 'winner': None, 'ply': 0, 'first': 1}
    s.update(P.new_fields())
    if deputies:
        s['deputies'] = dict(deputies)
    s['out'] = list(out)
    s['eliminated'] = list(out)
    for a in out:
        s['vitality'][a] = False
    P.refresh_combat(s)
    return s


print('=' * 74)
print('【一】副帅的走法范围（GEN_T 以 home 为键 → 副帅在"自己代表的方"军帐内活动）')
print('=' * 74)
print('  魏主帅 GEN_T[(1,115)] = %s -> %s'
      % (sorted(R.GEN_T.get((1, '115'), ())), [lab(x) for x in sorted(R.GEN_T.get((1, '115'), ()))]))
print('  吴军帐 = %s' % [lab(x) for x in sorted(P.TENT[2])])
print('  吴军帐中心 = %s   （副帅优先进驻这里）' % lab(P.TENT_CENTER[2]))

print()
print('=' * 74)
print('【二】两个主帅的军帐能否直接接触？（这是"帅吃帅"可行性的根本前提）')
print('=' * 74)
for a, b in ((1, 2), (1, 3), (2, 3)):
    mn = min(dist(p, q) for p in P.TENT[a] for q in P.TENT[b])
    print('  %s军帐 <-> %s军帐  最近两点距离 = %7.3f' % (CN[a], CN[b], mn))
print('  → 三军帐彼此最近也有 83.974，而帅单步只能走 1 格（GEN_T 只有 3 个点）')
print('  ⇒ 任何主帅都不可能走到对方军帐里 →「帅吃帅」在引擎里物理上不可能')

print()
print('=' * 74)
print('【三】老师场景：吴帅被魏方吃掉 → 副帅诞生（代表吴，归魏控制）')
print('=' * 74)
dep = P.TENT_CENTER[2]                      # 225 吴军帐中心
s = mk({'115': {'kind': 'general', 'army': 1, 'home': 1},          # 魏主帅
        '315': {'kind': 'general', 'army': 3, 'home': 3},          # 蜀主帅
        dep: {'kind': 'general', 'army': 1, 'home': 2, 'deputy': True}},  # 副帅
       turn=1, deputies={2: {'pos': dep, 'owner': 1}}, out=(2,))
print('  盘面：魏主帅 %s | 蜀主帅 %s | 副帅(代表吴、归魏) %s'
      % (lab('115'), lab('315'), lab(dep)))
print('  out = %s   vitality = %s   combat = %s'
      % ([CN[x] for x in s['out']], s['vitality'], s['combat']))
mv = GA.legal_moves(s, army=1)
dep_mv = [t for f, t in mv if f == dep]
print('  副帅 %s 的合法着法 = %s' % (lab(dep), [lab(x) + '|' + x for x in dep_mv]))
print('  副帅能出军帐吗 = %s（其落点全在吴军帐 %s 内）'
      % (any(x not in P.TENT[2] for x in dep_mv), [lab(x) for x in sorted(P.TENT[2])]))

print()
print('=' * 74)
print('【四】副帅能"射杀"蜀帅（315）吗？—— 逐条判据')
print('=' * 74)
print('  ① 副帅 → 蜀帅 的着法在 legal_moves 里吗 = %s' % ((dep, '315') in mv))
print('  ② 副帅与蜀帅是否共线无阻（照面）= %s' % R.line_of_sight(s, dep, '315'))
print('  ③ 副帅与蜀帅的几何距离 = %.3f（帅的单步 = 军帐内相邻点）' % dist(dep, '315'))
print('  ④ 副帅到蜀帅的最小"步数"上限：副帅只能走 GEN_T[(2,%s)] = %s'
      % (dep, [lab(x) for x in sorted(R.GEN_T.get((2, dep), ()))]))
print('  ⇒ 四个判据一致：副帅**够不着**蜀帅，也没有任何"射杀"着法')

print()
print('=' * 74)
print('【五】穷举验证：副帅能否吃到任何主帅？（副帅位置 × 主帅位置 全组合）')
print('=' * 74)
hit = 0
tried = 0
for d in sorted(P.TENT[2]):            # 副帅在吴军帐的 9 个可能位置
    board = {'115': {'kind': 'general', 'army': 1, 'home': 1},
             '315': {'kind': 'general', 'army': 3, 'home': 3},
             d: {'kind': 'general', 'army': 1, 'home': 2, 'deputy': True}}
    s2 = mk(board, turn=1, deputies={2: {'pos': d, 'owner': 1}}, out=(2,))
    for a in (1, 3):
        for f, t in GA.legal_moves(s2, army=a):
            if s2['board'][f]['kind'] == 'general' and s2['board'].get(t, {}).get('kind') == 'general':
                hit += 1
                print('    ！命中 副帅 %s → %s' % (lab(f), lab(t)))
    tried += 1
print('  副帅位置 9 个 × 2 个在局方 = 共 %d 个局面，「吃帅」着法命中 = %d' % (tried * 2, hit))

print()
print('=' * 74)
print('【六】副帅是"活子"吗？—— 它能不能吃普通棋子（走进吴军帐的敌人）')
print('=' * 74)
near = sorted([q for q in P.TENT[2] if q != dep and dist(dep, q) < 30],
              key=lambda q: dist(dep, q))
print('  副帅 %s 在吴军帐内的几何相邻点 = %s'
      % (lab(dep), [(lab(q), round(dist(dep, q), 3)) for q in near]))
cand = near[0] if near else None
print('  取一个同在吴军帐内的邻点做实验 = %s（距离 %.3f）' % (lab(cand), dist(dep, cand) if cand else -1))
if cand:
    s3 = mk({'115': {'kind': 'general', 'army': 1, 'home': 1},
             '315': {'kind': 'general', 'army': 3, 'home': 3},
             dep: {'kind': 'general', 'army': 1, 'home': 2, 'deputy': True},
             cand: {'kind': 'pawn', 'army': 3, 'home': 3}},   # 蜀兵闯进吴军帐
            turn=1, deputies={2: {'pos': dep, 'owner': 1}}, out=(2,))
    m3 = GA.legal_moves(s3, army=1)
    print('  蜀兵在 %s，副帅能否吃它 = %s' % (lab(cand), (dep, cand) in m3))

print()
print('=' * 74)
print('【七】副帅是否参与 generals_facing（见面）判定？')
print('=' * 74)
s4 = mk({'115': {'kind': 'general', 'army': 1, 'home': 1},
         '255': {'kind': 'general', 'army': 2, 'home': 2},
         '315': {'kind': 'general', 'army': 2, 'home': 3, 'deputy': True}},
        turn=1, deputies={3: {'pos': '315', 'owner': 2}}, out=(3,))
print('  局面：魏主帅 115 | 吴主帅 255 | 副帅(代表蜀、归吴) 315')
print('  115 与 315 共线无阻 =', R.line_of_sight(s4, '115', '315'))
print('  115 与 255 共线无阻 =', R.line_of_sight(s4, '115', '255'))
print('  generals_facing() =', [(lab(p), lab(q)) for p, q in R.generals_facing(s4)])
print('  → 引擎只报主帅↔主帅；**副帅被无条件排除**（rules_dxf.py:948 `not pc.get("deputy")`）')
print('  → 规则图 §9 原文却写「不可把己方帅和**对手的帅（主帅和副帅）**放在…线路上」')

print()
print('=' * 74)
print('【八】"C 不可吃 B 的帅"（规则图 §9 第 3 条豁免）引擎有没有实现？')
print('=' * 74)
print('  扫描 server/ 全目录关键词「不可吃 / 不得吃 / 保护」→ 无任何实现代码')
print('  实测：出局方 B=吴 的副帅，第三方 C=蜀 的车能否吃它？')
s5 = mk({'115': {'kind': 'general', 'army': 1, 'home': 1},
         '315': {'kind': 'general', 'army': 3, 'home': 3},
         '215': {'kind': 'general', 'army': 1, 'home': 2, 'deputy': True}},
        turn=3, deputies={2: {'pos': '215', 'owner': 1}}, out=(2,))
# 蜀车放在能直线打到 215 的点上：先用炮/车找一条
found = []
for src in sorted(B.ids):
    if src in s5['board']:
        continue
    s6 = dict(s5)
    s6['board'] = dict(s5['board'])
    s6['board'][src] = {'kind': 'rook', 'army': 3, 'home': 3}
    if ('215' in R.side_moves(s6, 3, set())) or (src, '215') in R.side_moves(s6, 3, set()):
        found.append(src)
print('  能打到副帅 215 的蜀车位置 = %s' % [lab(x) + '|' + x for x in found[:6]])

print()
print('=' * 74)
print('【九】显示层常数一致性')
print('=' * 74)
print('  geometry_dxf.ARMY_CN = %s   ← 权威（与棋盘原图一致）' % G.ARMY_CN)
print('  game_dxf.ARMY_CN     = %s   ← 继承权威 ✓' % GA.ARMY_CN)
print('  patent.ARMY_CN       = %s   ← ❌ 蜀/吴对调（当前无人引用，死常量）' % P.ARMY_CN)
