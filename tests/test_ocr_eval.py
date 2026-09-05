"""CER/WER and the Arabic normalisation methodology."""

from __future__ import annotations

import pytest

from app.ocr_eval import (
    arabic_ratio, error_rate, levenshtein, measure, measure_both,
    normalize_arabic, normalize_light,
)


def test_identical_text_scores_zero():
    result = measure("الحمد لله رب العالمين", "الحمد لله رب العالمين")
    assert result.cer == 0.0 and result.wer == 0.0


def test_empty_hypothesis_scores_one():
    assert measure("الحمد لله", "").cer == 1.0


def test_hallucination_can_exceed_one():
    """An engine that invents more than the page holds must score above 1."""
    assert measure("نص", "نص طويل جدا مخترع بالكامل").cer > 1.0


def test_levenshtein_basics():
    assert levenshtein("كتاب", "كتاب") == 0
    assert levenshtein("كتاب", "كتب") == 1
    assert levenshtein("", "كتب") == 3


@pytest.mark.parametrize("pair", [
    ("أحمد", "احمد"), ("إبراهيم", "ابراهيم"), ("آمن", "امن"),
    ("مدرسة", "مدرسه"), ("على", "علي"), ("مؤمن", "مومن"), ("قائم", "قايم"),
])
def test_normalisation_folds_the_declared_variants(pair):
    a, b = pair
    assert normalize_arabic(a) == normalize_arabic(b)


def test_normalisation_removes_tashkeel_and_tatweel():
    assert normalize_arabic("الْعِلْمُ") == "العلم"
    assert normalize_arabic("الــعــلــم") == "العلم"


def test_normalisation_unifies_digits_and_punctuation():
    assert normalize_arabic("سنة ١٤٣٥") == "سنه 1435"   # ة folds too
    assert normalize_arabic("نعم، لا؛ ماذا؟") == "نعم, لا; ماذا?"


def test_strict_reading_folds_nothing_but_whitespace():
    assert normalize_light("الْعِلْمُ  نور") == "الْعِلْمُ نور"
    assert normalize_light("أحمد") != normalize_light("احمد")


def test_both_readings_are_reported_and_strict_is_never_kinder():
    """The strict reading can only be equal or worse; a report showing the
    opposite would mean the normaliser introduced errors."""
    both = measure_both("الْحَمْدُ لِلَّهِ", "الحمد لله")
    assert both["normalized"]["cer"] == 0.0
    assert both["strict"]["cer"] >= both["normalized"]["cer"]


def test_word_errors_are_counted_over_words_not_characters():
    result = measure("الحمد لله رب العالمين", "الحمد لله رب العالمون")
    assert result.wer == pytest.approx(0.25)      # one word of four
    assert result.cer < result.wer


def test_arabic_ratio_detects_garbage_but_is_not_accuracy():
    assert arabic_ratio("الحمد لله") == 1.0
    assert arabic_ratio("###@@@") == 0.0
    # identical ratio, completely different accuracy: the signal is weak by design
    assert arabic_ratio("الحمد لله") == arabic_ratio("كلمات خاطئة تماما")


def test_error_rate_handles_empty_reference():
    assert error_rate("", "") == 0.0
    assert error_rate("", "شيء") == 1.0
