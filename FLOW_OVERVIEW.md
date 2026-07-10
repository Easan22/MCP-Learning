# MCP Chat Flow Overview

This file is a compact reference for how this repo works and how to think about MCP in practice.

## Big Picture

This repo is a terminal app that connects:

- a local MCP server
- a local MCP client
- an OpenAI model
- a CLI chat loop

The clean mental model is:

- `mcp_server.py` defines capabilities
- `mcp_client.py` connects to the server and invokes those capabilities
- `core/cli_chat.py` orchestrates the app flow
- `core/openai_service.py` talks to OpenAI and runs the tool loop
- `main.py` wires everything together

## How The Server Is "Hosted"

The server is not hosted over HTTP.

It is started as a local subprocess by `main.py`:

- `uv run mcp_server.py`
- or `python mcp_server.py`

Inside `mcp_server.py`, this line starts the MCP server:

```python
mcp.run(transport="stdio")
```

That means:

- the server reads MCP requests from `stdin`
- the server writes MCP responses to `stdout`
- the client talks to it over `stdio`

So this is a local process-to-process connection, not a web server.

## What The Server Exposes

`mcp_server.py` exposes three kinds of MCP capabilities.

### Tools

Registered with `@mcp.tool(...)`.

In this repo:

- `read_doc_contents`
- `edit_document`

Tools are actions the model can call.

### Resources

Registered with `@mcp.resource(...)`.

In this repo:

- `docs://documents`
- `docs://documents/{doc_id}`

Resources are things the app can read directly.

### Prompts

Registered with `@mcp.prompt(...)`.

In this repo:

- `format`
- `summarize`

Prompts are reusable instruction templates served by the MCP server.

## How Tools Get Exposed To The Model

At startup, `CliChat.refresh_capabilities()` loads:

- document ids
- prompt metadata
- tool metadata

The MCP tool list comes from `mcp_client.py -> list_tools()`.

Then `OpenAIChatService.mcp_tools_to_openai()` converts each MCP tool into OpenAI tool format:

- `name`
- `description`
- `parameters` (JSON schema)

That converted list is stored in `self._openai_tools` and sent to OpenAI on chat requests.

So MCP is the source of truth, and the app translates MCP metadata into the schema the model sees.

## What Tool Descriptions And Field Descriptions Do

There are two different layers of description:

### Tool description

Example:

```python
@mcp.tool(
    name="read_doc_contents",
    description="Read the contents of a document and return it as a string.",
)
```

This mainly helps the model decide when a tool is useful.

### Field description

Example:

```python
doc_id: str = Field(description="Id of the document to read")
```

This becomes part of the parameter schema and helps the model build valid arguments.

Short version:

- tool description helps with tool selection
- field descriptions help with argument construction

## What Happens If The Model Does Not Have Enough Details

The schema does not give the model missing facts. It only tells the model what inputs are required.

If the model wants to use a tool but is missing arguments, it can:

- ask the user for clarification
- use another tool first to gather context
- avoid the tool and answer directly if possible

Example:

- `edit_document` needs `doc_id`, `old_str`, and `new_str`
- if the model does not know the exact current text, it should first call `read_doc_contents`
- after reading the document, it has enough detail to call `edit_document`

So the model uses the schema to realize what it still needs.

## How The MCP Client Works

`mcp_client.py` is a thin wrapper around an MCP `ClientSession`.

Its responsibilities are:

- start the MCP server subprocess
- open a `stdio` transport
- initialize the MCP session
- provide convenience methods like:
  - `list_tools()`
  - `call_tool()`
  - `list_prompts()`
  - `get_prompt()`
  - `read_resource()`

The setup flow is:

1. build `StdioServerParameters`
2. call `stdio_client(server_params)`
3. get read/write streams
4. wrap them in `ClientSession`
5. call `initialize()`

After that, the app can make MCP requests over the session.

