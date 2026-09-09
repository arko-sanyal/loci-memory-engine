import os

OLLAMA_HOST = os.environ.get("RAG_OLLAMA_HOST", "http://127.0.0.1:11434")
EMBEDDING_MODEL = os.environ.get("RAG_EMBEDDING_MODEL", "nomic-embed-text")
LLM_MODEL = os.environ.get("RAG_LLM_MODEL", "llama3.2")
OLLAMA_CONNECT_TIMEOUT_SECONDS = float(
    os.environ.get("RAG_OLLAMA_CONNECT_TIMEOUT_SECONDS", "10")
)
CHROMA_DB_PATH = os.environ.get("RAG_CHROMA_DB_PATH", "./chroma_db")
COLLECTION_NAME = os.environ.get("RAG_COLLECTION_NAME", "documents")
