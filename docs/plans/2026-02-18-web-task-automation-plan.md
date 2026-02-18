# Web Task Automation Agent -- Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Google ADK agent that reads tasks from Excel, executes them on web pages via Playwright MCP, screenshots via Chrome DevTools MCP, and writes results back.

**Architecture:** Single ADK `LoopAgent` wrapping an `LlmAgent` (Gemini 2.5 Flash) with dual MCP toolsets (Playwright + Chrome DevTools) and a `LongRunningFunctionTool` for human authentication pauses. Python orchestrator reads Excel, runs agent per task, saves screenshots, updates Excel.

**Tech Stack:** Python 3.13, google-adk, openpyxl, python-dotenv, @playwright/mcp (npm), chrome-devtools-mcp (npm)

**Design doc:** `docs/plans/2026-02-18-web-task-automation-design.md`

---

### Task 1: Project Setup and Dependencies

**Files:**
- Modify: `pyproject.toml`
- Create: `.env.example`
- Modify: `.gitignore`

**Step 1: Update pyproject.toml with all dependencies**

```toml
[project]
name = "tester-agent"
version = "0.1.0"
description = "Web task automation agent powered by Google ADK with Playwright and Chrome DevTools MCP"
readme = "README.md"
requires-python = ">=3.13"
dependencies = [
    "google-adk>=1.25.0",
    "playwright>=1.58.0",
    "openpyxl>=3.1.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
]
```

**Step 2: Create .env.example**

```
GOOGLE_API_KEY=your-gemini-api-key-here
```

**Step 3: Update .gitignore**

Add these lines:
```
.env
pics/
```

**Step 4: Install dependencies**

Run: `uv sync --all-extras`
Expected: All packages install successfully.

**Step 5: Commit**

```bash
git add pyproject.toml .env.example .gitignore uv.lock
git commit -m "chore: add project dependencies and config"
```

---

### Task 2: Excel I/O Module with Tests

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_excel_io.py`
- Create: `excel_io.py`

**Step 1: Create test file**

```python
# tests/test_excel_io.py
import os
import pytest
from openpyxl import Workbook
from excel_io import Task, read_tasks, update_task_result


@pytest.fixture
def sample_xlsx(tmp_path):
    """Create a sample tasks.xlsx for testing."""
    path = tmp_path / "tasks.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["task_id", "url", "instructions"])
    ws.append(["T001", "https://example.com", "Click the login button"])
    ws.append(["T002", "https://example.org", "Fill in the search field with 'hello'"])
    wb.save(path)
    return path


@pytest.fixture
def xlsx_with_results(tmp_path):
    """Create a tasks.xlsx that already has result columns and one completed task."""
    path = tmp_path / "tasks.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["task_id", "url", "instructions", "screenshot_link", "status", "error"])
    ws.append(["T001", "https://example.com", "Click login", "pics/T001.png", "success", ""])
    ws.append(["T002", "https://example.org", "Fill search", "", "", ""])
    wb.save(path)
    return path


def test_read_tasks_returns_all_rows(sample_xlsx):
    tasks = read_tasks(sample_xlsx)
    assert len(tasks) == 2
    assert tasks[0] == Task(task_id="T001", url="https://example.com", instructions="Click the login button")
    assert tasks[1].task_id == "T002"


def test_read_tasks_skips_completed(xlsx_with_results):
    tasks = read_tasks(xlsx_with_results)
    assert len(tasks) == 1
    assert tasks[0].task_id == "T002"


def test_update_task_result_adds_columns(sample_xlsx):
    update_task_result(sample_xlsx, "T001", "pics/T001_123.png", "success", "")
    from openpyxl import load_workbook
    wb = load_workbook(sample_xlsx)
    ws = wb.active
    headers = [cell.value for cell in ws[1]]
    assert "screenshot_link" in headers
    assert "status" in headers
    assert "error" in headers
    # Check T001 row values
    row2 = [cell.value for cell in ws[2]]
    assert row2[headers.index("screenshot_link")] == "pics/T001_123.png"
    assert row2[headers.index("status")] == "success"


