import pytest
from parsetrail.core.parser_routing import first_successful_candidate


def test_returns_first_successful_candidate() -> None:
    attempted: list[str] = []

    def parse(candidate: str) -> str:
        attempted.append(candidate)
        if candidate == "first":
            raise ValueError("not this layout")
        return f"parsed by {candidate}"

    assert first_successful_candidate(["first", "second", "third"], parse, source="statement.csv") == "parsed by second"
    assert attempted == ["first", "second"]


def test_reports_every_failed_candidate() -> None:
    def fail(candidate: str) -> str:
        raise ValueError(f"{candidate} failed")

    with pytest.raises(ValueError) as exc_info:
        first_successful_candidate(["csv_a", "csv_b"], fail, source="statement.csv")

    message = str(exc_info.value)
    assert "statement.csv" in message
    assert "csv_a: csv_a failed" in message
    assert "csv_b: csv_b failed" in message


def test_rejects_empty_candidate_list() -> None:
    with pytest.raises(ValueError, match="No parser candidates"):
        first_successful_candidate([], lambda candidate: candidate, source="statement.xlsx")
