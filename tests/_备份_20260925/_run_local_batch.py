# -*- coding: utf-8 -*-
"""本地 Bot 批量对局统计：连跑 N 局，汇总终局分布。

目的：单局偶然性大，用几局样本回答两个待重验的问题——
  ① 三方象棋是不是「必然僵持」？（撑满 max_ply 的比例）
  ② 斩帅/出局/收编/副帅这些规则路径实际跑出来的频率。
"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8771"
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
ARMY = {"1": "魏", "2": "吴", "3": "蜀"}
N = 3   # 局数：命令行第一个非 -- 参数，默认 3
FORCE = "--force" in sys.argv
_args = [a for a in sys.argv[1:] if not a.startswith("--")]
if _args:
    N = int(_args[0])


def _call(path, body=None, timeout=60):
    req = (urllib.request.Request(BASE + path) if body is None else
           urllib.request.Request(BASE + path, data=json.dumps(body).encode("utf-8"),
                                  headers={"Content-Type": "application/json"}))
    with _OPENER.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def guard_local_only(force=False):
    """防呆：本脚本是用来跑「本地 Bot」的。若当前配的是真实大模型，
    连跑 N 局 × 300 手会打掉大量 API 积分 —— 默认直接拦下。
    """
    ag = _call("/api/agents")
    models = {v.get("model", "") for v in ag["resolved"].values()}
    remote = sorted(m for m in models
                    if m and not m.startswith("__") and "local" not in m.lower())
    if remote and not force:
        print("⚠ 当前 agents.json 配的是真实大模型：%s" % ", ".join(remote))
        print("  连跑 %d 局会消耗 API 积分。若确认要跑，加 --force；" % N)
        print("  若想跑本地 Bot，先把 agents.json 的 model_id 改为 __local__ 再 reload_agents。")
        sys.exit(2)
    return ag


def run_one(i):
    _call("/api/new", {})
    _call("/api/auto", {"on": True})
    t0 = time.time()
    st = None
    while time.time() - t0 < 180:
        st = _call("/api/state")
        if st.get("finished"):
            break
        time.sleep(0.4)
    s = st["status"]
    row = {
        "局": i, "ply": s["ply"], "耗时": round(time.time() - t0, 1),
        "终局": ("斩帅·%s胜" % ARMY[str(s["winner"])]) if s["winner"]
                else ("判和(无着)" if st.get("drawn") else "打满上限"),
        "出局": [ARMY[str(a)] for a in s.get("eliminated") or []],
        "斩帅": {ARMY[k]: v for k, v in st["slain"].items() if v},
        "kills": {ARMY[k]: v for k, v in st["kills"].items()},
        "scores": {ARMY[k]: v for k, v in st["scores"].items()},
        "ranks": {ARMY[k]: v for k, v in st["ranks"].items()},
        "收编": s.get("annexed"), "副帅": s.get("deputies"),
        "log条数": len(st.get("log") or []),
    }
    return row


guard_local_only(FORCE)
print("本地 Bot（LocalBot greedy）连跑 %d 局，delay=0.05，max_ply=300\n" % N)
rows = []
for i in range(1, N + 1):
    r = run_one(i)
    rows.append(r)
    print("第 %d 局: ply=%-4d %-14s 耗时 %5.1fs | 出局=%s 斩帅=%s | 排名=%s"
          % (r["局"], r["ply"], r["终局"], r["耗时"], r["出局"] or "无",
             r["斩帅"] or "无", r["ranks"]))

print("\n" + "=" * 74)
print("汇总（本批 %d 局）" % N)
print("=" * 74)
from collections import Counter
c = Counter(r["终局"].split("·")[0].split("(")[0] for r in rows)
print("终局类型分布 :", dict(c))
print("平均 ply     : %.1f" % (sum(r["ply"] for r in rows) / len(rows)))
print("平均耗时     : %.1f s" % (sum(r["耗时"] for r in rows) / len(rows)))
out_cnt = Counter()
for r in rows:
    for a in r["出局"]:
        out_cnt[a] += 1
print("各方出局次数 :", dict(out_cnt) or "无")
kill = {a: 0.0 for a in ("魏", "吴", "蜀")}
for r in rows:
    for k, v in r["kills"].items():
        kill[k] += v
print("各方吃子合计 :", {k: round(v, 1) for k, v in kill.items()})
r1 = Counter("魏" if r["ranks"]["魏"] == 1 else ("蜀" if r["ranks"]["蜀"] == 1 else "吴")
             for r in rows)
print("第一名次数   :", dict(r1))
print("=" * 74)
