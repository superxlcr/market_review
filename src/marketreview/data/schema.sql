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
