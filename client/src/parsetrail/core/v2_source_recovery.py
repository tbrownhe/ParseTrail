"""Recover verified embedded originals without altering the profile or replacing files."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from parsetrail.core.v2_profile_store import ProfileFormatError, V2ProfileStore


def recover_source_original(profile: Path, source_sha256: str, destination: Path) -> Path:
    """Publish an exact saved original at a new path; preserve all inputs on failure."""
    destination = destination.expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise ProfileFormatError("source_destination_exists")
    if not destination.parent.is_dir():
        raise ProfileFormatError("source_destination_parent_missing")
    with V2ProfileStore.open(profile, read_only=True) as store:
        saved = store.load_import(source_sha256)
    # load_import verifies the retained source, definition and evidence together.
    # Recheck the output bytes before publication rather than exporting a reparse.
    if hashlib.sha256(saved.source).hexdigest() != source_sha256:
        raise ProfileFormatError("saved_source_integrity")
    descriptor, partial_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".partial", dir=destination.parent
    )
    partial = Path(partial_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(saved.source)
            stream.flush()
            os.fsync(stream.fileno())
        if hashlib.sha256(partial.read_bytes()).hexdigest() != source_sha256:
            raise ProfileFormatError("recovered_source_integrity")
        try:
            os.link(partial, destination)
        except FileExistsError:
            raise ProfileFormatError("source_destination_exists") from None
        return destination.resolve()
    finally:
        partial.unlink(missing_ok=True)
