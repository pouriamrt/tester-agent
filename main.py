# main.py
"""Orchestrator: reads tasks from Excel, runs agent per task, saves results."""

import asyncio
import base64
import logging
import os
import subprocess
import sys
import time
import urllib.request
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
APP_NAME = "tester_agent"
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

    # Poll CDP endpoint until Chrome is ready
    for attempt in range(15):
        if proc.poll() is not None:
            log.error("Chrome exited with code %d", proc.returncode)
            sys.exit(1)
        try:
            urllib.request.urlopen(f"http://localhost:{port}/json/version", timeout=2)
            log.info("Chrome CDP endpoint ready on port %d", port)
            return proc
        except Exception:
            time.sleep(1)

    log.error("Chrome did not become ready on port %d after 15 seconds", port)
    proc.terminate()
    sys.exit(1)


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
        async for event in runner.run_async(
            user_id="human",
            session_id=session.id,
            new_message=message,
        ):
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
                        await asyncio.to_thread(input)
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

        try:
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
                label = "OK" if s == "success" else "FAIL"
                print(f"  [{label}] {tid}: {s}" + (f" -- {e}" if e else ""))
            print(f"{'='*60}")
            passed = sum(1 for _, s, _ in results if s == "success")
            print(f"  {passed}/{len(results)} tasks succeeded.")
        finally:
            await runner.close()

    finally:
        log.info("Shutting down Chrome...")
        chrome_proc.terminate()
        try:
            chrome_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            log.warning("Chrome did not exit after terminate(); killing process.")
            chrome_proc.kill()
            chrome_proc.wait(timeout=5)


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
