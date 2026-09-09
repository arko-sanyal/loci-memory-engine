import pytest

from rag import config
from rag.llm import generate

try:
    import ollama as _ollama_client

    _ollama_client.Client(
        host=config.OLLAMA_HOST, timeout=config.OLLAMA_CONNECT_TIMEOUT_SECONDS
    ).list()
    OLLAMA_AVAILABLE = True
except Exception:
    OLLAMA_AVAILABLE = False

requires_ollama = pytest.mark.skipif(
    not OLLAMA_AVAILABLE, reason="Ollama is not reachable at RAG_OLLAMA_HOST"
)


@requires_ollama
def test_generate_returns_nonempty_answer():
    answer = generate("Reply with exactly one word: hello")

    assert isinstance(answer, str)
    assert len(answer.strip()) > 0


def test_generate_raises_clear_error_when_ollama_unreachable(monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_HOST", "http://127.0.0.1:1")
    monkeypatch.setattr(config, "OLLAMA_CONNECT_TIMEOUT_SECONDS", 1.0)

    with pytest.raises(ConnectionError, match="ollama serve"):
        generate("test")
