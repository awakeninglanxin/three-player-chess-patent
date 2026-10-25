#!/bin/bash
# 版本对决（2026-10-02）：**同一配方、相邻轮次产出的两份权重，棋力是否真的差一倍？**
#
# 【起因】
#   组1（第三方 bal，300 局）用 12:33 版 value_mlp.json  ⇒  offi 胜率 36.3%（vs none 18.3%，p<0.0001）
#   G1 （第三方 bal，198 局）用 13:33 版（frozen 副本）  ⇒  offi 胜率 19.7%（vs none 17.7%，p=0.728）
#   两组**第三方相同、seed 相同、代码相同**，`none` 的胜率也一致（18.3% / 17.7%），
#   唯一差别就是 `offi` 用的那份权重版本。
#   而两版的 AUC 只差 0.003（0.6496 vs 0.6467）。
#   ⇒ 若本实验证实 v1233 确实强得多，就说明：
#       **AUC 既不能选配方（铁律 160）、也不能选轮次（本条）——
#         权重上线必须逐个对局验证（AlphaZero 的 gating 就是这个道理）。**
#
# 【设计】三份权重同局对照，座位轮转，**换新的 seed0**（独立第三批局面）：
#     v1233 = 12:33 版权重（组1 里表现最好的）
#     v1333 = 13:33 版权重（G1 里表现平庸的）
#     none  = 关闭价值网络（基线）
#   `v1233 vs v1333` 的配对结果就是答案。
#
# 等 4 组锚点实验（ab4.log 出现 ALL DONE）自动接续，避免我盯着。
cd /root/autodl-tmp/sanchi || exit 1
PY=/root/miniconda3/bin/python

echo "=== [$(date '+%F %T')] 等 ab4 的 4 组跑完…"
while ! grep -q "ALL DONE" /root/autodl-tmp/ab4.log 2>/dev/null; do sleep 30; done
echo "=== [$(date '+%F %T')] 4 组已完，开始版本对决 ==="

$PY -u tools/ab_match.py \
    --games 300 --workers 6 --tl 0.2 --depth 1 --maxply 300 --threads 1 --seed0 4000000 \
    --cfg v1233=value_mlp_1233.json \
    --cfg v1333=value_mlp_frozen.json \
    --cfg none=- \
    --out _对照实验/ab_ver.json

echo "=== [$(date '+%F %T')] 版本对决完毕 ==="