## How The Rest Of The Repo Uses The MCP Client

`main.py` creates the `MCPClient` and passes it into `CliChat`.

Then `CliChat` uses it in three main ways:

- `read_resource("docs://documents")` to load document ids
- `get_prompt(...)` for slash prompt commands like `/format report.pdf`
- `call_tool(...)` when the model requests a tool

So:

- `MCPClient` handles protocol communication
- `CliChat` decides when to use it

## How The Model Is Prompted In This Repo

OpenAI requests are built in `core/openai_service.py`.

Each request can include:

- `model`
- `input`
- `instructions`
- `tools`
- optional `reasoning`

For normal chat, `CliChat` sends:

- `SYSTEM_PROMPT` as `instructions`
- the user message as `input`
- the converted tool schemas as `tools`

For MCP slash prompt commands like `/format report.pdf`, `CliChat` sends:

- `PROMPT_COMMAND_INSTRUCTIONS` as `instructions`
- the rendered MCP prompt text as `input`
- the converted tool schemas as `tools`

So the model is guided by both:

- high-level app instructions
- the current user task or MCP prompt text

## How The Tool Loop Works

The tool loop lives in `OpenAIChatService.respond()`.

It works like this:

1. build `input_items` from history plus the current user text
2. send a Responses API request
3. check whether the model returned any `function_call` items
4. if not, return the final text answer
5. if yes:
   - append the model's output items to `input_items`
   - execute each requested tool
   - append a `function_call_output` item for each tool result
   - send another Responses API request
6. repeat until the model returns normal text instead of another tool call

This is why the model can keep the original goal in mind: the original request stays in the growing `input_items` list for that turn.

## Where Document Edits Actually Happen

This repo does not edit real files when `edit_document` is called.

It edits the in-memory `docs` dictionary in `mcp_server.py`:

```python
docs[doc_id] = docs[doc_id].replace(old_str, new_str)
```

That means:

- the document content changes only inside the running server process
- reads after the edit will return the updated value
- restarting the server resets the documents back to the hardcoded values

So `edit_document` mutates RAM, not source code on disk.

## Difference Between `@document` And Tool Calls

This repo has two ways document content can reach the model.

### `@document` expansion

If the user types something like:

```text
Tell me about @report.pdf
```

the app reads the resource itself before calling OpenAI and appends the document text to the user message.

This is local app preprocessing.

### Model-driven tool call

If the user says:

```text
Tell me what report.pdf says
```

the model may decide to call `read_doc_contents`.

This is model-driven action.

Short version:

- `@document` is handled by the app before the model call
- tools are chosen by the model during the model call

## Concrete Example: `/format report.pdf`

This path touches almost everything.

1. User enters `/format report.pdf`
2. `CliChat` sees it is a slash command
3. `CliChat` asks the MCP server for the `format` prompt with `doc_id=report.pdf`
4. the server returns prompt text instructing the model to format the doc and use `edit_document`
5. `CliChat` sends that prompt text plus tool schemas to OpenAI
6. the model realizes it needs the current document text first
7. the model calls `read_doc_contents(report.pdf)`
8. the app sends that tool call through `MCPClient` to the MCP server
9. the server returns the current text
10. the app sends the tool result back to OpenAI
11. the model now calls `edit_document(...)`
12. the app sends that tool call through `MCPClient`
13. the server mutates the in-memory `docs` entry
14. the app sends the tool success result back to OpenAI
15. the model returns the final formatted text

That is the core MCP + tool-calling loop in this repo.

## Final Mental Model

If you remember only one thing, remember this:

- the MCP server defines capabilities
- the MCP client transports requests to those capabilities
- the app orchestrates when to fetch resources, prompts, or tools
- the model decides when to use tools based on descriptions, schemas, and current context
- tool results are fed back into the same turn until the model can produce a final answer

This repo is a small but very solid example of an MCP-enabled agent loop over `stdio`.
