"""Task 5.1: the sync->async bridge in OpponentLink (fastmcp Client is async)."""
import sys
import types


def test_send_turn_bridges_the_async_client(monkeypatch):
    calls = {}

    class FakeClient:
        def __init__(self, url):
            calls["url"] = url

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def call_tool(self, name, args):
            calls["tool"], calls["args"] = name, args
            return {"status": "ok", "acknowledged_commit": "abc"}

    fake = types.ModuleType("fastmcp")
    fake.Client = FakeClient
    monkeypatch.setitem(sys.modules, "fastmcp", fake)

    from police_thief.infra.mcp_client import OpponentLink
    out = OpponentLink("http://127.0.0.1:8801/mcp").send_turn({"role": "thief"})

    assert out == {"status": "ok", "acknowledged_commit": "abc"}
    assert calls["url"] == "http://127.0.0.1:8801/mcp"
    assert calls["tool"] == "receive_move"
    assert calls["args"] == {"message": {"role": "thief"}}


def test_result_object_with_data_attribute_is_unwrapped(monkeypatch):
    class Result:                       # fastmcp 2.x returns CallToolResult-like objects
        data = {"status": "ok"}

    class FakeClient:
        def __init__(self, url): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *exc): return False
        async def call_tool(self, name, args): return Result()

    fake = types.ModuleType("fastmcp")
    fake.Client = FakeClient
    monkeypatch.setitem(sys.modules, "fastmcp", fake)

    from police_thief.infra.mcp_client import OpponentLink
    assert OpponentLink("http://x/mcp").send_turn({}) == {"status": "ok"}
