import tempfile
from pathlib import Path
from datetime import date, timedelta

from plaid_mcp.db import init_db, get_db
from plaid_mcp.recurring import detect_recurring


def seed_data(db_path):
    conn = get_db(db_path)
    conn.execute("INSERT INTO plaid_institutions (item_id, institution_name) VALUES ('item_1', 'Chase')")
    conn.execute("INSERT INTO plaid_accounts (account_id, item_id, name, type) VALUES ('acc_1', 'item_1', 'Checking', 'depository')")
    conn.commit()
    conn.close()


def insert_transactions(db_path, merchant, amounts, dates):
    conn = get_db(db_path)
    for i, (amount, d) in enumerate(zip(amounts, dates)):
        conn.execute(
            "INSERT INTO plaid_transactions (transaction_id, account_id, date, name, merchant_name, amount, category) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"txn_{merchant}_{i}", "acc_1", str(d), merchant, merchant, amount, "Subscription"),
        )
    conn.commit()
    conn.close()


class TestDetectRecurring:
    def setup_method(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = Path(self._tmp) / "test.db"
        init_db(self.db_path)
        seed_data(self.db_path)

    def test_detects_monthly_subscription(self):
        today = date(2026, 4, 5)
        dates = [today - timedelta(days=30 * i) for i in range(4)]
        dates.reverse()
        insert_transactions(self.db_path, "Netflix", [15.99] * 4, dates)

        results = detect_recurring(self.db_path)

        assert len(results) == 1
        assert results[0]["merchant_name"] == "Netflix"
        assert results[0]["frequency"] == "monthly"
        assert results[0]["typical_amount"] == 15.99
        assert results[0]["confidence"] >= 0.7

    def test_detects_weekly_pattern(self):
        today = date(2026, 4, 5)
        dates = [today - timedelta(weeks=i) for i in range(5)]
        dates.reverse()
        insert_transactions(self.db_path, "House Cleaner", [120.00] * 5, dates)

        results = detect_recurring(self.db_path)

        weekly = [r for r in results if r["merchant_name"] == "House Cleaner"]
        assert len(weekly) == 1
        assert weekly[0]["frequency"] == "weekly"

    def test_ignores_random_transactions(self):
        insert_transactions(
            self.db_path, "Random Store",
            [10.00, 25.50, 7.99],
            [date(2026, 1, 5), date(2026, 2, 20), date(2026, 3, 8)],
        )
        results = detect_recurring(self.db_path)
        random_matches = [r for r in results if r["merchant_name"] == "Random Store"]
        assert len(random_matches) == 0

    def test_requires_minimum_3_transactions(self):
        insert_transactions(
            self.db_path, "TwoTimer",
            [50.00, 50.00],
            [date(2026, 3, 1), date(2026, 4, 1)],
        )
        results = detect_recurring(self.db_path)
        assert not any(r["merchant_name"] == "TwoTimer" for r in results)

    def test_writes_to_plaid_recurring_table(self):
        today = date(2026, 4, 5)
        dates = [today - timedelta(days=30 * i) for i in range(4)]
        dates.reverse()
        insert_transactions(self.db_path, "Spotify", [9.99] * 4, dates)

        detect_recurring(self.db_path)

        conn = get_db(self.db_path)
        rows = conn.execute("SELECT * FROM plaid_recurring WHERE merchant_name = 'Spotify'").fetchall()
        assert len(rows) == 1
        assert rows[0]["frequency"] == "monthly"
        assert rows[0]["is_active"] == 1
        conn.close()

    def test_predicts_next_date(self):
        dates = [date(2026, 1, 15), date(2026, 2, 15), date(2026, 3, 15)]
        insert_transactions(self.db_path, "Gym Membership", [49.99] * 3, dates)

        results = detect_recurring(self.db_path)
        gym = [r for r in results if r["merchant_name"] == "Gym Membership"][0]
        assert gym["next_expected_date"] == "2026-04-15"
