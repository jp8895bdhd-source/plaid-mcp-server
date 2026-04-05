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


def sync_balances(client, access_token: str, item_id: str, db_path: Path | None = None) -> int:
    """Pull account balances and upsert into plaid_accounts."""
    path = db_path or DEFAULT_DB_PATH
    conn = get_db(path)

    request = AccountsBalanceGetRequest(access_token=access_token)
    response = client.accounts_balance_get(request)

    count = 0
    for acct in response["accounts"]:
        balances = acct["balances"]
        conn.execute(
            """INSERT INTO plaid_accounts
               (account_id, item_id, name, official_name, type, subtype, mask,
                current_balance, available_balance, credit_limit, balance_updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(account_id) DO UPDATE SET
                 name=excluded.name, official_name=excluded.official_name,
                 type=excluded.type, subtype=excluded.subtype, mask=excluded.mask,
                 current_balance=excluded.current_balance, available_balance=excluded.available_balance,
                 credit_limit=excluded.credit_limit, balance_updated_at=excluded.balance_updated_at""",
            (
                acct["account_id"], item_id, acct["name"], acct.get("official_name"),
                str(acct["type"]), str(acct.get("subtype") or ""), acct.get("mask"),
                balances.get("current"), balances.get("available"), balances.get("limit"),
            ),
        )
        count += 1

    conn.execute(
        "UPDATE plaid_institutions SET last_synced_at = datetime('now') WHERE item_id = ?",
        (item_id,),
    )
    conn.commit()
    conn.close()
    return count


def sync_liabilities(client, access_token: str, db_path: Path | None = None) -> int:
    """Pull liability data (credit cards, loans, mortgages)."""
    path = db_path or DEFAULT_DB_PATH
    conn = get_db(path)

    request = LiabilitiesGetRequest(access_token=access_token)
    response = client.liabilities_get(request)

    count = 0
    liabilities = response["liabilities"]

    for credit in liabilities.get("credit", []):
        apr = None
        if credit.get("aprs"):
            purchase_aprs = [a for a in credit["aprs"] if a.get("apr_type") == "purchase_apr"]
            apr = purchase_aprs[0]["apr_percentage"] if purchase_aprs else credit["aprs"][0]["apr_percentage"]

        conn.execute(
            """INSERT INTO plaid_liabilities
               (account_id, type, last_payment_amount, last_payment_date,
                minimum_payment_amount, next_payment_due_date, apr, updated_at)
               VALUES (?, 'credit', ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(account_id) DO UPDATE SET
                 last_payment_amount=excluded.last_payment_amount,
                 last_payment_date=excluded.last_payment_date,
                 minimum_payment_amount=excluded.minimum_payment_amount,
                 next_payment_due_date=excluded.next_payment_due_date,
                 apr=excluded.apr, updated_at=excluded.updated_at""",
            (
                credit["account_id"], credit.get("last_payment_amount"),
                str(credit.get("last_payment_date") or ""),
                credit.get("minimum_payment_amount"),
                str(credit.get("next_payment_due_date") or ""), apr,
            ),
        )
        count += 1

    for mortgage in liabilities.get("mortgage", []):
        conn.execute(
            """INSERT INTO plaid_liabilities
               (account_id, type, last_payment_amount, last_payment_date,
                minimum_payment_amount, next_payment_due_date, apr, updated_at)
               VALUES (?, 'mortgage', ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(account_id) DO UPDATE SET
                 last_payment_amount=excluded.last_payment_amount,
                 last_payment_date=excluded.last_payment_date,
                 minimum_payment_amount=excluded.minimum_payment_amount,
                 next_payment_due_date=excluded.next_payment_due_date,
                 apr=excluded.apr, updated_at=excluded.updated_at""",
            (
                mortgage["account_id"], mortgage.get("last_payment_amount"),
                str(mortgage.get("last_payment_date") or ""),
                mortgage.get("next_monthly_payment"),
                str(mortgage.get("next_payment_due_date") or ""),
                mortgage.get("interest_rate", {}).get("percentage"),
            ),
        )
        count += 1

    for student in liabilities.get("student", []):
        conn.execute(
            """INSERT INTO plaid_liabilities
               (account_id, type, last_payment_amount, last_payment_date,
                minimum_payment_amount, next_payment_due_date, apr, updated_at)
               VALUES (?, 'student', ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(account_id) DO UPDATE SET
                 last_payment_amount=excluded.last_payment_amount,
                 last_payment_date=excluded.last_payment_date,
                 minimum_payment_amount=excluded.minimum_payment_amount,
                 next_payment_due_date=excluded.next_payment_due_date,
                 apr=excluded.apr, updated_at=excluded.updated_at""",
            (
                student["account_id"], student.get("last_payment_amount"),
                str(student.get("last_payment_date") or ""),
                student.get("minimum_payment_amount"),
                str(student.get("next_payment_due_date") or ""),
                student.get("interest_rate_percentage"),
            ),
        )
        count += 1

    conn.commit()
    conn.close()
    return count


def sync_investments(client, access_token: str, db_path: Path | None = None) -> int:
    """Pull investment holdings."""
    path = db_path or DEFAULT_DB_PATH
    conn = get_db(path)

    request = InvestmentsHoldingsGetRequest(access_token=access_token)
    response = client.investments_holdings_get(request)

    securities = {s["security_id"]: s for s in response.get("securities", [])}

    account_ids = {h["account_id"] for h in response.get("holdings", [])}
    for aid in account_ids:
        conn.execute("DELETE FROM plaid_investments WHERE account_id = ?", (aid,))

    count = 0
    for holding in response.get("holdings", []):
        sec = securities.get(holding.get("security_id"), {})
        conn.execute(
            """INSERT INTO plaid_investments
               (account_id, security_name, ticker, quantity, price, value, cost_basis, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (
                holding["account_id"], sec.get("name"), sec.get("ticker_symbol"),
                holding.get("quantity"), holding.get("institution_price"),
                holding.get("institution_value"), holding.get("cost_basis"),
            ),
        )
        count += 1

    conn.commit()
    conn.close()
    return count
