"""Agent intent and prompt-building tests for Chat."""

from __future__ import annotations


def test_agent_detects_navigation_and_service_repair_intents():
    from services.chat.main import _deterministic_actions

    navigation = _deterministic_actions("Open the DJ Mix workspace")
    assert navigation == [{"tool": "navigate", "args": {"path": "/music?tab=dj-mix"}}]

    enable = _deterministic_actions("Enable the DJ service")
    assert enable[0]["tool"] == "service_action"
    assert enable[0]["args"] == {"name": "dj", "action": "enable"}

    diagnose = _deterministic_actions("Diagnose why translation is failing")
    assert diagnose[0]["tool"] == "diagnose"


def test_agent_builds_copy_ready_opencode_prompt():
    from services.chat.tools import build_opencode_prompt

    prompt = build_opencode_prompt("The DJ service is offline", details="logs: connection refused")
    assert "/home/hdlrocha/open-studio" in prompt
    assert "pytest" in prompt
    assert "vue-tsc" in prompt
    assert "The DJ service is offline" in prompt
    assert "connection refused" in prompt
