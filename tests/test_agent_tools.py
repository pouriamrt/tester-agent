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
    assert js.strip().startswith("(")
    assert js.strip().endswith(")")


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
    assert "WAVE" in js
    assert "btoa" in js  # base64 encoding


def test_task_instruction_mentions_audio_capture():
    from agent import TASK_INSTRUCTION
    assert "start_audio_capture" in TASK_INSTRUCTION
    assert "stop_audio_capture" in TASK_INSTRUCTION
