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


def test_agent_builds_copy_ready_opencode_prompt():
    from services.chat.tools import build_opencode_prompt

    prompt = build_opencode_prompt("The DJ service is offline", details="logs: connection refused")
    assert "/home/hdlrocha/open-studio" in prompt
    assert "pytest" in prompt
    assert "vue-tsc" in prompt
    assert "The DJ service is offline" in prompt
    assert "connection refused" in prompt
