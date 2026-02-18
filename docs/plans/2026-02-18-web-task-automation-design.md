# Web Task Automation Agent -- Design Document

**Date:** 2026-02-18
**Status:** Approved

## Goal

Build a Google ADK agent that reads web tasks from an Excel file, executes each task autonomously using Playwright MCP, captures full-page screenshots via Chrome DevTools MCP, and writes results back to the Excel file. Human involvement is limited to authentication only.

## Architecture: Single ADK Agent with Dual MCP Toolsets

```
tasks.xlsx (openpyxl)
    |
    v
main.py -- Orchestrator Loop
    |
    v  for each row:
LoopAgent (max_iterations=3, retry on failure)
    |
    v
LlmAgent "task_executor" (Gemini 2.5 Flash)
    |-- McpToolset: Playwright (navigate, click, type, fill, snapshot, etc.)
    |-- McpToolset: Chrome DevTools (take_screenshot full-page)
    |-- LongRunningFunctionTool: request_human_auth()
    |-- FunctionTool: mark_task_complete(status, error?)
    |
    v
Event Processor -> save screenshot -> update Excel row
```

## Project Structure

```
tester-agent/
  main.py              # Entry point + orchestrator loop
  agent.py             # ADK agent definition (tools, instruction, LoopAgent)
  excel_io.py          # Read/write tasks.xlsx with openpyxl
  tasks.xlsx           # Input file (user-provided)
  pics/                # Screenshot output folder (auto-created)
  .env                 # GOOGLE_API_KEY
  pyproject.toml       # Dependencies
```

## Components

### 1. excel_io.py

- `read_tasks(path) -> list[Task]`: reads tasks.xlsx, returns list of Task dataclasses
  - `Task(task_id: str, url: str, instructions: str)`
  - Skips rows where status is already "success" (re-run support)
- `update_task_result(path, task_id, screenshot_link, status, error)`: writes results back
  - Adds columns `screenshot_link`, `status`, `error` if they don't exist
  - Finds the row by task_id and updates in place

### 2. agent.py

**Agent hierarchy:**

```python
LoopAgent(
    name="task_loop",
    max_iterations=3,
    sub_agents=[
        LlmAgent(
            name="task_executor",
            model="gemini-2.5-flash",
            instruction=TASK_INSTRUCTION,
            tools=[
                playwright_toolset,
                chrome_devtools_toolset,
                request_human_auth_tool,   # LongRunningFunctionTool
                mark_task_complete_tool,    # FunctionTool -- escalates to exit loop
            ],
        )
    ],
)
```

**`request_human_auth(description: str) -> dict`**: Called by agent when it detects login/2FA. Returns `{"status": "pending"}`. Orchestrator pauses, prompts human, resumes with `{"status": "authenticated"}`.

**`mark_task_complete(status: str, summary: str) -> dict`**: Called by agent when task is done. Sets `escalate=True` on the event context to break out of the LoopAgent. Returns the status for the orchestrator to record.

**Agent instruction** tells the agent to:
1. Navigate to the URL
2. Check if authentication is needed; if so, call `request_human_auth`
3. Execute the natural-language instructions step by step
4. After completing instructions, take a full-page screenshot via Chrome DevTools
5. Call `mark_task_complete` with status "success" or "failed" and a summary
6. If something fails, describe the error clearly so the LoopAgent can retry

### 3. main.py -- Orchestrator

```
async main():
    tasks = read_tasks("tasks.xlsx")
    os.makedirs("pics", exist_ok=True)

    # Build agent
    agent = build_agent()  # returns the LoopAgent

    # Build App with resumability for HITL
    app = App(name="tester", root_agent=agent,
              resumability_config=ResumabilityConfig(is_resumable=True))
    runner = Runner(app=app, session_service=InMemorySessionService())

    results = []
    for task in tasks:
        session = create_session(task.task_id)
        prompt = format_task_prompt(task)

        try:
            status, screenshot_path, error = await run_task(
                runner, session, task, prompt
            )
        except Exception as e:
            status, error = "failed", str(e)
            screenshot_path = attempt_emergency_screenshot(task)

        update_task_result("tasks.xlsx", task.task_id, screenshot_path, status, error)
        results.append((task.task_id, status, error))

    print_summary(results)
    await runner.close()
```

**`run_task()`** handles the event loop:
- Iterates `runner.run_async()` events
- Detects `long_running_tool_ids` for auth pauses -> prompts human -> resumes
- Extracts screenshot binary data from Chrome DevTools tool responses
- Saves screenshots to `pics/{task_id}_{timestamp}.png`
- Detects `mark_task_complete` function responses for final status

### Browser Lifecycle

**Problem:** Both Playwright MCP and Chrome DevTools MCP need the same browser.

**Solution:** Launch Chrome manually with `--remote-debugging-port=9222`, then:
- Playwright MCP connects via CDP URL (`--cdp-endpoint`)
- Chrome DevTools MCP connects to `localhost:9222`

This ensures both MCP servers operate on the same browser instance. The orchestrator handles Chrome lifecycle (start before tasks, kill after all tasks complete).

### Auth Flow

1. Agent navigates to URL, sees login form
2. Agent calls `request_human_auth("Login form detected at example.com")`
3. `LongRunningFunctionTool` returns `{"status": "pending"}`
4. Event has `long_running_tool_ids` set -> orchestrator detects pause
5. Orchestrator prints: "Authentication required: Login form detected at example.com. Complete auth in the browser, then press Enter."
6. Human authenticates, presses Enter
7. Orchestrator resumes with `FunctionResponse(status="authenticated")`
8. Agent continues task execution

Auth is requested once per domain. The agent's instruction tells it to only request auth when truly needed.

### Retry via LoopAgent

- `LoopAgent(max_iterations=3)` wraps the executor
- On success: executor calls `mark_task_complete(status="success")` which escalates
- On failure: executor can either retry within the loop or call `mark_task_complete(status="failed")` to escalate with an error
- If max_iterations reached without escalation, orchestrator records as "failed" with "max retries exceeded"

### Error Handling

- Each task in a try/except -- failures never stop the loop
- On failure: attempt screenshot of current state, record error in Excel
- Transient MCP disconnects: ADK's built-in `retry_on_errors` handles reconnection
- Browser crashes: orchestrator detects, restarts Chrome, continues with next task

### Dependencies

```toml
[project]
dependencies = [
    "google-adk>=1.25.0",
    "playwright>=1.58.0",
    "openpyxl>=3.1.0",
    "python-dotenv>=1.0.0",
]
```

### Output

- `pics/` folder with `{task_id}_{timestamp}.png` for each task
- `tasks.xlsx` updated with `screenshot_link`, `status`, `error` columns
- Console log summarizing each task result (task_id, status, error if any)
