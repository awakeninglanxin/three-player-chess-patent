#!/bin/bash
# 对局台诊断 第二轮（2026-10-02）：**正交拆解"tl"与"同场对手"两个嫌疑**。
#
# 【已知】
#   A = {none, v1233, bal }  tl=5.0  ⇒ v1233 **37.3%**、none 17.7%（= D1，复现了 exp1）
#   D = {none, v1233, v1333} tl=0.2  ⇒ v1233 **17.0%**、none 16.3%（= 版本对决）
#   同一个 v1233、同一 seed0、同样 300 局，两次差 **20 个百分点**。
#   两个变量同时变了：① tl（5.0→0.2） ② 第三家（bal→v1333）。
#
# 【B/C 就是为了把这两条分开】
#   B = {none, v1233, bal }  tl=0.2   —— 只改 tl（与 A 比）⇒ 若是 tl 的锅，v1233 应掉到 ~17%
#   C = {none, v1233, v1333} tl=5.0   —— 只改第三家（与 A 比）⇒ 若是"两家 mlp 互相抵消"，
#                                        v1233 应仍是高分
#   D = {none, v1233, v1333} tl=0.2   —— 与 C 配成 tl 的对照（把版本对决重做一次，带健康度）
#
# 【判读表】
#   B 高 & C 高 ⇒ 之前的分歧是"tl=0.2 时那一次的偶发"（例如机器恰好很忙）
#   B 高 & C 低 ⇒ **同场两家 mlp 会互相抵消**（三人棋特有的现象）
#   B 低 & C 高 ⇒ **tl 是根因**：时间一紧，价值网络就白给
#   B 低 & C 低 ⇒ 两个因素叠加（也最可能 —— 因为两者都在削弱价值网络的发挥）
cd /root/autodl-tmp/sanchi || exit 1
PY=/root/miniconda3/bin/python
BASE="--workers 8 --depth 1 --maxply 300 --threads 1 --seed0 2000000"

run() {   # $1=tl  $2=第三家 cfg  $3=输出名  $4=说明
    echo "=== [$(date '+%F %T')] $4 ==="
    $PY -u tools/ab_match.py $BASE --games 300 --tl "$1" \
        --cfg none=- --cfg v1233=value_mlp_1233.json --cfg "$2" \
        --out "_对照实验/$3"
}

run 0.2 "bal=value_mlp_bal.json"      ab_B_tl02_bal.json    "B: {none,v1233,bal}  tl=0.2（只改 tl）"
run 5.0 "v1333=value_mlp_frozen.json" ab_C_tl50_1333.json  "C: {none,v1233,v1333} tl=5.0（只改第三家）"
run 0.2 "v1333=value_mlp_frozen.json" ab_D_tl02_1333.json  "D: {none,v1233,v1333} tl=0.2（版本对决重做，带健康度）"
echo "=== [$(date '+%F %T')] ALL DONE ==="
