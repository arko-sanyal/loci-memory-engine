import json

from loci_engine.vectors import VectorStore


def test_add_then_query_returns_closest_dense_match_first(tmp_path):
    store = VectorStore(str(tmp_path / "loci.db"))
    store.add(
        ids=["a", "b"],
        embeddings=[[1.0] + [0.0] * 767, [0.0, 1.0] + [0.0] * 766],
        texts=["points right", "points up"],
        metadatas=[{"source": "a.txt"}, {"source": "b.txt"}],
    )

    results = store.query(embedding=[0.9, 0.1] + [0.0] * 766, top_k=1)

    assert results[0]["id"] == "a"
    assert results[0]["text"] == "points right"
    assert results[0]["metadata"] == {"source": "a.txt"}


def test_add_with_same_id_updates_instead_of_duplicating(tmp_path):
    store = VectorStore(str(tmp_path / "loci.db"))
    store.add(
        ids=["a"],
        embeddings=[[1.0] + [0.0] * 767],
        texts=["original text"],
        metadatas=[{"source": "a.txt"}],
    )

    store.add(
        ids=["a"],
        embeddings=[[1.0] + [0.0] * 767],
        texts=["updated text"],
        metadatas=[{"source": "a.txt"}],
    )

    results = store.query(embedding=[1.0] + [0.0] * 767, top_k=10)

    assert len(results) == 1
    assert results[0]["text"] == "updated text"


def test_fts5_lexical_match_surfaces_a_result_with_no_dense_neighbor(tmp_path):
    store = VectorStore(str(tmp_path / "loci.db"))
    # "lexical" embedding is orthogonal/far from the query embedding on purpose:
    # only the BM25 side should be able to find it.
    store.add(
        ids=["lexical"],
        embeddings=[[0.0, 0.0, 1.0] + [0.0] * 765],
        texts=["the quick brown fox jumps over the lazy dog"],
        metadatas=[{"source": "fox.txt"}],
    )

    results = store.query(
        embedding=[1.0] + [0.0] * 767,  # nowhere near the stored embedding
        top_k=5,
        query_text="quick brown fox",
    )

    assert any(r["id"] == "lexical" for r in results)


def test_query_without_query_text_still_works_dense_only(tmp_path):
    store = VectorStore(str(tmp_path / "loci.db"))
    store.add(
        ids=["a"],
        embeddings=[[1.0] + [0.0] * 767],
        texts=["points right"],
        metadatas=[{"source": "a.txt"}],
    )

    results = store.query(embedding=[1.0] + [0.0] * 767, top_k=5)

    assert results[0]["id"] == "a"


def test_query_text_with_punctuation_does_not_raise_fts5_syntax_error(tmp_path):
    # Raw natural-language questions contain characters (?, -, *, etc.) that are
    # significant to FTS5's own MATCH query syntax and raise
    # sqlite3.OperationalError: fts5: syntax error if passed through unescaped.
    store = VectorStore(str(tmp_path / "loci.db"))
    store.add(
        ids=["a"],
        embeddings=[[1.0] + [0.0] * 767],
        texts=["the sky is blue on a clear day"],
        metadatas=[{"source": "a.txt"}],
    )

    results = store.query(
        embedding=[1.0] + [0.0] * 767, top_k=5, query_text="What color is the sky?"
    )

    assert any(r["id"] == "a" for r in results)


def test_query_text_with_no_word_tokens_skips_the_sparse_arm(tmp_path):
    # A query_text with no \w tokens (e.g. just punctuation) must not raise and
    # must still return dense-only results.
    store = VectorStore(str(tmp_path / "loci.db"))
    store.add(
        ids=["a"],
        embeddings=[[1.0] + [0.0] * 767],
        texts=["points right"],
        metadatas=[{"source": "a.txt"}],
    )

    results = store.query(embedding=[1.0] + [0.0] * 767, top_k=5, query_text="???")

    assert results[0]["id"] == "a"
