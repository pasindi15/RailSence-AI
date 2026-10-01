"""
Romanized Sinhala ("Singlish") support for the Passenger Assistant Agent.

Passengers often type Sinhala using the Latin alphabet, e.g.
"mata colomba idala badullata ticket ekak ganna oni"
("I want to get a ticket from Colombo to Badulla").

Without this module that message:
  - detects as language "en" (no Sinhala/Tamil script characters to scan),
  - classifies as intent "unknown" (all booking keywords are either English
    words or Sinhala *script*),
  - resolves only one station ("badulla"; "colomba" doesn't match the
    "colombo" alias), with no origin/destination role for it.

This module is a lightweight, deterministic, rule-based layer - not a model -
so it stays fast, free, offline and it is the layer that runs *before* any
LLM call. Intent and NER are what decide routing (booking card vs. RAG vs.
Hub) in main.py, so the LLM downstream can never repair a wrong routing
decision made here.

Scope: romanized Sinhala only. Romanized Tamil (Tanglish) would use the same
functions with a parallel lexicon, added later.
"""
import re
from difflib import SequenceMatcher

# Sinhala/Tamil Unicode blocks - used to make sure we only ever treat *Latin*
# text as romanized Sinhala. Script text is handled by the existing
# lang_detect.py / intent_classifier.py / ner_extractor.py script-based paths.
_SINHALA_RANGE = (0x0D80, 0x0DFF)
_TAMIL_RANGE = (0x0B80, 0x0BFF)


def _has_sinhala_or_tamil_script(text: str) -> bool:
    for ch in text:
        code = ord(ch)
        if _SINHALA_RANGE[0] <= code <= _SINHALA_RANGE[1] or _TAMIL_RANGE[0] <= code <= _TAMIL_RANGE[1]:
            return True
    return False


def normalize(text: str) -> str:
    """Fold romanized-Sinhala spelling variance down to a canonical form so a
    keyword/alias and the passenger's actual spelling compare equal.

    Both sides of every comparison in this module (the passenger's text AND
    the lexicons below) are passed through this same function, so it only
    has to be *consistent*, not linguistically perfect.
    """
    if not text:
        return ""
    normalized = text.lower()
    # Keep letters, digits and whitespace only - punctuation carries no
    # signal for this matching and would otherwise block collapsing/boundary
    # checks (e.g. "ticket?" vs "ticket").
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    # Common digraph -> single-letter folds seen across different romanization
    # habits ("photo"-style "ph" for a /p/ sound isn't actually used in
    # Sinhala loanwords, but "v"/"q"/"x" spelling swaps are common).
    normalized = normalized.replace("ph", "p")
    normalized = normalized.replace("v", "w")
    normalized = normalized.replace("q", "k")
    normalized = normalized.replace("x", "ks")
    # Collapse any run of the same character (letter OR space) to one
    # instance: "oniii" -> "oni", "wenkaranna" -> "wenkarana", multiple
    # spaces -> one space. This is the main defence against spelling
    # variance like "ganna"/"gannaa" or "kiyada"/"kiyyada".
    normalized = re.sub(r"(.)\1+", r"\1", normalized)
    return normalized.strip()


def tokens(text: str) -> list[str]:
    normalized = normalize(text)
    return normalized.split() if normalized else []


# --------------------------------------------------------------------------
# Lexicons. Stored as their natural romanized spelling and normalized once at
# import time, so lookups always compare normalized-to-normalized.
# --------------------------------------------------------------------------

def _norm_set(words) -> frozenset[str]:
    return frozenset(normalize(w) for w in words)


def _norm_phrases(phrases) -> list[str]:
    # Order preserved (some callers care about first-match priority).
    return [normalize(p) for p in phrases]


