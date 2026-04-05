from unittest.mock import patch, MagicMock
import subprocess

from plaid_mcp.credentials import get_plaid_credential, list_access_tokens


class TestGetPlaidCredential:
    @patch("plaid_mcp.credentials.subprocess.run")
    def test_returns_credential_on_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="my-secret-value\n"
        )
        result = get_plaid_credential("client-id")
        assert result == "my-secret-value"
        mock_run.assert_called_once_with(
            ["security", "find-generic-password", "-s", "plaid-api", "-a", "client-id", "-w"],
            capture_output=True,
            text=True,
            timeout=5,
        )

    @patch("plaid_mcp.credentials.subprocess.run")
    def test_returns_none_on_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=44, stdout="")
        result = get_plaid_credential("nonexistent")
        assert result is None

    @patch("plaid_mcp.credentials.subprocess.run")
    def test_returns_none_on_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="security", timeout=5)
        result = get_plaid_credential("client-id")
        assert result is None


class TestListAccessTokens:
    @patch("plaid_mcp.credentials.subprocess.run")
    def test_extracts_access_token_accounts(self, mock_run):
        keychain_output = (
            'keychain: "/Users/alex/Library/Keychains/login.keychain-db"\n'
            '    "svce"<blob>="plaid-api"\n'
            '    "acct"<blob>="access-token-chase"\n'
            '    "svce"<blob>="plaid-api"\n'
            '    "acct"<blob>="access-token-wells-fargo"\n'
            '    "svce"<blob>="plaid-api"\n'
            '    "acct"<blob>="client-id"\n'
        )
        mock_run.return_value = MagicMock(returncode=0, stdout=keychain_output)
        tokens = list_access_tokens()
        assert tokens == ["access-token-chase", "access-token-wells-fargo"]

    @patch("plaid_mcp.credentials.subprocess.run")
    def test_returns_empty_on_no_tokens(self, mock_run):
        mock_run.return_value = MagicMock(returncode=44, stdout="")
        tokens = list_access_tokens()
        assert tokens == []
