"""Keychain helpers for Plaid credentials."""

import subprocess
from typing import Optional

from plaid_mcp.db import get_db

KEYCHAIN_SERVICE = "plaid-api"


def get_plaid_credential(account: str) -> Optional[str]:
    """Read a credential from macOS Keychain.

    Args:
        account: The account name (e.g. "client-id", "secret", "access-token-chase").

    Returns:
        The credential value, or None if not found.
    """
    result = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account, "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def save_plaid_credential(account: str, value: str) -> None:
    """Save a credential to macOS Keychain.

    Args:
        account: The account name.
        value: The credential value.
    """
    subprocess.run(
        ["security", "add-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account, "-w", value, "-U"],
        check=True,
        capture_output=True,
    )


def list_access_tokens() -> list[str]:
    """Return all access token names by querying the institutions table.

    Token names follow the pattern: access-token-{institution-name-slug}
    where slug = institution_name.lower().replace(" ", "-")

    Returns:
        List of token name strings (e.g. ["access-token-chase", "access-token-wells-fargo"]).
    """
    try:
        conn = get_db()
        rows = conn.execute("SELECT institution_name FROM plaid_institutions").fetchall()
        conn.close()
        return [
            f"access-token-{row['institution_name'].lower().replace(' ', '-')}"
            for row in rows
        ]
    except Exception:
        return []
