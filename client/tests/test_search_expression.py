import pytest
from parsetrail.core.search_expression import SearchExpressionError, match_search_string


def test_and_has_higher_precedence_than_or() -> None:
    expression = "alpha||beta&&gamma"

    assert match_search_string(expression, "alpha")
    assert not match_search_string(expression, "beta")
    assert match_search_string(expression, "beta gamma")


def test_parentheses_override_operator_precedence() -> None:
    expression = "(alpha||beta)&&gamma"

    assert not match_search_string(expression, "alpha")
    assert match_search_string(expression, "alpha gamma")


def test_quoted_phrase_is_one_literal_and_matching_is_case_insensitive() -> None:
    assert match_search_string('bank&&"Account Summary"', "BANK\nAccount Summary")
    assert not match_search_string('bank&&"Account Summary"', "bank account monthly summary")


def test_quotes_inside_an_unquoted_literal_remain_literal_content() -> None:
    expression = '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN">'
    assert match_search_string(expression, expression)


@pytest.mark.parametrize(
    "expression",
    ["", "alpha&&", "||alpha", "alpha beta", "alpha&(beta)", "(alpha||beta", '"unterminated'],
)
def test_rejects_malformed_expressions(expression: str) -> None:
    if expression == "alpha beta":
        assert match_search_string(expression, "alpha beta")
        return
    with pytest.raises(SearchExpressionError):
        match_search_string(expression, "alpha beta")
