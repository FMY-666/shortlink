#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""零依赖压测脚本 —— 用来替代 Windows 上装不了的 wrk。

为什么会有这个文件：
    常见的方案是 `wrk -t4 -c100 -d30s`，但 wrk 是 Linux 工具，
    Windows 上没有可靠的原生版本。与其让你去折腾编译一个压测工具，
    不如用 Python 标准库写一个：只用 threading + http.client，
    不需要 pip install 任何东西，而且你能读懂它、能改它。

它到底在做什么（面试可能会问）：
    开 N 个线程，每个线程拿着一条 keep-alive 连接，在指定时长内不停地
    发请求、记录每条请求的耗时，最后把所有耗时排序算分位数。
    压测的本质就这两件事：**并发发请求** + **统计延迟分布**。

用法：
    # 压跳转接口（GET）
    python bench.py http://127.0.0.1:8000/000001
    python bench.py http://127.0.0.1:8000/000001 -c 100 -d 20

    # 压创建接口（POST）。用 --json-url 就不用和 cmd 的引号转义搏斗
    python bench.py http://127.0.0.1:8000/api/links --json-url "https://example.com/{n}" -c 20 -d 10

    # v3 布隆过滤器要用：每次请求换一个随机的短码，模拟有人拿海量
    # 不存在的短码来刷你的服务（这时「空值缓存」是挡不住的，
    # 因为每个短码都是新的，缓存里永远不会有）
    python bench.py http://127.0.0.1:8000/000001 --random

参数：
    url      要压的地址（带 --random 时，只有它的路径会被随机替换）
    -c       并发连接数（默认 50）
    -d       持续时间，秒（默认 15）
    -w       预热秒数，不计入统计（默认 2）
    -t       单请求超时，秒（默认 5）
    -X       请求方法，GET / POST（默认 GET）
    --json-url  压创建接口专用，只写 url，脚本自动拼成 {"url": "..."}；
              URL 里的 {n} 会替换成递增计数器，保证每次创建的链接都不一样
    -b       请求体模板（一般不用，除非要压别的接口）
    --random 每次请求换一个随机 6 位短码
