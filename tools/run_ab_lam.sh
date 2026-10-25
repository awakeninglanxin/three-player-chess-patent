#!/bin/bash
# λ 扫描（2026-10-02）：固定 `none` 当锚点，扫混合系数 λ。
#
# 【为什么固定锚点】
#   三人棋里"A 比 B 强"依赖同场的第三方（SOUL 铁律 161）。
#   所以每一条都必须带同一个 `none` 当参照物，才能跨条比较。
#
# 【背景数据】
#   D1（tl=5.0，{none, v1233@0.35, bal}）：v1233 **37.3%** vs none 17.7%（p=0.000）
#   ⇒ λ=0.35 已经有效。本脚本要回答：**0.35 是不是最优**。
#   已知的极端：l70（v1333@0.70）在 tl=0.2 时是弱于 none 的，但那批数据受 tl 污染。
#
# 【读法】
#   看每条的「v35 vs none」与「vNN vs none」两组 p(序数)：
#     · 若 v60/v85 的序数分**明显**高于 v35 ⇒ 网络权重该加大
#     · 若都低于 v35 ⇒ 0.35 附近就是甜点，甚至该往 0.15 探
cd /root/autodl-tmp/sanchi || exit 1
PY=/root/miniconda3/bin/python
BASE="--workers 8 --tl 5.0 --depth 1 --maxply 300 --threads 1 --seed0 2100000"

run() {   # $1 = 第三个 cfg  $2 = 输出名  $3 = 说明
    echo "=== [$(date '+%F %T')] $3 ==="
    $PY -u tools/ab_match.py $BASE --games 300 \
        --cfg none=- --cfg v35=value_mlp_1233.json:0.35 --cfg "$1" \
        --out "_对照实验/$2"
}

run "v60=value_mlp_1233.json:0.60" ab_L1_lam60.json "L1: λ=0.60 vs λ=0.35"
run "v15=value_mlp_1233.json:0.15" ab_L2_lam15.json "L2: λ=0.15 vs λ=0.35"
run "v85=value_mlp_1233.json:0.85" ab_L3_lam85.json "L3: λ=0.85 vs λ=0.35"
echo "=== [$(date '+%F %T')] LAM DONE ==="
