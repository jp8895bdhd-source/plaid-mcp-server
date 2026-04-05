"""SQLite database initialization and helpers for Plaid data."""

import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / "claude-automation" / "data" / "assistant.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS plaid_institutions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT UNIQUE NOT NULL,
    institution_id TEXT,
    institution_name TEXT NOT NULL,
    status TEXT DEFAULT 'healthy',
    error_code TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    last_synced_at TEXT
);

CREATE TABLE IF NOT EXISTS plaid_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT UNIQUE NOT NULL,
    item_id TEXT NOT NULL REFERENCES plaid_institutions(item_id),
    name TEXT NOT NULL,
    official_name TEXT,
    type TEXT NOT NULL,
    subtype TEXT,
    mask TEXT,
    current_balance REAL,
    available_balance REAL,
    credit_limit REAL,
    balance_updated_at TEXT
);

CREATE TABLE IF NOT EXISTS plaid_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id TEXT UNIQUE NOT NULL,
    account_id TEXT NOT NULL REFERENCES plaid_accounts(account_id),
    date TEXT NOT NULL,
    authorized_date TEXT,
    name TEXT NOT NULL,
    merchant_name TEXT,
    amount REAL NOT NULL,
    category TEXT,
    subcategory TEXT,
    pending INTEGER DEFAULT 0,
    payment_channel TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS plaid_liabilities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT UNIQUE NOT NULL REFERENCES plaid_accounts(account_id),
    type TEXT NOT NULL,
    last_payment_amount REAL,
    last_payment_date TEXT,
    minimum_payment_amount REAL,
    next_payment_due_date TEXT,
    apr REAL,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS plaid_investments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL REFERENCES plaid_accounts(account_id),
    security_name TEXT,
    ticker TEXT,
    quantity REAL,
    price REAL,
    value REAL,
    cost_basis REAL,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS plaid_recurring (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL REFERENCES plaid_accounts(account_id),
    merchant_name TEXT NOT NULL,
    typical_amount REAL NOT NULL,
    frequency TEXT NOT NULL,
    last_occurrence TEXT NOT NULL,
    next_expected_date TEXT NOT NULL,
    confidence REAL NOT NULL,
    category TEXT,
    is_active INTEGER DEFAULT 1,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS plaid_sync_cursors (
    item_id TEXT PRIMARY KEY REFERENCES plaid_institutions(item_id),
    cursor TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS plaid_sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT,
    status TEXT NOT NULL,
    items_synced INTEGER DEFAULT 0,
    transactions_added INTEGER DEFAULT 0,
    transactions_modified INTEGER DEFAULT 0,
    transactions_removed INTEGER DEFAULT 0,
    error_message TEXT
);
"""


def init_db(db_path: Path | None = None) -> None:
    """Create all plaid_* tables if they don't exist. Enables WAL mode."""
    path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA_SQL)
    conn.close()


def get_db(db_path: Path | None = None) -> sqlite3.Connection:
    """Return a connection with Row factory for dict-like access."""
    path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