# Function/grammar words common in romanized Sinhala requests. Used only to
# *detect* that a Latin-script message is Sinhala, not to extract meaning.
FUNCTION_WORDS = _norm_set([
    "mata", "mage", "apita", "ohuta", "oyata",
    "oni", "ona", "oyanne", "ekak", "eka", "eke", "ek",
    "karanna", "ganna", "denna", "kiyanna", "wada",
    "thiyenawa", "nathiwa", "puluwanda", "puluwan", "baa",
    "kiyada", "kiyala", "kiyanawada", "kohomada", "kawada", "koheda",
    "idala", "indala", "idan", "indan", "sita", "patan",
    "wage", "wagema", "neda", "newei", "haemma",
    # "towards/to" (the standalone word form of the same dative case already
    # modelled as a suffix on station tokens via DEST_SUFFIXES) and "does it
    # come to/become" (a common colloquial quantity/cost question tag, e.g.
    # "ticket eka kiyak wenawada" - "how much does the ticket come to?").
    "walata", "wenawada",
])

# Minimum token/candidate length for the fuzzy fallback below - short words
# (2-3 letters) are too easily confused by chance at any useful ratio.
_FUZZY_MIN_LEN = 4
_FUZZY_RATIO = 0.72


def _fuzzy_hit(token: str, candidates: frozenset[str]) -> bool:
    """True if `token` is close enough (SequenceMatcher ratio) to one of
    `candidates` to tolerate the vowel-dropping/SMS-style spelling common in
    casual romanized Sinhala - "kiyd"/"kiyak" for "kiyada", "indn" for
    "indan", "walat" for "walata". An exact match is checked separately by
    the caller; this only covers near-misses."""
    if len(token) < _FUZZY_MIN_LEN:
        return False
    return any(
        len(cand) >= _FUZZY_MIN_LEN and SequenceMatcher(None, token, cand).ratio() >= _FUZZY_RATIO
        for cand in candidates
    )

# Intent -> list of romanized phrases. Multi-word phrases are matched with
# word boundaries against the *normalized, space-joined* text (never as bare
# substrings of a single token) so e.g. "ta" never matches inside "ticket".
INTENT_KEYWORDS_LATN: dict[str, list[str]] = {
    "delay_check": [
        "pramadai", "pramadaida", "parakku", "parakkuda", "leit",
    ],
    "cancel_booking": [
        "cancel karanna", "booking eka cancel", "ticket eka cancel",
        "awalangu karanna", "awalanguda",
    ],
    "booking_request": [
        "book karanna", "wenkaranna", "wen karanna", "buk karanna",
        "ticket ekak ganna", "ticket ekak oni", "ticket eka ganna",
        "ticket eka oni", "reserve karanna",
    ],
    "fare_query": [
        # Bare "kiyada" was here and removed - it's a generic Sinhala
        # question suffix ("...tell me?"), not fare-specific, and as a
        # substring-free keyword it hijacked "welawa kiyada" ("what time is
        # it?" - a schedule question) into fare_query since fare_query is
        # checked before schedule_query below. "gaasthuwa"/"gastuwa"/"mila"
        # are unambiguously about price, so those stay.
        "gaasthuwa", "gastuwa", "mila kiyada", "mila",
        "ticket eka kiyada", "ticket ekak kiyada",
    ],
    "schedule_query": [
        "welawa", "welawada", "kiyatada", "koi welawe", "yana kochchiya",
    ],
    "complaint": [
        "kadila", "waradi", "wada karanne na", "wada karanne ne",
    ],
}

# Canonical station name -> romanized aliases (parallel to
# ner_extractor.STATION_ALIASES, kept separate so that module doesn't need to
# import this one just to add a few Latin spellings to its script-based dict).
STATION_ALIASES_LATN: dict[str, list[str]] = {
    "Colombo Fort": ["colomba", "kolamba", "colombo", "kotuwa"],
    "Kandy": ["mahanuwara", "mahanuwera", "kandy"],
    "Galle": ["gaalla", "galla", "galle"],
    "Jaffna": ["yapanaya", "yaapanaya", "jaffna"],
    "Anuradhapura": ["anuradhapuraya", "anuradhapura"],
    "Matara": ["maathara", "matara"],
    "Badulla": ["badulle", "badulla"],
}
_STATION_ALIASES_LATN_NORM: dict[str, list[str]] = {
    canonical: sorted(_norm_set(aliases), key=len, reverse=True)
    for canonical, aliases in STATION_ALIASES_LATN.items()
}

