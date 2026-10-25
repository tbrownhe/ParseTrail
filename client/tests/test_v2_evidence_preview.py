"""Read-only 2.0 preview displays uncertainty from reopened source evidence."""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path

from parsetrail.core.v2_citi_source_output import from_citi
from parsetrail.core.v2_legacy_citi_lines import parse_legacy_citi
from parsetrail.core.v2_profile_store import SavedImport, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_synchrony_source_output import from_synchrony_table
from parsetrail.gui.v2_evidence_preview import V2EvidencePreview, preview_saved_source
from PySide6.QtWidgets import QApplication, QLabel, QTabWidget

from devtools.parser_engine_pilot.preview_source import main as preview_main
from devtools.parser_engine_pilot.test_citi_source_output import DEFINITION_BYTES as RECENT_CITI_DEFINITION
from devtools.parser_engine_pilot.test_citi_source_output import sample as recent_citi_sample
from devtools.parser_engine_pilot.test_legacy_citi_lines import DEFINITION as CITI_DEFINITION
from devtools.parser_engine_pilot.test_legacy_citi_lines import lines as citi_lines
from devtools.parser_engine_pilot.test_synchrony_source_output import DEFINITION as CARD_DEFINITION
from devtools.parser_engine_pilot.test_synchrony_source_output import SOURCE as CARD_SOURCE
from devtools.parser_engine_pilot.test_synchrony_source_output import channels as card_channels

DEFINITION = Path(__file__).parents[2] / "devtools" / "parser_engine_pilot" / "mohela-account-history-definition.json"
SOURCE = (
    b'<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN">'
    b"Date,Description,Principal,Interest,Fees,Total,\n"
    b"10/01/2026,Payment,-$80.00,-$20.00,$0.00,-$100.00,\n"
)


def test_preview_reopens_unknown_account_without_writing_profile(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    profile = tmp_path / "v2.db"
    definition = DEFINITION.read_bytes()
    evidence = build_source_evidence(SOURCE, definition, suffix=".csv")
    with V2ProfileStore.create(profile) as store:
        assert store.import_source(SOURCE, definition, evidence, suffix=".csv")
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    dialog = preview_saved_source(profile, evidence.source_sha256)
    try:
        labels = dialog.findChildren(QLabel)
        assert any("This preview shows saved source evidence" in label.text() for label in labels)
        assert any("Source capture needs review" in label.text() for label in labels)
        assert dialog.rows_model.rowCount() == 1
        assert dialog.rows_model.data(dialog.rows_model.index(0, 3)) == "Not identified by source"
        assert dialog.rows_model.data(dialog.rows_model.index(0, 5)) == "-$100.00"
        assert dialog.findChild(QTabWidget).count() == 2
    finally:
        dialog.close()
        app.processEvents()
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before


def test_synthetic_preview_launcher_uses_disposable_profile(monkeypatch) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.gui.v2_evidence_preview import V2EvidencePreview

    opened = []
    monkeypatch.setattr(
        V2EvidencePreview,
        "exec",
        lambda self: opened.append((self.rows_model.rowCount(), self.dispositions_model.rowCount())),
    )
    assert preview_main(["--demo"]) == 0
    assert opened == [(5, 1)]


def test_preview_shows_statement_balance_check_and_dispositions(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    evidence = from_synchrony_table(CARD_DEFINITION, *card_channels())
    profile = tmp_path / "statement.db"
    with V2ProfileStore.create(profile) as store:
        store.import_source(CARD_SOURCE, CARD_DEFINITION, evidence, suffix=".pdf")
    dialog = preview_saved_source(profile, evidence.source_sha256)
    try:
        assert any("Printed balance equation passed" in label.text() for label in dialog.findChildren(QLabel))
        assert dialog.rows_model.rowCount() == 1
        assert dialog.dispositions_model.rowCount() == 4
        assert dialog.rows_model.data(dialog.rows_model.index(0, 0)) == "2025-12-31 (derived from source)"
        assert dialog.rows_model.data(dialog.rows_model.index(0, 2)) == "2026-01-01 (assumed)"
    finally:
        dialog.close()
        app.processEvents()


def test_preview_surfaces_unclassified_dollar_lines(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    evidence = parse_legacy_citi(CITI_DEFINITION, citi_lines(extra=("Offer balance $2.34",)))
    profile = tmp_path / "older-citi.db"
    with V2ProfileStore.create(profile) as store:
        store.import_source(b"%PDF-synthetic", CITI_DEFINITION, evidence, suffix=".pdf")
    dialog = preview_saved_source(profile, evidence.source_sha256)
    try:
        assert any("Unclassified dollar lines: 1" in label.text() for label in dialog.findChildren(QLabel))
        assert dialog.dispositions_model.rowCount() >= 1
    finally:
        dialog.close()
        app.processEvents()


def test_preview_separates_recent_citi_unclassified_page_text() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    source = replace(recent_citi_sample(), simple_text_pages=("01/02 01/02 SHOP $10.00\nGeneral notice",))
    evidence = from_citi(source, RECENT_CITI_DEFINITION)
    dialog = V2EvidencePreview(SavedImport(b"synthetic", RECENT_CITI_DEFINITION, evidence, ".pdf"))
    try:
        assert any("Unclassified page text lines: 1" in label.text() for label in dialog.findChildren(QLabel))
        assert dialog.unclassified_text_model.rowCount() == 1
        assert dialog.unclassified_text_model.data(dialog.unclassified_text_model.index(0, 2)) == "General notice"
        tabs = dialog.findChild(QTabWidget)
        assert tabs.tabText(2) == "Unclassified page text"
    finally:
        dialog.close()
        app.processEvents()
