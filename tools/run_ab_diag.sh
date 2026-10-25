#!/bin/bash
# 对局台诊断（2026-10-02）：**先证明测量可信，再谈裁决权重**。
#
# 【为什么跑这个】
#   版本对决（配对，300 局）说：v1233 ≈ v1333 ≈ none（全无显著差异）。
#   但跨批次比较（exp1 前 198 局 vs ab4-G1 前 198 局）说：同一份 v1233
#   分别拿到 39.4% 和 19.7% 的胜率。**同一个权重、同一批 seed，两次差一倍**
#   ⇒ 矛盾在"测量"，不在"权重"。本脚本一次回答两个问题：
#
#   D1 = exp1 原配置原样重跑（none / v1233 / bal，300 局，seed0=2000000）
#        若重新得到 ~36% ⇒ exp1 的奇异来自别处；若得到 ~17% ⇒ exp1 本身是异常次
#   D2 = **空对照**：把**同一个权重**挂两个标签（x1/x2 指向同一文件）
#        两者强度**完全相等**（同进程还共用同一个 advisor 对象），
#        所以 x1:x2 的任何偏离都是**纯噪声** ⇒ 给出这套设计的噪声地板。
#        没有这个地板，任何"p<0.05"都没有意义。
#
# 【关键改进】`--tl 5.0`
#   depth=1 只需 3 plies（正常 0.05s 跑完），给 5s 等于**取消时间限制**。
#   原 tl=0.2 在本机（15 核配额，cpu.stat 显示 82% 周期被 throttle）会被
#   按"谁算得贵"差异化切断：价值网络每手要算 ~40 次前向 ⇒ 更容易超时 ⇒
#   整层作废、连价值重排一起失效、退化成 legal[0]。**这会把 A/B 变成
#   "测机器忙不忙"，而不是"测棋力"。** 新报告会打印健康度一栏来验收这件事。
cd /root/autodl-tmp/sanchi || exit 1
PY=/root/miniconda3/bin/python
COMMON="--workers 8 --tl 5.0 --depth 1 --maxply 300 --threads 1 --seed0 2000000"

echo "=== [$(date '+%F %T')] D1 复现 exp1 原配置（none / v1233 / bal）300 局 ==="
$PY -u tools/ab_match.py $COMMON --games 300 \
    --cfg none=- --cfg v1233=value_mlp_1233.json --cfg bal=value_mlp_bal.json \
    --out _对照实验/ab_D1_repro.json

echo "=== [$(date '+%F %T')] D2 空对照：同一权重挂两个标签（噪声地板）300 局 ==="
$PY -u tools/ab_match.py $COMMON --games 300 \
    --cfg none=- --cfg x1=value_mlp_frozen.json --cfg x2=value_mlp_frozen.json \
    --out _对照实验/ab_D2_null.json

echo "=== [$(date '+%F %T')] ALL DONE ==="
