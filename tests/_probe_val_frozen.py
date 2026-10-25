# -*- coding: utf-8 -*-
"""回归探针：冻结验证集 —— 数据长出来之后，验证集必须**逐行不变**。

【它守的是什么事故】2026-10-02 实测：守护每轮用
        rng = np.random.default_rng(20261001); idx = rng.permutation(len(Y))
取前 10% 当验证集，注释还写着"固定种子 ⇒ 各轮验证集同口径"。
**但 `len(Y)` 每轮都在涨**——同一个种子配不同长度 = 另一套洗牌，`nval` 也在涨。
⇒ 每轮其实换了一把尺子 ⇒ 冠军存的 auc 永远追不上 ⇒ 夜班白跑。

【本探针的断言】（不需要 GPU、不需要真数据）
  ① 建 → 落盘 → 再读：键与指纹**完全一致**（幂等，不会重抽）
  ② 数据长大（追加新分片）后，用同一批键取出来的验证集**逐行 byte 级相同**
     ← **这一条就是事故的回归测试**：老实现这里必然失败
  ③ 掩码是"分片整进整出"：命中的行数与键的行数一致，且训练/验证**无交集**
  ④ 结构断言：源码里必须调用 `frozen_val_keys(` / `cache.group_mask(`，
     且那句错误注释（"固定种子 ⇒ 各轮验证集同口径"）不许复活
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, "tools")
for _p in (ROOT, TOOLS, os.path.join(ROOT, "server")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import gpu_daemon as GD                                    # noqa: E402


class FakeCache:
    """最小的 PartCache 替身：只提供 gkeys/gsize/dirs/names。

    真 `PartCache` 要读磁盘分片；这里要的是**可控的"数据长大"**，
    所以直接按测试脚本的意思造行数与键。
    """

    def __init__(self, dirs, gkeys, gsize):
        self.dirs = list(dirs)
        self.names = [os.path.basename(d) for d in dirs]
        self.gkeys = list(gkeys)
        self.gsize = list(gsize)

    def group_mask(self, keys):
        return GD.PartCache.group_mask(self, keys)

    # 造出与 group_mask 行序一致的 X/Y，供"逐行相同"断言用
    def make_XY(self):
        rows = []
        for k, n in zip(self.gkeys, self.gsize):
            rows.append(np.full((n, 3), float(sum(map(ord, k)) % 97), dtype=np.float32))
        return np.concatenate(rows) if rows else np.zeros((0, 3), np.float32)


def mk_keys(di, n, size):
    return [f"{di}/part{i:05d}.npz" for i in range(n)], [size] * n


def main():
    tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_val_frozen.json")
    if os.path.exists(tmp):
        os.remove(tmp)
    ok = 0
    fail = []

    def chk(cond, msg):
        nonlocal ok
        if cond:
            ok += 1
            print(f"  ✓ {msg}")
        else:
            fail.append(msg)
            print(f"  ✗ {msg}")

    # ---------------------------------------------------------------- ① 幂等
    print("\n① 建 → 落盘 → 再读：必须幂等")
    k1, s1 = mk_keys(1, 40, 1000)
    c1 = FakeCache(["/x/sp2.parts", "/x/old.parts"], k1, s1)
    keys, vid = GD.frozen_val_keys(c1, tmp, 4000, 1)
    chk(os.path.exists(tmp), f"定义文件已落盘：{os.path.basename(tmp)}")
    chk(0 < len(keys) and vid, f"返回非空：{vid}")
    keys2, vid2 = GD.frozen_val_keys(c1, tmp, 999999, 1)          # 目标故意给大
    chk(keys == keys2 and vid == vid2,
        f"第二次调用**不重抽**（目标从 4000 改成 999999 也不动）：{vid2}")
    with open(tmp, encoding="utf-8") as f:
        dd = json.load(f)
    chk(dd.get("keys") and dd.get("id") == vid, "落盘内容含 keys + id")

    # ---------------------------------------------------------------- ② 长大不许变
    print("\n② 数据长大（追加新分片）后，验证集必须**逐行不变**")
    c2 = FakeCache(c1.dirs, k1 + mk_keys(0, 10, 1000)[0],
                   s1 + mk_keys(0, 10, 1000)[1])
    X1, X2 = c1.make_XY(), c2.make_XY()
    m1 = c1.group_mask(keys)
    m2 = c2.group_mask(keys)
    chk(m1.sum() == m2.sum(),
        f"验证行数不变：{int(m1.sum()):,} → {int(m2.sum()):,}")
    same = np.array_equal(X1[m1], X2[m2])
    chk(same, "**验证集逐行 byte 级相同** ← 事故回归点（老实现必假）")
    # 对照：老实现（同种子 + 变长）必然破坏这条不变量
    rng = np.random.default_rng(20261001)
    o1 = rng.permutation(len(X1))[:max(1, int(len(X1) * 0.1))]
    rng = np.random.default_rng(20261001)
    o2 = rng.permutation(len(X2))[:max(1, int(len(X2) * 0.1))]
    old_same = (len(o1) == len(o2)) and np.array_equal(X1[o1], X2[o2])
    chk((not old_same),
        f"老实现（同种子+变长）确实会变：{len(o1)} → {len(o2)} 行，内容相同="
        f"{old_same} ⇒ 证明这条不变量是**新增保护**")

    # ---------------------------------------------------------------- ③ 整片进出
    print("\n③ 掩码：分片整进整出、训练/验证无交集")
    chk(int(m2.sum()) == int(sum(n for k, n in zip(c2.gkeys, c2.gsize) if k in keys)),
        "命中行数 == 命中键的行数之和")
    chk(int(m2.sum()) + int((~m2).sum()) == len(X2), "掩码覆盖全部行（无遗漏）")
    off = 0
    partial = False
    for k, n in zip(c2.gkeys, c2.gsize):
        seg = m2[off:off + n]
        if seg.any() and not seg.all():
            partial = True
        off += n
    chk(not partial, "没有任何分片被切成一半（整片进/整片出）")

    # ---------------------------------------------------------------- ④ 结构断言
    print("\n④ 结构断言（防「改回去」）")
    src = open(os.path.join(TOOLS, "gpu_daemon.py"), encoding="utf-8").read()
    chk("frozen_val_keys(" in src.replace("def frozen_val_keys(", ""),
        "`frozen_val_keys` 有**调用点**（不是死代码）")
    chk("cache.group_mask(val_keys)" in src, "验证集真的是用 `group_mask` 取的")
    chk("vmask = cache.group_mask" in src, "主循环用冻结掩码，不是随机 permutation")
    # ⚠️ 随机切必须**只在兜底分支**：字符串计数会被 docstring 里引用的旧代码误导
    #    （`frozen_val_keys` 的说明里就抄了老实现那一行）⇒ 一律走 **AST**，
    #    按语法树判，不受注释/字符串影响（与 `_verify_rays_topology.py` 同一套路）。
    import ast
    tree = ast.parse(src)
    seeds, warn_lines = [], []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "default_rng" and node.args):
            try:
                seeds.append((int(ast.literal_eval(node.args[0])), node.lineno))
            except Exception:                              # noqa: BLE001
                seeds.append((None, node.lineno))
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and "冻结验证集一行都没命中" in node.value):
            warn_lines.append(node.lineno)
    hit = [ln for s, ln in seeds if s == 20261001]
    chk(len(hit) == 1,
        f"AST 里 `default_rng(20261001)` 只被**调用**一次（实得 {len(hit)} 处，"
        f"行号 {hit}）；docstring 里的引用不算")
    chk(bool(warn_lines) and hit and hit[0] > warn_lines[0],
        f"随机切在兜底分支里（兜底告警在第 {warn_lines[:1]} 行，随机切在第 {hit} 行）"
        f"—— 回不到主路径")

    # ---------------------------------------------------------------- ⑤ 比例与不吞池
    #   ⚠️ 这一节守的是**冒烟时才暴露的第二个 bug**：第一版"逐行均匀抽"在文件数
    #      少于"目标行数/片"时退化成"每个文件都被命中" ⇒ 去重后**整个池子全进验证集**
    #      （实测 52,182 行全进验证、训练集 0 行、AUC 0.503 纯噪声）。
    print("\n⑤ 验证集规模：要接近目标比例，且**绝不许吃掉整个池子**")
    tmp2 = tmp + ".2"
    if os.path.exists(tmp2):
        os.remove(tmp2)
    ks = mk_keys(0, 5, 1000)[0] + mk_keys(1, 5, 1000)[0]
    c3 = FakeCache(c1.dirs, ks, [1000] * 10)
    tgt = 5218                                          # 池 10,000 行 ⇒ 想要 ~5,218
    keys3, vid3 = GD.frozen_val_keys(c3, tmp2, tgt, -1)
    nv = int(c3.group_mask(keys3).sum())
    chk(nv < 10_000, f"训练集没被吃光：验证 {nv:,} / 池 10,000（训练剩 {10_000 - nv:,}）")
    chk(0.4 * tgt <= nv <= 1.6 * tgt,
        f"规模接近目标：{nv:,} vs 目标 {tgt:,}（±60% 内即可，冻结后不再变）")
    chk(int(c3.group_mask(keys3).sum()) ==
        int(sum(n for k, n in zip(c3.gkeys, c3.gsize) if k in keys3)),
        "整片进出（不切文件）")
    if os.path.exists(tmp2):
        os.remove(tmp2)
    print(f"      （尺子指纹：{vid3}）")

    if os.path.exists(tmp):
        os.remove(tmp)
    print(f"\n{'-' * 60}\n通过 {ok} 项" + (f"，失败 {len(fail)} 项：{fail}" if fail else "，全部通过 ✅"))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
