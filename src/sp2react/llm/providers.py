"""Model providers. Bridger (GitHub Copilot bridge) serving Claude is the default.

Two wire formats cover every provider:
  * Anthropic Messages  (POST {base}/v1/messages)          -> anthropic, bridger(api_format=anthropic)
  * OpenAI Chat         (POST {base}/v1/chat/completions)  -> openai, bridger(api_format=openai), azure_openai
"""
from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import requests

from ..config import ConfigError, LLMConfig, secret

log = logging.getLogger(__name__)
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}


class LLMError(RuntimeError):
    pass


@dataclass
class Completion:
    text: str
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    truncated: bool = False          # stopped because of max_tokens
    raw: dict = field(default_factory=dict, repr=False)


class LLM:
    name = "base"

    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self.policy = None
        self._local = threading.local()

    @property
    def session(self) -> requests.Session:
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            s.verify = self.cfg.verify_ssl
            if self.policy is not None:
                self.policy.guard(s)
            self._local.session = s
        return s

    def _post(self, url: str, headers: dict, body: dict, timeout: Optional[int]) -> dict:
        delay = 2.0
        for attempt in range(5):
            try:
                r = self.session.post(url, headers=headers, json=body, timeout=timeout or self.cfg.timeout)
            except requests.RequestException as e:
                if attempt == 4:
                    raise LLMError(f"{self.name}: request failed: {e}") from e
                log.warning("%s: %s, retrying in %.0fs", self.name, e, delay)
            else:
                if r.status_code < 400:
                    try:
                        return r.json()
                    except ValueError as e:
                        raise LLMError(f"{self.name}: non-JSON response: {r.text[:300]}") from e
                if r.status_code not in RETRY_STATUS or attempt == 4:
                    raise LLMError(f"{self.name}: HTTP {r.status_code}: {r.text[:500]}")
                ra = r.headers.get("retry-after")
                if ra and ra.replace(".", "", 1).isdigit():
                    delay = max(delay, float(ra))
                log.warning("%s: HTTP %s, retrying in %.0fs", self.name, r.status_code, delay)
            time.sleep(delay + random.random())
            delay = min(delay * 2, 60)
        raise LLMError(f"{self.name}: gave up")  # pragma: no cover

    def complete(self, system: str, messages: list[dict], *, max_tokens: Optional[int] = None,
                 json_output: bool = False, timeout: Optional[int] = None) -> Completion:
        raise NotImplementedError

    def models(self) -> list[str]:
        return []


def _key(cfg: LLMConfig, required: bool) -> Optional[str]:
    return secret(cfg.api_key_env, "model API key/token", required=required) if cfg.api_key_env else None


class AnthropicMessages(LLM):
    """Anthropic Messages API: api.anthropic.com, or Bridger serving Claude in Anthropic format."""

    def __init__(self, cfg: LLMConfig, base_url: str, name: str, bearer: bool):
        super().__init__(cfg)
        self.base = base_url.rstrip("/").removesuffix("/v1")
        self.name = name
        self.key = _key(cfg, required=not bearer)
        self.bearer = bearer
        if not cfg.model:
            raise ConfigError(f"{name}: set llm.model (run `sp2react doctor` to list models)")

    def _headers(self) -> dict:
        h = {"content-type": "application/json", "anthropic-version": "2023-06-01", **self.cfg.extra_headers}
        if self.key:
            h["x-api-key"] = self.key
            if self.bearer:
                h["authorization"] = f"Bearer {self.key}"
        return h

    def complete(self, system, messages, *, max_tokens=None, json_output=False, timeout=None) -> Completion:
        body = {"model": self.cfg.model, "max_tokens": max_tokens or self.cfg.max_tokens, "system": system,
                "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
                "temperature": self.cfg.temperature}
        data = self._post(f"{self.base}/v1/messages", self._headers(), body, timeout)
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        u = data.get("usage") or {}
        return Completion(text=text, model=data.get("model", self.cfg.model or ""), input_tokens=u.get("input_tokens", 0),
                          output_tokens=u.get("output_tokens", 0), truncated=data.get("stop_reason") == "max_tokens", raw=data)

    def models(self) -> list[str]:
        r = self.session.get(f"{self.base}/v1/models", headers=self._headers(), timeout=30)
        r.raise_for_status()
        return [m.get("id") for m in r.json().get("data", [])]


