"""Plaid MCP Server -- exposes financial data tools to Claude Code."""

from datetime import datetime

from mcp.server.fastmcp import FastMCP

from plaid_mcp.db import init_db, get_db
from plaid_mcp.tools import (
    plaid_get_accounts,
    plaid_get_balances,
    plaid_get_transactions,
    plaid_spending_summary,
    plaid_upcoming_payments,
    plaid_link_status,
)
from plaid_mcp.client import create_plaid_client
from plaid_mcp.sync import sync_transactions, sync_balances, sync_liabilities, sync_investments
from plaid_mcp.recurring import detect_recurring
from plaid_mcp.credentials import get_plaid_credential, list_access_tokens

# Initialize database tables on import
init_db()

mcp = FastMCP("Plaid", json_response=True)


@mcp.tool()
def get_accounts() -> dict:
    """List all linked bank accounts with institution names, types, and balances."""
    return plaid_get_accounts()


@mcp.tool()
def get_balances(live: bool = False) -> dict:
    """Get account balances grouped by type (depository, credit, investment, loan).

    Args:
        live: If True, fetches real-time balances from Plaid API instead of cached data.
    """
    if live:
        try:
            client = create_plaid_client()
            token_names = list_access_tokens()
            for token_name in token_names:
                access_token = get_plaid_credential(token_name)
                if access_token:
                    item_id_suffix = token_name.replace("access-token-", "")
                    conn = get_db()
                    row = conn.execute(
                        "SELECT item_id FROM plaid_institutions WHERE LOWER(REPLACE(institution_name, ' ', '-')) = ?",
                        (item_id_suffix,),
                    ).fetchone()
                    if row:
                        sync_balances(client, access_token, row["item_id"])
                    conn.close()
        except Exception as e:
            return {"error": f"Live balance fetch failed: {e}", "fallback": plaid_get_balances()}
    return plaid_get_balances()


@mcp.tool()
def get_transactions(
    start_date: str = "",
    end_date: str = "",
    category: str = "",
    merchant: str = "",
    min_amount: float = 0,
    max_amount: float = 0,
    account_id: str = "",
    limit: int = 50,
) -> dict:
    """Search transactions with filters.

    Args:
        start_date: Start date (YYYY-MM-DD). Defaults to 30 days ago.
        end_date: End date (YYYY-MM-DD). Defaults to today.
        category: Filter by category (e.g., "Food and Drink", "Travel", "Shopping").
        merchant: Partial match on merchant name.
        min_amount: Minimum transaction amount.
        max_amount: Maximum transaction amount (0 = no max).
        account_id: Filter to specific account.
        limit: Max results (default 50).
    """
    return plaid_get_transactions(
        start_date=start_date or None,
        end_date=end_date or None,
        category=category or None,
        merchant=merchant or None,
        min_amount=min_amount if min_amount > 0 else None,
        max_amount=max_amount if max_amount > 0 else None,
        account_id=account_id or None,
        limit=limit,
    )


@mcp.tool()
def spending_summary(
    start_date: str = "",
    end_date: str = "",
    group_by: str = "category",
    account_id: str = "",
) -> dict:
    """Get spending totals grouped by category, merchant, week, or month.

    Args:
        start_date: Start date (YYYY-MM-DD). Defaults to 30 days ago.
        end_date: End date (YYYY-MM-DD). Defaults to today.
        group_by: How to group results: "category" (default), "merchant", "week", "month".
        account_id: Filter to specific account.
    """
    return plaid_spending_summary(
        start_date=start_date or None,
        end_date=end_date or None,
        group_by=group_by,
        account_id=account_id or None,
    )


@mcp.tool()
def upcoming_payments(days_ahead: int = 30) -> dict:
    """Show upcoming payment due dates from credit cards, loans, and detected recurring bills.

    Args:
        days_ahead: How many days to look ahead (default 30).
    """
    return plaid_upcoming_payments(days_ahead=days_ahead)


@mcp.tool()
def link_status() -> dict:
    """Show linked institutions, connection health, and last sync time."""
    return plaid_link_status()


@mcp.tool()
def sync() -> dict:
    """Pull latest data from Plaid for all linked institutions.

    Syncs transactions (incremental), balances, liabilities, and investments.
    Runs recurring transaction detection after sync.
    """
    try:
        client = create_plaid_client()
    except ValueError as e:
        return {"error": str(e)}

    token_names = list_access_tokens()
    if not token_names:
        return {"error": "No access tokens found. Link an institution first."}

    results = []
    total_txn_added = 0
    total_txn_modified = 0
    total_txn_removed = 0
    items_synced = 0
    started_at = datetime.now().isoformat()

    for token_name in token_names:
        access_token = get_plaid_credential(token_name)
        if not access_token:
            continue

        institution_slug = token_name.replace("access-token-", "")
        conn = get_db()
        row = conn.execute(
            "SELECT item_id, institution_name FROM plaid_institutions WHERE LOWER(REPLACE(institution_name, ' ', '-')) = ?",
            (institution_slug,),
        ).fetchone()
        conn.close()

        if not row:
            results.append({"institution": institution_slug, "error": "Institution not found in database"})
            continue

        item_id = row["item_id"]
        inst_name = row["institution_name"]
        item_result = {"institution": inst_name}

        try:
            txn_result = sync_transactions(client, access_token, item_id)
            item_result["transactions"] = txn_result
            total_txn_added += txn_result["added"]
            total_txn_modified += txn_result["modified"]
            total_txn_removed += txn_result["removed"]
        except Exception as e:
            item_result["transactions_error"] = str(e)

        try:
            balance_count = sync_balances(client, access_token, item_id)
            item_result["accounts_updated"] = balance_count
        except Exception as e:
            item_result["balances_error"] = str(e)

        try:
            liability_count = sync_liabilities(client, access_token)
            item_result["liabilities_synced"] = liability_count
        except Exception as e:
            item_result["liabilities_error"] = str(e)

        try:
            investment_count = sync_investments(client, access_token)
            item_result["investments_synced"] = investment_count
        except Exception as e:
            item_result["investments_error"] = str(e)

        results.append(item_result)
        items_synced += 1

    recurring_count = 0
    try:
        recurring_results = detect_recurring()
        recurring_count = len(recurring_results)
    except Exception:
        pass

    conn = get_db()
    conn.execute(
        """INSERT INTO plaid_sync_log
           (started_at, completed_at, status, items_synced, transactions_added, transactions_modified, transactions_removed)
           VALUES (?, datetime('now'), 'success', ?, ?, ?, ?)""",
        (started_at, items_synced, total_txn_added, total_txn_modified, total_txn_removed),
    )
    conn.commit()
    conn.close()

    return {
        "items_synced": items_synced,
        "transactions_added": total_txn_added,
        "transactions_modified": total_txn_modified,
        "transactions_removed": total_txn_removed,
        "recurring_patterns_detected": recurring_count,
        "details": results,
    }
