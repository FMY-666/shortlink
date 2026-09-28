# 踩坑记录 · v1 → v3

从零到 GitHub 上线的全过程里，**实际撞到的每一个报错**。

报错原文直接来自当时的终端输出，不是后来补编的。每条都写清四件事：
**现象 → 根因 → 怎么修 → 下次怎么避免**。

- 时间跨度：2026-09-26 建库 → 2026-09-27 v1 上线、v2 缓存上线 → 2026-09-28 v3 布隆过滤器
- 技术栈：Python 3.14 + FastAPI + MySQL 8.0.45 + Redis 8.10.2 + Git
- 版本对应：v1 = 建库到上线，v2 = Redis 缓存，v3 = 布隆过滤器
- 条目：**v1 段 18 条 + v2 段 4 条 + v3 段 2 条 = 24 条**

---

## 问题总览

| # | 问题 | 类别 | 严重度 |
|---|---|---|---|
| 1 | `code` 列大小写不敏感，62 进制悄悄变成 36 进制 | 数据库 | ★★★ 招牌 |
| 2 | `ERROR 1046 (3D000): No database selected` | 数据库 | ★ |
| 3 | 自增 id 有空洞、短码跳号 | 数据库 | 认知类 |
| 4 | `OperationalError 1045 / 2003` 连不上库 | 数据库 | ★★ |
| 5 | `SyntaxError: invalid syntax`，报错行正好是最后一行 | 代码 | ★★ |
| 6 | `SyntaxError` 出现在*不该出现的*行 | 代码 | 认知类 |
| 7 | `.env` 密码没改，仍是模板值 | 配置 | ★★ |
| 8 | `cd D:\...` 跨盘符静默失败 | 命令行 | ★★★ 踩了三次 |
| 9 | `curl` 的 `^` 续行吞掉 `-d` 参数 | 命令行 | ★★ |
| 10 | SQL 敲进了 cmd 而不是 `mysql>` | 命令行 | ★ |
| 11 | 浏览器直接访问 `POST` 接口 → 405 | 命令行 | ★ |
| 12 | `short_url` 里的端口和服务端口不一致 | 配置 | ★★ |
| 13 | 本机根本没装 Git | Git | ★ |
| 14 | `nothing added to commit but untracked files present` | Git | ★★ |
| 15 | `fatal: not a git repository` | Git | ★★ |
| 16 | `Recv failure: Connection was reset` / `Could not connect to server` | 网络 | ★★★ |
| 17 | `git log` 中文乱码（虚惊一场） | 工具 | ★★ |
| 18 | `warning: LF will be replaced by CRLF` | Git | 虚警 |
| 19 | ⭐ Windows 版 `redis-cli` 把 `*` 当本地文件名展开 | 命令行 | ★★ |
| 20 | cmd 不支持多行粘贴 | 命令行 | ★★ |
| 21 | Redis 窗口被关 = 服务停掉（不是关日志界面） | 运行 | ★★ |
| 22 | `TypeError: _run() takes 12 ... but 13 were given` | 代码 | ★ |
| 23 | ⭐ `flushdb` 连带清掉 `bloom:links`，所有短链全 404 且不自愈 | 运行 | ★★★ |
| 24 | ⭐ 粘贴残留：`py_compile` 通过、服务照跑，`return` 后面躺着死代码 | 代码 | ★★★ |

---

## 一、数据库

### 1. ⭐ `code` 列大小写不敏感，62 进制悄悄变成 36 进制

**现象**

前 35 条创建都正常，第 36 条开始全部 500：

```
pymysql.err.IntegrityError: (1062, "Duplicate entry '00000A' for key 'links.uk_code'")
```

抛出点在 `app/main.py` 回填短码的那句：

```python
cur.execute("UPDATE links SET code = %s WHERE id = %s", (code, new_id))
```

查库发现：表里 39 行，`id` 是 **1–35 和 62–65**，**36–61 这 26 个 id 整段失踪**。

**根因**

`schema.sql` 里 `code` 列只写了 `VARCHAR(16) DEFAULT NULL`，**没指定 collation**。
MySQL 8 给 `utf8mb4` 的默认排序规则是 **`utf8mb4_0900_ai_ci`**，末尾 `ci` = **case insensitive（大小写不敏感）**。

而 62 进制字母表是 `0-9a-zA-Z`：

- `id=10` → `00000a`（小写 a）
- `id=36` → `00000A`（大写 A）

在大小写不敏感的规则下，`'00000a' = '00000A'` 成立 → `uk_code` 唯一索引判重 → 抛 `IntegrityError`。

**字母表里 10–35 是小写、36–61 是大写，两两配对，正好撞 26 次。**

```sql
-- 修复前的证据：明明查的是大写 A，命中的却是小写 a
SELECT id, code FROM links WHERE code = '00000A';
-- 返回 (10, '00000a')
```

**怎么修**

```sql
USE shortlink;
ALTER TABLE links MODIFY code VARCHAR(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL;
```

`bin` = binary，按字节比较，大小写敏感。

同步改 `schema.sql`，让新建的库不会再犯：

```sql
code VARCHAR(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL
```

**验证**

```sql
USE shortlink;
SHOW FULL COLUMNS FROM links;   -- Collation 列必须是 utf8mb4_bin
SELECT id FROM links WHERE code = '00000A';   -- 修复前返回 1 行，修复后返回 0 行
```

**实测对比**（临时库，60 并发创建）：

| `code` 列 collation | 成功 | 失败 | 白吃掉的 id |
|---|---|---|---|
| 不指定（`utf8mb4_0900_ai_ci`） | 35 | 25 | 25 |
| 显式 `utf8mb4_bin` | **60** | **0** | **0** |

**下次怎么避免**

- 所有**参与唯一性判断**的字符串列（短码、token、订单号、邀请码），一律显式写 `COLLATE utf8mb4_bin`。默认值是"给人搜的"，不是"给机器比对的"。
- **单元测试抓不到这个 bug**：它只在"第 36 条"之后才出现，前 35 条全绿。要么写跨边界的测试（一次跑 100 条），要么用并发压测扫边界。
- 顺带一个认知：库的默认 collation 是 `utf8mb4_general_ci`，但 MySQL 8 的表/列实际继承了新默认 `utf8mb4_0900_ai_ci`。**别靠记忆猜，`SHOW FULL COLUMNS` 看一眼最省事。**

