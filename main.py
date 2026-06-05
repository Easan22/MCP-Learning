import asyncio
import sys
import os
from dotenv import load_dotenv
from contextlib import AsyncExitStack

from mcp_client import MCPClient
from core.openai_service import OpenAIChatService
from core.cli_chat import CliChat
from core.cli import CliApp

load_dotenv()

# OpenAI Config
openai_model = os.getenv("OPENAI_MODEL", "")
openai_api_key = os.getenv("OPENAI_API_KEY", "")
reasoning_effort = os.getenv("OPENAI_REASONING_EFFORT", "").strip() or None


assert openai_model, "Error: OPENAI_MODEL cannot be empty. Update .env"
assert openai_api_key, (
    "Error: OPENAI_API_KEY cannot be empty. Update .env"
)


async def main():
    openai_service = OpenAIChatService(
        model=openai_model,
        api_key=openai_api_key,
        reasoning_effort=reasoning_effort,
    )

    server_scripts = sys.argv[1:]
    clients = {}

    command, args = (
        ("uv", ["run", "mcp_server.py"])
        if os.getenv("USE_UV", "0") == "1"
        else ("python", ["mcp_server.py"])
    )

    async with AsyncExitStack() as stack:
        doc_client = await stack.enter_async_context(
            MCPClient(command=command, args=args)
        )
        clients["doc_client"] = doc_client

        for i, server_script in enumerate(server_scripts):
            client_id = f"client_{i}_{server_script}"
            extra_command, extra_args = (
                ("uv", ["run", server_script])
                if os.getenv("USE_UV", "0") == "1"
                else ("python", [server_script])
            )
            client = await stack.enter_async_context(
                MCPClient(command=extra_command, args=extra_args)
            )
            clients[client_id] = client

        chat = CliChat(
            doc_client=doc_client,
            clients=clients,
            openai_service=openai_service,
        )

        cli = CliApp(chat)
        await cli.initialize()
        await cli.run()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
