from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from . import bloom, cache, config, db, ids


@asynccontextmanager
async def lifespan(app: FastAPI):
    """进程启动 / 关闭时要做的事。"""
    n = bloom.load_from_db()
    print("[startup] 布隆过滤器预热完成，载入 %d 个短码" % n)
    yield


app = FastAPI(
    title="ShortLink",
    description="一个读多写少的高并发短链服务",
    version="0.3.0",
    lifespan=lifespan,
)


class CreateLinkReq(BaseModel):
    url: str


class CreateLinkResp(BaseModel):
    code: str
    short_url: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/links", response_model=CreateLinkResp)
def create_link(req: CreateLinkReq):
    url = req.url.strip()

    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="url 必须以 http:// 或 https:// 开头")
    if len(url) > config.URL_MAX_LEN:
        raise HTTPException(status_code=400, detail=f"url 超过 {config.URL_MAX_LEN} 个字符")

    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO links (code, url) VALUES (NULL, %s)", (url,))
            new_id = cur.lastrowid

            code = ids.make_code(new_id, config.CODE_LEN)
            cur.execute("UPDATE links SET code = %s WHERE id = %s", (code, new_id))

    # 新短码要立刻进过滤器，否则自己刚创建的短链会被判成「不存在」
    bloom.add(code)

    return CreateLinkResp(code=code, short_url=f"{config.BASE_URL}/{code}")


@app.get("/{code}")
def redirect_to_original(code: str):
    """访问短链，跳转到原始链接。

    v2 改造：先查 Redis，命中就直接跳，不再碰数据库。
    一个短链被访问 10000 次，现在只有第 1 次会落到 MySQL 上。

    注意用的是 302 而不是 301：
      301 = 永久重定向，浏览器会把结果缓存下来，用户第二次点就不经过我们的服务器了，
            点击统计会全部丢失。
      302 = 临时重定向，每次都回来问一次，所以能统计、也能随时改目标地址。
    这是短链服务的经典取舍，面试很爱问。
    """
    # ---- 第 1 道：布隆过滤器 ----
    # 它说「不存在」就一定不存在。海量随机短码的攻击会死在这一行，
    # Redis 的缓存查询和 MySQL 都不会被碰到。
    if not bloom.might_contain(code):
        raise HTTPException(status_code=404, detail="短码不存在")

    # ---- 第 2 道：Redis 缓存 ----
    r = cache.get_client()
    key = cache.cache_key(code)

    # 第一步永远是问缓存。
    # 注意 None 的含义是「缓存里没有」，不是「短码不存在」—— 这两件事要分清楚。
    url = r.get(key)

    if url is None:
        # ---------- 缓存未命中：回源查数据库 ----------
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, url FROM links WHERE code = %s", (code,))
                row = cur.fetchone()

                if row is None:
                    # 数据库里也没有 → 这个短码确实不存在。
                    # 把「空」也写进缓存：否则别人反复刷同一个不存在的短码，
                    # 每次都会穿透缓存打到数据库上（这就是「缓存穿透」）。
                    # 只存 60 秒，是为了万一它其实是个还没生成的短码，不至于错太久。
                    r.set(key, "", ex=cache.MISS_TTL)
                    raise HTTPException(status_code=404, detail="短码不存在")

                url = row["url"]

                # 点击计数。注意只有回源才会走到这里 ——
                # 换句话说：命中缓存的那 9999 次，clicks 一次都没加。
                # 这不是 bug，是 v2 的已知取舍，v5 用异步 + 批量写入来补。
                cur.execute("UPDATE links SET clicks = clicks + 1 WHERE id = %s", (row["id"],))

        # 回源拿到结果后写进缓存，下次就不用再查库了
        r.set(key, url, ex=cache.URL_TTL)

    elif url == "":
        # 命中的是上面写进去的「空值缓存」：这个短码确认不存在，直接 404。
        # 拿空字符串当哨兵是安全的 —— url 有校验，必须以 http:// 或 https:// 开头，
        # 所以真实数据的值永远不可能是个空串。
        raise HTTPException(status_code=404, detail="短码不存在")

    return RedirectResponse(url=url, status_code=302)