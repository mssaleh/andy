from __future__ import annotations

import sys
from pathlib import Path

import pytest

from andy.config import MCPServerSpec, _mcp_servers

SERVER = Path(__file__).parent / "connectors" / "weather_server.py"


def _in_process_server():
    """Load the fixture server as a module, without it being importable.

    The directory is deliberately not a package: a test package named `mcp`
    shadows the MCP SDK that the client library imports internally, which is a
    failure that looks like a missing dependency rather than a name collision.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("andy_test_connector", SERVER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.mcp


def test_a_plain_url_list_is_still_the_easy_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("M", "https://one.test/mcp, https://two.test/mcp")
    specs = _mcp_servers("M")
    assert [s.transport for s in specs] == ["http", "http"]
    assert specs[0].url == "https://one.test/mcp"


def test_the_standard_client_shape_is_understood(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same `mcpServers` block every other MCP client reads."""
    monkeypatch.setenv(
        "M",
        '{"mcpServers": {'
        '"home": {"url": "https://ha.test/api/mcp",'
        ' "headers": {"Authorization": "Bearer secret"}},'
        '"notes": {"command": "python3", "args": ["-m", "notes"],'
        ' "env": {"NOTES_DIR": "/data"}},'
        '"legacy": {"url": "https://old.test/sse", "transport": "sse"}}}',
    )
    specs = {s.name: s for s in _mcp_servers("M")}

    assert specs["home"].transport == "http"
    assert specs["home"].headers["Authorization"] == "Bearer secret"
    assert specs["notes"].transport == "stdio"
    assert specs["notes"].args == ("-m", "notes")
    assert specs["notes"].env == {"NOTES_DIR": "/data"}
    assert specs["legacy"].transport == "sse"


def test_a_connector_never_describes_its_own_credentials() -> None:
    """`describe` is what reaches the log and `GET /agent`."""
    spec = MCPServerSpec(
        name="home",
        transport="http",
        url="https://ha.test/api/mcp",
        headers={"Authorization": "Bearer secret"},
    )
    rendered = spec.describe()
    assert "secret" not in rendered
    assert "ha.test" in rendered


@pytest.mark.parametrize(
    "raw",
    [
        '{"mcpServers": {"bad": {}}}',
        '{"mcpServers": {"bad": {"url": "x", "command": "y"}}}',
        '{"mcpServers": {"bad": {"url": "not-a-url"}}}',
        '{"mcpServers": {"bad": {"url": "https://a.test", "transport": "carrier"}}}',
        '{"mcpServers": {"bad": "string"}}',
        "{not json",
    ],
)
def test_a_broken_connector_fails_at_startup_not_mid_conversation(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("M", raw)
    with pytest.raises(RuntimeError):
        _mcp_servers("M")


@pytest.mark.asyncio
async def test_the_configured_connector_is_what_gets_dialled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configuration to handshake, with nothing hand-written in between.

    Configuring a URL proves nothing. This parses the configuration exactly as
    the application does, hands it to the same client the application builds,
    completes a real stdio handshake with a server that actually runs, and
    reads back the tools the agent would be given.
    """
    from fastmcp.client import Client

    monkeypatch.setenv(
        "M",
        '{"mcpServers": {"tides": {"command": "%s", "args": ["%s"]}}}'
        % (sys.executable, SERVER),
    )
    specs = _mcp_servers("M")
    assert [s.transport for s in specs] == ["stdio"]

    client = Client({"mcpServers": {s.name: s.as_config() for s in specs}})
    async with client:
        tools = await client.list_tools()

    names = [tool.name for tool in tools]
    assert any("tide_height" in name for name in names), names


@pytest.mark.asyncio
async def test_a_connector_tool_can_be_called_and_returns_its_answer() -> None:
    """Listing a tool is not using one.

    The agent's value from a connector is the result it gets back, so the test
    goes all the way: call the tool over the transport and read the answer.
    """
    from fastmcp.client import Client

    async with Client(_in_process_server()) as client:
        result = await client.call_tool("tide_height", {"harbour": "Dover"})

    assert "2.4 metres" in str(result.content[0].text)


@pytest.mark.asyncio
async def test_the_agent_is_given_the_connector_as_a_toolset() -> None:
    """What `build_agent` receives is a toolset, not a URL."""
    from fastmcp.client import Client
    from pydantic_ai.mcp import MCPToolset

    toolset = MCPToolset(Client(_in_process_server()))
    assert isinstance(toolset, MCPToolset)
