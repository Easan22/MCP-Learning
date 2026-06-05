import asyncio
import json
from typing import Any, Awaitable, Callable

from openai import OpenAI

from core.debug import debug_log


ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[str]]


class OpenAIChatService:
    def __init__(
        self,
        model: str,
        api_key: str,
        reasoning_effort: str | None = None,
    ):
        self.model = model
        self.reasoning_effort = reasoning_effort
        self._client = OpenAI(api_key=api_key)

    async def respond(
        self,
        *,
        user_text: str,
        history: list[tuple[str, str]] | None = None,
        instructions: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> tuple[str, bool]:
        input_items = self._build_input_items(history or [], user_text)
        used_tools = False

        while True:
            debug_log(
                "Sending Responses API request",
                self._build_debug_payload(
                    input_items=input_items,
                    instructions=instructions,
                    tools=tools or [],
                ),
            )
            response = await asyncio.to_thread(
                self._create_response,
                input_items,
                instructions,
                tools or [],
            )
            debug_log(
                "Received Responses API output",
                self._serialize_output_items(getattr(response, "output", [])),
            )

            function_calls = [
                item
                for item in getattr(response, "output", [])
                if getattr(item, "type", None) == "function_call"
            ]
            if not function_calls:
                return response.output_text, used_tools

            if tool_executor is None:
                raise RuntimeError(
                    "The model requested a tool call, but no tool executor was configured."
                )

            used_tools = True
            input_items.extend(self._serialize_output_items(response.output))

            for tool_call in function_calls:
                arguments = self._load_arguments(tool_call.arguments)
                debug_log(
                    f"Model requested tool `{tool_call.name}`",
                    arguments,
                )
                result = await tool_executor(tool_call.name, arguments)
                debug_log(
                    f"Tool `{tool_call.name}` returned",
                    result,
                )
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": tool_call.call_id,
                        "output": result,
                    }
                )

    def mcp_tools_to_openai(self, tools: list[Any]) -> list[dict[str, Any]]:
        openai_tools = []

        for tool in tools:
            input_schema = (
                getattr(tool, "inputSchema", None)
                or getattr(tool, "input_schema", None)
                or {
                    "type": "object",
                    "properties": {},
                }
            )
            openai_tools.append(
                {
                    "type": "function",
                    "name": getattr(tool, "name"),
                    "description": getattr(tool, "description", "") or "",
                    "parameters": input_schema,
                }
            )

        return openai_tools

    def _create_response(
        self,
        input_items: list[dict[str, Any]],
        instructions: str | None,
        tools: list[dict[str, Any]],
    ):
        payload: dict[str, Any] = {
            "model": self.model,
            "input": input_items,
        }
        if instructions:
            payload["instructions"] = instructions
        if tools:
            payload["tools"] = tools
        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}

        return self._client.responses.create(**payload)

    def _build_input_items(
        self,
        history: list[tuple[str, str]],
        user_text: str,
    ) -> list[dict[str, Any]]:
        input_items = []

        for role, text in history:
            content_type = (
                "output_text" if role == "assistant" else "input_text"
            )
            input_items.append(
                {
                    "role": role,
                    "content": [{"type": content_type, "text": text}],
                }
            )

        input_items.append(
            {
                "role": "user",
                "content": [{"type": "input_text", "text": user_text}],
            }
        )
        return input_items

    def _serialize_output_items(
        self, output_items: list[Any]
    ) -> list[dict[str, Any]]:
        serialized = []

        for item in output_items:
            if hasattr(item, "model_dump"):
                serialized.append(item.model_dump(exclude_none=True))
            elif isinstance(item, dict):
                serialized.append(item)

        return serialized

    def _load_arguments(self, arguments: str) -> dict[str, Any]:
        if not arguments:
            return {}

        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return {"raw_arguments": arguments}

        return parsed if isinstance(parsed, dict) else {"value": parsed}

    def _build_debug_payload(
        self,
        *,
        input_items: list[dict[str, Any]],
        instructions: str | None,
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": input_items,
        }
        if instructions:
            payload["instructions"] = instructions
        if tools:
            payload["tools"] = tools
        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}

        return payload
