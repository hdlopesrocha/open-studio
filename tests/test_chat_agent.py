"""Agent intent, tool-loop and prompt-building tests for Chat."""

from __future__ import annotations

import asyncio
import importlib
import json
import sys


def _load_chat(tmp_path, monkeypatch):
    for name in list(sys.modules):
        if name == "services.chat.main":
            del sys.modules[name]
    monkeypatch.setenv("CHAT_DB_PATH", str(tmp_path / "chat-agent.db"))
    return importlib.import_module("services.chat.main")


def test_agent_detects_navigation_and_service_repair_intents():
    from services.chat.main import _deterministic_actions

    navigation = _deterministic_actions("Open the DJ Mix workspace")
    assert navigation == [{"tool": "navigate", "args": {"path": "/music?tab=dj-mix"}}]

    enable = _deterministic_actions("Enable the DJ service")
    assert enable[0]["tool"] == "service_action"
    assert enable[0]["args"] == {"name": "dj", "action": "enable"}

    diagnose = _deterministic_actions("Diagnose why translation is failing")
    assert diagnose[0]["tool"] == "diagnose"


def test_agent_distinguishes_questions_from_tasks(tmp_path, monkeypatch):
    module = _load_chat(tmp_path, monkeypatch)

    assert module._should_use_agent("How do I make a DJ mix?", []) is False
    assert module._should_use_agent("What services are online?", []) is True
    assert module._should_use_agent("Check which jobs failed", []) is True
    assert module._should_use_agent("Summarize these notes", ["notes.txt"]) is True
    assert module._should_use_agent("Tell me about Open Studio", []) is False


def test_agent_parses_json_and_code_fenced_decisions():
    from services.chat.main import _parse_agent_decision

    parsed = _parse_agent_decision('{"thought":"look","actions":[{"tool":"list_services","args":{}}],"final":null}')
    assert parsed is not None
    assert parsed["actions"] == [{"tool": "list_services", "args": {}}]
    assert parsed["final"] is None

    fenced = _parse_agent_decision('```json\n{"actions":[],"final":"All good"}\n```')
    assert fenced is not None
    assert fenced["final"] == "All good"

    plain = _parse_agent_decision("FINAL: Here is the result")
    assert plain == {"actions": [], "final": "Here is the result"}


def test_agent_loop_executes_tool_then_continues(tmp_path, monkeypatch):
    module = _load_chat(tmp_path, monkeypatch)
    calls: list[list[dict]] = []
    executed: list[tuple[str, dict]] = []

    async def fake_llm(messages, model, **kwargs):
        calls.append(messages)
        if len(calls) == 1:
            return {"content": json.dumps({"thought": "Inspect services", "actions": [{"tool": "list_services", "args": {}}], "final": None}), "model": model, "usage": {}}
        return {"content": json.dumps({"thought": "Enough information", "actions": [], "final": "Services checked."}), "model": model, "usage": {}}

    async def fake_tool(name, args):
        executed.append((name, args))
        return {"ok": True, "data": {"items": [{"name": "video", "online": True}]}}

    monkeypatch.setattr(module, "_request_llm", fake_llm)
    monkeypatch.setattr(module, "execute_tool", fake_tool)

    results, text = asyncio.run(module._run_agent({"id": "test-session", "system_prompt": "Open Studio"}, "Inspect the platform and report back", [], "test-model"))
    assert "Services checked" in (text or "")
    assert len(calls) == 2
    assert executed == [("list_services", {})]
    assert results[0]["tool"] == "list_services"
    assert results[0]["ok"] is True
    # The second turn must include the first tool result.
    assert any("TOOL RESULTS" in str(item.get("content")) for item in calls[1])


def test_agent_seeds_multiple_query_tools(tmp_path, monkeypatch):
    module = _load_chat(tmp_path, monkeypatch)

    actions = module._query_actions("Check the services and the five most recent jobs")
    assert [(item["tool"], item["args"]) for item in actions] == [
        ("list_services", {}),
        ("list_jobs", {"status": ""}),
    ]


def test_agent_prepares_direct_tool_arguments(tmp_path, monkeypatch):
    module = _load_chat(tmp_path, monkeypatch)

    translated = module._prepare_action(
        {"tool": "translate_text", "args": {}},
        "Translate this text into Portuguese: Open Studio is working.",
    )
    assert translated["args"]["text"] == "Open Studio is working."
    assert translated["args"]["target_language"] == "pt"

    assert module._image_prompt("Generate an image of a red square on a blue background") == "a red square on a blue background"


