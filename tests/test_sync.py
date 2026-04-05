import sqlite3
import tempfile
from unittest.mock import MagicMock, patch
from pathlib import Path

from plaid_mcp.db import init_db, get_db
from plaid_mcp.sync import sync_transactions, sync_balances, sync_liabilities, sync_investments
from tests.fixtures.plaid_responses import (
    make_transaction,
    make_transactions_sync_response,
    make_account,
    make_balance_response,
    make_liabilities_response,
    make_credit_liability,
    make_investment_holding,
    make_security,
)


def seed_institution(db_path, item_id="item_1", name="Chase"):
    conn = get_db(db_path)
    conn.execute(
        "INSERT INTO plaid_institutions (item_id, institution_name) VALUES (?, ?)",
        (item_id, name),
    )
    conn.commit()
    conn.close()


def seed_account(db_path, account_id="acc_checking_1", item_id="item_1", name="Checking", type="depository", subtype="checking"):
    conn = get_db(db_path)
    conn.execute(
        "INSERT OR IGNORE INTO plaid_accounts (account_id, item_id, name, type, subtype) VALUES (?, ?, ?, ?, ?)",
        (account_id, item_id, name, type, subtype),
    )
    conn.commit()
    conn.close()


class TestSyncTransactions:
    def setup_method(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = Path(self._tmp) / "test.db"
        init_db(self.db_path)
        seed_institution(self.db_path)
        seed_account(self.db_path)

    def test_adds_new_transactions(self):
        mock_client = MagicMock()
        mock_client.transactions_sync.return_value = make_transactions_sync_response(
            added=[
                make_transaction(transaction_id="txn_1", amount=5.50, name="STARBUCKS"),
                make_transaction(transaction_id="txn_2", amount=42.00, name="AMAZON"),
            ],
            cursor="cursor_after_sync",
        )

        result = sync_transactions(mock_client, "fake-access-token", "item_1", self.db_path)

        assert result["added"] == 2
        assert result["modified"] == 0
        assert result["removed"] == 0

        conn = get_db(self.db_path)
        rows = conn.execute("SELECT * FROM plaid_transactions ORDER BY transaction_id").fetchall()
        assert len(rows) == 2
        assert rows[0]["transaction_id"] == "txn_1"
        assert rows[0]["amount"] == 5.50
        assert rows[1]["transaction_id"] == "txn_2"
        conn.close()

    def test_saves_cursor(self):
        mock_client = MagicMock()
        mock_client.transactions_sync.return_value = make_transactions_sync_response(
            cursor="new_cursor_123",
        )

        sync_transactions(mock_client, "fake-token", "item_1", self.db_path)

        conn = get_db(self.db_path)
        row = conn.execute("SELECT cursor FROM plaid_sync_cursors WHERE item_id = ?", ("item_1",)).fetchone()
        assert row["cursor"] == "new_cursor_123"
        conn.close()

    def test_uses_existing_cursor(self):
        conn = get_db(self.db_path)
        conn.execute(
            "INSERT INTO plaid_sync_cursors (item_id, cursor) VALUES (?, ?)",
            ("item_1", "existing_cursor"),
        )
        conn.commit()
        conn.close()

        mock_client = MagicMock()
        mock_client.transactions_sync.return_value = make_transactions_sync_response(cursor="next_cursor")

        sync_transactions(mock_client, "fake-token", "item_1", self.db_path)

        call_args = mock_client.transactions_sync.call_args
        request_obj = call_args[0][0]
        assert request_obj.cursor == "existing_cursor"

    def test_handles_modified_transactions(self):
        conn = get_db(self.db_path)
        conn.execute(
            "INSERT INTO plaid_transactions (transaction_id, account_id, date, name, amount) VALUES (?, ?, ?, ?, ?)",
            ("txn_1", "acc_checking_1", "2026-04-01", "STARBUCKS", 5.50),
        )
        conn.commit()
        conn.close()

        mock_client = MagicMock()
        mock_client.transactions_sync.return_value = make_transactions_sync_response(
            modified=[make_transaction(transaction_id="txn_1", amount=6.00, name="STARBUCKS UPDATED")],
            cursor="cursor_mod",
        )

        result = sync_transactions(mock_client, "fake-token", "item_1", self.db_path)
        assert result["modified"] == 1

        conn = get_db(self.db_path)
        row = conn.execute("SELECT * FROM plaid_transactions WHERE transaction_id = ?", ("txn_1",)).fetchone()
        assert row["amount"] == 6.00
        assert row["name"] == "STARBUCKS UPDATED"
        conn.close()

    def test_handles_removed_transactions(self):
        conn = get_db(self.db_path)
        conn.execute(
            "INSERT INTO plaid_transactions (transaction_id, account_id, date, name, amount) VALUES (?, ?, ?, ?, ?)",
            ("txn_1", "acc_checking_1", "2026-04-01", "OLD TXN", 10.00),
        )
        conn.commit()
        conn.close()

        mock_client = MagicMock()
        mock_client.transactions_sync.return_value = make_transactions_sync_response(
            removed=[{"transaction_id": "txn_1"}],
            cursor="cursor_rem",
        )

        result = sync_transactions(mock_client, "fake-token", "item_1", self.db_path)
        assert result["removed"] == 1

        conn = get_db(self.db_path)
        row = conn.execute("SELECT * FROM plaid_transactions WHERE transaction_id = ?", ("txn_1",)).fetchone()
        assert row is None
        conn.close()

    def test_handles_pagination(self):
        mock_client = MagicMock()
        mock_client.transactions_sync.side_effect = [
            make_transactions_sync_response(
                added=[make_transaction(transaction_id="txn_1")],
                cursor="page_1_cursor",
                has_more=True,
            ),
            make_transactions_sync_response(
                added=[make_transaction(transaction_id="txn_2")],
                cursor="page_2_cursor",
                has_more=False,
            ),
        ]

        result = sync_transactions(mock_client, "fake-token", "item_1", self.db_path)
        assert result["added"] == 2
        assert mock_client.transactions_sync.call_count == 2


class TestSyncBalances:
    def setup_method(self):
        import tempfile
        self._tmp = tempfile.mkdtemp()
        self.db_path = Path(self._tmp) / "test.db"
        init_db(self.db_path)
        seed_institution(self.db_path)

    def test_upserts_account_balances(self):
        mock_client = MagicMock()
        mock_client.accounts_balance_get.return_value = make_balance_response(
            accounts=[
                make_account(account_id="acc_1", name="Checking", current=5000.0, available=4800.0),
                make_account(account_id="acc_2", name="Savings", type="depository", subtype="savings", current=20000.0, available=20000.0),
            ]
        )
        sync_balances(mock_client, "fake-token", "item_1", self.db_path)
        conn = get_db(self.db_path)
        rows = conn.execute("SELECT * FROM plaid_accounts ORDER BY account_id").fetchall()
        assert len(rows) == 2
        assert rows[0]["current_balance"] == 5000.0
        assert rows[0]["available_balance"] == 4800.0
        assert rows[1]["current_balance"] == 20000.0
        conn.close()

    def test_updates_existing_account_balances(self):
        seed_account(self.db_path, account_id="acc_1")
        conn = get_db(self.db_path)
        conn.execute("UPDATE plaid_accounts SET current_balance = 1000.0 WHERE account_id = 'acc_1'")
        conn.commit()
        conn.close()

        mock_client = MagicMock()
        mock_client.accounts_balance_get.return_value = make_balance_response(
            accounts=[make_account(account_id="acc_1", current=5000.0, available=4800.0)]
        )
        sync_balances(mock_client, "fake-token", "item_1", self.db_path)
        conn = get_db(self.db_path)
        row = conn.execute("SELECT * FROM plaid_accounts WHERE account_id = 'acc_1'").fetchone()
        assert row["current_balance"] == 5000.0
        conn.close()


class TestSyncLiabilities:
    def setup_method(self):
        import tempfile
        self._tmp = tempfile.mkdtemp()
        self.db_path = Path(self._tmp) / "test.db"
        init_db(self.db_path)
        seed_institution(self.db_path)
        seed_account(self.db_path, account_id="acc_credit_1", type="credit", subtype="credit card")

    def test_syncs_credit_card_liabilities(self):
        mock_client = MagicMock()
        mock_client.liabilities_get.return_value = make_liabilities_response(
            credit=[make_credit_liability(
                account_id="acc_credit_1",
                next_payment_due_date="2026-04-15",
                minimum_payment_amount=35.0,
                last_payment_amount=500.0,
            )]
        )
        sync_liabilities(mock_client, "fake-token", self.db_path)
        conn = get_db(self.db_path)
        row = conn.execute("SELECT * FROM plaid_liabilities WHERE account_id = 'acc_credit_1'").fetchone()
        assert row is not None
        assert row["next_payment_due_date"] == "2026-04-15"
        assert row["minimum_payment_amount"] == 35.0
        assert row["type"] == "credit"
        conn.close()


class TestSyncInvestments:
    def setup_method(self):
        import tempfile
        self._tmp = tempfile.mkdtemp()
        self.db_path = Path(self._tmp) / "test.db"
        init_db(self.db_path)
        seed_institution(self.db_path)
        seed_account(self.db_path, account_id="acc_invest_1", type="investment", subtype="brokerage")

    def test_syncs_investment_holdings(self):
        mock_client = MagicMock()
        mock_client.investments_holdings_get.return_value = {
            "holdings": [make_investment_holding(
                account_id="acc_invest_1",
                security_id="sec_1",
                quantity=10.0,
                institution_price=150.0,
                institution_value=1500.0,
                cost_basis=1200.0,
            )],
            "securities": [make_security(security_id="sec_1", name="Apple Inc", ticker_symbol="AAPL")],
        }
        sync_investments(mock_client, "fake-token", self.db_path)
        conn = get_db(self.db_path)
        row = conn.execute("SELECT * FROM plaid_investments WHERE account_id = 'acc_invest_1'").fetchone()
        assert row is not None
        assert row["ticker"] == "AAPL"
        assert row["security_name"] == "Apple Inc"
        assert row["quantity"] == 10.0
        assert row["value"] == 1500.0
        conn.close()
