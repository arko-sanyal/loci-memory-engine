import chromadb

from rag import config


class LociEngine:
    def __init__(
        self,
        path: str = config.CHROMA_DB_PATH,
        collection_name: str = config.COLLECTION_NAME,
    ):
        client = chromadb.PersistentClient(path=path)
        self._collection = client.get_or_create_collection(collection_name)

    def add(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        texts: list[str],
        metadatas: list[dict],
    ) -> None:
        self._collection.upsert(
            ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas
        )

    def query(self, embedding: list[float], top_k: int = 5) -> list[dict]:
        results = self._collection.query(
            query_embeddings=[embedding], n_results=top_k
        )
        return [
            {"id": id_, "text": text, "metadata": metadata, "distance": distance}
            for id_, text, metadata, distance in zip(
                results["ids"][0],
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            )
        ]
