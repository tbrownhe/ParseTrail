"""Automatic account binding stays scoped and obeys the global preference."""

from parsetrail.core.settings import AppSettings
from parsetrail.core.v2_account_matching import LedgerAccountCandidate, match_source_account


def candidate(account_id: str, number: str, *, institution: str = "citi", kind: str = "liability"):
    return LedgerAccountCandidate(account_id, institution, kind, number)


def decide(settings: AppSettings, *candidates: LedgerAccountCandidate):
    return match_source_account(
        "1234",
        "last_four",
        institution_key="citi",
        kind="liability",
        candidates=candidates,
        preferences=settings,
    )


def test_default_off_shows_enable_option_and_does_not_bind() -> None:
    settings = AppSettings()
    assert settings.allow_abbreviated_account_matching is False
    result = decide(settings, candidate("card-a", "999991234"))
    assert result.status == "review" and result.ledger_account_id is None
    assert result.suggestions == ("card-a",)
    assert result.offer_enable_abbreviated_matching


def test_enabled_unique_same_institution_and_kind_autobinds() -> None:
    settings = AppSettings(allow_abbreviated_account_matching=True)
    result = decide(
        settings,
        candidate("card-a", "999991234"),
        candidate("other-bank", "888881234", institution="other"),
        candidate("checking", "777771234", kind="asset"),
    )
    assert result.status == "automatic" and result.ledger_account_id == "card-a"


def test_ambiguous_suffix_still_requires_review_when_enabled() -> None:
    settings = AppSettings(allow_abbreviated_account_matching=True)
    result = decide(settings, candidate("card-a", "999991234"), candidate("card-b", "888881234"))
    assert result.status == "ambiguous" and result.ledger_account_id is None
    assert not result.offer_enable_abbreviated_matching


def test_opaque_never_autobinds_and_full_requires_exact_match() -> None:
    settings = AppSettings(allow_abbreviated_account_matching=True)
    candidates = (candidate("card-a", "999991234"),)
    opaque = match_source_account(
        "1234", "opaque", institution_key="citi", kind="liability", candidates=candidates, preferences=settings
    )
    exact = match_source_account(
        "999991234", "full", institution_key="citi", kind="liability", candidates=candidates, preferences=settings
    )
    assert opaque.status == "review"
    assert exact.status == "automatic" and exact.ledger_account_id == "card-a"