# Case-marking suffixes attached directly to a station token, e.g.
# "badulla" + "ta" -> "badullata" (dative -> destination), "colomba" + "in"
# -> "colombain" (ablative -> origin). Longer suffixes first so "ata" is
# tried before its own trailing "ta" would otherwise also match.
DEST_SUFFIXES = ("ata", "ta")
ORIGIN_SUFFIXES = ("gen", "en", "in")

# Case-marking words that appear as their own token right after (origin) or
# around a station name (destination), e.g. "colomba idala ..." (origin),
# "... badulla dakwa" (destination).
ORIGIN_PARTICLES = _norm_set(["idala", "indala", "idan", "indan", "sita", "patan"])
DEST_PARTICLES = _norm_set(["dakwa", "wetha", "weta"])

# English loanwords ("ticket", "book", "station"...) are deliberately NOT in
# here - a plain English sentence can contain those, and this set is also
# used to *detect* romanized Sinhala, where that would false-positive. These
# are Sinhala words with no English-homograph risk, so even a single hit
# ("kochchiya pramadai", no grammar/function word in sight) is safe to trust.
SINHALA_ONLY_DOMAIN_WORDS = _norm_set([
    "kochchiya", "kochiya", "dumriya", "gaasthuwa", "gastuwa", "welawa",
    "welawada", "kiyatada", "stesama", "awalangu", "pramadai", "pramadaida",
    "parakku", "asana", "wenkaranna", "waradi",
    # Sinhala-spelled station names (as opposed to the plain English place
    # names "colombo"/"kandy"/"galle"/... already in STATION_ALIASES_LATN,
    # which an English sentence could also contain) - unambiguous enough to
    # trust as a language signal on their own, same reasoning as above.
    "mahanuwara", "mahanuwera", "yapanaya", "yaapanaya", "anuradhapuraya",
    "gaalla", "maathara", "badulle", "kolamba", "colomba", "kotuwa",
])

RAILWAY_VOCAB_LATN = _norm_set([
    "kochchiya", "kochiya", "dumriya", "ticket", "tikat", "gaasthuwa",
    "gastuwa", "welawa", "stesama", "station", "platform", "seat", "asana",
    "booking", "book", "cancel", "awalangu", "pramadai", "parakku",
])


def is_romanized_sinhala(text: str) -> bool:
    """True when `text` looks like Sinhala written in Latin letters.

    Deliberately conservative on grammar/function words alone: a lone
    Singlish-looking word ("mata" by itself) does not trigger - short
    messages need a higher hit ratio. An unambiguous Sinhala-only domain
    word (no plausible English sentence contains "kochchiya" or "pramadai")
    is trusted on a single hit instead, so a terse message with no grammar
    words ("kochchiya pramadai" - "train delayed") still gets caught.
    Everything is skipped outright if the text already contains Sinhala or
    Tamil script (that's the existing script-based path's job).
    """
    if not text or _has_sinhala_or_tamil_script(text):
        return False
    toks = tokens(text)
    if not toks:
        return False
    # Exact match only here, deliberately not fuzzy: this path trusts a
    # SINGLE hit, and "colombo" (a plain English place name, kept OUT of
    # this set on purpose - see its definition above) fuzzy-matches
    # "colomba" closely enough to defeat that exclusion if allowed through.
    if any(tok in SINHALA_ONLY_DOMAIN_WORDS for tok in toks):
        return True
    hits = sum(1 for tok in toks if tok in FUNCTION_WORDS or _fuzzy_hit(tok, FUNCTION_WORDS))
    if hits >= 2:
        return True
    if hits >= 1 and len(toks) >= 3 and (hits / len(toks)) >= 0.34:
        return True
    return False