**一个常见误区**：改完 collation **不需要重启 uvicorn**。collation 是 MySQL 的表属性，跟 Python 进程无关，改完下一句 `SELECT` 就按新规则比较。

---

### 2. `ERROR 1046 (3D000): No database selected`

**现象**

```sql
ALTER TABLE links MODIFY code VARCHAR(16) ... ;
-- ERROR 1046 (3D000): No database selected
```

**根因**

`ALTER TABLE links` 里的 `links` 是**没有带库名的裸表名**。刚登录 `mysql>` 时并没有选中任何一个库，MySQL 不知道该去哪个库里找 `links`。

**怎么修**

```sql
USE shortlink;
ALTER TABLE links MODIFY code VARCHAR(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL;
```

或者一条命令带全库名：

```sql
ALTER TABLE shortlink.links MODIFY code VARCHAR(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL;
```

**下次怎么避免**

只要不是紧跟在 `USE 库名;` 后面，SQL 里的表名就写成 `库名.表名`。多打几个字符，省一次报错。

---

### 3. 自增 id 有空洞、短码跳号 —— 这不是 bug

**现象**

`id` 是 1–35、62–65，中间 36–61 整段缺失；短码从 `000013` 跳到 `000014`，不连续。

**根因**

**MySQL 的自增值一旦分配出去就不退还**，无论这次插入最后成不成功：

- 插入撞唯一索引失败 → 吃掉一个 id
- 事务里 `INSERT` 之后 `ROLLBACK` → 照样吃掉一个 id

实测（临时库）：`INSERT` 后立刻 `ROLLBACK`，表里 0 行，但 `AUTO_INCREMENT` 已经 +1。

**怎么修**

不用修，这是**正常行为**，也是分布式发号器要解决的问题之一。
只有 `TRUNCATE TABLE` 会把自增一起归零（`DELETE FROM` 不会）。

```sql
USE shortlink;
TRUNCATE TABLE links;
SELECT COUNT(*) FROM links;   -- 0
-- 下一条短码回到 000001
```

**下次怎么避免**

- 别把"自增 id"当"第几条记录"用。
- **短码 ≠ 序号**：`000013` 对应的是 `id=65`，不是"第 13 条"。62 进制只是 id 的另一种写法。
- 一切涉及"总数"的统计都用 `COUNT(*)`，不要去猜 `MAX(id)`。

---

### 4. `OperationalError` 连不上数据库

**现象 A**

```
pymysql.err.OperationalError: (1045, "Access denied for user 'root'@'localhost' (using password: NO)")
```

注意末尾 `using password: NO` —— **压根没带密码过去**。

根因：`load_dotenv()` 默认从**当前工作目录**往上找 `.env`。在 `D:\dev` 下跑脚本时，`.env` 在 `shortlink\` 子目录里，找不到 → `DB_PASSWORD` 是空串。

修法：跑任何连库脚本前，先切到项目根：

```bash
cd /d D:\dev\shortlink
```

**现象 B**

```
pymysql.err.OperationalError: (1045, "Access denied for user 'root'@'localhost' (using password: YES)")
```

`using password: YES` = 密码带过去了，但**不对**。检查 `.env` 里的 `DB_PASSWORD`。

**现象 C**

```
pymysql.err.OperationalError: (2003, "Can't connect to MySQL server on '127.0.0.1'")
```

端口/地址不对，或 MySQL 服务没启动。这个错**耗时约 2 秒**才抛出（连接超时重试），可以据此区分它和前两种（前两种是立刻返回的）。

**下次怎么避免**

`pymysql.connect()` **不是懒加载，调用即连接**（TCP 三次握手 + 认证）。
所以"连接测试"可以有意识地在启动早期做一次，让错误尽早暴露，而不是等第一个用户请求进来才炸。

---

## 二、Python 代码

### 5. `SyntaxError`，而报错行正好是文件的最后一行

**现象**

```
File "D:\dev\shortlink\app\main.py", line 23
    @app.get("/health")
    ^
SyntaxError: invalid syntax
```

第 23 行是文件末尾，内容是一个**光秃秃的装饰器**，下面没有 `def health():`。

**根因**

**文件没敲完。** 装饰器 `@app.get("/health")` 必须紧跟着一个函数定义，单独一行就是语法错误。

**怎么修**

把剩下的补上：

```python
@app.get("/health")
def health():
    return {"status": "ok"}
