# AutoDL 配置与操作手册（三人象棋 · AlphaZero 化）

> 目标：把「800 局自对弈 → AUC 0.75」扩到「10 万局 → AUC 0.85+」，
> 验证**瓶颈是数据量而不是算法**。
>
> 本手册的所有数字都来自本机实测（`tests/_bench_selfplay_throughput.py`），
> 不是拍脑袋估的。

---

## 〇、一页结论（照这个买就行）

| 项目 | 建议 | 理由 |
|---|---|---|
| **GPU 型号** | **RTX 3090 24G**（¥1.32/时） | 本轮**几乎用不到 GPU**（见第二节）。3090 性价比最高；若预算宽松上 4090（¥1.88/时） |
| **CPU 核数** | **≥ 12 核，最好 16 核**（选机型时**优先看这一列**） | 自对弈产数据是**纯 CPU 任务**，核数直接决定工时 |
| **内存** | ≥ 32 GB | 16 个 worker 各带一份棋盘 + numba 工作区 |
| **镜像** | `PyTorch 2.x / Python 3.12 / CUDA 12.1` 或 `Miniconda3` | 只有 3 个依赖（numpy/numba/torch），环境极简 |
| **磁盘** | 系统盘 30G 够用；数据放 `/root/autodl-tmp` | 10 万局的 npz 只占 ~0.5 GB |
| **预计总花费** | **¥5 ~ ¥15** | 产数据 3 小时 + 训练 10 分钟 + 装环境 |

**一句话**：**钱花在核数上，不要花在 GPU 上。**

---

## 一、为什么「需要 GPU」这个前提，在本轮其实不成立

我先把任务拆开看每一段到底吃什么资源：

| 阶段 | 干什么 | 吃 CPU 还是 GPU |
|---|---|---|
| ① 自对弈产数据 | 跑 10 万局三人棋，每步做 3 plies alpha-beta 搜索 | **100% CPU**（numba JIT 内核，纯整数/浮点，零 GPU） |
| ② 训练价值网络 | 32 维特征 → MLP(64,32) → 1 个胜率 | **CPU 就够**，GPU 反而更慢（见下） |
| ③（将来）MCTS + ResNet 双头 | 每步上千次网络推理 | **这里才真正需要 GPU** |

**第②段为什么 GPU 反而慢**：网络只有 `32 → 64 → 32 → 1`，参数量约 4 千个，
batch 1024。这个规模在 GPU 上 kernel launch 的开销（每次几微秒）会**盖过**计算本身，
实测小网络 CPU 比 GPU 快 2~5 倍。本机 800 局数据（6.4 万样本）CPU 训练只要 **561 秒**。

⇒ **所以本轮买 GPU 只是为第③段做准备。如果只做第①②段，甚至可以不开卡。**

---

## 二、本机实测标定（这是买几核的唯一依据）

测试条件：12 逻辑核 / `tl=0.02s` / `maxply=250` / Windows **spawn** 启动
（每个子进程都要独立 JIT 编译一次，占了大头）。

| 进程数 | 墙钟 | 其中预热 | 其中纯产局 | 总吞吐 | **纯产局吞吐** |
|---:|---:|---:|---:|---:|---:|
| 1 | 26.2s | 16.4s | 8.3s | 0.46 局/秒 | **1.45 局/秒** |
| 2 | 30.5s | 18.1s | 10.6s | 0.79 | 2.26 |
| 4 | 36.8s | 22.8s | 12.0s | 1.30 | 4.00 |
| 8 | 56.1s | 34.5s | 18.4s | 1.71 | 5.22 |
| **12** | **72.6s** | **50.7s** | **23.1s** | **1.98** | **6.23** |

**关键发现：并行效率只有 36%**

- 单核真实速度：**0.69 秒/局**（1.45 局/秒）
- 12 核并行实测：**6.23 局/秒**，而线性外推应是 17.4 局/秒
- 验证过不是线程过度订阅（`NUMBA_NUM_THREADS=1` 结果完全一样，
  因为我们的 njit 没有 `parallel=True`，本来就是单线程）
