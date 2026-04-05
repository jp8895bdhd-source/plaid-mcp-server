"""Entry point for running the Plaid MCP server."""

from plaid_mcp.server import mcp

mcp.run(transport="stdio")
