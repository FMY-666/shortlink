from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from . import config, db, ids

app = FastAPI(
    title="ShortLink",
    description="一个读多写少的高并发短链服务",
    version="0.1.0",
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

    return CreateLinkResp(code=code, short_url=f"{config.BASE_URL}/{code}")


@app.get("/{code}")
def redirect_to_original(code: str):
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, url FROM links WHERE code = %s", (code,))
            row = cur.fetchone()

            if row is None:
                raise HTTPException(status_code=404, detail="短码不存在")

            cur.execute("UPDATE links SET clicks = clicks + 1 WHERE id = %s", (row["id"],))

    return RedirectResponse(url=row["url"], status_code=302)