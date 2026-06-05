from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

from core.cli_chat import CliChat


class MCPCompleter(Completer):
    def __init__(self, chat: CliChat):
        self.chat = chat

    def get_completions(self, document: Document, complete_event):
        word = document.get_word_before_cursor(WORD=True)

        if word.startswith("@"):
            prefix = word[1:]
            for doc_id in self.chat.document_ids:
                if doc_id.startswith(prefix):
                    yield Completion(
                        f"@{doc_id}",
                        start_position=-len(word),
                        display=f"@{doc_id}",
                    )
            return

        if word.startswith("/"):
            prefix = word[1:]
            for command in self.chat.get_slash_commands():
                if command.startswith(prefix):
                    yield Completion(
                        f"/{command}",
                        start_position=-len(word),
                        display=f"/{command}",
                    )
            return

        if document.text_before_cursor == "@":
            for doc_id in self.chat.document_ids:
                yield Completion(
                    f"@{doc_id}",
                    start_position=-1,
                    display=f"@{doc_id}",
                )
            return

        if document.text_before_cursor == "/":
            for command in self.chat.get_slash_commands():
                yield Completion(
                    f"/{command}",
                    start_position=-1,
                    display=f"/{command}",
                )


class CliApp:
    def __init__(self, chat: CliChat):
        self.chat = chat
        self.session: PromptSession | None = None

    async def initialize(self):
        await self.chat.initialize()
        self.session = PromptSession(
            completer=MCPCompleter(self.chat),
            complete_while_typing=True,
        )

    async def run(self):
        assert self.session is not None, "CLI session must be initialized first."

        print("MCP Chat for OpenAI Codex")
        print("Type /help for commands. Use @document_id to inline a document.")

        while True:
            try:
                user_input = await self.session.prompt_async("> ")
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye.")
                return

            response = await self.chat.handle_input(user_input)
            if response is None:
                print("Goodbye.")
                return
            if response:
                print(response)
