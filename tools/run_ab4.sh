#!/bin/bash
# A/B 锚点实验（2026-10-02）：**固定对比 none vs offi，第三方换 4 种**。
#
# 【为什么要这么设计】
#   当天早先两组实验结论**相反**：
#     组1（第三方 bal ）： none 18.3% vs offi 36.3%，p<0.0001 ⇒ offi 强
#     组2（第三方 osml）： none 12.3% vs offi 13.3%，p=0.820  ⇒ 无差异
#   而 `none` 是**同一个配置**，两组胜率却差 6 个百分点 —— 唯一的差别是第三方是谁。
#   ⇒ 三人棋里「A 比 B 强」不是绝对命题，**强依赖第三方**；单组 200~300 局噪声巨大。
#   本实验把 `none vs offi` 当**锚点对**，在 4 个不同第三方下各跑一遍：
#     · 若 4 组的符号方向一致 ⇒ 结论可信（再合并 p 值）
#     · 若方向摇摆 ⇒ 说明这个差距小于"对手构成"带来的扰动，不能上线
#
# 【权重必须冻结】
#   组2 的教训：A/B 指向 `value_mlp.json`（守护会不断覆盖），
#   结果跑到一半（13:33）文件被换掉 ⇒ 前后半程用的不是同一份权重。
#   本脚本一律用 `*_frozen.json`（cp -p 冻结的副本，守护不碰）。
cd /root/autodl-tmp/sanchi || exit 1
PY=/root/miniconda3/bin/python
COMMON="--games 200 --workers 6 --tl 0.2 --depth 1 --maxply 300 --threads 1 --seed0 2000000"

run() {   # $1 = "标签=权重[:λ]"   $2 = 输出文件名
    echo "=== [$(date '+%F %T')] 跑 $1 ==="
    $PY -u tools/ab_match.py $COMMON \
        --cfg none=- --cfg offi=value_mlp_frozen.json --cfg "$1" \
        --out "_对照实验/$2"
}

run "bal=value_mlp_bal.json"           ab_G1.json
run "osml=value_mlp_small_frozen.json" ab_G2.json
run "l70=value_mlp_frozen.json:0.70"   ab_G3.json
run "logi=value_logi.json"             ab_G4.json
echo "=== [$(date '+%F %T')] ALL DONE ==="
