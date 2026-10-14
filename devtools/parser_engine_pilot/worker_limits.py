"""Shared process, time and OS memory boundary for fixed decoder workers."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

MIN_MEMORY_BYTES = 128 * 1024 * 1024
MAX_MEMORY_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_MEMORY_BYTES = 512 * 1024 * 1024
MAX_INPUT_BYTES = 17 * 1024 * 1024
MAX_OUTPUT_BYTES = 32 * 1024 * 1024
WorkerModule = Literal["devtools.parser_engine_pilot.pdf_text_worker", "devtools.parser_engine_pilot.xlsx_worker"]


class WorkerError(ValueError):
    """Redacted failure; never include source or decoded values."""


@dataclass(frozen=True, slots=True)
class WorkerLimits:
    memory_bytes: int = DEFAULT_MEMORY_BYTES
    wall_seconds: float = 20.0

    def __post_init__(self) -> None:
        if (
            type(self.memory_bytes) is not int
            or not MIN_MEMORY_BYTES <= self.memory_bytes <= MAX_MEMORY_BYTES
            or type(self.wall_seconds) not in {int, float}
            or not 0.01 <= self.wall_seconds <= 120.0
        ):
            raise WorkerError("invalid_limits")


def enforce_child_memory_limit(raw: str) -> None:
    """Set POSIX address-space limit before importing a decoder library."""
    try:
        memory_bytes = int(raw)
    except ValueError:
        raise WorkerError("invalid_limits") from None
    if not MIN_MEMORY_BYTES <= memory_bytes <= MAX_MEMORY_BYTES:
        raise WorkerError("invalid_limits")
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))


class _WindowsJob:
    """Own a job that caps committed memory and kills children on close."""

    def __init__(self, memory_bytes: int) -> None:
        import ctypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in (
                    "ReadOperationCount",
                    "WriteOperationCount",
                    "OtherOperationCount",
                    "ReadTransferCount",
                    "WriteTransferCount",
                    "OtherTransferCount",
                )
            ]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimits),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p)
        self._kernel.CreateJobObjectW.restype = ctypes.c_void_p
        self._kernel.SetInformationJobObject.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        )
        self._kernel.SetInformationJobObject.restype = ctypes.c_int
        self._kernel.AssignProcessToJobObject.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        self._kernel.AssignProcessToJobObject.restype = ctypes.c_int
        self._kernel.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        self._kernel.OpenProcess.restype = ctypes.c_void_p
        self._kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
        self._kernel.CloseHandle.restype = ctypes.c_int
        self._handle = self._kernel.CreateJobObjectW(None, None)
        if not self._handle:
            raise WorkerError("memory_limit_unavailable")
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x00000100 | 0x00002000
        limits.ProcessMemoryLimit = memory_bytes
        if not self._kernel.SetInformationJobObject(self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise WorkerError("memory_limit_unavailable")

    def attach(self, pid: int) -> None:
        # PROCESS_SET_QUOTA and PROCESS_TERMINATE are required for assignment.
        process = self._kernel.OpenProcess(0x0100 | 0x0001, False, pid)
        if not process:
            raise WorkerError("memory_limit_unavailable")
        try:
            if not self._kernel.AssignProcessToJobObject(self._handle, process):
                raise WorkerError("memory_limit_unavailable")
        finally:
            self._kernel.CloseHandle(process)

    def close(self) -> None:
        if self._handle:
            self._kernel.CloseHandle(self._handle)
            self._handle = None


def run_worker(
    module: WorkerModule,
    payload: bytes,
    *,
    output_limit: int,
    limits: WorkerLimits = WorkerLimits(),
) -> bytes:
    """Run only a fixed local decoder module behind native resource limits."""
    if module not in {"devtools.parser_engine_pilot.pdf_text_worker", "devtools.parser_engine_pilot.xlsx_worker"}:
        raise WorkerError("unsupported_worker")
    if not isinstance(payload, bytes) or not payload or len(payload) > MAX_INPUT_BYTES:
        raise WorkerError("input_size")
    if not 0 < output_limit <= MAX_OUTPUT_BYTES:
        raise WorkerError("output_limit")
    if sys.platform not in {"win32", "darwin", "linux"}:
        raise WorkerError("unsupported_platform")
    job = _WindowsJob(limits.memory_bytes) if sys.platform == "win32" else None
    process = None
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", module, str(limits.memory_bytes)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=Path(__file__).resolve().parents[2],
        )
        if job is not None:
            job.attach(process.pid)
        try:
            output, _ = process.communicate(input=payload, timeout=limits.wall_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise WorkerError("timeout") from None
        if process.returncode != 0 or not output:
            raise WorkerError("worker_failed")
        if len(output) > output_limit:
            raise WorkerError("output_limit")
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate()
        if job is not None:
            job.close()
    return output
