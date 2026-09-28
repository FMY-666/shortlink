"""号段模式发号器（segment allocator）。

v4 新增。要解决的问题：

    v1~v3 创建一条短链要写两次数据库：
        INSERT 拿到自增 id   →   UPDATE 把算好的 code 写回去
    两次写都发生在同一个请求里，创建接口的吞吐被数据库死死按住。

号段模式的思想（美团 Leaf 的 leaf-segment 方案）：

    不要每次都去数据库要一个 id，而是一次要「一整段」id 放在内存里，
    之后在内存里发号 —— 发号这个动作从此完全不碰数据库。

    代价有两个，都要能说清楚：
      1. id 不再连续 —— 服务重启会丢掉没用完的那半段，于是有空洞；
      2. 需要额外一张表来记录「已经发到哪了」。

「双 buffer」是什么：
    内存里同时存两个段：正在用的（current）和备用的（next）。
    当前段用掉 80% 时，后台线程悄悄去数据库把下一段取回来。
    这样等当前段真用完时，直接切到备用段，**发号这个动作永远不会等数据库**。
    只有一种情况会卡：备用段还没取回来当前段就先用完了（预取失败 / 取太慢）。
"""

import threading

from . import db

BIZ_TAG = "link_id"    # 业务标识。以后别的业务也能用同一张表，靠这个字段区分
STEP = 1000          # 每次从数据库申请多少个 id
PREFETCH_AT = 0.8      # 当前段用掉 80% 就提前预取下一段

_lock = threading.Lock()
_current = None        # 正在用的段，三元组 (start, next, end)
_next = None           # 备用段，双 buffer 的另一半
_loading = False       # 预取是否正在进行，防止重复发起


def _new_segment():
    """去数据库申请一段，返回 (start, end)。

    关键在这一句：UPDATE biz_segment SET max_id = max_id + step WHERE biz_tag = %s
    它把「读」和「写」合成了一次原子操作。两个进程同时来申请，
    MySQL 的行锁保证它们拿到不同的段 —— 这就是多进程不重复发号的原因。
    """
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE biz_segment SET max_id = max_id + step WHERE biz_tag = %s",
                (BIZ_TAG,),
            )
            if cur.rowcount == 0:
                # 第一次运行，表里还没有这一行，建一行再发第一段
                cur.execute(
                    "INSERT INTO biz_segment (biz_tag, max_id, step) VALUES (%s, %s, %s)",
                    (BIZ_TAG, STEP, STEP),
                )
                return 1, STEP

            cur.execute("SELECT max_id, step FROM biz_segment WHERE biz_tag = %s", (BIZ_TAG,))
            row = cur.fetchone()
            end = row["max_id"]
            return end - row["step"] + 1, end


def _prefetch():
    """后台线程：提前把下一段取回来。这就是「双 buffer」的另一半。"""
    global _next, _loading
    try:
        seg = _new_segment()
    except Exception as exc:
        # 预取失败不能影响发号，下一次请求还会再试
        print("[segment] 预取失败：%s" % exc)
        seg = None
    with _lock:
        _next = seg
        _loading = False


def next_id() -> int:
    """发一个 id。绝大多数情况下，这只是内存里的加法。"""
    global _current, _next, _loading
    with _lock:
        if _current is None:
            start, end = _new_segment()
            _current = (start, start, end)

        start, nxt, end = _current
        if nxt > end:
            # 当前段发完了。正常情况下这里早该有备用段了
            if _next is None:
                _next = _new_segment()     # 没预取到，只能同步取一次（这一下会卡）
            start, end = _next
            _next = None
            nxt = start

        value = nxt
        _current = (start, nxt + 1, end)

        # 用掉 80% 就提前把下一段取回来
        used = (nxt - start + 1) / (end - start + 1)
        if used >= PREFETCH_AT and _next is None and not _loading:
            _loading = True
            threading.Thread(target=_prefetch, daemon=True).start()

        return value


def status() -> dict:
    """看一眼发号器当前状态，验证的时候用。"""
    with _lock:
        return {"current": _current, "next": _next, "loading": _loading}
