"""Mock Plaid API responses for testing."""


def make_transaction(
    transaction_id="txn_1",
    account_id="acc_checking_1",
    date="2026-04-01",
    name="STARBUCKS",
    merchant_name="Starbucks",
    amount=5.50,
    category=None,
    pending=False,
    payment_channel="in store",
    authorized_date=None,
):
    cat = category or ["Food and Drink", "Coffee Shop"]
    return {
        "transaction_id": transaction_id,
        "account_id": account_id,
        "date": date,
        "authorized_date": authorized_date or date,
        "name": name,
        "merchant_name": merchant_name,
        "amount": amount,
        "personal_finance_category": {"primary": cat[0], "detailed": cat[-1]},
        "pending": pending,
        "payment_channel": payment_channel,
    }


def make_transactions_sync_response(
    added=None, modified=None, removed=None, cursor="cursor_abc", has_more=False
):
    return {
        "added": added or [],
        "modified": modified or [],
        "removed": removed or [],
        "next_cursor": cursor,
        "has_more": has_more,
    }


def make_account(
    account_id="acc_checking_1",
    name="Checking",
    official_name="TOTAL CHECKING",
    type="depository",
    subtype="checking",
    mask="1234",
    current=5000.00,
    available=4800.00,
    limit=None,
):
    return {
        "account_id": account_id,
        "name": name,
        "official_name": official_name,
        "type": type,
        "subtype": subtype,
        "mask": mask,
        "balances": {
            "current": current,
            "available": available,
            "limit": limit,
        },
    }


def make_balance_response(accounts=None):
    return {"accounts": accounts or []}


def make_liabilities_response(credit=None, mortgage=None, student=None):
    return {
        "accounts": [],
        "liabilities": {
            "credit": credit or [],
            "mortgage": mortgage or [],
            "student": student or [],
        },
    }


def make_credit_liability(
    account_id="acc_credit_1",
    last_payment_amount=500.0,
    last_payment_date="2026-03-15",
    minimum_payment_amount=35.0,
    next_payment_due_date="2026-04-15",
    aprs=None,
):
    return {
        "account_id": account_id,
        "last_payment_amount": last_payment_amount,
        "last_payment_date": last_payment_date,
        "minimum_payment_amount": minimum_payment_amount,
        "next_payment_due_date": next_payment_due_date,
        "aprs": aprs or [{"apr_percentage": 24.99, "apr_type": "purchase_apr"}],
    }


def make_investment_holding(
    account_id="acc_invest_1",
    security_id="sec_1",
    quantity=10.0,
    institution_price=150.00,
    institution_value=1500.00,
    cost_basis=1200.00,
):
    return {
        "account_id": account_id,
        "security_id": security_id,
        "quantity": quantity,
        "institution_price": institution_price,
        "institution_value": institution_value,
        "cost_basis": cost_basis,
    }


def make_security(security_id="sec_1", name="Apple Inc", ticker_symbol="AAPL"):
    return {
        "security_id": security_id,
        "name": name,
        "ticker_symbol": ticker_symbol,
    }
