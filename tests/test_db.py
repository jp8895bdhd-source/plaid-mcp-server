import sqlite3
import tempfile
from pathlib import Path

from plaid_mcp.db import init_db, get_db


class TestInitDb:
    def test_creates_all_tables(self, tmp_path):
        db_path = tmp_path / "test.db"
        init_db(db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()

        expected_tables = [
            "plaid_accounts",
            "plaid_institutions",
            "plaid_investments",
            "plaid_liabilities",
            "plaid_recurring",
            "plaid_sync_cursors",
            "plaid_sync_log",
            "plaid_transactions",
        ]
        assert tables == expected_tables

    def test_idempotent(self, tmp_path):
        db_path = tmp_path / "test.db"
        init_db(db_path)
        init_db(db_path)  # Should not raise

        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 8

    def test_wal_mode_enabled(self, tmp_path):
        db_path = tmp_path / "test.db"
        init_db(db_path)

        conn = sqlite3.connect(db_path)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"


class TestGetDb:
    def test_returns_connection_with_row_factory(self, tmp_path):
        db_path = tmp_path / "test.db"
        init_db(db_path)

        conn = get_db(db_path)
        conn.execute(
            "INSERT INTO plaid_institutions (item_id, institution_name) VALUES (?, ?)",
            ("item_1", "Chase"),
        )
        row = conn.execute("SELECT * FROM plaid_institutions WHERE item_id = ?", ("item_1",)).fetchone()
        assert row["institution_name"] == "Chase"
        assert row["item_id"] == "item_1"
        conn.close()
