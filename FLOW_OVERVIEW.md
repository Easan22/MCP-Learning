# MCP Chat Flow Overview

This document explains, in detail, how this repository works when a user types a query into the terminal.

It is written for two audiences:

- someone trying to understand this exact repository
- someone trying to learn the architecture of a terminal app that combines an LLM with MCP

The repository is small, but it contains the core patterns that show up in larger agent-style apps:

- local terminal input
- an MCP server running as a subprocess
- an MCP client session over `stdio`
- a chat loop
- optional local input preprocessing
- OpenAI Responses API calls
- structured tool calling
- looping tool results back into the model

## High-Level Architecture

There are four main parts:

1. The terminal app
2. The MCP client
3. The MCP server
4. The OpenAI chat service

The files are:

- `main.py`
- `core/cli.py`
- `core/cli_chat.py`
- `mcp_client.py`
- `mcp_server.py`
- `core/openai_service.py`
- `core/debug.py`

At runtime, the data flow is:

1. `main.py` loads configuration from `.env`
2. `main.py` starts the MCP server as a subprocess
3. `mcp_client.py` opens an MCP `ClientSession` over the server's `stdio`
4. `core/cli.py` starts an interactive prompt-toolkit terminal session
5. `core/cli_chat.py` loads MCP capabilities up front
6. user enters a query
7. the query is either:
   - handled as a slash command
   - expanded locally if it contains `@document`
   - sent to OpenAI as normal chat
8. if the model requests a tool call, the app calls the MCP server through `mcp_client.py`
9. the tool result is fed back into the model
10. the final answer is printed in the terminal

## Startup Flow

### 1. Configuration is loaded

`main.py` begins by loading environment variables with `load_dotenv()`.

It then reads:

- `OPENAI_MODEL`
- `OPENAI_API_KEY`
- `OPENAI_REASONING_EFFORT`
- `USE_UV`

These values affect:

- which OpenAI model is used
- how the OpenAI client authenticates
- whether reasoning effort is requested
- whether the MCP server subprocess is launched with `uv` or `python`

### 2. The OpenAI service is created

`main.py` creates an `OpenAIChatService` instance from `core/openai_service.py`.

This service is responsible for:

- assembling Responses API payloads
- sending requests to OpenAI
- detecting structured tool calls
- looping tool outputs back into the model

### 3. The MCP server command is chosen

`main.py` chooses one of these subprocess commands:

- `uv run mcp_server.py`
- `python mcp_server.py`

This matters because the server is not an HTTP service. It is a local process using `stdio` transport.

### 4. The MCP client is created and connected

`main.py` enters an `AsyncExitStack` and creates an `MCPClient`.

`MCPClient.connect()` in `mcp_client.py` does the important setup:

1. build `StdioServerParameters`
2. start the subprocess transport with `stdio_client(server_params)`
3. wrap the streams in an MCP `ClientSession`
4. call `initialize()`

At that point, the app has an active MCP connection to the subprocess server.

### 5. The chat and terminal app are created

`main.py` creates:

- `CliChat` from `core/cli_chat.py`
- `CliApp` from `core/cli.py`

`CliApp.initialize()` then calls `CliChat.initialize()`, which triggers capability loading before the user types anything.

## What Happens Before Any Query

This is one of the most important parts of the app.

Before the user sends a message, `CliChat.initialize()` calls `refresh_capabilities()`.

That method does three MCP requests immediately:

1. `read_resource("docs://documents")`
2. `list_prompts()`
3. `list_tools()`

This means the app learns, up front:

- which document IDs exist
- which prompt names exist
- which tools exist

### Why the tool list is called before any query

The tool list is needed before normal chat starts because OpenAI tool calling requires the app to send the available tool schema with the model request.

If the tool list were not loaded first, the model would not know:

- that `read_doc_contents` exists
- that `edit_document` exists
- what arguments they accept

So the app retrieves the tool definitions once at startup and stores them in memory.

### Where the capability data is stored

`CliChat.refresh_capabilities()` stores the results in these instance variables:

- `self.document_ids`
- `self.prompt_names`
- `self.tool_names`
- `self._openai_tools`

The first three are human-facing convenience lists.

`self._openai_tools` is especially important. It contains the MCP tools converted into OpenAI function-tool format by:

- `OpenAIChatService.mcp_tools_to_openai()`

That means the app stores the model-ready tool schema in memory before the first user message.

### Why the app keeps both raw-ish and converted capability views

There are two separate needs:

1. UI and local app logic need names
2. the model needs tool schemas

