"""Detect recurring transactions from transaction history."""

from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, stdev

from plaid_mcp.db import get_db, DEFAULT_DB_PATH

FREQUENCIES = [
    ("weekly", 7, 2),
    ("biweekly", 14, 3),
    ("monthly", 30, 5),
    ("quarterly", 91, 10),
    ("annual", 365, 30),
]

MIN_TRANSACTIONS = 3
MIN_CONFIDENCE = 0.7


def _classify_frequency(intervals: list[int]) -> tuple[str, float] | None:
    if not intervals:
        return None

    avg_interval = mean(intervals)
    interval_stdev = stdev(intervals) if len(intervals) > 1 else 0

    best_match = None
    best_confidence = 0.0

    for freq_name, expected, tolerance in FREQUENCIES:
        if abs(avg_interval - expected) <= tolerance:
            closeness = 1.0 - (abs(avg_interval - expected) / tolerance)
            consistency = max(0.0, 1.0 - (interval_stdev / expected)) if expected > 0 else 0.0
            confidence = (closeness * 0.4) + (consistency * 0.6)

            if confidence > best_confidence:
                best_confidence = confidence
                best_match = freq_name

    if best_match and best_confidence >= MIN_CONFIDENCE:
        return (best_match, round(best_confidence, 3))
    return None


def _predict_next_date(last_date: date, frequency: str) -> date:
    intervals = {
        "weekly": 7, "biweekly": 14, "monthly": 30, "quarterly": 91, "annual": 365,
    }

    if frequency == "monthly":
        month = last_date.month + 1
        year = last_date.year
        if month > 12:
            month = 1
            year += 1
        day = min(last_date.day, 28)
        return date(year, month, day)

    return last_date + timedelta(days=intervals.get(frequency, 30))


def detect_recurring(db_path: Path | None = None) -> list[dict]:
    path = db_path or DEFAULT_DB_PATH
    conn = get_db(path)

    rows = conn.execute(
        """SELECT merchant_name, account_id, date, amount, category
           FROM plaid_transactions
           WHERE merchant_name IS NOT NULL AND merchant_name != ''
           ORDER BY merchant_name, date"""
    ).fetchall()

    groups = defaultdict(list)
    for row in rows:
        key = (row["merchant_name"], row["account_id"])
        groups[key].append(row)

    results = []
    conn.execute("DELETE FROM plaid_recurring")

    for (merchant, account_id), txns in groups.items():
        if len(txns) < MIN_TRANSACTIONS:
            continue

        dates = [date.fromisoformat(t["date"]) for t in txns]
        dates.sort()
        intervals = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]

        amounts = [t["amount"] for t in txns]
        amount_stdev = stdev(amounts) if len(amounts) > 1 else 0
        avg_amount = mean(amounts)
        if avg_amount > 0 and amount_stdev / avg_amount > 0.3:
            continue

        classification = _classify_frequency(intervals)
        if classification is None:
            continue

        freq_name, confidence = classification
        last_date = dates[-1]
        next_date = _predict_next_date(last_date, freq_name)
        typical_amount = round(mean(amounts), 2)

        entry = {
            "account_id": account_id,
            "merchant_name": merchant,
            "typical_amount": typical_amount,
            "frequency": freq_name,
            "last_occurrence": str(last_date),
            "next_expected_date": str(next_date),
            "confidence": confidence,
            "category": txns[-1]["category"],
        }
        results.append(entry)

        conn.execute(
            """INSERT INTO plaid_recurring
               (account_id, merchant_name, typical_amount, frequency,
                last_occurrence, next_expected_date, confidence, category, is_active, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, datetime('now'))""",
            (account_id, merchant, typical_amount, freq_name,
             str(last_date), str(next_date), confidence, txns[-1]["category"]),
        )

    conn.commit()
    conn.close()
    return results
