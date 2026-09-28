"""令牌桶限流器（v5 新增）。

为什么必须用 Redis，而不能用进程内的变量：
    v6 会开多个 uvicorn worker 进程，每个进程有自己独立的内存。
    用进程内计数器的话，4 个 worker 各自允许 100 次/秒，
    实际放行就是 400 次/秒 —— 限流形同虚设。
    放 Redis 才能让所有进程共享同一个桶。

令牌桶和固定窗口的区别（面试常问）：
    固定窗口：这一秒最多 100 次。有人在第 999 毫秒打 100 次、
              下一秒第 1 毫秒又打 100 次 —— 2 毫秒内过了 200 次，
              窗口边界处会「双倍放行」。
    令牌桶：桶里按固定速率积累令牌，桶满了就不再增加。
            既限住了平均速率，又允许一定的瞬时突发（突发上限 = 桶容量）。
"""

import time

from . import cache

RATE = 100     # 每秒往桶里放多少个令牌（= 长期平均 QPS 上限）
BURST = 200    # 桶容量（= 允许的瞬时突发上限）

_KEY_PREFIX = "rl:"

# 整段逻辑必须原子执行：读令牌、按时间差补充、判断、写回去，
# 中间不能被另一个请求插队。所以写成 Lua 脚本交给 Redis 单线程跑，
# 而不是在 Python 里分几次调用 —— 那样在两次调用之间就会有竞态。
_LUA = """
local key   = KEYS[1]
local rate  = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local now   = tonumber(ARGV[3])
local cost  = tonumber(ARGV[4])

local data   = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts     = tonumber(data[2])

if tokens == nil then
  tokens = burst
  ts = now
end

-- 距离上次请求过去了多少毫秒，按速率补充令牌（最多补到桶容量）
local delta = math.max(0, now - ts)
tokens = math.min(burst, tokens + delta * rate / 1000)

local allowed = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
end

redis.call('HMSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, math.ceil(burst / rate) * 2 + 1)
return allowed
"""

_script = None


def _get_script():
    global _script
    if _script is None:
        # register_script 会把脚本正文缓存到 Redis 上，
        # 之后每次调用只传参数（EVALSHA），省掉重复传输脚本正文的开销
        _script = cache.get_client().register_script(_LUA)
    return _script


def allow(name: str, cost: int = 1) -> bool:
    """给 name（一般传客户端 IP）放一个令牌，放到了返回 True。

    cost 大于 1 就是「按权重限流」——比如搜索接口一次算 5 个令牌。
    """
    ok = _get_script()(
        keys=[_KEY_PREFIX + name],
        args=[RATE, BURST, int(time.time() * 1000), cost],
    )
    return bool(ok)


def peek(name: str) -> dict:
    """看一眼桶里还剩多少令牌，验证的时候用。"""
    r = cache.get_client()
    data = r.hgetall(_KEY_PREFIX + name)
    return {
        "tokens": float(data.get("tokens", 0)),
        "ts": int(data.get("ts", 0)),
        "ttl": r.ttl(_KEY_PREFIX + name),
    }
