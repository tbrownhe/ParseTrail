"""Replacement card identities retain separate source facts on one chosen account."""

from datetime import date

from parsetrail.core.v2_dual_text_card_lines import parse_dual_text_card
from parsetrail.core.v2_format_recognition import FormatRecognition, candidate_from_evidence, catalog_digest
from parsetrail.core.v2_import_accounts import ImportAccountChoice, build_import_account_review, prepare_import_accounts
from parsetrail.core.v2_pdf_lines import page_lines
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore

from devtools.parser_engine_pilot.test_dual_text_card_lines import DEFINITION, channels

from .test_v2_source_account_context import _catalog


def replacement_source(number):
    printed = " ".join(number[index : index + 4] for index in range(0, 16, 4))
    original, simple = channels({0: f"Open Date: 01/01/2026 Closing Date: 01/31/2026 Account: {printed}"})
    source = f"%PDF-public-replacement-card-{number}".encode()
    layout = page_lines(
        source, ["\n".join(line.raw for line in original.lines)], extraction_library=original.extraction_library
    )
    plain = page_lines(
        source, ["\n".join(line.raw for line in simple.lines)], extraction_library=simple.extraction_library
    )
    return source, parse_dual_text_card(DEFINITION, layout, plain)


def test_five_printed_numbers_bind_one_account_only_after_each_explicit_choice(tmp_path):
    catalog = _catalog(tmp_path / "catalog", (DEFINITION,), institution="usbank", kind="liability")
    numbers = tuple(f"123456789012{ending}" for ending in ("1111", "2222", "3333", "4444", "5555"))
    path = tmp_path / "replacement-card.db"
    sources = []
    with V2ProfileStore.create(path) as store:
        store.add_financial_account(
            FinancialAccount(
                "card",
                "My continuing card account",
                "liability",
                "usbank",
                full_account_number=numbers[0],
                product_type="credit_card",
            )
        )
        for index, number in enumerate(numbers):
            source, evidence = replacement_source(number)
            candidate = candidate_from_evidence(catalog.definitions[0], evidence, catalog)
            recognition = FormatRecognition(evidence.source_sha256, ".pdf", catalog_digest(catalog), (candidate,))
            review = build_import_account_review(store, recognition, catalog, preferences=V2Preferences())
            group = review.groups[0]
            assert group.source_identity == number
            assert group.automatic == (index == 0)  # A new number never becomes an inferred alias.
            plan = prepare_import_accounts(review, (ImportAccountChoice(group.group_id, "card"),), evidence.parser_id)
            assert plan.choices[0].account_id == "card"
            store.import_source(source, DEFINITION, evidence, suffix=".pdf")
            store.bind_source_account(evidence.source_sha256, number, "full", "card")
            if index == 0:
                store.lock_pdf_import_account("card", evidence.source_sha256)
            remembered = build_import_account_review(store, recognition, catalog, preferences=V2Preferences())
            assert remembered.groups[0].automatic and remembered.groups[0].suggested_account_id == "card"
            sources.append((source, evidence))
        assert store.financial_accounts()[0].full_account_number == numbers[0]
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    with V2ProfileStore.open(path, read_only=True) as store:
        assert len(store.financial_accounts()) == 1
        assert len(store.document_summaries()) == 5
        assert len(store.account_positions(as_of=date(2026, 1, 31)).accounts) == 1
        for source, evidence in sources:
            saved = store.load_import(evidence.source_sha256)
            assert saved.source == source and saved.evidence == evidence
            binding = store.source_account_bindings(evidence.source_sha256)[0]
            assert binding.source_identity in numbers and binding.ledger_account_id == "card"