```

**下次怎么避免** —— 记住这条判据，边敲边跑时几乎每次都用得上：

| 报错行在哪 | 说明 |
|---|---|
| **等于文件最后一行** | 还没敲完（装饰器没有函数体、括号没闭合、`:` 后面没内容） |
| 在文件中间 | 才是真写错了 |

**顺带一个沟通教训**：我当时写的是"先敲骨架（到 `/health` 结束）"，被理解成"敲到 `/health` 那一行为止"。
进度描述应该写成"**第 N 行到第 M 行，最后一行长什么样**"，不要用"到 X 结束"这种有歧义的说法。

---

### 6. 报错出现在"不该出现"的行

**现象**

改完文件、保存，重新导入还是报同样的 `SyntaxError`，但行号指向的地方看着完全正常。

**根因**

Python 的 `SyntaxError` 报的是**解析器卡住的位置**，不一定是错误真正的位置。
典型的：括号少了一个闭不上，解析器会一路读到文件末尾才报错。

**下次怎么避免**

- 报错行在最后一行 → 先怀疑"没敲完"（见上一条）。
- 报错行在中间且看着没问题 → 往上翻，检查**上一行**的括号、引号、冒号。
- 改完代码必须**重新执行**才生效，别盯着旧报错继续查。

---

### 7. `.env` 里的密码没改，值还是模板占位符

**现象**

建表做完了，`config.py` 也写对了，但打印出来的密码是：

```
'change_me_to_your_mysql_password'
```

**根因**

`.env` 是从 `.env.example` 复制来的，里面那句 `DB_PASSWORD=change_me_to_your_mysql_password`
是**占位符**，需要替换成真实密码，但当时漏做了。

**为什么前面没暴露**：v1 的 `config.py` / `db.py` / `ids.py` **都不连库**，所以直到真正连库的那一步才炸。

**怎么修**

打开 `.env`，把那一行改成自己的 MySQL root 密码，保存。

**怎么验证**（这一步很关键，别只看文件）：

```bash
python -c "from app import config; print(repr(config.DB_PASSWORD))"
```

打印出来的应该是你自己的密码，而不是 `change_me_...`。

**下次怎么避免**

复制模板 → 立刻改，别留到"以后要用的时候再说"。占位符和真值长得相似的配置项，最容易被跳过。

---

## 三、终端与命令行

### 8. ⭐ `cd D:\...` 跨盘符静默失败

**现象**

```bash
cd D:\dev\shortlink
git add .
# fatal: not a git repository (or any of the parent directories): .git
```

看提示符才发现：**人还在 `C:\Users\me>`**。`cd` 没报错，但也没生效。

**根因**

cmd 里 **`cd` 不能跨盘符切换**。它只是"记住 D 盘下次该进哪个目录"，人还在 C 盘。而且它**不报错**，
`cd` 成功时也是零输出 —— 所以这一步失败时毫无提示。

**怎么修**

```bash
cd /d D:\dev\shortlink
```

`/d` 参数就是为跨盘符准备的。等价写法：

```bash
D:
cd \dev\shortlink
```

**怎么判断成功**：**只能看提示符**。

```
C:\Users\me>                   ← 没进去
D:\dev\shortlink>     ← 进去了
```

`cd` 成功不打印任何东西，所以"敲完没输出"不等于失败。不确定就单独敲一条 `cd`（不带参数），它会打印当前目录。

**这个坑在 v1 里踩了三次**，每次都是**新开了一个 cmd 窗口**：

> **cmd 不记忆跨窗口的工作目录。** 每开一个新窗口，工作目录都回到 `C:\Users\me>`。

**更省事的入口**：文件资源管理器进到项目目录 → 点顶部地址栏 → 全选删掉、输入 `cmd` → 回车。
新窗口天生就在这个目录里，不用再 cd。

**最危险的一条**：如果不小心在 `C:\Users\me` 里敲了 `git init`，会把**整个用户主目录**变成一个 Git 仓库，
之后桌面上动任何文件都会被它跟踪。幸好三次都赶在 `git init` 之前拦住了。

---

### 9. `curl` 的 `^` 多行续行吞掉 `-d` 参数

**现象**

```bash
curl -X POST http://127.0.0.1:8000/api/links ^
  -H "Content-Type: application/json" ^
  -d "{\"url\": \"https://www.baidu.com\"}"
```

返回：

```json
{"detail":[{"type":"missing","loc":["body"],"msg":"Field required"}]}
```

`-d` 的请求体**根本没发出去**。

**根因**

cmd 用 `^` 做换行续行，但配合引号、`{}`、转义时解析经常出错，`-d` 那一整段被吞掉。
（另外注意：`curl` 在 PowerShell 里是 `Invoke-WebRequest` 的别名，语法完全不同，所以命令要在 **cmd** 里敲。）

**怎么修**

**一律写成单行**，不要用 `^` 续行：

```bash
curl -X POST http://127.0.0.1:8000/api/links -H "Content-Type: application/json" -d "{\"url\": \"https://www.baidu.com\"}"
```

**cmd 里的引号规则实测**：

| 写法 | 结果 |
|---|---|
| `-d "{\"url\": \"https://x.com\"}"` | ✅ 正确 |
| `-d '{url: ...}'` | ❌ 单引号 cmd 不识别，`json_invalid` |

**顺带一条最好用的 flag 组合**（自动化测试的雏形）：

```bash
curl -s -o NUL -w "status=%{http_code} redirect=%{redirect_url}" http://127.0.0.1:8000/000001
# status=302 redirect=https://www.baidu.com/
```

把响应的关键信息压成一行，以后写压测脚本正好用。

---

### 10. SQL 敲进了 cmd 而不是 `mysql>`

**现象**

```bash
C:\Users\me> TRUNCATE TABLE links;
'TRUNCATE' 不是内部或外部命令，也不是可运行的程序或批处理文件。
```

**根因**

`TRUNCATE` 是 SQL 语句，只能在 `mysql>` 客户端里执行。cmd 把它当成了"某个不存在的程序"。

**怎么修**

先进 mysql 客户端：

```bash
cd /d D:\ProgramFiles\MySQL\MySQL80\bin
mysql -u root -p
```

看到提示符变成 `mysql>` 之后：

```sql
USE shortlink;
TRUNCATE TABLE links;
exit
```

（`exit` 不用加分号。）

**下次怎么避免**：敲任何命令前先看一眼**当前提示符**，它决定这条命令归谁管。

| 提示符 | 归谁管 |
|---|---|
| `C:\Users\me>` | cmd，只能敲系统命令和 git |
| `mysql>` | MySQL，只能敲 SQL，语句以 `;` 结尾 |
| `->` | 上一条 SQL 还没写完（少了个引号或分号） |
| `(shortlink)` 或 `(shortlink-venv)` | 已激活 Python 虚拟环境 |

---

### 11. 浏览器直接访问 `POST` 接口 → 405

**现象**

在浏览器地址栏输入 `http://127.0.0.1:8000/api/links`，得到：

```json
{"detail":"Method Not Allowed"}
```

响应头里带 `allow: POST`。

**根因**

`/api/links` 只接受 `POST`（创建），而**浏览器地址栏发的是 `GET`**。方法不匹配 → 405。

**怎么修**

- 想用浏览器点着测 → 打开 `/docs`，找到 `POST /api/links` → Try it out → Execute
- 想用命令行测 → `curl -X POST ...`

**顺带记住几种错误码分别是谁拒的**：

| 状态码 | 谁拒绝的 | 典型原因 |
|---|---|---|
| 400 | **你的代码** | url 不以 `http://` 开头、超过 2048 字符 |
| 404 | **你的代码** | 短码在库里不存在 |
| 405 | **FastAPI 框架** | 方法不对（该 POST 用了 GET），根本没进你的函数 |
| 422 | **FastAPI 框架（pydantic）** | 请求体不符合模型，比如漏了 `Content-Type: application/json` |

