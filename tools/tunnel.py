"""启动 Cloudflare 快速隧道（quick tunnel），并把公网地址写进 .env 的 BASE_URL。

用法（在项目根目录下，或直接双击 tunnel-start.bat）：

    .venv\\Scripts\\python.exe tools\\tunnel.py

它做三件事：
  1. 起一个 cloudflared quick tunnel —— 不需要 Cloudflare 账号，域名是随机的
     https://xxx.trycloudflare.com；
  2. 从 cloudflared 的日志里抓出那个地址，改写 .env 里的 BASE_URL；
  3. 把 cloudflared 的输出继续打在屏幕上，直到你按 Ctrl+C（Ctrl+C 就是断隧道）。

为什么必须先跑它、再跑 start-all.bat：
  uvicorn 只在「启动那一刻」读一次 .env。所以正确的顺序是
      tunnel-start.bat  →  start-all.bat
  先让 .env 里的地址是新隧道地址，服务再起来，短链才会用这个地址。
  （服务已经在跑的话，改完 .env 要 stop-all.bat 再 start-all.bat。）

为什么不用 cloudflared 默认的 QUIC：
  这里固定用 --protocol http2（走 TCP 7844）。实测本机 UDP 7844 只有 region1 通、
  region2 不通，走 HTTP/2 更稳。
"""

import io
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
BACKUP = ROOT / "_local" / "backup" / ".env.bak.before-tunnel"

URL_RE = re.compile(r"https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com")

PLACEHOLDERS = [
    "",  # 空的就跳过
    os.environ.get("CLOUDFLARED", ""),
    r"D:\ProgramFiles\cloudflared\cloudflared.exe",
    r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
    "cloudflared",
]


def find_cloudflared():
    for c in PLACEHOLDERS:
        if not c:
            continue
        if c == "cloudflared":
            return c
        if os.path.isfile(c):
            return c
    return None


def set_base_url(url):
    """把 .env 里的 BASE_URL 换成 url，返回替换的行数。"""
    s = io.open(ENV_FILE, encoding="utf-8", newline="").read()
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    io.open(BACKUP, "w", encoding="utf-8", newline="").write(s)

    out, n = [], 0
    for line in s.split("\n"):
        if line.lstrip().startswith("BASE_URL="):
            out.append("BASE_URL=" + url)
            n += 1
        else:
            out.append(line)
    if n == 0:
        out.append("BASE_URL=" + url)
    io.open(ENV_FILE, "w", encoding="utf-8", newline="").write("\n".join(out))
    return n


def main():
    exe = find_cloudflared()
    if not exe:
        print("[错误] 找不到 cloudflared.exe")
        print("请把它放到 D:\\ProgramFiles\\cloudflared\\cloudflared.exe，")
        print("或者设一个环境变量 CLOUDFLARED 指向它的完整路径。")
        return 2

    if not ENV_FILE.is_file():
        print("[错误] 找不到 %s，请在项目根目录下运行。" % ENV_FILE)
        return 2

    env = dict(os.environ)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(k, None)

    cmd = [exe, "tunnel", "--url", "http://127.0.0.1:8000",
           "--protocol", "http2", "--no-autoupdate"]
    print("使用的 cloudflared:", exe)
    print("启动命令:", " ".join(cmd))
    print("-" * 72)

    proc = subprocess.Popen(
        cmd, cwd=str(ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True, encoding="utf-8", errors="replace", bufsize=1,
    )

    url = None
    t0 = time.time()
    try:
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            if url is None:
                m = URL_RE.search(line)
                if m:
                    url = m.group(0)
                    n = set_base_url(url)
                    print("")
                    print("=" * 72)
                    print("公网地址: %s" % url)
                    print("已写入 .env 的 BASE_URL（替换 %d 行，原文件备份在 %s）" % (n, BACKUP))
                    print("")
                    print("接下来：")
                    print("  服务还没起  -> 现在双击 start-all.bat")
                    print("  服务已经在跑 -> 先 stop-all.bat，再 start-all.bat（.env 不热重载）")
                    print("")
                    print("关掉这个窗口 = 隧道断开。Ctrl+C 停止。")
                    print("=" * 72)
                elif time.time() - t0 > 120:
                    # 注意：这个超时判断必须留在 "还没拿到地址" 的分支里。
                    # 一旦把它挪到外面（写成 elif 挂在 if url is None 上），
                    # 拿到地址之后每次有新日志都会走到这里 —— 隧道会在启动
                    # 约 120 秒后被自己 terminate 掉，而屏幕上报的还是
                    # 「120 秒还没拿到隧道地址」，症状和原因完全对不上。
                    print("[错误] 120 秒还没拿到隧道地址，退出。", flush=True)
                    proc.terminate()
                    return 3
    except KeyboardInterrupt:
        print("\n用户中断，关闭隧道。")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()

    return 0 if url else 1


if __name__ == "__main__":
    sys.exit(main())
