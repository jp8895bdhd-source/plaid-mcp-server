"""MCP tool implementations -- all query tools read from SQLite."""

from datetime import date, timedelta
from pathlib import Path

from plaid_mcp.db import get_db, DEFAULT_DB_PATH


def plaid_get_accounts(db_path: Path | None = None) -> dict:
    """List all linked accounts with institution names and types."""
    path = db_path or DEFAULT_DB_PATH
    conn = get_db(path)
    rows = conn.execute(
        """SELECT a.account_id, a.name, a.official_name, a.type, a.subtype, a.mask,
                  a.current_balance, a.available_balance, a.credit_limit, a.balance_updated_at,
                  i.institution_name, i.last_synced_at
           FROM plaid_accounts a
           JOIN plaid_institutions i ON a.item_id = i.item_id
           ORDER BY i.institution_name, a.type, a.name"""
    ).fetchall()
    accounts = [
        {
            "account_id": r["account_id"], "name": r["name"], "official_name": r["official_name"],
            "institution": r["institution_name"], "type": r["type"], "subtype": r["subtype"],
            "mask": r["mask"], "current_balance": r["current_balance"],
            "available_balance": r["available_balance"], "credit_limit": r["credit_limit"],
            "last_synced": r["last_synced_at"],
        }
        for r in rows
    ]
    conn.close()
    return {"accounts": accounts}


def plaid_get_balances(live: bool = False, db_path: Path | None = None) -> dict:
    """Get account balances grouped by account type."""
    path = db_path or DEFAULT_DB_PATH
    conn = get_db(path)
    rows = conn.execute(
        """SELECT a.type, a.name, a.mask, a.current_balance, a.available_balance,
                  a.credit_limit, i.institution_name, i.last_synced_at
           FROM plaid_accounts a
           JOIN plaid_institutions i ON a.item_id = i.item_id
           ORDER BY a.type, i.institution_name"""
    ).fetchall()
    by_type = {}
    last_synced = None
    for r in rows:
        t = r["type"]
        if t not in by_type:
            by_type[t] = {"accounts": [], "total_current": 0.0, "total_available": 0.0}
        by_type[t]["accounts"].append({
            "name": r["name"], "institution": r["institution_name"], "mask": r["mask"],
            "current": r["current_balance"], "available": r["available_balance"],
            "credit_limit": r["credit_limit"],
        })
        by_type[t]["total_current"] += r["current_balance"] or 0
        by_type[t]["total_available"] += r["available_balance"] or 0
        if r["last_synced_at"]:
            if last_synced is None or r["last_synced_at"] > last_synced:
                last_synced = r["last_synced_at"]
    conn.close()
    return {"by_type": by_type, "last_synced": last_synced}


def plaid_get_transactions(
    start_date: str | None = None, end_date: str | None = None,
    category: str | None = None, merchant: str | None = None,
    min_amount: float | None = None, max_amount: float | None = None,
    account_id: str | None = None, limit: int = 50,
    db_path: Path | None = None,
) -> dict:
    """Get transactions with optional filters."""
    path = db_path or DEFAULT_DB_PATH
    conn = get_db(path)
    if not start_date:
        start_date = str(date.today() - timedelta(days=30))
    if not end_date:
        end_date = str(date.today())
    query = """SELECT t.transaction_id, t.date, t.name, t.merchant_name, t.amount,
                      t.category, t.subcategory, t.pending, t.payment_channel,
                      a.name as account_name, i.institution_name
               FROM plaid_transactions t
               JOIN plaid_accounts a ON t.account_id = a.account_id
               JOIN plaid_institutions i ON a.item_id = i.item_id
               WHERE t.date >= ? AND t.date <= ?"""
    params: list = [start_date, end_date]
    if category:
        query += " AND t.category = ?"
        params.append(category)
    if merchant:
        query += " AND (t.merchant_name LIKE ? OR t.name LIKE ?)"
        params.extend([f"%{merchant}%", f"%{merchant}%"])
    if min_amount is not None:
        query += " AND t.amount >= ?"
        params.append(min_amount)
    if max_amount is not None:
        query += " AND t.amount <= ?"
        params.append(max_amount)
    if account_id:
        query += " AND t.account_id = ?"
        params.append(account_id)
    query += " ORDER BY t.date DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    transactions = [
        {
            "date": r["date"], "name": r["name"], "merchant": r["merchant_name"],
            "amount": r["amount"], "category": r["category"], "subcategory": r["subcategory"],
            "pending": bool(r["pending"]), "account": r["account_name"],
            "institution": r["institution_name"],
        }
        for r in rows
    ]
    conn.close()
    return {"transactions": transactions, "count": len(transactions)}


