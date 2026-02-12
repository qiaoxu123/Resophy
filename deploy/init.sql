-- ============================================================
-- Resophy Multi-User Database Schema
-- Target: MySQL 8.4+
-- Charset: utf8mb4 (full Unicode support)
-- ============================================================

CREATE DATABASE IF NOT EXISTS resophy
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE resophy;

-- ============================================================
-- 1. papers - 共享论文表（全局唯一，跨用户去重）
-- ============================================================
CREATE TABLE IF NOT EXISTS papers (
    id          VARCHAR(36)   NOT NULL PRIMARY KEY,
    content_hash VARCHAR(64)  DEFAULT NULL COMMENT 'SHA-256 of PDF content for dedup',
    arxiv_id    VARCHAR(50)   DEFAULT NULL,
    title       TEXT,
    authors     TEXT,
    abstract    TEXT,
    year        VARCHAR(10)   DEFAULT NULL,
    journal     VARCHAR(255)  DEFAULT NULL,
    affiliation TEXT,
    keywords    TEXT,
    subject     TEXT,
    summary     TEXT          COMMENT 'arXiv summary (original format)',
    bibtex      TEXT,

    -- File storage (shared)
    pdf_storage_path      VARCHAR(500)  DEFAULT NULL COMMENT 'Shared PDF physical path',
    original_filename     VARCHAR(500)  DEFAULT NULL,
    chinese_pdf_path      VARCHAR(500)  DEFAULT NULL COMMENT 'Translated .zh.dual.pdf',
    analysis_result_path  VARCHAR(500)  DEFAULT NULL COMMENT 'AI analysis result.md path',

    -- External links
    arxiv_url             VARCHAR(500)  DEFAULT NULL,
    arxiv_published_date  VARCHAR(50)   DEFAULT NULL,
    github                VARCHAR(500)  DEFAULT NULL,
    homepage              VARCHAR(500)  DEFAULT NULL,

    -- AI task status (shared since result is shared)
    translation_status    VARCHAR(20)   DEFAULT 'idle',
    translation_task_id   VARCHAR(36)   DEFAULT NULL,
    analysis_status       VARCHAR(20)   DEFAULT 'idle',
    analysis_task_id      VARCHAR(36)   DEFAULT NULL,
    status_updated_at     DATETIME      DEFAULT NULL,

    -- Audit
    uploaded_by           INT UNSIGNED  DEFAULT NULL COMMENT 'flarum_users.id of first uploader',
    created_at            DATETIME      DEFAULT CURRENT_TIMESTAMP,
    updated_at            DATETIME      DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Indexes
    UNIQUE KEY uk_content_hash (content_hash),
    INDEX idx_arxiv_id (arxiv_id),
    INDEX idx_uploaded_by (uploaded_by),
    INDEX idx_created_at (created_at),
    FULLTEXT INDEX ft_papers (title, authors, abstract) WITH PARSER ngram
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Shared paper repository (one row per unique paper)';


-- ============================================================
-- 2. user_papers - 用户-论文关联表（每用户独立的论文视图）
-- ============================================================
CREATE TABLE IF NOT EXISTS user_papers (
    id          BIGINT        AUTO_INCREMENT PRIMARY KEY,
    user_id     INT UNSIGNED  NOT NULL COMMENT 'flarum_users.id',
    paper_id    VARCHAR(36)   NOT NULL,

    -- Per-user metadata
    category_id VARCHAR(36)   DEFAULT NULL COMMENT 'user_categories.id',
    notes       TEXT          COMMENT 'Personal notes',
    starred     TINYINT(1)    DEFAULT 0,
    read_time   INT           DEFAULT 0 COMMENT 'Cumulative reading seconds',
    analysis_view_time INT    DEFAULT 0 COMMENT 'AI analysis viewing seconds',
    upload_source VARCHAR(50) DEFAULT NULL COMMENT 'pdf/arxiv/zotero/daily_arxiv',
    use_chinese_version TINYINT(1) DEFAULT 0,

    added_at    DATETIME      DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME      DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_user_paper (user_id, paper_id),
    INDEX idx_user_category (user_id, category_id),
    INDEX idx_user_starred (user_id, starred),
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Per-user paper associations with personal metadata';


-- ============================================================
-- 3. user_categories - 用户分类树
-- ============================================================
CREATE TABLE IF NOT EXISTS user_categories (
    id          VARCHAR(36)   NOT NULL PRIMARY KEY,
    user_id     INT UNSIGNED  NOT NULL COMMENT 'flarum_users.id',
    parent_id   VARCHAR(36)   DEFAULT NULL,
    name        VARCHAR(255)  NOT NULL,
    sort_order  INT           DEFAULT 0,
    pinned      TINYINT(1)    DEFAULT 0,
    icon_color  VARCHAR(20)   DEFAULT NULL,
    created_at  DATETIME      DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_user_parent (user_id, parent_id),
    FOREIGN KEY (parent_id) REFERENCES user_categories(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Per-user category tree (adjacency list model)';


-- ============================================================
-- 4. user_reading_history - 用户阅读历史
-- ============================================================
CREATE TABLE IF NOT EXISTS user_reading_history (
    id              BIGINT        AUTO_INCREMENT PRIMARY KEY,
    user_id         INT UNSIGNED  NOT NULL COMMENT 'flarum_users.id',
    date            DATE          NOT NULL,
    total_minutes   INT           DEFAULT 0,
    paper_ids       JSON          DEFAULT NULL COMMENT 'Array of paper IDs read that day',

    UNIQUE KEY uk_user_date (user_id, date),
    INDEX idx_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Per-user daily reading history';


-- ============================================================
-- 5. user_settings - 用户设置
-- ============================================================
CREATE TABLE IF NOT EXISTS user_settings (
    user_id             INT UNSIGNED  NOT NULL PRIMARY KEY COMMENT 'flarum_users.id',

    -- Display preferences
    heatmap_color_scheme VARCHAR(20)  DEFAULT 'green',
    ai_language         VARCHAR(10)   DEFAULT 'zh' COMMENT 'en or zh',
    onboarding_done     TINYINT(1)    DEFAULT 0,

    -- LLM API config (per-user allows different API keys)
    llm_model           VARCHAR(100)  DEFAULT 'gemini-2.5-flash',
    llm_base_url        VARCHAR(500)  DEFAULT 'https://hiapi.online/v1',
    llm_api_key         VARCHAR(500)  DEFAULT NULL,

    -- MinerU config
    mineru_server_url   VARCHAR(500)  DEFAULT NULL,
    mineru_use_api      TINYINT(1)    DEFAULT 1,
    mineru_api_token    VARCHAR(500)  DEFAULT NULL,

    -- Daily arXiv preferences (stored as JSON for flexibility)
    daily_arxiv_settings JSON        DEFAULT NULL,

    created_at          DATETIME      DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME      DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Per-user application settings';


-- ============================================================
-- 6. user_reading_list - 用户阅读清单
-- ============================================================
CREATE TABLE IF NOT EXISTS user_reading_list (
    id          BIGINT        AUTO_INCREMENT PRIMARY KEY,
    user_id     INT UNSIGNED  NOT NULL COMMENT 'flarum_users.id',
    paper_id    VARCHAR(36)   NOT NULL,
    added_at    DATETIME      DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uk_user_paper (user_id, paper_id),
    INDEX idx_user_id (user_id),
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Per-user reading list (to-read queue)';


-- ============================================================
-- Schema migrations: add columns that may be missing on
-- tables created before these columns were introduced.
-- Errors (e.g. "Duplicate column name") are caught by
-- ensure_schema()'s per-statement try/except.
-- ============================================================
-- ============================================================
-- 7. shared_categories - 分类共享关系
-- ============================================================
CREATE TABLE IF NOT EXISTS shared_categories (
    id          BIGINT        AUTO_INCREMENT PRIMARY KEY,
    category_id VARCHAR(36)   NOT NULL,
    owner_id    INT UNSIGNED  NOT NULL COMMENT 'flarum_users.id of category owner',
    shared_with INT UNSIGNED  NOT NULL COMMENT 'flarum_users.id of recipient',
    permission  ENUM('view', 'edit') NOT NULL DEFAULT 'view',
    created_at  DATETIME      DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_category_shared (category_id, shared_with),
    INDEX idx_shared_with (shared_with),
    INDEX idx_owner_id (owner_id),
    FOREIGN KEY (category_id) REFERENCES user_categories(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Category sharing relationships between users';


-- ============================================================
-- Schema migrations
-- ============================================================
ALTER TABLE user_categories ADD COLUMN pinned TINYINT(1) DEFAULT 0 AFTER sort_order;
ALTER TABLE user_categories ADD COLUMN icon_color VARCHAR(20) DEFAULT NULL AFTER pinned;


-- ============================================================
-- Global Team Library seed data (user_id=0 as virtual owner)
-- ============================================================
INSERT IGNORE INTO user_categories (id, user_id, parent_id, name, sort_order)
VALUES ('global-jlu-mcns-mec', 0, NULL, 'JLU-MCNS-MEC', 0);