class OpenAIChat(LLM):
    """OpenAI-style chat completions: OpenAI, Bridger in OpenAI format, Azure OpenAI."""

    def __init__(self, cfg: LLMConfig, base_url: str, name: str, azure: bool = False, key_required: bool = True):
        super().__init__(cfg)
        self.name = name
        self.azure = azure
        self.key = _key(cfg, required=key_required)
        base = base_url.rstrip("/")
        if azure:
            if not cfg.deployment:
                raise ConfigError("azure_openai: set llm.deployment")
            self.url = f"{base}/openai/deployments/{cfg.deployment}/chat/completions?api-version={cfg.api_version}"
            self.models_url = None
        else:
            if not cfg.model:
                raise ConfigError(f"{name}: set llm.model (run `sp2react doctor` to list models)")
            root = base if base.endswith("/v1") else base + "/v1"
            self.url, self.models_url = f"{root}/chat/completions", f"{root}/models"

    def _headers(self) -> dict:
        h = {"content-type": "application/json", **self.cfg.extra_headers}
        if self.key:
            h["api-key" if self.azure else "authorization"] = self.key if self.azure else f"Bearer {self.key}"
        return h

    def complete(self, system, messages, *, max_tokens=None, json_output=False, timeout=None) -> Completion:
        body = {"messages": [{"role": "system", "content": system}] + messages,
                "max_tokens": max_tokens or self.cfg.max_tokens, "temperature": self.cfg.temperature}
        if not self.azure:
            body["model"] = self.cfg.model
        if json_output and self.cfg.json_mode:
            body["response_format"] = {"type": "json_object"}
        data = self._post(self.url, self._headers(), body, timeout)
        choice = (data.get("choices") or [{}])[0]
        u = data.get("usage") or {}
        return Completion(text=(choice.get("message") or {}).get("content") or "", model=data.get("model", self.cfg.model or ""),
                          input_tokens=u.get("prompt_tokens", 0), output_tokens=u.get("completion_tokens", 0),
                          truncated=choice.get("finish_reason") == "length", raw=data)

    def models(self) -> list[str]:
        if not self.models_url:
            return [self.cfg.deployment or ""]
        r = self.session.get(self.models_url, headers=self._headers(), timeout=30)
        r.raise_for_status()
        return [m.get("id") for m in r.json().get("data", [])]


class ScriptedLLM(LLM):
    """Deterministic stand-in for tests and dry runs: responder(agent, system, messages) -> text."""
    name = "scripted"

    def __init__(self, responder: Callable[[str, str, list[dict]], str], cfg: Optional[LLMConfig] = None):
        super().__init__(cfg or LLMConfig(provider="scripted"))
        self.responder = responder
        self.calls: list[dict] = []
        self.agent = ""

    def complete(self, system, messages, *, max_tokens=None, json_output=False, timeout=None) -> Completion:
        agent = self.agent
        for line in system.splitlines()[:3]:
            if line.startswith("<agent name=\""):
                agent = line.split('"')[1]
        self.calls.append({"agent": agent, "messages": messages})
        return Completion(text=self.responder(agent, system, messages), model="scripted")


def make_llm(cfg: LLMConfig, policy=None) -> LLM:
    llm = _make(cfg)
    llm.policy = policy
    return llm


def _make(cfg: LLMConfig) -> LLM:
    p = cfg.provider
    if p == "bridger":
        if not cfg.base_url:
            raise ConfigError("bridger: set llm.base_url to the Bridger endpoint, e.g. http://localhost:4141")
        if cfg.api_format == "anthropic":
            return AnthropicMessages(cfg, cfg.base_url, "bridger", bearer=True)
        return OpenAIChat(cfg, cfg.base_url, "bridger", key_required=False)
    if p == "anthropic":
        return AnthropicMessages(cfg, cfg.base_url or "https://api.anthropic.com", "anthropic", bearer=False)
    if p == "openai":
        return OpenAIChat(cfg, cfg.base_url or "https://api.openai.com/v1", "openai")
    if p == "azure_openai":
        if not cfg.base_url:
            raise ConfigError("azure_openai: set llm.base_url to https://<resource>.openai.azure.com")
        return OpenAIChat(cfg, cfg.base_url, "azure_openai", azure=True)
    raise ConfigError("provider 'scripted' is only for tests; construct ScriptedLLM directly")