So the app stores:

- document IDs for `@` completion and validation
- prompt names for `/` completion and dispatch
- tool names for `/tools` display
- fully converted OpenAI tool definitions for Responses API calls

## MCP Server Responsibilities

`mcp_server.py` defines the local server's capabilities.

Those capabilities are grouped into three MCP categories.

### 1. Tools

The server exposes:

- `read_doc_contents`
- `edit_document`

These are actions the model can call through the client when tool calling is enabled.

### 2. Resources

The server exposes:

- `docs://documents`
- `docs://documents/{doc_id}`

Resources are used by the local app for capability lookup and document expansion.

In this repo, the document list comes from the `docs://documents` resource, and a specific document body comes from `docs://documents/{doc_id}`.

### 3. Prompts

The server exposes:

- `format`
- `summarize`

These are MCP prompts, not ordinary shell commands. The local app can fetch them and then send the resulting text to OpenAI.

## Terminal Session Flow

The interactive terminal session lives in `core/cli.py`.

`CliApp.initialize()` creates a `PromptSession` with a custom completer:

- `MCPCompleter`

This enables completion behavior for `@` and `/`.

`CliApp.run()` is the main loop:

1. wait for user input with `prompt_async("> ")`
2. pass the line to `CliChat.handle_input()`
3. print the returned response
4. continue until EOF, Ctrl+C, or `/quit`

So the terminal is just the outer shell. The real routing logic happens in `CliChat`.

## Query Routing in `CliChat`

Every user line goes through `CliChat.handle_input(text)`.

This method makes the first major branching decision:

- if the text starts with `/`, treat it as a slash command
- otherwise, treat it as normal chat

That split is important because slash commands are handled locally first, while normal chat goes through the OpenAI tool-calling loop.

## Slash Command Flow

If the input starts with `/`, `CliChat._handle_command()` takes over.

There are two categories of slash commands.

### 1. Built-in commands

These are handled entirely by local Python code:

- `/help`
- `/docs`
- `/prompts`
- `/tools`
- `/refresh`
- `/quit`

Examples:

- `/docs` returns the contents of `self.document_ids`
- `/prompts` returns `self.prompt_names`
- `/refresh` reruns capability discovery from MCP

No OpenAI call is needed for these commands.

### 2. MCP prompt commands

If the command name matches a prompt name from the server, for example:

- `/summarize report.pdf`
- `/format plan.md`

then the flow is:

1. parse the command name and argument
2. call `self.doc_client.get_prompt(command, {"doc_id": doc_id})`
3. receive the MCP prompt messages
4. flatten them into plain text with `_prompt_messages_to_text()`
5. send that text to OpenAI with `OpenAIChatService.respond()`

This is a subtle but important point:

- the slash command does not directly execute the prompt by itself
- it asks the MCP server for the prompt content
- then the app forwards that prompt content to OpenAI

So MCP prompts act like reusable instruction templates owned by the server.

## `@` Mention Flow

If the user types normal chat and includes `@document_id`, the app handles that locally before OpenAI sees the final message.

Example:

```text
Tell me more about @outlook.pdf
```

The flow is:

1. `handle_input()` sees that the line does not start with `/`
2. it calls `_expand_document_mentions(text)`
3. regex finds the mention, for example `outlook.pdf`
4. the app checks whether the doc ID is in `self.document_ids`
5. if valid, it calls:
   - `read_resource("docs://documents/outlook.pdf")`
6. it appends the document contents to the message in this shape:

```text
<Document id="outlook.pdf">
This document presents the projected future performance of the system.
</Document>
```

The expanded message is then sent to OpenAI.

### Why `@` is local preprocessing instead of an MCP tool call

This is a design decision.

The app wants `@` to feel like "attach this document to my prompt."

So instead of hoping the model decides to call a tool, the app does the retrieval itself before the model request.

That has a few effects:

- it is deterministic
- it keeps the user experience simple
- it does not require the model to infer that a document should be fetched

This is a common app pattern:

- user-facing "attachment-like" affordances are often resolved locally
- model-driven tool usage is reserved for actions the model decides to take

## Autocomplete Flow for `@` and `/`

Autocomplete is handled by `MCPCompleter` in `core/cli.py`.

### `@` completion

If the current token starts with `@`, the completer checks `self.chat.document_ids` and yields matching completions.

That list came from the MCP resource `docs://documents` during capability loading.

So the flow is:

1. startup calls `read_resource("docs://documents")`
2. IDs are stored in `self.document_ids`
3. completer reads that list
4. terminal shows completions

