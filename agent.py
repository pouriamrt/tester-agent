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


def mark_task_complete(status: str, summary: str, tool_context) -> dict:  # noqa: ANN001 -- injected by ADK FunctionTool
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
