# Tester Agent

Web task automation agent powered by [Google ADK](https://github.com/google/adk-python) with Playwright and Chrome DevTools MCP toolsets.

## What it does

Reads tasks from an Excel spreadsheet (`tasks.xlsx`), launches Chrome, and uses an LLM-driven agent to execute each task on the web. Screenshots are captured after each task and saved to `pics/`. Results (status, screenshot path, errors) are written back into the spreadsheet.

Key features:

- **Dual MCP toolsets** -- Playwright MCP for browser interaction, Chrome DevTools MCP for screenshots
- **Human-in-the-loop auth** -- pauses for manual login/2FA when detected, then resumes
- **Automatic retry** -- LoopAgent wraps the executor with up to 3 attempts per task
- **Per-task isolation** -- failures on one task don't block the rest

## Architecture

![Architecture](architecture.png)

## Setup

Requires Python 3.13+, Node.js (for `npx`), and Chrome installed.

```bash
# Install dependencies
uv sync

# Create .env with your API key
cp .env.example .env
# Edit .env and set OPENAI_API_KEY
```

## Usage

1. Create a `tasks.xlsx` with columns: `task_id`, `url`, `instructions`. A sample generator is included:

   ```bash
   uv run python create_sample_xlsx.py
   ```

2. Run the agent:

   ```bash
   uv run python main.py
   ```

3. Results are written to `tasks.xlsx` (columns: `screenshot_link`, `status`, `error`) and screenshots are saved in `pics/`.

## Project structure

```
main.py               Orchestrator -- launches Chrome, runs tasks, collects screenshots
agent.py              ADK agent definition (LoopAgent + LlmAgent + MCP toolsets)
excel_io.py           Read/write task spreadsheets
create_sample_xlsx.py Generate a sample tasks.xlsx
tests/                Unit tests
docs/plans/           Design and implementation docs
```

## Configuration

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | OpenAI API key (required) |
| `CHROME_PATH` | Custom Chrome executable path (optional) |

The agent model is set in `agent.py` (default: `openai/gpt-5.2` via LiteLLM).
