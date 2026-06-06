CREATE TABLE IF NOT EXISTS tushare_cache (
    code       TEXT NOT NULL,
    date       TEXT NOT NULL,
    open       REAL,
    high       REAL,
    low        REAL,
    close      REAL,
    vol        REAL,
    amount     REAL,
    adj_factor REAL,
    PRIMARY KEY (code, date)
);

CREATE INDEX IF NOT EXISTS idx_cache_code_date ON tushare_cache(code, date DESC);