**400/404 是你写的业务逻辑在起作用，405/422 是框架在之前就把请求拦住了** —— 排查时先看这个区别，能省一半时间。

---

### 12. `short_url` 里的端口和服务的实际端口不一致

**现象**

把服务起在 8126 端口，创建接口返回的却是：

```json
{"short_url": "http://127.0.0.1:8000/000001"}
```

端口不对，但这个地址点不开（服务不在 8000）。

**根因**

`short_url` 是用 `.env` 里的 `BASE_URL` 拼出来的，**跟服务实际监听的端口无关**：

```python
return CreateLinkResp(code=code, short_url=f"{config.BASE_URL}/{code}")
```

**怎么修**

改 `.env`：

```
BASE_URL=http://127.0.0.1:8126
```

改完要**重启 uvicorn** 才生效（`load_dotenv()` 只在进程启动时读一次）。

**下次怎么避免**

记住 `BASE_URL` 和 `--port` 是**两个独立的开关**，改一个必须同步改另一个。
这也是 v6 上线时的关键配置项：**部署到服务器后，`BASE_URL` 要换成真实域名**，否则返回的短链全指向 `127.0.0.1`。

---

## 四、Git 与网络

### 13. 本机根本没装 Git

**现象**

```bash
git --version
'git' 不是内部或外部命令，也不是可运行的程序或批处理文件。
```

**根因**

系统里确实没有 Git。`C:\Program Files\Git`、`D:\Git`、`%LOCALAPPDATA%\Programs\Git` 全不存在，
**VS Code 也不自带 Git**（很多人以为自带了，其实 VS Code 只是"调用"系统里的 git）。

**怎么修**

```bash
winget install --id Git.Git -e --source winget
```

