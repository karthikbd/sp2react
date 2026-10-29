"""Scripted stand-in for the model in tests: returns the agent outputs stored under fixtures/agent_responses.

These fixture responses are what a correct agent run produces for the replica site; the tests prove the
pipeline accepts correct output, rejects wrong output (validation feedback + retry) and builds the app.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from sp2react.llm.providers import ScriptedLLM

RESP = Path(__file__).parent / "fixtures" / "agent_responses"


def screen_of(messages: list[dict]) -> str:
    text = messages[0]["content"]
    m = re.search(r"Screen (\S+) \(", text) or re.search(r"for screen (\S+) \(", text) or re.search(r'"id": "([^"]+)",\s*"kind": "(?:list-form|page)"', text)
    return m.group(1) if m else "?"


def responder(agent: str, system: str, messages: list[dict]) -> str:
    sid = screen_of(messages)
    if agent == "spec":
        return (RESP / "spec" / f"{sid}.json").read_text()
    if agent == "page":
        return (RESP / "page" / f"{sid}.txt").read_text()
    if agent == "dbmap":
        return (RESP / "dbmap" / "mapping.json").read_text()
    if agent == "review":
        return json.dumps({"verdict": "pass", "findings": []})
    raise AssertionError(f"unexpected agent call: {agent} for {sid}")


def scripted() -> ScriptedLLM:
    return ScriptedLLM(responder)
