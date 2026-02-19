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

## Audio / microphone testing:
Chrome is launched with fake media device flags, so `getUserMedia()` works without a real microphone. If the task involves audio or microphone testing:
1. Call `inject_fake_audio` to get a JavaScript snippet that overrides `getUserMedia` with a synthetic audio stream (configurable frequency and duration).
2. Execute the returned JS using Playwright's `browser_evaluate` tool BEFORE clicking any "start recording" or "allow microphone" buttons.
3. Then interact with the page normally -- the app will receive the fake audio stream.

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


def inject_fake_audio(frequency: float = 440.0, duration: float = 10.0) -> dict:
    """Get JavaScript code that injects a synthetic audio tone into the page.

    Call this when a task involves microphone or audio input testing. Execute the
    returned JS via Playwright's browser_evaluate BEFORE the page requests mic access.

    The script overrides navigator.mediaDevices.getUserMedia so that any audio
    request returns a MediaStream driven by a Web Audio OscillatorNode.

    Args:
        frequency: Tone frequency in Hz (default 440 = A4 note). Use 0 for silence.
        duration: How long the tone plays in seconds (default 10).

    Returns:
        Dict with 'js' key containing the JavaScript code to execute via browser_evaluate.
    """
    js_code = (
        "(()=>{"
        "const ctx=new AudioContext();"
        "const osc=ctx.createOscillator();"
        f"osc.frequency.setValueAtTime({frequency},ctx.currentTime);"
        "const dest=ctx.createMediaStreamDestination();"
        "osc.connect(dest);osc.start();"
        f"setTimeout(()=>osc.stop(),{int(duration*1000)});"
        "const orig=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);"
        "navigator.mediaDevices.getUserMedia=async(c)=>{"
        "if(c&&c.audio){const s=dest.stream;"
        "if(c.video){const v=await orig({video:c.video});"
        "v.getAudioTracks().forEach(t=>s.addTrack(t));return s;}"
        "return s;}return orig(c);};"
        "return 'Audio injection active';})()"
    )
    return {
        "js": js_code,
        "instruction": (
            "Execute this JS via browser_evaluate to inject fake audio. "
            "Do this BEFORE the page calls getUserMedia (before clicking record/call buttons)."
        ),
    }


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


def build_agent(
    cdp_endpoint: str = "http://localhost:9222",
    model: str = "openai/gpt-5.2",
) -> LoopAgent:
    """Build the LoopAgent with task executor sub-agent.

    Args:
        cdp_endpoint: CDP endpoint URL for connecting to Chrome.
        model: LLM model string for ADK (e.g. "openai/gpt-5.2", "vertex_ai/gemini-2.5-flash").

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
    audio_tool = FunctionTool(func=inject_fake_audio)

    task_executor = Agent(
        name="task_executor",
        model=model,
        instruction=TASK_INSTRUCTION,
        tools=[playwright_toolset, chrome_devtools_toolset, auth_tool, complete_tool, audio_tool],
    )

    loop_agent = LoopAgent(
        name="task_loop",
        max_iterations=3,
        sub_agents=[task_executor],
    )

    return loop_agent
