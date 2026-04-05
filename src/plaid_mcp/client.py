"""Plaid API client initialization from Keychain credentials."""

import plaid
from plaid.api import plaid_api

from plaid_mcp.credentials import get_plaid_credential


def get_environment_host(env_name: str) -> str:
    """Map environment name to Plaid host URL."""
    hosts = {
        "sandbox": plaid.Environment.Sandbox,
        "development": plaid.Environment.Sandbox,  # Development maps to Sandbox
        "production": plaid.Environment.Production,
    }
    return hosts.get(env_name, plaid.Environment.Sandbox)


def create_plaid_client() -> plaid_api.PlaidApi:
    """Create a Plaid API client using Keychain credentials.

    Reads client-id, secret, and environment from Keychain service 'plaid-api'.

    Raises:
        ValueError: If client-id or secret is not found in Keychain.
    """
    client_id = get_plaid_credential("client-id")
    secret = get_plaid_credential("secret")
    env_name = get_plaid_credential("environment") or "sandbox"

    if not client_id:
        raise ValueError(
            "Plaid client-id not found in Keychain. Run:\n"
            '  security add-generic-password -s "plaid-api" -a "client-id" -w "YOUR_ID" -U'
        )
    if not secret:
        raise ValueError(
            "Plaid secret not found in Keychain. Run:\n"
            '  security add-generic-password -s "plaid-api" -a "secret" -w "YOUR_SECRET" -U'
        )

    configuration = plaid.Configuration(
        host=get_environment_host(env_name),
        api_key={
            "clientId": client_id,
            "secret": secret,
        },
    )
    api_client = plaid.ApiClient(configuration)
    return plaid_api.PlaidApi(api_client)