def test_update_task_result_writes_error(sample_xlsx):
    update_task_result(sample_xlsx, "T002", "", "failed", "Element not found")
    from openpyxl import load_workbook
    wb = load_workbook(sample_xlsx)
    ws = wb.active
    headers = [cell.value for cell in ws[1]]
    row3 = [cell.value for cell in ws[3]]
    assert row3[headers.index("status")] == "failed"
    assert row3[headers.index("error")] == "Element not found"


def test_update_existing_result_columns(xlsx_with_results):
    update_task_result(xlsx_with_results, "T002", "pics/T002_456.png", "success", "")
    from openpyxl import load_workbook
    wb = load_workbook(xlsx_with_results)
    ws = wb.active
    headers = [cell.value for cell in ws[1]]
    row3 = [cell.value for cell in ws[3]]
    assert row3[headers.index("screenshot_link")] == "pics/T002_456.png"
    assert row3[headers.index("status")] == "success"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_excel_io.py -v`
Expected: FAIL -- `ModuleNotFoundError: No module named 'excel_io'`

**Step 3: Implement excel_io.py**

```python
# excel_io.py
"""Read and write task data from/to Excel files."""

from dataclasses import dataclass
from pathlib import Path
from openpyxl import load_workbook


@dataclass(frozen=True)
class Task:
    task_id: str
    url: str
    instructions: str


def read_tasks(path: str | Path) -> list[Task]:
    """Read tasks from Excel, skipping rows where status is 'success'."""
    wb = load_workbook(path)
    ws = wb.active
    headers = [cell.value for cell in ws[1]]

    task_id_col = headers.index("task_id")
    url_col = headers.index("url")
    instructions_col = headers.index("instructions")
    status_col = headers.index("status") if "status" in headers else None

    tasks = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if status_col is not None and row[status_col] == "success":
            continue
        tasks.append(Task(
            task_id=str(row[task_id_col]),
            url=str(row[url_col]),
            instructions=str(row[instructions_col]),
        ))
    return tasks


def update_task_result(
    path: str | Path,
    task_id: str,
    screenshot_link: str,
    status: str,
    error: str,
) -> None:
    """Write task results back to the Excel file."""
    wb = load_workbook(path)
    ws = wb.active
    headers = [cell.value for cell in ws[1]]

    # Add result columns if missing
    for col_name in ("screenshot_link", "status", "error"):
        if col_name not in headers:
            headers.append(col_name)
            ws.cell(row=1, column=len(headers), value=col_name)

    task_id_col = headers.index("task_id")
    ss_col = headers.index("screenshot_link") + 1  # openpyxl is 1-indexed
    status_col = headers.index("status") + 1
    error_col = headers.index("error") + 1

    for row in ws.iter_rows(min_row=2):
        if str(row[task_id_col].value) == task_id:
            ws.cell(row=row[0].row, column=ss_col, value=screenshot_link)
            ws.cell(row=row[0].row, column=status_col, value=status)
            ws.cell(row=row[0].row, column=error_col, value=error)
            break

    wb.save(path)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_excel_io.py -v`
Expected: All 5 tests PASS.

**Step 5: Commit**

```bash
git add excel_io.py tests/
git commit -m "feat: add Excel I/O module for reading and writing task results"
```

---

### Task 3: Agent Definition Module

**Files:**
- Create: `agent.py`

**Step 1: Create agent.py with the ADK agent definition**

```python
# agent.py
"""Google ADK agent definition with Playwright and Chrome DevTools MCP toolsets."""

from google.adk import Agent
from google.adk.agents import LoopAgent
from google.adk.tools import LongRunningFunctionTool, FunctionTool
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from mcp import StdioServerParameters

TASK_INSTRUCTION = """You are a web task automation agent. You execute tasks on web pages.

## Your workflow for each task:

1. **Navigate** to the given URL using Playwright browser tools.
2. **Check for authentication**: If you see a login form, CAPTCHA, or 2FA prompt, call `request_human_auth` with a description of what you see. Wait for the response before continuing.
3. **Execute the instructions** step by step using Playwright tools (click, type, fill, select, etc.). Use `browser_snapshot` to inspect the page state when needed.
4. **Take a screenshot** after completing the instructions using Chrome DevTools `take_screenshot` tool.
5. **Report completion** by calling `mark_task_complete` with status "success" and a brief summary.

## Error handling:
- If a step fails, try an alternative approach (different selector, waiting longer, etc.).
- If you cannot complete the task after reasonable attempts, call `mark_task_complete` with status "failed" and a clear error description.
- Always attempt to take a screenshot before reporting failure.

## Important rules:
- Do NOT ask the human for help except via `request_human_auth` for login/2FA.
- Use `browser_snapshot` to understand page structure before interacting with elements.
- Wait for page loads and animations to complete before interacting.
- Be precise with selectors -- prefer accessible names and roles over CSS selectors.
"""


