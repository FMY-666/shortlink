-- ============================================================
-- v4 号段模式发号器：建表 + 对齐起点
-- 用法（在 cmd 里，不是 mysql> 里）：
--     cd /d D:\dev\shortlink
--     mysql -u root -p < schema_v4.sql
-- 或者在 mysql> 里：
--     source D:/dev/shortlink/schema_v4.sql
-- ============================================================

USE shortlink;

-- ------------------------------------------------------------
-- 号段表：记录每个业务「已经分配到哪个 id 了」
-- 一张表可以服务多个业务，靠 biz_tag 区分（我们只用一个：link_id）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS biz_segment (
  biz_tag     VARCHAR(32) NOT NULL COMMENT '业务标识',
  max_id      BIGINT      NOT NULL DEFAULT 0 COMMENT '已经分配出去的最大 id',
  step        INT         NOT NULL DEFAULT 1000 COMMENT '每次申请多少个',
  update_time TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (biz_tag)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='号段表';

-- ------------------------------------------------------------
-- 关键一步：把起点对齐到「库里已经用掉的最大 id」
--
-- 不对齐会怎样？号段从 1 开始发号，而 links 表里已经有 id=1、2、3……
-- 于是 INSERT 立刻撞主键，报 Duplicate entry '1' for key 'PRIMARY'。
-- 这是切到号段模式时最容易踩的坑。
--
-- @cur_max 是用户变量，只在当前这个 mysql 会话里有效。
-- 所以这两句必须「一起跑」，中间别退出 mysql。
-- ------------------------------------------------------------
SET @cur_max = (SELECT COALESCE(MAX(id), 0) FROM links);

INSERT INTO biz_segment (biz_tag, max_id, step)
VALUES ('link_id', @cur_max, 1000)
ON DUPLICATE KEY UPDATE max_id = GREATEST(max_id, @cur_max);

-- 看一眼结果：max_id 应该 >= 你刚才查出来的最大 id
SELECT * FROM biz_segment;
SELECT COALESCE(MAX(id), 0) AS links_max_id FROM links;