def match_intent(text: str) -> str | None:
    """First romanized-Sinhala intent keyword phrase found in `text`, or None.

    Matched against the normalized, space-joined text with word boundaries -
    never a bare substring check - so a short phrase like "ta" cannot match
    inside an unrelated token.
    """
    normalized = normalize(text)
    if not normalized:
        return None
    for intent, phrases in INTENT_KEYWORDS_LATN.items():
        for phrase in _norm_phrases(phrases):
            if re.search(rf"\b{re.escape(phrase)}\b", normalized):
                return intent
    return None


def mentions_railway(text: str) -> bool:
    normalized = normalize(text)
    if not normalized:
        return False
    return any(re.search(rf"\b{re.escape(term)}\b", normalized) for term in RAILWAY_VOCAB_LATN)


def _strip_suffix(token: str, alias: str, suffixes: tuple[str, ...]) -> str | None:
    """If `token` is `alias` plus one of `suffixes`, return that suffix."""
    if not token.startswith(alias):
        return None
    remainder = token[len(alias):]
    return remainder if remainder in suffixes else None


def match_stations(text: str) -> list[tuple[str, str | None, int]]:
    """Find romanized station mentions in `text`.

    Returns a list of (canonical_name, role, token_index) tuples, role being
    "origin", "dest" or None (unmarked - same convention as
    ner_extractor.resolve_route_roles). token_index is the position of the
    matched token in the normalized token list, used to order multiple
    mentions the way they were spoken.
    """
    toks = tokens(text)
    if not toks:
        return []

    found: list[tuple[str, str | None, int]] = []
    matched_indices: set[int] = set()

    for idx, tok in enumerate(toks):
        if idx in matched_indices:
            continue
        for canonical, aliases in _STATION_ALIASES_LATN_NORM.items():
            role: str | None = None
            matched = False
            for alias in aliases:
                if tok == alias:
                    matched = True
                    break
                suffix = _strip_suffix(tok, alias, DEST_SUFFIXES)
                if suffix:
                    matched, role = True, "dest"
                    break
                suffix = _strip_suffix(tok, alias, ORIGIN_SUFFIXES)
                if suffix:
                    matched, role = True, "origin"
                    break
            if not matched:
                # Fuzzy fallback: only for longer tokens, to keep short
                # unrelated words (e.g. "mata") from accidentally matching a
                # short alias by chance.
                for alias in aliases:
                    if len(tok) >= 5 and len(alias) >= 5:
                        ratio = SequenceMatcher(None, tok, alias).ratio()
                        if ratio >= 0.85:
                            matched = True
                            break
            if not matched:
                continue

            if role is None:
                # No suffix attached directly - check the neighbouring token
                # for a standalone case-marking particle instead.
                prev_tok = toks[idx - 1] if idx > 0 else None
                next_tok = toks[idx + 1] if idx + 1 < len(toks) else None
                if next_tok in ORIGIN_PARTICLES or prev_tok in ORIGIN_PARTICLES:
                    role = "origin"
                elif next_tok in DEST_PARTICLES:
                    role = "dest"

            found.append((canonical, role, idx))
            matched_indices.add(idx)
            break  # this token is claimed; don't test it against other stations

    found.sort(key=lambda item: item[2])
    return found


if __name__ == "__main__":
    tests = [
        "mata colomba idala badullata ticket ekak ganna oni",
        "mahanuwara idan colombata welawa kiyada",
        "Is the 14:35 Colombo Fort to Kandy train delayed?",
        "mata",
    ]
    for t in tests:
        print(t)
        print("  romanized:", is_romanized_sinhala(t))
        print("  intent   :", match_intent(t))
        print("  stations :", match_stations(t))
