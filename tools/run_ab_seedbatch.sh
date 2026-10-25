#!/bin/bash
# 补上缺的那一格（2026-10-02）：**固定第三方 bal，换 seed 批次**。
#
# 【要回答什么】
#   现有 7 组里，`v35 vs none` 的配对序数判决是：
#     third=bal    @ seed0=2000000 ⇒ 144:72（v 强）/ 126:86（v 强）  ← 两次都一边倒
#     third=v1333  @ seed0=2000000 ⇒  80:107 / 94:90                ← 打平
#     third=v60    @ seed0=2100000 ⇒  86:80                          ← 打平
#     third=v15    @ seed0=2100000 ⇒  67:100（none 强）
#     third=v85    @ seed0=2100000 ⇒ 127:126                         ← 打平
#   两个变量在同时变：**第三方** 与 **seed 批次**。本脚本固定第三方=bal，
#   把 seed 换掉 ⇒ 若照样"v 强"，则**根源是第三方**（SOUL 163 的结论成立）；
#   若变成打平，则**根源是 seed 批次**（说明 300 局的批次噪声足以翻转结论）。
#
# 【顺带】每个 seed 各跑两次不同的 batch，估**批次间**的散布。
cd /root/autodl-tmp/sanchi || exit 1
PY=/root/miniconda3/bin/python
BASE="--workers 8 --tl 5.0 --depth 1 --maxply 300 --threads 1"

for S in 2100000 2300000 2400000; do
    echo "=== [$(date '+%F %T')] third=bal，seed0=$S ==="
    $PY -u tools/ab_match.py $BASE --games 300 --seed0 "$S" \
        --cfg none=- --cfg v35=value_mlp_1233.json:0.35 --cfg bal=value_mlp_bal.json \
        --out "_对照实验/ab_S${S}_bal.json"
done
echo "=== [$(date '+%F %T')] SEEDBATCH DONE ==="
