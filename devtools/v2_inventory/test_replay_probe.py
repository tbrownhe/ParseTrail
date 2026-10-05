"""Read-only source-registry and replay-summary safeguards."""

from __future__ import annotations

import pytest

from devtools.v2_inventory.replay_probe import SourceRegistry, parser_bindings, summarize


def test_checkout_registry_includes_every_source_parser() -> None:
    registry = SourceRegistry()
    assert len(registry.classes) == 22
    assert "pdf_synchrony-amzncc_202501" in registry.classes
    assert all(registry.metadata[name]["PLUGIN_NAME"] == name for name in registry.classes)


def test_replay_summary_conserves_verified_expense_assertions() -> None:
    legacy = {"Statements": [{}], "Transactions": [{}, {}]}
    evidence = {
        "files": {"source": {"status": "parsed", "plugin": "synthetic"}},
        "statements": {"statement": {}},
        "transactions": {"a": {}, "b": {}},
        "unreferenced_archive_files": ["failed.txt"],
    }
    categories = {
        "decisions": [{"status": "restored"}, {"status": "ambiguous_match"}],
        "totals": [{"original_count": 2, "restored_count": 1, "pending_count": 1}],
    }
    result = summarize(legacy, evidence, categories)
    assert result["source_status_counts"] == {"parsed": 1}
    assert result["verified_expense_assertions"] == {
        "original": 2,
        "restored": 1,
        "pending": 1,
        "reason_counts": {"ambiguous_match": 1, "restored": 1},
    }
    categories["totals"][0]["pending_count"] = 0
    with pytest.raises(ValueError, match="conservation"):
        summarize(legacy, evidence, categories)


def test_legacy_revision_cannot_be_assumed_to_identify_one_current_layout() -> None:
    legacy = {
        "Plugins": [{"PluginID": 1, "PluginName": "legacy_citi", "Version": "0.1.0"}],
        "Statements": [
            {"StatementID": 1, "PluginID": 1},
            {"StatementID": 2, "PluginID": 1},
            {"StatementID": 3, "PluginID": 1},
        ],
    }
    evidence = {
        "legacy_sources": {"1": "source_a", "2": "source_b"},
        "files": {
            "source_a": {"status": "parsed", "plugin": "layout_a", "version": "2"},
            "source_b": {"status": "parsed", "plugin": "layout_b", "version": "2"},
        },
    }
    result = parser_bindings(legacy, evidence)
    assert result["ambiguous_legacy_revisions"] == [{"legacy_parser": "legacy_citi", "legacy_version": "0.1.0"}]
    assert result["unresolved_statement_count"] == 1
    assert {row["checkout_parser"] for row in result["bindings"]} == {"layout_a", "layout_b"}
