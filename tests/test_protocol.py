from __future__ import annotations

import pytest

from custom_components.daybetter_p0c6.api import (
    append_crc16,
    build_rgb_command,
    crc16_modbus,
    ensure_crc16,
    verify_crc16,
)

CAPTURED_FRAMES = [
    "A0041A6666FF0102030405060708090A0B0C0D0E0F10111213144FC1",
    "A0041A9933FF0102030405060708090A0B0C0D0E0F10111213148537",
    "A0110401B121",
    "A011040070E1",
    "A0100401E0E1",
    "A009042270FF",
    "A0090428F0F8",
    "a1110401b0dd",
    "a1040401a119",
    "a109040130da",
]


@pytest.mark.parametrize("hex_frame", CAPTURED_FRAMES)
def test_captured_frames_verify_crc16_modbus(hex_frame: str) -> None:
    raw = bytes.fromhex(hex_frame)
    assert verify_crc16(raw) is True
    assert append_crc16(raw[:-2]) == raw


def test_build_rgb_command_matches_captured_samples() -> None:
    assert (
        build_rgb_command(0x66, 0x66, 0xFF)
        == "A0041A6666FF0102030405060708090A0B0C0D0E0F10111213144FC1"
    )
    assert (
        build_rgb_command(0x99, 0x33, 0xFF)
        == "A0041A9933FF0102030405060708090A0B0C0D0E0F10111213148537"
    )


def test_build_rgb_command_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        build_rgb_command(256, 0, 0)
    with pytest.raises(ValueError):
        build_rgb_command(0, -1, 0)


def test_verify_crc16_detects_corruption() -> None:
    corrupted = bytearray(bytes.fromhex("A0110401B121"))
    corrupted[-1] ^= 0xFF
    assert verify_crc16(bytes(corrupted)) is False
    assert verify_crc16(b"\x01\x02") is False
    assert crc16_modbus(bytes.fromhex("A0110401")) == 0x21B1


def test_ensure_crc16_preserves_complete_and_pads_classic_templates() -> None:
    assert ensure_crc16("a009042270ff") == "A009042270FF"
    padded = ensure_crc16("A009082A070200")
    raw = bytes.fromhex(padded)
    assert len(raw) == 10
    assert raw[:8] == bytes.fromhex("A009082A07020032")
    assert verify_crc16(raw) is True

    fast = bytes.fromhex(ensure_crc16("A009082A070200", speed=80))
    assert fast[:8] == bytes.fromhex("A009082A07020050")
    assert verify_crc16(fast) is True
