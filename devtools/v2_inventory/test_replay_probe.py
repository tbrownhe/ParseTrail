"""Read-only source-registry and replay-summary safeguards."""

from __future__ import annotations

import pytest

from devtools.v2_inventory.replay_probe import SourceRegistry, summarize


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
