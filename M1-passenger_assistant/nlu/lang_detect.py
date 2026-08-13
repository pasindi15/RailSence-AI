"""
nlu/lang_detect.py
Detects whether a message is English, Sinhala, or Tamil.

Phase 1: implemented and callable, but /chat doesn't use it yet — it's here
so Phase 2 only has to wire it in, not build it from scratch under time
pressure.
"""

from langdetect import detect, LangDetectException

# langdetect returns ISO codes; Sinhala/Tamil have their own Unicode blocks
# so script-range detection is more reliable than langdetect for them.
SINHALA_RANGE = (0x0D80, 0x0DFF)
TAMIL_RANGE = (0x0B80, 0x0BFF)


def detect_language(text: str) -> str:
    """Returns 'si', 'ta', or 'en'."""
    for ch in text:
        code_point = ord(ch)
        if SINHALA_RANGE[0] <= code_point <= SINHALA_RANGE[1]:
            return "si"
        if TAMIL_RANGE[0] <= code_point <= TAMIL_RANGE[1]:
            return "ta"

    # No Sinhala/Tamil script found — fall back to langdetect for
    # English vs. other Latin-script languages
    try:
        code = detect(text)
        return "en" if code == "en" else code
    except LangDetectException:
        return "en"