装到 `C:\Program Files\Git\`，版本 2.55.0。

**装完必须重开 cmd** —— PATH 是进程启动时读的，老窗口认不出新装的程序。

**怎么验证**

```bash
cd /d D:\dev\shortlink
git --version    # git version 2.55.0.windows.3
```

---

### 14. `nothing added to commit but untracked files present`

**现象**

```bash
git commit -m "feat: v1 最小闭环"
# On branch master
# nothing added to commit but untracked files present (use "git add" to track)
```

**根因**

**少敲了 `git add .`**。Git 的提交是两阶段的：

```
工作区(你写的文件)  --git add-->  暂存区(待提交清单)  --git commit-->  仓库(历史)
```

`git commit` **只提交暂存区里的东西**。文件还没 add，暂存区是空的，自然没东西可提。

**怎么修**

```bash
git add .
git status        # 安全检查点
git commit -m "feat: v1 最小闭环，创建短链与 302 跳转"
```

**颜色法则**（`git status` 里）：

| 颜色 | 含义 |
|---|---|
| **红** | 还没 add，不会被提交 |
| **绿** | 已 add，会被提交 |

**顺带一个好习惯**：`git add .` 之后**别直接 commit**，先 `git status` 扫一眼绿色列表。
这一次的 `git status` 就是一份"安全证明"——它确认了 `.env` **不在**列表里：

```
.env.example     ← 模板，该提交
.gitignore
README.md
app/
requirements.txt
schema.sql
verify.sql
```

**没有 `.env`**，而磁盘上 `.env` 确实存在（里面有真实的 MySQL 密码）。
说明 `.gitignore` 里的 `.env` 规则正在生效。想再确认一道：

```bash
git check-ignore -v .env
# .gitignore:17:.env
```

---

### 15. `fatal: not a git repository (or any of the parent directories): .git`

**现象**

```bash
git remote add origin https://github.com/FMY-666/shortlink.git
# fatal: not a git repository (or any of the parent directories): .git
```

四条 Git 命令全部报同一个错。

**根因**

**不在项目目录里**（站在 `C:\Users\me>`）。Git 从当前目录**逐级往上**找 `.git`，
一路找到 `C:\` 也没有，就报这句。

**为什么中间两条 `git config --global` 却成功了**：`--global` 写的是全局配置文件，**跟当前目录无关**。

**怎么修**

```bash
cd /d D:\dev\shortlink
```

然后重跑那四条命令。

**这次没有任何损害** —— 四条命令的性质都是"查看/设置"，失败 = 没做事，不是做错事。
**唯一真危险的是 `git init`**：在 `C:\Users\me` 里 init 会把整个用户主目录变成 Git 仓库。
（已核实：`C:\Users\me\.git` 不存在，没误建。）

---

### 16. ⭐ `Recv failure: Connection was reset` / `Could not connect to server`

**现象**

```bash
git push -u origin main
# Recv failure: Connection was reset
```

稍后再试，换成另一种错：

```
Failed to connect to github.com port 443 after 21098 ms: Could not connect to server
```

**这两句的区别很重要**：

| 报错 | 含义 | 进度 |
|---|---|---|
| `Recv failure: Connection was reset` | 连上了，但传输中被**中途掐断** | 走了一半 |
| `Failed to connect ... after 21098 ms` | 熬了 21 秒**连接都没建立起来** | 还没开始 |

**根因**

**本机直连 GitHub 不通**（国内网络访问 GitHub 时通时断是常态）。

排查过程（都是只读检查）：

| 检查 | 结果 |
|---|---|
| 连 `www.baidu.com` | 200 OK ✓ |
| 连 `github.com` | **超时** ✗ |
| Windows 系统代理 | **关着**（`ProxyEnable=0`），但残留地址 `127.0.0.1:7890` |
| git 有没有配代理 | 没配 |
| 有代理软件在跑吗 | **没有**（7890 等端口都没在监听） |

`127.0.0.1:7890` 这个残留地址是关键线索：**7890 是 Clash 的默认端口**，说明以前装过代理工具，只是当时没打开。

**怎么修**

打开代理软件，让 git 也走它：

```bash
git config --global http.proxy http://127.0.0.1:7890
git config --global https.proxy http://127.0.0.1:7890
git push -u origin main
```

端口跟软件里显示的 **HTTP 端口**一致：

| 软件 | 常见端口 |
|---|---|
| Clash | 7890 |
| v2rayN | 10809 |
| Clash Verge | 7897 |

**配完立刻就能连上了** —— 说明代理一直在工作，只是 git 不知道它存在。
（浏览器走"系统代理"设置，git 只认自己的 `http.proxy`，**两套配置互不相通**。）

**⚠️ 一个要记住的规则**

这台机器上**代理配置必须保留**，不能推完就删：

- 代理软件**开着** → git 能推
- 代理软件**关着** → 报 `Failed to connect to 127.0.0.1:7890`，这不是坏了，把软件打开就行

只有将来换到一个**能直连 GitHub 的网络**时，才需要清掉：

```bash
git config --global --unset http.proxy
git config --global --unset https.proxy
```

**另一个顺手可试的办法**：`git config --global http.version HTTP/1.1`。
有些网络设备会干扰 HTTP/2 的连接复用，症状正好是 `Connection was reset`。

**网络不通时最省事的一招**：**手机开热点、电脑连热点**再 push。校园网对 GitHub 的限制比流量网络更狠。

**好消息**：网络不通**不会损坏任何东西**。提交和 remote 都老老实实躺在本地仓库里，
网络一通只需要再敲一条 `git push`，前面的步骤一个都不用重做。

---

### 17. `git log` 中文乱码 —— 虚惊一场

**现象**

```bash
git log --oneline
# 0efabea feat: v1 鏈€灏忛棴鐜紝鍒涘缓鐭摼涓?302 璺宠浆
```

提交信息里的中文全是乱码，一度以为提交时存坏了。

**根因**

**仓库里存的是好的，是"看的人"编码错配了。**

用 Python 取原始字节验证：

```python
subprocess.run([git, "-C", repo, "log", "--format=%s", "-1"], capture_output=True)
# raw hex => ... 76 31 20 e6 9c 80 e5 b0 8f ...
```

`e69c80` 正是「最」字的 **UTF-8** 编码。用 `utf-8` 解码完全正常，用 `gbk` 解码才是那串乱码
—— 是读取管道按错误编码解码造成的。

最终确认：GitHub 网页上渲染正常。

**下次怎么避免**

**中文乱码先怀疑"显示端"，别怀疑"存储端"。** 验证顺序：

1. 直接开 GitHub 网页看（最硬的裁判）
2. 用 Python 取原始字节自己解码
3. **不要**急着 `git commit --amend` —— 那是在改一个根本没坏的东西

---

### 18. `warning: LF will be replaced by CRLF` —— 不是错误

**现象**

```bash
git add .
# warning: in the working copy of 'README.md', LF will be replaced by CRLF the next time Git touches it
```

**根因**

`core.autocrlf=true` 的正常提示。Windows 用 `CRLF` 换行，Linux/macOS/GitHub 用 `LF`，
git 提交时自动把 CRLF 转成 LF 存进仓库、检出时再转回来。

**怎么处理**

不用处理。看到 `warning:` 前缀就知道它不是错误。真正的错误是 `error:` 或 `fatal:`。

**怎么区分这三个前缀**：

| 前缀 | 含义 |
|---|---|
| `warning:` | 提醒，操作已成功，可以忽略 |
| `error:` | 这个操作没做成，但 git 还在跑 |
| `fatal:` | 严重错误，git 直接停下了 |

---

## 五、v2 新增：Redis 与缓存（19—22）

### 19. ⭐ Windows 版 `redis-cli` 把 `*` 当本地文件名展开

**现象**

```bash
D:\dev\shortlink>D:\ProgramFiles\Redis\redis-cli.exe keys *
(error) ERR wrong number of arguments for 'keys' command
```

同一条命令，网上所有教程都这么写，偏偏这里报错。

**根因**

Windows 版的 `redis-cli` 在解析参数时，会**先把带通配符的参数当本地文件名展开一遍**。
你在项目目录里敲 `keys *`，`*` 被换成了当前目录的文件名 —— 当时 `shortlink/` 下有 18 个条目，
于是 Redis 收到的是「KEYS 命令带了 18 个参数」，它当然要抱怨参数数量不对。

**怎么证明**（隔离实验，判据很干脆）

| 在哪敲 `keys *` | 结果 |
|---|---|
| `D:\dev\shortlink`（有 18 个条目） | `ERR wrong number of arguments` ✗ |
| 一个**空目录**（无文件可展开） | `link:000001` ✓ |

同一条命令、同一个 Redis 服务，**只换当前目录，结果反转** —— 说明问题在"本地文件"，不在 Redis。

**怎么修**

```bash
D:\ProgramFiles\Redis\redis-cli.exe --scan                        # 推荐
D:\ProgramFiles\Redis\redis-cli.exe keys "link:*"                 # 也可以
```

- `--scan` **完全没有通配符**，一步到位，而且底层用的是 `SCAN`。
- `keys "link:*"` 之所以能用：带上前缀后，当前目录里没有任何以 `link:` 开头的文件，
  通配符**原样**传给了 Redis。
- ⚠️ **加引号救不了裸 `*`**：cmd 会先把引号剥掉，退化成 `*` 又被展开一次。

**下次怎么避免**

需要遍历键就默认用 `--scan`，别用 `keys`。这条命令还有第二层理由（见下）。

> **真正的收获**：`KEYS` 是 **O(N) 阻塞命令** —— Redis 是单线程的，几百万键的库上执行一次
> 能把整个服务卡住好几秒。**生产环境直接禁用**，官方文档明说该用 `SCAN`（分批游标、可中断）。
> 那个报错反而把我从一条禁用命令上推开了。

---

### 20. cmd 不支持多行粘贴

**现象**

```bash
D:\dev\shortlink>python -c "from app import db
D:\dev\shortlink>with db.get_conn() as c:
'with' 不是内部或外部命令，也不是可运行的程序或批处理文件。
```

**根因**

**cmd 按回车切命令，不像 bash 会等引号闭合。** 你一回车，它就把
`python -c "from app import db` 当成一条完整命令执行了（引号没闭合），
下一行的 `with db.get_conn() as c:` 被当成**一条新命令**，去系统里找名叫 `with` 的程序。

