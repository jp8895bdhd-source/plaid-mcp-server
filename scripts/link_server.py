#!/usr/bin/env python3
"""Minimal Flask server for Plaid Link OAuth flow.

Run this when you need to connect a new bank account.
Usage: python scripts/link_server.py
Then open http://localhost:8080 in your browser.
Kill with Ctrl+C when done.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from flask import Flask, render_template, request, jsonify

import plaid
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.products import Products
from plaid.model.country_code import CountryCode

from plaid_mcp.client import create_plaid_client
from plaid_mcp.credentials import save_plaid_credential
from plaid_mcp.db import init_db, get_db

app = Flask(__name__, template_folder=str(Path(__file__).parent / "templates"))


def get_client():
    return create_plaid_client()


@app.route("/")
def index():
    client = get_client()
    request_obj = LinkTokenCreateRequest(
        products=[Products("transactions"), Products("liabilities"), Products("investments")],
        client_name="Plaid MCP Server",
        country_codes=[CountryCode("US")],
        language="en",
        user=LinkTokenCreateRequestUser(client_user_id=str(int(time.time()))),
    )
    response = client.link_token_create(request_obj)
    link_token = response["link_token"]
    return render_template("link.html", link_token=link_token)


@app.route("/exchange", methods=["POST"])
def exchange():
    data = request.get_json()
    public_token = data["public_token"]
    institution_id = data["institution_id"]
    institution_name = data["institution_name"]
    accounts = data["accounts"]

    client = get_client()

    try:
        exchange_request = ItemPublicTokenExchangeRequest(public_token=public_token)
        exchange_response = client.item_public_token_exchange(exchange_request)
        access_token = exchange_response["access_token"]
        item_id = exchange_response["item_id"]
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

    slug = institution_name.lower().replace(" ", "-")
    token_name = f"access-token-{slug}"
    save_plaid_credential(token_name, access_token)

    init_db()
    conn = get_db()
    conn.execute(
        """INSERT INTO plaid_institutions (item_id, institution_id, institution_name)
           VALUES (?, ?, ?)
           ON CONFLICT(item_id) DO UPDATE SET institution_name=excluded.institution_name""",
        (item_id, institution_id, institution_name),
    )
    for acct in accounts:
        conn.execute(
            """INSERT INTO plaid_accounts (account_id, item_id, name, type, subtype, mask)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(account_id) DO UPDATE SET
                 name=excluded.name, type=excluded.type, subtype=excluded.subtype""",
            (acct["id"], item_id, acct["name"], acct["type"], acct.get("subtype", ""), acct.get("mask")),
        )
    conn.commit()
    conn.close()

    print(f"\nLinked: {institution_name} ({len(accounts)} accounts)")
    print(f"Access token saved to Keychain as '{token_name}'")

    return jsonify({"success": True, "institution": institution_name, "accounts": len(accounts)})


if __name__ == "__main__":
    init_db()
    print("\n  Plaid Link Server running at http://localhost:8080")
    print("  Open in your browser to connect a bank account.")
    print("  Press Ctrl+C to stop.\n")
    app.run(host="127.0.0.1", port=8080, debug=False)
