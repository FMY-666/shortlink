# ShortLink · 高性能短链服务

一个读多写少的高并发服务。把长链接压成 6 位短码，访问短码时 302 跳转回原网址。

**状态：v1 已完成**（创建 + 跳转 + 点击统计）。下一站 v2：加 Redis 缓存。

## 这个项目在做什么

| 接口 | 作用 |
|---|---|
| `POST /api/links` | 传一个长链接，返回短码和短链 |
| `GET /{code}` | 访问短码，浏览器自动跳到原始链接 |
| `GET /health` | 健康检查，部署时探活用 |

关键事实：**创建一天几万次，访问一天几千万次**。业务复杂度为零，性能复杂度拉满——
这正是它适合拿来练手的原因：每一轮优化都能在本地压出真实的 before/after 数字。

## 快速开始

```bash
# 1. 建库建表
mysql -u root -p < schema.sql

# 2. 建虚拟环境并装依赖
python -m venv .venv
.venv\Scripts\activate          # macOS / Linux: source .venv/bin/activate
pip install -r requirements.txt

# 3. 配置
copy .env.example .env           # 然后编辑 .env 填上 MySQL 密码

# 4. 启动
python -m uvicorn app.main:app --reload
```

打开 http://127.0.0.1:8000/docs 可以看到交互式接口文档。

## 怎么用

服务起来之后，它就是一个"把长链接变短"的机器。三步就能跑通。

### 1. 创建一条短链

浏览器打开 <http://127.0.0.1:8000/docs>，展开 `POST /api/links` → 点 **Try it out** →
把 Request body 改成下面这行 → 点 **Execute**：

```json
{"url": "https://www.baidu.com"}
```

服务器返回：

```json
{
  "code": "000001",
  "short_url": "http://127.0.0.1:8000/000001"
}
```

`code` 是 6 位短码，`short_url` 是拼好的完整短链（前缀取自 `.env` 里的 `BASE_URL`）。

不想点鼠标就用命令行：

```bash
curl -X POST http://127.0.0.1:8000/api/links -H "Content-Type: application/json" -d "{\"url\":\"https://www.baidu.com\"}"
```

### 2. 访问短链

把 `http://127.0.0.1:8000/000001` 粘进浏览器地址栏。页面跳到百度，
**并且地址栏也从 `127.0.0.1:8000` 变成了 `www.baidu.com`** —— 这就是 302 在干活。

### 3. 查点击统计

每被访问一次，这条记录的 `clicks` 加 1：

```sql
USE shortlink;
SELECT id, code, url, clicks FROM links ORDER BY id DESC LIMIT 5;
```

### 4. 停掉服务

在跑 uvicorn 的那个窗口按 `Ctrl+C`。

> **注意**：服务只在 `127.0.0.1:8000` 上监听，**只有你这台机器能访问，别人的手机打不开**。
> 想给别人用，得等 v6 部署到云服务器。其他限制见文末的「已知问题」。

## 目录结构

```
shortlink/
├── app/               服务代码
│   ├── __init__.py
│   ├── config.py      配置读取（全部走环境变量）
│   ├── db.py          MySQL 连接与事务管理
│   ├── ids.py         短码生成（自增 id → 62 进制）
│   └── main.py        FastAPI 入口与路由
├── schema.sql         建库建表
├── verify.sql         建表后的自检查询
├── practice.sql       SQL 练习（用 mysql --force 跑）
├── requirements.txt
├── .env.example       配置模板，复制成 .env 再填密码
└── .gitignore
```

## 技术选型说明

- **FastAPI**：异步、自动生成 OpenAPI 文档（`/docs`），演示和截图方便
- **PyMySQL 而不是 ORM**：SQL 必须自己写。索引、慢查询、执行计划是面试重点，
  用 ORM 自动生成会把这些全部藏起来，你就失去了所有能聊的东西
- **302 而不是 301**：301 会被浏览器永久缓存，第二次点击不经过服务器，点击统计全丢

## 演进路线

- [x] **v1** 最小闭环：创建 + 跳转
- [ ] **v2** 缓存加速：Redis + Cache-Aside，读 QPS 提升
- [ ] **v3** 防穿透：手写布隆过滤器，挡住不存在的短码
- [ ] **v4** 发号器重构：数据库自增改号段模式，双 buffer 预取
- [ ] **v5** 稳定性：令牌桶限流、连接池、超时与熔断
- [ ] **v6** 上线调优：py-spy 火焰图定位热点、Docker、Nginx

## 已知问题（故意的，留给后面解决）

- 每次请求新建一条数据库连接 —— v5 引入连接池
- 每次跳转都要写一次库（点击计数）—— 这是最大的性能隐患，v2 之后会更明显
- 短码依赖数据库自增，创建接口的 QPS 被数据库按住 —— v4 换号段模式
- 短码有规律、可枚举 —— v4 换雪花算法或打乱字母表
