import json
import re
import shlex
from typing import Any

from mcp import types

from core.debug import debug_log
from core.openai_service import OpenAIChatService
from mcp_client import MCPClient


SYSTEM_PROMPT = """You are a terminal-based coding and document assistant powered by OpenAI Codex.

Use MCP tools when they help answer the user accurately. Do not modify documents unless the user explicitly asks or the MCP prompt instructs you to do so.
When document contents are provided inline, use them directly instead of asking the user to re-paste them.
"""


PROMPT_COMMAND_INSTRUCTIONS = """You are executing an MCP prompt command.

Follow the prompt exactly, use tools when helpful, and return a concise final result for the terminal.
"""


class CliChat:
    def __init__(
        self,
        doc_client: MCPClient,
        clients: dict[str, MCPClient],
        openai_service: OpenAIChatService,
    ):
        self.doc_client = doc_client
        self.clients = clients
        self.openai_service = openai_service
        self.history: list[tuple[str, str]] = []
        self.document_ids: list[str] = []
        self.prompt_names: list[str] = []
        self.tool_names: list[str] = []
        self._openai_tools: list[dict[str, Any]] = []
        self._documents_dirty = False

    async def initialize(self):
        await self.refresh_capabilities()

    async def refresh_capabilities(self):
        docs = await self.doc_client.read_resource("docs://documents")
        prompts = await self.doc_client.list_prompts()
        tools = await self.doc_client.list_tools()

        self.document_ids = sorted(docs or [])
        self.prompt_names = sorted(prompt.name for prompt in prompts)
        self.tool_names = sorted(tool.name for tool in tools)
        self._openai_tools = self.openai_service.mcp_tools_to_openai(tools)
        debug_log(
            "Refreshed MCP capabilities",
            {
                "documents": self.document_ids,
                "prompts": self.prompt_names,
                "tools": self.tool_names,
            },
        )

    async def handle_input(self, text: str) -> str | None:
        text = text.strip()
        if not text:
            return ""

        if text.startswith("/"):
            debug_log("Handling slash command", text)
            return await self._handle_command(text[1:])

        expanded = await self._expand_document_mentions(text)
        debug_log(
            "Handling chat input",
            {
                "original_text": text,
                "expanded_text": expanded,
            },
        )
        response, used_tools = await self.openai_service.respond(
            user_text=expanded,
            history=self.history,
            instructions=SYSTEM_PROMPT,
            tools=self._openai_tools,
            tool_executor=self._call_tool,
        )
        self.history.append(("user", text))
        self.history.append(("assistant", response))

        if used_tools and self._documents_dirty:
            await self.refresh_capabilities()
            self._documents_dirty = False

        return response

    def get_slash_commands(self) -> list[str]:
        builtins = ["docs", "help", "prompts", "quit", "refresh", "tools"]
        return sorted(set(builtins + self.prompt_names))

    async def _handle_command(self, raw_command: str) -> str | None:
        try:
            parts = shlex.split(raw_command)
        except ValueError as exc:
            return f"Could not parse command: {exc}"

        if not parts:
            return ""

        command = parts[0]
        args = parts[1:]

        if command == "quit":
            return None
        if command == "help":
            return self._help_text()
        if command == "docs":
            return "\n".join(self.document_ids)
        if command == "prompts":
            return "\n".join(self.prompt_names)
        if command == "tools":
            return "\n".join(self.tool_names)
        if command == "refresh":
            await self.refresh_capabilities()
            return "Refreshed document, prompt, and tool metadata."

        if command in self.prompt_names:
            if len(args) != 1:
                return f"Usage: /{command} <doc_id>"

            doc_id = args[0]
            prompt_messages = await self.doc_client.get_prompt(
                command, {"doc_id": doc_id}
            )
            prompt_text = self._prompt_messages_to_text(prompt_messages)
            response, used_tools = await self.openai_service.respond(
                user_text=prompt_text,
                instructions=PROMPT_COMMAND_INSTRUCTIONS,
                tools=self._openai_tools,
                tool_executor=self._call_tool,
            )
            if used_tools and self._documents_dirty:
                await self.refresh_capabilities()
                self._documents_dirty = False
            return response

        return (
            f"Unknown command: /{command}\n"
            f"Use /help to see available commands."
        )

    async def _expand_document_mentions(self, text: str) -> str:
        mentions = sorted(set(re.findall(r"@([A-Za-z0-9_.-]+)", text)))
        if not mentions:
            return text

        sections = [text]
        for doc_id in mentions:
            if doc_id not in self.document_ids:
                continue

            contents = await self.doc_client.read_resource(
                f"docs://documents/{doc_id}"
            )
            debug_log(
                f"Expanded @{doc_id} from MCP resource",
                contents,
            )
            sections.append(
                f"\n\n<Document id=\"{doc_id}\">\n{contents}\n</Document>"
            )

        return "".join(sections)

    async def _call_tool(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        result = await self.doc_client.call_tool(tool_name, tool_input)
        if tool_name == "edit_document":
            self._documents_dirty = True

        if result is None:
            return "success"

        content = getattr(result, "content", None)
        if not content:
            structured = (
                getattr(result, "structuredContent", None)
                or getattr(result, "structured_content", None)
            )
            if structured is not None:
                return json.dumps(structured)
            return "success"

        parts = []
        for item in content:
            if isinstance(item, types.TextContent) or hasattr(item, "text"):
                parts.append(item.text)
                continue

            if hasattr(item, "model_dump"):
                parts.append(json.dumps(item.model_dump(exclude_none=True)))
            else:
                parts.append(str(item))

        return "\n".join(parts) if parts else "success"

    def _prompt_messages_to_text(self, messages: list[Any]) -> str:
        chunks = []
        for message in messages:
            role = getattr(message, "role", "user")
            content = getattr(message, "content", "")
            if isinstance(content, list):
                text = "\n".join(
                    part.text
                    for part in content
                    if hasattr(part, "text") and part.text
                )
            else:
                text = str(content)

            chunks.append(f"{role.upper()}:\n{text}")

        return "\n\n".join(chunks)

    def _help_text(self) -> str:
        return (
            "Commands:\n"
            "/help - show this message\n"
            "/docs - list available document ids\n"
            "/prompts - list available MCP prompts\n"
            "/tools - list available MCP tools\n"
            "/refresh - reload MCP metadata\n"
            "/quit - exit the app\n"
            "\n"
            "Prompt commands:\n"
            + "\n".join(f"/{name} <doc_id>" for name in self.prompt_names)
            + "\n\n"
            "Document mentions:\n"
            "Type @document_id in normal chat to inline that resource before the model call."
        )
