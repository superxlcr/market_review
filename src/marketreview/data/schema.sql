CREATE TABLE IF NOT EXISTS tushare_cache (
    code       TEXT NOT NULL,
    date       TEXT NOT NULL,
    open       REAL,
    high       REAL,
    low        REAL,
    close      REAL,
    vol        REAL,
    amount     REAL,
    adj_factor  REAL,
    asset_type  TEXT NOT NULL DEFAULT 'stock',  -- 'stock' or 'index'
    PRIMARY KEY (code, date)
);

CREATE INDEX IF NOT EXISTS idx_cache_code_date ON tushare_cache(code, date DESC);
CREATE INDEX IF NOT EXISTS idx_cache_date ON tushare_cache(date, asset_type);

CREATE TABLE IF NOT EXISTS index_weight_cache (
    index_code   TEXT    NOT NULL,
    con_code     TEXT    NOT NULL,
    weight_date  TEXT    NOT NULL,
    weight       REAL    NOT NULL,
    PRIMARY KEY (index_code, con_code, weight_date)
);

CREATE INDEX IF NOT EXISTS idx_iwc_code_date
    ON index_weight_cache(index_code, weight_date DESC);

CREATE TABLE IF NOT EXISTS stock_industry_cache (
    ts_code   TEXT PRIMARY KEY,
    name      TEXT,
    l1_code   TEXT,
    l1_name   TEXT,
    l2_code   TEXT,
    l2_name   TEXT,
    l3_code   TEXT,
    l3_name   TEXT
);

CREATE TABLE IF NOT EXISTS stock_basic_cache (
    ts_code   TEXT PRIMARY KEY,
    name      TEXT,
    list_date TEXT,
    is_st     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS daily_basic_cache (
    ts_code    TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    total_mv   REAL,
    circ_mv    REAL,
    PRIMARY KEY (ts_code, trade_date)
);

CREATE TABLE IF NOT EXISTS wave33_cache (
    trade_date   TEXT PRIMARY KEY,
    count        INTEGER NOT NULL,
    profit_count INTEGER NOT NULL,
    profit_pct   REAL NOT NULL,
    stock_codes  TEXT,
    updated_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS kd80_cache (
    trade_date   TEXT PRIMARY KEY,
    count        INTEGER NOT NULL,
    updated_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ind_kd80_cache (
    trade_date    TEXT NOT NULL,
    industry_type TEXT NOT NULL,   -- 'L1' | 'L2'
    industry_name TEXT NOT NULL,
    count         INTEGER NOT NULL,
    updated_at    TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (trade_date, industry_type, industry_name)
);

CREATE TABLE IF NOT EXISTS index_contribution_cache (
    index_code   TEXT NOT NULL,
    trade_date   TEXT NOT NULL,
    top_n        INTEGER NOT NULL DEFAULT 10,
    weight_type  TEXT NOT NULL,   -- 'dynamic' (total_mv) or 'cached' (index_weight API)
    data         TEXT NOT NULL,   -- JSON blob: {index, gainers, losers}
    created_at   TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (index_code, trade_date, top_n)
);

CREATE TABLE IF NOT EXISTS stk_limit_cache (
    ts_code    TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    up_limit   REAL NOT NULL,
    down_limit REAL NOT NULL,
    PRIMARY KEY (ts_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_slc_date ON stk_limit_cache(trade_date);

CREATE TABLE IF NOT EXISTS ai_summary (
    trade_date   TEXT NOT NULL,
    summary_type TEXT NOT NULL,
    guide_key    TEXT NOT NULL,
    content      TEXT NOT NULL,
    model        TEXT,
    created_at   TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (trade_date, summary_type, guide_key)
);

-- ── Industry (sector) data ──

CREATE TABLE IF NOT EXISTS industry_classify (
    index_code    TEXT PRIMARY KEY,   -- 行业指数代码 (801081.SI / 850818.SI ...)
    industry_name TEXT NOT NULL,      -- 行业名称
    level         TEXT NOT NULL,      -- L1 / L2 / L3
    industry_code TEXT NOT NULL,      -- 行业分类代码 (270000 ...)
    parent_code   TEXT NOT NULL,      -- 父级分类代码 (L1 parent=0)
    src           TEXT NOT NULL       -- 分类标准 (SW2021)
);

CREATE TABLE IF NOT EXISTS industry_daily (
    industry_code TEXT NOT NULL,      -- 行业指数代码
    trade_date    TEXT NOT NULL,      -- 交易日 YYYYMMDD
    open          REAL,               -- 开盘价
    high          REAL,               -- 最高价
    low           REAL,               -- 最低价
    close         REAL,               -- 收盘价
    vol           REAL,               -- 成交量
    amount        REAL,               -- 成交额（千元）
    pct_change    REAL,               -- 涨跌幅 %
    PRIMARY KEY (industry_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_ind_daily_date
    ON industry_daily(trade_date);

-- ── Concept (同花顺概念) data ──

CREATE TABLE IF NOT EXISTS concept_index (
    ts_code   TEXT PRIMARY KEY,   -- 概念指数代码 (885710.TI ...)
    name      TEXT NOT NULL,      -- 概念名称
    type      TEXT NOT NULL,      -- I (行业) / N (概念)
    list_date TEXT,               -- 上市日期
    count     INTEGER             -- 成分股数量
);

CREATE TABLE IF NOT EXISTS concept_member (
    con_code   TEXT NOT NULL,     -- 概念指数代码
    stock_code TEXT NOT NULL,     -- 成分股代码
    stock_name TEXT,              -- 成分股名称
    PRIMARY KEY (con_code, stock_code)
);
