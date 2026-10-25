# -*- coding: utf-8 -*-
"""把一份权重**封为冠军**（写 `champion{sfx}.json`），并带指纹 + 标尺成绩。

【为什么需要它】
  `tools/gpu_daemon.py` 里的 `save_champion/load_champion` 现在会跨重启接手冠军，
  但**第一次**封盘必须有人做：老部署盘上只有 `value_mlp.json`，没有 `champion.json`。
  守护自己有一条"现场封冠军"兜底（第 1 轮、`best is None` 时触发），但它
  · 只会带 **AUC**，不带**标尺成绩** ⇒ 第一次遇到候选挑战仍要重跑冠军标尺（3 分钟）
  · 而且每次进程重启都会重测 AUC（约 1 分钟）
  所以：**先手工封一次**，把 AUC（取权威来源）+ 标尺成绩一次写全。

【单一来源】本工具**不重写**写盘逻辑，而是用 AST 从 `gpu_daemon.py` 里摘出
  `_md5_file / save_champion / load_champion` 三个函数来执行 ⇒ 格式永远和守护一致。
  （这点很重要：2026-10-02 我在"报告 vs 实盘"上栽过一次，就是因为两边各写各的。）

用法：
    python tools/seal_champion.py                                  # 最常用：封 value_mlp.json
    python tools/seal_champion.py --weights value_mlp_bal.json     # 封均衡版
    python tools/seal_champion.py --weights value_mlp.json \
        --yard _对照实验/ab_yard_value_mlp_frozen.json \
        --auc 0.6467 --note "标尺裁决 v1333 > v1233"
可选：
    --auc    覆盖 AUC（默认从 gpu_daemon_status{sfx}.json 的 best 里取，**权威**）
    --yard   标尺报告（默认按权重名自动找 `_对照实验/ab_yard_<stem>.json`）
    --no-yard 不带标尺成绩（下次门禁会自己量一次）
"""
import argparse
import ast
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAEMON = os.path.join(ROOT, "tools", "gpu_daemon.py")
VALDIR = os.path.join(ROOT, "server", "agents", "values")
WANT = ("_md5_file", "load_champion", "save_champion")


def _load_writers():
    """从 gpu_daemon.py 摘出三个函数（避免 import torch/numba 的重依赖）。"""
    import hashlib
    src = open(DAEMON, encoding="utf-8").read()
    tree = ast.parse(src)
    body = [n for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name in WANT]
    missing = set(WANT) - {n.name for n in body}
    if missing:
        sys.exit(f"✗ gpu_daemon.py 里找不到 {sorted(missing)}")
    ns = {"hashlib": hashlib, "json": json, "os": os, "time": time}
    exec(compile(ast.Module(body=body, type_ignores=[]), DAEMON, "exec"), ns)
    return ns


