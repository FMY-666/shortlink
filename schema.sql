-- 短链服务 · 建库建表脚本
-- 用法：mysql -u root -p < schema.sql

CREATE DATABASE IF NOT EXISTS shortlink
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_general_ci;

USE shortlink;

DROP TABLE IF EXISTS links;

CREATE TABLE links (
  id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  -- code 必须显式写 COLLATE utf8mb4_bin（二进制比较 = 大小写敏感）。
  -- 为什么：MySQL 8 给 utf8mb4 的默认排序规则是 utf8mb4_0900_ai_ci，其中 ci = case-insensitive，
  -- 它认为 '00000a' 和 '00000A' 是同一个值。而 62 进制字母表里 a 和 A 是两个不同字符，
  -- 于是 id=10 的短码 '00000a' 会把 id=36 的短码 '00000A' 判成「重复」，创建接口直接 500。
  -- 这个坑单条测试看不出来，要连续创建 36 次以上才会炸。
  code       VARCHAR(16)     CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL,
  url        VARCHAR(2048)   NOT NULL,
  clicks     BIGINT UNSIGNED NOT NULL DEFAULT 0,
  created_at DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

  PRIMARY KEY (id),
  -- code 必须唯一，否则两个短码可能指向同一条记录、或一条记录被重复插入
  -- 允许 NULL：创建时先插空值拿到自增 id，算出 code 后再 UPDATE 回来
  -- MySQL 的唯一索引允许多个 NULL，所以这个技巧才成立
  UNIQUE KEY uk_code (code)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4;

-- 验证建好了
SHOW CREATE TABLE links;

-- 验证 code 列是大小写敏感的（这里应该显示 utf8mb4_bin，不能是 utf8mb4_0900_ai_ci）
SELECT COLUMN_NAME, COLLATION_NAME
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'shortlink'
  AND TABLE_NAME   = 'links'
  AND COLUMN_NAME  = 'code';
