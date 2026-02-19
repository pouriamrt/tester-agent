# Tab Audio Capture Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add tab audio capture so the tester-agent can save WAV recordings of audio playing on websites alongside screenshots.

**Architecture:** Two new FunctionTools (`start_audio_capture`, `stop_audio_capture`) return JavaScript that the agent executes via Playwright's `browser_evaluate`. The JS uses Web Audio API + ScriptProcessorNode to capture PCM samples, then encodes them as WAV. The orchestrator reads the base64 result via CDP and saves to `audio/`.

**Tech Stack:** Web Audio API (browser-side), base64 encoding (Python stdlib), WAV header construction (JS-side PCM -> WAV, Python-side decode)

---

### Task 1: Add `audio_link` to Excel I/O

**Files:**
- Modify: `excel_io.py:46-81`
- Test: `tests/test_excel_io.py`

**Step 1: Write the failing test**

Add to `tests/test_excel_io.py`:

```python
def test_update_task_result_writes_audio_link(sample_xlsx):
    update_task_result(sample_xlsx, "T001", "pics/T001_123.png", "success", "", audio_link="audio/T001_123.wav")
    wb = load_workbook(sample_xlsx)
    ws = wb.active
    headers = [cell.value for cell in ws[1]]
    assert "audio_link" in headers
    row2 = [cell.value for cell in ws[2]]
    assert row2[headers.index("audio_link")] == "audio/T001_123.wav"


def test_update_task_result_audio_link_empty_by_default(sample_xlsx):
    update_task_result(sample_xlsx, "T001", "pics/T001_123.png", "success", "")
    wb = load_workbook(sample_xlsx)
    ws = wb.active
    headers = [cell.value for cell in ws[1]]
    assert "audio_link" in headers
    row2 = [cell.value for cell in ws[2]]
    assert row2[headers.index("audio_link")] is None or row2[headers.index("audio_link")] == ""
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_excel_io.py::test_update_task_result_writes_audio_link -v`
Expected: FAIL (no `audio_link` parameter or column)

**Step 3: Write minimal implementation**

In `excel_io.py`, update `update_task_result`:

```python
def update_task_result(
    path: str | Path,
    task_id: str,
    screenshot_link: str,
    status: str,
    error: str,
    explanation: str = "",
    audio_link: str = "",
) -> None:
    """Write task results back to the Excel file."""
    wb = load_workbook(path)
    ws = wb.active
    headers = [cell.value for cell in ws[1]]

    # Add result columns if missing
    for col_name in ("screenshot_link", "status", "error", "explanation", "audio_link"):
        if col_name not in headers:
            headers.append(col_name)
            ws.cell(row=1, column=len(headers), value=col_name)

    task_id_col = headers.index("task_id")
    ss_col = headers.index("screenshot_link") + 1
    status_col = headers.index("status") + 1
    error_col = headers.index("error") + 1
    explanation_col = headers.index("explanation") + 1
    audio_col = headers.index("audio_link") + 1

    for row in ws.iter_rows(min_row=2):
        if str(row[task_id_col].value) == task_id:
            ws.cell(row=row[0].row, column=ss_col, value=screenshot_link)
            ws.cell(row=row[0].row, column=status_col, value=status)
            ws.cell(row=row[0].row, column=error_col, value=error)
            ws.cell(row=row[0].row, column=explanation_col, value=explanation)
            ws.cell(row=row[0].row, column=audio_col, value=audio_link or "")
            break
    else:
        raise ValueError(f"Task ID '{task_id}' not found in {path}")

    wb.save(path)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_excel_io.py -v`
Expected: ALL PASS (both new tests + existing tests unchanged)

**Step 5: Commit**

```bash
git add excel_io.py tests/test_excel_io.py
git commit -m "feat: add audio_link column to Excel task results"
```

---

### Task 2: Add `start_audio_capture` tool to agent

**Files:**
- Modify: `agent.py`
- Test: `tests/test_agent_tools.py` (create)

**Step 1: Write the failing test**

Create `tests/test_agent_tools.py`:

