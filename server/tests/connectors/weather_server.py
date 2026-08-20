"""A tiny MCP server, used to prove Andy's connector path end to end.

Andy is meant to reach tools he does not own. That claim is worth nothing
unless something has actually connected: the transport, the handshake and the
tool listing all have to work, and none of them are exercised by configuring a
URL that is never dialled. This server exists so a test can dial one.

It is a `FastMCP` server, the same library the client half of the connector
path is built on, so the test exercises the pairing Andy actually uses.
"""

from fastmcp import FastMCP

mcp = FastMCP("andy-test-connector")


@mcp.tool
def tide_height(harbour: str) -> str:
    """Return the tide height at a harbour, so a test has something to call."""
    return f"The tide at {harbour} is 2.4 metres and rising."


if __name__ == "__main__":
    mcp.run()
