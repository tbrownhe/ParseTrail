import struct
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import release_architecture as architecture


def pe(*, machine=0x8664, magic=0x20B, flags=0x0002, offset=128):
    data = bytearray(512)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 60, offset)
    data[128:132] = b"PE\0\0"
    struct.pack_into("<H", data, 132, machine)
    struct.pack_into("<HHH", data, 148, 240, flags, magic)
    return bytes(data)


def macho(*, cpu=0x01000007, file_type=2, order="<", command_bytes=8):
    return struct.pack(order + "IIIIIIII", 0xFEEDFACF, cpu, 3, file_type, 1, command_bytes, 0, 0) + b"\0" * 8


@pytest.mark.parametrize(
    "payload,target",
    [
        (pe(), "windows-x86_64"),
        (macho(), "macos-x86_64"),
        (macho(order=">"), "macos-x86_64"),
    ],
)
def test_accepts_native_executable_headers_without_launching(tmp_path, payload, target):
    binary = tmp_path / "candidate.bin"
    binary.write_bytes(payload)
    report = architecture.verify_binary(binary, target)
    assert report["target_platform"] == target
    assert report["architecture"] == "x86_64"


@pytest.mark.parametrize(
    "payload,target",
    [
        (pe(machine=0xAA64), "windows-x86_64"),
        (pe(machine=0x14C, magic=0x10B), "windows-x86_64"),
        (pe(magic=0x10B), "windows-x86_64"),
        (pe(flags=0x2002), "windows-x86_64"),
        (pe(flags=0), "windows-x86_64"),
        (pe(offset=2**32 - 1), "windows-x86_64"),
        (pe()[:154], "windows-x86_64"),
        (macho(cpu=0x0100000C), "macos-x86_64"),
        (macho(file_type=6), "macos-x86_64"),
        (macho(command_bytes=200), "macos-x86_64"),
        (bytes.fromhex("cafebabe") + b"\0" * 64, "macos-x86_64"),
        (pe(), "macos-x86_64"),
        (macho(), "windows-x86_64"),
        (b"", "windows-x86_64"),
        (b"\xcf\xfa\xed\xfe", "macos-x86_64"),
    ],
)
def test_rejects_wrong_cpu_format_dll_universal_and_truncated_headers(tmp_path, payload, target):
    binary = tmp_path / "candidate.bin"
    binary.write_bytes(payload)
    with pytest.raises(ValueError):
        architecture.verify_binary(binary, target)


def test_package_free_cli_rejects_candidate_before_it_can_execute(tmp_path):
    binary = tmp_path / "wrong.exe"
    binary.write_bytes(pe(machine=0xAA64))
    result = subprocess.run(
        [sys.executable, "-I", "-S", architecture.__file__, "--platform", "windows-x86_64", "--binary", str(binary)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert "AMD64" in result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Inspect the real Windows CPython executable")
def test_real_windows_interpreter_reports_amd64():
    assert architecture.verify_binary(Path(sys.executable), "windows-x86_64")["format"] == "PE32+"
