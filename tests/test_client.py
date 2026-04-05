from unittest.mock import patch

from plaid_mcp.client import create_plaid_client, get_environment_host


class TestGetEnvironmentHost:
    def test_sandbox(self):
        import plaid
        assert get_environment_host("sandbox") == plaid.Environment.Sandbox

    def test_development(self):
        import plaid
        assert get_environment_host("development") == plaid.Environment.Sandbox

    def test_production(self):
        import plaid
        assert get_environment_host("production") == plaid.Environment.Production

    def test_defaults_to_sandbox(self):
        import plaid
        assert get_environment_host("unknown") == plaid.Environment.Sandbox


class TestCreatePlaidClient:
    @patch("plaid_mcp.client.get_plaid_credential")
    def test_creates_client_with_keychain_creds(self, mock_cred):
        mock_cred.side_effect = lambda key: {
            "client-id": "test-client-id",
            "secret": "test-secret",
            "environment": "sandbox",
        }.get(key)

        client = create_plaid_client()
        assert client is not None

    @patch("plaid_mcp.client.get_plaid_credential")
    def test_raises_on_missing_client_id(self, mock_cred):
        mock_cred.return_value = None
        try:
            create_plaid_client()
            assert False, "Should have raised"
        except ValueError as e:
            assert "client-id" in str(e)
