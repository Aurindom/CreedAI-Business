"""Calls Claude directly through the Claude API, for testing with an Anthropic key."""

import os
from typing import Any

import anthropic

DEFAULT_MODEL = "claude-haiku-5-5"
MAX_OUTPUT_TOKENS = 2000
TIMEOUT_SECONDS = 25
ERRORS: tuple[type[Exception], ...] = (anthropic.APIStatusError, anthropic.APIConnectionError)


def tools_for_claude(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": action["function"]["name"],
            "description": action["function"]["description"],
            "input_schema": action["function"]["parameters"],
        }
        for action in actions
    ]


class ClaudeConversation:
    """Keeps Claude's own content blocks between steps, as the API expects."""

    def __init__(self, system: str, history: list[dict[str, str]], message: str, actions: list[dict[str, Any]], client: Any = None):
        self.system = system
        self.tools = tools_for_claude(actions)
        self.messages: list[dict[str, Any]] = [*history, {"role": "user", "content": message}]
        self.client = client or anthropic.AsyncAnthropic(max_retries=1, timeout=TIMEOUT_SECONDS)
        self.last_content: Any = None

    async def ask(self) -> dict[str, Any]:
        response = await self.client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL),
            max_tokens=MAX_OUTPUT_TOKENS,
            system=self.system,
            tools=self.tools,
            messages=self.messages,
            output_config={"effort": "low"},
        )
        self.last_content = response.content
        usage = {"prompt_tokens": response.usage.input_tokens, "completion_tokens": response.usage.output_tokens}
        if response.stop_reason in ("refusal", "max_tokens"):
            return {"text": "", "calls": [], "usage": usage}
        calls = [
            {"id": block.id, "name": block.name, "arguments": block.input if isinstance(block.input, dict) else {}}
            for block in response.content
            if block.type == "tool_use"
        ]
        text = "".join(block.text for block in response.content if block.type == "text")
        return {"text": text, "calls": calls, "usage": usage}

    def add_results(self, results: list[tuple[str, str]]) -> None:
        self.messages.append({"role": "assistant", "content": self.last_content})
        self.messages.append({
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": call_id, "content": text} for call_id, text in results],
        })
