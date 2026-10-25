# -*- coding: utf-8 -*-
"""打一个 AutoDL 用的上传包（zip）

    python tools/pack_autodl.py                 # → dist/sanchi_autodl_<时间戳>.zip
    python tools/pack_autodl.py --with-tests     # 连 tests/ 一起（云端想跑门禁时用）

【带什么】
  server/            整个规则引擎 + Bot（**三人象棋专属：DXF 变形网格、军帐、三角区、
                     副帅、判负/出局、重复判罚…… 一样都不能少**）
  tools/             云端产数据 / 训练脚本
  docs/AutoDL_*.md   配置手册（方便在云端照着做）
  requirements_cloud.txt

【不带什么】
  __pycache__ / *.pyc     云端是 Linux + 别的 Python 版本，带过去只会碍事
  server/data/autosave.json  老师的对局存档（含个人数据，不该上传）
  web/  server/app.py     前端与对弈台（云端只跑计算，不需要）
  tests/_bench_*.json 等  大文件（除非 --with-tests）

【强行带什么】（FORCE_INCLUDE）
  server/data/board_135.json   ★ **棋盘几何数据**，`geometry_dxf.Board()` 启动就 load，
                               缺了直接 `FileNotFoundError`（2026-10-01 冒烟测试踩到）。
                               它不是"用户数据"，被 `server/data/` 前缀连坐排除了 —— 已修。

上传后在 AutoDL 上：
  unzip -q sanchi_autodl_*.zip -d /root/autodl-tmp/sanchi
  cd /root/autodl-tmp/sanchi && pip install -r requirements_cloud.txt
"""
import argparse
import os
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".idea", ".vscode"}
SKIP_EXT = {".pyc", ".pyo", ".nbi", ".nbc", ".zip", ".7z", ".rar"}

# 明确排除的路径（相对 ROOT，用 / 分隔）
EXCLUDE_PREFIX = (
    "server/data/",            # 对局存档（含老师个人数据）—— 但 board_135.json 例外，见下
    "server/__pycache__/",
    "tests/_备份_",            # 历史备份目录
    "dist/",
)

# ★ 强行包含（优先级最高，压过 EXCLUDE_PREFIX）
#   board_135.json 是棋盘几何数据，被 "server/data/" 前缀连坐排除了 ⇒ 必须显式放回
FORCE_INCLUDE = (
    "server/data/board_135.json",
)


def _want(rel, with_tests):
    r = rel.replace(os.sep, "/")
    if r in FORCE_INCLUDE:
        return True
    if any(r.startswith(p) for p in EXCLUDE_PREFIX):
        return False
    parts = r.split("/")
    if any(p in SKIP_DIRS for p in parts):
        return False
    if os.path.splitext(r)[1].lower() in SKIP_EXT:
        return False
    # 下划线开头的私有文件（如 tools/_autodl_remote.py 里有本机私用逻辑）不进包
    if parts[-1].startswith("_"):
        return False
    top = parts[0]
    if top in ("server", "tools", "docs"):
        if top == "docs" and not parts[-1].startswith("AutoDL"):
            return False
        return True
    if with_tests and top == "tests":
        return True
    if r in ("requirements_cloud.txt",):
        return True
    return False


def build(with_tests=False):
    stamp = time.strftime("%Y%m%d_%H%M")
    dist = os.path.join(ROOT, "dist")
    os.makedirs(dist, exist_ok=True)
    out = os.path.join(dist, f"sanchi_autodl_{stamp}.zip")

    n, tot = 0, 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, ROOT)
                if not _want(rel, with_tests):
                    continue
                z.write(full, rel.replace(os.sep, "/"))
                n += 1
                tot += os.path.getsize(full)

    print("=" * 74)
    print(f"打包完成：{out}")
    print(f"  {n} 个文件，原始 {tot / 1024:.1f} KB，压缩后 {os.path.getsize(out) / 1024:.1f} KB")
    print("=" * 74)
    print("\nAutoDL 上的步骤：")
    print("  ① 无卡模式开机 → 上传这个 zip（或用 JupyterLab 拖进去）")
    print("  ② unzip -q sanchi_autodl_*.zip -d /root/autodl-tmp/sanchi")
    print("  ③ cd /root/autodl-tmp/sanchi")
    print("  ④ pip install -r requirements_cloud.txt")
    print("  ⑤ python tools/cloud_selfplay.py --games 100000 --workers 16 \\")
    print("       --out data/selfplay_100k.npz")
    print("  ⑥ python tools/train_cloud.py --data data/selfplay_100k.npz")
    print("  ⑦ 把 server/agents/values/*.json 下载回来（scp / JupyterLab 下载）")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-tests", action="store_true", help="连 tests/ 一起打包")
    a = ap.parse_args()
    build(a.with_tests)
