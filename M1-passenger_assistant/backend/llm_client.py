"""
LLM client for the Passenger Assistant Agent.

Exposes the same tiny surface the code has always used from Gemini -
`model.generate_content(prompt).text` - so main.py and the NER fallback need
no call-site changes and tests can keep faking the model the same way.

Two providers are supported, chosen by LLM_PROVIDER:

  LLM_PROVIDER=gemini-3.5-flash-lite   -> Google Gemini, via GEMINI_API_KEY
  LLM_PROVIDER=openrouter (or unset)   -> OpenRouter, via OPENROUTER_API_KEY

Either way the client holds an ordered list of models and moves to the next one
when a call fails or comes back unusable, so one rate-limited model doesn't take
the assistant down.

Why the provider switch exists: OpenRouter's free tier has a per-day account cap
("Rate limit exceeded: free-models-per-day"). Once it's spent, every `:free`
model returns 429 and the only thing still answering is the `openrouter/free`
auto-router - which picks whatever free model is idle, including
`nvidia/nemotron-3.5-content-safety:free` (a safety *classifier* that replies
"User Safety: safe" instead of answering) and `liquid/lfm-2.5-2.6b:free` (which
often returns nothing at all). Those replies were reaching passengers verbatim.
"""
import os
import re
from types import SimpleNamespace

try:
    from openai import OpenAI, OpenAIError
except ImportError:  # LLM is optional; callers fall back to templates/RAG text.
    OpenAI = None
    OpenAIError = Exception

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODELS = [
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "qwen/qwen3.8-27b:free",
    "openrouter/free",
]

# Gemini chain: the fast, cheap one first, then the fuller model if it's down.
DEFAULT_GEMINI_MODELS = ["gemini-3.5-flash-lite", "gemini-3.5-flash"]

# A safety classifier answers with a verdict ("User Safety: safe"), not prose.
# When the router hands us one of those, the verdict is not an answer to the
# passenger's question, so treat it exactly like an empty reply and move on.
_CLASSIFIER_VERDICT_RE = re.compile(
    r"^\s*(?:user|agent|response|content)?\s*safety\s*[:\-]\s*(?:safe|unsafe)\b",
    re.IGNORECASE,
)


def _usable(text: str) -> bool:
    """False for replies that are not an answer (empty, or a classifier verdict)."""
    return bool(text) and not _CLASSIFIER_VERDICT_RE.match(text)


class OpenRouterModel:
    def __init__(self, api_key: str, models: list[str] | None = None, system_instruction: str | None = None):
        self.models = models or list(DEFAULT_MODELS)
        self.model = self.models[0]  # primary; shown in the startup log
        self.system_instruction = system_instruction
        # max_retries=0: a 429 from a shared free pool rarely clears in the SDK's
        # short backoff, so switching model is faster than retrying the same one.
        self._client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key, max_retries=0, timeout=30)

    def generate_content(self, prompt: str):
        messages = []
        if self.system_instruction:
            messages.append({"role": "system", "content": self.system_instruction})
        messages.append({"role": "user", "content": prompt})

        last_error: Exception | None = None
        for model in self.models:
            try:
                r = self._client.chat.completions.create(model=model, messages=messages)
                text = (r.choices[0].message.content or "").strip()
                if not _usable(text):  # empty, or a safety verdict - try the next one
                    print(f"[llm] {model} returned no usable answer ({text[:40]!r}) - trying next model")
                    continue
                print(f"[llm] answered by {model}")
                return SimpleNamespace(text=text)
            except OpenAIError as e:
                last_error = e
                print(f"[llm] {model} failed ({type(e).__name__}) - trying next model")
        if last_error:
            raise last_error
        return SimpleNamespace(text="")


class GeminiModel:
    """Google Gemini, behind the same generate_content(prompt).text surface."""

    def __init__(self, api_key: str, models: list[str] | None = None, system_instruction: str | None = None):
        import google.generativeai as genai

        self._genai = genai
        genai.configure(api_key=api_key)
        self.models = models or list(DEFAULT_GEMINI_MODELS)
        self.model = self.models[0]  # primary; shown in the startup log
        self.system_instruction = system_instruction
        self._clients: dict = {}

    def _client(self, name: str):
        if name not in self._clients:
            self._clients[name] = self._genai.GenerativeModel(
                name, system_instruction=self.system_instruction
            )
        return self._clients[name]

    def generate_content(self, prompt: str):
        last_error: Exception | None = None
        for model in self.models:
            try:
                r = self._client(model).generate_content(prompt)
                # .text raises rather than returning "" when the candidate was
                # blocked or finished without content, so it's inside the try.
                text = (r.text or "").strip()
                if not _usable(text):
                    print(f"[llm] {model} returned no usable answer - trying next model")
                    continue
                print(f"[llm] answered by {model}")
                return SimpleNamespace(text=text)
            except Exception as e:  # SDK raises several unrelated error types
                last_error = e
                print(f"[llm] {model} failed ({type(e).__name__}) - trying next model")
        if last_error:
            raise last_error
        return SimpleNamespace(text="")


def build_model(system_instruction: str | None = None):
    """Return a ready model for the configured provider, or None if none is usable."""
    provider = os.getenv("LLM_PROVIDER", "").strip()

    # A Gemini model id in LLM_PROVIDER both selects the provider and names the
    # primary model, which is how the existing .env is already written.
    if provider.lower().startswith("gemini"):
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            configured = [provider] + [m for m in DEFAULT_GEMINI_MODELS if m != provider]
            try:
                return GeminiModel(api_key, configured, system_instruction)
            except ImportError:
                print("[llm] LLM_PROVIDER asks for Gemini but google-generativeai "
                      "isn't installed - falling back to OpenRouter")
        else:
            print("[llm] LLM_PROVIDER asks for Gemini but GEMINI_API_KEY is not set "
                  "- falling back to OpenRouter")

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key or OpenAI is None:
        return None
    configured = [m.strip() for m in os.getenv("OPENROUTER_MODEL", "").split(",") if m.strip()]
    return OpenRouterModel(api_key, configured or None, system_instruction)
