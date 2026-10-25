# -*- coding: utf-8 -*-
"""探针：/api/hint 的后端实现冒烟（正式门禁见 tests/_verify_hint.py）

跑法：cd server && python ../tests/_probe_hint.py
"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "server"))

from match import Match                                     # noqa: E402
from engine import game_dxf as GA                           # noqa: E402

m = Match()
print("ply=", m.state["ply"], "turn=", m.state["turn"])

before = copy.deepcopy(m.state)

# 短预算冒烟（3 plies，秒级）——正式档位是 12 plies / 60s
r = m.hint(plies=3, budget=3.0)
print("hint(3 plies) ->", json.dumps(r, ensure_ascii=False))

after = copy.deepcopy(m.state)
print("state 是否逐字段不变:", before == after)
print("legal 条数:", len(GA.legal_moves(m.state, m.state["turn"])))

# 12 plies 参数是否落到 depth=4（真跑一次很慢，这里只看参数换算）
lv_bot = m.hint(plies=12, budget=0.6)      # 0.6s 预算 ⇒ 只搜到 3 plies 就返回
print("hint(12 plies, 0.6s) ->", json.dumps(lv_bot, ensure_ascii=False))
print("state 仍然不变:", before == copy.deepcopy(m.state))
