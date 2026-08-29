"""
Headless batch parser to regression-test ready statements against current plugins.

Runs through statement_uploads rows with plugin_status='ready', decrypts each,
and attempts to parse via the in-memory parse pipeline. Summarizes failures.
"""

import argparse

# Make the client modules importable
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from aes import decrypt_statement
from db import get_sessionmaker
from loguru import logger
from orm import StatementUploads
from settings import require_runtime_settings, settings

CLIENT_SRC = Path(__file__).resolve().parents[2] / "client" / "src"
if not CLIENT_SRC.exists():
    raise ImportError("Unable to import ParseTrail client modules")
sys.path.insert(0, str(CLIENT_SRC))

try:
    from parsetrail.build_plugins import compile_plugins  # noqa: E402
    from parsetrail.core.parse import ParseInput, extract_pdf_features, parse_any  # noqa: E402
    from parsetrail.core.parser_classification import classification_trace  # noqa: E402
    from parsetrail.core.plugin_manager import PluginManager  # noqa: E402
    from parsetrail.core.utils import PDFReader  # noqa: E402
except Exception as e:  # pragma: no cover - optional dependency
    logger.warning(f"Unable to import ParseTrail client modules: {e}")
    raise


def _iter_rows(
    session_maker,
    ids: Sequence[int] | None = None,
    limit: int | None = None,
    status: str = "ready",
) -> Iterable[StatementUploads]:
    with session_maker() as session:
        q = session.query(StatementUploads)
        if status != "all":
            q = q.filter(StatementUploads.plugin_status == status)
        if ids:
            q = q.filter(StatementUploads.id.in_(ids))
        if limit:
            q = q.limit(limit)
        yield from q.order_by(StatementUploads.id.asc())


def _routing_diagnostic(plaintext: bytes, row: StatementUploads, metadata: dict, plugin_manager: PluginManager) -> str:
    parse_input = ParseInput.from_decrypted(plaintext, row.file_name, metadata)
    if parse_input.suffix != ".pdf":
        return f"routing trace unavailable for unsupported suffix {parse_input.suffix}"
    with PDFReader(parse_input.data, parse_input.path_hint) as reader:
        features = extract_pdf_features(reader)
    trace = classification_trace(features, plugin_manager.metadata)

    def candidates(values: tuple[str, ...]) -> str:
        return ",".join(values) if values else "<none>"

    return (
        f"suffix=[{candidates(trace.suffix_candidates)}] "
        f"metadata=[{candidates(trace.metadata_candidates)}] "
        f"header=[{candidates(trace.header_candidates)}] "
        f"body=[{candidates(trace.body_candidates)}]"
    )


def _parse_row(
    row: StatementUploads,
    plugin_manager: PluginManager,
    *,
    accept_warnings: bool = False,
    diagnose_routing: bool = False,
):
    plaintext, metadata = decrypt_statement(row)
    try:
        parse_input = ParseInput.from_decrypted(plaintext, row.file_name, metadata)
        result = parse_any(plugin_manager, parse_input)
        return result.require_statement(accept_warnings=accept_warnings)
    except Exception:
        if diagnose_routing:
            try:
                logger.info(
                    "Routing trace for submission id={}: {}",
                    row.id,
                    _routing_diagnostic(plaintext, row, metadata, plugin_manager),
                )
            except Exception as diagnostic_error:
                logger.warning(
                    "Routing trace unavailable for submission id={}: {}",
                    row.id,
                    type(diagnostic_error).__name__,
                )
        raise
    finally:
        plaintext = b""


def run(
    ids: Sequence[int] | None = None,
    limit: int | None = None,
    *,
    accept_warnings: bool = False,
    status: str = "ready",
    diagnose_routing: bool = False,
) -> int:
    require_runtime_settings()
    plugin_dir = Path(settings.PLUGINS_DIR).expanduser().resolve()
    compile_plugins(plugin_dir)
    plugin_manager = PluginManager(plugin_dir=plugin_dir, allow_unsigned=True)
    plugin_manager.load_plugins()

    failures: list[tuple[int, str]] = []
    total = 0

    session_maker = get_sessionmaker()
    for row in _iter_rows(session_maker, ids, limit, status):
        total += 1
        try:
            _parse_row(
                row,
                plugin_manager,
                accept_warnings=accept_warnings,
                diagnose_routing=diagnose_routing,
            )
            logger.success(f"Parsed statement submission id={row.id}")
        except Exception as e:
            err = str(e)
            failures.append((row.id, err))
            logger.error(f"Failed statement submission id={row.id}: {err}")

    logger.info(f"Processed {total} statements; {len(failures)} failures.")
    if failures:
        for sid, err in failures:
            logger.error(f"[FAIL] id={sid}: {err}")
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description="Batch test parsing for ready statements.")
    parser.add_argument("--ids", nargs="*", type=int, help="Optional specific statement IDs to run.")
    parser.add_argument("--limit", type=int, help="Optional limit on number of statements.")
    parser.add_argument(
        "--status",
        choices=("ready", "pending", "all"),
        default="ready",
        help="Submission status to test (default: ready).",
    )
    parser.add_argument(
        "--accept-warnings",
        action="store_true",
        help="Treat validated parses with warnings as successful.",
    )
    parser.add_argument(
        "--diagnose-routing",
        action="store_true",
        help="Log redacted candidate IDs at each routing stage for failures.",
    )
    args = parser.parse_args()
    exit_code = run(
        ids=args.ids,
        limit=args.limit,
        accept_warnings=args.accept_warnings,
        status=args.status,
        diagnose_routing=args.diagnose_routing,
    )
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