def request_human_auth(description: str) -> dict:
    """Pause execution and request the human to authenticate in the browser.

    Call this when you detect a login form, CAPTCHA, or 2FA prompt.

    Args:
        description: What you see that requires authentication (e.g., "Login form at example.com")

    Returns:
        Status dict. When status is "authenticated", you may continue.
    """
    return {"status": "pending", "message": description}


def mark_task_complete(status: str, summary: str, tool_context) -> dict:
    """Mark the current task as complete and exit the retry loop.

    Args:
        status: "success" or "failed"
        summary: Brief description of what happened

    Returns:
        The status and summary for the orchestrator.
    """
    tool_context.actions.escalate = True
    return {"status": status, "summary": summary}


def build_agent(cdp_endpoint: str = "http://localhost:9222") -> LoopAgent:
    """Build the LoopAgent with task executor sub-agent.

    Args:
        cdp_endpoint: CDP endpoint URL for connecting to Chrome.

    Returns:
        LoopAgent wrapping the task executor.
    """
    playwright_toolset = McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="npx",
                args=["-y", "@playwright/mcp@latest", "--cdp-endpoint", cdp_endpoint],
            ),
            timeout=30.0,
        ),
    )

    chrome_devtools_toolset = McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="npx",
                args=["-y", "chrome-devtools-mcp@latest", "--browser-url", cdp_endpoint],
            ),
            timeout=30.0,
        ),
    )

    auth_tool = LongRunningFunctionTool(func=request_human_auth)
    complete_tool = FunctionTool(func=mark_task_complete)

    task_executor = Agent(
        name="task_executor",
        model="gemini-2.5-flash",
        instruction=TASK_INSTRUCTION,
        tools=[playwright_toolset, chrome_devtools_toolset, auth_tool, complete_tool],
    )

    loop_agent = LoopAgent(
        name="task_loop",
        max_iterations=3,
        sub_agents=[task_executor],
    )

    return loop_agent
```

**Step 2: Verify import works**

Run: `uv run python -c "from agent import build_agent; print('OK')"`
Expected: Prints "OK" (no import errors).

**Step 3: Commit**

```bash
git add agent.py
git commit -m "feat: add ADK agent with Playwright + DevTools MCP and auth/retry support"
```

---

### Task 4: Orchestrator (main.py)

**Files:**
- Modify: `main.py`

**Step 1: Implement the full orchestrator**

```python
# main.py
"""Orchestrator: reads tasks from Excel, runs agent per task, saves results."""

import asyncio
import base64
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from google.adk import Runner
from google.adk.apps.app import App, ResumabilityConfig
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types

from agent import build_agent
from excel_io import read_tasks, update_task_result

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

PICS_DIR = Path("pics")
APP_NAME = "tester-agent"
CDP_PORT = 9222
CDP_ENDPOINT = f"http://localhost:{CDP_PORT}"


