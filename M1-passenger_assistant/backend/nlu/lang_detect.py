"""
Language detection for Passenger Assistant Agent.
Order of checks:
 1. Unicode range check (fast, reliable for Sinhala & Tamil scripts)
 2. Romanized-Sinhala lexicon check (Sinhala written in Latin letters)
 3. langdetect fallback (for English / mixed / ambiguous text)

Returns one of: "si" (Sinhala), "ta" (Tamil), "en" (English)

Romanized Sinhala ("Singlish", e.g. "mata colomba idala badullata ticket
ekak ganna oni") deliberately returns "si", not a separate code - i18n.py's
t() and every `language == "si"` / `.get(language, ...)` branch in main.py
already have full Sinhala-script handling, and reusing "si" gets all of that
for free instead of silently falling through to English everywhere an
unrecognised code would hit a `.get(..., ["en"])` default. See
nlu/romanized.py for why replies are still written in Sinhala script even
though the question came in Latin letters.
"""
try:
    # pyrefly: ignore [missing-import]
    from langdetect import detect, DetectorFactory
    DetectorFactory.seed = 0
except ImportError:
    detect = None

from nlu.romanized import is_romanized_sinhala

# Unicode block ranges
SINHALA_RANGE = (0x0D80, 0x0DFF)
TAMIL_RANGE = (0x0B80, 0x0BFF)


def _unicode_scan(text: str) -> str | None:
    """Script of the message. Mixed text (e.g. Sinhala with an English word, or
    Sinhala and Tamil together) is decided by which script has MORE letters, not
    by whichever character comes first; a tie goes to the script seen first."""
    counts = {"si": 0, "ta": 0}
    first = None
    for ch in text:
        code = ord(ch)
        if SINHALA_RANGE[0] <= code <= SINHALA_RANGE[1]:
            counts["si"] += 1
            first = first or "si"
        elif TAMIL_RANGE[0] <= code <= TAMIL_RANGE[1]:
            counts["ta"] += 1
            first = first or "ta"
    if not first:
        return None
    if counts["si"] == counts["ta"]:
        return first
    return "si" if counts["si"] > counts["ta"] else "ta"


def detect_language(text: str) -> str:
    if not text or not text.strip():
        return "en"

    # Step 1: unicode script check
    script_lang = _unicode_scan(text)
    if script_lang:
        return script_lang

    # Step 2: romanized Sinhala (no Sinhala/Tamil script present, but the
    # words are Sinhala spelled in Latin letters)
    if is_romanized_sinhala(text):
        return "si"

    # Step 3: fallback to langdetect (mainly disambiguates English vs others)
    try:
        if detect is None:
            return "en"
        code = detect(text)
        if code == "en":
            return "en"
        # langdetect doesn't reliably support si/ta codes -> default to en
        return "en"
    except Exception:
        return "en"


if __name__ == "__main__":
    tests = [
        "Is the 14:35 Colombo-Kandy train delayed?",
        "Colombo to Kandy මාර්ගයේ ඊළඟ දුම්රිය කීයටද?",
        "கொழும்பு முதல் கண்டி வரை அடுத்த ரயில் எப்போது?",
    ]
    for t in tests:
        print(t, "->", detect_language(t))
