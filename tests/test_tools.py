import tempfile
from pathlib import Path

from plaid_mcp.db import init_db, get_db
from plaid_mcp.tools import (
    plaid_get_accounts,
    plaid_get_balances,
    plaid_get_transactions,
    plaid_spending_summary,
    plaid_upcoming_payments,
    plaid_link_status,
)


def seed_full_dataset(db_path):
    conn = get_db(db_path)
    conn.execute(
        "INSERT INTO plaid_institutions (item_id, institution_id, institution_name, status, last_synced_at) VALUES (?, ?, ?, ?, ?)",
        ("item_1", "ins_chase", "Chase", "healthy", "2026-04-05 06:00:00"),
    )
    conn.execute(
        "INSERT INTO plaid_institutions (item_id, institution_id, institution_name, status, last_synced_at) VALUES (?, ?, ?, ?, ?)",
        ("item_2", "ins_bofa", "Bank of America", "healthy", "2026-04-05 06:00:00"),
    )
    conn.execute(
        """INSERT INTO plaid_accounts
           (account_id, item_id, name, official_name, type, subtype, mask, current_balance, available_balance, credit_limit, balance_updated_at)
           VALUES ('acc_chk', 'item_1', 'Checking', 'TOTAL CHECKING', 'depository', 'checking', '1234', 5000.0, 4800.0, NULL, '2026-04-05 06:00:00')"""
    )
    conn.execute(
        """INSERT INTO plaid_accounts
           (account_id, item_id, name, official_name, type, subtype, mask, current_balance, available_balance, credit_limit, balance_updated_at)
           VALUES ('acc_sav', 'item_1', 'Savings', 'CHASE SAVINGS', 'depository', 'savings', '5678', 20000.0, 20000.0, NULL, '2026-04-05 06:00:00')"""
    )
    conn.execute(
        """INSERT INTO plaid_accounts
           (account_id, item_id, name, official_name, type, subtype, mask, current_balance, available_balance, credit_limit, balance_updated_at)
           VALUES ('acc_cc', 'item_2', 'Visa Platinum', 'VISA PLATINUM', 'credit', 'credit card', '9012', 1500.0, NULL, 10000.0, '2026-04-05 06:00:00')"""
    )
    transactions = [
        ("txn_1", "acc_chk", "2026-04-01", "STARBUCKS", "Starbucks", 5.50, "Food and Drink", "Coffee Shop", 0, "in store"),
        ("txn_2", "acc_chk", "2026-04-02", "AMAZON", "Amazon", 42.00, "Shopping", "Online Marketplace", 0, "online"),
        ("txn_3", "acc_cc", "2026-04-03", "UBER", "Uber", 25.00, "Travel", "Ride Share", 0, "online"),
        ("txn_4", "acc_chk", "2026-04-04", "WHOLE FOODS", "Whole Foods", 85.00, "Food and Drink", "Groceries", 0, "in store"),
        ("txn_5", "acc_chk", "2026-03-15", "NETFLIX", "Netflix", 15.99, "Entertainment", "Streaming", 0, "online"),
        ("txn_6", "acc_chk", "2026-04-05", "PENDING TXN", None, 10.00, "Shopping", "General", 1, "online"),
    ]
    for t in transactions:
        conn.execute(
            "INSERT INTO plaid_transactions (transaction_id, account_id, date, name, merchant_name, amount, category, subcategory, pending, payment_channel) VALUES (?,?,?,?,?,?,?,?,?,?)", t,
        )
    conn.execute(
        """INSERT INTO plaid_liabilities
           (account_id, type, last_payment_amount, last_payment_date, minimum_payment_amount, next_payment_due_date, apr)
           VALUES ('acc_cc', 'credit', 500.0, '2026-03-15', 35.0, '2026-04-15', 24.99)"""
    )
    conn.execute(
        """INSERT INTO plaid_recurring
           (account_id, merchant_name, typical_amount, frequency, last_occurrence, next_expected_date, confidence, category, is_active)
           VALUES ('acc_chk', 'Netflix', 15.99, 'monthly', '2026-03-15', '2026-04-15', 0.95, 'Entertainment', 1)"""
    )
    conn.commit()
    conn.close()