**识别法（很有用）**

`XXX 不是内部或外部命令` 这个错，看 XXX 是什么：

| XXX 是 | 说明 |
|---|---|
| 你本来就想敲的程序名（如 `myslq`） | 拼错了，或程序不在 PATH 上 |
| 编程语言关键字（`with` / `for` / `import`） | **把代码当命令敲了**，或命令被断成了几行 |

**怎么修**

一条命令写在一行。查数据就用 `-e`：

```bash
mysql -u root -p -e "SELECT id, code, url, clicks FROM shortlink.links;"
```

`-e` 执行完即退出，不用进 `mysql>` 交互界面。顺带：`mysql` 已经在本机 PATH 上，
**不用 `cd` 到 MySQL 的 bin 目录**。

---

### 21. Redis 窗口被关掉 = 服务停掉（不是"关掉日志界面"）

**现象**

```bash
D:\ProgramFiles\Redis>redis-cli.exe ping
Could not connect to Redis at 127.0.0.1:6379: Connection refused
```

**怎么判断是"崩溃"还是"正常退出"** —— 这一步很值：

| 检查 | 本次结果 | 含义 |
|---|---|---|
| `dump.rdb` 修改时间 | 与停止时间吻合 | 退出前**正常落盘**了 |
| `redis_6379.pid` | 不存在 | 退出时**清理过现场** |

**崩溃不会落盘、也不会清 pid 文件。** 所以那是被正常关闭的。

为什么查无对证？`redis.conf` 里写着 `logfile ""` —— **空字符串 = 日志只打在屏幕上，不写文件**，
窗口一关，它说过什么就全没了。

**怎么修**

双击目录里的 `redis-start.bat`。它内部用的是：

```bat
start "Redis 8.10.2" /min redis-server.exe redis.conf
```

`start` 的意思是**另开一个窗口去跑**，所以双击出来的那个窗口关掉**不影响** Redis。
要正经停就用 `redis-stop.bat`（等于 `redis-cli shutdown save`，会落盘）。

**下次怎么避免 —— 这是一个认知问题，不是操作问题**

**Redis / uvicorn / 数据库这类"服务"，就是"活着的进程"。关掉它的窗口 = 停掉这项服务**，
不是"关掉一个看日志的界面"。这是新手最容易误解的一点。

> 从 v2 开始你手里要**常驻两个窗口**：一个跑 Redis（最小化）、一个跑 uvicorn（前台看日志），
> 再加上敲命令的第三个。v3～v6 都是这个格局，早点习惯。

---

### 22. `TypeError: _run() takes 12 positional arguments but 13 were given`

**现象**

`bench.py` 在**预热阶段**就崩了，一个请求都没发出去。

**根因**

调用链有三层：`main() → _run() → _worker()`。
给最内层的 `_worker()` 加一个 `--json-url` 参数时，**两头都改了，漏了中间那层 `_run()`**。
于是 `main()` 递过去 13 个参数，`_run()` 只有 12 个位置接。

**为什么 `py_compile` 没抓到**

因为它**只查语法，不查"参数个数对不对"**。参数个数是**运行时**才检查的。
这三类错误报的时机完全不同，值得背下来：

| 错误 | 什么时候报 | 典型场景 |
|---|---|---|
| `SyntaxError` | 文件**还没跑起来** | 漏括号、缩进错、文件没敲完 |
| `TypeError` | 跑起来、**执行到那一行** | 参数个数不对、`None` 当函数调 |
| `IntegrityError` | 数据库**拒绝**时 | collation 把短码判重复（第 1 条） |

**能编译 ≠ 能跑**，这是三层里最浅的一层。

**怎么修**

给 `_run()` 补上 `json_url`，并继续透传给 `_worker()`。

**下次怎么避免**

**改了函数签名，必须检查全部调用点 —— 尤其是链条中间那层。**
两头最容易想起来，中间那层最容易漏。

---

## 六、v3 新增：布隆过滤器（23—24）

### 23. ⭐ 服务跑着的时候 `flushdb`，所有短链全部 404

**现象**

v3 之后，短链页面**突然全部 404** —— 连你自己刚创建、一分钟前还能正常跳转的那条也一样：

```json
{"detail": "短码不存在"}
```

`redis-cli dbsize` 掉到接近 0。反复刷新无效，**不重启服务就永远不恢复**。

**根因**

v3 的布隆过滤器是**服务启动时一次性预热**的 —— `lifespan` 里调 `bloom.load_from_db()`，
把库里所有短码灌进 `bloom:links` 这个 Redis bitmap。

而 `flushdb` 清的是**整个 Redis 库**，不只是你的缓存键 —— `bloom:links` 一起被清空了。
空 bitmap 对任何输入都返回"不存在"，于是第一道关口把**所有**请求全部 404 掉。

**为什么不会自愈**：预热只发生在**启动那一刻**。服务还在跑，它不知道自己脚下的位图被抽走了。
所以这不是 bug，是"启动时状态 + 运行中外部删除"的必然结果。

**怎么修**

重启 uvicorn。看到日志这行就恢复了：

```
[startup] 布隆过滤器预热完成，载入 N 个短码
```

**下次怎么避免**

v3 之后 **`flushdb` 是危险动作**，别再顺手敲。要清缓存就精确删，别用清库：

```bash
# 在项目根目录、venv 激活状态下（用项目自己的连接配置，不会误伤 bloom:links）
python -c "from app import cache; r = cache.get_client(); ks = list(r.scan_iter('link:*')); print('将删除', len(ks), '个缓存键'); r.delete(*ks)"
```

> 用 `scan_iter('link:*')` 而不是 `keys`：`SCAN` 是增量遍历、不阻塞 Redis，
> `KEYS` 是 O(N) 阻塞命令，生产环境本来就被禁用（第 19 条顺带聊过）。

**分清两条长得一样的 `flushdb`**：开发过程中做过一条**故意的破坏性实验**
（就是为了亲眼看"过滤器没预热 = 全部 404"这个现象），日常操作里没有它的位置。

---

### 24. ⭐ 粘贴残留：`py_compile` 通过、服务照跑，`return` 后面躺着一堆死代码

