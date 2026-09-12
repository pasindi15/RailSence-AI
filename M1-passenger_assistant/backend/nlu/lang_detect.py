"""
Language detection for Passenger Assistant Agent.
Order of checks:
 1. Unicode range check (fast, reliable for Sinhala & Tamil scripts)
 2. langdetect fallback (for English / mixed / ambiguous text)

Returns one of: "si" (Sinhala), "ta" (Tamil), "en" (English)
"""
try:
    from langdetect import detect, DetectorFactory
    DetectorFactory.seed = 0
except ImportError:
    detect = None

# Unicode block ranges
SINHALA_RANGE = (0x0D80, 0x0DFF)
TAMIL_RANGE = (0x0B80, 0x0BFF)


def _unicode_scan(text: str) -> str | None:
    for ch in text:
        code = ord(ch)
        if SINHALA_RANGE[0] <= code <= SINHALA_RANGE[1]:
            return "si"
        if TAMIL_RANGE[0] <= code <= TAMIL_RANGE[1]:
            return "ta"
    return None


def detect_language(text: str) -> str:
    if not text or not text.strip():
        return "en"

    # Step 1: unicode script check
    script_lang = _unicode_scan(text)
    if script_lang:
        return script_lang

    # Step 2: fallback to langdetect (mainly disambiguates English vs others)
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
