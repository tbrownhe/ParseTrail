from pathlib import Path

from parsetrail.core.parser_classification import (
    DocumentFeatures,
    matching_plugins,
    normalize_pdf_metadata,
)
from parsetrail.core.plugin_loader import load_plugin


def test_classification_tree_uses_suffix_metadata_header_then_body() -> None:
    catalog = {
        "specific": {
            "SUFFIX": ".pdf",
            "SEARCH_STRING": "institution",
            "ROUTING_RULE": {
                "pdf_metadata_keys": ["Creator", "Producer"],
                "pdf_metadata": {"Creator": "statement engine"},
                "header": '"sale post description amount"',
            },
        },
        "wrong_header": {
            "SUFFIX": ".pdf",
            "SEARCH_STRING": "institution",
            "ROUTING_RULE": {"header": '"transaction detail"'},
        },
        "wrong_format": {"SUFFIX": ".csv", "SEARCH_STRING": "institution"},
    }
    features = DocumentFeatures(
        suffix=".pdf",
        body_text="Institution monthly statement",
        header_text="Sale Post Description Amount",
        pdf_metadata=normalize_pdf_metadata({"Creator": "Statement Engine 4", "Producer": "PDF Producer"}),
        page_count=3,
    )

    assert matching_plugins(features, catalog) == ("specific",)


def test_document_features_repr_never_contains_statement_content() -> None:
    features = DocumentFeatures(
        suffix=".pdf",
        body_text="private extracted text",
        header_text="private header",
        pdf_metadata={"author": "private author"},
    )

    representation = repr(features)
    assert "private" not in representation
    assert "body_text" not in representation
    assert "pdf_metadata" not in representation


def test_citi_layout_headers_route_to_one_plugin_each() -> None:
    plugin_dir = Path(__file__).parents[1] / "src" / "parsetrail" / "plugins"
    catalog = {}
    for plugin_path in sorted(plugin_dir.glob("pdf_citicc_*.py")):
        plugin_id, _, metadata = load_plugin(plugin_path)
        catalog[plugin_id] = metadata

    cases = {
        "Date Description Amount": "pdf_citicc_201505",
        "Trans. Post Description Amount": "pdf_citicc_202506",
        "Sale Post Description Amount": "pdf_citicc_202511",
    }
    for header, expected in cases.items():
        features = DocumentFeatures(
            suffix=".pdf",
            body_text="www.citicards.com",
            header_text=header,
        )
        assert matching_plugins(features, catalog) == (expected,)
