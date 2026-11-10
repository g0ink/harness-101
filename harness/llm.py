"""Model client: one ``chat`` call, one ``Reply``.

How this file is used
---------------------
``harness.loop`` calls ``llm.chat(messages, tools)`` once per turn and splits the
answer into two things: text, and tool-call requests. Nothing here knows about the
loop, the tools or the policy -- it is a thin, replaceable edge.

Transport is the OpenAI-compatible ``/v1/chat/completions`` shape, which LM Studio,
vLLM, llama.cpp and the hosted providers all speak. Switching backend is a
``base_url`` change.

Credentials
-----------
``LM_API_TOKEN`` comes from the environment, or from a ``.env`` file next to this
package. Never hard-code it: this directory is meant to be published.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_URL = os.environ.get("HARNESS_BASE_URL", "http://localhost:1234/v1")
MODEL = os.environ.get("HARNESS_MODEL", "qwen3-4b-thinking-2507-mlx")
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class MissingToken(RuntimeError):
    """Raised when no credential is configured, instead of letting a 401 escape."""


def _read_env_file() -> dict[str, str]:
    """Parse KEY=VALUE lines from ``.env``. Missing file is not an error."""
    if not ENV_FILE.is_file():
        return {}
    pairs: dict[str, str] = {}
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        pairs[key.strip()] = value.strip().strip("'\"")
    return pairs


def load_token() -> str:
    """Environment wins over ``.env``; absent both, fail with instructions."""
    token = os.environ.get("LM_API_TOKEN") or _read_env_file().get("LM_API_TOKEN")
    if token:
        return token
    raise MissingToken(
        "No LM Studio API token found. Pick one:\n"
        f"  1) export LM_API_TOKEN=<token>\n"
        f"  2) write LM_API_TOKEN=<token> into {ENV_FILE}\n"
        "  3) turn off 'Require Authentication' in LM Studio -> Developer -> Server Settings\n"
        "Create a token on the same page: Manage Tokens -> Create Token."
    )


@dataclass
class Usage:
    """Token accounting. Every budget decision downstream reads these numbers."""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, other: Usage) -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens


@dataclass
class Reply:
    """One model answer: either prose, or one/more tool-call requests."""

    content: str | None = None
    tool_calls: list[dict] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)

    @property
    def wants_tool(self) -> bool:
        return bool(self.tool_calls)


class ChatLLM:
    """Blocking client for an OpenAI-compatible endpoint."""

    def __init__(self, model: str = MODEL, base_url: str = BASE_URL, temperature: float = 0.0, timeout: int = 180):
        # Imported lazily so offline scripts (selftest, adversarial) need no SDK.
        from openai import OpenAI  # type: ignore[import-not-found]

        self.model = model
        self.temperature = temperature
        self.client = OpenAI(base_url=base_url, api_key=load_token(), timeout=timeout)

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> Reply:
        payload: dict = {"model": self.model, "messages": messages, "temperature": self.temperature}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        response = self.client.chat.completions.create(**payload)
        message = response.choices[0].message
        usage = response.usage
        return Reply(
            content=message.content,
            tool_calls=[call.model_dump() for call in (message.tool_calls or [])],
            usage=Usage(
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
            ),
        )


def build(model: str = MODEL) -> ChatLLM:
    """Factory used by the CLI, the eval runner and the probes."""
    return ChatLLM(model=model)
