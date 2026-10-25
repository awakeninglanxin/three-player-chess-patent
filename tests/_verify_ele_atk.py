# -*- coding: utf-8 -*-
"""口径一致性：象的走法生成(_elephant) 与 攻击表(attacks/_hit) 必须同判

象改造后，两处都改成「田中心无子 + 不过河」，此脚本随机撒子对拍。
"""
import sys, random
sys.path.insert(0, 'server')
from engine import rules_dxf as R, geometry_dxf as G

B = G.BOARD
random.seed(20260924)
KINDS = [R.ROOK, R.HORSE, R.ELEPHANT, R.ADVISOR, R.GENERAL, R.CANNON, R.PAWN]
bad = []
cnt = 0
ele_seen = 0
for trial in range(150):
    board = {}
    for _ in range(random.randint(0, 16)):
        p = random.choice(B.ids)
        if p in board:
            continue
        board[p] = {'kind': random.choice(KINDS),
                    'army': random.choice([1, 2, 3]),
                    'home': random.choice([1, 2, 3])}
    for pos, pc in board.items():
        if pc['kind'] != R.ELEPHANT:
            continue
        ele_seen += 1
        army, home = pc['army'], pc['home']
        legal = set(R._elephant(board, pos, home, army, frozenset()))
        for t in B.ids:
            a = R.attacks(board, pos, pc, t)
            b = (t in legal) and (board.get(t) is None or board[t]['army'] != army)
            cnt += 1
            if a != b:
                bad.append((pos, t, a, b))

print(f"随机局面 {150} 个，遇到象 {ele_seen} 个")
print(f"走法 vs 攻击表 对比 {cnt} 项，差异 {len(bad)}")
for row in bad[:8]:
    print("   ", row)

# 直接验证「田中心被占 → 打不到该落点」
print()
print("定向验证（113 象）：")
for dest, tian in (('131', '122'), ('135', '124')):
    for occ in (None, tian, '112', '123'):
        b = {'113': {'kind': R.ELEPHANT, 'army': 1, 'home': 1}}
        if occ:
            b[occ] = {'kind': R.PAWN, 'army': 2, 'home': 2}
        mv = R._elephant(b, '113', 1, 1, frozenset())
        atk = R.attacks(b, '113', b['113'], dest)
        print(f"   {dest}(田心{tian}) 占位={occ or '空':>4} → 走法含={dest in mv}  攻击={atk}")
