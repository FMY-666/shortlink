"""手写布隆过滤器（Bloom Filter）。

v3 新增。要解决的问题：

    v2 用「空值缓存」挡住了对同一个不存在短码的反复请求，
    但如果对方每次换一个随机的短码，空值缓存就完全失效了 ——
    每个码都是新的，缓存里永远不会有它，于是全部穿透到 MySQL。

布隆过滤器（Bloom Filter）的性质，只有两条，必须记牢：

    说「不存在」 → 一定不存在（可以放心拒绝）
    说「可能存在」→ 可能误判，还得继续往下查缓存 / 数据库

换句话说：它不会漏报（false negative 恒为 0），但会误报（false positive）。

代价小得离谱：2 MB 的内存，就能记住上百万个短码，误判率只有万分之几。

为什么用 Redis 的 bitmap，而不是 Python 的 bytearray：
    bytearray 是进程内内存。v6 会开多个 uvicorn worker 进程，
    每个进程一份 bytearray，各自只知道自己启动时灌进去的那些短码 ——
    新建的短码只在某一个进程里，其它进程会说它「不存在」，直接 404。
    放 Redis 里所有进程共用一份，这个问题就不存在了。
"""

import hashlib

from . import cache, db

# ---- 三个参数，决定了「内存占用」和「误判率」之间的平衡 ----
BIT_SIZE = 1 << 24    # 位数组长度：2^24 = 16777216 位 = 2 MB
HASH_COUNT = 7        # 每个短码点亮 7 个位
BLOOM_KEY = "bloom:links"


def _positions(code: str):
    """把短码映射成 HASH_COUNT 个位下标。

    手法叫「双重哈希」（double hashing）：先算两个独立的哈希 h1、h2，
    再用 h1 + i * h2 派生出第 i 个位置。

    好处是只需要算两次哈希函数就能得到任意多个位置，
    而且理论上证明它和「真的写 7 个不同的哈希函数」效果差不多。
    """
    raw = code.encode("utf-8")
    h1 = int.from_bytes(hashlib.md5(raw).digest()[:8], "big")
    h2 = int.from_bytes(hashlib.sha1(raw).digest()[:8], "big")
    for i in range(HASH_COUNT):
        yield (h1 + i * h2) % BIT_SIZE


def add(code: str) -> None:
    """把一个短码加进过滤器。SETBIT 是 O(1) 的，7 个位一次管道发出去。"""
    r = cache.get_client()
    pipe = r.pipeline(transaction=False)
    for pos in _positions(code):
        pipe.setbit(BLOOM_KEY, pos, 1)
    pipe.execute()


def might_contain(code: str) -> bool:
    """判断短码「可能存在」。

    返回 False = 一定不存在（7 个位里只要有一个是 0，就说明从没加过它）
    返回 True  = 可能存在（7 个位全是 1，但这 7 个位很可能是别的短码碰巧一起点亮的）
    """
    r = cache.get_client()
    pipe = r.pipeline(transaction=False)
    for pos in _positions(code):
        pipe.getbit(BLOOM_KEY, pos)
    return all(pipe.execute())


def load_from_db() -> int:
    """预热：把库里已有的短码全部灌进过滤器，返回灌了多少个。

    为什么必须先预热？
    过滤器是空的，就等于说「谁都不存在」—— 所有正常短链都会被判 404。
    所以服务启动时第一件事就是把它填满。
    """
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT code FROM links WHERE code IS NOT NULL")
            codes = [row["code"] for row in cur.fetchall()]

    if codes:
        r = cache.get_client()
        pipe = r.pipeline(transaction=False)
        for code in codes:
            for pos in _positions(code):
                pipe.setbit(BLOOM_KEY, pos, 1)
        pipe.execute()
    return len(codes)


def reset() -> None:
    """清空过滤器。

    库被 TRUNCATE 之后一定要调它，否则旧短码还留在过滤器里，
    会出现「库里没有但这个码能通过过滤器」的假象。
    """
    cache.get_client().delete(BLOOM_KEY)


def stats() -> dict:
    """看一眼当前状态，验证的时候用。"""
    r = cache.get_client()
    return {
        "bits": BIT_SIZE,
        "hashes": HASH_COUNT,
        "set_bits": r.bitcount(BLOOM_KEY),
        "capacity": "约 100 万短码，误判率约 0.05%",
    }