# -*- coding: utf-8 -*-
"""本地 Bot 快跑一局：热重载 agents.json → 开局 → 轮询到终局 → 打印战报。

不走 restart：POST /api/reload_agents 会让服务重建 MATCH，
页面（老师正开着）不会断连。

注意：必须显式禁用代理 —— 本机 HTTP_PROXY 指向 127.0.0.1:26041，
访问 127.0.0.1:8771 会被代理截走返回假错误。
"""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8771"
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

ARMY = {"1": "魏", "2": "吴", "3": "蜀"}


def _call(path, body=None, timeout=60):
    if body is None:
        req = urllib.request.Request(BASE + path)
    else:
        req = urllib.request.Request(
            BASE + path, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"})
    with _OPENER.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    print("== 1. 热重载 agents.json ==")
    _call("/api/reload_agents", {})
    ag = _call("/api/agents")
    for k, v in sorted(ag["resolved"].items()):
        print("   %s号位 %s  model=%s" % (k, v["label"], v["model"]))

    print("\n== 2. 开局 ==")
    _call("/api/auto", {"on": True})

    print("== 3. 轮询到终局 ==")
    t0 = time.time()
    last = -1
    st = None
    while time.time() - t0 < 240:
        st = _call("/api/state")
        ply = st["status"]["ply"]
        if ply != last:
            last = ply
            print("   ply=%-4d turn=%s alive=%s %.1fs"
                  % (ply, ARMY.get(str(st["status"]["turn"]), "?"),
                     st["status"]["alive"], time.time() - t0))
        if st.get("finished"):
            break
        time.sleep(0.4)

    print("\n" + "=" * 66)
    print("  终局战报")
    print("=" * 66)
    if st is None:
        print("  未取到状态")
        return
    s = st["status"]
    print("  着法数 ply        = %d / %d" % (s["ply"], st["max_ply"]))
    print("  finished          = %s   drawn(判和) = %s" % (st["finished"], st.get("drawn")))
    print("  winner            = %s" % (ARMY.get(str(s["winner"]), "无（判和/未分胜负）")))
    print("  存活 alive        = %s" % [ARMY[str(a)] for a in s["alive"]])
    print("  出局 eliminated   = %s" % [ARMY[str(a)] for a in s.get("eliminated") or []])
    print("  斩帅 slain        = %s" % {ARMY[k]: v for k, v in st["slain"].items()})
    print("  吃子收益 kills    = %s" % {ARMY[k]: v for k, v in st["kills"].items()})
    print("  综合分 scores     = %s" % {ARMY[k]: v for k, v in st["scores"].items()})
    print("  排名 ranks        = %s" % {ARMY[k]: v for k, v in st["ranks"].items()})
    print("  出局方 out        = %s" % [ARMY[str(a)] for a in s.get("out") or []])
    print("  收编 annexed      = %s" % s.get("annexed"))
    print("  副帅 deputies     = %s" % s.get("deputies"))
    print("  非法输出 wrong    = %s" % {ARMY[k]: v for k, v in st["wrong"].items()})

    logs = st.get("log") or []
    types = {}
    for e in logs:
        types[e.get("type")] = types.get(e.get("type"), 0) + 1
    print("\n  日志类型统计      = %s  (返回的最近 %d 条)" % (types, len(logs)))
    caps = [e for e in logs if e.get("captured")]
    print("  最近日志里的吃子   = %d 次" % len(caps))
    for e in caps[-8:]:
        print("     ply%-4s %s方 %s→%s 吃 %s%s%s"
              % (e.get("ply"), ARMY[str(e.get("army"))], e.get("from"), e.get("to"),
                 ARMY.get(str(e.get("captured_army")), "?"), e.get("captured"),
                 "  【斩帅】" if e.get("captured") == "general" else ""))
    if st.get("drawn"):
        print("\n  ★ 本局以「三方均无法取胜」判和结束 —— 判和终止修复实测生效 ✓")
    print("=" * 66)


if __name__ == "__main__":
    main()
