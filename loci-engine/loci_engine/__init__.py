from loci_engine import store
from loci_engine.db import open_db
from loci_engine.vectors import VectorStore


class LociEngine:
    def __init__(self, path: str):
        self._conn = open_db(path)
        self._vectors = VectorStore(path)

    def remember(
        self, entity: str, gist: str | None = None, expanded: str | None = None
    ) -> None:
        store.remember_entity(self._conn, entity, gist=gist, expanded=expanded)

    def recall(self, entity: str, hop: int = 0) -> dict | None:
        try:
            store.touch_entity(self._conn, entity, hop=hop)
        except KeyError:
            return None
        return store.get_entity(self._conn, entity)

    def add_fact(
        self,
        entity: str,
        key: str,
        value: str,
        unit: str | None = None,
        source=None,
        confidence: float = 1.0,
    ) -> dict:
        return store.add_fact(
            self._conn, entity, key, value, unit=unit, source=source, confidence=confidence
        )

    def get_facts(self, entity: str, key: str | None = None) -> list[dict]:
        return store.get_facts(self._conn, entity, key=key)

    def get_fact_history(self, entity: str, key: str) -> list[dict]:
        return store.get_fact_history(self._conn, entity, key)

    def add_chunk(
        self,
        chunk_id: str,
        embedding: list[float],
        text: str,
        metadata: dict | None = None,
    ) -> None:
        self._vectors.add([chunk_id], [embedding], [text], [metadata or {}])

    def query(
        self, embedding: list[float], top_k: int = 5, query_text: str | None = None
    ) -> list[dict]:
        return self._vectors.query(embedding, top_k=top_k, query_text=query_text)

    def close(self) -> None:
        self._conn.close()
        self._vectors.close()
