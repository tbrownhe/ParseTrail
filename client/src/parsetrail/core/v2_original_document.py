"""Verified ordinary local originals in private, session-owned temporary files."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
import threading
import time
from pathlib import Path
from uuid import uuid4

from parsetrail.core.v2_profile_store import MAX_SOURCE_BYTES, SavedImport, V2ProfileStore

STALE_AFTER_SECONDS = 24 * 60 * 60
MAX_SESSION_FILES = 128
MAX_SESSION_BYTES = 256 * 1024 * 1024
_SESSION_NAME = re.compile(r"session-[0-9a-f]{32}\Z")
_FILE_NAME = re.compile(r"(?:original-[0-9a-f]{32}\.(?:pdf|csv)|partial-[0-9a-f]{32})\Z")
_LEASE_CONTENT = b"ParseTrail local originals v1\n"


class OriginalDocumentError(ValueError):
    """An original cannot be safely prepared or cleaned up."""


def _plain(path: Path, *, directory: bool = False):
    info = path.lstat()
    if (
        stat.S_ISLNK(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
    ):
        raise OriginalDocumentError("temporary_path_is_not_a_plain_directory_or_file")
    return info


def _windows_private(path: Path) -> None:
    """Accept only this user's owner SID and standard user/admin/system allow ACEs."""
    import ctypes
    from ctypes import wintypes

    api = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    pointer = ctypes.c_void_p
    api.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(pointer),
        ctypes.POINTER(pointer),
        ctypes.POINTER(pointer),
        ctypes.POINTER(pointer),
        ctypes.POINTER(pointer),
    ]
    api.GetNamedSecurityInfoW.restype = wintypes.DWORD
    api.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    api.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        pointer,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    api.EqualSid.argtypes = [pointer, pointer]
    api.GetAclInformation.argtypes = [pointer, pointer, wintypes.DWORD, ctypes.c_int]
    api.GetAce.argtypes = [pointer, wintypes.DWORD, ctypes.POINTER(pointer)]
    api.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(pointer)]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [pointer]
    owner, acl, descriptor = pointer(), pointer(), pointer()
    token = wintypes.HANDLE()
    allowed = []
    try:
        if api.GetNamedSecurityInfoW(
            str(path), 1, 5, ctypes.byref(owner), None, ctypes.byref(acl), None, ctypes.byref(descriptor)
        ):
            raise OriginalDocumentError("temporary_permissions_unavailable")
        if not api.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
            raise OriginalDocumentError("temporary_owner_unavailable")
        size = wintypes.DWORD()
        api.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        user = ctypes.create_string_buffer(size.value)
        if not api.GetTokenInformation(token, 1, user, size, ctypes.byref(size)):
            raise OriginalDocumentError("temporary_owner_unavailable")
        current_sid = pointer.from_buffer(user)
        if not owner or not api.EqualSid(owner, current_sid):
            raise OriginalDocumentError("temporary_directory_has_another_owner")
        for value in ("S-1-5-18", "S-1-5-32-544", "S-1-3-4"):
            sid = pointer()
            if not api.ConvertStringSidToSidW(value, ctypes.byref(sid)):
                raise OriginalDocumentError("temporary_permissions_unavailable")
            allowed.append(sid)
        if not acl:
            raise OriginalDocumentError("temporary_directory_is_not_private")
        information = (wintypes.DWORD * 3)()
        if not api.GetAclInformation(acl, information, ctypes.sizeof(information), 2) or not information[0]:
            raise OriginalDocumentError("temporary_permissions_unavailable")
        for index in range(information[0]):
            ace = pointer()
            if not api.GetAce(acl, index, ctypes.byref(ace)):
                raise OriginalDocumentError("temporary_permissions_unavailable")
            # Standard ACCESS_ALLOWED_ACE: header(4), mask(4), SID.
            if ctypes.c_ubyte.from_address(ace.value).value != 0:
                raise OriginalDocumentError("temporary_directory_has_unexpected_permissions")
            sid = pointer(ace.value + 8)
            if not any(api.EqualSid(sid, candidate) for candidate in (current_sid, *allowed)):
                raise OriginalDocumentError("temporary_directory_is_not_private")
    finally:
        for sid in allowed:
            kernel.LocalFree(sid)
        if token:
            kernel.CloseHandle(token)
        if descriptor:
            kernel.LocalFree(descriptor)


def _private_directory(path: Path) -> None:
    info = _plain(path, directory=True)
    if os.name == "nt":
        _windows_private(path)
    elif info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise OriginalDocumentError("temporary_directory_is_not_private")


def _lock(descriptor: int) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _open_lease(path: Path) -> int:
    _plain(path)
    descriptor = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    try:
        if os.read(descriptor, 128) != _LEASE_CONTENT:
            raise OriginalDocumentError("temporary_session_marker_invalid")
        _lock(descriptor)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _session_files(directory: Path) -> tuple[Path, ...]:
    _private_directory(directory)
    files = tuple(directory.iterdir())
    for path in files:
        if path.name != ".lease" and _FILE_NAME.fullmatch(path.name) is None:
            raise OriginalDocumentError("temporary_session_has_unexpected_contents")
        _plain(path)
    if not any(path.name == ".lease" for path in files):
        raise OriginalDocumentError("temporary_session_marker_missing")
    return files


