# tests/test_audio_collection.py
import base64
import struct
from pathlib import Path
from main import collect_audio


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
