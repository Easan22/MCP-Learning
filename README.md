# MCP Chat

MCP Chat is a command-line interface application that connects OpenAI models, including Codex models, to a local MCP (Model Context Protocol) server over stdio. The app supports interactive chat, `@document` retrieval, slash-command prompt execution, and MCP tool calling for document workflows.

## Prerequisites

- Python 3.10+
- OpenAI API key

## Setup

### Step 1: Configure the environment variables

Create or edit the `.env` file in the project root:

```
OPENAI_MODEL="gpt-5.2-codex"
OPENAI_API_KEY=""  # Enter your OpenAI API key
OPENAI_REASONING_EFFORT="medium"  # Optional: low, medium, high, xhigh
USE_UV=1
```

As of June 5, 2026, OpenAI's current Codex model docs list `gpt-5.2-codex` as the flagship coding model, and Codex models are available through the Responses API:

- Models: https://platform.openai.com/docs/models
- GPT-5.2-Codex: https://platform.openai.com/docs/models/gpt-5.2-codex
- Responses API: https://platform.openai.com/docs/api-reference/responses/create?api-mode=responses

### Step 2: Install dependencies

#### Option 1: Setup with uv (Recommended)

[uv](https://github.com/astral-sh/uv) is a fast Python package installer and resolver.

1. Install uv, if not already installed:

```bash
pip install uv
```

2. Create and activate a virtual environment:

```bash
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install dependencies:

```bash
uv pip install -e .
```

4. Run the project

```bash
uv run main.py
```

#### Option 2: Setup without uv

1. Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

2. Install dependencies:

```bash
pip install openai python-dotenv prompt-toolkit "mcp[cli]==1.8.0"
```

3. Run the project

```bash
python main.py
```

## Usage

### Basic Interaction

Type your message and press Enter to chat with the configured OpenAI model.

### Document Retrieval

Use `@` followed by a document ID to inline that MCP resource before the OpenAI request:

```
> Tell me about @deposition.md
```

When you type `@` in the terminal and press Tab, the CLI completes document ids sourced from the MCP resource at `docs://documents`.

### Commands

Use `/` to execute built-in CLI commands or MCP prompts:

```
> /summarize deposition.md
> /format report.pdf
```

Available built-ins:

- `/help`
- `/docs`
- `/prompts`
- `/tools`
- `/refresh`
- `/quit`

When you type `/` in the terminal and press Tab, the CLI completes prompt names discovered from the MCP server.

### How It Works

The local client starts `mcp_server.py` as a subprocess and communicates with it using MCP over stdio.

- `main.py` launches the server
- `mcp_client.py` opens a `ClientSession` over stdio
- `mcp_server.py` exposes tools, resources, and prompts
- `core/openai_service.py` sends requests to the OpenAI Responses API and loops through MCP-backed function calls when the model requests tools
- `core/cli.py` and `core/cli_chat.py` provide the terminal UX and autocomplete

## Development

### Adding New Documents

Edit the `mcp_server.py` file to add new documents to the `docs` dictionary.

### MCP Features Included

- Tool: `read_doc_contents`
- Tool: `edit_document`
- Resource: `docs://documents`
- Resource: `docs://documents/{doc_id}`
- Prompt: `format`
- Prompt: `summarize`

### Notes

- The repository now includes the previously missing `core/` package needed by `main.py`.
- The OpenAI integration uses the Responses API, which OpenAI recommends for new agentic applications: https://platform.openai.com/docs/guides/migrate-to-responses
