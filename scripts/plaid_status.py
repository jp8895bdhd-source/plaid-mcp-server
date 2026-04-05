#!/usr/bin/env python3
"""Status output for daily briefing integration.

Usage:
    python plaid_status.py           # Morning briefing (default)
    python plaid_status.py morning   # Morning briefing
    python plaid_status.py eod       # End of day briefing
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from plaid_mcp.db import get_db


def morning_briefing():
    conn = get_db()

    rows = conn.execute(
        """SELECT a.type, SUM(a.current_balance) as total
           FROM plaid_accounts a GROUP BY a.type ORDER BY a.type"""
    ).fetchall()

    if rows:
        print("PLAID BALANCES:")
        for r in rows:
            print(f"  {r['type'].title()}: ${r['total']:,.2f}")

    cutoff = str(date.today() + timedelta(days=7))
    today_str = str(date.today())

    payments = conn.execute(
        """SELECT a.name, i.institution_name, l.next_payment_due_date, l.minimum_payment_amount
           FROM plaid_liabilities l
           JOIN plaid_accounts a ON l.account_id = a.account_id
           JOIN plaid_institutions i ON a.item_id = i.item_id
           WHERE l.next_payment_due_date >= ? AND l.next_payment_due_date <= ?
           ORDER BY l.next_payment_due_date""",
        (today_str, cutoff),
    ).fetchall()

    recurring = conn.execute(
        """SELECT merchant_name, typical_amount, next_expected_date
           FROM plaid_recurring
           WHERE is_active = 1 AND next_expected_date >= ? AND next_expected_date <= ?
           ORDER BY next_expected_date""",
        (today_str, cutoff),
    ).fetchall()

    if payments or recurring:
        print("\nUPCOMING PAYMENTS (7 days):")
        for p in payments:
            print(f"  {p['next_payment_due_date']}: {p['name']} ({p['institution_name']}) - ${p['minimum_payment_amount']:,.2f} min")
        for r in recurring:
            print(f"  {r['next_expected_date']}: {r['merchant_name']} - ~${r['typical_amount']:,.2f}")

    last_sync = conn.execute(
        "SELECT * FROM plaid_sync_log ORDER BY started_at DESC LIMIT 1"
    ).fetchone()

    if last_sync:
        status_icon = "OK" if last_sync["status"] == "success" else "WARN"
        print(f"\nSYNC: {status_icon} (last: {last_sync['started_at'][:16]})")
        if last_sync["error_message"]:
            print(f"  Errors: {last_sync['error_message']}")
    else:
        print("\nSYNC: No sync history found")

    disconnected = conn.execute(
        "SELECT institution_name FROM plaid_institutions WHERE status != 'healthy'"
    ).fetchall()
    if disconnected:
        names = ", ".join(r["institution_name"] for r in disconnected)
        print(f"  DISCONNECTED: {names}")

    conn.close()


def eod_briefing():
    conn = get_db()
    today_str = str(date.today())

    rows = conn.execute(
        """SELECT COUNT(*) as count, SUM(amount) as total
           FROM plaid_transactions
           WHERE date = ? AND pending = 0 AND amount > 0""",
        (today_str,),
    ).fetchone()

    if rows and rows["count"] > 0:
        print(f"TODAY'S SPENDING: {rows['count']} transactions, ${rows['total']:,.2f}")
    else:
        print("TODAY'S SPENDING: No transactions recorded")

    largest = conn.execute(
        """SELECT name, merchant_name, amount, category
           FROM plaid_transactions
           WHERE date = ? AND pending = 0 AND amount > 0
           ORDER BY amount DESC LIMIT 1""",
        (today_str,),
    ).fetchone()

    if largest:
        merchant = largest["merchant_name"] or largest["name"]
        print(f"  Largest: {merchant} - ${largest['amount']:,.2f} ({largest['category']})")

    pending = conn.execute(
        "SELECT COUNT(*) as count, SUM(amount) as total FROM plaid_transactions WHERE pending = 1"
    ).fetchone()

    if pending and pending["count"] > 0:
        print(f"  Pending: {pending['count']} transactions (${pending['total']:,.2f})")

    conn.close()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "morning"
    if mode == "eod":
        eod_briefing()
    else:
        morning_briefing()