def launch_chrome(port: int) -> subprocess.Popen:
    """Launch Chrome with remote debugging enabled."""
    # Try common Chrome paths on Windows
    chrome_paths = [
        os.environ.get("CHROME_PATH", ""),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    chrome_exe = None
    for p in chrome_paths:
        if p and os.path.isfile(p):
            chrome_exe = p
            break

    if not chrome_exe:
        log.error("Chrome not found. Set CHROME_PATH environment variable.")
        sys.exit(1)

    log.info("Launching Chrome with --remote-debugging-port=%d", port)
    proc = subprocess.Popen(
        [
            chrome_exe,
            f"--remote-debugging-port={port}",
            "--no-first-run",
            "--no-default-browser-check",
            "--user-data-dir=" + str(Path.home() / ".tester-agent-chrome-profile"),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(3)  # Give Chrome time to start
    return proc


def save_screenshot(task_id: str, data: bytes) -> str:
    """Save screenshot bytes to pics/ and return the relative path."""
    PICS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{task_id}_{timestamp}.png"
    path = PICS_DIR / filename
    path.write_bytes(data)
    log.info("Screenshot saved: %s", path)
    return str(path)


async def run_task(
    runner: Runner,
    task_id: str,
    prompt: str,
) -> tuple[str, str, str]:
    """Run a single task through the agent. Returns (status, screenshot_path, error)."""
    session = await runner.session_service.create_session(
        app_name=APP_NAME,
        user_id="human",
        session_id=f"task-{task_id}",
    )

    screenshot_path = ""
    status = "failed"
    error = ""
    last_function_call_id = None
    last_function_call_name = None

    message = types.Content(role="user", parts=[types.Part(text=prompt)])

    while True:
        events = []
        async for event in runner.run_async(
            user_id="human",
            session_id=session.id,
            new_message=message,
        ):
            events.append(event)

            # Check for screenshot data in function responses
            for fr in event.get_function_responses():
                if fr.name == "take_screenshot" and fr.response:
                    img_data = fr.response.get("result", "")
                    if img_data:
                        try:
                            screenshot_path = save_screenshot(
                                task_id, base64.b64decode(img_data)
                            )
                        except Exception as e:
                            log.warning("Failed to decode screenshot: %s", e)

            # Check for mark_task_complete
            for fr in event.get_function_responses():
                if fr.name == "mark_task_complete" and fr.response:
                    status = fr.response.get("status", "failed")
                    error = fr.response.get("summary", "") if status == "failed" else ""

            # Check for auth pause (LongRunningFunctionTool)
            if event.long_running_tool_ids:
                for fc in event.get_function_calls():
                    if fc.id in event.long_running_tool_ids:
                        last_function_call_id = fc.id
                        last_function_call_name = fc.name
                        desc = fc.args.get("description", "Authentication required")
                        log.info("AUTH REQUIRED: %s", desc)
                        print(f"\n{'='*60}")
                        print(f"AUTHENTICATION REQUIRED: {desc}")
                        print("Complete authentication in the browser, then press Enter.")
                        print(f"{'='*60}")
                        input()  # Block until human presses Enter
                break  # Exit event loop to resume

        # If we paused for auth, resume
        if last_function_call_id:
            message = types.Content(
                role="user",
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=last_function_call_name,
                            id=last_function_call_id,
                            response={"status": "authenticated"},
                        )
                    )
                ],
            )
            last_function_call_id = None
            last_function_call_name = None
            continue  # Resume agent

        # No pause -- agent finished (or loop exhausted)
        break

    return status, screenshot_path, error


def format_task_prompt(task) -> str:
    """Format a Task into a prompt string for the agent."""
    return (
        f"Task ID: {task.task_id}\n"
        f"URL: {task.url}\n"
        f"Instructions: {task.instructions}\n\n"
        f"Execute these instructions on the web page. "
        f"Take a full-page screenshot when done. "
        f"Then call mark_task_complete with the result."
    )


