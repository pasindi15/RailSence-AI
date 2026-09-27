"""
OpenRouter LLM client for the Passenger Assistant Agent.

Exposes the same tiny surface the code previously used from Gemini -
`model.generate_content(prompt).text` - so main.py and the NER fallback need
no call-site changes and tests can keep faking the model the same way.

Free OpenRouter models are frequently rate-limited upstream (429), so the
client holds an ordered list of models and moves to the next one on any API
error. OPENROUTER_MODEL may be a single id or a comma-separated list.
"""
import os
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
                if not text:  # empty reply (e.g. reasoning model) - try the next one
                    continue
                print(f"[llm] answered by {model}")
                return SimpleNamespace(text=text)
            except OpenAIError as e:
                last_error = e
                print(f"[llm] {model} failed ({type(e).__name__}) - trying next model")
        if last_error:
            raise last_error
        return SimpleNamespace(text="")


def build_model(system_instruction: str | None = None) -> OpenRouterModel | None:
    """Return a ready model, or None when no key / SDK is available."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key or OpenAI is None:
        return None
    configured = [m.strip() for m in os.getenv("OPENROUTER_MODEL", "").split(",") if m.strip()]
    return OpenRouterModel(api_key, configured or None, system_instruction)