def _remove_session(directory: Path, descriptor: int) -> bool:
    """Delete only recognized plain files, never a recursive or following sweep."""
    try:
        files = _session_files(directory)
        for path in files:
            if path.name != ".lease":
                path.unlink()
    except (OSError, OriginalDocumentError):
        os.close(descriptor)
        return False
    os.close(descriptor)
    try:
        (directory / ".lease").unlink()
        directory.rmdir()
    except OSError:
        return False
    return True


def collect_stale_originals(root: Path, *, now: float | None = None) -> int:
    """Collect our old, unlocked sessions; leave live, young and unfamiliar paths alone."""
    _private_directory(root)
    cutoff = (time.time() if now is None else now) - STALE_AFTER_SECONDS
    removed = 0
    for directory in root.iterdir():
        if _SESSION_NAME.fullmatch(directory.name) is None:
            continue
        descriptor = None
        try:
            files = _session_files(directory)
            if max((directory.stat().st_mtime, *(path.stat().st_mtime for path in files))) >= cutoff:
                continue
            descriptor = _open_lease(directory / ".lease")
        except (OSError, OriginalDocumentError):
            continue
        if descriptor is not None and _remove_session(directory, descriptor):
            removed += 1
    return removed


def read_saved_original(profile: Path, source_sha256: str, *, cancelled=lambda: False) -> SavedImport:
    if cancelled():
        raise OriginalDocumentError("original_open_cancelled")
    with V2ProfileStore.open(profile, read_only=True) as store:
        store.connection.set_progress_handler(lambda: int(cancelled()), 1000)
        saved = store.load_import(source_sha256)
    if cancelled():
        raise OriginalDocumentError("original_open_cancelled")
    return saved


class OriginalDocumentSession:
    """Retain successful opens for this session; never infer an external viewer's exit."""

    def __init__(self, root: Path | None = None):
        if root is None:
            identity = str(os.getuid()) if hasattr(os, "getuid") else "local"
            root = Path(tempfile.gettempdir()) / f"parsetrail-originals-v2-{identity}"
        self.root = root.absolute()
        _plain(self.root.parent, directory=True)
        try:
            self.root.mkdir(mode=0o700)
        except FileExistsError:
            pass
        _private_directory(self.root)
        collect_stale_originals(self.root)
        self.directory = self.root / f"session-{uuid4().hex}"
        self.directory.mkdir(mode=0o700)
        _private_directory(self.directory)
        self._mutex = threading.Lock()
        self._closed = False
        self._lease = os.open(self.directory / ".lease", os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(self._lease, _LEASE_CONTENT)
        _lock(self._lease)
        self._published: set[Path] = set()
        self._sizes: dict[Path, int] = {}

    def materialize(self, saved: SavedImport) -> Path:
        if (
            not isinstance(saved, SavedImport)
            or saved.suffix not in {".pdf", ".csv"}
            or type(saved.source) is not bytes
            or not 0 < len(saved.source) <= MAX_SOURCE_BYTES
            or hashlib.sha256(saved.source).hexdigest() != saved.evidence.source_sha256
            or hashlib.sha256(saved.definition).hexdigest() != saved.evidence.definition_sha256
        ):
            raise OriginalDocumentError("saved_original_is_invalid")
        with self._mutex:
            if self._closed:
                raise OriginalDocumentError("original_session_closed")
            if (
                len(self._published) >= MAX_SESSION_FILES
                or sum(self._sizes.values()) + len(saved.source) > MAX_SESSION_BYTES
            ):
                raise OriginalDocumentError("original_session_limit_reached")
            _private_directory(self.root)
            _private_directory(self.directory)
            partial = self.directory / f"partial-{uuid4().hex}"
            destination = self.directory / f"original-{uuid4().hex}{saved.suffix}"
            descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(saved.source)
                    stream.flush()
                    os.fsync(stream.fileno())
                if hashlib.sha256(partial.read_bytes()).hexdigest() != saved.evidence.source_sha256:
                    raise OriginalDocumentError("temporary_original_integrity")
                os.link(partial, destination)
                self._published.add(destination)
                self._sizes[destination] = len(saved.source)
                return destination
            finally:
                partial.unlink(missing_ok=True)

    def discard(self, path: Path) -> None:
        with self._mutex:
            if path not in self._published:
                raise OriginalDocumentError("original_path_is_not_session_owned")
            _private_directory(self.root)
            _private_directory(self.directory)
            _plain(path)
            path.unlink()
            self._published.remove(path)
            self._sizes.pop(path, None)

    def close(self) -> bool:
        with self._mutex:
            if self._closed:
                return not self.directory.exists()
            self._closed = True
            try:
                _private_directory(self.root)
            except (OSError, OriginalDocumentError):
                os.close(self._lease)
                return False
            return _remove_session(self.directory, self._lease)
