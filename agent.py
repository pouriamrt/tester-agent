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


def start_audio_capture() -> dict:
    """Get JavaScript code that starts capturing audio output from the page.

    Call this when a task involves a website that plays audio. Execute the
    returned JS via Playwright's browser_evaluate BEFORE audio starts playing.

    The script intercepts audio from <audio>/<video> elements and Web Audio API,
    recording raw PCM data into window.__audioCapture.

    Returns:
        Dict with 'js' key containing the JavaScript code to execute via browser_evaluate,
        and 'instruction' key with usage guidance.
    """
    js_code = """(()=>{
if(window.__audioCapture&&window.__audioCapture.active){return 'Audio capture already active';}
const ctx=new (window.AudioContext||window.webkitAudioContext)();
const dest=ctx.createMediaStreamDestination();
const chunks=[];
const processor=ctx.createScriptProcessor(4096,2,2);
dest.stream.getAudioTracks().forEach(t=>{
const src=ctx.createMediaStreamSource(new MediaStream([t]));
src.connect(processor);
});
processor.onaudioprocess=function(e){
const L=new Float32Array(e.inputBuffer.getChannelData(0));
const R=e.inputBuffer.numberOfChannels>1?new Float32Array(e.inputBuffer.getChannelData(1)):L;
chunks.push({left:L,right:R});
};
processor.connect(ctx.destination);
const origPlay=HTMLMediaElement.prototype.play;
HTMLMediaElement.prototype.play=function(){
try{
if(!this.__audioCaptureConnected){
const source=ctx.createMediaElementSource(this);
source.connect(dest);
source.connect(ctx.destination);
this.__audioCaptureConnected=true;
}
}catch(e){}
return origPlay.apply(this,arguments);
};
window.__audioCapture={active:true,ctx:ctx,dest:dest,processor:processor,chunks:chunks,origPlay:origPlay,sampleRate:ctx.sampleRate};
return 'Audio capture started at '+ctx.sampleRate+'Hz';
})()"""
    return {
        "js": js_code,
        "instruction": (
            "Execute this JS via browser_evaluate to start capturing tab audio. "
            "Do this BEFORE audio starts playing on the page. "
            "Call stop_audio_capture when done to retrieve the recorded WAV data."
        ),
    }


def stop_audio_capture() -> dict:
    """Get JavaScript code that stops audio capture and returns WAV data.

    Call this after the page has finished playing audio. Execute the returned JS
    via Playwright's browser_evaluate. The result will be a base64-encoded WAV
    string stored on window.__audioCaptureResult.

    Returns:
        Dict with 'js' key containing the JavaScript code to execute via browser_evaluate,
        and 'instruction' key with usage guidance.
    """
    js_code = """(()=>{
if(!window.__audioCapture||!window.__audioCapture.active){return JSON.stringify({error:'No active audio capture'});}
const cap=window.__audioCapture;
cap.processor.disconnect();
HTMLMediaElement.prototype.play=cap.origPlay;
cap.active=false;
const chunks=cap.chunks;
if(chunks.length===0){
window.__audioCaptureResult='';
return JSON.stringify({status:'stopped',samples:0,audio:''});
}
const sampleRate=cap.sampleRate;
const numChannels=2;
const bitsPerSample=16;
let totalSamples=0;
for(let i=0;i<chunks.length;i++){totalSamples+=chunks[i].left.length;}
const dataSize=totalSamples*numChannels*(bitsPerSample/8);
const buffer=new ArrayBuffer(44+dataSize);
const view=new DataView(buffer);
function writeStr(offset,str){for(let i=0;i<str.length;i++){view.setUint8(offset+i,str.charCodeAt(i));}}
writeStr(0,'RIFF');
view.setUint32(4,36+dataSize,true);
writeStr(8,'WAVE');
writeStr(12,'fmt ');
view.setUint32(16,16,true);
view.setUint16(20,1,true);
view.setUint16(22,numChannels,true);
view.setUint32(24,sampleRate,true);
view.setUint32(28,sampleRate*numChannels*(bitsPerSample/8),true);
view.setUint16(32,numChannels*(bitsPerSample/8),true);
view.setUint16(34,bitsPerSample,true);
writeStr(36,'data');
view.setUint32(40,dataSize,true);
let offset=44;
for(let i=0;i<chunks.length;i++){
const L=chunks[i].left;
const R=chunks[i].right;
for(let j=0;j<L.length;j++){
const lSample=Math.max(-1,Math.min(1,L[j]));
view.setInt16(offset,lSample<0?lSample*0x8000:lSample*0x7FFF,true);
offset+=2;
const rSample=Math.max(-1,Math.min(1,R[j]));
view.setInt16(offset,rSample<0?rSample*0x8000:rSample*0x7FFF,true);
offset+=2;
}
}
const bytes=new Uint8Array(buffer);
let binary='';
for(let i=0;i<bytes.length;i++){binary+=String.fromCharCode(bytes[i]);}
const b64=btoa(binary);
window.__audioCaptureResult=b64;
const durationSec=totalSamples/sampleRate;
return JSON.stringify({status:'stopped',samples:totalSamples,duration_sec:durationSec,size_bytes:buffer.byteLength,audio:b64.substring(0,50)+'...'});
})()"""
    return {
        "js": js_code,
        "instruction": (
            "Execute this JS via browser_evaluate to stop audio capture and encode as WAV. "
            "The base64-encoded WAV is stored on window.__audioCaptureResult. "
            "The orchestrator will automatically collect and save it."
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