def test_agent_dispatches_explicit_api_catalog_tool(tmp_path, monkeypatch):
    module = _load_chat(tmp_path, monkeypatch)

    actions = module._explicit_tool_actions("Use api_catalog for music to find the project endpoint")
    assert actions == [{"tool": "api_catalog", "args": {"service": "music"}}]


def test_auto_repair_reads_logs_restarts_and_retries(monkeypatch):
    from services.chat import tools

    calls: list[tuple[str, str]] = []

    async def fake_item(name):
        return {"name": name, "enabled": False, "running": False, "health": "offline", "state": "stopped"}

    async def fake_request(service, method, path, body=None, **kwargs):
        calls.append((method, path))
        if path.endswith("/logs?lines=80"):
            return {"ok": True, "data": {"lines": "translation\nRuntimeError: model missing\n"}}
        if "/services/translation/enable" in path:
            return {"ok": True, "data": {"job": {"id": "repaired"}}}
        return {"ok": False, "error": "unexpected"}

    async def fake_execute(name, args):
        return {"ok": True, "data": {"translated_text": "Olá"}}

    monkeypatch.setattr(tools, "_service_item", fake_item)
    monkeypatch.setattr(tools, "_request", fake_request)
    monkeypatch.setattr(tools, "execute_tool", fake_execute)

    result = asyncio.run(tools.repair_tool_failure(
        {"tool": "translate_text", "args": {"text": "Hello"}},
        {"ok": False, "status": 503, "error": "translation unreachable"},
    ))
    assert result["ok"] is True
    assert result["data"]["translated_text"] == "Olá"
    assert result["repair"]["service"] == "translation"
    assert result["repair"]["action"] == "enable"
    assert result["repair"]["retried"] is True
    assert any(path.endswith("/logs?lines=80") for _, path in calls)


def test_diagnose_treats_running_admin_services_as_online(monkeypatch):
    import asyncio
    from services.chat import tools

    async def fake_request(service, method, path, body=None, **kwargs):
        if path == "/api/admin/services":
            return {"ok": True, "data": {"items": [
                {"name": "admin", "enabled": True, "running": True, "health": "healthy"},
                {"name": "translation", "enabled": True, "running": True, "health": "healthy"},
                {"name": "music-engine", "enabled": False, "running": False, "health": "stopped"},
            ]}}
        if path == "/api/admin/models":
            return {"ok": True, "data": {"items": []}}
        if path.startswith("/api/jobs"):
            return {"ok": True, "data": {"items": [], "total": 0}}
        return {"ok": False, "error": "unexpected"}

    monkeypatch.setattr(tools, "_request", fake_request)
    result = asyncio.run(tools._diagnose())
    assert result["data"]["offline_services"] == []


def test_api_spec_catalog_and_describe_expose_request_fields(): 
    import asyncio
    from services.chat import tools

    catalog = asyncio.run(tools.execute_tool("api_catalog", {"service": "music"}))
    assert catalog["ok"] is True
    create = next(item for item in catalog["data"]["endpoints"] if item["method"] == "POST" and item["path"] == "/api/music/projects")
    assert "title" in create["body_fields"]

    described = asyncio.run(tools.execute_tool("api_describe", {"service": "music", "method": "POST", "path": "/api/music/projects"}))
    assert described["ok"] is True
    assert described["data"]["body_fields"] == ["artist", "color", "description", "title"]
    assert described["data"]["request_example"]["title"] == "string"
    assert "ProjectCreate" in described["data"]["components"]


def test_chat_jobs_include_originating_prompt(monkeypatch):
    from services.chat import tools

    captured: dict = {}

    async def fake_request(service, method, path, body=None, **kwargs):
        captured.update({"service": service, "method": method, "path": path, "body": body})
        return {"ok": True, "data": {"id": "job-1"}}

    tools.set_chat_prompt("Make a red square image")
    monkeypatch.setattr(tools, "_request", fake_request)
    result = asyncio.run(tools.execute_tool("start_job", {"component": "imagegen", "action": "generate", "params": {"prompt": "red square"}}))
    assert result["ok"] is True
    assert captured["body"]["params"]["prompt"] == "red square"
    assert captured["body"]["params"]["chat_prompt"] == "Make a red square image"


def test_agent_builds_copy_ready_opencode_prompt():
    from services.chat.tools import build_opencode_prompt

    prompt = build_opencode_prompt("The DJ service is offline", details="logs: connection refused")
    assert "/home/hdlrocha/open-studio" in prompt
    assert "pytest" in prompt
    assert "vue-tsc" in prompt
    assert "The DJ service is offline" in prompt
    assert "connection refused" in prompt