```python
# tests/test_agent_tools.py
from agent import start_audio_capture, stop_audio_capture


def test_start_audio_capture_returns_js():
    result = start_audio_capture()
    assert "js" in result
    assert "instruction" in result
    assert "window.__audioCapture" in result["js"]
    assert "__audioCapture" in result["js"]


def test_start_audio_capture_js_is_valid_iife():
    """The JS should be an IIFE that can be passed to browser_evaluate."""
    result = start_audio_capture()
    js = result["js"]
    assert js.startswith("(")
    assert js.endswith(")")
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agent_tools.py::test_start_audio_capture_returns_js -v`
Expected: FAIL with ImportError (function doesn't exist)

**Step 3: Write minimal implementation**

Add to `agent.py`:

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_agent_tools.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add agent.py tests/test_agent_tools.py
git commit -m "feat: add start_audio_capture tool"
```

---

### Task 3: Add `stop_audio_capture` tool to agent

**Files:**
- Modify: `agent.py`
- Test: `tests/test_agent_tools.py`

**Step 1: Write the failing test**

Add to `tests/test_agent_tools.py`:

```python
def test_stop_audio_capture_returns_js():
    result = stop_audio_capture()
    assert "js" in result
    assert "instruction" in result
    assert "__audioCaptureResult" in result["js"]


def test_stop_audio_capture_js_encodes_wav():
    """The stop JS should contain WAV encoding logic."""
    result = stop_audio_capture()
    js = result["js"]
    assert "RIFF" in js  # WAV header magic bytes
    assert "WAVEfmt" in js or "WAVE" in js
    assert "base64" in js.lower() or "btoa" in js
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agent_tools.py::test_stop_audio_capture_returns_js -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Add to `agent.py`:

```python
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
```

**Step 4: Run all agent tool tests**

Run: `uv run pytest tests/test_agent_tools.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add agent.py tests/test_agent_tools.py
git commit -m "feat: add stop_audio_capture tool with WAV encoding"
```

---

### Task 4: Register tools and update agent instructions

**Files:**
- Modify: `agent.py:108-158` (build_agent function and TASK_INSTRUCTION)

**Step 1: Write the failing test**

Add to `tests/test_agent_tools.py`:

```python
def test_task_instruction_mentions_audio_capture():
    from agent import TASK_INSTRUCTION
    assert "start_audio_capture" in TASK_INSTRUCTION
    assert "stop_audio_capture" in TASK_INSTRUCTION
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agent_tools.py::test_task_instruction_mentions_audio_capture -v`
Expected: FAIL

**Step 3: Update TASK_INSTRUCTION and register tools**

Append to `TASK_INSTRUCTION` in `agent.py`, after the existing "Audio / microphone testing" section:

```python
## Audio capture (recording page audio output):
If the task involves a website that plays audio (music, speech, notifications, sound effects):
1. Call `start_audio_capture` to get JS that hooks the page's audio output.
2. Execute the returned JS via Playwright's `browser_evaluate` BEFORE audio starts playing.
3. Let the page play audio normally while you complete other task steps.
4. When done (before calling mark_task_complete), call `stop_audio_capture` to get JS that finalizes the recording.
5. Execute that JS via `browser_evaluate` -- it encodes the recording as base64 WAV.
The orchestrator will automatically save the audio file.
```

In `build_agent()`, add tool registrations:

```python
audio_capture_start_tool = FunctionTool(func=start_audio_capture)
audio_capture_stop_tool = FunctionTool(func=stop_audio_capture)
```

Add both to the `tools=` list in the `Agent()` constructor.

**Step 4: Run tests**

Run: `uv run pytest tests/test_agent_tools.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add agent.py tests/test_agent_tools.py
git commit -m "feat: register audio capture tools and update agent instructions"
```

---

### Task 5: Add audio collection to orchestrator

**Files:**
- Modify: `main.py`

**Step 1: Write the failing test**

Add `tests/test_audio_collection.py`:

```python
# tests/test_audio_collection.py
import base64
import struct
from pathlib import Path
from main import collect_audio, AUDIO_DIR


def _make_tiny_wav_b64() -> str:
    """Create a minimal valid WAV as base64 (44-byte header, 4 bytes of silence)."""
    sample_rate = 44100
    num_channels = 2
    bits_per_sample = 16
    data_size = 4  # 1 stereo sample
    header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF', 36 + data_size, b'WAVE',
        b'fmt ', 16, 1, num_channels, sample_rate,
        sample_rate * num_channels * (bits_per_sample // 8),
        num_channels * (bits_per_sample // 8), bits_per_sample,
        b'data', data_size,
    )
    wav_bytes = header + b'\x00' * data_size
    return base64.b64encode(wav_bytes).decode('ascii')


def test_collect_audio_saves_wav(tmp_path, monkeypatch):
    monkeypatch.setattr('main.AUDIO_DIR', tmp_path / 'audio')
    b64 = _make_tiny_wav_b64()
    result = collect_audio("T001", b64)
    assert result != ""
    saved = Path(result)
    assert saved.exists()
    assert saved.suffix == ".wav"
    assert saved.parent == tmp_path / 'audio'
    # Verify WAV header
    with open(saved, 'rb') as f:
        assert f.read(4) == b'RIFF'


def test_collect_audio_empty_returns_empty():
    result = collect_audio("T001", "")
    assert result == ""


def test_collect_audio_none_returns_empty():
    result = collect_audio("T001", None)
    assert result == ""
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audio_collection.py::test_collect_audio_saves_wav -v`
Expected: FAIL with ImportError

**Step 3: Write implementation in `main.py`**

Add near the top with other constants:

```python
AUDIO_DIR = Path("audio")
```

Add the `collect_audio` function:

```python
def collect_audio(task_id: str, b64_wav: str | None) -> str:
    """Decode a base64 WAV string and save to audio/ directory. Returns saved path or empty string."""
    if not b64_wav:
        return ""

    import base64

    AUDIO_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = AUDIO_DIR / f"{task_id}_{timestamp}.wav"

    try:
        wav_bytes = base64.b64decode(b64_wav)
        dest.write_bytes(wav_bytes)
        log.info("Audio saved: %s (%d bytes)", dest, len(wav_bytes))
        return str(dest)
    except Exception as e:
        log.warning("Failed to save audio for task %s: %s", task_id, e)
        return ""
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_audio_collection.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add main.py tests/test_audio_collection.py
git commit -m "feat: add collect_audio function for saving WAV files"
```

---

### Task 6: Wire audio collection into the task loop

**Files:**
- Modify: `main.py:236-301` (async_main function)

**Step 1: No test for this step** (integration wiring, covered by existing architecture)

**Step 2: Update `async_main()` in `main.py`**

1. Add `audio/` clearing alongside `pics/` clearing:

```python
# Clear audio folder
if AUDIO_DIR.exists():
    shutil.rmtree(AUDIO_DIR)
    log.info("Cleared %s directory.", AUDIO_DIR)
AUDIO_DIR.mkdir(exist_ok=True)
```

2. After `collect_screenshots()`, add audio retrieval via CDP:

```python
# Collect audio if the agent recorded any
audio_b64 = ""
try:
    import json
    resp = urllib.request.urlopen(
        urllib.request.Request(
            f"{CDP_ENDPOINT}/json",
            method="GET",
        ),
        timeout=5,
    )
    pages = json.loads(resp.read())
    if pages:
        ws_url = pages[0].get("webSocketDebuggerUrl", "")
        if ws_url:
            # Use CDP Runtime.evaluate via HTTP endpoint
            import urllib.parse
            page_id = pages[0]["id"]
            eval_url = f"{CDP_ENDPOINT}/json/protocol"  # not used, use page target
            # Simpler: use the existing Chrome DevTools MCP or direct CDP HTTP
            # For simplicity, use urllib + CDP HTTP API
            eval_payload = json.dumps({
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {"expression": "window.__audioCaptureResult || ''", "returnByValue": True},
            }).encode()
            # CDP requires WebSocket, so use a lightweight approach instead:
            # Just have the agent return the audio status in mark_task_complete
except Exception as e:
    log.debug("Audio collection via CDP skipped: %s", e)
```

Actually, the simpler approach: **modify `mark_task_complete` to accept an optional `audio_data` parameter** that the agent passes after running `stop_audio_capture`. This avoids CDP WebSocket complexity.

**Revised Step 2: Simpler wiring via mark_task_complete**

In `agent.py`, update `mark_task_complete`:

```python
def mark_task_complete(status: str, summary: str, tool_context, audio_data: str = "") -> dict:
    """Mark the current task as complete and exit the retry loop.

    Args:
        status: "success" or "failed"
        summary: Brief description of what happened
        audio_data: Optional base64-encoded WAV audio data from stop_audio_capture

    Returns:
        The status, summary, and audio_data for the orchestrator.
    """
    tool_context.actions.escalate = True
    return {"status": status, "summary": summary, "audio_data": audio_data}
```

In `main.py`, update the event processing in `run_task` to extract audio_data:

```python
# Existing line that reads status:
status = fr.response.get("status", "failed")
explanation = fr.response.get("summary", "")
error = explanation if status == "failed" else ""
audio_b64 = fr.response.get("audio_data", "")
```

Update `run_task` return signature to `tuple[str, str, str, str]` (status, error, explanation, audio_b64).

In the task loop, after `collect_screenshots`:

```python
audio_path = collect_audio(task.task_id, audio_b64)
update_task_result(xlsx_path, task.task_id, screenshot_path, status, error, explanation, audio_link=audio_path)
```

**Step 3: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add main.py agent.py
git commit -m "feat: wire audio collection into task loop via mark_task_complete"
```

---

### Task 7: Update agent instructions for audio_data in mark_task_complete

**Files:**
- Modify: `agent.py` (TASK_INSTRUCTION)

**Step 1: Update instructions**

Update the "Audio capture" section in TASK_INSTRUCTION to include passing audio data:

```
## Audio capture (recording page audio output):
If the task involves a website that plays audio (music, speech, notifications, sound effects):
1. Call `start_audio_capture` to get JS that hooks the page's audio output.
2. Execute the returned JS via Playwright's `browser_evaluate` BEFORE audio starts playing.
3. Let the page play audio normally while you complete other task steps.
4. When done, call `stop_audio_capture` to get JS that finalizes the recording.
5. Execute that JS via `browser_evaluate`. The result JSON includes a short preview; the full data is on `window.__audioCaptureResult`.
6. Read `window.__audioCaptureResult` using `browser_evaluate('window.__audioCaptureResult')`.
7. Pass the base64 string as the `audio_data` parameter when calling `mark_task_complete`.
```

**Step 2: Run tests**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
git add agent.py
git commit -m "feat: update agent instructions for audio_data flow"
```

---

### Task 8: Update CLAUDE.md documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add audio capture section to CLAUDE.md**

Under the existing "Audio / Microphone Testing" section, add:

```markdown
## Audio Capture (Recording Page Output)

The agent can record audio playing on a website and save it as WAV files:

1. **`start_audio_capture` tool:** Returns JS that hooks `<audio>`/`<video>` elements and Web Audio API to intercept audio output. Must be executed via `browser_evaluate` before audio starts playing.

2. **`stop_audio_capture` tool:** Returns JS that stops recording, encodes PCM data as WAV, and stores base64 on `window.__audioCaptureResult`. Agent reads this and passes it to `mark_task_complete(audio_data=...)`.

3. **Orchestrator collection:** `main.py` decodes the base64 WAV and saves to `audio/{task_id}_{timestamp}.wav`. Path is written to `audio_link` column in the Excel spreadsheet.

Audio files are saved in the `audio/` directory (cleared at each run start, same as `pics/`).
```

Also update the Architecture section's tool list to include the two new tools.

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add audio capture documentation to CLAUDE.md"
```

---

### Task 9: Update create_sample_xlsx.py with audio task example

**Files:**
- Modify: `create_sample_xlsx.py`

**Step 1: Check current sample tasks**

Read the file and add one task that involves audio playback (e.g., testing a page that plays a sound).

**Step 2: Add sample audio task**

Add a row like:
```python
("T004", "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3", "Play the audio on this page and capture the audio output. Verify audio plays for at least 3 seconds.")
```

**Step 3: Commit**

```bash
git add create_sample_xlsx.py
git commit -m "feat: add audio playback sample task to xlsx generator"
```

---

### Task 10: Final integration test and cleanup

**Step 1: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

**Step 2: Verify no import errors**

Run: `uv run python -c "from agent import build_agent, start_audio_capture, stop_audio_capture; print('OK')"`
Run: `uv run python -c "from main import collect_audio; print('OK')"`
Expected: Both print "OK"

**Step 3: Final commit if any cleanup needed**

```bash
git add -A
git commit -m "chore: final cleanup for audio capture feature"
```
