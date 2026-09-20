import pytest


@pytest.fixture(autouse=True)
def _no_live_gemini_station_fallback(monkeypatch):
    """ner_extractor falls back to a live Gemini call whenever no station alias
    matches (i.e. for most policy/off-topic questions). In tests that made real
    API calls: slow, flaky, and it burned the free-tier daily quota (429), which
    then made results depend on the quota state. Alias-based extraction - what the
    tests actually exercise - is unaffected."""
    from nlu import ner_extractor

    monkeypatch.setattr(ner_extractor, "_llm_model", None)