- **真因：内存带宽争抢** —— 每局要反复扫全盘 135 点、访问 DIST 矩阵，
  16 个进程同时跑就是在抢同一条内存通道。这类任务的并行效率 40% 左右是正常的。

**Linux（AutoDL）会比这个数字更好**，因为：
1. `fork` 启动 ⇒ 父进程先 `warmup()`，子进程**白嫖**已编译产物，**预热归零**
2. 服务器 CPU 单核速度通常比笔记本快 1.3~1.8 倍

### 外推表（保守，已含 40% 并行效率折损）

| 核数 | 估计吞吐 | 10 万局 | 30 万局 |
|---:|---:|---:|---:|
| 8 | ~5 局/秒 | 5.6 h | 16.7 h |
| **12** | **~7 局/秒** | **4.0 h** | 11.9 h |
| **16** | **~9 局/秒** | **3.0 h** | 9.0 h |
| 24 | ~13 局/秒 | 2.1 h | 6.4 h |
| 32 | ~17 局/秒 | 1.6 h | 4.8 h |

⇒ **12 核够用（4 小时），16 核舒服（3 小时）。再往上边际收益递减。**

---

## 三、具体怎么配（照着点）

### 3.1 机型选择页要看的三列
1. **GPU 型号** → 3090（本轮够）
2. **CPU 核数** → **挑最大的那档**（这列才是关键）
3. **内存** → ≥ 32GB

### 3.2 镜像
- 首选：`PyTorch 2.x` + `Python 3.12`（或 3.10/3.11）+ `CUDA 12.1`
- 备选：`Miniconda3`（自己建环境）

⚠️ 本机是 **Python 3.12.2 + numpy 2.4.3 + numba 0.65.0**，云端尽量对齐。

### 3.3 环境安装（**先在「无卡模式」做完**，¥0.1/时，省 95% 费用）

```bash
# 1) 上传并解压（JupyterLab 直接拖 zip 进去也行）
cd /root/autodl-tmp
unzip -q sanchi_autodl_*.zip -d sanchi
cd sanchi

# 2) 装依赖（只有 3 个包，秒装）
pip install -r requirements_cloud.txt

# 3) 自检：GPU 是否可用（**不要**在这里 pip install torch！）
python -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"

# 4) 自检：规则引擎能不能加载（三人象棋的 DXF 变形网格 + 军帐 + 三角区）
python -c "
import sys; sys.path[:0]=['server','server/engine','server/agents']
from engine import game_dxf as GA
s = GA.new_game(first=1)
print('开局点数', len(s['board']), '  轮次', s['turn'])
print('魏方合法着法', len(GA.legal_moves(s, 1)), '手')
"
```

### 3.4 先跑一个**小标定**（1 分钟，确认云端真实速度）

```bash
python tools/cloud_selfplay.py --games 200 --workers 16 --out data/_probe.npz
```

看输出的 `吞吐 N 局/秒`。用它乘 `3600` 就是每小时的局数，
再决定 `--games` 报多少 —— **不要盲目报 10 万**。

---

## 四、正式跑（三步）

```bash
# ① 产数据（把 --workers 设成 CPU 核数；脚本会自动 fork 白嫖 JIT 预热）
python tools/cloud_selfplay.py \
    --games 100000 --workers 16 --tl 0.02 --maxply 250 --eps 0.12 --cap 40 \
    --out data/selfplay_100k.npz \
    2>&1 | tee log_selfplay.txt

# 断了没关系 —— 分片已落盘，加 --resume 接着跑
python tools/cloud_selfplay.py --games 100000 --workers 16 \
    --out data/selfplay_100k.npz --resume

# ② 训练（几分钟）
python tools/train_cloud.py --data data/selfplay_100k.npz \
    --hidden 64,32 --epochs 160 --tag 100k \
    2>&1 | tee log_train.txt

# ③ 下载回本机（三个文件）
#    server/agents/values/value_logi_100k.json
#    server/agents/values/value_mlp_100k.json
#    data/selfplay_100k.report.json
```