"""

import argparse
import http.client
import itertools
import json
import random
import ssl
import string
import threading
import time
from collections import Counter
from urllib.parse import urlparse

# 生成随机短码用的字符集，和 ids.py 里的 ALPHABET 保持一致
CODE_CHARS = string.digits + string.ascii_lowercase + string.ascii_uppercase


class Stats:
    """线程安全的统计容器。多个 worker 线程会同时往里写。"""

    def __init__(self):
        self._lock = threading.Lock()
        self.latencies = []      # 每条成功请求的耗时，单位毫秒
        self.codes = Counter()   # HTTP 状态码分布，比如 302: 15234
        self.errors = Counter()  # 连接层异常分布，比如 RemoteDisconnected: 3

    def ok(self, ms, status):
        with self._lock:
            self.latencies.append(ms)
            self.codes[status] += 1

    def err(self, name):
        with self._lock:
            self.errors[name] += 1


def _pct(sorted_vals, p):
    """取第 p 百分位。传入的列表必须已经排好序。"""
    if not sorted_vals:
        return 0.0
    idx = int(round((p / 100.0) * (len(sorted_vals) - 1)))
    idx = max(0, min(len(sorted_vals) - 1, idx))
    return sorted_vals[idx]


def _random_code(length=6):
    return "".join(random.choices(CODE_CHARS, k=length))


def _worker(host, port, path, use_tls, timeout, stop_at, stats,
            random_code, method, body_tpl, json_url, counter):
    """一个 worker 线程：不停发请求直到到点。"""
    conn = None
    while time.perf_counter() < stop_at:
        this_path = "/" + _random_code() if random_code else path
        try:
            if conn is None:
                if use_tls:
                    conn = http.client.HTTPSConnection(
                        host, port, timeout=timeout,
                        context=ssl.create_default_context(),
                    )
                else:
                    conn = http.client.HTTPConnection(host, port, timeout=timeout)

            # 每次请求现场生成 body（把 {n} 换成递增计数器），
            # 这样压创建接口时，每条短链的 url 都不一样
            body = None
            headers = {}
            if json_url:
                # 这个入口是给创建接口用的：只写 url，JSON 由脚本自己拼，
                # 免得在 cmd 里和转义引号搏斗
                payload = {"url": json_url.replace("{n}", str(next(counter)))}
                body = json.dumps(payload).encode("utf-8")
                headers["Content-Type"] = "application/json"
            elif body_tpl:
                body = body_tpl.replace("{n}", str(next(counter))).encode("utf-8")
                headers["Content-Type"] = "application/json"

            t0 = time.perf_counter()
            conn.request(method, this_path, body=body, headers=headers)
            resp = conn.getresponse()
            resp.read()   # 必须把 body 读干净，否则这条连接没法复用
            ms = (time.perf_counter() - t0) * 1000.0
            stats.ok(ms, resp.status)

        except Exception as exc:
            # 连接断了 / 超时了就记一笔，丢掉这条连接下轮重连
            stats.err(type(exc).__name__)
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            conn = None

    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


def _run(host, port, path, use_tls, timeout, concurrency, duration, stats,
         random_code, method, body_tpl, json_url, counter):
    """开 concurrency 个线程压 duration 秒，返回实际耗时。"""
    stop_at = time.perf_counter() + duration
    threads = [
        threading.Thread(
            target=_worker,
            args=(host, port, path, use_tls, timeout, stop_at, stats,
                  random_code, method, body_tpl, json_url, counter),
            daemon=True,
        )
        for _ in range(concurrency)
    ]

    t0 = time.perf_counter()
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=duration + timeout + 5)
    return time.perf_counter() - t0


def main():
    ap = argparse.ArgumentParser(description="零依赖压测脚本（Python 标准库实现）")
    ap.add_argument("url", help="要压的地址，例如 http://127.0.0.1:8000/000001")
    ap.add_argument("-c", "--concurrency", type=int, default=50, help="并发连接数（默认 50）")
    ap.add_argument("-d", "--duration", type=float, default=15.0, help="持续秒数（默认 15）")
    ap.add_argument("-w", "--warmup", type=float, default=2.0, help="预热秒数，不计入统计（默认 2）")
    ap.add_argument("-t", "--timeout", type=float, default=5.0, help="单请求超时秒（默认 5）")
    ap.add_argument("-X", "--method", default="GET", help="请求方法，默认 GET")
    ap.add_argument("-b", "--body", default=None,
                    help='请求体模板，{n} 会替换成递增计数器')
    ap.add_argument("--json-url", default=None,
                    help='压创建接口专用：只写 url，脚本自动拼成 {"url": "..."}，'
                         '里面的 {n} 会替换成递增计数器。给了这个参数会自动切成 POST')
    ap.add_argument("--random", action="store_true",
                    help="每次请求换一个随机 6 位短码（用于测试缓存穿透防护）")
    args = ap.parse_args()

    u = urlparse(args.url)
    if not u.hostname:
        print("这个地址看不懂：%s" % args.url)
        return 2

    use_tls = (u.scheme == "https")
    port = u.port or (443 if use_tls else 80)
    path = u.path or "/"
    if u.query:
        path += "?" + u.query

    method = args.method.upper()
    if args.json_url and method == "GET":
        method = "POST"
    counter = itertools.count(1)   # 线程安全的自增计数器

    print("=" * 46)
    print("目标      %s" % args.url)
    print("方法      %s" % method)
    print("并发      %d 条连接" % args.concurrency)
    print("时长      %.1f s" % args.duration)
    if args.json_url:
        print("请求体    {\"url\": \"%s\"}" % args.json_url)
    elif args.body:
        print("请求体    %s" % args.body)
    if args.random:
        print("模式      随机短码（每次请求都不一样）")
    print("=" * 46)

    if args.warmup > 0:
        print("预热 %.1f s（结果丢弃，让连接池和缓存先热起来）..." % args.warmup)
        _run(u.hostname, port, path, use_tls, args.timeout,
             args.concurrency, args.warmup, Stats(), args.random,
             method, args.body, args.json_url, itertools.count(1))

    print("压测中，请稍候 ...")
    stats = Stats()
    elapsed = _run(u.hostname, port, path, use_tls, args.timeout,
                   args.concurrency, args.duration, stats, args.random,
                   method, args.body, args.json_url, counter)

    done = len(stats.latencies)
    failed = sum(stats.errors.values())

    print()
    print("---------------- 结果 ----------------")
    print("总请求    %d" % (done + failed))
    print("拿到响应  %d" % done)
    print("失败      %d" % failed)
    print("实际耗时  %.2f s" % elapsed)
    print()
    print("QPS       %.1f" % (done / elapsed if elapsed > 0 else 0.0))

    if stats.codes:
        parts = ["%s: %d" % (k, v) for k, v in sorted(stats.codes.items())]
        print("状态码    %s" % " | ".join(parts))
    if stats.errors:
        parts = ["%s: %d" % (k, v) for k, v in sorted(stats.errors.items())]
        print("错误      %s" % " | ".join(parts))

    lats = sorted(stats.latencies)
    if lats:
        avg = sum(lats) / len(lats)
        print()
        print("延迟(ms)  平均 %.1f" % avg)
        print("          P50  %.1f   <- 一半的请求比它快" % _pct(lats, 50))
        print("          P95  %.1f   <- 95%% 的请求比它快" % _pct(lats, 95))
        print("          P99  %.1f   <- 尾延迟，压测最该看的数字" % _pct(lats, 99))
        print("          最大 %.1f" % lats[-1])

    print("--------------------------------------")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
