# -*- coding: utf-8 -*-
"""AutoDL 远程操作（本地私有工具，下划线开头 = 不进上传包）

凭据策略（2026-10-01 起**免密优先**）：
    ① 公钥免密：~/.ssh/id_ed25519_autodl（已装到云端 authorized_keys）
    ② 密码兜底：环境变量 AUTODL_PW（仅在免密失效时用；绝不写进文件）

    环境变量 AUTODL_HOST  默认 connect.nmb2.seetacloud.com
             AUTODL_PORT  默认 49682
             AUTODL_USER  默认 root

用法：
    python tools/_autodl_remote.py probe
    python tools/_autodl_remote.py run "nvidia-smi; nproc"
    python tools/_autodl_remote.py put dist/sanchi_autodl_x.zip /root/autodl-tmp/
    python tools/_autodl_remote.py tail /root/autodl-tmp/log.txt 40

★ 云端的 python 不在 PATH 里，必须写全路径：/root/miniconda3/bin/python
"""
import os
import sys
import time

import paramiko

HOST = os.environ.get("AUTODL_HOST", "connect.nmb2.seetacloud.com")
PORT = int(os.environ.get("AUTODL_PORT", "49682"))
USER = os.environ.get("AUTODL_USER", "root")
PW = os.environ.get("AUTODL_PW", "")
KEY = os.path.expanduser(os.environ.get(
    "AUTODL_KEY", "~/.ssh/id_ed25519_autodl"))


def connect(retries=3):
    """免密优先，密码兜底。"""
    pkey = None
    if os.path.exists(KEY):
        try:
            pkey = paramiko.Ed25519Key.from_private_key_file(KEY)
        except Exception as e:                       # noqa: BLE001
            print(f"  ⚠ 私钥加载失败（{KEY}）：{e}", flush=True)
    if pkey is None and not PW:
        sys.exit(f"✗ 免密私钥不可用且未设置 AUTODL_PW —— {KEY}")

    last = None
    for i in range(retries):
        for mode, kw in (("公钥", {"pkey": pkey}), ("密码", {"password": PW})):
            if kw.get("pkey") is None and not PW:
                continue
            try:
                c = paramiko.SSHClient()
                c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                c.connect(HOST, port=PORT, username=USER,
                          timeout=25, banner_timeout=25, auth_timeout=25,
                          allow_agent=False, look_for_keys=False, **kw)
                return c
            except Exception as e:                   # noqa: BLE001
                last = f"[{mode}] {e}"
        print(f"  连接失败（{i + 1}/{retries}）：{last}", flush=True)
        time.sleep(3)
    sys.exit(f"✗ 无法连接 {USER}@{HOST}:{PORT} —— {last}")


def run(c, cmd, timeout=900, quiet=False):
    """执行远程命令，返回 (rc, stdout, stderr)"""
    stdin, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    rc = stdout.channel.recv_exit_status()
    if not quiet:
        if out.strip():
            print(out.rstrip())
        if err.strip():
            print("--- stderr ---")
            print(err.rstrip())
    return rc, out, err


def put(c, local, remote):
    sftp = c.open_sftp()
    t0 = time.time()
    sftp.put(local, remote)
    sz = os.path.getsize(local)
    sftp.close()
    print(f"  上传 {os.path.basename(local)} → {remote}"
          f"  ({sz / 1024:.1f} KB, {time.time() - t0:.1f}s)")


def get(c, remote, local):
    sftp = c.open_sftp()
    sftp.get(remote, local)
    sftp.close()
    print(f"  下载 {remote} → {local}  ({os.path.getsize(local) / 1024:.1f} KB)")


PROBE = r"""
echo "===== 主机 ====="
hostname; uname -srm
echo; echo "===== CPU ====="
echo "核数 nproc = $(nproc)"
lscpu 2>/dev/null | grep -E "^Model name|^CPU\(s\)|^Thread|^Core|^Socket|MHz" | head -6
echo; echo "===== 内存 ====="
free -g 2>/dev/null | head -2
echo; echo "===== GPU ====="
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>&1 | head -3 || echo "(无 nvidia-smi —— 可能是无卡模式)"
echo; echo "===== 磁盘 ====="
df -h /root /root/autodl-tmp 2>/dev/null | grep -v "^Filesystem"
echo; echo "===== Python ====="
which python python3; python -V 2>&1; python3 -V 2>&1
python -c "import numpy,numba;print('numpy',numpy.__version__,'numba',numba.__version__)" 2>&1 | head -2
python -c "import torch;print('torch',torch.__version__,'cuda',torch.cuda.is_available())" 2>&1 | head -2
echo; echo "===== 网络 ====="
timeout 8 curl -sI https://pypi.org/simple/ 2>&1 | head -1 || echo "(pypi 不通)"
"""


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    c = connect()
    print(f"✓ 已连接 {USER}@{HOST}:{PORT}\n")
    try:
        if cmd == "probe":
            run(c, PROBE)
        elif cmd == "run":
            run(c, sys.argv[2], timeout=int(sys.argv[3]) if len(sys.argv) > 3 else 900)
        elif cmd == "put":
            put(c, sys.argv[2], sys.argv[3])
        elif cmd == "get":
            get(c, sys.argv[2], sys.argv[3])
        elif cmd == "tail":
            n = sys.argv[3] if len(sys.argv) > 3 else "40"
            run(c, f"tail -n {n} {sys.argv[2]}")
        else:
            sys.exit(f"未知子命令 {cmd}")
    finally:
        c.close()


if __name__ == "__main__":
    main()