**现象**

改 `main.py` 时，**用粘贴代替了替换** —— 新代码写好了，旧代码没删。表象全是"正常"：

| 检查 | 结果 |
|---|---|
| `python -m py_compile app/main.py` | ✅ 通过 |
| `uvicorn` 启动 | ✅ 正常 |
| 页面功能 | ✅ 看起来是对的 |

**踩到的三处**（v3 改动实测）：

1. `create_link`：新实现写好了，**旧的 9 行没删**，落在 `return` 后面 → 永远执行不到的死代码
2. `redirect_to_original`：过滤器块被粘在 `def` 行**之后、docstring 之前**
3. 同函数里 `r = cache.get_client()` / `key = cache.cache_key(code)` **出现两遍**

**根因**

光标停在旧代码**前面**就直接 `Ctrl+V` —— 新代码**叠在**旧代码上，而不是替换它。
`Ctrl+V` 永远不会帮你删掉旧的，这件事必须由你选中来做。

**为什么 `py_compile` 抓不到**

因为它**只查语法**。下面三类全是**语法合法**的，编译阶段永远不报错：

| 现象 | 为什么语法合法 |
|---|---|
| `return` 之后还有语句 | Python 语法允许不可达代码，连个警告都不给 |
| docstring 不在函数第一位 | 它退化成一条普通的字符串表达式语句，合法；只是 `__doc__` 变成 `None` |
| 变量连续赋值两遍 | 合法，第二遍覆盖第一遍 |

**"能编译"与"改对了"是两件事。** 这和 22 条那个 `TypeError` 是同一个道理的延伸：
`SyntaxError` / `TypeError` / 结构性残留，是三个不同层面的检查，谁也替不了谁。

**怎么查**（肉眼会漏，用 `ast` 读结构）

```python
import ast, io
src = io.open('app/main.py', encoding='utf-8').read()
for f in ast.walk(ast.parse(src)):
    if isinstance(f, ast.FunctionDef):
        b = f.body
        first = b[0] if b else None
        is_doc = isinstance(first, ast.Expr) and isinstance(getattr(first, 'value', None), ast.Constant)
        print('%-22s docstring=%s' % (f.name, is_doc))
        for s in b[:-1]:
            if isinstance(s, ast.Return):
                print('   !! 第 %d 行 return 之后还有不可达代码' % s.lineno)
```

把上面这段存成 `check_structure.py`，一条命令查全部：

```bash
python check_structure.py app/main.py app/bloom.py app/cache.py
```

**怎么修**

**从下往上删** —— 先删下面的函数，上面函数的行号就不会漂。删完再跑一遍上面的结构检查。

**下次怎么避免**

1. **先选中旧代码，再粘贴。** 改函数的正确姿势是"选中整个旧实现 → 粘贴新实现"，
   而不是"把光标放上去敲 `Ctrl+V`"。
2. **改完立刻看 `git diff`** —— 这是最省事的验收方式：
   **diff 里只该有新增行（`+`）和必须改的那几行（`-`）。出现成片的 `-` 删除行，
   就说明要么你多删了东西，要么有残留没清干净。**
3. 注意：**"改了"和"没改坏"是两件事** —— 前面第 4 处残余（`create_link` 里丢了一个空行）
   就是这么翻出来的：功能没影响，但它是"顺手改坏"的唯一痕迹，留着会让 `git diff` 永远多一行噪音。

---

## 七、这些坑怎么用在面试里

面试官问"遇到最难的问题是什么"时，**不要讲"环境装不上"这类** —— 那体现不出工程能力。
挑下面这几个：

### ① collation 那个（首选）

> "我实现了一个 62 进制的短码生成器，字母表是数字加大小写字母。前 35 条创建全正常，
> 第 36 条开始全部 500 报唯一键冲突。
>
> 排查后发现，我在建表时 `code` 列只写了 `VARCHAR(16)`，没指定 collation。
> MySQL 8 给 utf8mb4 的默认排序规则是 `utf8mb4_0900_ai_ci`，`ci` 是大小写不敏感 ——
> 于是索引 10 号生成的小写 `00000a` 和索引 36 号生成的大写 `00000A` 被判为同一个值。
> **我的字母表有 62 个字符，但数据库只认 36 个。**
>
> 修复是给这一列显式加 `COLLATE utf8mb4_bin`。改完在 60 并发下从 35 成功 / 25 失败变成 60 全成功。
>
> 这件事让我记住两点：一是**凡是参与唯一性判断的字符串列都要显式指定 collation**，
> 默认值是给人类搜索用的，不是给机器比对用的；二是这个 bug 只在第 36 条之后才暴露，
> **单元测试永远抓不到**，必须跨边界测或者用并发压测扫。"

**为什么这条值钱**：它同时展示了 ① 能定位到根因（不是靠猜）② 知道数据库默认值背后的坑 ③ 有量化对比 ④ 提炼出了可复用的原则。

### ② 跨盘符 `cd` 静默失败

> "Git 命令连续报了三次 `not a git repository`。我一开始以为是仓库坏了，
> 后来发现是自己站在用户主目录里操作 —— **cmd 的 `cd` 不能跨盘符，而且失败时既不报错也没有输出**。
> 从那以后我养成了习惯：每个新开的终端窗口，第一件事就是进目录并确认提示符。"

**为什么值钱**：展示的是**排查纪律**，以及"失败要能看得见"这个工程直觉。而且能顺势聊到
"如果当时误在主目录执行了 `git init` 会有什么后果"。

### ③ HTTP/2 连接复用被中间设备干扰

> "push 一直失败，报 `Connection was reset`。逐层排查：百度通、GitHub 超时、
> 系统代理关着但有残留端口、git 没配代理。最后定位到本机直连 GitHub 不通，
> 让 git 走本地代理端口后立刻成功。中间还试过把 HTTP 版本降回 1.1，
> 因为有些网络设备会干扰 HTTP/2 的连接复用，症状正好是 `reset`。"

**为什么值钱**：这是**分层排查**的范例 —— 先分清"网络层"还是"应用层"，再逐层收窄，
而不是乱试命令。

---

### ④ 一次"平台差异"的排查（Windows 下 `keys *` 报参数错）

