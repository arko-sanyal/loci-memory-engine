from rag.loci import LociEngine


def test_query_returns_closest_match_first(tmp_path):
    engine = LociEngine(path=str(tmp_path))
    engine.add(
        ids=["a", "b"],
        embeddings=[[1.0, 0.0], [0.0, 1.0]],
        texts=["points right", "points up"],
        metadatas=[{"source": "a.txt"}, {"source": "b.txt"}],
    )

    results = engine.query(embedding=[0.9, 0.1], top_k=1)

    assert results[0]["id"] == "a"
    assert results[0]["text"] == "points right"
    assert results[0]["metadata"] == {"source": "a.txt"}


def test_add_with_same_id_updates_instead_of_duplicating(tmp_path):
    engine = LociEngine(path=str(tmp_path))
    engine.add(
        ids=["a"],
        embeddings=[[1.0, 0.0]],
        texts=["original text"],
        metadatas=[{"source": "a.txt"}],
    )

    engine.add(
        ids=["a"],
        embeddings=[[1.0, 0.0]],
        texts=["updated text"],
        metadatas=[{"source": "a.txt"}],
    )

    results = engine.query(embedding=[1.0, 0.0], top_k=10)

    assert len(results) == 1
    assert results[0]["text"] == "updated text"
