import pytest

from mycode.matching import MatchPatternError, parse_match_pattern


def test_automatic_exact_and_glob_are_backward_compatible() -> None:
    exact = parse_match_pattern("README.md")
    glob = parse_match_pattern("git *")

    assert exact.kind == "exact" and exact.matches("README.md")
    assert not exact.matches("readme.md")
    assert glob.kind == "glob" and glob.matches("git status")
    assert not glob.matches("Git status")


def test_explicit_glob_keeps_glob_priority_without_metacharacters() -> None:
    matcher = parse_match_pattern("glob:literal")

    assert matcher.kind == "glob"
    assert matcher.matches("literal")
    assert matcher.render() == "glob:literal"


def test_regex_uses_case_sensitive_search() -> None:
    matcher = parse_match_pattern(r"re:^rm\s")

    assert matcher.kind == "regex"
    assert matcher.matches("rm file")
    assert not matcher.matches("sudo rm file")
    assert not matcher.matches("RM file")


def test_negation_inverts_existing_candidate_match() -> None:
    matcher = parse_match_pattern("glob:safe/*", negated=True)

    assert not matcher.matches("safe/file")
    assert matcher.matches("unsafe/file")


@pytest.mark.parametrize("value", ["", "re:", "glob:", "re:("])
def test_invalid_patterns_are_rejected(value: str) -> None:
    with pytest.raises(MatchPatternError):
        parse_match_pattern(value)
