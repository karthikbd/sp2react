"""Agent runtime: prompt -> model -> parse -> validate -> retry with the problems, with transcripts on disk.

Agents never write straight into the app: their output is parsed and validated (schema, coverage gate,
import whitelist, compile/type checks) and only accepted when it passes.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from ..llm.providers import LLM, LLMError

PROMPTS = Path(__file__).parent / "prompts"


class ParseError(ValueError):
    pass


class AgentFailed(RuntimeError):
    def __init__(self, agent: str, task: str, problems: list[str], transcript: Path):
        super().__init__(f"{agent}/{task} failed validation after retries: {problems[:3]}")
        self.agent, self.task, self.problems, self.transcript = agent, task, problems, transcript


@dataclass
class AgentResult:
    output: Any
    attempts: int
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    notes: Optional[str] = None
    transcript: Optional[Path] = None


def render_sections(sections: dict[str, str]) -> str:
    parts = []
    for tag, content in sections.items():
        if content is None or content == "":
            continue
        parts.append(f"<{tag}>\n{content.strip()}\n</{tag}>")
    return "\n\n".join(parts)


def parse_json(text: str) -> dict:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    start = t.find("{")
    if start < 0:
        raise ParseError("Your reply did not contain a JSON object. Reply with exactly one JSON object.")
    try:
        obj, _ = json.JSONDecoder().raw_decode(t[start:])
    except json.JSONDecodeError as e:
        raise ParseError(f"Your reply was not valid JSON ({e.msg} at line {e.lineno} column {e.colno}). Reply with exactly one valid JSON object.") from e
    if not isinstance(obj, dict):
        raise ParseError("The JSON must be an object.")
    return obj


FILE_BLOCK = re.compile(r'<file\s+path="([^"]+)"\s*>\n?(.*?)\n?</file>', re.S)


def parse_files(text: str) -> dict:
    files = {}
    for path, body in FILE_BLOCK.findall(text):
        body = re.sub(r"^\s*```\w*\n", "", body)
        body = re.sub(r"\n```\s*$", "", body)
        files[path.strip()] = body.rstrip() + "\n"
    notes = re.search(r"<notes>(.*?)</notes>", text, re.S)
    patch = re.search(r"<spec_patch>(.*?)</spec_patch>", text, re.S)
    out = {"files": files, "notes": notes.group(1).strip() if notes else None, "spec_patch": None}
    if patch:
        out["spec_patch"] = parse_json(patch.group(1))
    if not files and not patch:
        raise ParseError('No <file path="...">...</file> blocks found. Return every file in that format.')
    return out


class Agent:
    def __init__(self, name: str, llm: LLM, workdir: Path, output: str = "json", retries: int = 2,
                 max_tokens: Optional[int] = None, progress: Callable[[str], None] = lambda s: None):
        self.name, self.llm, self.output = name, llm, output
        self.retries, self.max_tokens, self.progress = retries, max_tokens, progress
        self.workdir = workdir / "agents" / name
        self.prompt = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")

    @property
    def system(self) -> str:
        return f'<agent name="{self.name}">\n{self.prompt}\n</agent>'

    def _complete(self, messages: list[dict]) -> tuple[str, int, int]:
        text, tin, tout = "", 0, 0
        msgs = list(messages)
        for _ in range(4):
            c = self.llm.complete(self.system, msgs, max_tokens=self.max_tokens, json_output=(self.output == "json"))
            text += c.text
            tin += c.input_tokens
            tout += c.output_tokens
            if not c.truncated:
                break
            msgs = messages + [{"role": "assistant", "content": text},
                               {"role": "user", "content": "Your reply was cut off by the length limit. Continue exactly where it stopped. Do not repeat anything."}]
        return text, tin, tout

    def run(self, task_id: str, sections: dict[str, str], validate: Callable[[Any], list[str]]) -> AgentResult:
        tdir = self.workdir / re.sub(r"[^\w.\-]+", "_", task_id)
        tdir.mkdir(parents=True, exist_ok=True)
        user = render_sections(sections)
        (tdir / "prompt.md").write_text(f"# system\n\n{self.system}\n\n# user\n\n{user}\n", encoding="utf-8")
        messages = [{"role": "user", "content": user}]
        t0, tin, tout, problems = time.time(), 0, 0, []
        for attempt in range(1, self.retries + 2):
            self.progress(f"{self.name}: {task_id} attempt {attempt}")
            try:
                text, a, b = self._complete(messages)
            except LLMError as e:
                problems = [f"model call failed: {e}"]
                (tdir / f"attempt-{attempt}.error.txt").write_text(str(e), encoding="utf-8")
                if attempt > self.retries:
                    break
                continue
            tin, tout = tin + a, tout + b
            (tdir / f"attempt-{attempt}.response.md").write_text(text, encoding="utf-8")
            try:
                parsed = parse_json(text) if self.output == "json" else parse_files(text)
                problems = validate(parsed)
            except ParseError as e:
                problems = [str(e)]
            except Exception as e:  # a validator crashed on odd output: report it to the model like any problem
                problems = [f"Output could not be processed: {type(e).__name__}: {e}"]
            if not problems:
                (tdir / "accepted.txt").write_text(f"attempt {attempt}\n", encoding="utf-8")
                notes = parsed.get("notes") if isinstance(parsed, dict) else None
                return AgentResult(parsed, attempt, tin, tout, time.time() - t0, notes, tdir)
            (tdir / f"attempt-{attempt}.problems.md").write_text("\n".join(f"- {p}" for p in problems), encoding="utf-8")
            messages = messages + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": "<validation_feedback>\nYour output was rejected by automatic validation. Fix every problem and return the complete output again.\n"
                                            + "\n".join(f"- {p}" for p in problems[:60]) + "\n</validation_feedback>"},
            ]
        raise AgentFailed(self.name, task_id, problems, tdir)
