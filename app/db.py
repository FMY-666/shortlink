"""数据库访问层（v5：换成连接池）。

v1 的做法是「每次请求开一条连接，用完关掉」。
简单、不会出错，但建连接本身要花时间：TCP 三次握手 + MySQL 账号认证，毫秒级。
跳转接口每秒被调用上千次，等于每秒白扔掉上千个毫秒。

连接池做什么：
    进程启动时先建好几条连接放着。请求来了直接从池子里「借」一条，
    用完「还」回去 —— 连接一直在复用，不再反复握手。

注意 get_conn() 的用法一个字符都没变（with db.get_conn() as conn），
所以 main.py 一行都不用改。这就是「把变化封在模块内部」的价值。
"""

from contextlib import contextmanager

import pymysql
from dbutils.pooled_db import PooledDB
from pymysql.cursors import DictCursor

from . import config

_pool = PooledDB(
    creator=pymysql,
    maxconnections=20,   # 池子里最多 20 条连接（MySQL 默认最大连接数是 151）
    mincached=5,         # 启动时先建好 5 条，避免第一个请求还要等握手
    blocking=True,       # 池子空了就排队等，而不是直接抛异常
    ping=1,              # 每次借出前 ping 一下，被 MySQL 掐掉的空闲连接会自动重连
    host=config.DB_HOST,
    port=config.DB_PORT,
    user=config.DB_USER,
    password=config.DB_PASSWORD,
    database=config.DB_NAME,
    charset="utf8mb4",
    cursorclass=DictCursor,
    autocommit=False,
)


@contextmanager
def get_conn():
    """从池子里借一条连接，用完还回去。

    用法和 v1 完全一样：
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("...")
    """
    conn = _pool.connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()   # 注意：对池子里的连接来说，close 是「还回去」，不是真断开