def _yard_from(rep_path):
    """按 `yard_score()` 的**同一公式**从一份 ab_match 报告里算标尺成绩。

    ★ 必须和 `yard_score` 一字不差：它累加的是"含 x 的那些配对里 x 那一侧的 bx /
      n_x"。篡改这里的口径 ⇔ 冠军和候选不在同一把尺子上量 ⇒ 门禁判决无效。
    """
    d = json.load(open(rep_path, encoding="utf-8"))
    ordi = wins = 0
    hit = 0
    for p in d.get("pairs", []):
        if "x" not in (p["x"], p["y"]):
            continue
        hit += 1
        ordi += p["bx"] if p["x"] == "x" else p["by"]
        wins += p["n_x"] if p["x"] == "x" else p["n_y"]
    if hit != 2:
        sys.exit(f"✗ 标尺报告 {rep_path} 里含 x 的配对是 {hit} 个（应为 2）"
                 f" ⇒ 这不是 `{{n1,n2,x}}` 的标尺报告")
    return {"ordi": int(ordi), "wins": int(wins),
            "games": int(d["games"]), "seed0": int(d["seed0"]),
            "tl": d.get("tl"), "depth": d.get("depth"),
            "maxply": d.get("maxply"), "src": os.path.basename(rep_path)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default="value_mlp.json",
                    help="要封的权重文件名（相对 server/agents/values/）")
    ap.add_argument("--auc", type=float, default=None, help="覆盖 AUC")
    ap.add_argument("--yard", default=None, help="标尺报告路径（相对项目根）")
    ap.add_argument("--no-yard", action="store_true", help="不写标尺成绩")
    ap.add_argument("--note", default="", help="写进 champion.json 的备注")
    a = ap.parse_args()

    ns = _load_writers()
    w = a.weights if os.path.isabs(a.weights) else os.path.join(VALDIR, a.weights)
    if not os.path.exists(w):
        sys.exit(f"✗ 权重不存在：{w}")
    stem = os.path.basename(w)
    # 与守护同一套命名：value_mlp.json→champion.json；value_mlp_bal.json→champion_bal.json
    if not stem.startswith("value_mlp") or not stem.endswith(".json"):
        sys.exit(f"✗ 权重名不合规（应为 value_mlp*.json）：{stem}")
    sfx = stem[len("value_mlp"):-len(".json")]
    champ = os.path.join(VALDIR, f"champion{sfx}.json")
    status = os.path.join(VALDIR, f"gpu_daemon_status{sfx}.json")

    # ---- AUC：优先命令行，其次 status 的 best（**权威**，是训练时实测的）----
    auc = a.auc
    best = {}
    if os.path.exists(status):
        try:
            best = json.load(open(status, encoding="utf-8")).get("best") or {}
        except Exception:                                   # noqa: BLE001
            best = {}
    if auc is None:
        if not best.get("auc"):
            sys.exit(f"✗ 既没给 --auc，{os.path.basename(status)} 里也没有 best.auc")
        auc = float(best["auc"])
    # ⚠️ status 里的 best 可能指向**另一份**权重（我踩过：12:33 的 0.6496 被 13:33
    #    的 0.6467 覆盖，而 status 只留最后一次）⇒ 用 mtime 对一下，不符就报警。
    md5_now = ns["_md5_file"](w)
    if best.get("mtime") and best.get("mtime") != time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(os.stat(w).st_mtime)):
        print(f"   ⚠ status 的 best.mtime={best.get('mtime')} ≠ 现场 "
              f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.stat(w).st_mtime))}"
              f" ⇒ AUC 可能不是这份权重的，请用 --auc 显式指定")

    # ---- 标尺成绩 ----
    yard = None
    if not a.no_yard:
        yp = a.yard or os.path.join(ROOT, "_对照实验", f"ab_yard_{stem[:-5]}.json")
        if not os.path.isabs(yp):
            yp = os.path.join(ROOT, yp)
        if os.path.exists(yp):
            yard = _yard_from(yp)
        else:
            print(f"   ⚠ 找不到标尺报告 {yp} ⇒ 本次不带 yard（门禁首次会自己量一次）")

    st = os.stat(w)
    payload = dict(best) if best else {}
    payload.update({
        "name": payload.get("name") or stem,
        "auc": round(float(auc), 4),
        "file": stem,
        "bytes": st.st_size,
        "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
        "round": payload.get("round", -1),
        "tag": payload.get("tag", ""),
    })
    if "bad_pairs" not in payload:
        payload["bad_pairs"] = 0
        payload["cmp_pairs"] = 0
    if yard:
        payload["yard"] = yard
    if a.note:
        payload["note"] = a.note

    if os.path.exists(champ):
        bak = champ + ".bak"
        os.replace(champ, bak)
        print(f"   （旧 champion 已备份 → {os.path.basename(bak)}）")

    c = ns["save_champion"](champ, payload, w)
    print("=" * 72)
    print(json.dumps(c, ensure_ascii=False, indent=1))
    print("=" * 72)
    back = ns["load_champion"](champ, w)
    print(f"回读核验：{'✅ 接手成功' if back else '✗ 接手失败'}  "
          f"name={back and back.get('name')}  auc={back and back.get('auc')}  "
          f"yard_ordi={back and (back.get('yard') or {}).get('ordi')}  "
          f"md5={md5_now[:8]}")
    return 0 if back and back.get("auc") == round(float(auc), 4) else 1


if __name__ == "__main__":
    sys.exit(main())
