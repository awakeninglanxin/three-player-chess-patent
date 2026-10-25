# -*- coding: utf-8 -*-
"""解析老师的 DXF，提取实体统计与几何结构。"""
import collections
import math
import os

DXF = r"D:\AAA我的文件\中国三人象棋_专利版\三人版中国象棋.dxf"


def read_dxf(path):
    """返回 [(type, [(code, value), ...]), ...]"""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read().splitlines()
    ents = []
    i = 0
    n = len(raw)
    # 找 ENTITIES 段
    while i < n:
        if raw[i].strip() == "ENTITIES":
            i += 1
            break
        i += 1
    cur = None
    while i < n - 1:
        code = raw[i].strip()
        val = raw[i + 1].rstrip("\n")
        i += 2
        if code == "0":
            if cur:
                ents.append(cur)
            if val.strip() == "ENDSEC":
                break
            cur = (val.strip(), [])
        elif cur is not None:
            cur[1].append((code, val.strip()))
    if cur:
        ents.append(cur)
    return ents


ents = read_dxf(DXF)
print("实体总数:", len(ents))
print("类型分布:", dict(collections.Counter(t for t, _ in ents)))

# 图层分布
layers = collections.Counter()
for t, attrs in ents:
    for c, v in attrs:
        if c == "8":
            layers[v] += 1
            break
print("图层分布:", dict(layers))

# 各类型的几何摘要
print("\n=== LINE 样例 ===")
lines = []
for t, attrs in ents:
    if t == "LINE":
        d = {}
        for c, v in attrs:
            if c in ("10", "20", "11", "21", "8"):
                d[c] = v
        if all(k in d for k in ("10", "20", "11", "21")):
            lines.append((float(d["10"]), float(d["20"]), float(d["11"]), float(d["21"]), d.get("8", "")))
print(f"LINE 共 {len(lines)} 条，前 5 条：")
for L in lines[:5]:
    print("  ", L)

print("\n=== 其他实体类型 ===")
for t, attrs in ents:
    if t not in ("LINE", "LWPOLYLINE", "TEXT", "MTEXT"):
        print("  ", t, attrs[:8])