### `/` completion

If the current token starts with `/`, the completer checks `self.chat.get_slash_commands()`.

That merges:

- built-in commands
- prompt names discovered from MCP

So the user sees both local command names and server-defined prompt names in one command palette.

## Normal Chat Flow Without `@` or `/`

If the user enters plain chat like:

```text
read report.pdf and tell me what it is about
```

the flow is:

1. `handle_input()` receives the text
2. it is not a slash command
3. `_expand_document_mentions()` finds no `@` tokens
4. the original text is passed to `OpenAIChatService.respond()`
5. the app includes prior chat history
6. the app includes the precomputed tool list
7. OpenAI decides whether to answer directly or call a tool

This is where OpenAI tool calling and MCP start to work together.

## How the OpenAI Request Is Shaped

`OpenAIChatService.respond()` builds the Responses API request in two stages:

1. build `input_items`
2. assemble the final payload

### Stage 1: build conversation input

`_build_input_items()` creates the `input` array.

It uses these rules:

- prior user messages become:
  - `{"role": "user", "content": [{"type": "input_text", "text": "..."}]}`
- prior assistant messages become:
  - `{"role": "assistant", "content": [{"type": "output_text", "text": "..."}]}`
- current user message becomes:
  - `{"role": "user", "content": [{"type": "input_text", "text": "..."}]}`

This gives OpenAI the conversation state in the format expected by the Responses API.

### Stage 2: assemble the full payload

The final payload may contain:

- `model`
- `input`
- `instructions`
- `tools`
- `reasoning`

In this repo:

- `model` comes from `.env`
- `instructions` usually come from `SYSTEM_PROMPT`
- `tools` come from the precomputed `self._openai_tools`
- `reasoning` is added only if configured

## How Tool Schemas Are Produced

The app does not hardcode the OpenAI tool definitions manually.

Instead, it derives them from MCP tool metadata.

Flow:

1. `mcp_client.list_tools()` asks the server for its MCP tools
2. each MCP tool includes:
   - name
   - description
   - input schema
3. `OpenAIChatService.mcp_tools_to_openai()` converts each one into OpenAI function-tool format

That means MCP is the source of truth for what tools exist.

The OpenAI tool list is a translated view of the MCP tool list.

This is a very important architecture lesson:

- MCP defines tools in a provider-neutral way
- the app translates them into the shape needed by the chosen LLM API

## Why the Model Returns Structured Output When Needed

The model does not need to return JSON for ordinary answers.

It only needs structured output when using tools.

That structure is encouraged by the fact that the app sends the tool definitions in the Responses API payload.

Once the tools are present, the model can return `function_call` items in `response.output`.

This repo then explicitly checks for:

- `item.type == "function_call"`

When that happens, the app expects structured arguments and parses them with:

- `_load_arguments()`

So the structured behavior is not coming only from prompt instructions. It comes from:

- OpenAI tool-calling support
- tool schema in the payload
- app logic that branches on `function_call`

## Tool Call Execution Flow

Now take the example:

```text
read report.pdf and tell me what it is about
```

The model may decide to call `read_doc_contents`.

If it does, the flow is:

1. OpenAI returns a `function_call` item
2. `respond()` detects it
3. `_load_arguments()` parses the arguments string into a Python dict
4. `respond()` calls the injected `tool_executor`
5. in this repo, that executor is `CliChat._call_tool()`
6. `_call_tool()` calls `self.doc_client.call_tool(tool_name, tool_input)`
7. the MCP client sends the tool request to the MCP server
8. the server runs the decorated Python tool function
9. the result comes back through MCP
10. the app converts that result into a string for the model
11. `respond()` appends a `function_call_output` item to the input
12. `respond()` makes another Responses API call
13. now the model has the tool output and can answer normally

This two-step pattern is the heart of tool-based agents.

## How MCP Tool Results Are Shaped

The app has to bridge between MCP result objects and OpenAI tool-result input items.

That happens in `CliChat._call_tool()`.

The method:

1. calls the MCP tool
2. inspects `result.content`
3. extracts any text content
4. falls back to structured content serialization when necessary
5. returns a plain string result to `OpenAIChatService.respond()`

Then `respond()` wraps it in this shape:

```python
{
    "type": "function_call_output",
    "call_id": tool_call.call_id,
    "output": result,
}
```

So there are two translations happening:

1. MCP tool metadata -> OpenAI tool schema
2. MCP tool result -> OpenAI `function_call_output`