**训练输出必须看两个数**（`train_cloud.py` 会打出来）：

1. `val auc` —— 要 **≥ 0.80**（本机 800 局是 0.7511，base 0.5741）
2. **`④ ★ 稳健性自检`** —— `mlp` 的矛盾对数必须**掉到接近 0**
   （本机 800 局是 **148/946 ❌**，这就是它不能上线的原因）

**只要稳健性自检还有几百对矛盾，就不许上线** —— 那说明网络在噪声里排名。

---

## 五、三种规模的选择

| 方案 | 局数 | 预计工时（16 核） | 花费 | 目的 |
|---|---|---|---|---|
| **小试** | 2 万 | 40 分钟 | ~¥1 | 验证云端流程通不通 |
| **标准**（推荐先做） | **10 万** | **3 小时** | **~¥4** | 验证「数据量是不是瓶颈」 |
| **大干** | 30 万 | 9 小时 | ~¥12 | 若 10 万仍不够，再上 |

建议**先跑 10 万**：如果 AUC 从 0.75 → 0.85+，就证明瓶颈是数据，继续加；
如果 AUC 卡在 0.78 不动，**说明瓶颈是特征或算法，加数据没用** —— 那就转向 Phase 3。

---

## 六、五个必须知道的坑

1. **`numba` 必须 0.65.0，`numpy` 必须 2.4.3**
   `nb_core.py` 有 20+ 个 njit 内核，且是「Python 版 + JIT 版」双实现，
   由 `tests/_verify_numba_parity.py`（3517 项）逐位对拍。换版本可能改变浮点规约顺序，
   两边不再逐位一致 ⇒ 对拍全红。而且 `nb_core` 的 njit **一律不加 `cache=True`**
   （递归 njit + 磁盘缓存 = 读缓存必 SEGV），所以每个新进程都要重编译。

2. **不要 `pip install torch`**
   AutoDL 镜像自带 CUDA 版 torch，在这里再装会把它覆盖成 CPU 版，GPU 直接失效。

3. **`fork` 才白嫖 JIT 预热**
   Linux 默认就是 fork，脚本会自动用。**别手动改成 spawn**，
   否则每个 worker 都要重新编译（本机实测 12 进程预热要 50 秒）。

4. **数据放 `/root/autodl-tmp`**
   系统盘只有 30G 且重启可能丢；数据盘才是持久化的。

5. **跑完立刻关机**
   按量计费。产出只有几个 json，下载完就关。

---

## 七、拿回来怎么用（本机侧）

1. 把 `value_mlp_100k.json` / `value_logi_100k.json` 放进
   `server/agents/values/`，`report.json` 放进 `data/`
2. 我这边把**价值网络接入搜索**（老师 2026-10-01 定的方案 c：
   推荐与对弈都接、留开关、旧 `eval_dxf` 降级为快速兜底）
3. 跑门禁：`_verify_hint.py` / `_verify_hint_ui.js` / `numba_parity` 等
4. **对比验证**：同一局面（老师报的「送马」手）在新旧两种估值下的排名

> ⚠️ 注意：`value_net` 是 **CPU 推理**的（纯 torch CPU，32 维向量一次前向几微秒），
> 拿回本机**不需要 GPU**，也不会拖慢对弈台。

---

## 附：本手册涉及的命令速查

```bash
# 本机：打包上传
python tools/pack_autodl.py              # → dist/sanchi_autodl_<时间戳>.zip

# 本机：产能标定（买几核的依据）
python tests/_bench_selfplay_throughput.py

# 云端：小标定 → 正式产数据 → 训练
python tools/cloud_selfplay.py --games 200 --workers 16 --out data/_probe.npz
python tools/cloud_selfplay.py --games 100000 --workers 16 --out data/selfplay_100k.npz
python tools/train_cloud.py --data data/selfplay_100k.npz --tag 100k
```
