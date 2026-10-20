import unicodedata
import uuid

import pytest

from app.scan.engine import Detection, KeywordRule, count, scan


def rule(*keywords: str, threshold: int = 1, name: str = "rule", id: uuid.UUID | None = None):
    return KeywordRule(id=id or uuid.uuid4(), name=name, keywords=keywords, threshold=threshold)


def hits(keywords: str | tuple[str, ...], text: str) -> int:
    keywords = (keywords,) if isinstance(keywords, str) else keywords
    return count(rule(*keywords), text)


# --- Case and words ---


def test_case_insensitive_counts_every_casing():
    assert hits("salary", "Salary SALARY sAlArY") == 3


@pytest.mark.parametrize(
    ("keyword", "text"),
    [("ssn", "classname"), ("pass", "password"), ("ssn", "ssn_number"), ("ssn", "ssn123")],
)
def test_no_match_inside_a_word(keyword, text):
    assert hits(keyword, text) == 0


@pytest.mark.parametrize("text", ["ssn-number", "(ssn)", "ssn.", "ssn", "\nssn\n", "x ssn"])
def test_matches_at_non_word_boundaries(text):
    assert hits("ssn", text) == 1


# --- Multi-word and whitespace ---


@pytest.mark.parametrize(
    "text",
    [
        "social  security\tnumber",
        "social security\nnumber",
        "social\u00a0security number",  # NBSP is \s too
    ],
)
def test_multi_word_keyword_matches_any_whitespace_run(text):
    assert hits("social security number", text) == 1


@pytest.mark.parametrize("text", ["socialsecuritynumber", "social-security number"])
def test_multi_word_keyword_needs_whitespace_between_tokens(text):
    assert hits("social security number", text) == 0


@pytest.mark.parametrize("text", ["credit card", "credit  card", "my credit\ncard", "creditcard"])
def test_untidy_keyword_behaves_like_its_collapsed_form(text):
    assert hits("  credit   card ", text) == hits("credit card", text)


# --- Literal metacharacters and non-word edges ---


@pytest.mark.parametrize(
    ("keyword", "text", "expected"),
    [
        ("a.b", "a.b", 1),
        ("a.b", "axb", 0),
        ("C++", "I like C++ a lot", 1),
        ("C++", "C++y", 1),
        ("C++", "xC++", 0),
        ("@company.com", "john@company.com", 1),
        ("@company.com", "@company.comx", 0),
        ("$100", "cost:$100.", 1),
        ("$100", "$1000", 0),
        ("(test)", "x(test)y", 1),
    ],
)
def test_metacharacters_are_literal_and_non_word_edges_need_no_boundary(keyword, text, expected):
    assert hits(keyword, text) == expected


@pytest.mark.parametrize(("keyword", "text", "expected"), [("--", "----", 2), ("+", "C++", 2)])
def test_punctuation_only_keyword_matches_as_substring(keyword, text, expected):
    assert hits(keyword, text) == expected


# --- Overlaps and counting ---


@pytest.mark.parametrize(("text", "expected"), [("credit card", 1), ("credit card card", 2)])
def test_longest_keyword_wins_and_spans_count_once(text, expected):
    assert hits(("credit card", "card"), text) == expected


@pytest.mark.parametrize(("text", "expected"), [("credit card", 1), ("credit card card", 2)])
def test_overlap_result_does_not_depend_on_keyword_order(text, expected):
    assert hits(("card", "credit card"), text) == expected


def test_counts_every_occurrence():
    assert hits("salary", "salary salary salary") == 3


def test_duplicate_keywords_cannot_double_count():
    assert hits(("salary", "Salary"), "salary salary") == 2


@pytest.mark.parametrize(("text", "expected"), [("aaaa", 0), ("aa aa", 2)])
def test_repeated_letters_respect_word_boundaries(text, expected):
    assert hits("aa", text) == expected


# --- Thresholds and OR ---


@pytest.mark.parametrize(
    ("threshold", "text", "detected"),
    [(3, "ssn ssn ssn", True), (3, "ssn ssn", False), (1, "ssn", True)],
)
def test_detected_iff_count_reaches_threshold(threshold, text, detected):
    assert bool(scan(text, [rule("ssn", threshold=threshold)])) is detected


def test_rules_are_independent_and_only_matching_ones_are_returned():
    hit = rule("salary", threshold=2, name="Salary")
    miss = rule("ssn", threshold=2, name="SSN")

    assert scan("salary salary ssn", [hit, miss]) == [Detection(hit.id, "Salary", 2)]


def test_threshold_below_one_is_rejected_at_construction():
    with pytest.raises(ValueError, match="threshold"):
        rule("ssn", threshold=0)


# --- Empty and degenerate ---


@pytest.mark.parametrize("text", ["", "   \n\t", "!!! ... ---"])
def test_empty_or_blank_text_detects_nothing(text):
    assert scan(text, [rule("ssn"), rule("salary")]) == []


@pytest.mark.parametrize("keywords", [(), ("", "  ")])
def test_rule_without_usable_keywords_is_never_detected(keywords):
    assert count(rule(*keywords), "anything at all") == 0
    assert scan("anything at all", [rule(*keywords)]) == []


def test_text_equal_to_keyword_matches_once():
    assert hits("social security number", "social security number") == 1


# --- Unicode (NFC + documented limitations) ---


@pytest.mark.parametrize(("text", "expected"), [("my résumé", 1), ("résumés", 0), ("RÉSUMÉ", 1)])
def test_accented_keyword(text, expected):
    assert hits("résumé", text) == expected


def test_nfc_makes_decomposed_keyword_match_precomposed_text():
    keyword = unicodedata.normalize("NFD", "café")
    assert keyword != "café"  # guard: the two really are different strings

    assert hits(keyword, unicodedata.normalize("NFC", "café")) == 1


def test_nfc_recomposes_text_so_accented_letter_is_a_word_char():
    # Without NFC, "e" + U+0301 would leave "cafe" followed by a non-word combining mark.
    assert hits("cafe", unicodedata.normalize("NFD", "café")) == 0


@pytest.mark.parametrize(("text", "expected"), [("מסמך סודי מאוד", 1), ("סודיות", 0)])
def test_hebrew_whole_word(text, expected):
    assert hits("סודי", text) == expected


def test_limitation_combining_marks_are_not_word_chars():
    # Pointed Hebrew: the hiriq after ד is not \w, so "סוד" matches "inside" סוד\u05b4י.
    assert hits("סוד", "סוד\u05b4י") == 1


def test_limitation_hebrew_prefixes_are_not_stripped():
    assert hits("סודי", "והסודי") == 0


def test_limitation_simple_case_folding_treats_dotted_i_as_i():
    assert hits("istanbul", "İstanbul") == 1


def test_limitation_simple_case_folding_keeps_eszett_distinct():
    assert hits("strasse", "straße") == 0


# --- Ordering and purity ---


def test_sorted_by_count_desc_then_name():
    rules = [rule("x", name="b"), rule("y", name="c"), rule("x", name="a")]

    result = scan("x x x x x y y", rules)

    assert [(d.name, d.match_count) for d in result] == [("a", 5), ("b", 5), ("c", 2)]


def test_equal_count_and_name_sorted_by_id():
    low, high = uuid.UUID(int=1), uuid.UUID(int=2)

    result = scan("x", [rule("x", name="same", id=high), rule("x", name="same", id=low)])

    assert [d.id for d in result] == [low, high]


def test_scan_is_repeatable():
    rules = [rule("salary"), rule("credit card", "card", threshold=2)]
    text = "salary credit card card"

    assert scan(text, rules) == scan(text, rules)