This is where the app acts as the adapter between the two systems.

## Conversation History Storage

After a normal chat answer is produced, `CliChat.handle_input()` appends to:

- `self.history`

The history is stored as:

- `(role, text)` tuples

Specifically:

- `("user", original_text)`
- `("assistant", response)`

That history is then re-encoded into Responses API input items on the next turn.

This is how the terminal session becomes a multi-turn chat instead of isolated one-off requests.

## What Happens After Document Editing

If a tool call uses `edit_document`, the app marks:

- `self._documents_dirty = True`

After the response completes, `handle_input()` and slash-prompt execution both check this flag.

If documents were changed, the app reruns `refresh_capabilities()`.

That keeps the app's cached capability data synchronized after edits.

In this repo, the document IDs themselves do not change, but the pattern is still useful:

- tool actions may change the local knowledge the UI depends on
- caches should be refreshed when that happens

## How Debugging Works

`core/debug.py` provides opt-in logging controlled by:

- `MCP_CHAT_DEBUG`

If enabled, the app prints:

- when the MCP server process starts
- when resources, prompts, and tools are requested
- how chat input was expanded
- the Responses API payload shape
- the model output items
- tool call arguments
- tool results

This is useful because it lets you see:

- what the app did locally
- what was sent to OpenAI
- what came back from OpenAI
- what was sent through MCP

That makes the boundaries between app logic, MCP, and LLM behavior much easier to understand.

## End-to-End Summary of the Main Paths

### Path A: plain chat

Example:

```text
What documents do I have?
```

Flow:

1. terminal receives text
2. not a slash command
3. no `@` expansion
4. send text + history + tools to OpenAI
5. model either answers directly or calls a tool
6. final response printed

### Path B: chat with `@`

Example:

```text
Tell me more about @outlook.pdf
```

Flow:

1. terminal receives text
2. not a slash command
3. local app expands `@outlook.pdf` using MCP resource read
4. expanded text sent to OpenAI
5. model answers with the attached content available

### Path C: built-in slash command

Example:

```text
/docs
```

Flow:

1. terminal receives text
2. slash command branch
3. local command handler returns cached document IDs
4. no OpenAI call needed

### Path D: MCP prompt slash command

Example:

```text
/summarize report.pdf
```

Flow:

1. terminal receives text
2. slash command branch
3. app fetches MCP prompt definition
4. prompt text is sent to OpenAI
5. model may call tools
6. final response printed

## How to Think About Building an App Like This

The cleanest mental model is:

- MCP server = capability provider
- MCP client = transport and invocation layer
- local app = orchestration layer
- LLM API = reasoning and language layer

More concretely:

- the server owns tools, resources, and prompts
- the client connects to the server and exposes those capabilities to the app
- the app decides what happens before the LLM call and after the LLM call
- the LLM decides whether to answer directly or use a provided tool

This split is powerful because it keeps responsibilities separate:

- MCP defines what can be done
- the app defines when and how to expose it
- the model defines when to use it

## Design Lessons From This Repo

There are a few important patterns worth carrying into more complex apps.

### 1. Preload capability metadata

Load tool lists, resource lists, and prompt names before the user needs them.

This enables:

- autocomplete
- validation
- proper tool schema injection

### 2. Separate local preprocessing from model-driven actions

`@document` is handled locally.

Tool calls are model-driven.

That split makes the UX more predictable.

### 3. Treat MCP as the source of truth

The app does not manually define separate copies of the server's capabilities.

Instead, it asks the MCP server what exists and translates that into the shapes the terminal app and OpenAI need.

### 4. Use the app as the adapter between MCP and the LLM provider

MCP and OpenAI do not directly speak the exact same payload format.

The local app bridges:

- tool schemas
- tool results
- chat history formatting
- prompt expansion

### 5. Make debugging visible

Agent-style apps become much easier to learn when you can see:

- capability discovery
- outgoing payloads
- tool calls
- tool outputs

That is why this repo now includes opt-in debug logging.

## Final Mental Model

If you only remember one thing, remember this:

When a user types into the terminal, this app is not "just sending a string to a model."

It is doing orchestration.

It may:

- inspect the text locally
- expand `@` mentions using MCP resources
- interpret `/` commands locally
- fetch MCP prompt templates
- send tool schemas to OpenAI
- receive structured tool calls from the model
- invoke MCP tools
- return tool outputs back to the model
- then finally print a natural-language answer

That orchestration layer is what turns a plain chat app into an MCP-enabled agentic application.
