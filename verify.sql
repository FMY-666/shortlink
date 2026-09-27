-- 自检脚本：跑完 schema.sql 之后执行，确认表真的建对了
-- 用法：mysql -u root -p --default-character-set=utf8mb4 -t < verify.sql
--
-- 注意：下面 SELECT 里的标题一律用英文 —— 因为 Windows 控制台是 GBK 码页，
-- 而 mysql 客户端按 utf8mb4 输出，中文标题在控制台里会显示成乱码。
-- 这是个很典型的编码坑，记住它。

SELECT '=== 1. columns of links ===' AS info;

SELECT ORDINAL_POSITION                  AS pos,
       COLUMN_NAME                       AS name,
       COLUMN_TYPE                       AS type,
       IS_NULLABLE                       AS nullable,
       IFNULL(COLUMN_DEFAULT, '(none)')  AS def,
       COLUMN_KEY                        AS `key`
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'shortlink'
  AND TABLE_NAME   = 'links'
ORDER BY ORDINAL_POSITION;

SELECT '=== 2. indexes of links ===' AS info;

SELECT INDEX_NAME AS name,
       COLUMN_NAME AS col,
       NON_UNIQUE AS non_unique
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = 'shortlink'
  AND TABLE_NAME   = 'links';

SELECT '=== 3. uk_code exists? (expect 1) ===' AS info;

SELECT COUNT(*) AS uk_code_exists
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = 'shortlink'
  AND TABLE_NAME   = 'links'
  AND INDEX_NAME   = 'uk_code';

SELECT '=== 4. code column nullable? (expect YES) ===' AS info;

SELECT IS_NULLABLE AS code_nullable
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'shortlink'
  AND TABLE_NAME   = 'links'
  AND COLUMN_NAME  = 'code';

SELECT '=== 5. code collation is case-sensitive? (expect utf8mb4_bin) ===' AS info;
-- 如果这里显示 utf8mb4_0900_ai_ci，说明 code 列大小写不敏感：
-- id=10 的码 '00000a' 会把 id=36 的码 '00000A' 判成重复，创建接口会在第 36 次开始报 500。
-- 修法见 schema.sql 里的注释。

SELECT COLLATION_NAME AS code_collation
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'shortlink'
  AND TABLE_NAME   = 'links'
  AND COLUMN_NAME  = 'code';

SELECT '=== 6. rows and auto_increment (gaps are normal) ===' AS info;
-- 自增值一旦分配就不会退还：插入失败、事务回滚都会「吃掉」一个 id。
-- 所以 id 有空洞、短码会跳号，都是正常的。

SELECT COUNT(*) AS rows_now FROM shortlink.links;

SELECT AUTO_INCREMENT AS next_id
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'shortlink'
  AND TABLE_NAME   = 'links';
