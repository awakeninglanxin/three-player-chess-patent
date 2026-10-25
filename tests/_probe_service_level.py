# -*- coding: utf-8 -*-
"""服务端实测：切某个难度档 → 走一手 → 报「真实耗时 + 实到 plies」

为什么不用 `tests/_bench_jit_levels.py` 的结论直接交差：
    bench 走的是**进程内直接调 `SearchBot.choose()`**；
    服务走的是 **HTTP + `Match.step()` + 后台长考线程 + `actual_plies` 汇总**。
    多这一层就多一种坏法（例如预热线程与主线程竞争、长考被 `/api/state` 阻塞）。
    老师关心的是"网页上点一下要等多久"，所以必须在**服务路径**上量一遍。

用法：
    python tests/_probe_service_level.py            # 默认档5
    python tests/_probe_service_level.py 4 6        # 依次测档4、档6
"""
import json
import os
import sys
import time
import urllib.request

BASE = os.environ.get("SANCHI_BASE", "http://127.0.0.1:8771")
# ⚠️ 必须绕过系统代理：本机全局设了 HTTP_PROXY，走代理探测 127.0.0.1 会得到假 502
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def post(path, data=None):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(data or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with _OPENER.open(req, timeout=240) as r:
        return json.loads(r.read().decode("utf-8"))


def get(path):
    with _OPENER.open(BASE + path, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def run_level(level):
    post("/api/difficulty", {"level": level})
    st0 = get("/api/state")
    meta = st0.get("difficulty_meta") or {}
    base_total = st0.get("replay_total") or 0
    print(f"\n=== 档{level} {meta.get('name')}（目标 {meta.get('plies')} plies，"
          f"上限 {meta.get('time_limit')}s）===")
    t0 = time.time()
    post("/api/step")
    t_post = time.time() - t0          # POST 本身多久返回（异步接口应极快）
    # ⚠️ 轮询判据必须用 **`replay_total` 增加**，不能用 `thinking is None`：
    #    `/api/step` 只置 `pending=True`，真正的长考要等 `_loop` 下一轮才启动
    #    ⇒ 立刻查 `thinking` 一定是 None（本探针第一版就踩了这个，误报"没走棋"）。
    waited = 0.0
    while True:
        st = get("/api/state")
        if (st.get("replay_total") or 0) > base_total:
            break
        time.sleep(0.4)
        waited += 0.4
        if t_post + waited > 300:
            print("  !! 等超过 300s，放弃（对局可能已结束/被判和）")
            break
    dt = time.time() - t0
    ap = st.get("actual_plies") or {}
    real = {k: v for k, v in ap.items() if v}
    agents = {k: v.get("last_plies") for k, v in (st.get("agents") or {}).items()}
    print(f"  POST 返回耗时 : {t_post * 1000:.0f} ms（异步接口，立即返回）")
    print(f"  长考总耗时    : {dt:.2f} s（POST 返回后仍在后台思考）")
    print(f"  实到 plies    : actual_plies={real}  agents.last_plies={agents}")
    ok = real and max(real.values()) == meta.get("plies")
    print(f"  结论          : {'[OK] 搜满标称深度' if ok else '[!] 未搜满（预算是硬上限，如实显示）'}")


def main():
    levels = [int(x) for x in sys.argv[1:]] or [5]
    print("=" * 70)
    print(f"服务端难度档实测  {BASE}")
    print("=" * 70)
    try:
        st = get("/api/state")
    except Exception as e:
        print(f"!! 服务没起来：{e}\n   先跑 启动对弈台.bat（或 server/app.py --local）")
        return 1
    print(f"服务在线 · 当前档 {st.get('difficulty')} · 三方 "
          f"{ {k: v.get('model') for k, v in (st.get('agents') or {}).items()} }")
    for lv in levels:
        run_level(lv)
    print("\n" + "=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
