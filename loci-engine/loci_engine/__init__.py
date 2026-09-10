from loci_engine import store
from loci_engine.db import open_db


class LociEngine:
    def __init__(self, path: str):
        self._conn = open_db(path)

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
        source: str | None = None,
    ) -> int:
        return store.add_fact(self._conn, entity, key, value, unit=unit, source=source)

    def get_facts(self, entity: str, key: str | None = None) -> list[dict]:
        return store.get_facts(self._conn, entity, key=key)

    def close(self) -> None:
        self._conn.close()