比 collation 更轻快，两分钟就能讲完，适合面试开场暖场：

> 我用 Redis 的时候，敲 `keys *` 一直报"参数数量不对"，但所有教程都这么写。
> 我先怀疑是自己敲错了，换个写法还是不行。后来做了个对照实验：
> **同一条命令在一个空目录里执行就正常，在项目目录里就报错** —— 这才定位到
> 是 Windows 版的 redis-cli 会把 `*` 当本地文件名展开，项目目录里文件多，于是被展开成一长串参数。
> 这件事给我两个收获：一是排查诡异问题时要**控制变量做对照**；
> 二是顺着它发现 **`KEYS` 这个命令在生产环境本来就是禁用的** ——
> 它是 O(N) 阻塞命令，会把单线程的 Redis 卡住，生产要改用 `SCAN`。
> 所以那个报错反而帮了我。

**为什么这条值得讲**：它展示的不是"我会用 Redis"，而是
**"遇到反直觉的现象时，我会设计一个实验把它钉死，而不是乱试命令"**。

---

## 附：当前状态（v1 → v3）

**接口**

| 方法 | 路径 | 作用 | 成功 | 失败 |
|---|---|---|---|---|
| `GET` | `/health` | 部署探活 | 200 | — |
| `POST` | `/api/links` | 创建短链 | 200 | 400（url 非法）/ 422（格式错） |
| `GET` | `/{code}` | 302 跳转 + 点击数 +1 | 302 | 404（短码不存在） |

**表结构**

```sql
CREATE TABLE links (
  id     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  code   VARCHAR(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  url    VARCHAR(2048) NOT NULL,
  clicks BIGINT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY uk_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**为什么 `code` 允许为 NULL**：短码是由自增 id 算出来的，而 id 只有插入之后才知道。
所以流程是"先插入一行 code 为 NULL 的记录 → 拿到 `lastrowid` → 算出短码 → `UPDATE` 回填"。
MySQL 的唯一索引允许多个 NULL 值，所以这一步不会冲突。

**v2 改变的东西**

| 文件 | 变化 |
|---|---|
| `app/cache.py` | 新增。模块级 Redis 连接池 + 缓存键 `link:{code}` |
| `app/main.py` | `GET /{code}` 从"直接查库"改为 **Cache-Aside**：先查缓存 → 未命中回源 → 写回缓存 |
| 空值缓存 | 查不到的短码写 `""` 进缓存，TTL 只给 60 秒，挡住"反复请求同一个不存在的短码" |
| 点击计数 | 只在**回源**时 +1。命中缓存的访问不再计数（v2 的主动取舍） |

**v2 实测（同一台机器，`-c 50 -d 15`）**

| 指标 | v1 无缓存 | v2 有缓存 | 变化 |
|---|---|---|---|
| QPS | 44.2 | **1340.5** | **↑ 30.3 倍** |
| 平均延迟 | 1124 ms | 37.3 ms | ↓ 到 3.3% |
| P99 | 1701 ms | 62.4 ms | ↓ 到 3.7% |
| Redis 命中率 | — | 99.99% | 22716 命中 / 3 未命中 |
| `clicks` 增长 | +797（685 请求） | **0**（20142 请求） | v2 的取舍 |

**这组数字的可信度**：用利特尔法则校验 `并发数 = QPS × 平均延迟` ——
v1 是 `44.2 × 1.124 = 49.7`，v2 是 `1340.5 × 0.0373 = 50.0`，都等于并发数 50，
说明两次都是 50 条连接全部跑满的饱和状态，不是在量空转或预热。

**v3 改变的东西**

| 文件 | 变化 |
|---|---|
| `app/bloom.py` | 新增。**用 Redis bitmap 实现**的布隆过滤器：`BIT_SIZE = 1 << 24`（2 MB）、`HASH_COUNT = 7`、键名 `bloom:links` |
| `app/main.py` | 加 `lifespan`：启动时 `bloom.load_from_db()` 预热；`GET /{code}` 在**问缓存之前**多一道过滤器；`create_link` 成功后 `bloom.add(code)` |
| 为什么用 Redis bitmap 而不是本地 `bytearray` | 多 worker 进程必须共享**同一份**位图。放在本地内存里，每个进程各存一份，一个进程写入的新短码另一个看不见 —— 自己创建的短链会被别的进程 404 |
| 三道关口 | 布隆过滤器 → Redis 缓存 → MySQL，**越便宜的检查放越前面** |

**v3 实测（同一台机器，`--random -c 50 -d 10`，全程刷不存在的随机短码）**

| 指标 | v2 空值缓存 | v3 布隆过滤器 | 变化 |
|---|---|---|---|
| QPS | 64.2 | **1147.9** | **↑ 17.9 倍** |
| 平均延迟 | 774.8 ms | 43.5 ms | ↓ 到 5.6% |
| P99 | 966.0 ms | **91.6 ms** | ↓ 到 9.5% |
| 10 秒内完成请求 | 681 | 11508 | ↑ 16.9 倍 |
| **Redis 键数（压测前 → 后）** | 1 → **833** | 1 → **2** | **垃圾键归零** |

**最后一行才是 v3 最硬的证据**：`dbsize` 停在 2（`bloom:links` + 一条真实缓存），
而 v2 时代同一轮压测是 `1 → 833` —— v3 连"查库之后才可能发生"的写缓存都没发生，
说明请求**在过滤器那道门就被拦下，MySQL 压根没被碰过**。
QPS 快只说明"处理得快"，键数不动直接说明"根本没走到那一步"。

**顺带一个结论**：v2 刷**存在**的短码是 1340.5 QPS，刷**不存在**的随机码是 64.2 —— 差 20 倍。
v3 之后随机码跑到 1147.9，和前者**只差 14%**。
"不存在的短码"从最贵的请求变成了最便宜的，这才是布隆过滤器真正买到的东西。

**利特尔法则校验**：`1147.9 × 0.0435 = 49.9 ≈ 50`，同样等于并发数，饱和成立。

---

*本文档随项目演进持续更新。v4（号段模式发号器）之后会新增"双 buffer 切换 / 号段耗尽竞态"相关条目。*
