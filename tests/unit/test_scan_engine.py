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


# --- Unicode (NFKC + documented limitations) ---


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


@pytest.mark.parametrize(
    ("keyword", "text", "expected"),
    [
        ("σ", "ς", 1),  # final sigma equals sigma (fold)
        ("ΟΔΟΣ", "ΟΔΟΣ.ΚΑΙ", 1),  # lower() alone would apply the final-sigma context rule
        ("ı", "i", 1),  # dotless i equals i (fold)
        ("İ", "i", 1),  # dotted capital I equals i, as one code point (fold)
        ("zmir", "İzmir", 0),  # lower() alone would split İ into i + combining dot
        ("ß", "ẞ", 1),  # lower() handles capital eszett
        ("s", "ſ", 1),  # long s: NFKC maps it to s before the fold, so still equal
        ("µ", "μ", 1),  # micro sign: NFKC maps it to Greek mu before the fold, so still equal
        ("в", "ᲀ", 0),  # Cyrillic rounded ve: equal under re.IGNORECASE only (accepted, D11)
    ],
)
def test_fold_equivalences_are_pinned(keyword, text, expected):
    assert hits(keyword, text) == expected


# --- False positives and negatives (realistic corpus) ---


@pytest.mark.parametrize(
    ("keyword", "text"),
    [
        ("secret", "the secretary's office"),
        ("card", "a wool cardigan"),
        ("pin", "pinned message"),
        ("id", "identity check"),
        ("pass", "Bring your passport"),
        ("token", "tokenizer settings"),
        ("credit card", "credit cardigan sale"),
        ("$100", "total $1000"),
        ("ssn", "ssnssn"),
    ],
)
def test_whole_word_rule_rejects_longer_words(keyword, text):
    assert hits(keyword, text) == 0


def test_nfkc_folds_ligatures_and_fullwidth():
    assert hits("confidential", "This report is con\ufb01dential") == 1  # "fi" ligature
    assert hits("password", "\uff50\uff41\uff53\uff53\uff57\uff4f\uff52\uff44") == 1  # full-width


@pytest.mark.parametrize(
    ("keyword", "text"),
    [
        ("password", "pass\u00adword"),  # soft hyphen
        ("password", "pass\u200bword"),  # zero-width space
        ("confidential", "\ufeffconfidential"),  # BOM
    ],
)
def test_invisible_format_characters_are_ignored(keyword, text):
    assert hits(keyword, text) == 1


@pytest.mark.parametrize(("keyword", "text"), [("pass", "pass\u00adport"), ("pin", "pin\u200bned")])
def test_invisible_format_characters_do_not_make_word_edges(keyword, text):
    assert hits(keyword, text) == 0


def test_keyword_of_only_invisible_characters_is_unusable():
    assert hits("\u200b", "any\u200bthing") == 0
    assert scan("any\u200bthing", [rule("\u200b")]) == []


def test_limitation_zwnj_and_zwj_are_not_stripped():
    # ZWNJ/ZWJ carry meaning in Arabic and Indic scripts, so they stay, as non-word characters.
    assert hits("password", "pass\u200cword") == 0
    assert hits("password", "pass\u200dword") == 0


@pytest.mark.parametrize(
    ("keyword", "text"),
    [
        ("password", "rotate all passwords"),
        ("password", "DB_PASSWORD=x"),
        ("api key", "apiKey = 1"),
        ("internal only", "internal-only deck"),
    ],
)
def test_limitation_plural_and_identifier_forms_need_their_own_keyword(keyword, text):
    # Exact word forms: stemming or identifier splitting would cost the precision above.
    assert hits(keyword, text) == 0


@pytest.mark.parametrize(
    ("keyword", "text", "expected"), [("+", "call +1 415", 1), ("--", "|------|", 3)]
)
def test_limitation_punctuation_only_keyword_matches_anywhere(keyword, text, expected):
    # No word character at either edge, so no boundary applies; pick such keywords with care.
    assert hits(keyword, text) == expected


@pytest.mark.parametrize("text", ["100,000 EUR", "version 100.5", "100%"])
def test_limitation_number_keyword_matches_inside_punctuated_number(text):
    # Comma, dot and percent are not \w; a digit guard would also miss "100,200,300".
    assert hits("100", text) == 1


@pytest.mark.parametrize(
    ("text", "expected"), [("x@company.com.attacker.net", 1), ("x@mail.company.com", 0)]
)
def test_limitation_domain_suffix_keyword(text, expected):
    # The keyword is a literal string, not a parsed address: "." after it is a valid edge.
    assert hits("@company.com", text) == expected


@pytest.mark.parametrize(("keyword", "text"), [("us", "let us know"), ("it", "It's fine")])
def test_limitation_two_letter_keyword_fires_on_prose(keyword, text):
    # Case is ignored, so an acronym is also a common word; use a threshold or a longer keyword.
    assert hits(keyword, text) == 1


def test_limitation_paragraph_break_joins_multi_word_keyword():
    # Any whitespace run matches, so extracted text that wraps lines still matches.
    assert hits("social security number", "social security\n\nNumber of dependents") == 1


def test_threshold_is_the_false_positive_control():
    footer = "CONFIDENTIAL: This message is confidential."

    assert hits("confidential", footer) == 2
    assert scan(footer, [rule("confidential", threshold=3)]) == []
    assert scan(footer, [rule("confidential", threshold=2)])


def test_limitation_matching_is_accent_sensitive():
    # NFKC keeps accents; stripping them would merge distinct words in other languages.
    assert hits("resume", "attach your résumé") == 0


@pytest.mark.parametrize(("text", "expected"), [("请输入密码以继续", 0), ("密码: 1234", 1)])
def test_limitation_scripts_without_spaces_have_no_word_boundaries(text, expected):
    # Every CJK character is \w, so running text is one long word; script rules are out of scope.
    assert hits("密码", text) == expected


def test_limitation_arabic_prefixes_are_not_stripped():
    # Like the Hebrew case: stripping an attached al- needs per-language rules.
    assert hits("سري", "المستند السري") == 0


@pytest.mark.parametrize(
    ("keyword", "text"), [("secret", "Secret Santa on Friday"), ("token", "token-based auth")]
)
def test_limitation_semantic_false_positives_are_inherent(keyword, text):
    # Keywords cannot see meaning; the threshold and keyword choice are the controls.
    assert hits(keyword, text) == 1


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
