"""Run current source plugins against authorized local statements without moving them."""

from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
from pathlib import Path

from loguru import logger

CLIENT_SRC = Path(__file__).resolve().parents[2] / "client" / "src"
if not CLIENT_SRC.is_dir():
    raise ImportError("Unable to import ParseTrail client modules")
sys.path.insert(0, str(CLIENT_SRC))

from parsetrail.build_plugins import compile_plugins  # noqa: E402
from parsetrail.core.parse import ParseInput, extract_pdf_features, parse_any  # noqa: E402
from parsetrail.core.parser_classification import classification_trace  # noqa: E402
from parsetrail.core.plugin_manager import PluginManager  # noqa: E402
from parsetrail.core.utils import PDFReader  # noqa: E402


def _fixture_label(path: Path, data: bytes, index: int, *, show_filename: bool) -> str:
    if show_filename:
        return path.name
    digest = hashlib.sha256(data).hexdigest()[:12]
    return f"fixture-{index:03d}-{digest}{path.suffix.lower()}"


def _routing_diagnostic(parse_input: ParseInput, plugin_manager: PluginManager) -> str:
    if parse_input.suffix != ".pdf":
        return f"routing trace unavailable for unsupported suffix {parse_input.suffix}"
    with PDFReader(parse_input.data, parse_input.path_hint) as reader:
        trace = classification_trace(extract_pdf_features(reader), plugin_manager.metadata)

    def candidates(values: tuple[str, ...]) -> str:
        return ",".join(values) if values else "<none>"

    return (
        f"suffix=[{candidates(trace.suffix_candidates)}] "
        f"metadata=[{candidates(trace.metadata_candidates)}] "
        f"header=[{candidates(trace.header_candidates)}] "
        f"body=[{candidates(trace.body_candidates)}]"
    )


def run(
    statement_dir: Path,
    *,
    accept_warnings: bool = False,
    show_filenames: bool = False,
    diagnose_routing: bool = False,
) -> int:
    statement_dir = statement_dir.expanduser().resolve()
    if not statement_dir.is_dir():
        raise FileNotFoundError(f"Statement directory does not exist: {statement_dir}")
    statement_paths = sorted((path for path in statement_dir.iterdir() if path.is_file()), key=lambda path: path.name)
    if not statement_paths:
        raise FileNotFoundError(f"Statement directory contains no files: {statement_dir}")

    failures: list[tuple[str, str]] = []
    successes: dict[str, int] = {}
    with tempfile.TemporaryDirectory(prefix="parsetrail-source-plugins-") as plugin_temp:
        plugin_dir = Path(plugin_temp)
        compile_plugins(plugin_dir)
        plugin_manager = PluginManager(plugin_dir=plugin_dir, allow_unsigned=True)
        plugin_manager.load_plugins()

        for index, path in enumerate(statement_paths, start=1):
            data = path.read_bytes()
            label = _fixture_label(path, data, index, show_filename=show_filenames)
            parse_input = ParseInput(name=path.name, suffix=path.suffix.lower(), data=data)
            try:
                result = parse_any(plugin_manager, parse_input)
                result.require_statement(accept_warnings=accept_warnings)
                successes[result.plugin_name] = successes.get(result.plugin_name, 0) + 1
                logger.success("Parsed {} with {}", label, result.plugin_name)
            except Exception as exc:
                failures.append((label, str(exc)))
                logger.error("Failed {}: {}", label, exc)
                if diagnose_routing:
                    try:
                        logger.info("Routing trace for {}: {}", label, _routing_diagnostic(parse_input, plugin_manager))
                    except Exception as diagnostic_error:
                        logger.warning("Routing trace unavailable for {}: {}", label, type(diagnostic_error).__name__)
            finally:
                parse_input.data = b""
                data = b""

    logger.info("Processed {} statements; {} failures.", len(statement_paths), len(failures))
    for plugin_name, count in sorted(successes.items()):
        logger.info("[PASS] {}: {}", plugin_name, count)
    for label, error in failures:
        logger.error("[FAIL] {}: {}", label, error)
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("statement_dir", type=Path)
    parser.add_argument("--accept-warnings", action="store_true")
    parser.add_argument("--show-filenames", action="store_true")
    parser.add_argument("--diagnose-routing", action="store_true")
    args = parser.parse_args()
    try:
        return run(
            args.statement_dir,
            accept_warnings=args.accept_warnings,
            show_filenames=args.show_filenames,
            diagnose_routing=args.diagnose_routing,
        )
    except (OSError, ValueError) as exc:
        logger.error("Local statement batch could not start: {}", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
