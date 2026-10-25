# -*- coding: utf-8 -*-
"""冠军落盘（champion.json）的存读往返自测 + **AST 防死代码复发**。

【为什么要这个探针】
  2026-10-02 我为了治"冠军随重启归零"写了 `load_champion` + `save_champion`，
  当时只验证了 `yard_score`（用猴补丁跑了个假报告），**没验证读写往返**。
  结果上云后才发现：`load_champion` **定义了但从未被调用**（死代码）——
  `best` 在每次重启后仍然是 None，只是靠"现场封冠军"兜底。
  兜底能防"随手覆盖"，但**读不回 champion.json 里的 yard**，
  于是每遇到候选挑战都要重跑一次冠军标尺（3 分钟），且 yard 随进程一次次丢失。

【做法】
  1) **AST 扫描**（防复发）：断言 `load_champion` 在模块里**至少有一个调用点**。
     这条是硬门禁 —— 只测"函数本身对不对"是抓不出死代码的。
  2) 存读往返：save → load 必须原样拿回（含 yard）。
  3) 指纹核验：把 champion.json 里的 md5 篡改 ⇒ load 必须**拒绝认**（返回 None）。
  4) 文件不在 ⇒ load 必须返回 None（空场，走兜底路径）。

用法：python tests/_probe_champion.py      （不需要 torch / numba，秒完）
"""
import ast
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, os.pardir, "tools", "gpu_daemon.py")
WANT = ("_md5_file", "load_champion", "save_champion")


def main():
    src = open(SRC, encoding="utf-8").read()
    tree = ast.parse(src)

    # ---------- 1) AST 防死代码 ----------
    n_calls = sum(
        1 for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "load_champion"
    )
    print(f"[1] AST 扫描：load_champion 调用点 {n_calls} 个")
    if n_calls < 1:
        print("    ✗ 死代码！load_champion 从未被调用 ⇒ 冠军跨重启必丢")
        return 1

    # ---------- 摘出三个函数（不 import 重依赖）----------
    body = [n for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name in WANT]
    got = {n.name for n in body}
    if got != set(WANT):
        print(f"    ✗ 函数缺失：期望 {set(WANT)}，实际 {got}")
        return 1
    ns = {"hashlib": hashlib, "json": json, "os": os, "time": time}
    exec(compile(ast.Module(body=body, type_ignores=[]), SRC, "exec"), ns)

    d = tempfile.mkdtemp(prefix="_champ_probe_")
    try:
        w = os.path.join(d, "value_mlp.json")
        c = os.path.join(d, "champion.json")
        with open(w, "wb") as f:
            f.write(b"\x00" * 4096)

        best = {"name": "mlp_512_256", "auc": 0.6467, "bad_pairs": 0,
                "cmp_pairs": 363, "hidden": [512, 256],
                "file": "value_mlp.json", "bytes": 4096, "round": -1, "tag": "",
                "samples": 11105318,
                "yard": {"ordi": 234, "wins": 160, "games": 300,
                         "seed0": 2200000}}

        # ---------- 2) 存读往返 ----------
        ns["save_champion"](c, best, w)
        assert os.path.exists(c), "champion.json 没写出来"
        assert not os.path.exists(c + ".tmp"), "临时文件没被 rename 掉"
        r = ns["load_champion"](c, w)
        ok = (r is not None and r["auc"] == 0.6467
              and r["yard"]["ordi"] == 234 and r["hidden"] == [512, 256]
              and r["md5"] == ns["_md5_file"](w))
        print(f"[2] 存读往返：{'✅' if ok else '✗'} name={r and r.get('name')} "
              f"auc={r and r.get('auc')} yard={r and r.get('yard', {}).get('ordi')} "
              f"md5={r and r.get('md5', '')[:8]}")
        if not ok:
            return 1

        # ---------- 3) 指纹核验：篡改 md5 必须拒绝 ----------
        j = json.load(open(c, encoding="utf-8"))
        j["md5"] = "0" * 32
        with open(c, "w", encoding="utf-8") as f:
            json.dump(j, f)
        r2 = ns["load_champion"](c, w)
        print(f"[3] 篡改指纹后 load：{'✅ 已拒绝' if r2 is None else '✗ 竟然认了'}")
        if r2 is not None:
            return 1

        # ---------- 4) 无 champion.json ⇒ None ----------
        os.remove(c)
        r3 = ns["load_champion"](c, w)
        print(f"[4] 无 champion.json：{'✅ None（走兜底封冠军）' if r3 is None else '✗'}")
        if r3 is not None:
            return 1

        # ---------- 5) 权重文件不在 ⇒ None（否则会认一个不存在的冠军）----------
        ns["save_champion"](c, best, w)
        os.remove(w)
        r4 = ns["load_champion"](c, w)
        print(f"[5] 权重文件缺失：{'✅ None' if r4 is None else '✗'}")
        if r4 is not None:
            return 1
    finally:
        shutil.rmtree(d, ignore_errors=True)

    print("\n全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
