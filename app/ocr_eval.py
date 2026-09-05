"""OCR accuracy measurement for Arabic text: CER and WER.

Two readings are always reported, because one alone misleads:

- `strict`     — nothing folded but whitespace. Punishes an engine for every
                 hamza and every diacritic it drops.
- `normalized` — the folds Arabic readers treat as the same word
                 (أإآ→ا, ى→ي, ة→ه, tashkeel and tatweel removed, digits and
                 punctuation unified). This is the number that reflects
                 whether a human can read the output.

Neither is "the" accuracy. A large gap between them is itself the finding:
it means the engines disagree about orthography, not about letters.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict

TASHKEEL = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭ]")
TATWEEL = "ـ"
_SPACES = re.compile(r"\s+")

# Arabic-Indic and extended Arabic-Indic digits -> ASCII
_DIGITS = {ord(c): str(i % 10) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹")}
# Punctuation that means the same thing in both scripts
_PUNCT = {"،": ",", "؛": ";", "؟": "?", "٪": "%", "ـ": "", "«": '"', "»": '"',
          "”": '"', "“": '"', "’": "'", "‘": "'", "–": "-", "—": "-"}


def normalize_light(text: str) -> str:
    """Whitespace only. The 'strict' reading: nothing about letters is folded."""
    text = unicodedata.normalize("NFC", text)
    return _SPACES.sub(" ", text).strip()


def normalize_arabic(text: str) -> str:
    """The 'normalized' reading. Every fold here is declared, none is hidden."""
    text = unicodedata.normalize("NFKC", text)
    text = TASHKEEL.sub("", text).replace(TATWEEL, "")
    for src, dst in (("أإآٱ", "ا"), ("ى", "ي"), ("ة", "ه"), ("ؤ", "و"), ("ئ", "ي")):
        for ch in src:
            text = text.replace(ch, dst)
    text = text.translate(_DIGITS)
    for src, dst in _PUNCT.items():
        text = text.replace(src, dst)
    return _SPACES.sub(" ", text).strip()


def levenshtein(a, b) -> int:
    """Edit distance over any sequence. Pure Python: no new dependency."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(
                previous[j] + 1,            # deletion
                current[j - 1] + 1,         # insertion
                previous[j - 1] + (ca != cb),  # substitution
            ))
        previous = current
    return previous[-1]


def error_rate(reference, hypothesis) -> float:
    """Edit distance divided by reference length. >1.0 is possible and real:
    an engine that hallucinates more than the page contains scores above 1."""
    if not reference:
        return 0.0 if not hypothesis else 1.0
    return levenshtein(reference, hypothesis) / len(reference)


@dataclass
class Accuracy:
    cer: float
    wer: float
    ref_chars: int
    ref_words: int
    hyp_chars: int
    hyp_words: int

    def to_dict(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v)
                for k, v in asdict(self).items()}


def measure(reference: str, hypothesis: str, normalizer=normalize_arabic) -> Accuracy:
    ref, hyp = normalizer(reference), normalizer(hypothesis)
    ref_words, hyp_words = ref.split(), hyp.split()
    return Accuracy(
        cer=error_rate(ref, hyp),
        wer=error_rate(ref_words, hyp_words),
        ref_chars=len(ref), ref_words=len(ref_words),
        hyp_chars=len(hyp), hyp_words=len(hyp_words),
    )


def measure_both(reference: str, hypothesis: str) -> dict:
    """The pair of readings the report always shows side by side."""
    return {
        "strict": measure(reference, hypothesis, normalize_light).to_dict(),
        "normalized": measure(reference, hypothesis, normalize_arabic).to_dict(),
    }


def arabic_ratio(text: str) -> float:
    """Share of non-space characters in the Arabic block. A sanity signal
    only: it detects garbage output, it does not measure accuracy."""
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    arabic = sum(1 for c in chars if "؀" <= c <= "ۿ")
    return round(arabic / len(chars), 4)
