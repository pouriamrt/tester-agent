# Tab Audio Capture Design

**Date:** 2026-02-19
**Status:** Approved

## Goal

Allow the tester-agent to save audio playing on websites it tests, producing WAV files alongside the existing screenshot captures.

## Requirements

- Capture **tab audio output** (what the site plays to the user)
- **Agent decides** when to record (based on task instructions and detected audio)
- Save as **WAV** (uncompressed, no external dependencies)
- Follow existing architecture patterns (FunctionTool returning JS, orchestrator collects artifacts)

## Approach

**Web Audio API + MediaRecorder via JS injection** (Approach 1).

Two new FunctionTools in `agent.py` that return JavaScript code. The agent executes the JS via Playwright's `browser_evaluate`, matching the pattern established by `inject_fake_audio`.

## Design

### New Tools (`agent.py`)

#### `start_audio_capture()`

Returns JS that:
1. Creates an `AudioContext` and `MediaStreamDestination`
2. Monkey-patches `HTMLMediaElement.prototype.play` to connect any `<audio>`/`<video>` element's source to the capture destination
3. Monkey-patches `AudioContext.prototype.createMediaElementSource` to tap audio routed through Web Audio API
4. Starts a `ScriptProcessorNode` that collects raw PCM float32 samples into `window.__audioCapture.chunks`
5. Sets `window.__audioCapture.active = true`

#### `stop_audio_capture()`

Returns JS that:
1. Disconnects the `ScriptProcessorNode` and restores monkey-patched methods
2. Encodes accumulated PCM chunks as a WAV file (44-byte header + 16-bit PCM data)
3. Converts WAV blob to base64 and stores on `window.__audioCaptureResult`
4. Returns the base64 string

### Agent Instructions Update

New section in `TASK_INSTRUCTION`:

```
## Audio capture:
If the task involves a website that plays audio (music, speech, notifications):
1. Call `start_audio_capture` to get JS that hooks the page's audio output.
2. Execute the JS via `browser_evaluate` BEFORE audio starts playing.
3. Let the page play audio normally.
4. When done, call `stop_audio_capture` to get JS that finalizes the recording.
5. Execute that JS via `browser_evaluate` -- it returns a base64-encoded WAV.
The orchestrator will save the audio file automatically.
```

### Orchestrator Changes (`main.py`)

1. New constant `AUDIO_DIR = Path("audio")`
2. Clear `audio/` at run start (same as `pics/`)
3. After each task completes, use CDP `Runtime.evaluate` to read `window.__audioCaptureResult`
4. If non-empty, base64-decode and save to `audio/{task_id}_{timestamp}.wav`
5. Pass audio path to `update_task_result()`

### Excel I/O Changes (`excel_io.py`)

- Add `audio_link` parameter to `update_task_result()`
- Write to new `audio_link` column in spreadsheet

### File Storage

- Directory: `audio/` (parallel to `pics/`)
- Naming: `{task_id}_{timestamp}.wav`
- Cleared at start of each run

## Files Changed

| File | Change |
|------|--------|
| `agent.py` | Add `start_audio_capture()`, `stop_audio_capture()` functions + FunctionTools; update `TASK_INSTRUCTION` |
| `main.py` | Add `AUDIO_DIR`, audio collection after each task (read base64 from page via CDP, decode, save WAV), clear `audio/` at start |
| `excel_io.py` | Add `audio_link` to `update_task_result()` and column writing |
| `CLAUDE.md` | Document audio capture tools and workflow |

## Not In Scope

- Microphone loopback capture (only tab output)
- Compressed formats (MP3, OGG) -- WAV only
- Always-on recording -- agent decides per-task
- Cross-origin iframe audio (browser security limitation)
