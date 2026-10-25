# -*- coding: utf-8 -*-
"""把 AutoDL 云端的成果拉回本机（断电/关机前的保险绳）

    python tools/pull_cloud_results.py
    python tools/pull_cloud_results.py --with-data     # 连训练集 npz 一起拉（慢，几百 MB）

【为什么不用 bat】
  Windows 的 .bat 在 GBK 代码页下处理 `D:\\AAA我的文件\\...` 这种中文路径会乱码，
  把目标目录写成乱码文件夹。Python 源码是 UTF-8、路径走 Unicode API ⇒ 稳。
  （这也是本项目「bat 只用 ASCII」铁律的由来。）

【拉什么】
  ① server/agents/values/    ← **权重 + 排行榜 + 报告**（最要紧，几十 KB ~ 几 MB）
  ② data/*.json              ← 自对弈统计
  ③ 各种 *.log               ← 训练/自对弈日志（复盘用）
  ④ --with-data 时另拉 selfplay_150k.npz（训练集，可留作以后重训）

落到项目根的 `_云端成果_<日期>/`，**按原目录结构存放**，不做任何覆盖删除。
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

HOST = os.environ.get("AUTODL_HOST", "connect.nmb2.seetacloud.com")
PORT = os.environ.get("AUTODL_PORT", "49682")
USER = os.environ.get("AUTODL_USER", "root")
KEY = os.path.expanduser(os.environ.get("AUTODL_KEY", "~/.ssh/id_ed25519_autodl"))
RROOT = "/root/autodl-tmp"

SSH_OPTS = ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null", "-o", "ConnectTimeout=20"]


def scp(remote, local, timeout=1800, recursive=False, must=True):
    args = ["scp", "-P", PORT, "-i", KEY] + SSH_OPTS
    if recursive:
        args.append("-r")
    args += [f"{USER}@{HOST}:{remote}", local]
    print(f"  ← {remote}", flush=True)
    t0 = time.time()
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"    ⚠ 超时 {timeout}s，跳过", flush=True)
        return False
    ok = p.returncode == 0
    msg = (p.stderr or "").strip().splitlines()
    if not ok and must:
        print(f"    ✗ rc={p.returncode} {(msg[-1] if msg else '')}", flush=True)
    else:
        print(f"    ✓ {time.time() - t0:.1f}s", flush=True)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-data", action="store_true", help="连训练集 npz 一起拉")
    ap.add_argument("--date", default=time.strftime("%Y%m%d"))
    # ★ 2026-10-02 新增：只拉**指定的分片目录**（增量拉取用）。
    #   原来 ② 整拉 `data/`，第二轮起 data/ 下同时有旧 150k 分片（约 300 MB），
    #   每小时跑一次会把整目录重拉一遍 —— 慢且没必要。
    #   `--parts sp2` ⇒ 只拉 data/sp2.parts/。留空 = 保留旧的"整目录"行为。
    ap.add_argument("--parts", default="", help="只拉 data/<名>.parts/（增量用，如 sp2）")
    a = ap.parse_args()

    out = os.path.join(ROOT, f"_云端成果_{a.date}")
    os.makedirs(out, exist_ok=True)
    print("=" * 78)
    print(f"拉取云端成果 → {out}")
    if a.parts:
        print(f"增量模式：只拉 data/{a.parts}.parts/")
    print("=" * 78)

    # ① 权重与报告（最关键，务必成功）
    scp(f"{RROOT}/sanchi/server/agents/values/",
        os.path.join(out, "values") + os.sep, recursive=True, timeout=900)

    # ② 自对弈数据
    if a.parts:
        # 增量模式：只拉指定分片目录 + 同名统计 json
        os.makedirs(os.path.join(out, "data"), exist_ok=True)
        scp(f"{RROOT}/data/{a.parts}.parts/",
            os.path.join(out, "data", f"{a.parts}.parts") + os.sep,
            recursive=True, timeout=3600, must=False)
        for f in (f"{a.parts}.json", "selfplay_sp2.log", "selfplay.log",
                  "cal.json", "smoke.json"):
            scp(f"{RROOT}/data/{f}", os.path.join(out, "data", f),
                timeout=300, must=False)
    else:
        scp(f"{RROOT}/data/", os.path.join(out, "data") + os.sep,
            recursive=True, timeout=900, must=False)

    # ③ 日志
    os.makedirs(os.path.join(out, "logs"), exist_ok=True)
    for lg in ("selfplay.log", "train_interim.log", "train_final.log",
               "gpu_daemon.log", "pip.log", "autopilot.log"):
        scp(f"{RROOT}/{lg}", os.path.join(out, "logs", lg), timeout=300, must=False)

    # ④ 训练集（可选；大，放最后，超时就跳过，不影响前面）
    if a.with_data:
        os.makedirs(os.path.join(out, "dataset"), exist_ok=True)
        scp(f"{RROOT}/data/selfplay_150k.npz",
            os.path.join(out, "dataset", "selfplay_150k.npz"),
            timeout=3600, must=False)

    print("\n" + "=" * 78)
    print("本机拿到的文件：")
    tot = 0
    for dp, _dn, fns in os.walk(out):
        for fn in sorted(fns):
            p = os.path.join(dp, fn)
            sz = os.path.getsize(p)
            tot += sz
            print(f"  {os.path.relpath(p, out):<46} {sz / 1024:>10.1f} KB")
    print(f"  合计 {tot / 1024 / 1024:.2f} MB")
    print("=" * 78)


if __name__ == "__main__":
    main()
