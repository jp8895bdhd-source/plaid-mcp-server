"""Plaid data sync logic -- pulls from Plaid API, writes to SQLite."""

from pathlib import Path

from plaid.model.transactions_sync_request import TransactionsSyncRequest
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
from plaid.model.liabilities_get_request import LiabilitiesGetRequest
from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest

from plaid_mcp.db import get_db, DEFAULT_DB_PATH


def sync_transactions(client, access_token: str, item_id: str, db_path: Path | None = None) -> dict:
    """Pull transactions using cursor-based sync. Handles added, modified, removed."""
    path = db_path or DEFAULT_DB_PATH
    conn = get_db(path)

    row = conn.execute(
        "SELECT cursor FROM plaid_sync_cursors WHERE item_id = ?", (item_id,)
    ).fetchone()
    cursor = row["cursor"] if row else ""

    total_added = 0
    total_modified = 0
    total_removed = 0

    while True:
        kwargs = {"access_token": access_token}
        if cursor:
            kwargs["cursor"] = cursor
        request = TransactionsSyncRequest(**kwargs)
        response = client.transactions_sync(request)

        for txn in response["added"]:
            category = txn.get("personal_finance_category", {})
            conn.execute(
                """INSERT OR IGNORE INTO plaid_transactions
                   (transaction_id, account_id, date, authorized_date, name, merchant_name,
                    amount, category, subcategory, pending, payment_channel)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    txn["transaction_id"],
                    txn["account_id"],
                    str(txn["date"]),
                    str(txn.get("authorized_date") or txn["date"]),
                    txn["name"],
                    txn.get("merchant_name"),
                    txn["amount"],
                    category.get("primary"),
                    category.get("detailed"),
                    1 if txn.get("pending") else 0,
                    txn.get("payment_channel"),
                ),
            )
        total_added += len(response["added"])

        for txn in response["modified"]:
            category = txn.get("personal_finance_category", {})
            conn.execute(
                """UPDATE plaid_transactions SET
                   date=?, authorized_date=?, name=?, merchant_name=?,
                   amount=?, category=?, subcategory=?, pending=?, payment_channel=?
                   WHERE transaction_id=?""",
                (
                    str(txn["date"]),
                    str(txn.get("authorized_date") or txn["date"]),
                    txn["name"],
                    txn.get("merchant_name"),
                    txn["amount"],
                    category.get("primary"),
                    category.get("detailed"),
                    1 if txn.get("pending") else 0,
                    txn.get("payment_channel"),
                    txn["transaction_id"],
                ),
            )
        total_modified += len(response["modified"])

        for txn in response["removed"]:
            conn.execute(
                "DELETE FROM plaid_transactions WHERE transaction_id = ?",
                (txn["transaction_id"],),
            )
        total_removed += len(response["removed"])

        cursor = response["next_cursor"]

        if not response["has_more"]:
            break

    conn.execute(
        """INSERT INTO plaid_sync_cursors (item_id, cursor, updated_at)
           VALUES (?, ?, datetime('now'))
           ON CONFLICT(item_id) DO UPDATE SET cursor=excluded.cursor, updated_at=excluded.updated_at""",
        (item_id, cursor),
    )
    conn.commit()
    conn.close()

    return {"added": total_added, "modified": total_modified, "removed": total_removed}
