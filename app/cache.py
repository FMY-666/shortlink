"""Redis 客户端与缓存键的构造。

v2 新增。目标：把「访问短链」这个高频读操作挡在数据库前面。

对照 v1 的问题：
    db.py 里的 _connect() 是「每个请求建一条新连接」，
    建 TCP + MySQL 认证握手是毫秒级的，而跳转接口是整个系统里被调用最频繁的接口。
    Redis 这边反过来 —— 连接池在模块加载时建一次，之后所有请求复用。

这个文件本身很短，但它是 v2 能提速的关键：
    连接复用 + 把读操作从 MySQL 挪到内存。
"""

import redis

from . import config

# ---- 两个过期时间，单位秒 ----
URL_TTL = 3600    # 正常短链：缓存 1 小时
MISS_TTL = 60     # 不存在的短码：只缓存 60 秒

# 连接池是模块级的，整个进程共享一份。
# decode_responses=True 让读出来直接是 str，否则是 bytes，每处都要手动 decode。
_pool = redis.ConnectionPool(
    host=config.REDIS_HOST,
    port=config.REDIS_PORT,
    db=config.REDIS_DB,
    decode_responses=True,
    max_connections=50,
)


def get_client() -> redis.Redis:
    """拿一个 Redis 客户端。注意：这里没有真的建连接，用的是池子里的。"""
    return redis.Redis(connection_pool=_pool)


def cache_key(code: str) -> str:
    """缓存键的命名规则。统一走这个函数，以后想改前缀只改一处。"""
    return f"link:{code}"