#!/usr/bin/env python3
"""Daily sync script for cron. Pulls all data from Plaid and updates SQLite."""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from plaid_mcp.client import create_plaid_client
from plaid_mcp.keychain import get_plaid_credential, list_access_tokens
from plaid_mcp.db import init_db, get_db
from plaid_mcp.sync import sync_transactions, sync_balances, sync_liabilities, sync_investments
from plaid_mcp.recurring import detect_recurring


def main():
    init_db()

    try:
        client = create_plaid_client()
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    token_names = list_access_tokens()
    if not token_names:
        print("No access tokens found. Link an institution first.", file=sys.stderr)
        sys.exit(1)

    started_at = datetime.now().isoformat()
    total_added = 0
    total_modified = 0
    total_removed = 0
    items_synced = 0
    errors = []

    for token_name in token_names:
        access_token = get_plaid_credential(token_name)
        if not access_token:
            continue

        slug = token_name.replace("access-token-", "")
        conn = get_db()
        row = conn.execute(
            "SELECT item_id, institution_name FROM plaid_institutions WHERE LOWER(REPLACE(institution_name, ' ', '-')) = ?",
            (slug,),
        ).fetchone()
        conn.close()

        if not row:
            errors.append(f"Institution not found for token: {token_name}")
            continue

        item_id = row["item_id"]
        inst_name = row["institution_name"]

        try:
            txn_result = sync_transactions(client, access_token, item_id)
            total_added += txn_result["added"]
            total_modified += txn_result["modified"]
            total_removed += txn_result["removed"]
        except Exception as e:
            errors.append(f"{inst_name} transactions: {e}")

        try:
            sync_balances(client, access_token, item_id)
        except Exception as e:
            errors.append(f"{inst_name} balances: {e}")

        try:
            sync_liabilities(client, access_token)
        except Exception as e:
            errors.append(f"{inst_name} liabilities: {e}")

        try:
            sync_investments(client, access_token)
        except Exception as e:
            errors.append(f"{inst_name} investments: {e}")

        items_synced += 1

    try:
        detect_recurring()
    except Exception as e:
        errors.append(f"Recurring detection: {e}")

    status = "success" if not errors else "partial"
    conn = get_db()
    conn.execute(
        """INSERT INTO plaid_sync_log
           (started_at, completed_at, status, items_synced, transactions_added, transactions_modified, transactions_removed, error_message)
           VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?)""",
        (started_at, status, items_synced, total_added, total_modified, total_removed, "; ".join(errors) if errors else None),
    )
    conn.commit()
    conn.close()

    print(f"Sync complete: {items_synced} institutions, +{total_added}/-{total_removed} transactions")
    if errors:
        print(f"Errors: {'; '.join(errors)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
