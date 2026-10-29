"""Agents: accepted output, rejected output with feedback + retry, and the provider wire formats."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from scripted_agents import RESP
from sp2react.agents.core import Agent, AgentFailed, parse_files
from sp2react.agents.tasks import merge_patch, page_file_problems, run_spec_agent
from sp2react.analysis.inventory import Legacy, build_inventory, screens
from sp2react.config import LLMConfig
from sp2react.llm.providers import ScriptedLLM, make_llm
from sp2react.spec.base import base_spec
from sp2react.spec.coverage import check

FIXTURE = Path(__file__).parent / "fixtures" / "legacy-site"


def form_inventory():
    lg = Legacy(FIXTURE)
    return lg, build_inventory(lg, screens(lg, ["Lists/VendorRequests/NewForm.aspx"])[0])


def test_correct_spec_patch_passes_the_gate():
    lg, inv = form_inventory()
    spec = merge_patch(base_spec(inv), json.loads((RESP / "spec" / "VendorRequests-form.json").read_text()))
    rep = check(spec, inv)
    assert rep.ok, rep.problems
    assert rep.covered == rep.must == 33


def test_spec_agent_gets_feedback_and_retries(tmp_path):
    lg, inv = form_inventory()
    good = json.loads((RESP / "spec" / "VendorRequests-form.json").read_text())
    bad = json.loads(json.dumps(good))
    r5 = next(r for r in bad["rules"] if r["id"] == "R5")
    r5["message"] = "Justification is required."                      # reworded legacy text
    bad["rules"] = [r for r in bad["rules"] if r["id"] != "R18"]       # and a dropped behaviour
    replies = [json.dumps(bad), "```json\n" + json.dumps(good) + "\n```"]
    seen = []

    def responder(agent, system, messages):
        seen.append(messages)
        return replies[len(seen) - 1]

    spec, res = run_spec_agent(Agent("spec", ScriptedLLM(responder), tmp_path), lg, inv, base_spec(inv))
    assert res.attempts == 2
    feedback = seen[1][-1]["content"]
    assert "<validation_feedback>" in feedback
    assert "Not covered: SiteAssets/js/vendor-request-form.js#L203:save_validation" in feedback
    assert 'Use exactly: "High Risk Justification is required for vendors in high-risk countries."' in feedback
    assert (tmp_path / "agents" / "spec" / "VendorRequests-form" / "attempt-1.problems.md").exists()
    assert len(spec.rules) == 23


def test_agent_gives_up_after_retries(tmp_path):
    lg, inv = form_inventory()
    agent = Agent("spec", ScriptedLLM(lambda a, s, m: "not json at all"), tmp_path, retries=1)
    with pytest.raises(AgentFailed) as e:
        run_spec_agent(agent, lg, inv, base_spec(inv))
    assert "did not contain a JSON object" in e.value.problems[0]


def test_page_validation_rejects_unsafe_or_reworded_code():
    out = parse_files((RESP / "page" / "Dashboard.txt").read_text())
    prefix = "frontend/src/screens/Dashboard/"
    texts = ["Approve this vendor request?", "This request was changed by someone else. Refresh and try again."]
    assert page_file_problems(out["files"], prefix, texts) == []
    code = out["files"][prefix + "Page.tsx"]
    bad = {prefix + "Page.tsx": code.replace('"Approve this vendor request?"', '"Approve?"').replace("api.get(LIST, id)", "fetch('/x')")
                                    .replace('from "../../api"', 'from "axios"')}
    probs = page_file_problems(bad, prefix, texts)
    assert any("Approve this vendor request?" in p for p in probs)
    assert any("fetch()" in p for p in probs)
    assert any("'axios' is not allowed" in p for p in probs)


# ------------------------------------------------------- provider wire formats
class _Capture(BaseHTTPRequestHandler):
    calls: list = []
    replies: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Capture.calls.append({"path": self.path, "headers": dict(self.headers), "body": body})
        payload = json.dumps(_Capture.replies.pop(0)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        payload = json.dumps({"data": [{"id": "claude-sonnet-4"}, {"id": "gpt-4.1"}]}).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture()
def server():
    _Capture.calls, _Capture.replies = [], []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Capture)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_bridger_claude_anthropic_format(server, monkeypatch):
    monkeypatch.setenv("BRIDGER_TOKEN", "tok")
    llm = make_llm(LLMConfig(provider="bridger", api_format="anthropic", base_url=server, model="claude-sonnet-4", api_key_env="BRIDGER_TOKEN"))
    _Capture.replies = [
        {"model": "claude-sonnet-4", "content": [{"type": "text", "text": '{"rules": ['}], "stop_reason": "max_tokens", "usage": {"input_tokens": 10, "output_tokens": 5}},
        {"model": "claude-sonnet-4", "content": [{"type": "text", "text": "]}"}], "stop_reason": "end_turn", "usage": {"input_tokens": 12, "output_tokens": 2}},
    ]
    agent = Agent("review", llm, Path("/tmp"), retries=0)
    text, tin, tout = agent._complete([{"role": "user", "content": "hi"}])
    assert text == '{"rules": []}' and (tin, tout) == (22, 7)                      # truncated reply continued
    first = _Capture.calls[0]
    assert first["path"] == "/v1/messages"
    assert first["headers"]["x-api-key"] == "tok" and first["headers"]["authorization"] == "Bearer tok"
    assert first["headers"]["anthropic-version"] == "2023-06-01"
    assert first["body"]["model"] == "claude-sonnet-4" and first["body"]["system"].startswith('<agent name="review">')
    assert _Capture.calls[1]["body"]["messages"][-1]["content"].startswith("Your reply was cut off")
    assert llm.models() == ["claude-sonnet-4", "gpt-4.1"]


def test_bridger_openai_format(server):
    llm = make_llm(LLMConfig(provider="bridger", api_format="openai", base_url=server, model="claude-sonnet-4"))
    _Capture.replies = [{"model": "claude-sonnet-4", "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 3, "completion_tokens": 1}}]
    c = llm.complete("sys", [{"role": "user", "content": "x"}], json_output=True)
    call = _Capture.calls[0]
    assert call["path"] == "/v1/chat/completions"
    assert call["body"]["messages"][0] == {"role": "system", "content": "sys"}
    assert call["body"]["response_format"] == {"type": "json_object"}
    assert c.text == "ok" and "authorization" not in {k.lower() for k in call["headers"]}