async def async_main():
    xlsx_path = Path("tasks.xlsx")
    if not xlsx_path.exists():
        log.error("tasks.xlsx not found in current directory.")
        sys.exit(1)

    tasks = read_tasks(xlsx_path)
    if not tasks:
        log.info("No pending tasks found in tasks.xlsx.")
        return

    log.info("Found %d pending task(s).", len(tasks))

    # Launch Chrome
    chrome_proc = launch_chrome(CDP_PORT)

    try:
        # Build agent and runner
        agent = build_agent(CDP_ENDPOINT)
        app = App(
            name=APP_NAME,
            root_agent=agent,
            resumability_config=ResumabilityConfig(is_resumable=True),
        )
        session_service = InMemorySessionService()
        runner = Runner(app=app, session_service=session_service)

        results = []
        for task in tasks:
            log.info("--- Task %s: %s ---", task.task_id, task.url)
            try:
                status, screenshot_path, error = await run_task(
                    runner, task.task_id, format_task_prompt(task)
                )
            except Exception as e:
                log.exception("Task %s failed with exception", task.task_id)
                status = "failed"
                screenshot_path = ""
                error = str(e)

            update_task_result(xlsx_path, task.task_id, screenshot_path, status, error)
            results.append((task.task_id, status, error))
            log.info("Task %s: %s %s", task.task_id, status, f"({error})" if error else "")

        # Print summary
        print(f"\n{'='*60}")
        print("RUN SUMMARY")
        print(f"{'='*60}")
        for tid, s, e in results:
            emoji = "OK" if s == "success" else "FAIL"
            print(f"  [{emoji}] {tid}: {s}" + (f" -- {e}" if e else ""))
        print(f"{'='*60}")
        passed = sum(1 for _, s, _ in results if s == "success")
        print(f"  {passed}/{len(results)} tasks succeeded.")

        await runner.close()

    finally:
        log.info("Shutting down Chrome...")
        chrome_proc.terminate()
        chrome_proc.wait(timeout=10)


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
```

**Step 2: Verify import works**

Run: `uv run python -c "from main import main; print('OK')"`
Expected: Prints "OK" (no import errors). It won't run because tasks.xlsx doesn't exist yet.

**Step 3: Commit**

```bash
git add main.py
git commit -m "feat: add orchestrator with task loop, auth handling, and screenshot saving"
```

---

### Task 5: Sample tasks.xlsx and .env

**Files:**
- Create: `create_sample_xlsx.py` (helper script, can be deleted after)
- Create: `.env` (manual, not committed)

**Step 1: Create a helper script to generate sample tasks.xlsx**

```python
# create_sample_xlsx.py
"""Generate a sample tasks.xlsx for testing."""
from openpyxl import Workbook

wb = Workbook()
ws = wb.active
ws.append(["task_id", "url", "instructions"])
ws.append([
    "T001",
    "https://example.com",
    "Verify the page title says 'Example Domain'. Click the 'More information...' link.",
])
ws.append([
    "T002",
    "https://httpbin.org/forms/post",
    "Fill the form: set 'custname' to 'Test User', 'custtel' to '555-1234', select 'medium' pizza size, check 'bacon' topping, and submit the form.",
])
wb.save("tasks.xlsx")
print("Created tasks.xlsx with 2 sample tasks.")
```

**Step 2: Run it**

Run: `uv run python create_sample_xlsx.py`
Expected: `Created tasks.xlsx with 2 sample tasks.`

**Step 3: Create .env with your Gemini API key**

Create `.env` manually:
```
GOOGLE_API_KEY=<your-actual-key>
```

**Step 4: Commit sample xlsx generator (not .env)**

```bash
git add create_sample_xlsx.py tasks.xlsx
git commit -m "feat: add sample tasks.xlsx and generator script"
```

---

### Task 6: Integration Test (Manual)

**Prerequisites:**
- Chrome installed
- `.env` has a valid `GOOGLE_API_KEY`
- `tasks.xlsx` exists with sample tasks
- npm/npx available (for MCP servers)

**Step 1: Run the full pipeline**

Run: `uv run python main.py`

Expected behavior:
1. Chrome launches with debugging port
2. Agent navigates to example.com, performs task T001
3. Screenshot saved to `pics/T001_*.png`
4. Agent navigates to httpbin.org form, fills it in for T002
5. Screenshot saved to `pics/T002_*.png`
6. `tasks.xlsx` updated with screenshot_link, status, error columns
7. Summary printed showing 2/2 succeeded

**Step 2: Verify outputs**

- Check `pics/` folder has 2 PNG files
- Open `tasks.xlsx` and verify new columns have data
- Review console log for any errors

**Step 3: Test auth flow (optional)**

Add a task row to tasks.xlsx with a URL that requires login (e.g., a private GitHub repo). Run again. The agent should:
1. Detect the login form
2. Print "AUTHENTICATION REQUIRED" in the console
3. Wait for you to log in manually in the browser
4. Continue after you press Enter

**Step 4: Test retry (optional)**

Add a task with intentionally bad instructions (e.g., "Click the element with id #nonexistent"). Run. The LoopAgent should retry up to 3 times, then record as failed.

**Step 5: Final commit**

```bash
git add -A
git commit -m "feat: complete web task automation agent v0.1.0"
```
