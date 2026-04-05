"""macOS Keychain credential management for Plaid API."""

import re
import subprocess

SERVICE_NAME = "plaid-api"


def get_plaid_credential(account: str) -> str | None:
    """Retrieve a credential from macOS Keychain."""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", SERVICE_NAME, "-a", account, "-w"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except (subprocess.TimeoutExpired, OSError):
        return None


def save_plaid_credential(account: str, value: str) -> bool:
    """Save a credential to macOS Keychain."""
    try:
        result = subprocess.run(
            ["security", "add-generic-password", "-s", SERVICE_NAME, "-a", account, "-w", value, "-U"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def list_access_tokens() -> list[str]:
    """List all Plaid access token account names stored in Keychain."""
    try:
        result = subprocess.run(
            ["security", "dump-keychain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []

        accounts = re.findall(r'"acct"<blob>="(access-token-[^"]+)"', result.stdout)
        return sorted(set(accounts))
    except (subprocess.TimeoutExpired, OSError):
        return []
