"""点击计数的异步批量写入（v5 新增）。

v2 为了把读操作挡在数据库外面，付出的代价是「命中缓存时点击统计丢失」——
    命中缓存意味着根本没查库，拿不到那一行的 id，UPDATE 自然写不了。

v5 把这笔账补回来，但不能退回「每次跳转写一次数据库」——
那正是 v2 干掉的瓶颈。

方案：
    跳转时只对 Redis 里的计数器 HINCRBY（纯内存操作，几十微秒）；
    后台协程每秒把累积的增量批量落库一次。
    MySQL 的写入量从「每次点击一次」降到「每秒一次批量」。

代价要说清楚：点击统计从此是「最终一致」的 ——
服务挂掉时，最多丢最后 1 秒的增量。对统计数据来说这是可以接受的，
对订单、余额这种数据就绝对不能这么干。
"""

import asyncio

from . import cache, db

FLUSH_INTERVAL = 1.0              # 每秒落库一次
PENDING_KEY = "clicks:pending"    # 一个 hash：短码 -> 还没落库的增量


def record(code: str) -> None:
    """记一次点击。只碰 Redis，完全不碰 MySQL。"""
    cache.get_client().hincrby(PENDING_KEY, code, 1)


def flush_once() -> int:
    """把累积的增量落库，返回这次写了几条。

    「取出」和「清空」放在一个 MULTI/EXEC 里，保证中间没有空隙：
    新来的 HINCRBY 要么进这一次的 HGETALL，要么进清空之后的新 hash，不会丢。
    （如果分两步做，第二步执行前服务崩了，这一批计数就没了。）
    """
    r = cache.get_client()
    pipe = r.pipeline(transaction=True)
    pipe.hgetall(PENDING_KEY)
    pipe.delete(PENDING_KEY)
    pending, _ = pipe.execute()

    if not pending:
        return 0

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            for code, delta in pending.items():
                cur.execute(
                    "UPDATE links SET clicks = clicks + %s WHERE code = %s",
                    (int(delta), code),
                )
    return len(pending)


async def flush_loop() -> None:
    """后台协程：每秒落一次库。在 main.py 的 lifespan 里启动。"""
    while True:
        await asyncio.sleep(FLUSH_INTERVAL)
        try:
            # to_thread：pymysql 是同步阻塞的，直接在协程里跑会卡住整个事件循环
            await asyncio.to_thread(flush_once)
        except Exception as exc:
            print("[clicks] 落库失败：%s" % exc)