def plaid_spending_summary(
    start_date: str | None = None, end_date: str | None = None,
    group_by: str = "category", account_id: str | None = None,
    db_path: Path | None = None,
) -> dict:
    """Get spending totals grouped by category, merchant, week, or month."""
    path = db_path or DEFAULT_DB_PATH
    conn = get_db(path)
    if not start_date:
        start_date = str(date.today() - timedelta(days=30))
    if not end_date:
        end_date = str(date.today())
    group_columns = {
        "category": "t.category", "merchant": "t.merchant_name",
        "week": "strftime('%Y-W%W', t.date)", "month": "strftime('%Y-%m', t.date)",
    }
    group_col = group_columns.get(group_by, "t.category")
    query = f"""SELECT {group_col} as grp, SUM(t.amount) as total, COUNT(*) as count
               FROM plaid_transactions t
               WHERE t.date >= ? AND t.date <= ? AND t.amount > 0 AND t.pending = 0"""
    params: list = [start_date, end_date]
    if account_id:
        query += " AND t.account_id = ?"
        params.append(account_id)
    query += f" GROUP BY {group_col} ORDER BY total DESC"
    rows = conn.execute(query, params).fetchall()
    summary = [
        {"group": r["grp"], "total": round(r["total"], 2), "count": r["count"]}
        for r in rows if r["grp"] is not None
    ]
    total_spending = sum(r["total"] for r in summary)
    conn.close()
    return {"summary": summary, "total": round(total_spending, 2), "period": f"{start_date} to {end_date}"}


def plaid_upcoming_payments(days_ahead: int = 30, db_path: Path | None = None) -> dict:
    """Get upcoming payment dates from liabilities and recurring transactions."""
    path = db_path or DEFAULT_DB_PATH
    conn = get_db(path)
    cutoff = str(date.today() + timedelta(days=days_ahead))
    today_str = str(date.today())
    payments = []
    rows = conn.execute(
        """SELECT l.account_id, l.type, l.minimum_payment_amount, l.next_payment_due_date,
                  a.name as account_name, i.institution_name
           FROM plaid_liabilities l
           JOIN plaid_accounts a ON l.account_id = a.account_id
           JOIN plaid_institutions i ON a.item_id = i.item_id
           WHERE l.next_payment_due_date IS NOT NULL AND l.next_payment_due_date != ''
             AND l.next_payment_due_date >= ? AND l.next_payment_due_date <= ?
           ORDER BY l.next_payment_due_date""",
        (today_str, cutoff),
    ).fetchall()
    for r in rows:
        payments.append({
            "source": "liability", "name": f"{r['account_name']} ({r['institution_name']})",
            "type": r["type"], "due_date": r["next_payment_due_date"],
            "amount": r["minimum_payment_amount"],
        })
    rows = conn.execute(
        """SELECT r.merchant_name, r.typical_amount, r.frequency, r.next_expected_date,
                  r.confidence, r.category
           FROM plaid_recurring r
           WHERE r.is_active = 1
             AND r.next_expected_date >= ? AND r.next_expected_date <= ?
           ORDER BY r.next_expected_date""",
        (today_str, cutoff),
    ).fetchall()
    for r in rows:
        payments.append({
            "source": "recurring", "name": r["merchant_name"], "type": r["category"],
            "due_date": r["next_expected_date"], "amount": r["typical_amount"],
            "confidence": r["confidence"],
        })
    payments.sort(key=lambda p: p["due_date"])
    conn.close()
    return {"payments": payments, "period": f"{today_str} to {cutoff}"}


def plaid_link_status(db_path: Path | None = None) -> dict:
    """Show linked institutions, connection health, and account counts."""
    path = db_path or DEFAULT_DB_PATH
    conn = get_db(path)
    rows = conn.execute(
        """SELECT i.item_id, i.institution_name, i.status, i.error_code, i.last_synced_at,
                  COUNT(a.account_id) as account_count
           FROM plaid_institutions i
           LEFT JOIN plaid_accounts a ON i.item_id = a.item_id
           GROUP BY i.item_id
           ORDER BY i.institution_name"""
    ).fetchall()
    institutions = [
        {"name": r["institution_name"], "status": r["status"], "error": r["error_code"],
         "last_synced": r["last_synced_at"], "account_count": r["account_count"]}
        for r in rows
    ]
    conn.close()
    return {"institutions": institutions}
