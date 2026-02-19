# tests/test_agent_tools.py
from agent import start_audio_capture


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
