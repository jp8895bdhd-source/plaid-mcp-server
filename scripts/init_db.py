#!/usr/bin/env python3
"""Initialize the Plaid database tables. Safe to run multiple times."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from plaid_mcp.db import init_db, DEFAULT_DB_PATH

if __name__ == "__main__":
    init_db()
    print(f"Plaid tables initialized in {DEFAULT_DB_PATH}")