class TestPlaidGetAccounts:
    def setup_method(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = Path(self._tmp) / "test.db"
        init_db(self.db_path)
        seed_full_dataset(self.db_path)

    def test_returns_all_accounts(self):
        result = plaid_get_accounts(self.db_path)
        assert len(result["accounts"]) == 3

    def test_includes_institution_name(self):
        result = plaid_get_accounts(self.db_path)
        chase_accounts = [a for a in result["accounts"] if a["institution"] == "Chase"]
        assert len(chase_accounts) == 2


class TestPlaidGetBalances:
    def setup_method(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = Path(self._tmp) / "test.db"
        init_db(self.db_path)
        seed_full_dataset(self.db_path)

    def test_returns_balances_grouped_by_type(self):
        result = plaid_get_balances(db_path=self.db_path)
        assert "depository" in result["by_type"]
        assert "credit" in result["by_type"]
        assert result["by_type"]["depository"]["total_current"] == 25000.0

    def test_includes_last_synced(self):
        result = plaid_get_balances(db_path=self.db_path)
        assert "last_synced" in result


class TestPlaidGetTransactions:
    def setup_method(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = Path(self._tmp) / "test.db"
        init_db(self.db_path)
        seed_full_dataset(self.db_path)

    def test_returns_recent_transactions(self):
        result = plaid_get_transactions(start_date="2026-04-01", end_date="2026-04-05", db_path=self.db_path)
        assert len(result["transactions"]) >= 4

    def test_filters_by_category(self):
        result = plaid_get_transactions(category="Food and Drink", db_path=self.db_path)
        assert all(t["category"] == "Food and Drink" for t in result["transactions"])

    def test_filters_by_merchant(self):
        result = plaid_get_transactions(merchant="Starbucks", db_path=self.db_path)
        assert len(result["transactions"]) == 1

    def test_filters_by_amount_range(self):
        result = plaid_get_transactions(min_amount=20.0, max_amount=50.0, db_path=self.db_path)
        amounts = [t["amount"] for t in result["transactions"]]
        assert all(20.0 <= a <= 50.0 for a in amounts)

    def test_respects_limit(self):
        result = plaid_get_transactions(limit=2, db_path=self.db_path)
        assert len(result["transactions"]) == 2


class TestPlaidSpendingSummary:
    def setup_method(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = Path(self._tmp) / "test.db"
        init_db(self.db_path)
        seed_full_dataset(self.db_path)

    def test_groups_by_category(self):
        result = plaid_spending_summary(db_path=self.db_path)
        categories = {r["group"]: r["total"] for r in result["summary"]}
        assert "Food and Drink" in categories

    def test_groups_by_merchant(self):
        result = plaid_spending_summary(group_by="merchant", db_path=self.db_path)
        merchants = {r["group"] for r in result["summary"]}
        assert "Starbucks" in merchants


class TestPlaidUpcomingPayments:
    def setup_method(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = Path(self._tmp) / "test.db"
        init_db(self.db_path)
        seed_full_dataset(self.db_path)

    def test_includes_liability_payments(self):
        result = plaid_upcoming_payments(days_ahead=30, db_path=self.db_path)
        liability_payments = [p for p in result["payments"] if p["source"] == "liability"]
        assert len(liability_payments) >= 1
        assert liability_payments[0]["due_date"] == "2026-04-15"

    def test_includes_recurring_payments(self):
        result = plaid_upcoming_payments(days_ahead=30, db_path=self.db_path)
        recurring_payments = [p for p in result["payments"] if p["source"] == "recurring"]
        assert len(recurring_payments) >= 1


class TestPlaidLinkStatus:
    def setup_method(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = Path(self._tmp) / "test.db"
        init_db(self.db_path)
        seed_full_dataset(self.db_path)

    def test_returns_all_institutions(self):
        result = plaid_link_status(self.db_path)
        assert len(result["institutions"]) == 2

    def test_includes_account_counts(self):
        result = plaid_link_status(self.db_path)
        chase = [i for i in result["institutions"] if i["name"] == "Chase"][0]
        assert chase["account_count"] == 2
