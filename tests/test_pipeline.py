import pytest

from rag import config
from rag.pipeline import ingest, query

try:
    import ollama as _ollama_client

    _ollama_client.Client(host=config.OLLAMA_HOST).list()
    OLLAMA_AVAILABLE = True
except Exception:
    OLLAMA_AVAILABLE = False

requires_ollama = pytest.mark.skipif(
    not OLLAMA_AVAILABLE, reason="Ollama is not reachable at RAG_OLLAMA_HOST"
)


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHROMA_DB_PATH", str(tmp_path / "chroma"))
    return tmp_path


@requires_ollama
def test_ingest_returns_number_of_chunks_added(isolated_store):
    data_dir = isolated_store / "data"
    data_dir.mkdir()
    (data_dir / "note.txt").write_text("The sky is blue on a clear day.")

    count = ingest(str(data_dir))

    assert count == 1


@requires_ollama
def test_ingest_is_idempotent_on_rerun(isolated_store):
    data_dir = isolated_store / "data"
    data_dir.mkdir()
    (data_dir / "note.txt").write_text("The sky is blue on a clear day.")

    ingest(str(data_dir))
    second_count = ingest(str(data_dir))

    from rag.embeddings import embed
    from rag.loci import LociEngine

    engine = LociEngine(path=config.CHROMA_DB_PATH)
    [query_vector] = embed(["sky"])
    results = engine.query(query_vector, top_k=10)

    assert second_count == 1
    assert len(results) == 1


@requires_ollama
def test_query_returns_answer_and_sources(isolated_store):
    data_dir = isolated_store / "data"
    data_dir.mkdir()
    note = data_dir / "note.txt"
    note.write_text("The sky is blue on a clear day.")
    ingest(str(data_dir))

    result = query("What color is the sky?")

    assert isinstance(result["answer"], str)
    assert len(result["answer"]) > 0
    assert str(note) in result["sources"]
