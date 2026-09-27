-- 建库后的动手练习：跑一遍，亲手撞两次报错，比读十篇文章管用
--
-- 用法（注意 --force，必须加）：
--   mysql -u root -p --force --default-character-set=utf8mb4 -t < practice.sql
--
-- 为什么要 --force：第 5 条和第 7 条语句是「故意让它报错」的。
-- 不加 --force，mysql 一遇到错误就停下，后面的步骤根本不会执行。
--
-- 标题一律用英文：Windows 控制台是 GBK 码页，而 mysql 按 utf8mb4 输出，
-- 中文标题会在控制台里显示成乱码。这是个很典型的编码坑，记住它。

USE shortlink;

SELECT '=== 1. table structure (DESC) ===' AS info;
DESC links;

SELECT '=== 2. insert one row, leave code empty on purpose ===' AS info;
INSERT INTO links (code, url) VALUES (NULL, 'https://example.com/a');
SELECT id, code, url, clicks, created_at FROM links;

SELECT '=== 3. insert another NULL code -- no error, unique index allows many NULLs ===' AS info;
INSERT INTO links (code, url) VALUES (NULL, 'https://example.com/b');
SELECT id, code FROM links;

SELECT '=== 4. fill in the code of row 1 ===' AS info;
UPDATE links SET code = 'aB3k9F' WHERE id = 1;
SELECT id, code FROM links;

SELECT '=== 5. reuse the same code -- EXPECT ERROR: Duplicate entry ===' AS info;
INSERT INTO links (code, url) VALUES ('aB3k9F', 'https://example.com/c');

SELECT '=== 6. check that clicks defaulted to 0 ===' AS info;
SELECT * FROM links;

SELECT '=== 7. omit url -- EXPECT ERROR: url has no default / cannot be null ===' AS info;
INSERT INTO links (code) VALUES ('xxxxxx');

SELECT '=== 8. clean up the practice rows ===' AS info;
DELETE FROM links;
SELECT COUNT(*) AS rows_left FROM links;
