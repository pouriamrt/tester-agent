# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Web task automation agent built on **Google ADK** (Agent Development Kit). Reads tasks from an Excel spreadsheet, drives Chrome via two MCP toolsets (Playwright for interaction, Chrome DevTools for screenshots), and writes results back to the spreadsheet. Uses a configurable LLM (default: OpenAI GPT-5.2 via LiteLLM) as the decision-making engine inside the agent. Supports OpenAI, Vertex AI (Google's enterprise Gemini), and native Google Gemini as providers.

## Commands

```bash
# Install dependencies (requires Python 3.13+ and uv)
uv sync --all-extras

# Run the agent (requires tasks.xlsx, Chrome, Node.js/npx, and an LLM API key in .env)
uv run python main.py

# Install with Vertex AI support
uv sync --extra vertex

# Generate a sample tasks.xlsx
uv run python create_sample_xlsx.py

# Run tests
uv run pytest tests/ -v

# Run a single test
uv run pytest tests/test_excel_io.py::test_read_tasks_returns_all_rows -v
```

## Architecture

**Three-layer design:** Orchestrator (`main.py`) -> ADK Agent (`agent.py`) -> MCP Toolsets

1. **Orchestrator** (`main.py`): Launches Chrome with `--remote-debugging-port=9222`, iterates over tasks from Excel, runs each through the ADK agent, collects screenshots from disk (new `.png` files in project root), moves them to `pics/`, and updates the spreadsheet. Handles the human-in-the-loop auth pause/resume cycle via ADK's `LongRunningFunctionTool` events.

2. **Agent** (`agent.py`): A `LoopAgent` (max 3 retries) wrapping an `LlmAgent` named `task_executor`. The executor has seven tools:
   - `McpToolset` for **Playwright MCP** -- browser navigation, clicking, typing, form filling
   - `McpToolset` for **Chrome DevTools MCP** -- `take_screenshot` for full-page captures
   - `LongRunningFunctionTool(request_human_auth)` -- pauses execution for manual login/2FA
   - `FunctionTool(mark_task_complete)` -- signals success/failure and escalates to exit the LoopAgent
   - `FunctionTool(inject_fake_audio)` -- returns JS to override `getUserMedia` with a synthetic audio stream for mic testing
   - `FunctionTool(start_audio_capture)` -- starts capturing tab audio by injecting Web Audio hooks
   - `FunctionTool(stop_audio_capture)` -- stops capture and encodes PCM data as base64 WAV

3. **Excel I/O** (`excel_io.py`): Reads `Task(task_id, url, instructions)` rows from `tasks.xlsx`, skips rows already marked `status=success` (re-run support). Writes results back by adding/updating `screenshot_link`, `audio_link`, `status`, `error` columns.

**Both MCP servers connect to the same Chrome instance** via CDP on port 9222. This is why Chrome is launched externally rather than by either MCP server.

**Auth flow:** Agent detects login/2FA -> calls `request_human_auth` -> orchestrator sees `long_running_tool_ids` in event -> prompts human on console -> resumes agent with `FunctionResponse(status="authenticated")`. Max 5 auth attempts per task.

**Screenshot collection:** Screenshots are saved as `.png` files to the project root by the Chrome DevTools MCP. After each task, the orchestrator diffs the `.png` file list (before vs after) and moves new files to `pics/` with naming `{task_id}_{timestamp}.png`.

## Key Conventions

- The LLM model is configured via `MODEL_PROVIDER` and `MODEL_NAME` env vars. `main.py:resolve_model_string()` builds the ADK model string and passes it to `build_agent()`. Supported providers: `openai` (default), `vertex_ai`, `google` (native Gemini).
- `mark_task_complete` uses `tool_context.actions.escalate = True` to break out of the LoopAgent -- this is an ADK-specific pattern, not a general Python concept.
- Chrome uses a dedicated user profile at `~/.tester-agent-chrome-profile` to persist login sessions across runs.
- The `pics/` directory is cleared at the start of each run.
- `tasks.xlsx` is not committed (gitignored). Use `create_sample_xlsx.py` to generate one.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `MODEL_PROVIDER` | No | LLM provider: `openai` (default), `vertex_ai`, or `google` |
| `MODEL_NAME` | No | Model name (default: `gpt-5.2`). Examples: `gemini-2.5-flash`, `gpt-5.2` |
| `OPENAI_API_KEY` | If openai | OpenAI API key (used by LiteLLM) |
| `VERTEXAI_PROJECT` | If vertex_ai | GCP project ID for Vertex AI |
| `VERTEXAI_LOCATION` | If vertex_ai | GCP region (e.g. `us-central1`) |
| `GOOGLE_API_KEY` | If google | Google AI API key for native Gemini |
| `CHROME_PATH` | No | Custom Chrome executable path |
| `FAKE_AUDIO_FILE` | No | Path to a WAV file for fake mic input (omit for synthetic beep tone) |

Copy `.env.example` to `.env` and fill in values.

## Audio / Microphone Testing

Chrome is launched with `--use-fake-device-for-media-stream` and related flags, so `getUserMedia()` works without a real microphone. Two levels of control:

1. **Static (Chrome flags):** Always active. Set `FAKE_AUDIO_FILE` to a WAV path to feed specific audio, or leave empty for a synthetic beep tone. The permission popup is auto-accepted.

2. **Dynamic (inject_fake_audio tool):** The agent calls `inject_fake_audio(frequency, duration)` which returns JavaScript code. The agent then executes it via Playwright's `browser_evaluate` *before* the page requests mic access. This overrides `getUserMedia` to return a `MediaStream` from a Web Audio `OscillatorNode`.

## Audio Capture (Recording Page Output)

The agent can record audio playing on a website and save it as WAV files:

1. **`start_audio_capture` tool:** Returns JS that hooks `<audio>`/`<video>` elements and Web Audio API to intercept audio output. Must be executed via `browser_evaluate` before audio starts playing.

2. **`stop_audio_capture` tool:** Returns JS that stops recording, encodes PCM data as WAV, and stores base64 on `window.__audioCaptureResult`. Agent reads this and passes it to `mark_task_complete(audio_data=...)`.

3. **Orchestrator collection:** `main.py` decodes the base64 WAV and saves to `audio/{task_id}_{timestamp}.wav`. Path is written to `audio_link` column in the Excel spreadsheet.

Audio files are saved in the `audio/` directory (cleared at each run start, same as `pics/`).

## External Dependencies

- **Chrome** must be installed and accessible
- **Node.js/npx** must be available (MCP servers are npm packages: `@playwright/mcp`, `chrome-devtools-mcp`)
- Both MCP servers are fetched on-the-fly via `npx -y` at runtime
